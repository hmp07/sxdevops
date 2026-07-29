"""
SubAgent 定义 — 替代 8 个硬编码 _run_*_evidence 收集函数。

3 个 SubAgent 对应 3 类分析场景：
1. alert-rca-agent     — 告警根因分析（替代 _run_alert_environment_analysis_evidence）
2. host-metrics-agent  — 主机指标分析（替代 _run_service_anomaly_evidence 的 Zabbix 部分）
3. cross-system-agent  — 跨系统关联分析（替代 _run_change_correlation_evidence）

每个 SubAgent 是 DeepAgents 的 SubAgent 规范，main agent 通过 task 工具调度。
"""

from __future__ import annotations

from typing import TypedDict


class SubAgentSpec(TypedDict, total=False):
    """DeepAgents SubAgent 定义规范。"""
    name: str
    description: str
    prompt: str
    tools: list[str]         # tool name 列表 (str)
    model: str               # 可选：独立模型
    max_iterations: int      # 最大工具调用轮次


# ── SubAgent 1: 告警根因分析 ──────────────────────────────────────────────

ALERT_RCA_SUBAGENT: SubAgentSpec = {
    "name": "alert-rca-agent",
    "description": (
        "告警根因分析专家。当需要分析告警原因、排查告警相关的日志/链路/K8s 事件时使用。"
        "典型触发词：告警原因、根因分析、为什么触发、排查、定位、分析这条告警。"
        "注意：简单的告警列表查询不需要此 agent，仅当需要深层分析时才调度。"
    ),
    "prompt": """你是告警根因分析专家。你的任务是综合分析多数据源，找出告警的真实原因。

分析流程：
1. **确认告警**：用 query_alerts_tool 或 query_zabbix_problems_tool 获取告警详情
2. **收集关联证据**：
   - 若有 K8s：用 query_k8s_cluster_summary_tool 查 Pod 状态
   - 若有日志源：用 query_logs_tool 查相关时间段的错误日志
   - 若有链路追踪：用 query_traces_tool 查异常 Span
   - 若有指标数据源：用 query_alert_metrics_tool 获取相关指标趋势
3. **根因判断**：综合以上证据，给出根本原因
4. **结构化输出**：
   - conclusion: 1-3 句话总结
   - key_evidence: 证据列表（含具体数值和来源）
   - risk_level: low / medium / high / critical
   - suggested_actions: 建议操作列表""",
    "tools": [
        "query_alerts_tool",
        "query_alert_root_cause_tool",
        "query_alert_metrics_tool",
        "query_zabbix_problems_tool",
        "query_logs_tool",
        "query_traces_tool",
        "query_k8s_cluster_summary_tool",
        "query_recent_changes_tool",
    ],
    "max_iterations": 4,
}


# ── SubAgent 2: 主机指标分析 ──────────────────────────────────────────────

HOST_METRICS_SUBAGENT: SubAgentSpec = {
    "name": "host-metrics-agent",
    "description": (
        "主机性能指标分析专家。当需要查 CPU/内存/磁盘/网络使用率、"
        "历史趋势、主机健康状态、性能瓶颈时使用。"
        "典型触发词：CPU、内存、磁盘、网络、使用率、性能、负载、趋势、瓶颈。"
    ),
    "prompt": """你是主机性能指标分析专家。你的任务是从 Zabbix 监控数据中分析主机运行状态。

分析流程：
1. **定位主机**：用 query_zabbix_hosts_tool 搜索主机名获取 hostid
2. **获取摘要**：用 query_zabbix_host_metrics_tool(hostid) 获取 CPU/内存/磁盘/网络四类指标
3. **深入分析**（如摘要中有异常）：
   - 用 query_zabbix_items_tool 搜索具体监控项
   - 用 query_zabbix_history_tool 获取历史数据
4. **完整视图**（如需要关联 CMDB）：用 query_device_detail_tool 获取全貌
5. **结构化输出**：
   - current_status: 当前各指标状态（含使用率百分比和阈值）
   - historical_trend: 历史趋势描述
   - anomalies: 异常项列表
   - recommendations: 优化建议""",
    "tools": [
        "query_zabbix_hosts_tool",
        "query_zabbix_items_tool",
        "query_zabbix_history_tool",
        "query_zabbix_host_metrics_tool",
        "query_device_detail_tool",
    ],
    "max_iterations": 5,
}


# ── SubAgent 3: 跨系统关联分析 ────────────────────────────────────────────

CROSS_SYSTEM_SUBAGENT: SubAgentSpec = {
    "name": "cross-system-agent",
    "description": (
        "跨系统关联分析专家。当需要分析变更影响范围、多系统依赖关系、"
        "上线风险评估、变更关联告警时使用。"
        "典型触发词：变更影响、依赖关系、上线风险、拓扑、影响范围、关联分析。"
    ),
    "prompt": """你是跨系统关联分析专家。你的任务是建立系统全貌，分析变更的潜在影响。

分析流程：
1. **建立上下文**：用 query_cmdb_items_tool + query_cmdb_topology_tool 建立系统依赖图
2. **关联变更**：用 query_recent_changes_tool 查最近的发布/工单
3. **关联告警**：用 query_alerts_tool 查相关系统的活跃告警
4. **关联基础设施**：用 query_k8s_cluster_summary_tool 查 K8s 状态
5. **关联知识图谱**：用 query_knowledge_graph_tool 获取业务关联
6. **结构化输出**：
   - impact_scope: 影响的系统和范围
   - risk_items: 风险项列表（含严重级别）
   - timeline: 关键时间线
   - recommendations: 应对建议""",
    "tools": [
        "query_cmdb_items_tool",
        "query_cmdb_topology_tool",
        "query_recent_changes_tool",
        "query_alerts_tool",
        "query_k8s_cluster_summary_tool",
        "query_knowledge_graph_tool",
        "query_zabbix_problems_tool",
    ],
    "max_iterations": 4,
}


# ── SubAgent 注册表 ───────────────────────────────────────────────────────

ALL_SUBAGENTS: list[SubAgentSpec] = [
    ALERT_RCA_SUBAGENT,
    HOST_METRICS_SUBAGENT,
    CROSS_SYSTEM_SUBAGENT,
]


def get_subagent_by_name(name: str) -> SubAgentSpec | None:
    """按名称查找 SubAgent 定义。"""
    for sa in ALL_SUBAGENTS:
        if sa['name'] == name:
            return sa
    return None


def get_subagents_for_action(action_code: str) -> list[SubAgentSpec]:
    """
    按 action 类型返回应激活的 SubAgent 列表。

    映射自原 _agent_sequence_for_action() / _run_*_evidence 的逻辑：
    - alert.root_cause        → alert-rca-agent
    - zabbix.problem_analysis → alert-rca-agent
    - k8s.diagnose            → alert-rca-agent
    - change.correlation      → cross-system-agent
    - cross_system.root_cause → cross-system-agent + alert-rca-agent
    - slo.analysis            → cross-system-agent
    - host_task.generate      → host-metrics-agent
    """
    mapping = {
        'alert.root_cause': [ALERT_RCA_SUBAGENT],
        'zabbix.problem_analysis': [ALERT_RCA_SUBAGENT],
        'k8s.diagnose': [ALERT_RCA_SUBAGENT],
        'change.correlation': [CROSS_SYSTEM_SUBAGENT],
        'cross_system.root_cause': [CROSS_SYSTEM_SUBAGENT, ALERT_RCA_SUBAGENT],
        'slo.analysis': [CROSS_SYSTEM_SUBAGENT],
        'host_task.generate': [HOST_METRICS_SUBAGENT],
        'itop.change_impact': [CROSS_SYSTEM_SUBAGENT],
    }
    return mapping.get(action_code, [])
