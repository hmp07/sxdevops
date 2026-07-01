"""Zabbix Problem → SxDevOps Alert 桥接模块.

提供将 Zabbix API 返回的问题数据转换为 SxDevOps Alert 模型的工具函数。
同时写入 EventWall 事件墙，便于故障复盘。
可通过 Webhook 或定时轮询两种方式触发。
"""
from django.utils.timezone import now
from ops.models import Alert

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


def upsert_alert_from_zabbix_problem(problem, host_name=''):
    """将 Zabbix problem 转换为 Alert 并 upsert"""
    event_id = str(problem.get('eventid', ''))
    if not event_id:
        return None

    alert, created = Alert.objects.update_or_create(
        fingerprint=f'zabbix:{event_id}',
        defaults={
            'title': problem.get('name', 'Zabbix 告警')[:256],
            'level': SEVERITY_MAP.get(int(problem.get('severity', 0)), 'warning'),
            'status': 'active' if not problem.get('r_eventid') else 'resolved',
            'source_type': 'zabbix',
            'source': 'zabbix_api',
            'external_id': event_id,
            'host': None,
            'resource': host_name or '',
            'starts_at': _ts_to_datetime(problem.get('clock')),
            'last_received_at': now(),
            'labels': {'zabbix_severity': str(problem.get('severity', ''))},
            'annotations': {'acknowledged': str(problem.get('acknowledged', ''))},
            'raw_payload': problem,
        },
    )
    _record_event(alert, created)
    return alert


def _ts_to_datetime(ts):
    """Unix 时间戳转 datetime"""
    if not ts:
        return now()
    from datetime import datetime, timezone as tz
    return datetime.fromtimestamp(int(ts), tz=tz.utc)
