"""
自定义 DeepAgents 中间件。

替代 services.py 中的：
- _tool_allowed() — RBAC 权限检查
- _create_tool_invocation / _finish_tool_invocation — 审计日志
- Pending Action 确认机制

通过 DeepAgents 的 AgentMiddleware 接口实现，
挂载到 create_deep_agent() 的 middleware 参数。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)


from langchain.agents.middleware.types import AgentMiddleware


class RBACMiddleware(AgentMiddleware):
    """
    Django RBAC 权限门控中间件。

    在工具调用前检查用户是否有对应权限。
    替代 services.py 中的 _tool_allowed() 和 per-action allowed_tools 检查。

    用法：
        middleware=[RBACMiddleware(user=request.user)]
    """

    def __init__(self, user=None):
        self.user = user
        self._permissions: Optional[set] = None

    @property
    def permissions(self) -> set:
        if self._permissions is None:
            if self.user and hasattr(self.user, 'get_all_permissions'):
                close_old_connections()
                self._permissions = set(self.user.get_all_permissions())
            else:
                self._permissions = set()
        return self._permissions

    def _tool_name_to_permission(self, tool_name: str) -> Optional[str]:
        """将工具名映射到 Django permission code。"""
        from aiops.tools.registry import TOOL_REGISTRY

        # tool_name 格式: "query_alerts_tool" → handler "query_alerts"
        handler = tool_name.replace('_tool', '')
        for plat_tool in TOOL_REGISTRY:
            if plat_tool['handler'] == handler or plat_tool.get('deepagents_name') == tool_name:
                return plat_tool.get('permission')
        return None

    def check_tool_access(self, tool_name: str) -> bool:
        """检查用户是否有权使用指定工具。"""
        close_old_connections()
        # 超级用户始终放行
        if self.user and getattr(self.user, 'is_superuser', False):
            return True
        permission = self._tool_name_to_permission(tool_name)
        if not permission:
            return True  # 无权限要求的工具默认允许
        return permission in self.permissions

    def check_tool_access_or_raise(self, tool_name: str) -> None:
        """检查权限，失败时抛出 PermissionError。"""
        if not self.check_tool_access(tool_name):
            raise PermissionError(
                f"用户 {getattr(self.user, 'username', 'anonymous')} "
                f"缺少权限调用工具 {tool_name}"
            )

    def wrap_tool_call(self, request, handler):
        """AgentMiddleware hook — 每次工具调用前自动执行 RBAC 检查。"""
        tool_name = ''
        if hasattr(request, 'tool_call') and isinstance(request.tool_call, dict):
            tool_name = request.tool_call.get('name', '')
        elif hasattr(request, 'tool_name'):
            tool_name = request.tool_name
        if tool_name:
            self.check_tool_access_or_raise(tool_name)
        return handler(request)


class AuditMiddleware(AgentMiddleware):
    """工具调用 + 模型调用审计中间件。

    通过 AgentMiddleware hook 自动记录：
    - wrap_tool_call → AIOpsToolInvocation (每次工具调用)
    - wrap_model_call → AIOpsModelInvocation (每次 LLM 调用)

    替代 services.py 中分散的 _create_tool_invocation / _finish_tool_invocation /
    _record_model_invocation 调用。
    """

    def __init__(self, session_id: int = None, message_id: int = None, user=None):
        self.session_id = session_id
        self.message_id = message_id
        self.user = user

    # ── 工具调用审计 ─────────────────────────────────────────────────

    def _tool_name_from_request(self, request) -> str:
        if hasattr(request, 'tool_call') and isinstance(request.tool_call, dict):
            return request.tool_call.get('name', 'unknown')
        return 'unknown'

    def _tool_args_from_request(self, request) -> dict:
        if hasattr(request, 'tool_call') and isinstance(request.tool_call, dict):
            return request.tool_call.get('args', {})
        return {}

    def wrap_tool_call(self, request, handler):
        """AgentMiddleware hook — 拦截每次工具调用，创建审计记录。"""
        tool_name = self._tool_name_from_request(request)
        args = self._tool_args_from_request(request)
        started_at = time.time()

        # 执行工具调用
        try:
            result = handler(request)
            success = True
            error_msg = ''
        except Exception as exc:
            result = None
            success = False
            error_msg = str(exc)[:500]

        elapsed_ms = int((time.time() - started_at) * 1000)

        # 写入审计记录
        if self.session_id:
            try:
                close_old_connections()
                from aiops.models import AIOpsToolInvocation
                AIOpsToolInvocation.objects.create(
                    session_id=self.session_id,
                    message_id=self.message_id,
                    tool_name=tool_name,
                    status='success' if success else 'failed',
                    request_payload=args,
                    response_summary={'summary': str(result)[:500]} if result else {'error': error_msg},
                    latency_ms=elapsed_ms,
                )
            except Exception as exc:
                logger.warning("工具审计写入失败 (%s): %s", tool_name, exc)

        if not success:
            raise  # re-raise after audit

        return result

    # ── 模型调用审计 ─────────────────────────────────────────────────

    def after_model(self, state, runtime):
        """AgentMiddleware hook — LLM 调用完成后，从 state 提取 token 信息并审计。"""
        if not self.session_id:
            return
        try:
            # 从 state messages 中找最后一条 AI 消息的 response_metadata
            messages = state.get('messages', [])
            model_name = ''
            input_tokens = 0
            output_tokens = 0

            for msg in reversed(messages):
                if hasattr(msg, 'response_metadata') and msg.response_metadata:
                    rm = msg.response_metadata
                    model_name = rm.get('model_name', '')
                    usage = rm.get('token_usage', {}) or rm.get('usage', {})
                    input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                    output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                    if input_tokens or output_tokens:
                        break

            # 也从 usage_metadata 尝试
            if not input_tokens:
                for msg in reversed(messages):
                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                        um = msg.usage_metadata
                        input_tokens = um.get('input_tokens', 0)
                        output_tokens = um.get('output_tokens', 0)
                        break

            if model_name or input_tokens or output_tokens:
                close_old_connections()
                from aiops.models import AIOpsModelInvocation
                AIOpsModelInvocation.objects.create(
                    session_id=self.session_id,
                    message_id=self.message_id,
                    username=getattr(self.user, 'username', '') if self.user else '',
                    purpose='agent_llm_call',
                    requested_model=model_name or 'unknown',
                    resolved_model=model_name or 'unknown',
                    status='success',
                    prompt_tokens=input_tokens or 0,
                    completion_tokens=output_tokens or 0,
                    total_tokens=(input_tokens or 0) + (output_tokens or 0),
                )
                logger.debug("模型审计已记录: model=%s tokens=%d", model_name, (input_tokens or 0) + (output_tokens or 0))
        except Exception as exc:
            logger.warning("模型审计写入失败: %s", exc)


class PendingActionMiddleware(AgentMiddleware):
    """
    待确认动作中间件。

    当工具调用结果中包含 pending_action_draft 时，
    自动创建 AIOpsPendingAction 记录，标记为需要用户确认。

    替代 services.py 中的 pending_action_draft → AIOpsPendingAction 流程。
    """

    def __init__(self, session_id: int = None, message_id: int = None, user=None):
        self.session_id = session_id
        self.message_id = message_id
        self.user = user

    def process_pending_action(
        self, tool_name: str, result: Any
    ) -> Optional[int]:
        """检查工具结果中是否有待确认动作，有则创建记录。"""
        if not isinstance(result, dict):
            return None
        draft = result.get('pending_action_draft')
        if not draft:
            return None
        close_old_connections()
        from aiops.models import AIOpsPendingAction

        try:
            pending = AIOpsPendingAction.objects.create(
                session_id=self.session_id,
                message_id=self.message_id,
                user=self.user,
                action_type=tool_name,
                payload=draft,
                status=AIOpsPendingAction.STATUS_PENDING,
            )
            return pending.id
        except Exception as exc:
            logger.warning(f"创建待确认动作失败 ({tool_name}): {exc}")
            return None
