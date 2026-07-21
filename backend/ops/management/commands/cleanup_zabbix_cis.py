"""将 DeviceMapping 从 Zabbix 创建的 CI 迁移到 iTop 权威 CI，清理孤立 CI"""
from django.core.management.base import BaseCommand
from django.db import transaction
from ops.models import DeviceMapping
from cmdb.models import ConfigItem
from ops.device_matcher import find_ci_by_ip, find_ci_by_name


class Command(BaseCommand):
    help = '将 DeviceMapping 从 Zabbix CI 迁移到 iTop CI，清理孤立 CI'

    def handle(self, *args, **options):
        self.stdout.write('=== Zabbix CI 清理 ===\n')

        # 1. 统计现状
        zbx_cis = ConfigItem.objects.filter(itop_datasource__isnull=True)
        itop_cis = ConfigItem.objects.filter(itop_datasource__isnull=False)
        self.stdout.write(f'Zabbix 创建的 CI: {zbx_cis.count()}')
        self.stdout.write(f'iTop 来源的 CI: {itop_cis.count()}')

        # 2. 迁移 DeviceMapping
        migrated = 0
        skipped = 0
        for dm in DeviceMapping.objects.filter(config_item__isnull=False).select_related('config_item'):
            ci = dm.config_item
            if ci.itop_datasource_id:
                continue  # 已经指向 iTop CI，无需迁移

            # 尝试找到匹配的 iTop CI
            itop_ci = None
            if dm.zabbix_ip:
                itop_ci = find_ci_by_ip(dm.zabbix_ip, prefer_itop=True)
            if not itop_ci:
                itop_ci = find_ci_by_name(dm.zabbix_hostname, prefer_itop=True)

            if itop_ci and itop_ci.itop_datasource_id:
                dm.config_item = itop_ci
                dm.match_method = DeviceMapping.MATCH_IP if (dm.zabbix_ip and _extract_ip_match(itop_ci, dm.zabbix_ip)) else DeviceMapping.MATCH_NAME
                dm.match_confidence = 1.0 if dm.match_method == DeviceMapping.MATCH_IP else 0.7
                dm.save(update_fields=['config_item', 'match_method', 'match_confidence'])
                migrated += 1
                self.stdout.write(f'  迁移: {dm.zabbix_hostname} → {itop_ci.name} [{itop_ci.ci_type.name}]')
            else:
                skipped += 1

        self.stdout.write(f'\n迁移: {migrated}, 跳过: {skipped}')

        # 3. 删除不再被引用的 Zabbix CI
        used_ci_ids = set(DeviceMapping.objects.filter(config_item__isnull=False).values_list('config_item_id', flat=True))
        to_delete = zbx_cis.exclude(id__in=used_ci_ids)
        count = to_delete.count()
        to_delete.delete()
        self.stdout.write(f'清理孤立 CI: {count} 条')

        # 4. 最终统计
        remaining = ConfigItem.objects.filter(itop_datasource__isnull=True).count()
        self.stdout.write(f'剩余 Zabbix CI: {remaining}')
        linked = DeviceMapping.objects.filter(config_item__isnull=False, config_item__itop_datasource__isnull=False).count()
        total = DeviceMapping.objects.filter(config_item__isnull=False).count()
        self.stdout.write(f'DeviceMapping 指向 iTop CI: {linked}/{total}')
        self.stdout.write('\n完成')


def _extract_ip_match(ci, ip):
    """检查 CI 的 IP 是否匹配"""
    attrs = ci.attributes or {}
    return (attrs.get('ip_address', '') == ip or
            attrs.get('managementip', '') == ip or
            attrs.get('managementip_id_friendlyname', '') == ip)
