from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import loki_views
from . import log_views
from . import docker_views
from . import k8s_views
from . import nginx_views
router = DefaultRouter()
router.register(r'hosts', views.HostViewSet)
router.register(r'deployments', views.DeploymentViewSet)
router.register(r'alerts', views.AlertViewSet)
router.register(r'logs', views.LogEntryViewSet)
router.register(r'log/datasources', log_views.LogDataSourceViewSet, basename='log-datasource')
router.register(r'k8s/clusters', k8s_views.K8sClusterViewSet)
router.register(r'docker/hosts', docker_views.DockerHostViewSet)
router.register(r'nginx/envs', nginx_views.NginxEnvironmentViewSet)
router.register(r'nginx/certs', nginx_views.NginxCertificateViewSet)
router.register(r'nginx/domains', nginx_views.NginxDomainViewSet)
router.register(r'nginx/routes', nginx_views.NginxRouteViewSet)



urlpatterns = [
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),
    path('log/providers/', log_views.log_providers, name='log-providers'),
    path('log/providers/<str:provider>/catalog/', log_views.log_provider_catalog, name='log-provider-catalog'),
    path('log/query/', log_views.log_query, name='log-query'),
    # Loki 代理
    path('loki/labels/', loki_views.loki_labels, name='loki-labels'),
    path('loki/label/<str:label_name>/values/', loki_views.loki_label_values, name='loki-label-values'),
    path('loki/query_range/', loki_views.loki_query_range, name='loki-query-range'),
    path('loki/series/', loki_views.loki_series, name='loki-series'),
    # Docker 容器管理
    path('docker/containers/', docker_views.list_containers, name='docker-containers'),
    path('docker/images/', docker_views.list_images, name='docker-images'),
    path('docker/images/remove/', docker_views.remove_images, name='docker-images-remove'),
    path('docker/images/prune/', docker_views.prune_dangling_images, name='docker-images-prune'),
    path('docker/containers/<str:container_id>/action/', docker_views.container_action, name='docker-container-action'),
    path('docker/containers/<str:container_id>/remove/', docker_views.container_remove, name='docker-container-remove'),
    path('docker/containers/<str:container_id>/logs/', docker_views.container_logs, name='docker-container-logs'),
    path('docker/containers/<str:container_id>/inspect/', docker_views.container_inspect, name='docker-container-inspect'),

    path('', include(router.urls)),
]

