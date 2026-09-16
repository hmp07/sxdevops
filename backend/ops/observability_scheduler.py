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

# Zabbix 告警轮询内置调度（不再依赖服务器外部 cron）
ZABBIX_POLL_INTERVAL = int(os.environ.get('SXDEVOPS_ZABBIX_POLL_INTERVAL', 300))
DISABLE_ZABBIX_POLL = os.environ.get('SXDEVOPS_DISABLE_ZABBIX_POLL') == '1'


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


def run_observability_history_scheduler_loop():
    """内置调度主循环：每轮独立 try/except，异常自愈（下轮重试），线程随进程退出。"""
    logger.info('zabbix alert poll scheduler started (interval=%ss)', ZABBIX_POLL_INTERVAL)
    while True:
        run_zabbix_poll_once()
        time.sleep(ZABBIX_POLL_INTERVAL)


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
