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

        # 映射：tool_name → TOOL_REGISTRY handler
        handler = tool_name.replace('_tool', '').replace('_', '-')
        for plat_tool in TOOL_REGISTRY:
            if plat_tool['handler'] == handler:
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
    """
    工具调用审计中间件。

    每次工具调用后自动创建/更新 AIOpsToolInvocation 记录，
    替代 services.py 中分散的 _create_tool_invocation /
    _finish_tool_invocation 调用。

    用法：
        middleware=[AuditMiddleware(session_id=session.id)]
    """

    def __init__(self, session_id: int = None, message_id: int = None):
        self.session_id = session_id
        self.message_id = message_id
        self._invocations: dict[str, int] = {}  # tool_name → invocation_id

    def record_tool_start(self, tool_name: str, arguments: dict) -> Optional[int]:
        """工具调用开始 — 创建 AIOpsToolInvocation 记录。"""
        if not self.session_id:
            return None
        close_old_connections()
        from aiops.models import AIOpsToolInvocation

        try:
            invocation = AIOpsToolInvocation.objects.create(
                session_id=self.session_id,
                message_id=self.message_id,
                tool_name=tool_name,
                input_args=arguments,
                status='running',
                started_at=timezone.now(),
            )
            self._invocations[tool_name] = invocation.id
            return invocation.id
        except Exception as exc:
            logger.warning(f"创建工具审计记录失败 ({tool_name}): {exc}")
            return None

    def record_tool_end(
        self, tool_name: str, result: Any,
        success: bool = True, error: str = '',
    ) -> None:
        """工具调用结束 — 更新 AIOpsToolInvocation 记录。"""
        invocation_id = self._invocations.pop(tool_name, None)
        if not invocation_id:
            return
        close_old_connections()
        from aiops.models import AIOpsToolInvocation

        try:
            result_summary = (
                str(result)[:500] if result else ''
            )
            AIOpsToolInvocation.objects.filter(id=invocation_id).update(
                status='completed' if success else 'failed',
                output_result={'summary': result_summary, 'error': error},
                finished_at=timezone.now(),
            )
        except Exception as exc:
            logger.warning(f"更新工具审计记录失败 ({tool_name}): {exc}")


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
