from pathlib import Path

from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = 'ops'
    path = str(Path(__file__).resolve().parent)

    def ready(self):
        from .observability_scheduler import start_observability_history_scheduler

        start_observability_history_scheduler()
        # 告警自动 AI 分析 worker 为懒启动（首次入队时 start_alert_analysis_worker）
