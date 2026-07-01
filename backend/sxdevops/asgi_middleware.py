"""ASGI middleware to prevent DRF Response template rendering in ASGI mode.

Django 5.2 ASGI calls response.render() on SimpleTemplateResponse subclasses.
DRF Response is one but uses its own rendering pipeline (accepted_renderer).
This middleware marks DRF Responses as already-rendered.
"""

from django.utils.deprecation import MiddlewareMixin


class DRFResponseRenderMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        # DRF Response always has 'data' attribute and inherits from SimpleTemplateResponse
        # TemplateResponse does NOT have 'data' until rendered
        if hasattr(response, 'data') and hasattr(response, '_is_rendered') and not response._is_rendered:
            response._is_rendered = True
        return response
