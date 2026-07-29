"""
Agent 主入口 — create_sxdevops_agent()。

基于 DeepAgents 的 create_deep_agent() 构建 SxDevOps AIOps 智能体。

这替代了 services.py 中的 _dispatch_with_tool_runtime() 和整个 ReAct 循环。
"""

from __future__ import annotations

import html
import logging
import os
from typing import Optional

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.store.memory import InMemoryStore

from .checkpointer import DjangoCacheSaver, get_checkpointer
from .fastpath import fastpath_router
from .middleware import AuditMiddleware, RBACMiddleware
from .state import AIOpsAgentState
from .store import DjangoStore, get_store
from .system_prompt import build_system_prompt
from .tools import SXDEVOPS_TOOLS, get_tools_for_action

logger = logging.getLogger(__name__)

# Provider preset → 环境变量名映射
_PROVIDER_ENV_KEY_MAP = {
    'deepseek': 'DEEPSEEK_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'zhipu': 'ZHIPUAI_API_KEY',
    'google': 'GOOGLE_API_KEY',
}

# Provider preset → DeepAgents model string 映射
_PRESET_MODEL_MAP = {
    'anthropic': 'anthropic:',
    'openai': 'openai:',
    'deepseek': 'deepseek:',
    'zhipu': 'zhipuai:',
    'ollama': 'ollama:',
    'google': 'google_genai:',
}


def resolve_model_from_provider(user=None):
    """从 AIOpsModelProvider 读取活跃模型配置，返回 DeepAgents 可用的模型。

    返回格式: "provider:model_name" 字符串，或已配置 API key 的 BaseChatModel 实例。
    """
    # 优先使用环境变量
    env_model = os.environ.get('DEEPAGENTS_MODEL')
    if env_model:
        return env_model

    try:
        from aiops.models import AIOpsModelProvider

        provider = AIOpsModelProvider.objects.filter(is_enabled=True).first()
        if not provider:
            logger.warning("无活跃的 AIOpsModelProvider，使用默认模型")
            return _default_model()

        model_name = provider.default_model
        if not model_name:
            logger.warning("AIOpsModelProvider 未配置默认模型")
            return _default_model()

        preset = (provider.provider_preset or '').lower()

        # 解密 API key 并注入环境变量（LangChain 自动读取）
        api_key = ''
        if hasattr(provider, 'get_api_key'):
            try:
                api_key = provider.get_api_key() or ''
            except Exception as exc:
                logger.warning("API key 解密失败 (%s): %s，将以无 key 模式运行", preset, type(exc).__name__)
                api_key = ''
        if api_key:
            _inject_api_key(preset, api_key)
        else:
            logger.debug("未找到 %s 的 API key，依赖环境变量或已缓存的 key", preset)

        prefix = _PRESET_MODEL_MAP.get(preset, '')
        if prefix:
            return f"{prefix}{model_name}"
        return model_name
    except Exception as exc:
        logger.warning("解析模型配置失败: %s，使用默认模型", exc)
        return _default_model()


def _default_model() -> str:
    """当没有配置 AIOpsModelProvider 时的默认模型。"""
    return "anthropic:claude-sonnet-4-5-20250929"


def _inject_api_key(preset: str, api_key: str) -> None:
    """将 API key 注入环境变量（如果尚未设置）。"""
    env_key = _PROVIDER_ENV_KEY_MAP.get(preset)
    if not env_key:
        return
    if not os.environ.get(env_key):
        os.environ[env_key] = api_key
        logger.debug("已从 AIOpsModelProvider 注入 %s", env_key)


def create_sxdevops_agent(
    model: Optional[str] = None,
    knowledge_environment: Optional[dict] = None,
    analysis_scope: Optional[dict] = None,
    user=None,
    session_id: Optional[int] = None,
    assistant_message_id: Optional[int] = None,
    action_code: Optional[str] = None,
    enable_subagents: bool = True,
    enable_audit: bool = True,
    enable_rbac: bool = True,
    enable_persistence: bool = True,
    enable_summarization: bool = True,
) -> StateGraph:
    """创建 SxDevOps AIOps DeepAgent。

    Args:
        model: 模型字符串 ("provider:model")，None 则自动从 AIOpsModelProvider 解析
        knowledge_environment: 当前知识环境信息
        analysis_scope: 分析范围 (主机/服务/告警源列表)
        user: Django User 实例
        session_id: AIOpsChatSession ID
        assistant_message_id: AIOpsChatMessage ID (用于审计追踪)
        action_code: 当前 action 代码 (用于工具子集过滤)
        enable_subagents: 是否启用 SubAgent
        enable_audit: 是否启用审计中间件
        enable_rbac: 是否启用 RBAC 中间件
        enable_persistence: 是否启用持久化 checkpointer + store
        enable_summarization: 是否启用上下文摘要（长会话自动压缩）

    Returns:
        编译后的 LangGraph StateGraph，可调用 .invoke() 或 .astream()
    """
    if model is None:
        model = resolve_model_from_provider(user=user)

    # 构建 system prompt
    user_permissions = (
        list(user.get_all_permissions())
        if user and hasattr(user, 'get_all_permissions')
        else []
    )
    system_prompt = build_system_prompt(
        knowledge_environment or {},
        analysis_scope or {},
        user_permissions,
    )

    # 按 action 过滤工具
    if action_code:
        tools = get_tools_for_action(action_code)
    else:
        tools = SXDEVOPS_TOOLS

    # 构建中间件
    middleware = []
    if enable_rbac and user:
        middleware.append(RBACMiddleware(user=user))
    if enable_audit and session_id:
        middleware.append(
            AuditMiddleware(
                session_id=session_id,
                message_id=assistant_message_id,
            )
        )
    # SummarizationMiddleware 是 DeepAgents 内置中间件，
    # 默认在 ~170k tokens 时自动触发，无需显式添加

    # 构建 SubAgent 列表
    subagents = []
    if enable_subagents and action_code:
        from .subagents import get_subagents_for_action

        subagent_specs = get_subagents_for_action(action_code)
        for spec in subagent_specs:
            subagents.append({
                "name": spec["name"],
                "description": spec["description"],
                "prompt": spec["prompt"],
                "tools": [
                    t for t in tools
                    if t.name in spec.get("tools", [])
                ],
                "model": spec.get("model"),  # None = 继承主 agent
                "max_iterations": spec.get("max_iterations", 3),
            })

    # 持久化层
    # DeepAgents 使用内置 MemorySaver + InMemoryStore 管理 Agent 状态
    # DjangoStore 作为补充层，用于工具结果缓存和跨会话用户偏好
    checkpointer = MemorySaver()
    store = InMemoryStore()

    if enable_persistence and session_id:
        try:
            _ = get_store()  # 预热 DjangoStore 连接
            logger.debug("DjangoStore 就绪 (session=%s)", session_id)
        except Exception as exc:
            logger.debug("DjangoStore 初始化跳过: %s", exc)

    # 创建 DeepAgent
    agent = create_deep_agent(
        name="sxdevops-aiops",
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        subagents=subagents if subagents else None,
        middleware=middleware if middleware else None,
        checkpointer=checkpointer,
        store=store,
    )

    logger.info(
        "创建 SxDevOps DeepAgent: model=%s, tools=%d, subagents=%d, "
        "middleware: rbac=%s, audit=%s, persistence=%s, summarization=%s",
        model, len(tools), len(subagents),
        enable_rbac, enable_audit, enable_persistence, enable_summarization,
    )

    return agent


def _resolve_env_and_scope(session, question: str) -> tuple[dict, dict]:
    """解析知识环境和分析范围（复用 services.py 中的实现）。"""
    from aiops.business.environment import (
        _build_analysis_scope,
        _resolve_chat_environment,
    )

    env_resolution = _resolve_chat_environment(session, question)
    if env_resolution.get('status') != 'resolved':
        raise EnvironmentError(
            f"环境未确认: {env_resolution.get('message', '未知错误')}"
        )

    knowledge_environment = env_resolution['environment']
    analysis_scope = _build_analysis_scope(knowledge_environment)
    return knowledge_environment, analysis_scope


def _format_agent_output(result: dict) -> str:
    """根据 agent state 中的结构化输出，构建前端兼容的消息内容。"""
    def _safe(val) -> str:
        """转义 HTML 特殊字符，防止 Markdown 注入。"""
        return html.escape(str(val))

    parts = []

    conclusion = result.get('conclusion', '')
    if conclusion:
        parts.append(f"## 结论\n{_safe(conclusion)}")

    evidence = result.get('evidence_items', [])
    if evidence:
        parts.append("## 关键证据")
        for i, item in enumerate(evidence, 1):
            title = item.get('title', f'证据 {i}')
            value = item.get('value', '')
            source = item.get('source', '')
            parts.append(f"{i}. **{_safe(title)}**: {_safe(value)}")
            if source:
                parts.append(f"   _(来源: {_safe(source)})_")

    risks = result.get('risk_items', [])
    if risks:
        parts.append("## 风险评估")
        for risk in risks:
            level = _safe(risk.get('level', 'info'))
            desc = _safe(risk.get('description', ''))
            parts.append(f"- [{level.upper()}] {desc}")

    actions = result.get('suggested_actions', [])
    if actions:
        parts.append("## 建议动作")
        for action in actions:
            parts.append(f"- {_safe(action)}")

    return '\n\n'.join(parts) if parts else '分析完成，但未产生结构化输出。'
