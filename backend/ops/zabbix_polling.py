"""Zabbix 告警轮询服务 — 供管理命令与内置调度器共用。"""

from django.utils.timezone import now

from ops.models import ZabbixDataSource
from ops.zabbix_alert_bridge import resolve_problem_host, upsert_alert_from_zabbix_problem
from ops.zabbix_client import ZabbixClient


def _log(out, msg):
    if out is not None:
        out.write(msg)


def poll_zabbix_alerts_once(datasource_id=None, dry_run=False, out=None):
    """单轮轮询启用 Zabbix 数据源的问题并导入告警。

    out: 可选 stdout 类对象（None 则静默）。
    返回 {'datasource_count', 'problem_count', 'created', 'updated', 'errors'}。
    """
    if datasource_id:
        sources = ZabbixDataSource.objects.filter(id=datasource_id, is_enabled=True)
    else:
        sources = ZabbixDataSource.objects.filter(is_enabled=True)

    stats = {
        'datasource_count': 0,
        'problem_count': 0,
        'created': 0,
        'updated': 0,
        'errors': [],
    }

    for ds in sources:
        stats['datasource_count'] += 1
        _log(out, f'正在从 "{ds.name}" ({ds.api_url}) 拉取告警...\n')
        try:
            client = ZabbixClient(ds)
            result = client.get_problems()
            if not isinstance(result, list):
                error = result.get('error', '未知错误') if isinstance(result, dict) else '未知错误'
                stats['errors'].append(f'{ds.name}: {error}')
                continue
            problems = result
            stats['problem_count'] += len(problems)
            _log(out, f'  获取到 {len(problems)} 个活跃问题\n')

            if dry_run:
                for p in problems[:5]:
                    _log(out, f'    [DRY-RUN] {p.get("name", "-")[:80]} '
                              f'severity={p.get("severity")} eventid={p.get("eventid")}\n')
                continue

            env_name = ds.environment or ds.name
            for problem in problems:
                try:
                    host_name, host_id, visible_name = resolve_problem_host(client, problem)
                    if not host_name and host_id:
                        # 兜底：通过 DeviceMapping 按 hostid 查找 iTop CI 名
                        from ops.models import DeviceMapping
                        dm = DeviceMapping.objects.filter(
                            zabbix_hostid=host_id
                        ).select_related('config_item').first()
                        if dm and dm.config_item:
                            host_name = dm.config_item.name
                    alert, is_new = upsert_alert_from_zabbix_problem(
                        problem, host_name=host_name, host_id=host_id,
                        visible_name=visible_name, env_name=env_name)
                    if alert:
                        if is_new:
                            stats['created'] += 1
                        else:
                            stats['updated'] += 1
                except Exception as exc:
                    stats['errors'].append(f'{ds.name} problem={problem.get("eventid", "")}: {exc}')

            ds.last_sync_at = now()
            ds.save(update_fields=['last_sync_at'])
        except Exception as exc:
            stats['errors'].append(f'{ds.name}: {exc}')

    _log(out, f'轮询完成: 共 {stats["created"] + stats["updated"]} 条告警 '
              f'(新建 {stats["created"]}，更新 {stats["updated"]})\n')
    return stats
