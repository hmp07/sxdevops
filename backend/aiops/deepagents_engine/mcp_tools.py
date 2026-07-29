"""
外部 MCP Server 工具构建模块。

从 AIOpsMCPServer 模型加载外部 MCP Server（HTTP/STDIO），
发现工具并包装为 LangChain @tool，供 DeepAgents Agent 使用。

复用 services.py 中的：
- _create_mcp_client_session(server)
- _discover_external_mcp_tools(server, client_session)
- _normalize_external_mcp_tool(server, tool)
- _build_mcp_tool_alias(server, raw_name)
"""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

from django.db import close_old_connections

logger = logging.getLogger(__name__)


def _safe_name_for_alias(name: str) -> str:
    """将 server 名转为安全的别名组件（字母数字 + 下划线）。"""
    import re
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', str(name or ''))
    return safe.strip('_') or 'mcp'


def _build_mcp_tool_alias(server, raw_tool_name: str) -> str:
    """构建 MCP 工具别名: mcp__{server_name}__{tool_name}。

    对齐 legacy services.py line 14820。
    """
    safe_server = _safe_name_for_alias(server.name)
    safe_tool = _safe_name_for_alias(raw_tool_name)
    return f'mcp__{safe_server}__{safe_tool}'


def build_external_mcp_tools(
    active_mcp_servers: list,
    user=None,
) -> tuple[list, dict, list, list]:
    """连接外部 MCP Server，发现工具，包装为 LangChain @tool。

    Args:
        active_mcp_servers: AIOpsMCPServer 实例列表
        user: Django User（预留，当前未使用）

    Returns:
        external_tools: LangChain Tool 列表（可与 SXDEVOPS_TOOLS 合并）
        registry: {tool_alias: {kind, server, session, raw_name}} 调用路由表
        managed_sessions: [client_session, ...] 需在请求结束后 close()
        diagnostics: [{'name':..., 'status':..., 'tool_count':..., 'server_type':...}, ...]
    """
    close_old_connections()

    from aiops.models import AIOpsMCPServer

    tool_specs: list = []
    registry: dict = {}
    managed_sessions: list = []
    diagnostics: list = []

    # 内置 MCP — 由 SXDEVOPS_TOOLS 覆盖，这里只做诊断
    builtin_servers = [
        s for s in active_mcp_servers
        if s.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN
    ]
    for server in builtin_servers:
        tool_names = server.tool_whitelist or []
        diagnostics.append({
            'name': server.name,
            'status': 'connected',
            'server_type': server.server_type,
            'tool_count': len(tool_names),
            'message': '',
        })

    # 外部 MCP — HTTP/STDIO
    external_servers = [
        s for s in active_mcp_servers
        if s.server_type != AIOpsMCPServer.SERVER_PLATFORM_BUILTIN
    ]

    for server in external_servers:
        try:
            # 复用 legacy 的 client session 创建
            from aiops.services import (
                _create_mcp_client_session,
                _discover_external_mcp_tools,
            )

            client_session = _create_mcp_client_session(server)
            client_session.initialize()
            external_tools_raw = _discover_external_mcp_tools(server, client_session)

            if external_tools_raw:
                managed_sessions.append(client_session)
            else:
                try:
                    client_session.close()
                except Exception:
                    pass

            diagnostics.append({
                'name': server.name,
                'status': 'connected',
                'server_type': server.server_type,
                'tool_count': len(external_tools_raw),
                'message': '',
            })

            # 包装为 LangChain @tool
            for raw_tool in external_tools_raw:
                raw_name = raw_tool.get('name', '')
                if not raw_name:
                    continue

                alias = _build_mcp_tool_alias(server, raw_name)
                description = raw_tool.get('description') or f'{server.name} / {raw_name}'
                input_schema = raw_tool.get('inputSchema') or {
                    'type': 'object', 'properties': {}
                }

                # 创建 @tool 包装
                external_tool = _make_external_mcp_tool(
                    server_name=server.name,
                    raw_name=raw_name,
                    alias=alias,
                    client_session=client_session,
                    description=description,
                    input_schema=input_schema,
                )
                tool_specs.append(external_tool)
                registry[alias] = {
                    'kind': 'external',
                    'server': server,
                    'session': client_session,
                    'raw_name': raw_name,
                }

        except Exception as exc:
            logger.warning("外部 MCP Server %s 连接失败: %s", server.name, type(exc).__name__)
            # 仅记录异常类名到诊断信息，不暴露 error message 内容
            # （诊断信息会注入 system prompt，可能被 LLM 提供商看到）
            diagnostics.append({
                'name': server.name,
                'status': 'failed',
                'server_type': server.server_type,
                'tool_count': 0,
                'message': f'连接失败 ({type(exc).__name__})',
            })

    logger.info(
        "外部 MCP 加载完成: %d 个工具, %d 个会话, %d 个 Server",
        len(tool_specs), len(managed_sessions),
        len([d for d in diagnostics if d['status'] == 'connected']),
    )
    return tool_specs, registry, managed_sessions, diagnostics


def _make_external_mcp_tool(
    server_name: str,
    raw_name: str,
    alias: str,
    client_session,
    description: str,
    input_schema: dict,
):
    """创建一个调用外部 MCP Server 的 LangChain @tool。

    工具被调用时，通过 client_session.call_tool(raw_name, args) 转发请求。
    """
    from langchain_core.tools import tool

    @tool(alias, description=description)
    def external_mcp_tool(**kwargs) -> str:
        """调用外部 MCP 工具。"""
        try:
            result = client_session.call_tool(raw_name, kwargs)
            if isinstance(result, dict) and 'content' in result:
                # MCP 标准响应格式
                content = result.get('content', [])
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            text_parts.append(str(item.get('text', '')))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    return '\n'.join(text_parts) if text_parts else str(result)
            return _json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            logger.warning("外部 MCP 工具 %s 调用失败: %s", alias, type(exc).__name__)
            # 仅返回异常类名给 LLM，不泄露内部错误详情
            return _json.dumps(
                {'error': type(exc).__name__,
                 'message': f'工具调用失败，请检查 MCP Server 连接状态或联系管理员。'},
                ensure_ascii=False,
            )

    # 尝试设置 args_schema（如果 LangChain 版本支持）
    try:
        from langchain_core.utils.pydantic import _create_subset_model
        external_mcp_tool.args_schema = _create_subset_model(
            alias, input_schema
        )
    except Exception:
        pass  # args_schema 不是必需的

    return external_mcp_tool
