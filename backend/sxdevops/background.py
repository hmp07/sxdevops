"""通用后台作业基础设施：daemon 线程启动（并发去重）与后台作业完成站内广播。

线程模式沿用 ops/models.py Zabbix 数据源同步先例：
- 线程入口只传 ID，线程内重新取 DB 对象（避免跨线程对象引用）；
- daemon=True；start 失败回滚防重入标记；
- 收尾在 in_atomic_block 守卫下关闭连接（长驻 Daphne 进程每个线程各建连接，
  用毕即关；测试直接调用 worker 时处于 TestCase 事务内，守卫避免误关）。
"""
import logging
import threading

from django.db import close_old_connections

logger = logging.getLogger(__name__)

# 后台作业完成广播组：所有已登录用户均加入（见 ops/notification_consumer.py）
BACKGROUND_JOB_GROUP = 'background-job-broadcast'


def start_background_thread(guard_set, guard_lock, key, target, *args):
    """启动后台 daemon 线程执行 target(*args)。

    guard_set/guard_lock 为调用方模块级 (set, threading.Lock)，key 唯一标识
    一次在途作业；返回 True=已启动，False=该 key 已有在途线程（防重入，
    调用方应视为冲突）。
    """
    with guard_lock:
        if key in guard_set:
            return False
        guard_set.add(key)

    def _worker():
        try:
            close_old_connections()
            target(*args)
        finally:
            with guard_lock:
                guard_set.discard(key)
            from django.db import connection

            if not connection.in_atomic_block:
                connection.close()

    try:
        threading.Thread(target=_worker, daemon=True).start()
        return True
    except Exception:
        with guard_lock:
            guard_set.discard(key)
        logger.exception('启动后台线程失败: %s', key)
        return False


def push_background_job_notification(job_type, *, title, message='', level='info',
                                     route='', job_id=None, extra=None):
    """向站内广播组推送「后台作业完成」事件（仅轻量字段，不含敏感内容）。

    前端 AppLayout 统一处理 kind=background_job_completed：toast + 派发
    window CustomEvent('sxdevops-background-job') 供相关页面刷新 + 刷新通知角标。
    level 取值 info/success/warning/error，与 ElNotification type 映射一致。
    """
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        event = {
            'kind': 'background_job_completed',
            'job_type': job_type,
            'title': str(title or '')[:120],
            'message': str(message or '')[:300],
            'level': level,
            'route': route or '',
            'job_id': job_id,
        }
        if extra:
            event.update(extra)
        async_to_sync(get_channel_layer().group_send)(
            BACKGROUND_JOB_GROUP, {'type': 'notify.event', 'event': event})
    except Exception:
        logger.warning('推送后台作业完成通知失败: %s %s', job_type, job_id, exc_info=True)
