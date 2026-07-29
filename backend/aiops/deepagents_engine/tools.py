"""
统一工具注册表 — 将 16 个平台工具包装为 DeepAgents/LangChain Tool。

设计原则：
1. 每个工具用 @tool 装饰器包装，docstring 即为 LLM 路由依据
2. 工具函数通过 RunnableConfig 提取 Django user/session 上下文
3. close_old_connections() 确保 Django ORM 在 Agent 线程中可用
4. 返回 JSON 字符串（LangChain Tool 标准格式）
5. SXDEVOPS_TOOLS 列表是唯一的工具注册点 — 替代原有 7 个注册点

原 7 个注册点映射：
  PLATFORM_MCP_TOOL_DEFINITIONS → @tool name + description
  _invoke_platform_mcp_handler  → tool func body (直接调用原实现函数)
  _run_tool_call                 → DeepAgents tool calling 自动处理
  _tool_allowed                  → RBACMiddleware (middleware.py)
  catalog                        → get_tool_names() + tool.description
  tool_whitelist                 → per-subagent tool subsets
  allowed_tools                  → per-action tool subsets (subagents.py)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from django.db import close_old_connections
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _get_user_from_config(config: Optional[RunnableConfig]):
    """从 LangGraph RunnableConfig 提取 Django User。"""
    if config is None:
        return None
    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        return None
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


def _get_session_from_config(config: Optional[RunnableConfig]):
    """从 LangGraph RunnableConfig 提取 AIOpsChatSession。"""
    if config is None:
        return None
    session_id = config.get("configurable", {}).get("session_id")
    if not session_id:
        return None
    from aiops.models import AIOpsChatSession
    try:
        return AIOpsChatSession.objects.get(id=session_id)
    except AIOpsChatSession.DoesNotExist:
        return None


def _safe_json(result) -> str:
    """安全序列化结果为 JSON 字符串。"""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _truncate_tool_output(result: dict, max_items: int = 10, max_str_len: int = 2000) -> dict:
    """截断工具输出，避免爆 context window。

    - sections 中的 items 超过 max_items 时截断，标记 truncated=True
    - 每个 item 中的 value/description 字符串超过 max_str_len 时截断
    - 不修改原始 result，返回浅拷贝
    """
    if not isinstance(result, dict):
        return result

    truncated = dict(result)
    sections = truncated.get('sections', [])
    if not sections:
        return truncated

    new_sections = []
    for section in sections:
        sec = dict(section)
        items = sec.get('items', [])
        if isinstance(items, list) and len(items) > max_items:
            sec['items'] = items[:max_items]
            sec['truncated'] = True
            sec['_original_count'] = len(items)
        new_sections.append(sec)

    truncated['sections'] = new_sections

    # 截断摘要中的长字符串
    summary = truncated.get('summary', {})
    if isinstance(summary, dict):
        for key in list(summary.keys()):
            val = summary[key]
            if isinstance(val, str) and len(val) > max_str_len:
                summary[key] = val[:max_str_len] + '...[truncated]'

    return truncated


def _try_cache(key_parts: list[str], ttl: int = 120):
    """从 Django Cache 读取缓存值。返回 None 表示未命中。"""
    from django.core.cache import cache
    return cache.get(':'.join(key_parts))


def _set_cache(key_parts: list[str], value, ttl: int = 120):
    """写入 Django Cache。失败静默忽略。"""
    from django.core.cache import cache
    try:
        cache.set(':'.join(key_parts), value, timeout=ttl)
    except Exception:
        pass


# ── P0 工具：告警 / 知识图谱 / CMDB / Zabbix 主机 — 最常用 ────────────────


@tool
def query_alerts_tool(
    query: str = "",
    level: str = "",
    status: str = "",
    date_filter: str = "",
    limit: int = 6,
    config: RunnableConfig = None,
) -> str:
    """查询告警中心的告警记录。

    用于：统计告警数量、按级别过滤（critical/warning/info）、查看活跃告警、
    查询今天/本周的告警、搜索特定关键词的告警。

    Args:
        query: 搜索关键词（告警名称、主机名、描述中的文本）
        level: 告警级别过滤 (critical / warning / info)
        status: 告警状态过滤 (active / resolved / closed / muted)
        date_filter: 时间范围 (today / yesterday / week / month / YYYY-MM-DD)
        limit: 返回数量上限，默认 6，最大 20
    """
    close_old_connections()
    # 尝试缓存命中（常见查询如 date_filter='today' 高频重复）
    cache_key = ['aiops', 'alerts', str(date_filter), str(level), str(status), str(limit)]
    cached = _try_cache(cache_key, ttl=120)
    if cached is not None:
        return cached

    from aiops.tools import query_alerts as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, level=level, status=status,
        date_filter=date_filter, limit=limit,
    )
    result = _truncate_tool_output(result)
    output = _safe_json(result)
    _set_cache(cache_key, output, ttl=120)
    return output


@tool
def query_knowledge_graph_tool(
    query: str = "",
    environment: str = "",
    system_name: str = "",
    service: str = "",
    limit: int = 8,
    config: RunnableConfig = None,
) -> str:
    """查询 AIOps 知识图谱，获取环境、系统或服务之间的业务关联关系。

    用于：了解系统间依赖关系、查询某业务线包含哪些服务、
    了解某服务关联的告警源/日志源/数据库。

    Args:
        query: 搜索关键词
        environment: 环境过滤 (prod/test/dev)
        system_name: 系统名称
        service: 服务名称
        limit: 返回数量上限，默认 8，最大 20
    """
    close_old_connections()
    from aiops.tools import query_knowledge_graph as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, environment=environment,
        system_name=system_name, service=service, limit=limit,
    )
    return _safe_json(result)


@tool
def query_cmdb_items_tool(
    query: str = "",
    environment: str = "",
    limit: int = 6,
    config: RunnableConfig = None,
) -> str:
    """查询 CMDB 配置项（CI），包括业务系统、服务器、数据库、中间件等。

    用于："有哪些业务系统"、"电商平台包含哪些服务器"、"查某台主机的CMDB信息"、
    "某业务线的所有配置项"等问题。

    Args:
        query: 搜索关键词（业务线名称、主机名、IP、CI类型）
        environment: 环境过滤 (prod/test/dev)
        limit: 返回数量上限，默认 6，最大 20
    """
    close_old_connections()
    from aiops.tools import query_cmdb_items as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, environment=environment, limit=limit,
    )
    return _safe_json(result)


@tool
def query_zabbix_hosts_tool(
    search: str = "",
    limit: int = 50,
    config: RunnableConfig = None,
) -> str:
    """查询 Zabbix 监控系统中的主机列表，包含主机名、状态、可用性、IP 地址。

    用于：搜索 Zabbix 中的主机、获取主机的 hostid（后续查询监控项/指标的前置步骤）、
    查看主机在线/离线状态。

    Args:
        search: 搜索关键字（按主机名模糊匹配，留空则返回所有主机）
        limit: 返回数量上限，默认 50，最大 200
    """
    close_old_connections()
    from aiops.tools import query_zabbix_hosts as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        search=search, limit=limit,
    )
    result = _truncate_tool_output(result)
    return _safe_json(result)


@tool
def query_zabbix_problems_tool(
    min_severity: int = 0,
    limit: int = 50,
    config: RunnableConfig = None,
) -> str:
    """查询 Zabbix 当前活跃的告警问题，包含问题描述、严重级别、确认状态。

    严重级别对照：
    0 - 未分类, 1 - 信息, 2 - 警告, 3 - 一般严重, 4 - 严重, 5 - 灾难

    用于：查看 Zabbix 当前有哪些问题、按严重级别过滤告警、
    查看未确认的告警、获取 Zabbix 侧的问题概览。

    Args:
        min_severity: 最低严重级别（0-5），只返回 >= 此级别的告警，默认 0（全部）
        limit: 返回数量上限，默认 50，最大 200
    """
    close_old_connections()
    from aiops.tools import query_zabbix_problems as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        min_severity=min_severity, limit=limit,
    )
    return _safe_json(result)


# ── P1 工具：日志 / 链路 / K8s / Zabbix 监控项 & 历史 ────────────────────


@tool
def query_logs_tool(
    query: str = "",
    service: str = "",
    level: str = "",
    duration_minutes: int = 60,
    limit: int = 10,
    config: RunnableConfig = None,
) -> str:
    """查询平台日志源中的日志样本，支持 Loki / ELK / SLS。

    用于：搜索错误日志、根据服务名和时间范围查询日志、
    关联分析时查找特定时间段的异常日志。

    Args:
        query: 搜索关键词
        service: 服务名称过滤
        level: 日志级别过滤 (ERROR / WARN / INFO)
        duration_minutes: 查询时间范围（分钟），默认 60（最近1小时），最大 1440
        limit: 返回数量上限，默认 10，最大 20
    """
    close_old_connections()
    from aiops.tools import query_logs as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, service=service, level=level,
        duration_minutes=duration_minutes, limit=limit,
    )
    return _safe_json(result)


@tool
def query_traces_tool(
    query: str = "",
    errors_only: bool = False,
    duration_minutes: int = 60,
    limit: int = 10,
    config: RunnableConfig = None,
) -> str:
    """查询链路追踪样本和异常链路，支持 SkyWalking / Tempo / Jaeger / Zipkin。

    用于：查看服务调用链路、定位慢请求、查找异常 Span、
    分析分布式追踪数据中的瓶颈。

    Args:
        query: 搜索关键词（服务名、Trace ID、Span 名称）
        errors_only: 仅返回错误链路，默认 False
        duration_minutes: 查询时间范围（分钟），默认 60，最大 1440
        limit: 返回数量上限，默认 10，最大 20
    """
    close_old_connections()
    from aiops.tools import query_traces as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, errors_only=errors_only,
        duration_minutes=duration_minutes, limit=limit,
    )
    return _safe_json(result)


@tool
def query_k8s_cluster_summary_tool(
    query: str = "",
    cluster_name: str = "",
    limit: int = 10,
    config: RunnableConfig = None,
) -> str:
    """查询 Kubernetes 集群摘要，包括 Pod 状态、异常事件、资源使用情况。

    用于：查看 K8s 集群健康状态、排查 Pod 异常重启、查看最近事件、
    了解命名空间的资源使用情况。

    Args:
        query: 搜索关键词（Pod 名称、命名空间、标签）
        cluster_name: 集群名称过滤
        limit: 返回数量上限，默认 10，最大 20
    """
    close_old_connections()
    from aiops.tools import query_k8s_cluster_summary as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, cluster_name=cluster_name, limit=limit,
    )
    return _safe_json(result)


@tool
def query_zabbix_items_tool(
    host_ids: list[int] = None,
    search: str = "",
    limit: int = 50,
    config: RunnableConfig = None,
) -> str:
    """查询指定主机的 Zabbix 监控项列表及最新值。

    包含监控项名称、键值、最新数值、单位、value_type。需要先通过
    query_zabbix_hosts_tool 获取主机 hostid。

    常用监控项搜索关键词：
    - CPU: "cpu" 或 "system.cpu"
    - 内存: "memory" 或 "vm.memory"
    - 磁盘: "disk" 或 "vfs.fs" 或 "storage"
    - 网络: "net" 或 "network"

    Args:
        host_ids: Zabbix 主机 ID 列表（从 query_zabbix_hosts_tool 获取）
        search: 按监控项键值或名称搜索关键词
        limit: 返回数量上限，默认 50，最大 200
    """
    close_old_connections()
    from aiops.tools import query_zabbix_items as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        host_ids=host_ids or [], search=search, limit=limit,
    )
    return _safe_json(result)


@tool
def query_zabbix_history_tool(
    item_ids: list[int] = None,
    value_type: int = None,
    limit: int = 50,
    config: RunnableConfig = None,
) -> str:
    """查询指定监控项的历史数据，用于绘制趋势图或分析指标变化。

    需要先通过 query_zabbix_items_tool 获取监控项 ID 和 value_type。
    支持自动探测 value_type，也可手动指定：
    0 = float（数值型）, 1 = char（字符型）, 3 = unsigned（无符号整数）, 4 = text（文本型）

    Args:
        item_ids: Zabbix 监控项 ID 列表
        value_type: 值类型（0/1/3/4），不传则自动探测
        limit: 返回数量上限，默认 50，最大 200
    """
    close_old_connections()
    from aiops.tools import query_zabbix_history as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        item_ids=item_ids or [], value_type=value_type, limit=limit,
    )
    return _safe_json(result)


@tool
def query_zabbix_host_metrics_tool(
    hostid: str,
    datasource_id: int = None,
    config: RunnableConfig = None,
) -> str:
    """一次查询获取主机的四类核心性能指标摘要：CPU、内存、文件系统、网络流量。

    用于快速评估主机健康状态，无需多次调用 query_zabbix_items_tool。
    需要先通过 query_zabbix_hosts_tool 获取主机的 hostid。

    返回内容：CPU 使用率、内存使用率/总量、各文件系统使用率、网络流入/流出速率。

    Args:
        hostid: Zabbix 主机 ID（字符串格式，从 query_zabbix_hosts_tool 获取）
        datasource_id: Zabbix 数据源 ID（可选，多数据源时指定）
    """
    close_old_connections()
    from aiops.tools import query_zabbix_host_metrics as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        hostid=hostid, datasource_id=datasource_id,
    )
    return _safe_json(result)


# ── P2 工具：告警根因 / 指标 / 变更 / 设备详情 / CMDB 拓扑 ────────────────


@tool
def query_alert_root_cause_tool(
    query: str = "",
    alert_id: int = None,
    fingerprint: str = "",
    latest: bool = False,
    config: RunnableConfig = None,
) -> str:
    """分析单条告警的根因，综合 K8s、事件、日志、链路和指标证据。

    当用户给出告警 ID 或指纹，或询问某环境最新告警的原因、根因、
    为什么、怎么处理时**必须使用**本工具。

    Args:
        query: 分析上下文描述
        alert_id: 告警 ID
        fingerprint: 告警指纹（去重标识）
        latest: 是否分析最新一条告警，默认 False
    """
    close_old_connections()
    from aiops.tools import query_alert_root_cause as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, alert_id=alert_id,
        fingerprint=fingerprint, latest=latest,
    )
    return _safe_json(result)


@tool
def query_alert_metrics_tool(
    query: str = "",
    alert_id: int = None,
    fingerprint: str = "",
    latest: bool = False,
    duration_minutes: int = 60,
    step: int = 60,
    budget: int = 5,
    metric_datasource_id: int = None,
    config: RunnableConfig = None,
) -> str:
    """按告警上下文生成 PromQL 查询计划，返回指标趋势和异常摘要。

    用于：查看告警相关的 CPU/内存/网络等指标变化趋势、
    验证告警是否由资源异常引起。

    Args:
        query: 描述要查询的指标上下文
        alert_id: 告警 ID
        fingerprint: 告警指纹
        latest: 是否使用最新告警
        duration_minutes: 查询时间范围（分钟），15-120
        step: 采样步长（秒），15-3600
        budget: PromQL 查询预算（最大查询数），1-5
        metric_datasource_id: 指标数据源 ID
    """
    close_old_connections()
    from aiops.tools import query_alert_metrics as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        query=query, alert_id=alert_id, fingerprint=fingerprint,
        latest=latest, duration_minutes=duration_minutes, step=step,
        budget=budget, metric_datasource_id=metric_datasource_id,
    )
    return _safe_json(result)


@tool
def query_recent_changes_tool(
    limit: int = 10,
    config: RunnableConfig = None,
) -> str:
    """查询最近的发布、工单和事件候选变更记录。

    用于：关联分析时查找最近有哪些上线/部署/变更可能导致了问题、
    变更影响分析、上线后风险排查。

    Args:
        limit: 返回数量上限，默认 10，最大 20
    """
    close_old_connections()
    from aiops.tools import query_recent_changes as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(session, None, user, limit=limit)
    return _safe_json(result)


@tool
def query_device_detail_tool(
    hostname: str = "",
    config: RunnableConfig = None,
) -> str:
    """查询设备的 Zabbix 监控与 iTop CMDB 合并视图。

    输入主机名或 IP 即可获取监控状态、CMDB 属性、关联工单等完整信息。
    用于需要了解一台设备全貌的场景（监控+配置+工单）。

    Args:
        hostname: 主机名或 IP 地址
    """
    close_old_connections()
    from aiops.tools import query_device_detail as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(session, None, user, hostname=hostname)
    return _safe_json(result)


@tool
def query_cmdb_topology_tool(
    business_line: str = "",
    ci_name: str = "",
    scope: str = "neighbors",
    config: RunnableConfig = None,
) -> str:
    """查询 CMDB 中指定业务线或 CI 的资源拓扑关系（上下游依赖图）。

    用于：影响分析（"电商平台依赖哪些数据库"）、根因定位、
    变更风险评估（"修改这个服务会影响哪些系统"）。

    Args:
        business_line: 业务线名称（如"电商平台"）
        ci_name: 配置项（CI）名称
        scope: 拓扑范围，exact（精确匹配）或 neighbors（包含邻居），默认 neighbors
    """
    close_old_connections()
    from aiops.tools import query_cmdb_topology as _impl
    user = _get_user_from_config(config)
    session = _get_session_from_config(config)
    result = _impl(
        session, None, user,
        business_line=business_line, ci_name=ci_name, scope=scope,
    )
    return _safe_json(result)


# ── 统一工具注册表（唯一的工具注册点）──────────────────────────────────────


SXDEVOPS_TOOLS = [
    # P0 — 最常用
    query_alerts_tool,
    query_knowledge_graph_tool,
    query_cmdb_items_tool,
    query_zabbix_hosts_tool,
    query_zabbix_problems_tool,
    # P1 — 常用
    query_logs_tool,
    query_traces_tool,
    query_k8s_cluster_summary_tool,
    query_zabbix_items_tool,
    query_zabbix_history_tool,
    query_zabbix_host_metrics_tool,
    # P2 — 专用
    query_alert_root_cause_tool,
    query_alert_metrics_tool,
    query_recent_changes_tool,
    query_device_detail_tool,
    query_cmdb_topology_tool,
]


def get_tool_by_name(name: str):
    """按名称查找工具。替代 PLATFORM_MCP_TOOL_DEFINITIONS 的字典索引。"""
    for t in SXDEVOPS_TOOLS:
        if t.name == name:
            return t
    return None


def get_tool_names() -> list[str]:
    """返回所有注册工具的 name 列表。"""
    return [t.name for t in SXDEVOPS_TOOLS]


def get_tools_for_action(action_code: str) -> list:
    """按 action 类型返回允许的工具子集。替代 allowed_tools per action。"""
    # 工具子集定义 — 每个 action 只能使用列表中的工具
    ACTION_TOOL_MAP = {
        'alert.root_cause': [
            'query_alerts_tool', 'query_alert_root_cause_tool',
            'query_alert_metrics_tool', 'query_knowledge_graph_tool',
            'query_zabbix_problems_tool', 'query_zabbix_hosts_tool',
            'query_logs_tool', 'query_traces_tool',
            'query_k8s_cluster_summary_tool', 'query_cmdb_items_tool',
            'query_cmdb_topology_tool', 'query_recent_changes_tool',
        ],
        'k8s.diagnose': [
            'query_k8s_cluster_summary_tool', 'query_logs_tool',
            'query_traces_tool', 'query_knowledge_graph_tool',
        ],
        'change.correlation': [
            'query_recent_changes_tool', 'query_alerts_tool',
            'query_cmdb_items_tool', 'query_cmdb_topology_tool',
            'query_knowledge_graph_tool', 'query_k8s_cluster_summary_tool',
        ],
        'zabbix.problem_analysis': [
            'query_zabbix_problems_tool', 'query_zabbix_hosts_tool',
            'query_zabbix_items_tool', 'query_zabbix_history_tool',
            'query_zabbix_host_metrics_tool', 'query_device_detail_tool',
        ],
        'cross_system.root_cause': [
            'query_alerts_tool', 'query_knowledge_graph_tool',
            'query_cmdb_items_tool', 'query_cmdb_topology_tool',
            'query_logs_tool', 'query_traces_tool',
            'query_k8s_cluster_summary_tool', 'query_recent_changes_tool',
            'query_zabbix_problems_tool',
        ],
        'cmdb.query': [
            'query_cmdb_items_tool', 'query_cmdb_topology_tool',
            'query_knowledge_graph_tool',
        ],
        'host_task.generate': [
            'query_zabbix_hosts_tool', 'query_zabbix_items_tool',
            'query_zabbix_host_metrics_tool', 'query_cmdb_items_tool',
        ],
    }
    tool_names = ACTION_TOOL_MAP.get(action_code, get_tool_names())
    return [t for t in SXDEVOPS_TOOLS if t.name in tool_names]
