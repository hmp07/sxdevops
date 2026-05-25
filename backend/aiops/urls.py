from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register('sessions', views.AIOpsChatSessionViewSet, basename='aiops-session')
router.register('admin/providers', views.AIOpsModelProviderViewSet, basename='aiops-provider')
router.register('admin/mcp-servers', views.AIOpsMCPServerViewSet, basename='aiops-mcp-server')
router.register('admin/skills', views.AIOpsSkillViewSet, basename='aiops-skill')
router.register('knowledge-environments', views.AIOpsKnowledgeEnvironmentViewSet, basename='aiops-knowledge-environment')
router.register('admin/audit/sessions', views.AIOpsAuditSessionViewSet, basename='aiops-audit-session')
router.register('admin/audit/tool-invocations', views.AIOpsToolInvocationViewSet, basename='aiops-audit-tool')
router.register('admin/audit/actions', views.AIOpsPendingActionViewSet, basename='aiops-audit-action')

urlpatterns = [
    path('bootstrap/', views.bootstrap, name='aiops-bootstrap'),
    path('knowledge-graph/', views.knowledge_graph, name='aiops-knowledge-graph'),
    path('admin/config/', views.agent_config_view, name='aiops-agent-config'),
    path('admin/providers/presets/', views.model_provider_presets, name='aiops-provider-presets-explicit'),
    path('admin/audit/overview/', views.audit_overview, name='aiops-audit-overview'),
    path('actions/<int:pk>/confirm/', views.confirm_pending_action, name='aiops-confirm-action'),
    path('actions/<int:pk>/cancel/', views.cancel_pending_action, name='aiops-cancel-action'),
    path('', include(router.urls)),
]
