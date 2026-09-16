"""存量 Zabbix 指标路由标记 config 回填命令。

历史生成的 'Zabbix - <数据源名>' 标记（tsdb_type='zabbix'）config 为空，
导致指标查询无法定位对应 Zabbix 数据源（只能回落全局默认）。本命令按
名称模式反查 ZabbixDataSource 回填 config.zabbix_datasource_id。

用法:
    python manage.py backfill_zabbix_metric_markers          # dry-run 预览
    python manage.py backfill_zabbix_metric_markers --yes    # 执行回填（幂等）
"""

from django.core.management.base import BaseCommand

from ops.models import MetricDataSource, ZabbixDataSource


class Command(BaseCommand):
    help = '回填 Zabbix 指标路由标记的 config.zabbix_datasource_id'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='确认执行（默认 dry-run）')

    def handle(self, *args, **options):
        confirm = options['yes']

        candidates = MetricDataSource.objects.filter(tsdb_type='zabbix').order_by('id')
        matched = 0
        unmatched = 0
        for marker in candidates:
            config = marker.config if isinstance(marker.config, dict) else {}
            if config.get('zabbix_datasource_id'):
                continue  # 已回填，幂等跳过
            prefix = 'Zabbix - '
            ds_name = marker.name[len(prefix):] if marker.name.startswith(prefix) else marker.name
            ds = ZabbixDataSource.objects.filter(name=ds_name, is_enabled=True).first()
            if ds is None:
                unmatched += 1
                continue
            matched += 1
            self.stdout.write(
                f'{"[执行]" if confirm else "[预检]"} 标记 #{marker.id} "{marker.name}"'
                f' -> Zabbix 数据源 #{ds.id} "{ds.name}"')
            if confirm:
                config['zabbix_datasource_id'] = ds.id
                MetricDataSource.objects.filter(id=marker.id).update(config=config)

        self.stdout.write(
            f'完成: 可回填 {matched} 个标记，无法匹配 {unmatched} 个'
            + ('' if confirm else '（dry-run，未写入）'))
        if not confirm:
            self.stdout.write(self.style.WARNING('dry-run 模式：确认后执行 --yes'))
