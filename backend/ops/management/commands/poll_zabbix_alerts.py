"""Zabbix 告警轮询命令.

从所有启用的 Zabbix 数据源拉取活跃问题，通过统一告警流水线导入 Alert 模型。
内置调度器（observability_scheduler）默认每 5 分钟自动轮询，本命令用于手动触发。

用法:
    python manage.py poll_zabbix_alerts
    python manage.py poll_zabbix_alerts --datasource-id 1
    python manage.py poll_zabbix_alerts --dry-run
"""
from django.core.management.base import BaseCommand


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

        from ops.zabbix_polling import poll_zabbix_alerts_once

        stats = poll_zabbix_alerts_once(
            datasource_id=datasource_id, dry_run=dry_run, out=self.stdout)

        for err in stats['errors']:
            self.stderr.write(self.style.ERROR(f'  {err}'))

        if stats['datasource_count'] == 0:
            if datasource_id:
                self.stderr.write(self.style.ERROR(f'未找到 ID={datasource_id} 的启用数据源'))
            else:
                self.stdout.write(self.style.WARNING('没有启用的 Zabbix 数据源，跳过轮询'))
