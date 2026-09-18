from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

_scheduler_lock = threading.Lock()
_scheduler_started = False

# Zabbix 告警轮询内置调度（不再依赖服务器外部 cron）。
# 混合方案下轮询为小时级兜底（webhook 推送负责秒级重要告警），默认 3600s。
ZABBIX_POLL_INTERVAL = int(os.environ.get('SXDEVOPS_ZABBIX_POLL_INTERVAL', 3600))
DISABLE_ZABBIX_POLL = os.environ.get('SXDEVOPS_DISABLE_ZABBIX_POLL') == '1'

# 事件墙滚动保留：非外部接入事件保留天数（0 = 不清理）
EVENT_RETENTION_DAYS = int(os.environ.get('SXDEVOPS_EVENT_RETENTION_DAYS', 7))

_last_daily_cleanup_date = None


def _seconds_until_next_hour():
    now = timezone.localtime()
    next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return max(1, int((next_hour - now).total_seconds()))


def scheduler_should_autostart():
    blocked = {'test', 'makemigrations', 'migrate', 'collectstatic', 'shell'}
    if any(item in sys.argv for item in blocked):
        return False
    if os.environ.get('RUN_MAIN') == 'false':
        return False
    return True


def run_zabbix_poll_once():
    """单次轮询迭代（无 sleep，供测试与手动调用）。"""
    try:
        from ops.zabbix_polling import poll_zabbix_alerts_once

        stats = poll_zabbix_alerts_once()
        if stats['errors']:
            logger.warning('zabbix poll partial: %s', stats)
        else:
            logger.info('zabbix poll done: %s', stats)
    except Exception:
        logger.exception('zabbix alert poll iteration failed')


def run_daily_event_cleanup():
    """每日事件滚动清理（保留 EVENT_RETENTION_DAYS 天；0 = 不清理）。"""
    if EVENT_RETENTION_DAYS <= 0:
        return
    try:
        from eventwall.models import EventRecord
        from eventwall.services import prune_event_records_before

        cutoff = timezone.now() - timedelta(days=EVENT_RETENTION_DAYS)
        deleted = prune_event_records_before(
            cutoff,
            actor_username='scheduler',
            actor_display='内置调度器',
            actor_type=EventRecord.ACTOR_SYSTEM,
            source_type=EventRecord.SOURCE_SYSTEM,
        )
        logger.info('event retention cleanup done: %s deleted (retention=%sd)', deleted, EVENT_RETENTION_DAYS)
    except Exception:
        logger.exception('event retention cleanup failed')


def run_observability_history_scheduler_loop():
    """内置调度主循环：每轮独立 try/except，异常自愈（下轮重试），线程随进程退出。

    小时级间隔时对齐整点运行（首轮启动即执行，随后睡到下一个整点），
    避免长时间漂移。
    """
    global _last_daily_cleanup_date
    logger.info('zabbix alert poll scheduler started (interval=%ss)', ZABBIX_POLL_INTERVAL)
    while True:
        run_zabbix_poll_once()
        # 兜底重扫：未完成 AI 分析的 critical 活跃 zabbix 告警重新入队（覆盖进程重启/漏触发）
        try:
            from .alert_ai_analysis import requeue_unanalyzed_alerts

            requeue_unanalyzed_alerts()
        except Exception:
            logger.exception('requeue unanalyzed alerts failed')
        today = timezone.localtime().date()
        if _last_daily_cleanup_date != today:
            _last_daily_cleanup_date = today
            run_daily_event_cleanup()
        sleep_seconds = _seconds_until_next_hour() if ZABBIX_POLL_INTERVAL >= 3600 else ZABBIX_POLL_INTERVAL
        time.sleep(sleep_seconds)


def start_observability_history_scheduler():
    global _scheduler_started
    if _scheduler_started or DISABLE_ZABBIX_POLL or not scheduler_should_autostart():
        return False
    with _scheduler_lock:
        if _scheduler_started:
            return False
        _scheduler_started = True
        thread = threading.Thread(
            target=run_observability_history_scheduler_loop,
            name='zabbix-alert-poll',
            daemon=True,
        )
        thread.start()
        logger.info('zabbix alert poll scheduler thread started (interval=%ss)', ZABBIX_POLL_INTERVAL)
        return True
