"""存量 Zabbix 告警指纹回填命令（双路径指纹统一迁移）。

统一前轮询路径指纹为明文 `zabbix:{eventid}`、webhook 路径为
`sha256('zabbix:{triggerid}')`；统一后两条路径共用后者。本命令按
raw_payload 重算存量告警指纹：
- 可重算且新指纹未被占用 → 更新指纹（幂等，已一致则跳过）；
- 新指纹已被其他告警占用（webhook 已建同告警）→ 本条置为 resolved；
- 无可匹配键（raw_payload 缺失/无 triggerid/eventid）→ 置为 resolved。

默认 dry-run；--apply 写入。
"""
from django.core.management.base import BaseCommand

from ops.alerting import _fingerprint
from ops.models import Alert


class Command(BaseCommand):
    help = '存量 zabbix 告警指纹回填（统一双路径指纹），默认 dry-run，--apply 写入'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='实际写入（默认仅预览）')

    def _new_fingerprint(self, alert):
        raw = alert.raw_payload or {}
        if not isinstance(raw, dict):
            return ''
        trigger_id = str(raw.get('objectid') or raw.get('triggerid') or raw.get('trigger_id') or '')
        event_id = str(raw.get('eventid') or raw.get('event_id') or '')
        base = trigger_id or event_id
        if not base:
            return ''
        return _fingerprint('zabbix', {'fingerprint': base, 'external_id': event_id})

    def handle(self, *args, **options):
        apply = options['apply']
        updated = resolved = skipped = 0
        queryset = Alert.objects.filter(source_type='zabbix').exclude(status=Alert.STATUS_CLOSED)
        for alert in queryset.iterator():
            new_fp = self._new_fingerprint(alert)
            if not new_fp:
                resolved += 1
                if apply:
                    alert.status = Alert.STATUS_RESOLVED
                    alert.save(update_fields=['status', 'updated_at'])
                self.stdout.write(f'  [{"apply" if apply else "dry-run"}] 无可匹配键 → resolved: Alert#{alert.pk} {alert.title[:48]}')
                continue
            if alert.fingerprint == new_fp:
                skipped += 1
                continue
            conflict = Alert.objects.filter(fingerprint=new_fp).exclude(pk=alert.pk).first()
            if conflict:
                resolved += 1
                if apply:
                    alert.status = Alert.STATUS_RESOLVED
                    alert.save(update_fields=['status', 'updated_at'])
                self.stdout.write(
                    f'  [{"apply" if apply else "dry-run"}] 新指纹已被 Alert#{conflict.pk} 占用 → resolved: '
                    f'Alert#{alert.pk} {alert.title[:48]}'
                )
                continue
            updated += 1
            if apply:
                alert.fingerprint = new_fp
                alert.save(update_fields=['fingerprint', 'updated_at'])
            self.stdout.write(f'  [{"apply" if apply else "dry-run"}] 指纹重算: Alert#{alert.pk} {alert.title[:48]}')
        mode = '已写入' if apply else 'dry-run（加 --apply 执行）'
        self.stdout.write(
            self.style.SUCCESS(
                f'扫描完成：重算 {updated} 处，置为 resolved {resolved} 处，已一致跳过 {skipped} 处；{mode}。'
            )
        )
