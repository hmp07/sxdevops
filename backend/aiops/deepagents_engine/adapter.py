"""
适配层 — 将 DeepAgents agent.invoke() 结果映射为现有 AIOpsChatMessage 格式。

保持 views.py 的 send_message / send_message_async 接口零改动。
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
from typing import Optional

from django.db import close_old_connections
from django.utils import timezone

from aiops.models import (
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsPendingAction,
)

logger = logging.getLogger(__name__)

# ── 外部 MCP 会话追踪（用于请求结束后的资源清理） ──
_managed_mcp_sessions: list = []


def dispatch_chat_deepagents(
    session: AIOpsChatSession,
    user_message: AIOpsChatMessage,
    user,
    question: str,
    analysis_only: bool = False,
    assistant_message: AIOpsChatMessage = None,   # ★ 可选：复用已有消息
) -> tuple[AIOpsChatMessage, Optional[AIOpsPendingAction]]:
    """
    DeepAgents 版本的 dispatch_chat。

    如果调用方已创建 assistant_message（如 async worker），传入后复用，
    不再重复创建 DB 记录。否则自动创建新消息。

    返回 (assistant_message, pending_action) 元组。
    """
    from .agent import (
        create_sxdevops_agent,
        _resolve_env_and_scope,
        _format_agent_output,
    )

    # 1. 解析环境
    try:
        knowledge_environment, analysis_scope = _resolve_env_and_scope(
            session, question
        )
    except EnvironmentError as exc:
        return _build_env_error_response(session, str(exc))

    # 1.5 加载配置、Skill、MCP、Preflight ─────────────────────────────
    from aiops.services import (
        get_agent_config,
        get_active_provider,
        _get_selected_mcp_servers,
    )

    config = get_agent_config()
    provider = get_active_provider(config)

    # -- 模型可用性检查 --
    try:
        from aiops.services import _provider_is_ready
        provider_ready = _provider_is_ready(provider)
    except Exception:
        provider_ready = bool(provider)
    if not provider_ready:
        logger.warning("无可用 AIOpsModelProvider")
        return _build_no_model_response(session)

    # -- Skill 加载 --
    from .skills import load_active_skills, build_skill_trace

    active_skills = load_active_skills(config=config, action_code=None, user=user)

    # -- 外部 MCP 加载 --
    external_tools = []
    mcp_registry = {}
    mcp_diagnostics = []
    global _managed_mcp_sessions

    try:
        active_mcp_servers = _get_selected_mcp_servers(config)
        from .mcp_tools import build_external_mcp_tools

        external_tools, mcp_registry, mcp_sessions, mcp_diagnostics = (
            build_external_mcp_tools(active_mcp_servers, user=user)
        )
        _managed_mcp_sessions = mcp_sessions
    except ImportError:
        logger.debug("mcp_tools 模块不可用，跳过外部 MCP 加载")
    except Exception as exc:
        logger.warning("外部 MCP 加载失败: %s", type(exc).__name__)
        logger.debug("MCP 加载异常详情", exc_info=True)

    # -- analysis_only 工具过滤 --
    analysis_only_filtered_tools = None  # 稍后在 agent 创建时使用

    # 2. 创建或复用 assistant message
    if assistant_message is None:
        assistant_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            message_type=AIOpsChatMessage.TYPE_ANALYSIS,
            content='正在分析平台数据...',
            metadata={
                'processing_status': 'running',
                'engine': 'deepagents',
                'processing_steps': [{
                    'title': '初始化',
                    'detail': '已确认环境，正在启动 DeepAgents 引擎',
                    'status': 'completed',
                    'timestamp': timezone.now().isoformat(),
                }],
                'tool_events': [],
            },
        )
    else:
        # 复用已有消息，更新为 running 状态
        existing_meta = dict(assistant_message.metadata or {})
        assistant_message.content = '正在分析平台数据...'
        assistant_message.message_type = AIOpsChatMessage.TYPE_ANALYSIS
        assistant_message.metadata = {
            **existing_meta,
            'processing_status': 'running',
            'engine': 'deepagents',
            'processing_steps': (existing_meta.get('processing_steps') or []) + [{
                'title': '初始化',
                'detail': '已确认环境，正在启动 DeepAgents 引擎',
                'status': 'running',
                'timestamp': timezone.now().isoformat(),
            }],
            'tool_events': existing_meta.get('tool_events', []),
        }
        assistant_message.save(update_fields=['content', 'message_type', 'metadata'])

    # 3. 构建 initial state
    page_context = (
        session.context.get('page_context')
        if isinstance(session.context, dict)
        else None
    )

    initial_messages = [{
        'role': 'user',
        'content': (
            f"[环境: {knowledge_environment.get('name')}] {question}"
        ),
    }]

    config = {
        'configurable': {
            'thread_id': f'session-{session.id}',
            'user_id': user.id,
            'session_id': session.id,
            'assistant_message_id': assistant_message.id,
        }
    }

    # 4. 执行快速路径检查
    from .fastpath import fastpath_router

    fastpath_tool, fastpath_params = fastpath_router(question)
    fastpath_result = None

    if fastpath_tool:
        from .tools import get_tool_by_name

        tool = get_tool_by_name(fastpath_tool)
        if tool:
            try:
                logger.info(
                    "Fastpath hit: tool=%s session_id=%s",
                    fastpath_tool, session.id,
                )
                fastpath_result = tool.invoke(fastpath_params or {}, config=config)
            except Exception as exc:
                logger.warning("Fastpath 执行失败 (%s): %s", fastpath_tool, type(exc).__name__)
                logger.debug("Fastpath 异常详情 (%s)", fastpath_tool, exc_info=True)
                # 失败时 fall through 到 LLM
                fastpath_result = None

    # 5. 选择 action（用于工具子集过滤）+ 按 action 过滤 Skill
    from aiops.business.routing import _select_action_for_question

    selected_action = _select_action_for_question(
        question, user=user, analysis_scope=analysis_scope
    )
    action_code = (
        selected_action.get('code') if selected_action else None
    )

    # 按 action 重新过滤 Skill（对齐 _skills_for_action）
    if action_code:
        active_skills = load_active_skills(
            config=config, action_code=action_code, user=user
        )

    # 解析 Agent 执行模式
    agent_mode = _resolve_agent_mode(action_code)

    # -- analysis_only 工具过滤 --
    all_tools_for_agent = None  # None = 使用 agent.py 内部的默认过滤

    # 6. 创建 agent 并执行
    agent = create_sxdevops_agent(
        model=None,  # 自动从 AIOpsModelProvider 解析
        knowledge_environment=knowledge_environment,
        analysis_scope=analysis_scope,
        user=user,
        session_id=session.id,
        assistant_message_id=assistant_message.id,
        action_code=action_code,
        active_skills=active_skills,
        external_tools=external_tools if external_tools else None,
        mcp_diagnostics=mcp_diagnostics,
        agent_mode=agent_mode,
    )

    start_time = time.time()

    try:
        # analysis_only: 注入约束消息
        if analysis_only:
            initial_messages.append({
                'role': 'user',
                'content': (
                    '约束：本轮为只分析模式，只能做查询、分析、解释和建议；'
                    '禁止生成、创建、新建、安排待执行任务，禁止调用 generate_host_task 或任何写入操作。'
                ),
            })

        # Fastpath 预取数据，但始终通过 LLM 格式化输出
        # （直接返回原始 JSON 会跳过 system prompt 中的所有格式规则）
        effective_messages = initial_messages
        if fastpath_result:
            # 将预取的 fastpath 数据作为额外上下文注入用户问题
            effective_messages = [{
                'role': 'user',
                'content': (
                    f'问题：{question}\n\n'
                    f'（系统已通过 {fastpath_tool} 预取到以下数据，'
                    f'请直接基于这些数据回答，不要再调用工具。）\n\n'
                    f'{fastpath_result}'
                ),
            }]
        close_old_connections()
        result = agent.invoke(
            {'messages': effective_messages},
            config=config,
        )
        tool_calls_data = _extract_tool_calls(result)
    except Exception as exc:
        logger.exception("DeepAgents agent.invoke() 异常")
        elapsed = time.time() - start_time

        # 清理 MCP 会话
        _close_managed_mcp_sessions()

        # 回退到 legacy 引擎
        if os.environ.get('DEEPAGENTS_FALLBACK_ON_ERROR', 'true').lower() == 'true':
            logger.warning("回退到 legacy 引擎: %s", type(exc).__name__)
            logger.debug("Legacy fallback 异常详情", exc_info=True)
            from aiops.services import dispatch_chat as legacy_dispatch

            return legacy_dispatch(
                session, user_message, user, question, analysis_only
            )

        # 不回退：构建用户友好的错误消息（不暴露内部异常细节）
        assistant_message.content = '分析过程出错，请稍后重试或联系管理员。'
        assistant_message.metadata = {
            'processing_status': 'failed',
            'engine': 'deepagents',
            'error': type(exc).__name__,  # 仅记录异常类名，不泄露消息内容
            'elapsed_seconds': round(elapsed, 2),
        }
        assistant_message.save(update_fields=['content', 'metadata'])
        return assistant_message, None
    finally:
        # 正常路径也清理 MCP 会话
        _close_managed_mcp_sessions()

    elapsed = time.time() - start_time

    # 7. 提取最终内容
    final_content = _extract_final_content(result)
    if not final_content:
        final_content = _format_agent_output(result)

    # 8. 更新 assistant_message — 保留已有 processing_steps，合并最终状态
    existing_meta = dict(assistant_message.metadata or {})
    tc_data = tool_calls_data if 'tool_calls_data' in dir() else []
    tc_count = len(tc_data)
    tc_names = [item.get('name', '') for item in tc_data]

    # 构建 skill_trace
    skill_trace = build_skill_trace(
        active_skills,
        action_code=action_code or '',
        tool_calls=tc_names,
    )

    assistant_message.content = final_content
    assistant_message.tool_calls = tc_data
    assistant_message.metadata = {
        **existing_meta,
        'processing_status': 'completed',
        'processing_text': f'分析完成，耗时 {round(elapsed, 1)}s',
        'engine': 'deepagents',
        'action_code': action_code,
        'agent_mode': agent_mode,
        'fastpath': fastpath_tool if fastpath_result else None,
        'elapsed_seconds': round(elapsed, 2),
        'tool_count': tc_count,
        'skill_trace': skill_trace,
        'skill_count': len(active_skills),
        'mcp_diagnostics': mcp_diagnostics,
        'external_tool_count': len(external_tools) if external_tools else 0,
        'analysis_only': analysis_only,
        'processing_steps': (existing_meta.get('processing_steps') or []) + [{
            'title': '分析完成',
            'detail': f'DeepAgents 引擎完成，耗时 {round(elapsed, 1)}s，调用 {tc_count} 个工具',
            'status': 'completed',
            'timestamp': timezone.now().isoformat(),
        }],
    }
    assistant_message.save()

    # 8.5 更新 session 审计信息 (last_message_at + title)
    from aiops.services import _touch_chat_session
    _touch_chat_session(session, question)

    # 9. 处理 pending actions（含 analysis_only/config 策略交互）
    action_block_reason = None
    if not getattr(config, 'allow_action_execution', True):
        action_block_reason = 'execution_disabled'
    elif analysis_only:
        action_block_reason = 'analysis_only'

    pending_action = _process_pending_actions(
        result, session, assistant_message, user,
        block_reason=action_block_reason,
    )

    logger.info(
        f"DeepAgents dispatch 完成: elapsed={elapsed:.1f}s, "
        f"action={action_code}, fastpath={bool(fastpath_result)}"
    )

    return assistant_message, pending_action


def _extract_final_content(result: dict) -> str:
    """从 agent result 中提取最终 AI 消息内容。"""
    messages = result.get('messages', [])
    # 从后往前找最后一条 AI 消息
    for msg in reversed(messages):
        if hasattr(msg, 'type') and msg.type == 'ai':
            content = getattr(msg, 'content', '')
            if content:
                return content
        elif hasattr(msg, 'content'):
            if isinstance(msg, dict) and msg.get('role') == 'assistant':
                return msg.get('content', '')
    return ''


def _extract_tool_calls(result: dict) -> list[dict]:
    """从 agent result 中提取工具调用记录。"""
    tool_calls = []
    messages = result.get('messages', [])
    for msg in messages:
        if hasattr(msg, 'type') and msg.type == 'tool':
            tool_calls.append({
                'name': getattr(msg, 'name', 'unknown'),
                'content': str(getattr(msg, 'content', ''))[:500],
            })
        elif isinstance(msg, dict) and msg.get('role') == 'tool':
            tool_calls.append({
                'name': msg.get('name', 'unknown'),
                'content': str(msg.get('content', ''))[:500],
            })
    return tool_calls


def _process_pending_actions(
    result: dict,
    session: AIOpsChatSession,
    assistant_message: AIOpsChatMessage,
    user,
    block_reason: str | None = None,
) -> Optional[AIOpsPendingAction]:
    """检查 agent 结果中是否有待确认动作。

    Args:
        block_reason: 如果非 None，pending action 被标记为 blocked
                      ('analysis_only' | 'execution_disabled')
    """
    pending_actions = result.get('pending_actions', [])
    if not pending_actions:
        return None

    try:
        pa = pending_actions[0]
        status = AIOpsPendingAction.STATUS_PENDING
        payload = dict(pa.get('payload', {}))

        if block_reason:
            payload['_block_reason'] = block_reason

        return AIOpsPendingAction.objects.create(
            session=session,
            message=assistant_message,
            user=user,
            action_type=pa.get('type', 'unknown'),
            title=pa.get('title', ''),
            risk_level=pa.get('risk_level', AIOpsPendingAction.RISK_LOW),
            action_payload=payload,
            status=status,
        )
    except Exception as exc:
        logger.warning("创建 PendingAction 失败: %s", type(exc).__name__)
        return None


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _close_managed_mcp_sessions() -> None:
    """关闭所有外部 MCP 会话，释放资源。"""
    global _managed_mcp_sessions
    for session_obj in _managed_mcp_sessions:
        try:
            session_obj.close()
        except Exception:
            pass
    _managed_mcp_sessions = []


def _resolve_agent_mode(action_code: str | None) -> str:
    """从 action registry 获取 agent_mode，默认 'react'。

    对齐 legacy BUILTIN_ACTION_REGISTRY 中的 agent_mode 字段。
    """
    if not action_code:
        return 'react'
    try:
        from aiops.services import _action_registry_item_by_code
        action = _action_registry_item_by_code(action_code, user=None)
        if action:
            return action.get('agent_mode', 'react')
    except Exception:
        pass
    return 'react'


# ── P1.1: SSE 流式输出 ─────────────────────────────────────────────────


async def dispatch_chat_deepagents_stream(session, user_message, user, question):
    """DeepAgents 流式版本 — async generator，逐块产出 SSE 事件 dict。

    使用 agent.astream() 替代 agent.invoke()，实时产出 token/tool_call/step/done。
    前端通过 SSE (text/event-stream) 接收事件。

    事件类型：
      token      — LLM 输出的单个文本块
      tool_start — 工具调用开始
      tool_end   — 工具调用结束（含结果摘要）
      step       — 处理步骤更新
      done       — 完成（含最终 metadata 和 assistant_message_id）
      error      — 错误
    """
    from .agent import create_sxdevops_agent, _resolve_env_and_scope

    # 1. 解析环境
    try:
        knowledge_environment, analysis_scope = _resolve_env_and_scope(
            session, question
        )
    except EnvironmentError as exc:
        yield {'type': 'error', 'message': str(exc)}
        return

    # 2. 创建 assistant message（占位）
    from aiops.models import AIOpsChatMessage

    assistant_message = await _async_create_message(
        session.id, AIOpsChatMessage.ROLE_ASSISTANT,
        '', AIOpsChatMessage.TYPE_ANALYSIS,
        {'processing_status': 'running', 'engine': 'deepagents'},
    )

    # 2.5 加载配置、Skill、MCP
    from aiops.services import get_agent_config, _get_selected_mcp_servers
    from .skills import load_active_skills

    config = get_agent_config()
    active_skills = load_active_skills(config=config, action_code=None, user=user)

    external_tools = []
    mcp_diagnostics = []
    try:
        active_mcp_servers = _get_selected_mcp_servers(config)
        from .mcp_tools import build_external_mcp_tools
        external_tools, _reg, _sessions, mcp_diagnostics = build_external_mcp_tools(
            active_mcp_servers, user=user
        )
    except Exception as exc:
        logger.debug("Stream MCP 加载跳过: %s", type(exc).__name__)

    # 3. Fastpath 检查 — 命中则预取数据，但仍走 LLM 格式化
    from .fastpath import fastpath_router

    fastpath_tool, fastpath_params = fastpath_router(question)
    fastpath_data = None
    if fastpath_tool:
        from .tools import get_tool_by_name

        tool = get_tool_by_name(fastpath_tool)
        if tool:
            try:
                fastpath_data = tool.invoke(fastpath_params or {}, config={
                    'configurable': {'user_id': user.id, 'session_id': session.id}
                })
            except Exception as exc:
                logger.debug("Stream fastpath 失败: %s", type(exc).__name__)

    # 4. 构建格式化请求并走 agent.astream()
    if fastpath_data:
        # 将预取数据嵌入用户问题，让 LLM 按 system prompt 格式输出
        format_question = (
            f'问题：{question}\n\n'
            f'已通过 {fastpath_tool} 获取到原始数据，'
            f'请根据数据回答用户问题：\n\n{fastpath_data}'
        )
    else:
        format_question = question
    from aiops.business.routing import _select_action_for_question

    selected_action = _select_action_for_question(
        question, user=user, analysis_scope=analysis_scope
    )
    action_code = selected_action.get('code') if selected_action else None

    # 按 action 重新过滤 Skill
    if action_code:
        active_skills = load_active_skills(config=config, action_code=action_code, user=user)

    agent_mode = _resolve_agent_mode(action_code)

    agent = create_sxdevops_agent(
        model=None,
        knowledge_environment=knowledge_environment,
        analysis_scope=analysis_scope,
        user=user,
        session_id=session.id,
        assistant_message_id=assistant_message.id,
        action_code=action_code,
        active_skills=active_skills,
        external_tools=external_tools if external_tools else None,
        mcp_diagnostics=mcp_diagnostics,
        agent_mode=agent_mode,
    )

    config = {
        'configurable': {
            'thread_id': f'session-{session.id}',
            'user_id': user.id,
            'session_id': session.id,
            'assistant_message_id': assistant_message.id,
        }
    }

    full_content = ''
    tool_calls = []

    try:
        async for mode, events in agent.astream(
            {'messages': [{'role': 'user', 'content': format_question}]},
            config=config,
            stream_mode=['messages'],
        ):
            for event in events:
                msg = event.get('message') or event
                msg_type = getattr(msg, 'type', '')
                if msg_type == 'AIMessageChunk' or msg_type == 'ai':
                    content = getattr(msg, 'content', '')
                    if content:
                        full_content += content
                        yield {'type': 'token', 'content': content}
                elif msg_type == 'tool':
                    tool_name = getattr(msg, 'name', 'unknown')
                    tool_result = str(getattr(msg, 'content', ''))[:300]
                    tool_calls.append({'name': tool_name, 'summary': tool_result})
                    yield {'type': 'tool_end', 'name': tool_name, 'summary': tool_result}

        # 完成
        yield {
            'type': 'done',
            'message_id': assistant_message.id,
            'metadata': {
                'engine': 'deepagents',
                'processing_status': 'completed',
                'action_code': action_code,
                'tool_count': len(tool_calls),
            },
        }

        # 持久化最终结果
        await _async_update_message(
            assistant_message.id,
            content=full_content,
            tool_calls=tool_calls,
            metadata_update={'processing_status': 'completed', 'tool_count': len(tool_calls)},
        )

    except Exception as exc:
        logger.exception("Stream agent.astream() 异常")
        yield {'type': 'error', 'message': type(exc).__name__}
        await _async_update_message(
            assistant_message.id,
            metadata_update={'processing_status': 'failed', 'error': type(exc).__name__},
        )


# ── Async Django ORM helpers ────────────────────────────────────────────

from asgiref.sync import sync_to_async


@sync_to_async
def _async_create_message(session_id, role, content, message_type, metadata):
    from aiops.models import AIOpsChatMessage
    from django.db import close_old_connections
    close_old_connections()
    return AIOpsChatMessage.objects.create(
        session_id=session_id, role=role, content=content,
        message_type=message_type, metadata=metadata,
    )


@sync_to_async
def _async_update_message(message_id, content=None, tool_calls=None, metadata_update=None):
    from aiops.models import AIOpsChatMessage
    from django.db import close_old_connections
    close_old_connections()
    msg = AIOpsChatMessage.objects.filter(id=message_id).first()
    if not msg:
        return
    if content is not None:
        msg.content = content
    if tool_calls is not None:
        msg.tool_calls = tool_calls
    if metadata_update:
        meta = dict(msg.metadata or {})
        meta.update(metadata_update)
        msg.metadata = meta
    msg.save()


def _build_env_error_response(
    session: AIOpsChatSession, error_message: str
) -> tuple[AIOpsChatMessage, None]:
    """构建环境解析失败的错误响应。"""
    msg = AIOpsChatMessage.objects.create(
        session=session,
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        message_type=AIOpsChatMessage.TYPE_TEXT,
        content=f'环境尚未确认，无法执行分析。\n\n{error_message}',
        metadata={
            'processing_status': 'failed',
            'engine': 'deepagents',
            'error': error_message,
        },
    )
    return msg, None


def _build_no_model_response(
    session: AIOpsChatSession,
) -> tuple[AIOpsChatMessage, None]:
    """构建无可用模型的错误响应。"""
    msg = AIOpsChatMessage.objects.create(
        session=session,
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        message_type=AIOpsChatMessage.TYPE_TEXT,
        content='当前没有可用的 AI 模型。请在 AIOps 配置中设置至少一个模型提供商。',
        metadata={
            'processing_status': 'failed',
            'engine': 'deepagents',
        },
    )
    return msg, None
