"""站内通知 WebSocket Consumer。

鉴权范式与 ssh_consumer 一致：query token → Token 校验 → is_active →
user_has_permissions(ops.alert.view)。连接后加入广播组
alert-analysis-broadcast；服务端在告警 AI 分析完成时向该组广播
轻量事件（仅告警 ID/级别/标题，不含敏感内容），前端收到后再经
REST 摘要接口按权限拉取详情。
"""
import json
import logging
from urllib.parse import parse_qs

from channels.generic.websocket import WebsocketConsumer
from rest_framework.authtoken.models import Token
from rbac.services import user_has_permissions

logger = logging.getLogger(__name__)

BROADCAST_GROUP = 'alert-analysis-broadcast'


class NotificationConsumer(WebsocketConsumer):
    def connect(self):
        token_key = parse_qs(self.scope.get('query_string', b'').decode('utf-8')).get('token', [''])[0]
        token = Token.objects.filter(key=token_key).select_related('user').first()
        if not token or not token.user.is_active:
            self.close(code=4401)
            return
        if not user_has_permissions(token.user, ['ops.alert.view']):
            self.close(code=4403)
            return

        self.user = token.user
        self.accept()
        try:
            from asgiref.sync import async_to_sync

            async_to_sync(self.channel_layer.group_add)(BROADCAST_GROUP, self.channel_name)
        except Exception:
            logger.warning('加入通知广播组失败', exc_info=True)

    def disconnect(self, close_code):
        try:
            from asgiref.sync import async_to_sync

            async_to_sync(self.channel_layer.group_discard)(BROADCAST_GROUP, self.channel_name)
        except Exception:
            pass

    def notify_event(self, event):
        """group_send 事件入口：转发业务事件给前端。"""
        self.send(text_data=json.dumps({'type': 'notify', 'event': event.get('event', {})}))
