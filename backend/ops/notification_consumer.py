"""站内通知 WebSocket Consumer。

鉴权：Sec-WebSocket-Protocol bearer.<token> 子协议 → Token 校验 → is_active。
连接后：
- 所有已登录用户加入 background-job-broadcast（后台作业完成通知，载荷为轻量字段）；
- 持有 ops.alert.view 的用户额外加入 alert-analysis-broadcast（告警 AI 分析完成，
  前端收到后再经 REST 摘要接口按权限拉取详情）。
"""
import json
import logging

from channels.generic.websocket import WebsocketConsumer
from rest_framework.authtoken.models import Token
from rbac.services import user_has_permissions

logger = logging.getLogger(__name__)

BROADCAST_GROUP = 'alert-analysis-broadcast'
BACKGROUND_JOB_GROUP = 'background-job-broadcast'


class NotificationConsumer(WebsocketConsumer):
    def connect(self):
        # 仅从 Sec-WebSocket-Protocol 子协议取 token（避免凭据进入 URL/访问日志）；
        # 旧式 ?token= 查询串已废弃（凭据会写入访问日志，安全审查整改后不再兼容）
        token_key = ''
        for proto in (self.scope.get('subprotocols') or []):
            if str(proto).startswith('bearer.'):
                token_key = str(proto)[len('bearer.'):]
                break
        if not token_key:
            self.close(code=4401)
            return
        token = Token.objects.filter(key=token_key).select_related('user').first()
        if not token or not token.user.is_active:
            self.close(code=4401)
            return

        self.user = token.user
        self.accept(subprotocol=f'bearer.{token_key}')
        try:
            from asgiref.sync import async_to_sync

            # 后台作业完成通知：所有已登录用户可收
            async_to_sync(self.channel_layer.group_add)(BACKGROUND_JOB_GROUP, self.channel_name)
            # 告警 AI 分析广播组保留 ops.alert.view 门槛（现有行为不变）
            if user_has_permissions(token.user, ['ops.alert.view']):
                async_to_sync(self.channel_layer.group_add)(BROADCAST_GROUP, self.channel_name)
        except Exception:
            logger.warning('加入通知广播组失败', exc_info=True)

    def disconnect(self, close_code):
        try:
            from asgiref.sync import async_to_sync

            async_to_sync(self.channel_layer.group_discard)(BACKGROUND_JOB_GROUP, self.channel_name)
            async_to_sync(self.channel_layer.group_discard)(BROADCAST_GROUP, self.channel_name)
        except Exception:
            pass

    def notify_event(self, event):
        """group_send 事件入口：转发业务事件给前端。"""
        self.send(text_data=json.dumps({'type': 'notify', 'event': event.get('event', {})}))
