"""按附录 A 告警码字典回填存量告警的 alert_code 字段。

匹配规则：标题 + 详情 依次匹配各告警码的正则模式，仅处理 alert_code 为空的告警。
用法:
  python manage.py backfill_alert_codes            # 执行回填
  python manage.py backfill_alert_codes --dry-run  # 仅统计预览
"""

import re

from django.core.management.base import BaseCommand

from ops.models import Alert

# 附录 A 告警码字典（docs/智能运维IT资产本体建模方案V2.0.md 附录A，共 31 条）
ALERT_CODE_PATTERNS = [
    ('HOST_DOWN', [r'host down', r'主机(宕机|离线|失联)', r'主机.*(down|不可达)']),
    ('STORAGE_IO_TIMEOUT', [r'storage.*io.*timeout', r'存储.*io.*(超时|timeout)']),
    ('STORAGE_FULL', [r'storage.*full', r'存储(卷|空间)?.*(写满|已满|full)']),
    ('PORT_DOWN', [r'port.*down', r'端口.*(down|断开|宕)']),
    ('PACKET_LOSS_HIGH', [r'packet.*loss', r'丢包率.*(高|过高)']),
    ('NETWORK_ABNORMAL', [r'network.*abnormal', r'网络异常']),
    ('ORA-03113', [r'ORA-03113']),
    ('ORA-12535', [r'ORA-12535', r'TNS.*(超时|timeout)']),
    ('ORA-03137', [r'ORA-03137']),
    ('ORA-12541', [r'ORA-12541', r'TNS.*no listener', r'TNS.*无监听']),
    ('ORA-12514', [r'ORA-12514', r'TNS.*service.*(未注册|unknown)']),
    ('TABLESPACE_FULL', [r'表空间.*(满|使用率|无法扩展|unable to extend)', r'tablespace.*full']),
    ('ORA-01653', [r'ORA-01653']),
    ('DB_HANG', [r'db.*hang', r'数据库.*挂起', r'数据库.*hung']),
    ('DB_IO_DEGRADED', [r'db.*io.*degraded', r'数据库.*io.*(劣化|下降)']),
    ('DB_WRITE_BLOCKED', [r'db.*write.*blocked', r'数据库.*(写入阻塞|写阻塞)']),
    ('INSTANCE_DOWN', [r'instance down', r'实例宕机', r'实例.*down']),
    ('INSTANCE_UNREACHABLE', [r'instance unreachable', r'实例不可达']),
    ('BLOCKING_LOCK', [r'blocking lock', r'阻塞锁', r'enq.*TX']),
    ('DB_LOCK_TIMEOUT', [r'lock.*timeout', r'锁等待超时']),
    ('LISTENER_DOWN', [r'listener.*down', r'监听(进程)?.*(宕机|down|停止)']),
    ('SERVICE_UNREGISTERED', [r'service.*unregistered', r'服务未注册']),
    ('ARCHIVE_DEST_FULL', [r'archive.*(dest|log).*full', r'归档(目录|日志|空间).*满']),
    ('PROCESS_DOWN', [r'process down', r'进程(宕机|异常退出|退出)']),
    ('THREAD_POOL_EXHAUSTED', [r'thread.*pool.*exhaust', r'线程池.*(耗尽|打满)']),
    ('CONN_POOL_EXHAUSTED', [r'conn.*pool.*exhaust', r'连接池.*(耗尽|打满|泄漏)']),
    ('API_TIMEOUT', [r'api timeout', r'接口超时', r'api.*超时']),
    ('ACCESS_FAILURE', [r'access failure', r'(访问失败|业务访问失败)']),
    ('BUSINESS_ERROR', [r'business error', r'业务(错误|报错)']),
    ('TRANSACTION_FAILURE', [r'transaction failure', r'交易失败']),
    ('TRANSACTION_TIMEOUT', [r'transaction timeout', r'交易超时']),
    ('DB_PERF_RISK', [r'db.*perf.*risk', r'数据库性能风险']),
]

_COMPILED = [(code, [re.compile(p, re.IGNORECASE) for p in patterns]) for code, patterns in ALERT_CODE_PATTERNS]


class Command(BaseCommand):
    help = '按附录 A 告警码字典回填存量告警的 alert_code（仅处理 alert_code 为空的告警）'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='仅统计预览，不落库')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        stats = {code: 0 for code, _ in _COMPILED}

        queryset = Alert.objects.filter(alert_code='')
        for alert in queryset.iterator():
            text = f"{alert.title}\n{alert.message or ''}"
            for code, patterns in _COMPILED:
                if any(p.search(text) for p in patterns):
                    stats[code] += 1
                    if not dry_run:
                        alert.alert_code = code
                        alert.save(update_fields=['alert_code'])
                    break

        total = sum(stats.values())
        for code, count in stats.items():
            if count:
                self.stdout.write(f'{code}: {count} 条')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\n[dry-run] 共识别 {total} 条告警可回填，未执行。确认后运行: '
                'python manage.py backfill_alert_codes'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f'回填完成：共更新 {total} 条告警。'))
