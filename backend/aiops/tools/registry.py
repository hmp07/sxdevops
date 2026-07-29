"""
唯一工具注册表 — 合并 PLATFORM_MCP_TOOL_DEFINITIONS + SXDEVOPS_TOOLS。

这是 aiops 模块中所有工具的单一注册点。新增工具只需在此文件中添加一个条目。
替代：
  - services.py 中的 PLATFORM_MCP_TOOL_DEFINITIONS (行 10177)
  - deepagents_engine/tools.py 中的 SXDEVOPS_TOOLS
"""

from __future__ import annotations

from typing import Optional

# ── 工具注册表定义 ──────────────────────────────────────────────────────

TOOL_REGISTRY: list[dict] = [
    {
        'name': 'sxdevops.query_knowledge_graph',
        'title': '查询 AIOps 知识图谱',
        'description': '按环境、系统或服务查询平台知识图谱节点和关系。',
        'permission': 'aiops.knowledge.view',
        'handler': 'query_knowledge_graph',
        'deepagents_name': 'query_knowledge_graph_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'environment': {'type': 'string'},
                'system_name': {'type': 'string'},
                'service': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_alerts',
        'title': '查询告警',
        'description': '查询告警中心只读告警事实。',
        'permission': 'ops.alert.view',
        'handler': 'query_alerts',
        'deepagents_name': 'query_alerts_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'level': {'type': 'string'},
                'status': {'type': 'string'},
                'date_filter': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_alert_root_cause',
        'title': '分析告警根因',
        'description': '分析单条告警的根因，综合 K8s、事件、日志、链路和指标证据。用户给出告警 ID/指纹，或询问某环境最新告警的原因、根因、为什么、怎么处理时必须使用本工具。',
        'permission': 'ops.alert.view',
        'handler': 'query_alert_root_cause',
        'deepagents_name': 'query_alert_root_cause_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'alert_id': {'type': 'integer', 'minimum': 1},
                'fingerprint': {'type': 'string'},
                'latest': {'type': 'boolean'},
            },
        },
    },
    {
        'name': 'sxdevops.query_alert_metrics',
        'title': '查询告警指标证据包',
        'description': '按告警上下文生成受预算约束的 PromQL 查询计划，返回指标趋势和异常摘要。',
        'permission': 'ops.metric.query',
        'handler': 'query_alert_metrics',
        'deepagents_name': 'query_alert_metrics_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'alert_id': {'type': 'integer', 'minimum': 1},
                'fingerprint': {'type': 'string'},
                'latest': {'type': 'boolean'},
                'duration_minutes': {'type': 'integer', 'minimum': 15, 'maximum': 120},
                'step': {'type': 'integer', 'minimum': 15, 'maximum': 3600},
                'budget': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                'metric_datasource_id': {'type': 'integer', 'minimum': 1},
            },
        },
    },
    {
        'name': 'sxdevops.query_logs',
        'title': '查询日志',
        'description': '查询平台日志源中的只读日志样本。',
        'permission': 'ops.log.query',
        'handler': 'query_logs',
        'deepagents_name': 'query_logs_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'service': {'type': 'string'},
                'level': {'type': 'string'},
                'duration_minutes': {'type': 'integer', 'minimum': 1, 'maximum': 1440},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_traces',
        'title': '查询链路',
        'description': '查询链路追踪只读样本和异常链路。',
        'permission': 'ops.trace.view',
        'handler': 'query_traces',
        'deepagents_name': 'query_traces_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'errors_only': {'type': 'boolean'},
                'duration_minutes': {'type': 'integer', 'minimum': 1, 'maximum': 1440},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_k8s_cluster_summary',
        'title': '查询 K8s 集群摘要',
        'description': '查询 Kubernetes 集群、Pod 和异常摘要。',
        'permission': 'ops.k8s.view',
        'handler': 'query_k8s_cluster_summary',
        'deepagents_name': 'query_k8s_cluster_summary_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'cluster_name': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_recent_changes',
        'title': '查询最近变更',
        'description': '查询最近发布、工单和事件候选变更。',
        'permission': 'ops.deployment.view',
        'handler': 'query_recent_changes',
        'deepagents_name': 'query_recent_changes_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
            },
        },
    },
    {
        'name': 'sxdevops.query_zabbix_hosts',
        'title': '查询 Zabbix 主机',
        'description': '查询 Zabbix 监控系统的主机列表，包含主机名、状态、可用性和 IP 地址。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_zabbix_hosts',
        'deepagents_name': 'query_zabbix_hosts_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'search': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50},
            },
        },
    },
    {
        'name': 'sxdevops.query_zabbix_problems',
        'title': '查询 Zabbix 告警问题',
        'description': '查询 Zabbix 当前活跃的告警问题，包含问题描述、严重级别、确认状态。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_zabbix_problems',
        'deepagents_name': 'query_zabbix_problems_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'min_severity': {'type': 'integer', 'minimum': 0, 'maximum': 5},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50},
            },
        },
    },
    {
        'name': 'sxdevops.query_zabbix_items',
        'title': '查询 Zabbix 监控项',
        'description': '查询指定主机的监控项列表及最新值，包含监控项名称、键值、最新数值和单位。需要先通过 query_zabbix_hosts 获取主机 ID。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_zabbix_items',
        'deepagents_name': 'query_zabbix_items_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'host_ids': {'type': 'array', 'items': {'type': 'integer'}},
                'search': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50},
            },
        },
    },
    {
        'name': 'sxdevops.query_zabbix_history',
        'title': '查询 Zabbix 历史数据',
        'description': '查询指定监控项的历史数据，用于绘制趋势图或分析指标变化。需要先通过 query_zabbix_items 获取监控项 ID 和 value_type。支持自动探测 value_type，也可手动指定（0=float, 1=char, 3=unsigned, 4=text）。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_zabbix_history',
        'deepagents_name': 'query_zabbix_history_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'item_ids': {'type': 'array', 'items': {'type': 'integer'}},
                'value_type': {'type': 'integer', 'minimum': 0, 'maximum': 4},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50},
            },
        },
    },
    {
        'name': 'sxdevops.query_zabbix_host_metrics',
        'title': '查询 Zabbix 主机核心指标',
        'description': '一次查询获取主机的 CPU 使用率、内存、文件系统、网络流量四类核心性能指标摘要。用于快速评估主机健康状态，无需多次调用 query_zabbix_items。需要先通过 query_zabbix_hosts 获取主机 hostid。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_zabbix_host_metrics',
        'deepagents_name': 'query_zabbix_host_metrics_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'hostid': {'type': 'string'},
                'datasource_id': {'type': 'integer'},
            },
            'required': ['hostid'],
        },
    },
    {
        'name': 'sxdevops.query_device_detail',
        'title': '查询设备完整信息',
        'description': '查询设备的 Zabbix 监控与 iTop CMDB 合并视图。输入主机名或 IP 即可获取监控状态、CMDB 属性、关联工单。',
        'permission': 'ops.zabbix.view',
        'handler': 'query_device_detail',
        'deepagents_name': 'query_device_detail_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'hostname': {'type': 'string'},
            },
        },
    },
    {
        'name': 'sxdevops.query_cmdb_items',
        'title': '查询 CMDB 配置项',
        'description': '查询平台 CMDB 中的配置项（CI），包括业务系统(ApplicationSolution)、服务器、数据库、中间件等。可按业务线、环境、关键词过滤。用于回答"有哪些系统"、"电商平台包含哪些服务器"等问题。',
        'permission': 'cmdb.ci.view',
        'handler': 'query_cmdb_items',
        'deepagents_name': 'query_cmdb_items_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'environment': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 6},
            },
        },
    },
    {
        'name': 'sxdevops.query_cmdb_topology',
        'title': '查询 CMDB 资源拓扑',
        'description': '查询 CMDB 中指定业务线或 CI 的拓扑关系（上下游依赖图）。用于影响分析、根因定位、"电商平台依赖哪些数据库"等问题。',
        'permission': 'cmdb.topology.view',
        'handler': 'query_cmdb_topology',
        'deepagents_name': 'query_cmdb_topology_tool',
        'input_schema': {
            'type': 'object',
            'properties': {
                'business_line': {'type': 'string'},
                'ci_name': {'type': 'string'},
                'scope': {'type': 'string', 'enum': ['exact', 'neighbors'], 'default': 'neighbors'},
            },
        },
    },
]


# ── 查询函数 ────────────────────────────────────────────────────────────


def get_tool_by_handler(handler_name: str) -> Optional[dict]:
    """按 handler 名称查找工具定义。"""
    for tool in TOOL_REGISTRY:
        if tool['handler'] == handler_name:
            return tool
    return None


def get_tool_by_deepagents_name(name: str) -> Optional[dict]:
    """按 deepagents @tool 名称查找工具定义。"""
    for tool in TOOL_REGISTRY:
        if tool.get('deepagents_name') == name:
            return tool
    return None


def list_tool_handlers() -> list[str]:
    """返回所有 handler 名称列表。"""
    return [t['handler'] for t in TOOL_REGISTRY]


def list_deepagents_names() -> list[str]:
    """返回所有 deepagents tool 名称列表。"""
    return [t['deepagents_name'] for t in TOOL_REGISTRY]
