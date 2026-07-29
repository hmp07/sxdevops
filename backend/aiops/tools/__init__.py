"""
AIOps 工具实现层 — 所有 16 个 query_* 函数的独立模块。

从 services.py 拆分而来，按数据源领域组织：
- alerts.py:    告警中心查询
- zabbix.py:     Zabbix 监控查询
- cmdb.py:       CMDB 配置项查询
- observability: 日志/链路/指标查询
- infrastructure: K8s/主机/容器查询
- knowledge:     知识图谱查询
- changes:       变更/设备详情查询
- registry:      唯一工具注册表
- mcp:           Platform MCP 服务端逻辑
"""

from .alerts import query_alerts, query_alert_root_cause, query_alert_metrics
from .changes import query_recent_changes, query_device_detail
from .cmdb import query_cmdb_items, query_cmdb_topology
from .infrastructure import query_k8s_cluster_summary
from .knowledge import query_knowledge_graph
from .observability import query_logs, query_traces
from .registry import TOOL_REGISTRY, get_tool_by_handler, list_tool_handlers
from .zabbix import (
    query_zabbix_history,
    query_zabbix_host_metrics,
    query_zabbix_hosts,
    query_zabbix_items,
    query_zabbix_problems,
)

__all__ = [
    'TOOL_REGISTRY',
    'get_tool_by_handler',
    'list_tool_handlers',
    'query_alert_metrics',
    'query_alert_root_cause',
    'query_alerts',
    'query_cmdb_items',
    'query_cmdb_topology',
    'query_device_detail',
    'query_k8s_cluster_summary',
    'query_knowledge_graph',
    'query_logs',
    'query_recent_changes',
    'query_traces',
    'query_zabbix_history',
    'query_zabbix_host_metrics',
    'query_zabbix_hosts',
    'query_zabbix_items',
    'query_zabbix_problems',
]
