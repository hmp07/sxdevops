"""
确定性路由前置节点 — 保留 7 个 _is_direct_* 函数作为 LangGraph pre-node。

设计原则：
- 这些函数作为 LangGraph 的 conditional edge，在 LLM 调用前执行
- 明确命中 → 直接调用工具返回结果，跳过 LLM 推理（省 token + 快）
- 命中但不确定 → fall through 到 DeepAgents 主 loop（LLM 判断）
- 未命中 → 直接交给 LLM

与原实现的区别：
- 原实现"命中即执行"，误匹配导致完全错误的工具链
- 新实现有置信度判断，不确定时交给 LLM 处理
"""

from __future__ import annotations

from typing import Optional


def _question_contains_any(question: str, keywords: list[str]) -> bool:
    """检查问题是否包含任一关键词（大小写不敏感）。"""
    text = str(question or '').lower()
    return any(kw.lower() in text for kw in keywords if kw)


def _question_contains_all(question: str, keywords: list[str]) -> bool:
    """检查问题是否包含所有关键词。"""
    text = str(question or '').lower()
    return all(kw.lower() in text for kw in keywords if kw)


# ── 快速路径模式定义 ──────────────────────────────────────────────────────

FASTPATH_PATTERNS = [
    {
        'name': 'alert_list',
        'tool': 'query_alerts_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['告警', 'alert', '警告'])
            and _question_contains_any(q, [
                '有哪些', '哪些', '列表', '当前', '今天', '今日',
                '统计', '按级别', '告警级别', '未确认', '严重',
            ])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'date_filter': 'today' if _question_contains_any(q, ['今天', '今日']) else '',
            'limit': 10,
        },
    },
    {
        'name': 'cmdb_query',
        'tool': 'query_cmdb_items_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['cmdb', '配置项', '业务系统', '有哪些系统',
                                       '包含哪些', '服务器', '数据库', '中间件',
                                       '依赖哪些', '属于哪些', '什么系统'])
            and not _question_contains_any(q, ['告警', '监控', 'zabbix', 'cpu', '内存'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'limit': 6,
        },
    },
    {
        'name': 'zabbix_problems',
        'tool': 'query_zabbix_problems_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['zabbix'])
            and _question_contains_any(q, ['问题', '告警', '严重', '灾难', 'problem'])
        ),
        'params': lambda q: {
            'min_severity': (
                4 if _question_contains_any(q, ['严重', '灾难', 'critical', 'disaster'])
                else 2 if _question_contains_any(q, ['警告', 'warning'])
                else 0
            ),
            'limit': 50,
        },
    },
    {
        'name': 'alert_metrics_query',
        'tool': 'query_alert_metrics_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['趋势', 'metric', '时序', '监控曲线'])
            and _question_contains_any(q, ['查', '最近', '看', '有哪些'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'limit': 10,
        },
    },
    {
        'name': 'host_metrics',
        'tool': None,  # 需要两步：先查 hostid，再查指标
        'matcher': lambda q: (
            _question_contains_any(q, ['cpu', '内存', '磁盘', '网络', 'memory', 'disk',
                                       'network', '使用率', '性能', '负载'])
            and not _question_contains_any(q, ['告警', '事件', '发布', '趋势', '时序', '监控曲线'])
        ),
        'params': None,
    },
    {
        'name': 'device_detail',
        'tool': 'query_device_detail_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['设备', '完整信息', '详情'])
            and _question_contains_any(q, ['监控', 'cmdb', '工单', '配置'])
        ),
        'params': lambda q: {
            'hostname': _extract_hostname(q),
        },
    },
    {
        'name': 'k8s_lookup',
        'tool': 'query_k8s_cluster_summary_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['k8s', 'kubernetes', 'pod', '集群', '容器'])
            and _question_contains_any(q, ['状态', '异常', '重启', '资源', '命名空间'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'limit': 10,
        },
    },
    {
        'name': 'recent_changes',
        'tool': 'query_recent_changes_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['最近', '变更', '发布', '上线', '部署'])
            and _question_contains_any(q, ['有哪些', '什么', '今天', '昨天', '查看'])
            and not _question_contains_any(q, ['分析', '影响', '关联'])
        ),
        'params': lambda q: {
            'limit': 10,
        },
    },
    # ── 新增: Phase 3 扩展 fastpath 模式 (6 → 12+) ──────────────────────
    {
        'name': 'log_query',
        'tool': 'query_logs_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['日志', 'log', '错误日志', '报错'])
            and _question_contains_any(q, ['查', '最近', '有哪些', '什么错误', '看'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'duration_minutes': (
                30 if _question_contains_any(q, ['最近半小时', '半小时', '30分钟'])
                else 1440 if _question_contains_any(q, ['今天', '今日'])
                else 60
            ),
            'limit': 20,
        },
    },
    {
        'name': 'trace_query',
        'tool': 'query_traces_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['链路追踪', '调用链', 'trace', '追踪', 'tracing'])
            and not _question_contains_any(q, ['配置', '设置', '部署', '安装'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'errors_only': _question_contains_any(q, ['错误', '异常', 'error', '失败']),
            'limit': 20,
        },
    },
    {
        'name': 'k8s_resource_lookup',
        'tool': 'query_k8s_cluster_summary_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['k8s', 'kubernetes', 'pod', 'deployment', 'service',
                                       'ingress', 'namespace', '节点', 'node',
                                       '容器组', '服务发现'])
            and not _question_contains_any(q, ['创建', '删除', '修改', '部署', '安装', '发布'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'limit': 10,
        },
    },
    {
        'name': 'workorder_query',
        'tool': 'query_recent_changes_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['工单', 'workorder', '变更单', '发布记录'])
            and _question_contains_any(q, ['有哪些', '查', '最近', '今天', '昨天'])
            and not _question_contains_any(q, ['影响', '关联', '分析'])
        ),
        'params': lambda q: {
            'limit': 10,
        },
    },
    {
        'name': 'knowledge_graph_lookup',
        'tool': 'query_knowledge_graph_tool',
        'matcher': lambda q: (
            _question_contains_any(q, ['知识图谱', '依赖关系', '系统依赖', '上下游', '拓扑'])
            and _question_contains_any(q, ['有哪些', '查', '是什么', '如何'])
            and not _question_contains_any(q, ['告警', 'cpu', '内存', '磁盘'])
        ),
        'params': lambda q: {
            'query': _strip_noise(q),
            'limit': 10,
        },
    },
]


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _strip_noise(question: str) -> str:
    """从问题中去除常见噪音词，提取核心关键词。"""
    noise = ['请', '帮我', '帮我查', '查询', '查看', '一下', '看看',
             '有没有', '是否', '怎么样', '如何', '告诉我', '我想',
             '统计', '按级别', '按告警级别', '今天', '今日', '昨天',
             '当前', '最近', '告警级别']
    result = str(question or '')
    for word in noise:
        result = result.replace(word, '')
    return result.strip()


def _extract_hostname(question: str) -> str:
    """从问题中提取主机名。"""
    import re
    text = str(question or '')
    # 匹配类似 "Dataease1", "Dataease2", "web-server-01" 的模式
    patterns = [
        r'([A-Za-z][A-Za-z0-9_-]{2,}(?:\d+)?)',  # 通用主机名
        r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})',  # IP 地址
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            return match.group(1)
    return ''


# ── 路由函数 ──────────────────────────────────────────────────────────────


def fastpath_router(question: str) -> tuple[Optional[str], Optional[dict]]:
    """
    快速路径路由器。

    返回 (tool_name, params) 或 (None, None)。
    - tool_name 非 None: 直接调用该工具，跳过 LLM
    - tool_name 为 None: 交给 LLM 处理

    与 _dispatch_with_tool_runtime 中的 14 个 if/elif 链不同：
    - 这里只返回"非常确定"的匹配
    - 不确定时返回 None，让 LLM 来决策
    """
    if not question or not str(question).strip():
        return None, None

    for pattern in FASTPATH_PATTERNS:
        if pattern['matcher'](question):
            if pattern['tool'] is None:
                # 需要多步的查询（如 host_metrics），交给 LLM
                return None, None
            if pattern['params']:
                params = pattern['params'](question)
                if params and _params_have_content(params):
                    return pattern['tool'], params
            else:
                return pattern['tool'], {}

    return None, None


def _params_have_content(params: dict) -> bool:
    """检查参数是否包含有效内容。"""
    for v in params.values():
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (int, float)) and v > 0:
            return True
        if isinstance(v, list) and v:
            return True
    return False
