"""Zabbix 告警轮询命令.

从所有启用的 Zabbix 数据源拉取活跃问题，通过统一告警流水线导入 Alert 模型。
建议通过 cron 或 Windows Task Scheduler 每 5 分钟执行一次。

用法:
    python manage.py poll_zabbix_alerts
    python manage.py poll_zabbix_alerts --datasource-id 1
    python manage.py poll_zabbix_alerts --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from ops.models import ZabbixDataSource
from ops.zabbix_client import ZabbixClient
from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem


class Command(BaseCommand):
    help = '从已配置的 Zabbix 数据源轮询活跃问题并导入告警中心'

    def add_arguments(self, parser):
        parser.add_argument(
            '--datasource-id', type=int, default=None,
            help='仅轮询指定 ID 的 Zabbix 数据源',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='仅拉取问题并显示统计，不实际写入 Alert',
        )

    def handle(self, **options):
        datasource_id = options.get('datasource_id')
        dry_run = options.get('dry_run', False)

        if datasource_id:
            sources = ZabbixDataSource.objects.filter(id=datasource_id, is_enabled=True)
            if not sources.exists():
                self.stderr.write(self.style.ERROR(f'未找到 ID={datasource_id} 的启用数据源'))
                return
        else:
            sources = ZabbixDataSource.objects.filter(is_enabled=True)
            if not sources.exists():
                self.stdout.write(self.style.WARNING('没有启用的 Zabbix 数据源，跳过轮询'))
                return

        total_created = 0
        total_updated = 0
        total_problems = 0

        for ds in sources:
            self.stdout.write(f'正在从 "{ds.name}" ({ds.api_url}) 拉取告警...')
            client = ZabbixClient(ds)

            result = client.get_problems()
            if 'error' in result:
                self.stderr.write(self.style.ERROR(f'  连接失败: {result["error"]}'))
                continue

            problems = result if isinstance(result, list) else []
            self.stdout.write(f'  获取到 {len(problems)} 个活跃问题')

            if dry_run:
                for p in problems[:5]:
                    self.stdout.write(f'    [DRY-RUN] {p.get("name", "-")[:80]} '
                                      f'severity={p.get("severity")} eventid={p.get("eventid")}')
                total_problems += len(problems)
                continue

            created = 0
            updated = 0
            for problem in problems:
                host_name = ''
                try:
                    # objectid 是触发器 ID，需通过 trigger.get 获取关联主机
                    triggers_resp = client.get_triggers(trigger_ids=[problem.get('objectid', '')])
                    if isinstance(triggers_resp, list) and triggers_resp:
                        hosts = triggers_resp[0].get('hosts', [])
                        if hosts:
                            host_name = hosts[0].get('host', '')
                except Exception:
                    pass

                alert, is_new = upsert_alert_from_zabbix_problem(problem, host_name=host_name, env_name=ds.name)
                if alert:
                    if is_new:
                        created += 1
                    else:
                        updated += 1

            # 更新数据源的最后同步时间
            ds.last_sync_at = now()
            ds.save(update_fields=['last_sync_at'])

            total_created += created
            total_updated += updated
            self.stdout.write(f'    新建 {created} 条，更新 {updated} 条')

        summary = f'轮询完成: 共 {total_created + total_updated} 条告警 (新建 {total_created}，更新 {total_updated})'
        if dry_run:
            summary = f'[DRY-RUN] {summary} — 共 {total_problems} 个问题，未实际写入'
        self.stdout.write(self.style.SUCCESS(summary))
