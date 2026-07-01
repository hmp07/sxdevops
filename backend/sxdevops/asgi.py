"""
ASGI config for sxdevops project.
Supports both HTTP and WebSocket connections.
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sxdevops.settings')

# Initialize Django ASGI application early to ensure apps are loaded
django_asgi_app = get_asgi_application()

# Monkey-patch DRF Response to prevent Django 5.2 ASGI template rendering.
# In ASGI mode, Django calls response.render() on SimpleTemplateResponse subclasses,
# but DRF Response handles rendering internally via accepted_renderer.
from rest_framework.response import Response as DRFResponse
_original_init = DRFResponse.__init__

def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self._is_rendered = True  # prevent Django ASGI from calling render()

DRFResponse.__init__ = _patched_init

from channels.routing import ProtocolTypeRouter, URLRouter
from ops.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
