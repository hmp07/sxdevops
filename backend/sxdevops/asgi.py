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
# We override rendered_content to safely degrade when renderer is missing.
from rest_framework.response import Response as DRFResponse
_original_rendered_content = DRFResponse.rendered_content.fget

def _safe_rendered_content(self):
    renderer = getattr(self, 'accepted_renderer', None)
    if renderer is None:
        # In ASGI mode without renderer set, return data as-is (will be serialized later)
        import json
        self['Content-Type'] = 'application/json'
        return json.dumps(self.data, ensure_ascii=False)
    return _original_rendered_content(self)

DRFResponse.rendered_content = property(_safe_rendered_content)

from channels.routing import ProtocolTypeRouter, URLRouter
from ops.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
