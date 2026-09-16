"""存量 Zabbix 主机业务线/环境标注回填命令。

按 Zabbix 数据源「默认业务线/默认主机环境」回填 source='zabbix' 的主机：
  - business_line：数据源默认值权威覆盖
  - environment：仅当主机环境为空时写入（不覆盖人工标注）
多数据源时以第一个启用数据源（-is_default 优先）的默认值为准。

用法:
    python manage.py backfill_zabbix_host_annotations          # dry-run 预览
    python manage.py backfill_zabbix_host_annotations --yes    # 执行回填（幂等）
"""

from django.core.management.base import BaseCommand

from ops.models import Host, ZabbixDataSource


class Command(BaseCommand):
    help = '按 Zabbix 数据源默认值回填主机业务线/环境标注'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='确认执行（默认 dry-run）')

    def handle(self, *args, **options):
        confirm = options['yes']

        ds = ZabbixDataSource.objects.filter(is_enabled=True).order_by('-is_default', 'name').first()
        if ds is None:
            self.stdout.write(self.style.WARNING('没有启用的 Zabbix 数据源，跳过'))
            return

        bl_updates = 0
        env_updates = 0
        for host in Host.objects.filter(source='zabbix', external_id__startswith='zabbix:'):
            if ds.business_line and host.business_line != ds.business_line:
                bl_updates += 1
                if confirm:
                    Host.objects.filter(id=host.id).update(business_line=ds.business_line)
            if ds.host_environment and not host.environment:
                env_updates += 1
                if confirm:
                    Host.objects.filter(id=host.id).update(environment=ds.host_environment)

        self.stdout.write(
            f'数据源 "{ds.name}": 业务线可回填 {bl_updates} 台，环境可回填 {env_updates} 台'
            + ('' if confirm else '（dry-run，未写入）'))
        if not confirm:
            self.stdout.write(self.style.WARNING('dry-run 模式：确认后执行 --yes'))
