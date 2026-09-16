"""存量 Zabbix 告警主机关联回填命令。

历史入库的 zabbix 告警（Alert.host 为 NULL）按关联键回填：
  1. labels['zabbix_hostid'] → Host.external_id='zabbix:{hostid}'（优先）
  2. 文本兜底：labels['hostname'] / labels['host'] / resource → Host.hostname / ip_address

--refresh 时额外对启用数据源重拉当前问题并重新 upsert（幂等，fingerprint
相同走更新分支，自动补 host 关联）。

用法:
    python manage.py backfill_zabbix_alert_hosts                  # dry-run 预览
    python manage.py backfill_zabbix_alert_hosts --yes            # 执行离线回填
    python manage.py backfill_zabbix_alert_hosts --yes --refresh  # 离线 + 在线刷新
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from ops.models import Alert, Host, ZabbixDataSource


class Command(BaseCommand):
    help = '回填存量 Zabbix 告警的主机关联（Alert.host 为 NULL 的记录）'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='确认执行（默认 dry-run）')
        parser.add_argument('--refresh', action='store_true', help='在线刷新：重新拉取问题并 upsert（幂等）')

    def handle(self, *args, **options):
        confirm = options['yes']
        refresh = options['refresh']

        qs = Alert.objects.filter(source_type='zabbix', host__isnull=True).order_by('id')
        total = qs.count()
        self.stdout.write(f'候选告警（source_type=zabbix 且 host 为空）: {total} 条')

        matched = 0
        unmatched = 0
        for alert in qs:
            host = self._resolve_host(alert.labels or {}, alert.resource)
            if host is None:
                unmatched += 1
                continue
            matched += 1
            if confirm:
                Alert.objects.filter(id=alert.id).update(host=host)

        self.stdout.write(
            f'离线匹配: 可回填 {matched} 条，无法匹配 {unmatched} 条'
            + ('' if confirm else '（dry-run，未写入）')
        )

        if refresh:
            self._refresh(confirm)

        if not confirm:
            self.stdout.write(self.style.WARNING('dry-run 模式：确认后执行 --yes'))

    def _resolve_host(self, labels, resource):
        zid = str(labels.get('zabbix_hostid') or '').strip()
        if zid:
            host = Host.objects.filter(external_id=f'zabbix:{zid}').first()
            if host:
                return host
        for text in (labels.get('hostname'), labels.get('host'), resource):
            text = str(text or '').strip()
            if not text:
                continue
            host = Host.objects.filter(Q(hostname=text) | Q(ip_address=text)).first()
            if host:
                return host
        return None

    def _refresh(self, confirm):
        from ops.zabbix_alert_bridge import resolve_problem_host, upsert_alert_from_zabbix_problem
        from ops.zabbix_client import ZabbixClient

        for ds in ZabbixDataSource.objects.filter(is_enabled=True):
            client = ZabbixClient(ds)
            result = client.get_problems()
            if not isinstance(result, list):
                self.stderr.write(f'  数据源 {ds.name} 拉取失败，跳过')
                continue
            for p in result:
                try:
                    host_name, host_id, visible_name = resolve_problem_host(client, p)
                    if not confirm:
                        continue
                    upsert_alert_from_zabbix_problem(
                        p, host_name=host_name, host_id=host_id,
                        visible_name=visible_name, env_name=(ds.environment or ds.name))
                except Exception:
                    pass
            self.stdout.write(
                f'  数据源 {ds.name}: {len(result)} 个问题已{"刷新" if confirm else "预览"}'
            )
