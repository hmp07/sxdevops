"""Zabbix Problem → SxDevOps Alert 桥接模块.

将 Zabbix API 返回的问题数据通过统一告警流水线导入 Alert 模型。
支持定时轮询和 Webhook 两种触发方式。
"""
from django.utils.timezone import now

SEVERITY_MAP = {0: 'info', 1: 'info', 2: 'warning', 3: 'warning', 4: 'critical', 5: 'critical'}
SEVERITY_RESULT_MAP = {0: 'info', 1: 'info', 2: 'warning', 3: 'partial', 4: 'failed', 5: 'failed'}


def _record_event(alert, created):
    """将告警导入操作记录到 EventWall"""
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
        )
    except ImportError:
        pass


def _build_normalized(problem, host_name='', env_name=''):
    """将 Zabbix problem 构建为统一告警流水线的标准化字典"""
    event_id = str(problem.get('eventid', ''))
    severity = int(problem.get('severity', 0))

    return {
        'title': problem.get('name', 'Zabbix 告警')[:256],
        'level': SEVERITY_MAP.get(severity, 'warning'),
        'status': 'active' if not problem.get('r_eventid') else 'resolved',
        'source': 'zabbix_api',
        'source_type': 'zabbix',
        'external_id': event_id,
        'fingerprint': f'zabbix:{event_id}',
        'group_key': '',
        'message': problem.get('name', ''),
        'resource_type': 'host',
        'resource': host_name or '',
        'environment': env_name or '',
        'labels': {'zabbix_severity': str(severity), 'host': host_name or '', 'hostname': host_name or ''},
        'annotations': {
            'acknowledged': str(problem.get('acknowledged', '')),
            'opdata': str(problem.get('opdata', '')),
        },
        'raw_payload': problem,
        'starts_at': _ts_to_datetime(problem.get('clock')),
        'ends_at': _ts_to_datetime(problem.get('r_clock')) if problem.get('r_eventid') else None,
        'last_received_at': now(),
    }


def upsert_alert_from_zabbix_problem(problem, host_name='', env_name=''):
    """将 Zabbix problem 通过统一流水线转换为 Alert 并返回 (alert, created)"""
    from ops import alerting

    event_id = str(problem.get('eventid', ''))
    if not event_id:
        return None, False

    normalized = _build_normalized(problem, host_name, env_name)
    alert, created = alerting.upsert_alert(normalized, integration=None, actor='zabbix_poll')

    if alert:
        alerting.apply_alert_suppression(alert)
        action = 'resolved' if alert.status == 'resolved' else 'fire'
        alerting.dispatch_alert_notifications(alert, action=action)
        _record_event(alert, created)

    return alert, created


def _ts_to_datetime(ts):
    """Unix 时间戳转 datetime"""
    if not ts:
        return now()
    from datetime import datetime, timezone as tz
    return datetime.fromtimestamp(int(ts), tz=tz.utc)
