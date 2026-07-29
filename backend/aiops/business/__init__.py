"""
AIOps 业务逻辑层 — 从 services.py 拆分。

按业务领域组织，与 Agent 运行时无关的纯业务逻辑：
- environment.py: 环境解析 + 分析范围构建
- routing.py:     Action 路由与问题匹配
- tasks.py:       任务草稿构建
- pending.py:     PendingAction 确认/取消
- runbook.py:     Runbook CRUD
- review.py:      Review Knowledge CRUD
- a2a.py:         External Task 编排
- sync.py:        Session Sync
"""

from .environment import _build_analysis_scope, _resolve_chat_environment
from .pending import cancel_action, confirm_action
from .routing import _select_action_for_question
from .runbook import publish_runbook
from .tasks import build_task_draft

__all__ = [
    '_build_analysis_scope',
    '_resolve_chat_environment',
    '_select_action_for_question',
    'build_task_draft',
    'cancel_action',
    'confirm_action',
    'publish_runbook',
]
