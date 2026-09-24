"""
演示模式模拟模型引擎 — 离线 Demo 的确定性 LLM 替代品。

设计目标：
- SXDEVOPS_DEMO_MODE=1 时，用 DemoMockChatModel 驱动真实的 DeepAgents 循环：
  第一阶段发一个 tool_call（工具对种子数据真实执行），
  第二阶段用模板把工具结果格式化为二阶段结构化答案。
- Action Router / Skill / RBAC / 审计中间件 / 待确认动作全链路真实运转。
- flag 关闭时本模块不被导入，生产路径零影响。

工作流程（单轮问答）:
  1. agent.invoke(messages) → DemoMockChatModel._generate 收到 HumanMessage
     - fastpath 预取标记 → 直接进入第二阶段（基于内嵌数据回答）
     - 否则 → 路由选择工具 → 返回 AIMessage(tool_calls=[...])
  2. DeepAgents 执行工具 → ToolMessage 追加
  3. agent.invoke 再次调用 → _generate 收到 ToolMessage
     → 解析工具 JSON 结果 → 按模板渲染最终答案 → 返回纯文本 AIMessage

不变式：最多 2 次模型调用、每次只发一个工具计划。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

DEMO_MODEL_NAME = 'sxdevops-demo-mock'
FASTPATH_MARKER = '（系统已通过'
ACTION_GENERATING_MARKERS = ['巡检', '巡检任务', '生成任务', '批量执行']


def is_demo_mode() -> bool:
    """演示模式开关 — 每次调用实时读取，便于测试与容器注入。"""
    return os.environ.get('SXDEVOPS_DEMO_MODE') == '1'


def llm_demo_mock_enabled() -> bool:
    """LLM 离线模拟开关（唯一事实来源）。

    SXDEVOPS_LLM_DEMO_MOCK 显式设置时以其为准（1=模拟模型, 0=真实模型）；
    未设置时回落 SXDEVOPS_DEMO_MODE，保证默认行为与历史完全一致。
    演示环境接入真实大模型时设置 SXDEVOPS_LLM_DEMO_MOCK=0 即可，
    观测侧演示数据（指标/日志/链路/Zabbix）不受影响。
    """
    if 'SXDEVOPS_LLM_DEMO_MOCK' in os.environ:
        return os.environ['SXDEVOPS_LLM_DEMO_MOCK'] == '1'
    return os.environ.get('SXDEVOPS_DEMO_MODE') == '1'


class DemoMockChatModel(BaseChatModel):
    """确定性模拟模型 — 驱动真实 DeepAgents 工具循环。"""

    model_name: str = DEMO_MODEL_NAME

    # ── 需要实现的抽象接口 ──────────────────────────────────────────

    @property
    def _llm_type(self) -> str:
        return 'sxdevops-demo-mock'

    @property
    def _identifying_params(self) -> dict:
        return {'model_name': self.model_name}

    def _get_ls_params(self, **kwargs):
        try:
            return {
                'ls_provider': 'sxdevops_demo',
                'ls_model_name': self.model_name,
                'ls_model_type': 'chat',
            }
        except Exception:
            return {}

    def bind_tools(self, tools, **kwargs):
        """DeepAgents 在模型上绑定工具 — 存储 schema 供第一阶段使用。"""
        try:
            self._bound_tool_schemas = []
            for t in tools or []:
                name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                if name:
                    self._bound_tool_schemas.append(name)
        except Exception as exc:  # pragma: no cover
            logger.warning('bind_tools 存储 schema 失败: %s', type(exc).__name__)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        # 1. 确定当前阶段
        last = messages[-1] if messages else None
        last_role = getattr(last, 'type', '') if hasattr(last, 'type') else ''

        # 2. 用户问题文本（最近一条 human 消息），并剥离环境前缀
        question = ''
        for msg in reversed(messages):
            if getattr(msg, 'type', '') == 'human' or getattr(msg, 'role', '') == 'user':
                question = _strip_env_prefix(str(getattr(msg, 'content', '') or ''))
                break

        if last_role == 'tool':
            # 第二阶段：基于工具结果渲染答案
            content = self._format_answer_from_tool_result(last)
        elif FASTPATH_MARKER in question:
            # fastpath 预取：数据内嵌在问题里，直接格式化回答
            content = self._format_answer_from_embedded_data(question)
        else:
            # 第一阶段：选择工具并发起调用
            tool_name, tool_args, pending = self._build_tool_plan(question)
            if tool_name:
                if pending:
                    self._pending_plan = pending
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content='',
                    tool_calls=[{
                        'name': tool_name,
                        'args': tool_args,
                        'id': 'call_demo_1',
                        'type': 'tool_call',
                    }],
                    response_metadata=self._response_metadata(),
                ))])
            content = self._greeting_answer(question)

        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=content,
            response_metadata=self._response_metadata(),
        ))])

    # ── 响应元数据（支撑智能体审计页）────────────────────────────────

    def _response_metadata(self, output_chars: int = 0) -> dict:
        return {
            'model_name': self.model_name,
            'usage': {
                'input_tokens': 120,
                'output_tokens': max(40, output_chars // 2),
                'total_tokens': 120 + max(40, output_chars // 2),
            },
        }

    # ── 路由与计划 ──────────────────────────────────────────────────

    def _build_tool_plan(self, question: str) -> tuple[Optional[str], dict, Optional[dict]]:
        """选择工具与参数。返回 (tool_name, args, pending_plan)。"""
        from .fastpath import fastpath_router

        # 精确覆盖表优先 — 保证演示脚本逐字可复现
        override = DEMO_QUESTION_OVERRIDES.get(question.strip())
        if override:
            args = dict(override.get('args') or {})
            # 根因分析需指定告警 ID（按标题关键词动态解析，保证命中故事线告警）
            if override['tool'] == 'query_alert_root_cause_tool' and not args.get('alert_id'):
                alert_id = _resolve_alert_id_by_keywords(override.get('alert_keywords'))
                if alert_id:
                    args['alert_id'] = alert_id
            return override['tool'], args, override.get('pending')

        tool_name, params = fastpath_router(question)
        if tool_name:
            return tool_name, params or {}, None

        # action 路由兜底
        try:
            from aiops.business.routing import _select_action_for_question
            from .tools import get_tools_for_action

            action = _select_action_for_question(question, user=None, analysis_scope=None)
            code = (action or {}).get('code')
            if code:
                tools = get_tools_for_action(code)
                if tools:
                    preferred = self._preferred_tool_for_action(code)
                    tool_obj = tools[0]
                    for t in tools:
                        if getattr(t, 'name', '') == preferred:
                            tool_obj = t
                            break
                    tool_name = getattr(tool_obj, 'name', None) or str(tool_obj)
                    return (
                        tool_name,
                        self._args_for_tool(tool_name, question),
                        self._pending_for_question(question),
                    )
        except Exception as exc:
            logger.warning('action 路由失败: %s', type(exc).__name__)

        # 兜底：查询告警
        return 'query_alerts_tool', {'limit': 5}, None

    def _preferred_tool_for_action(self, code: str) -> Optional[str]:
        mapping = {
            'alert.root_cause': 'query_alert_root_cause_tool',
            'zabbix.problem_analysis': 'query_zabbix_problems_tool',
            'cmdb.query': 'query_cmdb_items_tool',
            'log.query_generate': 'query_logs_tool',
        }
        return mapping.get(code)

    def _args_for_tool(self, tool: str, question: str) -> dict:
        from .fastpath import _strip_noise
        query = _strip_noise(question)
        if tool == 'query_logs_tool':
            return {'query': query, 'limit': 20}
        if tool == 'query_zabbix_problems_tool':
            return {'min_severity': 3, 'limit': 50}
        if tool == 'query_cmdb_items_tool':
            return {'query': query, 'limit': 6}
        if tool == 'query_zabbix_hosts_tool':
            return {'search': query or '', 'limit': 50}
        return {'query': query, 'limit': 10}

    def _pending_for_question(self, question: str) -> Optional[dict]:
        if any(m in question for m in ACTION_GENERATING_MARKERS):
            return build_demo_task_pending_plan(question)
        return None

    # ── 答案渲染 ────────────────────────────────────────────────────

    def _format_answer_from_tool_result(self, tool_msg: BaseMessage) -> str:
        tool_name = getattr(tool_msg, 'name', 'unknown')
        raw = getattr(tool_msg, 'content', '') or ''
        data = _parse_tool_json(raw)
        plan = getattr(self, '_pending_plan', None)
        return render_answer(tool_name, data, pending_plan=plan)

    def _format_answer_from_embedded_data(self, question: str) -> str:
        # fastpath 预取数据内嵌在问题文本中：`（系统已通过 X 预取到以下数据...）\n\n{json}`
        idx = question.find(FASTPATH_MARKER)
        header = question[:idx].strip()
        body = question[idx:]
        # 提取预取工具名
        import re
        m = re.search(r'通过\s+(\S+?)\s+预取', body)
        tool_name = m.group(1) if m else ''
        # 提取 JSON 数据（标记说明之后的部分）
        json_start = body.find('\n\n')
        data = None
        if json_start > 0:
            try:
                data = _parse_tool_json(body[json_start:].strip())
            except Exception:
                data = None
        return render_answer(tool_name or 'query_alerts_tool', data,
                             question=header, pending_plan=None)

    def _greeting_answer(self, question: str) -> str:
        q = question.lower()
        if any(k in q for k in ['你好', 'hello', 'hi', '在吗']):
            return '你好！我是 SxDevOps 智能运维助手。\n\n我可以帮你：\n- 查询和分析告警（"生产环境有哪些严重告警"）\n- 排查日志与链路（"查一下 order-center 最近的错误日志"）\n- 分析 Zabbix 监控问题与主机指标\n- 查询 CMDB 配置项与依赖拓扑\n- 生成主机巡检任务（需人工确认后执行）\n\n请问有什么可以帮你？'
        return (
            '我是 SxDevOps 智能运维助手，可以帮你查询告警、日志、链路、Zabbix 监控、'
            'CMDB 配置与依赖关系，也可以生成运维任务草稿。\n\n'
            '例如可以问我："生产环境当前有哪些严重告警？"'
        )


def _strip_env_prefix(question: str) -> str:
    """剥离消息中的 `[环境: xxx] ` 前缀，还原用户原始问题。"""
    import re
    text = str(question or '')
    m = re.match(r'^\[环境[:：]\s*[^\]]*\]\s*', text)
    if m:
        return text[m.end():]
    return text


# ── 工具 JSON 解析 ──────────────────────────────────────────────────


def _parse_tool_json(raw: str) -> Optional[dict]:
    """工具返回 JSON 字符串（可能被 LangChain 包裹），解析为 dict。"""
    if not raw:
        return None
    text = str(raw).strip()
    # 去掉可能的 markdown 代码块包裹
    if text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:]) if len(lines) > 1 else text
        if text.rstrip().endswith('```'):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except Exception:
        return {'_raw': text[:2000]}


# ── 演示问题精确覆盖表（保证讲解脚本逐字可复现）──────────────────────


DEMO_QUESTION_OVERRIDES = {
    '生产环境当前有哪些告警': {
        'tool': 'query_alerts_tool',
        'args': {'query': '生产环境', 'date_filter': 'today', 'limit': 10},
    },
    '生产环境当前有哪些严重告警': {
        'tool': 'query_alerts_tool',
        'args': {'query': '生产环境', 'level': 'critical', 'limit': 10},
    },
    '分析 order-center 库存校验超时的根因': {
        'tool': 'query_alert_root_cause_tool',
        'args': {'query': '库存校验超时'},
        'alert_keywords': ['库存校验超时'],
    },
    '查一下 order-center 最近的错误日志': {
        'tool': 'query_logs_tool',
        'args': {'query': 'order', 'limit': 20},
    },
    'Zabbix 上有哪些严重级别的磁盘问题': {
        'tool': 'query_zabbix_problems_tool',
        'args': {'min_severity': 4, 'limit': 50},
    },
    '帮我生成一个对订单相关主机的巡检任务': {
        'tool': 'query_zabbix_hosts_tool',
        'args': {'search': 'order', 'limit': 50},
        'pending': {
            'title': '订单服务主机巡检任务',
            'risk_level': 'low',
        },
    },
    'CMDB 里订单中心依赖哪些系统': {
        'tool': 'query_cmdb_topology_tool',
        'args': {'business_line': '', 'ci_name': 'order-center', 'scope': 'neighbors'},
    },
    '查询生产环境当前有哪些告警': {
        'tool': 'query_alerts_tool',
        'args': {'query': '生产环境', 'date_filter': 'today', 'limit': 10},
    },
    '生产环境 order 服务的请求量和错误率是多少': {
        'tool': 'query_metrics_promql_tool',
        'args': {'promql': 'sum by (service) (rate(http_requests_total[5m]))', 'range_query': True, 'duration_minutes': 60, 'limit': 6},
    },
    'order-api-ecs-01 磁盘使用率趋势和预测': {
        'tool': 'query_resource_forecast_tool',
        'args': {'hostname': 'order-api-ecs-01', 'metric': 'disk', 'lookback_hours': 24, 'horizon_hours': 6},
    },
    'order-api-ecs-01 的磁盘什么时候会满': {
        'tool': 'query_resource_forecast_tool',
        'args': {'hostname': 'order-api-ecs-01', 'metric': 'disk', 'horizon_hours': 24},
    },
    'member-api 内存使用趋势': {
        'tool': 'query_resource_forecast_tool',
        'args': {'hostname': 'member-api', 'metric': 'memory', 'lookback_hours': 168, 'horizon_hours': 12},
    },
    '统计一下本周生产环境的告警': {
        'tool': 'query_alerts_tool',
        'args': {'query': '生产环境', 'date_filter': 'week', 'limit': 20},
    },
    'ORCL01 为什么报 ORA-01653': {
        'tool': 'query_alert_root_cause_tool',
        'args': {'query': 'ORA-01653'},
        'alert_keywords': ['ORA-01653'],
    },
    'ORCL01 表空间满影响了哪些下游': {
        'tool': 'query_knowledge_graph_closure_tool',
        'args': {'query': 'TS_ORDER', 'node_name': 'TS_ORDER'},
    },
    '最近一条 ORA-12541 的根因是什么': {
        'tool': 'query_alert_root_cause_tool',
        'args': {'query': 'ORA-12541'},
        'alert_keywords': ['ORA-12541'],
    },
}


def build_demo_task_pending_plan(question: str) -> dict:
    """构造巡检任务的待确认动作计划（由 adapter 附着到 result['pending_actions']）。"""
    return {
        'title': '订单服务主机巡检任务',
        'risk_level': 'low',
        'payload': {
            'name': '订单服务主机巡检任务',
            'description': '由 AIOps 智能助手生成的订单相关主机巡检任务草稿，确认后载入任务中心。',
            'task_type': 'run_command',
            'target_type': 'host',
            'host_ids': [],
            'target_hosts': [],
            'host_count': 0,
            'payload': {
                'command': (
                    'echo "== Host =="; hostname; echo "== Uptime =="; uptime; '
                    'echo "== Disk =="; df -h; echo "== Memory =="; free -m'
                ),
                'script_kind': 'shell',
                'script_purpose': 'inspection',
            },
            'execution_mode': 'ssh',
            'execution_strategy': 'continue',
            'risk_level': 'low',
            'request_summary': question[:200],
        },
    }


# ── 答案渲染器 ──────────────────────────────────────────────────────


def render_answer(
    tool_name: str,
    data: Optional[dict],
    pending_plan: Optional[dict] = None,
    question: str = '',
) -> str:
    """按工具类型渲染二阶段结构化答案。只使用工具返回的真实数据。"""
    if not data:
        return (
            '## 结论\n查询未返回有效数据，请检查相关数据源配置或稍后再试。\n\n'
            '## 建议操作\n- 确认 Zabbix / CMDB 等数据源已正确接入\n- 重新发起查询'
        )

    if '_raw' in data:
        return f'## 结论\n已收到平台查询结果。\n\n## 关键证据\n{data["_raw"]}'

    # 各工具类型的模板渲染
    renderer = _ANSWER_RENDERERS.get(tool_name)
    if renderer:
        answer = renderer(data, question=question)
    else:
        answer = _render_generic(data)

    if pending_plan:
        answer += '\n\n> 已为你生成待确认的巡检任务草稿，请在上方确认或取消。'
    else:
        answer += '\n\n---\n_以上结论由离线演示模型基于平台真实模拟数据生成。_'
    return answer


def _count_alerts(data: dict) -> str:
    summary = data.get('summary') or {}
    total = summary.get('total')
    if total is None:
        total = summary.get('count')
    critical = summary.get('critical')
    if critical is None:
        critical = 0
    if total is None:
        # 无 summary 时从 items 统计（items 可能是字符串）
        for sec in data.get('sections') or []:
            items = sec.get('items') or []
            total += sec.get('_original_count', len(items))
            for it in items:
                text = str(it).lower()
                if 'critical' in text or '严重' in text:
                    critical += 1
    return str(total), str(critical)


def _first_items(data: dict, limit: int = 5) -> list:
    for sec in data.get('sections') or []:
        items = sec.get('items') or []
        if items:
            return items[:limit]
    return []


def _as_dict(item) -> dict:
    return item if isinstance(item, dict) else {}


def _item_title(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return (
        item.get('title')
        or item.get('name')
        or item.get('hostname')
        or item.get('service')
        or item.get('message')
        or item.get('description')
        or str(item)[:80]
    )


def _item_detail(item, keys: tuple = ('value', 'detail', 'description', 'status')) -> str:
    if not isinstance(item, dict):
        return ''
    for k in keys:
        v = item.get(k)
        if v:
            return str(v)
    return ''


def _render_alert_list(data: dict, question: str = '') -> str:
    total, critical = _count_alerts(data)
    lines = [
        f'## 结论\n平台当前共记录 {total} 条告警，其中严重告警 {critical} 条，需要优先关注。',
        '## 关键证据',
    ]
    for i, item in enumerate(_first_items(data), 1):
        title = _item_title(item)
        detail = _item_detail(item, ('value', 'detail', 'description'))
        line = f'{i}. **{title}**'
        if detail:
            line += f'：{detail}'
        lines.append(line)
    lines.append('## 风险评估')
    lines.append('- [HIGH] 严重告警涉及核心业务链路，存在业务中断风险')
    lines.append('## 建议操作')
    lines.append('- 优先确认严重告警的当前状态与影响范围')
    lines.append('- 对持续告警发起根因分析（可继续问我"分析 XX 的根因"）')
    return '\n'.join(lines)


def _render_root_cause(data: dict, question: str = '') -> str:
    summary = data.get('summary') or {}
    alert_info = data.get('alert') or {}
    conclusion = (
        summary.get('conclusion')
        or summary.get('root_cause')
        or summary.get('summary')
    )
    if not conclusion and alert_info:
        conclusion = (
            f'已定位目标告警：{alert_info.get("title", "")}'
            f'（级别 {alert_info.get("level", "-")}，状态 {alert_info.get("status", "-")}）。'
        )
    if not conclusion:
        conclusion = '已结合告警事实完成分析，证据链见下。'
    lines = ['## 结论', str(conclusion), '## 关键证据']
    for i, item in enumerate(_first_items(data), 1):
        title = _item_title(item)
        detail = _item_detail(item, ('value', 'detail'))
        line = f'{i}. **{title}**'
        if detail:
            line += f'：{detail}'
        lines.append(line)
    lines.append('## 风险评估')
    lines.append('- 根因未解除前告警可能持续或升级')
    lines.append('## 建议操作')
    lines.append('- 按根因结论执行处置（回滚/扩容/修复）')
    lines.append('- 处置后观察 30 分钟确认告警不再复现')
    return '\n'.join(lines)


def _render_logs(data: dict, question: str = '') -> str:
    items = _first_items(data, 5)
    errors = 0
    for it in items:
        text = str(it)
        if 'error' in text.lower() or '错误' in text:
            errors += 1
    lines = [
        f'## 结论\n检索到 {len(items)} 条相关日志，其中错误级别 {errors} 条。',
        '## 关键证据',
    ]
    for i, item in enumerate(items, 1):
        title = _item_title(item)
        detail = _item_detail(item, ('value', 'message', 'detail'))
        line = f'{i}. **{title}**'
        if detail:
            line += f'：{detail}'
        lines.append(line)
    lines.append('## 风险评估')
    lines.append('- 错误日志可能对应运行异常或依赖超时')
    lines.append('## 建议操作')
    lines.append('- 结合告警与链路追踪进一步定位（可问我"分析相关根因"）')
    return '\n'.join(lines)


def _render_zabbix_problems(data: dict, question: str = '') -> str:
    items = data.get('problems') or _first_items(data, 5)
    severity_map = {'4': '严重', '5': '灾难', '3': '警告', '2': '一般', '1': '信息', '0': '未知'}
    lines = [
        f'## 结论\nZabbix 当前存在 {len(items)} 个活跃问题，需要关注高严重级别项。',
        '## 关键证据',
    ]
    for i, item in enumerate(items, 1):
        it = _as_dict(item)
        title = _item_title(item)
        sev = str(it.get('severity') or it.get('severity_level') or '')
        sev_label = severity_map.get(str(sev), f'级别{sev}' if sev else '未分级')
        host = it.get('hostname') or it.get('host') or ''
        line = f'{i}. [{sev_label}] **{title}**'
        if host:
            line += f'（主机: {host}）'
        lines.append(line)
    lines.append('## 风险评估')
    lines.append('- [HIGH] 磁盘类问题持续增长可能引发写入失败')
    lines.append('## 建议操作')
    lines.append('- 对严重问题所在主机执行磁盘清理或扩容')
    lines.append('- 可通过"查询主机指标"进一步确认资源使用趋势')
    return '\n'.join(lines)


def _render_zabbix_hosts(data: dict, question: str = '') -> str:
    items = data.get('hosts') or _first_items(data, 6)
    online = sum(
        1 for it in items
        if str(_as_dict(it).get('status') or '').lower() in ('online', '可用', 'enabled', '0', '正常')
    )
    lines = [
        f'## 结论\n共查询到 {len(items)} 台 Zabbix 监控主机，在线 {online} 台。',
        '## 关键证据',
    ]
    for i, item in enumerate(items, 1):
        it = _as_dict(item)
        title = (
            it.get('host')
            or it.get('name')
            or it.get('hostname')
            or _item_title(item)
        )
        ip = it.get('ip') or it.get('ip_address') or it.get('interfaces') or ''
        line = f'{i}. **{title}**'
        if ip:
            line += f'（IP: {ip}）'
        lines.append(line)
    lines.append('## 建议操作')
    lines.append('- 可选择目标主机生成巡检任务（需确认后执行）')
    return '\n'.join(lines)


def _render_cmdb(data: dict, question: str = '') -> str:
    items = _first_items(data, 6)
    lines = [
        f'## 结论\nCMDB 中查询到 {len(items)} 个相关配置项。',
        '## 关键证据',
    ]
    for i, item in enumerate(items, 1):
        title = _item_title(item)
        detail = _item_detail(item, ('value', 'detail'))
        line = f'{i}. **{title}**'
        if detail:
            line += f'：{detail}'
        lines.append(line)
    lines.append('## 建议操作')
    lines.append('- 可继续查询依赖拓扑（"XX 依赖哪些系统"）进行影响分析')
    return '\n'.join(lines)


def _render_topology(data: dict, question: str = '') -> str:
    nodes = data.get('nodes') or []
    edges = data.get('edges') or []
    upstream = []
    downstream = []
    for e in edges or []:
        src = e.get('source') or e.get('from') or ''
        tgt = e.get('target') or e.get('to') or ''
        if isinstance(src, dict):
            src = _item_title(src)
        if isinstance(tgt, dict):
            tgt = _item_title(tgt)
        if 'order' in str(tgt).lower() or '订单' in str(tgt):
            upstream.append(src)
        if 'order' in str(src).lower() or '订单' in str(src):
            downstream.append(tgt)
    lines = ['## 结论']
    if upstream or downstream:
        if upstream:
            lines.append(f'订单中心上游依赖 {len(upstream)} 个系统：{"、".join(str(x) for x in upstream[:5])}')
        if downstream:
            lines.append(f'订单中心下游被 {len(downstream)} 个系统依赖：{"、".join(str(x) for x in downstream[:5])}')
    else:
        lines.append(f'拓扑中共 {len(nodes)} 个节点、{len(edges)} 条关系边。')
    lines.append('## 关键证据')
    for e in (edges or [])[:5]:
        src = e.get('source') or e.get('from') or {}
        tgt = e.get('target') or e.get('to') or {}
        rel = e.get('relation') or e.get('relation_type') or e.get('label') or '关联'
        src_name = _item_title(src) if isinstance(src, dict) else str(src)
        tgt_name = _item_title(tgt) if isinstance(tgt, dict) else str(tgt)
        lines.append(f'- {src_name} → {tgt_name}（{rel}）')
    lines.append('## 风险评估')
    lines.append('- 依赖链路上的任何变更或故障都可能传导至订单中心')
    lines.append('## 建议操作')
    lines.append('- 变更前先做依赖影响分析')
    return '\n'.join(lines)


def _render_generic(data: dict) -> str:
    summary = data.get('summary') or {}
    lines = ['## 结论', str(summary.get('summary') or summary.get('conclusion') or '查询完成。'), '## 关键证据']
    for i, item in enumerate(_first_items(data, 5), 1):
        title = _item_title(item)
        detail = _item_detail(item)
        line = f'{i}. **{title}**'
        if detail:
            line += f'：{detail}'
        lines.append(line)
    lines.append('## 建议操作')
    lines.append('- 如需进一步分析，可以让我查询关联的告警、日志或依赖关系')
    return '\n'.join(lines)


def _render_metrics(data: dict, question: str = '') -> str:
    """指标问数渲染：结论 + 各序列最新值与趋势 + ```chart 折线。"""
    import json as _json
    summary = data.get('summary') or {}
    payload = data.get('promql') or {}
    lines = ['## 结论']
    lines.append(
        f"指标查询完成：{summary.get('series_count', 0)} 个时间序列"
        f"（数据源 {summary.get('source') or '指标数据源'}，窗口 {summary.get('range') and '区间' or '瞬时'}）。"
    )
    for item in _first_items(data, 5):
        title = _item_title(item)
        detail = _item_detail(item)
        line = f'- **{title}**' + (f'：{detail}' if detail else '')
        lines.append(line)
    chart = payload.get('result') or []
    if chart and chart[0].get('values'):
        series = chart[0]
        values = series.get('values') or []
        step = max(1, len(values) // 12)
        sampled = values[::step]
        categories = []
        import time as _time
        for ts, _ in sampled:
            categories.append(_time.strftime('%H:%M', _time.localtime(float(ts))))
        numbers = [round(float(v), 1) for _, v in sampled]
        label = ' / '.join(f'{k}={v}' for k, v in (series.get('metric') or {}).items() if k != '__name__')
        chart_json = {
            'type': 'line',
            'title': f"指标趋势 {label}"[:15],
            'data': {'categories': categories, 'values': numbers},
        }
        lines.append('```chart')
        lines.append(_json.dumps(chart_json, ensure_ascii=False))
        lines.append('```')
    lines.append('## 建议操作')
    lines.append('- 如需更细粒度趋势，可指定时间窗口或改用资源趋势预测工具')
    return '\n'.join(lines)


def _render_forecast(data: dict, question: str = '') -> str:
    """资源趋势预测渲染：结论含阈值 ETA + 置信区间 + ```chart 历史与预测合成折线。"""
    import json as _json
    summary = data.get('summary') or {}
    chart = data.get('chart') or {}
    lines = ['## 结论']
    lines.append(
        f"{summary.get('hostname')} {summary.get('metric_label') or '指标'}当前 "
        f"{summary.get('current')}%（趋势{summary.get('trend')}）。"
        f"{summary.get('threshold_eta_text') or ''}"
    )
    lines.append('## 预测与置信区间')
    for section in (data.get('sections') or []):
        for item in section.get('items') or []:
            lines.append(f'- {item}')
    categories = chart.get('categories') or []
    values = (chart.get('values') or []) + (chart.get('forecast') or [])
    if categories and values and len(categories) == len(values):
        # 抽稀避免图表过密
        step = max(1, len(values) // 16)
        chart_json = {
            'type': 'line',
            'title': (chart.get('title') or '趋势预测')[:15],
            'data': {'categories': categories[::step], 'values': values[::step]},
        }
        lines.append('```chart')
        lines.append(_json.dumps(chart_json, ensure_ascii=False))
        lines.append('```')
    lines.append('## 建议操作')
    lines.append('- 关注阈值到达时间，提前扩容或清理磁盘/内存')
    lines.append('- 如需其它主机或 CPU/内存/磁盘维度，直接告诉我')
    return '\n'.join(lines)


def _render_closure(data):
    """因果闭包查询渲染：结论 + 依赖路径列表。"""
    summary = data.get('summary') or {}
    sections = data.get('sections') or []
    path_count = summary.get('path_count', 0)
    node_count = summary.get('node_count', 0)
    status_parts = [f'共 {path_count} 条依赖路径、覆盖 {node_count} 个节点']
    if summary.get('truncated'):
        status_parts.append('结果已截断')
    if summary.get('cycle_detected'):
        status_parts.append('图中存在环')
    lines = ['## 结论', '，'.join(status_parts) + '。', '', '## 依赖路径']
    found = False
    for section in sections:
        if '因果闭包' in (section.get('title') or ''):
            content = section.get('content') or ''
            if content and content != '起点无出边。':
                for item in content.split('\n'):
                    if item.strip():
                        lines.append(f'- {item}')
                found = True
            break
    if not found:
        lines.append('- 起点无出边。')
    return '\n'.join(lines)


_ANSWER_RENDERERS = {
    'query_alerts_tool': _render_alert_list,
    'query_alert_root_cause_tool': _render_root_cause,
    'query_alert_metrics_tool': _render_generic,
    'query_logs_tool': _render_logs,
    'query_traces_tool': _render_generic,
    'query_zabbix_problems_tool': _render_zabbix_problems,
    'query_zabbix_hosts_tool': _render_zabbix_hosts,
    'query_zabbix_items_tool': _render_generic,
    'query_zabbix_history_tool': _render_generic,
    'query_zabbix_host_metrics_tool': _render_generic,
    'query_knowledge_graph_tool': _render_generic,
    'query_cmdb_items_tool': _render_cmdb,
    'query_cmdb_topology_tool': _render_topology,
    'query_device_detail_tool': _render_generic,
    'query_k8s_cluster_summary_tool': _render_generic,
    'query_recent_changes_tool': _render_generic,
    'query_metrics_promql_tool': _render_metrics,
    'query_resource_forecast_tool': _render_forecast,
    'query_knowledge_graph_closure_tool': _render_closure,
}


def attach_demo_pending_action(result: dict, question: str) -> None:
    """demo 模式下：将巡检任务的待确认动作附着到 agent 结果。

    在 agent.invoke 之后、_process_pending_actions 之前调用。
    只有当问题命中"生成任务"类意图时才附着。
    从工具结果中提取主机名并映射到 ops.Host，填充任务草稿的 host_ids。
    """
    if not any(m in question for m in ACTION_GENERATING_MARKERS):
        return
    plan = build_demo_task_pending_plan(question)

    # 从 agent 结果中的工具消息提取主机名
    hostnames = _extract_hostnames_from_result(result)
    if hostnames:
        host_ids, target_hosts = _resolve_host_ids(hostnames)
        if host_ids:
            plan['payload']['host_ids'] = host_ids
            plan['payload']['target_hosts'] = target_hosts
            plan['payload']['host_count'] = len(host_ids)

    result['pending_actions'] = [{
        'type': 'execute_host_task',
        'title': plan['title'],
        'risk_level': plan['risk_level'],
        'payload': plan['payload'],
    }]


def _extract_hostnames_from_result(result: dict) -> list:
    """从 agent 结果的 tool 消息中提取主机名列表。"""
    names = []
    for msg in result.get('messages', []):
        if getattr(msg, 'type', '') != 'tool':
            continue
        raw = getattr(msg, 'content', '') or ''
        data = _parse_tool_json(raw)
        if not isinstance(data, dict):
            continue
        for item in data.get('hosts') or []:
            if isinstance(item, dict):
                name = item.get('host') or item.get('name') or item.get('hostname')
                if name:
                    names.append(name)
        for item in _first_items(data, 50):
            if isinstance(item, dict):
                name = item.get('host') or item.get('hostname')
                if name:
                    names.append(name)
    return names


def _resolve_alert_id_by_keywords(keywords) -> Optional[int]:
    """按标题关键词查找告警 ID（演示问题命中故事线告警）。"""
    if not keywords:
        return None
    try:
        from ops.models import Alert

        kw_list = keywords if isinstance(keywords, list) else [keywords]
        qs = Alert.objects.all()
        for kw in kw_list:
            qs = qs.filter(title__icontains=kw)
        alert = qs.order_by('-id').first()
        return alert.id if alert else None
    except Exception as exc:
        logger.warning('演示告警解析失败: %s', type(exc).__name__)
        return None


def _resolve_host_ids(hostnames: list) -> tuple[list, list]:
    """将主机名映射为 ops.Host 的 id 与目标快照。"""
    try:
        from ops.models import Host

        hosts = list(Host.objects.filter(hostname__in=hostnames))
        ids = [h.id for h in hosts]
        snapshots = [
            {'id': h.id, 'hostname': h.hostname, 'ip_address': h.ip_address,
             'environment': getattr(h, 'environment', '')}
            for h in hosts
        ]
        return ids, snapshots
    except Exception as exc:
        logger.warning('演示任务目标主机解析失败: %s', type(exc).__name__)
        return [], []
