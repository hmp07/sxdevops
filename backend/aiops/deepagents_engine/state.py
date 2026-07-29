"""
AIOpsAgentState — DeepAgents LangGraph 状态定义。

替代 services.py 中分散的 session.ctx / analysis_scope / knowledge_environment
状态管理方式，将所有 Agent 运行时状态统一为一个 TypedDict。
"""

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AIOpsAgentState(TypedDict, total=False):
    """AIOps DeepAgent 全局状态。

    所有节点通过此 State 共享数据。LangGraph 的 add_messages reducer
    自动处理消息列表的追加。
    """

    # ---- 对话消息 (LangGraph 标准字段) ----
    messages: Annotated[list, add_messages]

    # ---- 环境与分析范围 (替代 _build_analysis_scope) ----
    knowledge_environment: dict
    analysis_scope: dict

    # ---- 用户与权限 ----
    user_id: int
    rbac_permissions: list[str]

    # ---- 会话元数据 ----
    session_id: int
    assistant_message_id: int
    page_context: Optional[dict]

    # ---- 快速路径 ----
    fastpath_match: Optional[dict]  # fastpath_router 匹配结果

    # ---- 工具调用追踪 (替代临时 debug 文件) ----
    tool_invocations: list[dict]

    # ---- Pending Action ----
    pending_actions: list[dict]
    requires_confirmation: bool

    # ---- 双阶段回答结构化输出 ----
    conclusion: Optional[str]
    evidence_items: list[dict]
    risk_items: list[dict]
    suggested_actions: list[dict]

    # ---- 处理状态 (前端轮询可见) ----
    processing_steps: list[dict]
    tool_events: list[dict]

    # ---- 模型调用统计 ----
    model_name: Optional[str]
    total_tokens_used: int
    model_call_count: int
