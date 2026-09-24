"""L1 确定性因果收敛：告警码字典 + 默认因果规则（V2.0 本体方案轻量化落点）。

- ALERT_CODE_DICTIONARY：附录 A 告警码字典（31 条）+ TABLESPACE_FULL（D1 前件所需，附录未列）
- DEFAULT_CAUSAL_RULES：仅确定性 L1 规则，SWRL 语义规范（§4.3）的数据转写；
  纯合取、一规则一目标码、运行期物化由 evaluate_alert_causality 完成
"""

ALERT_CODE_DICTIONARY = {
    'HOST_DOWN': {'name': '主机宕机/离线', 'level': 'root', 'typical_cause': '硬件故障、断电、OS崩溃'},
    'STORAGE_IO_TIMEOUT': {'name': '存储卷IO超时', 'level': 'root', 'typical_cause': '存储性能劣化、链路异常'},
    'STORAGE_FULL': {'name': '存储卷写满', 'level': 'root', 'typical_cause': '容量耗尽'},
    'PORT_DOWN': {'name': '交换机端口Down', 'level': 'root', 'typical_cause': '链路/光模块/对端故障'},
    'PACKET_LOSS_HIGH': {'name': '端口丢包率过高', 'level': 'root', 'typical_cause': '链路质量、拥塞'},
    'TABLESPACE_FULL': {'name': '表空间使用率超限', 'level': 'root', 'typical_cause': '表空间使用率>99%（D1 前件）'},
    'NETWORK_ABNORMAL': {'name': '主机网络异常', 'level': 'derived', 'typical_cause': '交换机端口故障'},
    'ORA-03113': {'name': '通信通道EOF（连接中断）', 'level': 'derived', 'typical_cause': '网络闪断、会话被切断'},
    'ORA-12535': {'name': 'TNS操作超时', 'level': 'derived', 'typical_cause': '网络不通、防火墙拦截'},
    'ORA-03137': {'name': 'TTC协议内部错误', 'level': 'derived', 'typical_cause': '网络闪断/空闲连接被中段设备切断'},
    'ORA-12541': {'name': 'TNS:no listener', 'level': 'derived', 'typical_cause': '监听进程宕机'},
    'ORA-12514': {'name': '监听不认识该service', 'level': 'derived', 'typical_cause': '实例未注册/服务名错误'},
    'ORA-01653': {'name': '表空间无法扩展', 'level': 'derived', 'typical_cause': '表空间使用率>99%'},
    'DB_HANG': {'name': '数据库挂起', 'level': 'derived', 'typical_cause': '归档目的地满'},
    'DB_IO_DEGRADED': {'name': '数据库IO性能劣化', 'level': 'derived', 'typical_cause': '存储IO超时'},
    'DB_WRITE_BLOCKED': {'name': '数据库写入阻塞', 'level': 'derived', 'typical_cause': '存储卷写满'},
    'INSTANCE_DOWN': {'name': '数据库实例宕机', 'level': 'root', 'typical_cause': '实例崩溃或主机宕机'},
    'INSTANCE_UNREACHABLE': {'name': '实例不可达', 'level': 'derived', 'typical_cause': '主机宕机'},
    'BLOCKING_LOCK': {'name': '阻塞锁/锁等待', 'level': 'root', 'typical_cause': '长事务、死锁'},
    'DB_LOCK_TIMEOUT': {'name': '锁等待超时', 'level': 'derived', 'typical_cause': '阻塞锁传导'},
    'LISTENER_DOWN': {'name': '监听进程宕机', 'level': 'root', 'typical_cause': '监听进程异常退出'},
    'SERVICE_UNREGISTERED': {'name': '服务未注册到监听', 'level': 'root', 'typical_cause': '实例未注册/动态注册失败'},
    'ARCHIVE_DEST_FULL': {'name': '归档目的地满', 'level': 'root', 'typical_cause': '归档磁盘耗尽'},
    'PROCESS_DOWN': {'name': '进程宕机', 'level': 'root', 'typical_cause': '进程异常退出'},
    'THREAD_POOL_EXHAUSTED': {'name': '线程池耗尽', 'level': 'root', 'typical_cause': '流量突增、慢请求堆积'},
    'CONN_POOL_EXHAUSTED': {'name': '连接池耗尽', 'level': 'root', 'typical_cause': '连接泄漏、慢SQL'},
    'API_TIMEOUT': {'name': '接口超时', 'level': 'derived', 'typical_cause': '中间件/数据库资源耗尽'},
    'ACCESS_FAILURE': {'name': '业务访问失败', 'level': 'derived', 'typical_cause': 'WebServer宕机'},
    'BUSINESS_ERROR': {'name': '微服务业务错误', 'level': 'root', 'typical_cause': '数据库不可用或代码异常'},
    'TRANSACTION_FAILURE': {'name': '业务交易失败', 'level': 'derived', 'typical_cause': '微服务业务错误'},
    'TRANSACTION_TIMEOUT': {'name': '业务交易超时', 'level': 'derived', 'typical_cause': '微服务API超时'},
    'DB_PERF_RISK': {'name': '数据库性能风险（候选）', 'level': 'candidate', 'typical_cause': '主机资源耗尽嫌疑'},
}

# 默认 L1 因果规则（与 V2.0 §4.3 规则 ID 对齐；SWRL 语义规范转写为可执行数据规则）
DEFAULT_CAUSAL_RULES = [
    {
        'code': 'B3', 'name': '监听宕机 → ORA-12541',
        'description': 'Oracle监听进程宕机，实例连接报 TNS:no listener（资源直配）',
        'source_alert_codes': ['LISTENER_DOWN'],
        'target_alert_codes': ['ORA-12541'],
        'relation_type_code': '',
        'direction': 'upstream',
        'max_hops': 0,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'D1', 'name': '表空间满 → ORA-01653',
        'description': '表空间使用率>99%，新数据插入报 ORA-01653（沿 contains/depends_on 上溯）',
        'source_alert_codes': ['TABLESPACE_FULL'],
        'target_alert_codes': ['ORA-01653'],
        'relation_type_code': 'contains',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'D2', 'name': '存储卷满 → DB_WRITE_BLOCKED',
        'description': '存储卷写满，数据库写入阻塞（沿 depends_on 上溯）',
        'source_alert_codes': ['STORAGE_FULL'],
        'target_alert_codes': ['DB_WRITE_BLOCKED'],
        'relation_type_code': 'depends_on',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'D2b', 'name': '存储IO超时 → DB_IO_DEGRADED',
        'description': '存储卷IO超时，数据库IO性能劣化（沿 depends_on 上溯）',
        'source_alert_codes': ['STORAGE_IO_TIMEOUT'],
        'target_alert_codes': ['DB_IO_DEGRADED'],
        'relation_type_code': 'depends_on',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'D3', 'name': '归档满 → DB_HANG',
        'description': '归档目的地满，数据库挂起（沿 depends_on 上溯）',
        'source_alert_codes': ['ARCHIVE_DEST_FULL'],
        'target_alert_codes': ['DB_HANG'],
        'relation_type_code': 'depends_on',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'B1', 'name': '主机宕机 → INSTANCE_UNREACHABLE',
        'description': '主机宕机，其上软件实例不可达（沿 hosted_on 上溯）',
        'source_alert_codes': ['HOST_DOWN'],
        'target_alert_codes': ['INSTANCE_UNREACHABLE'],
        'relation_type_code': 'hosted_on',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
    {
        'code': 'B2', 'name': '端口Down → NETWORK_ABNORMAL',
        'description': '交换机端口Down，主机网络异常（沿 connects_to 上溯）',
        'source_alert_codes': ['PORT_DOWN', 'PACKET_LOSS_HIGH'],
        'target_alert_codes': ['NETWORK_ABNORMAL'],
        'relation_type_code': 'connects_to',
        'direction': 'upstream',
        'max_hops': 5,
        'window_minutes': 5,
        'priority': 10,
    },
]


import logging
import os
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ops.models import Alert, AlertCausalRule

logger = logging.getLogger(__name__)

MAX_BFS_NODES = 20


def _causality_enabled():
    return os.environ.get('SXDEVOPS_ALERT_CAUSALITY_ENABLED', '1') not in ('0', 'false', 'False')


def evaluate_alert_causality(alert):
    """同步执行 L1 因果收敛（只标记，不删不静默，不触碰 status/抑制/静默字段）。

    任何异常吞掉并记日志，保证 ingest 主链路不受影响。
    """
    if not _causality_enabled():
        return None
    try:
        return _evaluate(alert)
    except Exception:
        logger.warning('evaluate_alert_causality failed for alert %s', alert.id, exc_info=True)
        return None


def _alert_ci_key(alert):
    return (alert.resource or '').strip() or (alert.host.hostname if alert.host_id else '').strip()


def _env_rule_whitelist(alert):
    """环境级 causal_rule_set：返回 (allowed_codes|None, enabled)。无匹配环境 → (None, True)。"""
    env_name = (alert.environment or '').strip()
    if not env_name:
        return None, True
    from aiops.models import AIOpsKnowledgeEnvironment
    for env in AIOpsKnowledgeEnvironment.objects.filter(is_enabled=True).only(
            'alert_environments', 'causal_rule_set'):
        if env_name in (env.alert_environments or []):
            rule_set = env.causal_rule_set or {}
            if rule_set.get('enabled') is False:
                return None, False
            rules = rule_set.get('rules') or []
            return (rules or None), True
    return None, True


def _find_ci_anchor(alert):
    """告警 → CMDB 配置项锚点：resource/host 名称精确匹配 → IP 属性匹配。"""
    from cmdb.models import ConfigItem
    key = _alert_ci_key(alert)
    if key:
        ci = ConfigItem.objects.filter(name=key).first()
        if ci:
            return ci
        try:
            ci = ConfigItem.objects.filter(attributes__ip_address=key).first()
            if ci:
                return ci
        except Exception:
            pass
    return None


def _walk_adjacent(start_ci, relation_code, max_hops):
    """BFS 邻接遍历（≤max_hops；max_hops=0 仅起点）。返回 (visited_ids, truncated)。"""
    from cmdb.models import CIRelation

    visited = {start_ci.id}
    frontier = {start_ci.id}
    for _ in range(max_hops):
        qs = CIRelation.objects.filter(Q(source_id__in=frontier) | Q(target_id__in=frontier))
        if relation_code:
            qs = qs.filter(relation_type_id=relation_code)
        next_ids = set()
        for rel in qs.values('source_id', 'target_id'):
            for ci_id in (rel['source_id'], rel['target_id']):
                if ci_id not in visited:
                    next_ids.add(ci_id)
        if not next_ids:
            break
        visited.update(next_ids)
        if len(visited) > MAX_BFS_NODES:
            return visited, True
        frontier = next_ids
    return visited, False


def _match_root_alert(alert, rule, ci_names):
    """时间窗 ±window_minutes 内、落在 visited CI 上的前件告警 → 根因告警。"""
    window = timedelta(minutes=max(1, rule.window_minutes or 5))
    anchor_time = alert.starts_at or alert.created_at
    candidates = Alert.objects.filter(
        alert_code__in=(rule.source_alert_codes or []),
        status=Alert.STATUS_ACTIVE,
    ).exclude(id=alert.id).filter(
        starts_at__gte=anchor_time - window,
        starts_at__lte=anchor_time + window,
    )
    for cand in candidates:
        key = _alert_ci_key(cand)
        if key and key in ci_names:
            return cand
    return None


def _mark(alert, root_alert, rule, path_names):
    """写标记：本告警 derived + 证据链；根因告警 root。不改 status/抑制/静默。"""
    chain_entry = {
        'rule_code': rule.code,
        'relation_code': rule.relation_type_code,
        'path': path_names,
        'root_code': root_alert.alert_code,
        'at': timezone.now().isoformat(),
    }
    alert.causal_level = 'derived'
    derived = list(alert.derived_from or [])
    if root_alert.id not in derived:
        derived.append(root_alert.id)
    alert.derived_from = derived
    chain = list(alert.evidence_chain or [])
    if not any(e.get('rule_code') == rule.code and e.get('root_code') == root_alert.alert_code for e in chain):
        chain.append(chain_entry)
        alert.evidence_chain = chain[-10:]
    alert.save(update_fields=['causal_level', 'derived_from', 'evidence_chain'])

    if root_alert.causal_level == 'none':
        root_alert.causal_level = 'root'
        root_alert.save(update_fields=['causal_level'])


def _evaluate(alert):
    from cmdb.models import ConfigItem

    if not alert.alert_code or alert.causal_level != 'none':
        return None
    if alert.is_suppressed or alert.status != Alert.STATUS_ACTIVE:
        return None
    if (alert.occurrence_count or 0) >= 5:
        return None

    anchor = _find_ci_anchor(alert)
    if not anchor:
        return None

    allowed, enabled = _env_rule_whitelist(alert)
    if not enabled:
        return None
    rules = AlertCausalRule.objects.filter(is_enabled=True)
    if allowed:
        rules = rules.filter(code__in=allowed)

    for rule in rules:
        if alert.alert_code not in (rule.target_alert_codes or []):
            continue
        visited, truncated = _walk_adjacent(anchor, rule.relation_type_code, rule.max_hops or 0)
        if truncated:
            return {'rule': rule.code, 'root_alert_id': None, 'path': [],
                    'converged': False, 'truncated': True}
        ci_names = [ci.name for ci in ConfigItem.objects.filter(id__in=visited).only('name')]
        root_alert = _match_root_alert(alert, rule, set(ci_names))
        if root_alert:
            _mark(alert, root_alert, rule, ci_names)
            return {'rule': rule.code, 'root_alert_id': root_alert.id, 'path': ci_names,
                    'converged': True, 'truncated': False}
    return None


def _maybe_evaluate_causality(alert):
    """ingest 挂载点：开关短路 + 异常兜底，绝不阻断告警主链路。"""
    if not _causality_enabled():
        return None
    try:
        return evaluate_alert_causality(alert)
    except Exception:
        logger.warning('_maybe_evaluate_causality failed for alert %s', getattr(alert, 'id', None), exc_info=True)
        return None
