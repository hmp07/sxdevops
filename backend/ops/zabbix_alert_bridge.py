"""Zabbix Problem → SxDevOps Alert 桥接模块.

将 Zabbix API 返回的问题数据通过统一告警流水线导入 Alert 模型。
支持定时轮询和 Webhook 两种触发方式。
"""
import logging

from django.utils.timezone import now

SEVERITY_MAP = {0: 'info', 1: 'info', 2: 'warning', 3: 'warning', 4: 'critical', 5: 'critical'}
SEVERITY_RESULT_MAP = {0: 'info', 1: 'info', 2: 'warning', 3: 'partial', 4: 'failed', 5: 'failed'}


def _record_event(alert, created, status_changed=False):
    """将告警导入操作记录到 EventWall（仅创建或状态变化时调用）"""
    try:
        from eventwall.services import record_event
        record_event(
            module='ops',
            category='alert',
            action='zabbix_problem_import' if created else 'zabbix_problem_update',
            title=f'Zabbix 告警: {alert.title[:120]}',
            summary=f'来源: Zabbix API, 级别: {alert.level}, 状态: {alert.status}',
            result=SEVERITY_RESULT_MAP.get(
                int((alert.raw_payload or {}).get('severity', 0)), 'info'
            ) if created else 'success',
            resource_type='zabbix_event',
            resource_id=alert.external_id,
            resource_name=alert.title[:200],
            environment=alert.environment or '',
            metadata={'status_changed': bool(status_changed)},
        )
    except ImportError:
        pass


def resolve_problem_host(client, problem):
    """解析 problem 的关联主机：返回 (host_name 技术名, host_id, visible_name 可见名)。

    通过 trigger.get 的 selectHosts 获取；失败时返回 ('', '', '')。
    """
    trigger_id = problem.get('objectid', '')
    if not trigger_id:
        return '', '', ''
    try:
        resp = client.get_triggers(trigger_ids=[trigger_id])
    except Exception:
        return '', '', ''
    if isinstance(resp, list) and resp and resp[0].get('hosts'):
        h = resp[0]['hosts'][0]
        return (
            str(h.get('host', '') or ''),
            str(h.get('hostid', '') or ''),
            str(h.get('name', '') or ''),
        )
    return '', '', ''


def _unified_fingerprint(problem):
    """与 webhook 路径完全一致的指纹算法（双路径去重的关键）。

    webhook 侧经 normalize_alert_payload → _fingerprint('zabbix', {'fingerprint': triggerid 优先})
    → sha256('zabbix:{triggerid}')；此处复用同一 _fingerprint 实现，杜绝算法漂移。
    """
    from ops.alerting import _fingerprint

    trigger_id = str(problem.get('objectid') or problem.get('triggerid') or problem.get('trigger_id') or '')
    event_id = str(problem.get('eventid') or problem.get('event_id') or '')
    base = trigger_id or event_id
    if not base:
        return ''
    return _fingerprint('zabbix', {'fingerprint': base, 'external_id': event_id})


def _build_normalized(problem, host_name='', host_id='', visible_name='', env_name=''):
    """将 Zabbix problem 构建为统一告警流水线的标准化字典"""
    event_id = str(problem.get('eventid', ''))
    severity = int(problem.get('severity', 0))

    r_eventid = problem.get('r_eventid')
    # Zabbix JSON-RPC 返回数值字段为字符串，活跃问题的 r_eventid 为 "0"
    is_active = r_eventid in (None, '', '0', 0, 0.0)

    return {
        'title': problem.get('name', 'Zabbix 告警')[:256],
        'level': SEVERITY_MAP.get(severity, 'warning'),
        'status': 'active' if is_active else 'resolved',
        'source': 'zabbix_api',
        'source_type': 'zabbix',
        'external_id': event_id,
        'fingerprint': _unified_fingerprint(problem),
        'group_key': '',
        'message': problem.get('name', ''),
        'resource_type': 'host',
        'resource': host_name or '',
        'environment': env_name or '',
        'labels': {
            'zabbix_severity': str(severity),
            'host': host_name or '',
            'hostname': visible_name or host_name or '',
            'zabbix_hostid': str(host_id or ''),
        },
        'annotations': {
            'acknowledged': str(problem.get('acknowledged', '')),
            'opdata': str(problem.get('opdata', '')),
        },
        'raw_payload': problem,
        'starts_at': _ts_to_datetime(problem.get('clock')) or now(),
        'ends_at': _ts_to_datetime(problem.get('r_clock')) if not is_active else None,
        'last_received_at': now(),
    }


from ops.alert_causality import _maybe_evaluate_causality


def upsert_alert_from_zabbix_problem(problem, host_name='', host_id='', visible_name='', env_name=''):
    """将 Zabbix problem 通过统一流水线转换为 Alert 并返回 (alert, created)"""
    from ops import alerting

    event_id = str(problem.get('eventid', ''))
    if not event_id:
        return None, False

    normalized = _build_normalized(problem, host_name, host_id, visible_name, env_name)
    # 轮询路径：重复更新不记审计行（仅创建与状态变化时记录）
    alert, created = alerting.upsert_alert(normalized, integration=None, actor='zabbix_poll', audit_update=False)

    if alert:
        # 主机业务线富化：使按业务线的抑制/静默规则对 Zabbix 告警生效
        if not alert.business_line and alert.host_id and alert.host.business_line:
            alert.business_line = alert.host.business_line
            alert.save(update_fields=['business_line'])
        try:
            _maybe_evaluate_causality(alert)
        except Exception:
            logging.getLogger(__name__).warning('causality hook failed for alert %s', alert.id, exc_info=True)
        alerting.apply_alert_suppression(alert)
        action = 'resolved' if alert.status == 'resolved' else 'fire'
        alerting.dispatch_alert_notifications(alert, action=action)
        # 事件仅在创建或状态变化时记录（轮询重复 update 不再刷事件墙）
        status_changed = bool(getattr(alert, '_status_changed', False))
        if created or status_changed:
            _record_event(alert, created, status_changed=status_changed)

    return alert, created


def _ts_to_datetime(ts):
    """Unix 时间戳转 datetime；缺失返回 None（ends_at 语义：无恢复时间即无值）。

    starts_at 的兜底由调用方处理（_build_normalized 中 `or now()`）。
    """
    if not ts:
        return None
    from datetime import datetime, timezone as tz
    return datetime.fromtimestamp(int(ts), tz=tz.utc)
