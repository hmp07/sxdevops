from urllib.parse import quote

import json
import copy
import math
import re
from urllib.parse import urlparse

import requests as http_requests
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import user_has_permissions
from .alerting import _has_claimants
from .models import Alert, Deployment, GrafanaSetting, LogDataSource, LogEntry, ObservabilityDataSourceLink, SystemPostureEnvironment, SystemPostureSystem, TracingDataSource
from .serializers import (
    AlertSerializer,
    SystemPostureEnvironmentSerializer,
    SystemPostureSystemSerializer,
    GrafanaSettingSerializer,
    ObservabilityDataSourceLinkSerializer,
    TracingDataSourceSerializer,
)
from .tracing_providers import (
    ObservabilityError,
    load_trace_detail,
    load_tracing_catalog,
    search_tracing,
    test_tracing_connection,
    tracing_provider_info,
)


DEMO_GRAFANA_DASHBOARDS = [
    {'key': 'apm-overview', 'title': 'APM 全链路总览', 'slug': 'apm-overview', 'path': '/d/apm-overview', 'panel_count': 18, 'tags': ['SkyWalking', '应用', 'SLA'], 'description': '面向应用负责人查看服务吞吐、慢调用与错误率。'},
    {'key': 'infra-overview', 'title': '基础设施总览', 'slug': 'infra-overview', 'path': '/d/infra-overview', 'panel_count': 14, 'tags': ['Node', 'CPU', 'Memory'], 'description': '聚合节点 CPU、内存、磁盘与 Pod 负载走势。'},
    {'key': 'log-drilldown', 'title': '日志钻取看板', 'slug': 'log-drilldown', 'path': '/d/log-drilldown', 'panel_count': 12, 'tags': ['Loki', 'Error', 'Audit'], 'description': '配合日志中心快速回放错误时段与关键日志。'},
    {'key': 'ingress-slo', 'title': '入口流量与 SLO', 'slug': 'ingress-slo', 'path': '/d/ingress-slo', 'panel_count': 10, 'tags': ['Nginx', 'Latency', 'Availability'], 'description': '聚焦入口 QPS、响应时间分位和可用性目标。'},
    {'key': 'kubernetes-compute-resources-workload', 'title': 'Kubernetes / Compute Resources / Workload', 'slug': 'kubernetes-compute-resources-workload', 'path': '/d/k8s-resources-workload', 'panel_count': 16, 'tags': ['Kubernetes', 'Workload', 'Compute'], 'description': '按 namespace 和 workload 查看 Kubernetes 工作负载资源。'},
]


def _deny_if_missing_any(request, codes):
    allowed = any(user_has_permissions(request.user, [code]) for code in codes)
    if allowed:
        return None
    return Response({'detail': f"缺少权限: {', '.join(codes)}"}, status=403)


def _has_permission(request, code):
    return user_has_permissions(request.user, [code])


def _observability_access(request):
    return {
        'system_posture': _has_permission(request, 'ops.observability.system_posture.view'),
        'system_posture_manage': _has_permission(request, 'ops.observability.system_posture.manage'),
        'log_query': _has_permission(request, 'ops.log.query'),
        'log_entry': _has_permission(request, 'ops.log.entry.view'),
        'log_datasource': _has_permission(request, 'ops.log.datasource.view'),
        'alerts': _has_permission(request, 'ops.alert.view'),
        'trace': _has_permission(request, 'ops.trace.view'),
        'trace_datasource': _has_permission(request, 'ops.trace.datasource.view'),
        'links': _has_permission(request, 'ops.observability.link.view'),
        'grafana': _has_permission(request, 'ops.grafana.view'),
        'eventwall': _has_permission(request, 'eventwall.view'),
    }


def _observability_defaults():
    return getattr(settings, 'OBSERVABILITY_CONFIG', {}) or {}


DEFAULT_TRACE_ID_FIELDS = ['trace_id', 'traceId', 'traceID', 'trace.id', 'otelTraceID']
DEFAULT_TRACE_ID_REGEX = re.compile(r'(?:"?(?:trace_id|traceId|traceID|trace\.id)"?\s*[:=]\s*"?(?P<trace>[0-9a-fA-F]{16,32})"?)')
DEFAULT_LOG_QUERY_TEMPLATE = '${__tags} | json | trace_id="${__trace.traceId}"'
DEFAULT_LOG_LABEL_MAPPINGS = [
    {'trace_tag': 'service.name', 'log_label': 'container'},
    {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
]
DEFAULT_GRAFANA_VARIABLE_MAPPINGS = [
    {'trace_tag': 'service.name', 'variable': 'workload'},
    {'trace_tag': 'service.namespace', 'variable': 'namespace'},
    {'trace_tag': 'workload.type', 'variable': 'workload_type'},
]

SERVICE_TAG_ALIASES = [
    'service.name',
    'service',
    'service_name',
    'serviceName',
    'workload',
    'app',
    'application',
    'container',
    'container_name',
    'k8s.container.name',
    'kubernetes_container_name',
]
NAMESPACE_TAG_ALIASES = [
    'service.namespace',
    'namespace',
    'service_namespace',
    'serviceNamespace',
    'k8s.namespace.name',
    'kubernetes_namespace_name',
    'kubernetes.namespace',
]
WORKLOAD_TYPE_TAG_ALIASES = [
    'workload.type',
    'workload_type',
    'workloadType',
    'k8s.workload.type',
    'kubernetes_workload_type',
    'controller_kind',
    'owner_kind',
    'kind',
]


def _normalize_trace_id_fields(values):
    fields = []
    for item in values or DEFAULT_TRACE_ID_FIELDS:
        text = str(item or '').strip()
        if text and text not in fields:
            fields.append(text)
    return fields


def _normalize_label_mappings(values):
    mappings = []
    for item in values or DEFAULT_LOG_LABEL_MAPPINGS:
        if not isinstance(item, dict):
            continue
        trace_tag = str(item.get('trace_tag') or '').strip()
        log_label = str(item.get('log_label') or '').strip()
        if trace_tag and log_label:
            mappings.append({'trace_tag': trace_tag, 'log_label': log_label})
    return mappings or list(DEFAULT_LOG_LABEL_MAPPINGS)


def _normalize_grafana_variable_mappings(values):
    mappings = []
    for item in values or DEFAULT_GRAFANA_VARIABLE_MAPPINGS:
        if not isinstance(item, dict):
            continue
        trace_tag = str(item.get('trace_tag') or '').strip()
        variable = str(item.get('variable') or '').strip()
        if trace_tag and variable:
            mappings.append({'trace_tag': trace_tag, 'variable': variable})
    return mappings or list(DEFAULT_GRAFANA_VARIABLE_MAPPINGS)


def _first_text_value(data, keys):
    if not isinstance(data, dict):
        return ''
    lowered = {str(key).lower().replace('_', '.'): value for key, value in data.items()}
    for key in keys:
        candidates = {
            key,
            key.replace('.', '_'),
            key.replace('_', '.'),
            key.lower(),
            key.lower().replace('_', '.'),
        }
        for candidate in candidates:
            value = data.get(candidate)
            if isinstance(value, str) and value.strip():
                return value.strip()
            lowered_value = lowered.get(candidate.lower().replace('_', '.'))
            if isinstance(lowered_value, str) and lowered_value.strip():
                return lowered_value.strip()
    return ''


def _merge_standard_trace_tags(tags):
    normalized = dict(tags or {})
    service = _first_text_value(normalized, SERVICE_TAG_ALIASES)
    namespace = _first_text_value(normalized, NAMESPACE_TAG_ALIASES)
    workload_type = _first_text_value(normalized, WORKLOAD_TYPE_TAG_ALIASES) or 'deployment'
    if service and not normalized.get('service.name'):
        normalized['service.name'] = service
    if namespace and not normalized.get('service.namespace'):
        normalized['service.namespace'] = namespace
    if workload_type and not normalized.get('workload.type'):
        normalized['workload.type'] = workload_type.lower()
    return normalized


def _trace_id_from_mapping(attributes, fields=None, message='', regex=''):
    fields = _normalize_trace_id_fields(fields)
    attributes = attributes or {}
    if isinstance(attributes, dict):
        for field in fields:
            for candidate in (field, field.replace('.', '_')):
                value = attributes.get(candidate)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key, value in attributes.items():
            key_text = str(key).lower().replace('.', '_')
            if key_text in {'trace_id', 'traceid', 'oteltraceid'} and isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(message, str) and message.strip():
        try:
            parsed = json.loads(message)
            if isinstance(parsed, dict):
                nested = _trace_id_from_mapping(parsed, fields=fields, message='', regex=regex)
                if nested:
                    return nested
        except ValueError:
            pass
        pattern = DEFAULT_TRACE_ID_REGEX
        if regex:
            try:
                pattern = re.compile(regex)
            except re.error:
                pattern = DEFAULT_TRACE_ID_REGEX
        match = pattern.search(message)
        if match:
            return (match.groupdict().get('trace') or (match.group(1) if match.lastindex else match.group(0))).strip()
    return ''


def _render_log_selector(tags, mappings):
    tags = tags or {}
    mappings = _normalize_label_mappings(mappings)
    selector_parts = []
    for item in mappings:
        value = tags.get(item['trace_tag'])
        if isinstance(value, str) and value.strip():
            selector_parts.append(f'{item["log_label"]}="{value.strip()}"')
    return '{' + ','.join(selector_parts) + '}' if selector_parts else ''


def _normalize_trace_id_for_log(trace_id):
    value = str(trace_id or '').strip()
    if re.fullmatch(r'[0-9a-fA-F]{1,31}', value):
        return value.zfill(32)
    return value


def _render_log_query(link, trace_id, tags=None):
    template = (link.log_query_template or DEFAULT_LOG_QUERY_TEMPLATE).strip() or DEFAULT_LOG_QUERY_TEMPLATE
    selector = _render_log_selector(tags, link.log_label_mappings)
    query = template.replace('${__tags}', selector)
    log_trace_id = _normalize_trace_id_for_log(trace_id)
    query = query.replace('${__trace.traceId}', log_trace_id)
    query = query.replace('${__trace.traceID}', log_trace_id)
    query = query.replace('${__trace.id}', log_trace_id)
    query = query.replace('${traceId}', log_trace_id)
    if not trace_id:
        query = re.sub(r'\s*\|\s*(?:json\s*\|\s*)?trace_?id\s*=\s*""', '', query, flags=re.IGNORECASE)
    return query.strip()


def _resolve_observability_link(log_datasource_id='', tracing_datasource_id='', default_to_enabled=True):
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True)
    has_filter = bool(log_datasource_id or tracing_datasource_id)
    if log_datasource_id:
        queryset = queryset.filter(log_datasource_id=log_datasource_id)
    if tracing_datasource_id:
        queryset = queryset.filter(tracing_datasource_id=tracing_datasource_id)
    link = queryset.order_by('-is_default', 'name').first()
    if link or has_filter or not default_to_enabled:
        return link
    return (
        ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource')
        .filter(is_enabled=True)
        .order_by('-is_default', 'name')
        .first()
    )


def _resolve_observability_link_for_dashboard(dashboard_key=''):
    key = str(dashboard_key or '').strip()
    if not key:
        return None
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True)
    _, dashboard = _find_grafana_dashboard(key)
    candidates = [key]
    if dashboard:
        candidates.extend([
            dashboard.get('key'),
            dashboard.get('slug'),
            dashboard.get('title'),
        ])
    normalized = {str(item or '').strip().lower() for item in candidates if str(item or '').strip()}
    compact = {re.sub(r'[^a-z0-9]+', '', item) for item in normalized if item}
    for link in queryset.order_by('-is_default', 'name'):
        link_key = str(link.grafana_dashboard_key or '').strip()
        if not link_key:
            continue
        lowered = link_key.lower()
        if lowered in normalized:
            return link
        if re.sub(r'[^a-z0-9]+', '', lowered) in compact:
            return link
    return None


def _link_payload(link):
    data = ObservabilityDataSourceLinkSerializer(link).data
    data['trace_id_fields'] = data.get('trace_id_fields') or DEFAULT_TRACE_ID_FIELDS
    data['trace_id_regex'] = data.get('trace_id_regex') or DEFAULT_TRACE_ID_REGEX.pattern
    data['log_query_template'] = data.get('log_query_template') or DEFAULT_LOG_QUERY_TEMPLATE
    data['log_label_mappings'] = data.get('log_label_mappings') or DEFAULT_LOG_LABEL_MAPPINGS
    data['grafana_variable_mappings'] = data.get('grafana_variable_mappings') or DEFAULT_GRAFANA_VARIABLE_MAPPINGS
    return data


def _find_grafana_dashboard(dashboard_key=''):
    grafana = _grafana_meta()
    dashboards = grafana.get('dashboards') or []
    key = str(dashboard_key or '').strip()
    if key:
        normalized_key = key.lower()
        compact_key = re.sub(r'[^a-z0-9]+', '', normalized_key)
        for dashboard in dashboards:
            candidates = [
                dashboard.get('key'),
                dashboard.get('slug'),
                dashboard.get('title'),
            ]
            if any(str(candidate or '').strip().lower() == normalized_key for candidate in candidates):
                return grafana, dashboard
            if any(re.sub(r'[^a-z0-9]+', '', str(candidate or '').strip().lower()) == compact_key for candidate in candidates):
                return grafana, dashboard
        if 'workload' in normalized_key:
            for dashboard in dashboards:
                title = str(dashboard.get('title') or '').lower()
                tags = {str(tag).lower() for tag in dashboard.get('tags') or []}
                if 'workload' in title or 'workload' in tags:
                    return grafana, dashboard
    for dashboard in dashboards:
        tags = {str(tag).lower() for tag in dashboard.get('tags') or []}
        title = str(dashboard.get('title') or '').lower()
        if 'apm' in tags or '应用' in tags or 'trace' in tags or '链路' in title or 'apm' in title:
            return grafana, dashboard
    return grafana, dashboards[0] if dashboards else {}


def _render_grafana_query(link, trace_id, tags=None):
    tags = _merge_standard_trace_tags(tags or {})
    query = {}
    if trace_id:
        query['traceId'] = trace_id
    service = tags.get('service.name') or tags.get('service') or ''
    if isinstance(service, str) and service.strip():
        query['service'] = service.strip()
    for item in _normalize_grafana_variable_mappings(link.grafana_variable_mappings):
        value = tags.get(item['trace_tag'])
        if isinstance(value, str) and value.strip():
            query[f'var-{item["variable"]}'] = value.strip()
    workload_type = tags.get('workload.type')
    if isinstance(workload_type, str) and workload_type.strip() and not query.get('var-workload_type'):
        query['var-workload_type'] = workload_type.strip().lower()
    return query


def _dashboard_context_from_request(data):
    context = {}
    for key, value in (data or {}).items():
        if key in {'dashboard_key', 'dashboard', 'log_datasource_id', 'tracing_datasource_id', 'datasource_id'}:
            continue
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
        elif isinstance(value, (int, float)):
            context[key] = value
    raw_query = data.get('query') if isinstance(data, dict) else {}
    if isinstance(raw_query, dict):
        for key, value in raw_query.items():
            if isinstance(value, str) and value.strip():
                context[key] = value.strip()
            elif isinstance(value, (int, float)):
                context[key] = value
    return context


def _tags_from_grafana_context(link, context):
    tags = {}
    context = context or {}
    for item in _normalize_grafana_variable_mappings(link.grafana_variable_mappings):
        value = context.get(f'var-{item["variable"]}') or context.get(item['variable'])
        if isinstance(value, str) and value.strip():
            tags[item['trace_tag']] = value.strip()
    service = context.get('service') or context.get('var-service') or context.get('workload') or context.get('var-workload')
    namespace = context.get('namespace') or context.get('var-namespace')
    if isinstance(service, str) and service.strip() and not tags.get('service.name'):
        tags['service.name'] = service.strip()
    if isinstance(namespace, str) and namespace.strip() and not tags.get('service.namespace'):
        tags['service.namespace'] = namespace.strip()
    return _merge_standard_trace_tags(tags)


def _tags_from_log_attributes(link, attributes):
    tags = dict(attributes or {})
    for item in _normalize_label_mappings(link.log_label_mappings):
        value = attributes.get(item['log_label']) if isinstance(attributes, dict) else ''
        if isinstance(value, str) and value.strip() and not tags.get(item['trace_tag']):
            tags[item['trace_tag']] = value.strip()
    return _merge_standard_trace_tags(tags)


def _grafana_resolve_payload(link, trace_id, tags=None, request_data=None):
    request_data = request_data or {}
    dashboard_hint = request_data.get('dashboard_key') or request_data.get('dashboard') or request_data.get('grafana_dashboard_key') or link.grafana_dashboard_key
    grafana, dashboard = _find_grafana_dashboard(dashboard_hint)
    if not dashboard:
        return None
    dashboard_key = dashboard.get('key') or dashboard.get('slug') or link.grafana_dashboard_key
    query = _render_grafana_query(link, trace_id, tags=tags)
    query.update({
        'dashboard': dashboard_key,
        'source': 'trace',
    })
    if request_data.get('from'):
        query['from'] = request_data.get('from')
    if request_data.get('to'):
        query['to'] = request_data.get('to')
    return {
        'link': _link_payload(link),
        'trace_id': trace_id,
        'grafana': {
            'configured': grafana.get('configured'),
            'url': grafana.get('url'),
        },
        'dashboard': dashboard,
        'query': query,
    }


def _join_external_url(base, path=''):
    base = (base or '').rstrip('/')
    if not base:
        return ''
    normalized_path = (path or '').strip()
    if not normalized_path:
        return base
    if not normalized_path.startswith('/'):
        normalized_path = f'/{normalized_path}'
    return f'{base}{normalized_path}'


def _grafana_config():
    config = dict(_observability_defaults().get('grafana', {}))
    config.setdefault('enabled', True)
    config.setdefault('url', '')
    config.setdefault('default_path', '')
    config.setdefault('demo_mode', True)
    config.setdefault('folders', [])
    config.setdefault('dashboards', [])
    db_config = _get_grafana_setting()
    if db_config:
        config.update({
            'enabled': db_config.enabled,
            'url': db_config.url,
            'default_path': db_config.default_path,
            'folders': db_config.folders or config.get('folders') or [],
            'dashboards': db_config.dashboards or config.get('dashboards') or [],
        })
    return config


def _get_grafana_setting():
    return GrafanaSetting.objects.filter(name='default').first()


def _grafana_meta():
    config = _grafana_config()
    configured_dashboards = config.get('dashboards') or DEMO_GRAFANA_DASHBOARDS
    configured_folders = config.get('folders') or []
    dashboards = []
    base_url = config.get('url') or ''
    default_path = (config.get('default_path') or '').strip()
    for item in configured_dashboards:
        full_url = (item.get('full_url') or item.get('url') or '').strip()
        item_path = (item.get('path') or '').strip()
        slug = item.get('slug') or item.get('key') or ''
        path = item_path or default_path or (f"/d/{quote(slug)}" if slug else '')
        resolved_url = full_url or (_join_external_url(base_url, path) if base_url and path else base_url)
        dashboards.append({
            **item,
            'path': path,
            'full_url': full_url,
            'url': resolved_url,
        })
    has_dashboard_url = any(item.get('url') for item in dashboards)
    configured = bool(config.get('enabled') and (base_url or has_dashboard_url))
    return {
        'enabled': bool(config.get('enabled')),
        'configured': configured,
        'source': 'grafana' if configured else 'demo',
        'status_text': '已接入 Grafana' if configured else '未配置外部地址，当前展示推荐看板',
        'url': base_url,
        'embed_url': _join_external_url(base_url, default_path) if base_url and default_path else (dashboards[0]['url'] if dashboards else base_url),
        'dashboard_count': len(dashboards),
        'panel_count': sum(item['panel_count'] for item in dashboards),
        'datasource_count': 4,
        'folders': configured_folders,
        'dashboards': dashboards,
    }


def _log_module_summary():
    providers = []
    grouped = LogDataSource.objects.values('provider').annotate(total=Count('id')).order_by('provider')
    enabled_by_provider = {
        item['provider']: item['count']
        for item in LogDataSource.objects.filter(is_enabled=True).values('provider').annotate(count=Count('id'))
    }
    for item in grouped:
        provider = item['provider']
        providers.append({
            'provider': provider,
            'total': item['total'],
            'enabled': enabled_by_provider.get(provider, 0),
        })

    return {
        'query_path': '/logs/query',
        'datasource_path': '/logs/datasources',
        'datasource_count': LogDataSource.objects.count(),
        'enabled_count': LogDataSource.objects.filter(is_enabled=True).count(),
        'default_count': LogDataSource.objects.filter(is_default=True).count(),
        'providers': providers,
    }


def _alert_module_summary():
    latest = Alert.objects.select_related('host').prefetch_related('claim_records').all()[:5]
    return {
        'path': '/alerts',
        'total': Alert.objects.count(),
        'unacknowledged': Alert.objects.filter(claim_records__isnull=True).distinct().count(),
        'critical': Alert.objects.filter(level='critical').count(),
        'warning': Alert.objects.filter(level='warning').count(),
        'info': Alert.objects.filter(level='info').count(),
        'recent': AlertSerializer(latest, many=True).data,
    }


FIREMAP_STATUS_META = {
    'healthy': {'label': '健康', 'tone': 'success', 'rank': 1},
    'warning': {'label': '告警', 'tone': 'warning', 'rank': 2},
    'critical': {'label': '故障', 'tone': 'danger', 'rank': 3},
    'offline': {'label': '离线', 'tone': 'info', 'rank': 0},
}

FIREMAP_SYSTEM_TEMPLATES = [
    {
        'id': 'commerce-core',
        'name': '电商交易核心',
        'domain': '交易域',
        'owner': '交易平台',
        'tier': 'P0',
        'base_status': 'critical',
        'keywords': ['gateway-service', 'order-service', 'payment-service', 'inventory-service', 'checkout', '下单', '支付', '订单'],
        'north_star': {'label': '下单成功率', 'value': 93.8, 'target': 99.95, 'unit': '%', 'direction': 'higher'},
        'summary': '入口链路抖动，支付回调和订单查询都在放大故障面。',
        'focus_service_id': 'gateway-service',
        'focus_interface_id': 'gateway-order-detail',
        'focus_keyword': '订单查询与支付回调',
        'service_specs': [
            {
                'id': 'gateway-service',
                'name': 'API 网关',
                'role': '入口层',
                'base_status': 'critical',
                'metrics': [
                    {'label': 'QPS', 'value': 1860, 'target': 1500, 'unit': '', 'direction': 'higher'},
                    {'label': 'P95 延迟', 'value': 1280, 'target': 600, 'unit': 'ms', 'direction': 'lower'},
                    {'label': '5xx 错误率', 'value': 2.4, 'target': 0.5, 'unit': '%', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'gateway-order-detail', 'name': 'GET /api/orders/{id}', 'base_status': 'critical', 'hint': '订单详情查询超时', 'metrics': [{'label': 'P95', 'value': 1420, 'target': 550, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 2.9, 'target': 0.5, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'gateway-checkout', 'name': 'POST /api/checkout', 'base_status': 'warning', 'hint': '下单路径响应抖动', 'metrics': [{'label': 'P95', 'value': 930, 'target': 500, 'unit': 'ms', 'direction': 'lower'}, {'label': '超时率', 'value': 1.2, 'target': 0.3, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'order-service',
                'name': '订单服务',
                'role': '业务模块',
                'base_status': 'warning',
                'metrics': [
                    {'label': '写入成功率', 'value': 97.8, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
                    {'label': '队列积压', 'value': 18, 'target': 8, 'unit': '条', 'direction': 'lower'},
                    {'label': 'DB 慢查询', 'value': 34, 'target': 12, 'unit': '条', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'order-create', 'name': 'POST /api/orders', 'base_status': 'warning', 'hint': '创建订单偶发重试', 'metrics': [{'label': '成功率', 'value': 97.6, 'target': 99.8, 'unit': '%', 'direction': 'higher'}, {'label': 'P95', 'value': 840, 'target': 450, 'unit': 'ms', 'direction': 'lower'}]},
                    {'id': 'order-query', 'name': 'GET /api/orders/list', 'base_status': 'healthy', 'hint': '列表查询仍可用', 'metrics': [{'label': 'P95', 'value': 240, 'target': 400, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.1, 'target': 0.3, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'payment-service',
                'name': '支付服务',
                'role': '业务模块',
                'base_status': 'critical',
                'metrics': [
                    {'label': '回调成功率', 'value': 92.5, 'target': 99.95, 'unit': '%', 'direction': 'higher'},
                    {'label': '接口超时', 'value': 26, 'target': 5, 'unit': '次', 'direction': 'lower'},
                    {'label': '支付延迟', 'value': 1500, 'target': 700, 'unit': 'ms', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'payment-callback', 'name': 'POST /api/payments/callback', 'base_status': 'critical', 'hint': '回调处理超时', 'metrics': [{'label': 'P95', 'value': 1432, 'target': 600, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 3.6, 'target': 0.4, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'payment-ledger', 'name': '账务记账任务', 'base_status': 'warning', 'hint': '账务同步延后', 'metrics': [{'label': '积压', 'value': 11, 'target': 3, 'unit': '条', 'direction': 'lower'}, {'label': '同步延时', 'value': 8, 'target': 2, 'unit': '分钟', 'direction': 'lower'}]},
                ],
            },
        ],
        'dependencies': [
            {'id': 'nginx-ingress', 'name': 'Nginx Ingress', 'role': 'upstream', 'kind': '入口', 'base_status': 'warning', 'metrics': [{'label': '入口 P95', 'value': 24, 'target': 15, 'unit': 'ms', 'direction': 'lower'}, {'label': '入口错误率', 'value': 0.2, 'target': 0.1, 'unit': '%', 'direction': 'lower'}], 'impact': '入口时延抬头，故障更容易扩散到业务层。'},
            {'id': 'order-db', 'name': '订单数据库', 'role': 'downstream', 'kind': '数据库', 'base_status': 'critical', 'metrics': [{'label': '慢查询', 'value': 34, 'target': 12, 'unit': '条', 'direction': 'lower'}, {'label': '连接池', 'value': 88, 'target': 70, 'unit': '%', 'direction': 'lower'}], 'impact': '订单写入超时与重试放大。'},
            {'id': 'pay-queue', 'name': '支付消息队列', 'role': 'downstream', 'kind': '消息队列', 'base_status': 'warning', 'metrics': [{'label': '积压', 'value': 18, 'target': 6, 'unit': '条', 'direction': 'lower'}, {'label': '消费延时', 'value': 12, 'target': 4, 'unit': '分钟', 'direction': 'lower'}], 'impact': '支付回调和账务同步都受其影响。'},
        ],
        'playbook': [
            '先锁定网关和支付服务的慢 Span，再看订单库连接池和消息队列。',
            '在日志中心用 trace_id 回放回调链路，确认是外部超时还是内部重试。',
            '如果发布刚完成，优先对照最近变更与回滚窗口。',
        ],
    },
    {
        'id': 'member-fulfillment',
        'name': '会员与履约',
        'domain': '会员域 / 履约域',
        'owner': '会员与物流',
        'tier': 'P1',
        'base_status': 'warning',
        'keywords': ['member-service', 'warehouse-service', 'delivery-service', 'coupon-service', '会员', '履约', '仓库', '配送'],
        'north_star': {'label': '会员请求成功率', 'value': 98.6, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
        'summary': '会员查询正常，但履约链路出现等待和重试堆积。',
        'focus_service_id': 'member-service',
        'focus_interface_id': 'member-profile',
        'focus_keyword': '会员中心与履约查询',
        'service_specs': [
            {
                'id': 'member-service',
                'name': '会员服务',
                'role': '业务模块',
                'base_status': 'warning',
                'metrics': [
                    {'label': '成功率', 'value': 98.9, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
                    {'label': '缓存命中率', 'value': 86, 'target': 92, 'unit': '%', 'direction': 'higher'},
                    {'label': 'P95 延迟', 'value': 680, 'target': 300, 'unit': 'ms', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'member-profile', 'name': 'GET /api/members/profile', 'base_status': 'warning', 'hint': '会员信息读取变慢', 'metrics': [{'label': 'P95', 'value': 710, 'target': 280, 'unit': 'ms', 'direction': 'lower'}, {'label': '缓存命中率', 'value': 83, 'target': 90, 'unit': '%', 'direction': 'higher'}]},
                    {'id': 'member-points', 'name': 'GET /api/members/points', 'base_status': 'healthy', 'hint': '积分查询仍稳定', 'metrics': [{'label': 'P95', 'value': 190, 'target': 250, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.08, 'target': 0.3, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'coupon-service',
                'name': '优惠券服务',
                'role': '业务模块',
                'base_status': 'healthy',
                'metrics': [
                    {'label': '核销成功率', 'value': 99.4, 'target': 99.5, 'unit': '%', 'direction': 'higher'},
                    {'label': '库存耗尽率', 'value': 2, 'target': 5, 'unit': '%', 'direction': 'lower'},
                    {'label': 'P95 延迟', 'value': 260, 'target': 350, 'unit': 'ms', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'coupon-issue', 'name': 'POST /api/coupons/issue', 'base_status': 'healthy', 'hint': '券发放正常', 'metrics': [{'label': '成功率', 'value': 99.6, 'target': 99.5, 'unit': '%', 'direction': 'higher'}, {'label': 'P95', 'value': 220, 'target': 350, 'unit': 'ms', 'direction': 'lower'}]},
                    {'id': 'coupon-redeem', 'name': 'POST /api/coupons/redeem', 'base_status': 'warning', 'hint': '核销与库存更新轻微抖动', 'metrics': [{'label': '错误率', 'value': 0.7, 'target': 0.3, 'unit': '%', 'direction': 'lower'}, {'label': 'P95', 'value': 410, 'target': 300, 'unit': 'ms', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'warehouse-service',
                'name': '仓库服务',
                'role': '下游系统',
                'base_status': 'warning',
                'metrics': [
                    {'label': '出库成功率', 'value': 97.9, 'target': 99.6, 'unit': '%', 'direction': 'higher'},
                    {'label': '库存同步延迟', 'value': 7, 'target': 3, 'unit': '分钟', 'direction': 'lower'},
                    {'label': '补偿任务', 'value': 13, 'target': 4, 'unit': '条', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'warehouse-stock', 'name': 'GET /api/warehouse/stock', 'base_status': 'warning', 'hint': '库存同步有时滞', 'metrics': [{'label': 'P95', 'value': 540, 'target': 260, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.8, 'target': 0.2, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'warehouse-pick', 'name': 'POST /api/warehouse/pick', 'base_status': 'critical', 'hint': '拣货任务排队增加', 'metrics': [{'label': 'P95', 'value': 980, 'target': 420, 'unit': 'ms', 'direction': 'lower'}, {'label': '超时率', 'value': 1.8, 'target': 0.4, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
        ],
        'dependencies': [
            {'id': 'member-cache', 'name': '会员缓存', 'role': 'upstream', 'kind': '缓存', 'base_status': 'warning', 'metrics': [{'label': '命中率', 'value': 86, 'target': 92, 'unit': '%', 'direction': 'higher'}, {'label': '延时', 'value': 7, 'target': 3, 'unit': 'ms', 'direction': 'lower'}], 'impact': '缓存退化会放大会员查询的 P95。'},
            {'id': 'fulfillment-queue', 'name': '履约队列', 'role': 'downstream', 'kind': '消息队列', 'base_status': 'critical', 'metrics': [{'label': '积压', 'value': 13, 'target': 4, 'unit': '条', 'direction': 'lower'}, {'label': '消费延时', 'value': 9, 'target': 3, 'unit': '分钟', 'direction': 'lower'}], 'impact': '履约任务堆积会拖慢出库与配送。'},
            {'id': 'delivery-service', 'name': '配送服务', 'role': 'downstream', 'kind': '外部接口', 'base_status': 'warning', 'metrics': [{'label': '超时率', 'value': 1.1, 'target': 0.3, 'unit': '%', 'direction': 'lower'}, {'label': 'P95', 'value': 620, 'target': 320, 'unit': 'ms', 'direction': 'lower'}], 'impact': '配送回执超时会影响订单闭环。'},
        ],
        'playbook': [
            '优先看会员缓存命中率和履约队列积压是否同步波动。',
            '结合最近发布与库存同步事件，判断是数据不一致还是下游超时。',
            '必要时先恢复拣货与出库链路，再回头清理缓存。',
        ],
    },
    {
        'id': 'observability-stack',
        'name': '观测基础设施',
        'domain': '平台域',
        'owner': '平台可观测组',
        'tier': 'P1',
        'base_status': 'warning',
        'keywords': ['loki', 'tempo', 'grafana', 'alertmanager', 'observability', '日志', '链路', '看板', '告警'],
        'north_star': {'label': '观测接入成功率', 'value': 99.2, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
        'summary': '日志与链路链路基本可用，但查询延迟有轻微抬头。',
        'focus_service_id': 'grafana',
        'focus_interface_id': 'grafana-dashboards',
        'focus_keyword': '日志、链路、看板关联',
        'service_specs': [
            {
                'id': 'grafana',
                'name': 'Grafana',
                'role': '可视化入口',
                'base_status': 'healthy',
                'metrics': [
                    {'label': '看板数', 'value': 5, 'target': 4, 'unit': '个', 'direction': 'higher'},
                    {'label': '面板数', 'value': 70, 'target': 50, 'unit': '个', 'direction': 'higher'},
                    {'label': '嵌入成功率', 'value': 99.6, 'target': 99.5, 'unit': '%', 'direction': 'higher'},
                ],
                'interfaces': [
                    {'id': 'grafana-dashboards', 'name': '推荐看板集', 'base_status': 'healthy', 'hint': '看板入口稳定', 'metrics': [{'label': '加载成功率', 'value': 99.5, 'target': 99.2, 'unit': '%', 'direction': 'higher'}, {'label': '切换耗时', 'value': 120, 'target': 180, 'unit': 'ms', 'direction': 'lower'}]},
                    {'id': 'grafana-link', 'name': '日志 / 链路 跳转', 'base_status': 'warning', 'hint': '外部关联模板需确认', 'metrics': [{'label': '命中率', 'value': 96.8, 'target': 98.0, 'unit': '%', 'direction': 'higher'}, {'label': '跳转耗时', 'value': 240, 'target': 180, 'unit': 'ms', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'loki',
                'name': 'Loki',
                'role': '日志存储',
                'base_status': 'warning',
                'metrics': [
                    {'label': '查询成功率', 'value': 98.7, 'target': 99.5, 'unit': '%', 'direction': 'higher'},
                    {'label': '查询 P95', 'value': 920, 'target': 500, 'unit': 'ms', 'direction': 'lower'},
                    {'label': '热分片数', 'value': 12, 'target': 8, 'unit': '个', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'loki-query', 'name': '日志检索', 'base_status': 'warning', 'hint': '查询窗口增大时明显变慢', 'metrics': [{'label': 'P95', 'value': 940, 'target': 500, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.5, 'target': 0.2, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'loki-ingest', 'name': '日志写入', 'base_status': 'healthy', 'hint': '写入链路仍稳定', 'metrics': [{'label': '写入成功率', 'value': 99.8, 'target': 99.5, 'unit': '%', 'direction': 'higher'}, {'label': '堆积', 'value': 1, 'target': 5, 'unit': '批', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'tempo',
                'name': 'Tempo',
                'role': '链路存储',
                'base_status': 'healthy',
                'metrics': [
                    {'label': 'Trace 查询成功率', 'value': 99.4, 'target': 99.5, 'unit': '%', 'direction': 'higher'},
                    {'label': '查询 P95', 'value': 430, 'target': 500, 'unit': 'ms', 'direction': 'lower'},
                    {'label': '活跃服务数', 'value': 18, 'target': 15, 'unit': '个', 'direction': 'higher'},
                ],
                'interfaces': [
                    {'id': 'tempo-query', 'name': 'Trace 查询', 'base_status': 'healthy', 'hint': '标准 Trace 检索可用', 'metrics': [{'label': 'P95', 'value': 390, 'target': 500, 'unit': 'ms', 'direction': 'lower'}, {'label': '命中率', 'value': 99.2, 'target': 99.0, 'unit': '%', 'direction': 'higher'}]},
                    {'id': 'tempo-detail', 'name': 'Span 详情', 'base_status': 'warning', 'hint': '详情页偶发回落', 'metrics': [{'label': 'P95', 'value': 520, 'target': 400, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.4, 'target': 0.2, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
        ],
        'dependencies': [
            {'id': 'alertmanager', 'name': 'Alertmanager', 'role': 'upstream', 'kind': '告警聚合', 'base_status': 'warning', 'metrics': [{'label': '抑制命中率', 'value': 82, 'target': 90, 'unit': '%', 'direction': 'higher'}, {'label': '告警延时', 'value': 6, 'target': 3, 'unit': '分钟', 'direction': 'lower'}], 'impact': '告警聚合稍有抖动，但仍可追踪。'},
            {'id': 'link-rules', 'name': '可观测关联规则', 'role': 'downstream', 'kind': '配置', 'base_status': 'healthy', 'metrics': [{'label': '关联命中率', 'value': 99.1, 'target': 99.0, 'unit': '%', 'direction': 'higher'}, {'label': '规则数', 'value': 4, 'target': 3, 'unit': '组', 'direction': 'higher'}], 'impact': '日志、链路、看板之间的跳转规则保持稳定。'},
            {'id': 'query-proxy', 'name': '查询代理', 'role': 'downstream', 'kind': '入口', 'base_status': 'warning', 'metrics': [{'label': 'P95', 'value': 290, 'target': 180, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.5, 'target': 0.2, 'unit': '%', 'direction': 'lower'}], 'impact': '统一查询入口略有抖动。'},
        ],
        'playbook': [
            '先确认 Grafana、Loki、Tempo 三者的查询入口是否都能通。',
            '若日志跳转失效，优先看关联规则和数据源映射。',
            '可观测基础设施恢复后，再回到业务链路二次定位。',
        ],
    },
    {
        'id': 'platform-edge',
        'name': '平台入口与网络',
        'domain': '基础设施域',
        'owner': '基础设施与 SRE',
        'tier': 'P1',
        'base_status': 'warning',
        'keywords': ['nginx', 'gateway', 'dns', 'cdn', '入口', '网络', '边界', '路由'],
        'north_star': {'label': '入口成功率', 'value': 99.1, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
        'summary': '入口侧的 4xx / 5xx 有轻微波动，影响多个业务系统。',
        'focus_service_id': 'nginx-ingress',
        'focus_interface_id': 'ingress-api',
        'focus_keyword': '入口流量与网络',
        'service_specs': [
            {
                'id': 'nginx-ingress',
                'name': 'Nginx Ingress',
                'role': '入口层',
                'base_status': 'warning',
                'metrics': [
                    {'label': 'QPS', 'value': 2680, 'target': 2200, 'unit': '', 'direction': 'higher'},
                    {'label': '4xx / 5xx', 'value': 1.7, 'target': 0.8, 'unit': '%', 'direction': 'lower'},
                    {'label': 'P95 延迟', 'value': 320, 'target': 220, 'unit': 'ms', 'direction': 'lower'},
                ],
                'interfaces': [
                    {'id': 'ingress-api', 'name': '域名 / 路由入口', 'base_status': 'warning', 'hint': '部分域名命中慢路由', 'metrics': [{'label': 'P95', 'value': 340, 'target': 220, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 1.2, 'target': 0.4, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'ingress-ssl', 'name': '证书与 TLS', 'base_status': 'healthy', 'hint': '证书仍可用', 'metrics': [{'label': '剩余天数', 'value': 54, 'target': 30, 'unit': '天', 'direction': 'higher'}, {'label': '握手失败率', 'value': 0.02, 'target': 0.1, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'dns-service',
                'name': 'DNS 服务',
                'role': '边界依赖',
                'base_status': 'healthy',
                'metrics': [
                    {'label': '解析成功率', 'value': 99.98, 'target': 99.9, 'unit': '%', 'direction': 'higher'},
                    {'label': 'P95 延迟', 'value': 42, 'target': 80, 'unit': 'ms', 'direction': 'lower'},
                    {'label': '缓存命中率', 'value': 97, 'target': 95, 'unit': '%', 'direction': 'higher'},
                ],
                'interfaces': [
                    {'id': 'dns-public', 'name': '公网域名解析', 'base_status': 'healthy', 'hint': '解析稳定', 'metrics': [{'label': 'P95', 'value': 48, 'target': 80, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.02, 'target': 0.1, 'unit': '%', 'direction': 'lower'}]},
                    {'id': 'dns-private', 'name': '内网解析', 'base_status': 'healthy', 'hint': '内部域名未见抖动', 'metrics': [{'label': 'P95', 'value': 36, 'target': 70, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.01, 'target': 0.05, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
            {
                'id': 'cdn-service',
                'name': 'CDN 回源',
                'role': '边界依赖',
                'base_status': 'warning',
                'metrics': [
                    {'label': '回源成功率', 'value': 98.8, 'target': 99.5, 'unit': '%', 'direction': 'higher'},
                    {'label': '回源延时', 'value': 280, 'target': 180, 'unit': 'ms', 'direction': 'lower'},
                    {'label': '命中率', 'value': 91, 'target': 94, 'unit': '%', 'direction': 'higher'},
                ],
                'interfaces': [
                    {'id': 'cdn-static', 'name': '静态资源分发', 'base_status': 'healthy', 'hint': '静态资源仍可缓存命中', 'metrics': [{'label': '命中率', 'value': 95, 'target': 94, 'unit': '%', 'direction': 'higher'}, {'label': 'P95', 'value': 100, 'target': 150, 'unit': 'ms', 'direction': 'lower'}]},
                    {'id': 'cdn-origin', 'name': '源站回源', 'base_status': 'warning', 'hint': '源站回源偶有抖动', 'metrics': [{'label': 'P95', 'value': 310, 'target': 180, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.9, 'target': 0.2, 'unit': '%', 'direction': 'lower'}]},
                ],
            },
        ],
        'dependencies': [
            {'id': 'dns-resolver', 'name': 'DNS 解析', 'role': 'upstream', 'kind': '基础设施', 'base_status': 'healthy', 'metrics': [{'label': 'P95', 'value': 42, 'target': 80, 'unit': 'ms', 'direction': 'lower'}, {'label': '错误率', 'value': 0.02, 'target': 0.1, 'unit': '%', 'direction': 'lower'}], 'impact': '解析保持稳定，入口异常多半不是 DNS 造成。'},
            {'id': 'waf-rule', 'name': 'WAF 规则', 'role': 'upstream', 'kind': '安全', 'base_status': 'warning', 'metrics': [{'label': '拦截率', 'value': 9, 'target': 5, 'unit': '%', 'direction': 'lower'}, {'label': '误杀率', 'value': 0.3, 'target': 0.1, 'unit': '%', 'direction': 'lower'}], 'impact': '误杀会直接表现为入口 4xx 上升。'},
            {'id': 'origin-hosts', 'name': '源站主机', 'role': 'downstream', 'kind': '主机池', 'base_status': 'warning', 'metrics': [{'label': '在线率', 'value': 98.9, 'target': 99.5, 'unit': '%', 'direction': 'higher'}, {'label': '连接池', 'value': 84, 'target': 70, 'unit': '%', 'direction': 'lower'}], 'impact': '源站主机繁忙会拖慢整体入口。'},
        ],
        'playbook': [
            '先区分是 DNS、WAF 还是源站的问题。',
            '入口侧异常往往会同时放大多个业务系统的健康波动。',
            '将入口延迟与业务慢 Span 对齐后再决定是否回滚。',
        ],
    },
]


def _system_posture_slug(value, fallback='node'):
    text = re.sub(r'[^a-zA-Z0-9]+', '-', str(value or '').strip().lower()).strip('-')
    return text[:48] or fallback


def _system_posture_environment_label(key):
    normalized = str(key or '').strip() or 'prod'
    labels = {
        'prod': '生产环境',
        'production': '生产环境',
        'staging': '预发环境',
        'stage': '预发环境',
        'pre': '预发环境',
        'test': '测试环境',
        'testing': '测试环境',
        'dev': '开发环境',
        'development': '开发环境',
        'default': '默认环境',
    }
    return labels.get(normalized.lower()) or normalized


def _system_posture_environments(templates):
    configured = list(SystemPostureEnvironment.objects.filter(is_enabled=True).order_by('sort_order', 'id'))
    configured_keys = {item.key for item in configured}
    used_keys = {
        str(template.get('environment') or 'prod').strip() or 'prod'
        for template in templates
    }
    items = [
        {
            'id': item.id,
            'key': item.key,
            'name': item.name,
            'sort_order': item.sort_order,
            'source': 'configured',
        }
        for item in configured
    ]
    for key in sorted(used_keys - configured_keys):
        items.append({
            'id': None,
            'key': key,
            'name': _system_posture_environment_label(key),
            'sort_order': 1000,
            'source': 'derived',
        })
    if not items:
        items.append({
            'id': None,
            'key': 'prod',
            'name': '生产环境',
            'sort_order': 1000,
            'source': 'derived',
        })
    return items


def _system_posture_default_metric(system):
    north_star = system.north_star if isinstance(system.north_star, dict) else {}
    return {
        'label': north_star.get('label') or '可用率',
        'value': north_star.get('value', 99),
        'target': north_star.get('target', 99.9),
        'unit': north_star.get('unit') or '%',
        'direction': north_star.get('direction') or 'higher',
    }


def _system_posture_builtin_form(template):
    return {
        'id': '',
        'name': template.get('name') or '',
        'environment': template.get('environment') or 'prod',
        'domain': template.get('domain') or '',
        'tier': template.get('tier') or '',
        'owner': template.get('owner') or '',
        'summary': template.get('summary') or '',
        'base_status': template.get('base_status') or 'healthy',
        'health_score': template.get('health_score'),
        'keywords': template.get('keywords') or [],
        'north_star': template.get('north_star') or {},
        'metrics': template.get('metrics') or [],
        'service_specs': template.get('service_specs') or [],
        'dependencies': template.get('dependencies') or [],
        'rule_config': _system_posture_rule_config(template),
        'playbook': template.get('playbook') or [],
        'focus_service_id': template.get('focus_service_id') or '',
        'focus_interface_id': template.get('focus_interface_id') or '',
        'focus_keyword': template.get('focus_keyword') or template.get('name') or '',
        'sort_order': template.get('sort_order') or 100,
        'is_enabled': True,
    }


def _system_posture_system_to_template(system, builtin_backed=False):
    system_id = f'custom-{system.id}'
    slug = _system_posture_slug(system.name, f'custom-{system.id}')
    north_star = _system_posture_default_metric(system)
    service_specs = system.service_specs if isinstance(system.service_specs, list) else []
    dependencies = system.dependencies if isinstance(system.dependencies, list) else []
    metrics = system.metrics if isinstance(system.metrics, list) else []
    rule_config = system.rule_config if isinstance(system.rule_config, dict) else {}
    keywords = system.keywords if isinstance(system.keywords, list) else []
    playbook = system.playbook if isinstance(system.playbook, list) else []

    if not service_specs:
        service_id = f'{system_id}-{slug}-core'
        interface_id = f'{system_id}-{slug}-api'
        service_specs = [
            {
                'id': service_id,
                'name': f'{system.name} 核心服务',
                'role': system.tier or '核心链路',
                'base_status': system.base_status,
                'metrics': metrics or [north_star],
                'interfaces': [
                    {
                        'id': interface_id,
                        'name': f'{system.name} 关键接口',
                        'base_status': system.base_status,
                        'hint': system.summary or '从核心指标继续下钻定位接口层异常。',
                        'metrics': metrics or [north_star],
                    }
                ],
            }
        ]

    if not dependencies:
        dependencies = [
            {
                'id': f'{system_id}-{slug}-gateway',
                'name': '入口网关',
                'role': 'upstream',
                'kind': '网关',
                'base_status': 'healthy' if system.base_status == 'healthy' else 'warning',
                'metrics': [{'label': '可用率', 'value': 99.9, 'target': 99.5, 'unit': '%', 'direction': 'higher'}],
                'impact': '入口侧稳定性会影响该系统的外部可用性。',
            },
            {
                'id': f'{system_id}-{slug}-storage',
                'name': '数据存储',
                'role': 'downstream',
                'kind': '数据库',
                'base_status': 'healthy',
                'metrics': [{'label': 'P95', 'value': 48, 'target': 80, 'unit': 'ms', 'direction': 'lower'}],
                'impact': '存储延迟会直接放大接口耗时。',
            },
        ]

    form_payload = {
        'id': system.id,
        'name': system.name,
        'environment': system.environment or 'prod',
        'domain': system.domain,
        'tier': system.tier,
        'owner': system.owner,
        'summary': system.summary,
        'base_status': system.base_status,
        'health_score': system.health_score,
        'keywords': keywords,
        'north_star': north_star,
        'metrics': metrics,
        'service_specs': service_specs,
        'dependencies': dependencies,
        'rule_config': rule_config,
        'playbook': playbook,
        'focus_service_id': system.focus_service_id,
        'focus_interface_id': system.focus_interface_id,
        'focus_keyword': system.focus_keyword,
        'sort_order': system.sort_order,
        'is_enabled': system.is_enabled,
    }

    return {
        'id': system_id,
        'source': 'custom',
        'source_id': system.id,
        'editable': True,
        'builtin_backed': builtin_backed,
        'name': system.name,
        'environment': system.environment or 'prod',
        'domain': system.domain or '未分组',
        'tier': system.tier or '业务系统',
        'owner': system.owner or '未设置',
        'summary': system.summary or '自定义系统态势卡片，支持按关键字对齐告警、日志、Trace 和事件。',
        'base_status': system.base_status,
        'health_score': system.health_score,
        'keywords': keywords or [system.name, system.domain, system.owner],
        'north_star': north_star,
        'metrics': metrics,
        'service_specs': service_specs,
        'dependencies': dependencies,
        'rule_config': rule_config,
        'playbook': playbook or ['确认北极星指标是否持续异常。', '沿层级下钻定位服务与接口。', '回到日志、Trace 与变更证据核对时间线。'],
        'focus_service_id': system.focus_service_id or (service_specs[0].get('id') if service_specs else ''),
        'focus_interface_id': system.focus_interface_id or ((service_specs[0].get('interfaces') or [{}])[0].get('id') if service_specs else ''),
        'focus_keyword': system.focus_keyword or system.name,
        'form': form_payload,
    }


def _system_posture_templates():
    systems = list(SystemPostureSystem.objects.all())
    custom_by_name = {system.name: system for system in systems}
    builtin_names = {item['name'] for item in FIREMAP_SYSTEM_TEMPLATES}
    templates = []

    for item in FIREMAP_SYSTEM_TEMPLATES:
        override = custom_by_name.get(item['name'])
        if override:
            if override.is_enabled:
                templates.append(_system_posture_system_to_template(override, builtin_backed=True))
            continue
        templates.append({
            **item,
            'source': 'builtin',
            'source_id': '',
            'editable': True,
            'builtin_backed': True,
            'form': _system_posture_builtin_form(item),
        })

    for system in systems:
        if system.name in builtin_names or not system.is_enabled:
            continue
        templates.append(_system_posture_system_to_template(system))
    return templates


def _status_rank(status):
    return FIREMAP_STATUS_META.get(status, FIREMAP_STATUS_META['healthy'])['rank']


def _status_tone(status):
    return FIREMAP_STATUS_META.get(status, FIREMAP_STATUS_META['healthy'])['tone']


def _metric_status(metric):
    status = str(metric.get('status') or '').strip()
    if status in FIREMAP_STATUS_META:
        return status
    try:
        value = float(metric.get('value'))
        target = float(metric.get('target'))
    except (TypeError, ValueError):
        return metric.get('base_status') or 'healthy'
    direction = str(metric.get('direction') or 'lower').strip()
    if direction == 'higher':
        if value >= target:
            return 'healthy'
        if value >= target * 0.95:
            return 'warning'
        return 'critical'
    if value <= target:
        return 'healthy'
    if value <= target * 1.2:
        return 'warning'
    return 'critical'


def _normalize_metric(metric):
    item = dict(metric)
    item['status'] = _metric_status(item)
    item['tone'] = _status_tone(item['status'])
    return item


def _text_block(*values):
    parts = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if item)
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value if item)
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return ' '.join(parts).lower()


def _keywords_match(text, keywords):
    haystack = str(text or '').lower()
    return any(str(keyword or '').lower() in haystack for keyword in (keywords or []))


def _record_matches_keywords(record_text, keywords):
    return _keywords_match(record_text, keywords)


ECOMMERCE_FIREMAP_NAME = '电商交易核心'
ECOMMERCE_NAMESPACE = 'ecommerce'
ECOMMERCE_PROMQL_WINDOW = '5m'
ECOMMERCE_SERVICE_PATTERN = 'api-gateway|cart|order|inventory|catalog'
ECOMMERCE_SERVICE_SPECS = [
    {
        'id': 'api-gateway',
        'name': 'API 网关',
        'role': '入口层',
        'target_ms': 500,
        'paths': [
            {'id': 'gateway-checkout', 'name': 'POST /api/checkout', 'path': '/api/checkout', 'target_ms': 500, 'hint': '下单入口，成功率来自 checkout outcome 业务指标。'},
            {'id': 'gateway-cart-add', 'name': 'POST /api/cart/<user_id>/items', 'path': '/api/cart/<user_id>/items', 'target_ms': 300, 'hint': '加购入口，联动 catalog 与 cart 服务。'},
            {'id': 'gateway-cart-query', 'name': 'GET /api/cart/<user_id>', 'path': '/api/cart/<user_id>', 'target_ms': 250, 'hint': '购物车查询，联动 cart 与 Redis。'},
            {'id': 'gateway-products', 'name': 'GET /api/products', 'path': '/api/products', 'target_ms': 350, 'hint': '商品浏览入口，联动 catalog 与 inventory。'},
        ],
    },
    {
        'id': 'cart',
        'name': '购物车服务',
        'role': '交易前置',
        'target_ms': 250,
        'paths': [
            {'id': 'cart-add', 'name': 'POST /cart/<user_id>/items', 'path': '/cart/<user_id>/items', 'target_ms': 180, 'hint': '购物车写入接口，依赖 Redis。'},
            {'id': 'cart-query', 'name': 'GET /cart/<user_id>', 'path': '/cart/<user_id>', 'target_ms': 120, 'hint': '购物车读取接口，依赖 Redis。'},
        ],
    },
    {
        'id': 'order',
        'name': '订单服务',
        'role': '交易核心',
        'target_ms': 450,
        'paths': [
            {'id': 'order-create', 'name': 'POST /orders', 'path': '/orders', 'target_ms': 350, 'hint': '订单创建接口，依赖 inventory、PostgreSQL 与 Kafka。'},
        ],
    },
    {
        'id': 'inventory',
        'name': '库存服务',
        'role': '履约校验',
        'target_ms': 250,
        'paths': [
            {'id': 'inventory-availability', 'name': 'POST /availability', 'path': '/availability', 'target_ms': 160, 'hint': '库存可用性检查，直接影响下单成功率。'},
        ],
    },
    {
        'id': 'catalog',
        'name': '商品服务',
        'role': '商品读取',
        'target_ms': 250,
        'paths': [
            {'id': 'catalog-list', 'name': 'GET /products', 'path': '/products', 'target_ms': 180, 'hint': '商品列表接口。'},
            {'id': 'catalog-detail', 'name': 'GET /products/<int:product_id>', 'path': '/products/<int:product_id>', 'target_ms': 180, 'hint': '商品详情接口，加购前置依赖。'},
        ],
    },
]
ECOMMERCE_DEPENDENCIES = [
    {'id': 'postgres', 'name': 'PostgreSQL', 'role': 'downstream', 'kind': '数据库', 'impact': '订单写入与库存查询异常会直接影响下单。'},
    {'id': 'redis', 'name': 'Redis', 'role': 'downstream', 'kind': '缓存', 'impact': '购物车读写依赖 Redis，异常会阻断下单前置流程。'},
    {'id': 'kafka', 'name': 'Kafka', 'role': 'downstream', 'kind': '消息队列', 'impact': '订单事件写入 Kafka，异常会影响库存异步扣减。'},
]
ECOMMERCE_FIREMAP_RULE_CONFIG = {
    'version': 1,
    'enabled': True,
    'engine': 'prometheus-tempo',
    'namespace': ECOMMERCE_NAMESPACE,
    'window': ECOMMERCE_PROMQL_WINDOW,
    'service_pattern': ECOMMERCE_SERVICE_PATTERN,
    'description': '电商交易核心实时规则：Prometheus 计算业务成功率、健康分和下钻指标，Tempo 补充最近链路。',
    'overview_metrics': ['checkout_conflict_rate', 'checkout_5xx_rate', 'checkout_p95_ms', 'checkout_rps'],
    'prometheus': {
        'scalars': {
            'checkout_success_rate': {
                'label': '下单成功率',
                'target': 99,
                'unit': '%',
                'direction': 'higher',
                'query': '100 * sum(rate(ecommerce_checkout_outcomes_total{namespace="{namespace}",service="api-gateway",outcome="success"}[{window}])) / clamp_min(sum(rate(ecommerce_checkout_outcomes_total{namespace="{namespace}",service="api-gateway",outcome=~"success|conflict"}[{window}])), 0.000001)',
                'fallback_query': '100 * sum(rate(ecommerce_http_requests_total{namespace="{namespace}",service="api-gateway",path="/api/checkout",status=~"2.."}[{window}])) / clamp_min(sum(rate(ecommerce_http_requests_total{namespace="{namespace}",service="api-gateway",path="/api/checkout"}[{window}])), 0.000001)',
                'explain': '成功下单 / (成功下单 + 库存冲突拒单) * 100；指标缺失时降级为 /api/checkout 2xx / 全部 checkout 请求。',
            },
            'checkout_conflict_rate': {
                'label': 'Checkout 409占比',
                'target': 1,
                'unit': '%',
                'direction': 'lower',
                'query': '100 * sum(rate(ecommerce_checkout_outcomes_total{namespace="{namespace}",service="api-gateway",outcome="conflict"}[{window}])) / clamp_min(sum(rate(ecommerce_checkout_outcomes_total{namespace="{namespace}",service="api-gateway",outcome=~"success|conflict"}[{window}])), 0.000001)',
            },
            'checkout_5xx_rate': {
                'label': 'Checkout 5xx占比',
                'target': 1,
                'unit': '%',
                'direction': 'lower',
                'query': '100 * sum(rate(ecommerce_http_requests_total{namespace="{namespace}",service="api-gateway",path="/api/checkout",status=~"5.."}[{window}])) / clamp_min(sum(rate(ecommerce_http_requests_total{namespace="{namespace}",service="api-gateway",path="/api/checkout"}[{window}])), 0.000001)',
            },
            'checkout_rps': {
                'label': 'Checkout RPS',
                'target': 0.01,
                'unit': '',
                'direction': 'higher',
                'query': 'sum(rate(ecommerce_http_requests_total{namespace="{namespace}",service="api-gateway",path="/api/checkout"}[{window}]))',
            },
            'checkout_p95_ms': {
                'label': 'Checkout P95',
                'target': 500,
                'unit': 'ms',
                'direction': 'lower',
                'scale': 1000,
                'query': 'histogram_quantile(0.95, sum by (le) (rate(ecommerce_http_request_duration_seconds_bucket{namespace="{namespace}",service="api-gateway",path="/api/checkout"}[{window}])))',
            },
        },
        'series': {
            'service_rps': {
                'labels': ['service'],
                'query': 'sum by (service) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}]))',
            },
            'service_success_rate': {
                'labels': ['service'],
                'query': '100 * sum by (service) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}",status!~"5.."}[{window}])) / clamp_min(sum by (service) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}])), 0.000001)',
            },
            'service_2xx_rate': {
                'labels': ['service'],
                'query': '100 * sum by (service) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}",status=~"2.."}[{window}])) / clamp_min(sum by (service) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}])), 0.000001)',
            },
            'service_p95_ms': {
                'labels': ['service'],
                'scale': 1000,
                'query': 'histogram_quantile(0.95, sum by (service, le) (rate(ecommerce_http_request_duration_seconds_bucket{namespace="{namespace}",service=~"{services}"}[{window}])))',
            },
            'path_rps': {
                'labels': ['service', 'path'],
                'query': 'sum by (service,path) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}]))',
            },
            'path_success_rate': {
                'labels': ['service', 'path'],
                'query': '100 * sum by (service,path) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}",status!~"5.."}[{window}])) / clamp_min(sum by (service,path) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}])), 0.000001)',
            },
            'path_2xx_rate': {
                'labels': ['service', 'path'],
                'query': '100 * sum by (service,path) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}",status=~"2.."}[{window}])) / clamp_min(sum by (service,path) (rate(ecommerce_http_requests_total{namespace="{namespace}",service=~"{services}"}[{window}])), 0.000001)',
            },
            'path_p95_ms': {
                'labels': ['service', 'path'],
                'scale': 1000,
                'query': 'histogram_quantile(0.95, sum by (service,path,le) (rate(ecommerce_http_request_duration_seconds_bucket{namespace="{namespace}",service=~"{services}"}[{window}])))',
            },
            'up': {
                'labels': ['service'],
                'query': 'up{namespace="{namespace}",service=~"{services}"}',
            },
            'deployment_available': {
                'labels': ['deployment'],
                'query': 'kube_deployment_status_replicas_available{namespace="{namespace}"}',
            },
            'deployment_desired': {
                'labels': ['deployment'],
                'query': 'kube_deployment_spec_replicas{namespace="{namespace}"}',
            },
        },
    },
    'north_star': {
        'metric': 'checkout_success_rate',
        'label': '下单成功率',
        'target': 99,
        'unit': '%',
        'direction': 'higher',
    },
    'tempo': {
        'service_id': 'api-gateway',
        'keyword': 'POST /api/checkout',
        'duration_minutes': 30,
        'limit': 8,
    },
    'health_score': {
        'formula': 'success_rate * 0.62 + availability * 0.15 + latency * 0.10 + error_budget * 0.08 + traffic * 0.05 - success_extra_penalty',
        'weights': {
            'success_rate': 0.62,
            'availability': 0.15,
            'latency': 0.10,
            'error_budget': 0.08,
            'traffic': 0.05,
        },
        'defaults': {
            'success_rate': 75,
            'availability': 90,
            'latency': 85,
            'error_budget': 100,
            'traffic': 100,
        },
        'latency_target_ms': 500,
        'latency_penalty_per_ms': 0.0666667,
        'low_traffic_rps': 0.001,
        'low_traffic_score': 80,
        'error_penalty': {
            'checkout_5xx_rate': 12,
            'checkout_conflict_rate': 1.2,
        },
        'success_extra_penalty': {
            'threshold': 95,
            'factor': 0.4,
            'max': 18,
        },
        'availability_workloads': ['api-gateway', 'cart', 'order', 'inventory', 'catalog', 'postgres', 'redis', 'kafka'],
    },
    'status_rules': {
        'critical': {
            'health_score_lt': 70,
            'success_rate_lt': 95,
            'checkout_5xx_rate_gte': 5,
        },
        'warning': {
            'health_score_lt': 90,
            'success_rate_lt': 99,
            'checkout_conflict_rate_gte': 1,
            'checkout_p95_ms_gt': 500,
        },
    },
    'root_cause_rules': [
        {
            'id': 'inventory-conflict',
            'label': '库存冲突',
            'metric': 'checkout_conflict_rate',
            'min_rate': 1,
            'critical_rate': 50,
            'min_rps': 0.001,
            'zero_success_is_critical': True,
            'target_service_id': 'inventory',
            'target_interface_id': 'inventory-availability',
            'metric_label': '库存冲突率',
            'warning_message': 'Checkout 409 占比抬头，优先检查库存余量、补货任务和订单库存校验链路。',
            'critical_message': 'Checkout 409 持续发生，当前更像库存不足或库存已耗尽导致的业务拒单。',
        }
    ],
    'drilldown': {
        'services': ECOMMERCE_SERVICE_SPECS,
        'dependencies': ECOMMERCE_DEPENDENCIES,
    },
    'playbook': [
        '先确认下单成功率、Checkout 409 占比、Checkout P95 是否同时异常。',
        '若 Checkout 409 占比抬头，优先检查库存余量和补货任务是否生效。',
        '沿 API 网关 -> cart/order/inventory 下钻，查看接口级成功率与延迟。',
        '若接口正常但成功率下降，继续检查 PostgreSQL、Redis、Kafka 副本可用率。',
        '打开 Tempo 最近链路，核对慢 Span 或错误 Span 的真实下游。',
    ],
}


def _deep_merge_dict(base, override):
    merged = copy.deepcopy(base or {})
    if not isinstance(override, dict):
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _system_posture_rule_config(template):
    configured = template.get('rule_config') if isinstance(template.get('rule_config'), dict) else {}
    if _is_ecommerce_system_posture_template(template):
        return _deep_merge_dict(ECOMMERCE_FIREMAP_RULE_CONFIG, configured)
    return configured


def _rule_window(rule_config):
    return str(rule_config.get('window') or ECOMMERCE_PROMQL_WINDOW).strip() or ECOMMERCE_PROMQL_WINDOW


def _rule_namespace(rule_config):
    return str(rule_config.get('namespace') or ECOMMERCE_NAMESPACE).strip() or ECOMMERCE_NAMESPACE


def _rule_service_pattern(rule_config):
    return str(rule_config.get('service_pattern') or ECOMMERCE_SERVICE_PATTERN).strip() or ECOMMERCE_SERVICE_PATTERN


def _render_system_posture_promql(query, rule_config):
    return (
        str(query or '')
        .replace('{namespace}', _rule_namespace(rule_config))
        .replace('{window}', _rule_window(rule_config))
        .replace('{services}', _rule_service_pattern(rule_config))
    )


def _is_ecommerce_system_posture_template(template):
    name = str(template.get('name') or '').strip()
    return name == ECOMMERCE_FIREMAP_NAME or template.get('id') == 'commerce-core'


def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _prometheus_value(result):
    value = (result.get('value') or [None, None])[1] if isinstance(result, dict) else None
    return _safe_float(value)


def _round_system_posture_value(value, digits=1):
    number = _safe_float(value)
    if number is None:
        return ''
    if abs(number) >= 100:
        return int(round(number))
    if abs(number) >= 10:
        return round(number, 1)
    return round(number, digits)


def _metric(label, value, target, unit='', direction='higher', digits=1, base_status='healthy'):
    item = {
        'label': label,
        'value': _round_system_posture_value(value, digits=digits),
        'target': target,
        'unit': unit,
        'direction': direction,
    }
    if value is None:
        item['base_status'] = base_status
    return item


def _metric_status_rank(metrics):
    statuses = [_metric_status(metric) for metric in metrics or []]
    if 'critical' in statuses:
        return 'critical'
    if 'warning' in statuses:
        return 'warning'
    return 'healthy'


def _is_example_url(value):
    parsed = urlparse(str(value or ''))
    host = (parsed.hostname or '').lower()
    return not host or host.endswith('.example.com') or host in {'example.com', 'demo-loki.example.com'}


def _config_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in {'0', 'false', 'no', 'off'}


def _config_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_tempo_query_url():
    datasource = TracingDataSource.objects.filter(provider='tempo', is_enabled=True).order_by('-is_default', 'name').first()
    if datasource:
        config = datasource.config if isinstance(datasource.config, dict) else {}
        if config.get('query_url'):
            return str(config.get('query_url') or '').strip()
    defaults = _observability_defaults().get('tempo') or {}
    return str(defaults.get('query_url') or '').strip()


def _infer_grafana_url_from_tempo(config):
    tempo_url = _default_tempo_query_url()
    parsed = urlparse(tempo_url)
    if not parsed.scheme or not parsed.hostname or _is_example_url(tempo_url):
        return ''
    port = _config_int(config.get('inferred_grafana_port'), 30300)
    return f'{parsed.scheme}://{parsed.hostname}:{port}'


def _prometheus_headers(config):
    headers = {'Accept': 'application/json'}
    token = str(config.get('grafana_api_token') or config.get('api_token') or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _prometheus_config():
    defaults = _observability_defaults()
    config = dict(defaults.get('prometheus') or {})
    config.setdefault('enabled', True)
    config.setdefault('query_url', '')
    config.setdefault('grafana_url', '')
    config.setdefault('grafana_datasource_uid', 'prometheus-infra')
    config.setdefault('grafana_datasource_id', '')
    config.setdefault('grafana_api_token', '')
    config.setdefault('inferred_grafana_port', 30300)
    config.setdefault('timeout', 6)
    return config


def _resolve_prometheus_client():
    config = _prometheus_config()
    if not _config_bool(config.get('enabled'), True):
        return {'ready': False, 'warning': 'Prometheus 查询已禁用'}

    timeout = _config_int(config.get('timeout'), 6)
    headers = _prometheus_headers(config)
    query_url = str(config.get('query_url') or '').strip().rstrip('/')
    if query_url:
        return {
            'ready': True,
            'base_url': query_url,
            'headers': headers,
            'timeout': timeout,
            'source': 'prometheus',
            'description': 'Prometheus HTTP API',
        }

    grafana_url = str(config.get('grafana_url') or '').strip().rstrip('/')
    if not grafana_url:
        grafana_url = str(_grafana_config().get('url') or '').strip().rstrip('/')
    if not grafana_url:
        grafana_url = _infer_grafana_url_from_tempo(config).rstrip('/')
    if not grafana_url or _is_example_url(grafana_url):
        return {'ready': False, 'warning': '未配置可用的 Prometheus 或 Grafana 地址'}

    datasource_id = str(config.get('grafana_datasource_id') or '').strip()
    datasource_uid = str(config.get('grafana_datasource_uid') or 'prometheus-infra').strip()
    if not datasource_id:
        try:
            response = http_requests.get(
                f'{grafana_url}/api/datasources/uid/{quote(datasource_uid, safe="")}',
                headers=headers,
                timeout=timeout,
            )
            if response.status_code >= 400:
                return {'ready': False, 'warning': f'Grafana 数据源查询失败: HTTP {response.status_code}'}
            body = response.json()
            datasource_id = str(body.get('id') or '').strip()
        except Exception as exc:
            return {'ready': False, 'warning': f'Grafana 数据源查询失败: {exc}'}
    if not datasource_id:
        return {'ready': False, 'warning': 'Grafana Prometheus 数据源 ID 为空'}

    return {
        'ready': True,
        'base_url': f'{grafana_url}/api/datasources/proxy/{datasource_id}',
        'headers': headers,
        'timeout': timeout,
        'source': 'grafana',
        'description': f'Grafana 数据源代理 {datasource_uid}',
    }


def _prometheus_query(client, query):
    response = http_requests.get(
        f"{client['base_url'].rstrip('/')}/api/v1/query",
        params={'query': query},
        headers=client.get('headers') or {},
        timeout=client.get('timeout') or 6,
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Prometheus HTTP {response.status_code}')
    body = response.json()
    if body.get('status') != 'success':
        raise RuntimeError(body.get('error') or 'Prometheus 查询失败')
    return ((body.get('data') or {}).get('result') or [])


def _prometheus_scalar(client, query):
    results = _prometheus_query(client, query)
    return _prometheus_value(results[0]) if results else None


def _prometheus_series_map(client, query, labels):
    mapped = {}
    for result in _prometheus_query(client, query):
        metric = result.get('metric') or {}
        key = tuple(str(metric.get(label) or '') for label in labels)
        if len(key) == 1:
            key = key[0]
        value = _prometheus_value(result)
        if value is not None:
            mapped[key] = value
    return mapped


def _safe_prometheus_scalar(client, query, warnings):
    try:
        return _prometheus_scalar(client, query)
    except Exception as exc:
        warnings.append(str(exc))
        return None


def _safe_prometheus_series_map(client, query, labels, warnings):
    try:
        return _prometheus_series_map(client, query, labels)
    except Exception as exc:
        warnings.append(str(exc))
        return {}


def _ecommerce_prometheus_snapshot(client, rule_config):
    warnings = []
    snapshot = {
        'source': client.get('source'),
        'description': client.get('description'),
        'window': _rule_window(rule_config),
        'namespace': _rule_namespace(rule_config),
        'warnings': warnings,
    }
    prometheus_config = rule_config.get('prometheus') if isinstance(rule_config.get('prometheus'), dict) else {}
    scalar_rules = prometheus_config.get('scalars') if isinstance(prometheus_config.get('scalars'), dict) else {}
    for key, item in scalar_rules.items():
        if not isinstance(item, dict) or not item.get('query'):
            continue
        value = _safe_prometheus_scalar(client, _render_system_posture_promql(item.get('query'), rule_config), warnings)
        if value is None and item.get('fallback_query'):
            value = _safe_prometheus_scalar(client, _render_system_posture_promql(item.get('fallback_query'), rule_config), warnings)
        scale = _safe_float(item.get('scale')) or 1
        snapshot[key] = value * scale if value is not None else None

    series_rules = prometheus_config.get('series') if isinstance(prometheus_config.get('series'), dict) else {}
    for key, item in series_rules.items():
        if not isinstance(item, dict) or not item.get('query'):
            continue
        labels = item.get('labels') if isinstance(item.get('labels'), list) else []
        values = _safe_prometheus_series_map(client, _render_system_posture_promql(item.get('query'), rule_config), labels, warnings)
        scale = _safe_float(item.get('scale')) or 1
        snapshot[key] = {series_key: value * scale for series_key, value in values.items()} if scale != 1 else values

    snapshot['ready'] = any(
        [
            snapshot.get('checkout_success_rate') is not None,
            snapshot.get('service_rps'),
            snapshot.get('up'),
            snapshot.get('deployment_available'),
        ]
    )
    return snapshot


def _deployment_availability(snapshot, deployment):
    available = snapshot.get('deployment_available', {}).get(deployment)
    desired = snapshot.get('deployment_desired', {}).get(deployment)
    if desired is None or desired <= 0:
        return None, available, desired
    return max(0, min(100, available / desired * 100 if available is not None else 0)), available, desired


def _availability_status(availability):
    if availability is None:
        return 'warning'
    if availability >= 100:
        return 'healthy'
    if availability > 0:
        return 'warning'
    return 'critical'


def _ecommerce_scalar_rule(rule_config, metric_key):
    prometheus_config = rule_config.get('prometheus') if isinstance(rule_config.get('prometheus'), dict) else {}
    scalar_rules = prometheus_config.get('scalars') if isinstance(prometheus_config.get('scalars'), dict) else {}
    item = scalar_rules.get(metric_key) if isinstance(scalar_rules.get(metric_key), dict) else {}
    return item


def _ecommerce_configured_metric(rule_config, snapshot, metric_key, label=None, target=None, unit=None, direction=None, digits=1, base_status='healthy'):
    item = _ecommerce_scalar_rule(rule_config, metric_key)
    return _metric(
        label or item.get('label') or metric_key,
        snapshot.get(metric_key),
        target if target is not None else item.get('target'),
        unit if unit is not None else item.get('unit') or '',
        direction if direction is not None else item.get('direction') or 'higher',
        digits=digits,
        base_status=base_status,
    )


def _ecommerce_root_cause_rules(rule_config):
    rules = rule_config.get('root_cause_rules') if isinstance(rule_config.get('root_cause_rules'), list) else []
    return [item for item in rules if isinstance(item, dict)]


def _ecommerce_inventory_conflict_status(snapshot, rule_config):
    matched_rule = {}
    for rule in _ecommerce_root_cause_rules(rule_config):
        if rule.get('id') == 'inventory-conflict' or rule.get('target_service_id') == 'inventory':
            matched_rule = rule
            break
    if not matched_rule:
        return '', '', {}

    metric_key = matched_rule.get('metric') or 'checkout_conflict_rate'
    conflict_rate = snapshot.get(metric_key) or 0
    checkout_rps = snapshot.get('checkout_rps') or 0
    success_rate = snapshot.get('checkout_success_rate')
    min_rate = _safe_float(matched_rule.get('min_rate'))
    critical_rate = _safe_float(matched_rule.get('critical_rate'))
    min_rps = _safe_float(matched_rule.get('min_rps'))
    if min_rate is None:
        min_rate = 1
    if critical_rate is None:
        critical_rate = 50
    if min_rps is None:
        health_config = rule_config.get('health_score') if isinstance(rule_config.get('health_score'), dict) else {}
        min_rps = _safe_float(health_config.get('low_traffic_rps')) or 0.001
    if checkout_rps <= min_rps or conflict_rate < min_rate:
        return '', '', matched_rule
    if conflict_rate >= critical_rate or (matched_rule.get('zero_success_is_critical') and success_rate == 0):
        return 'critical', matched_rule.get('critical_message') or matched_rule.get('warning_message') or '', matched_rule
    return 'warning', matched_rule.get('warning_message') or '', matched_rule


def _ecommerce_conflict_metric(snapshot, rule_config, label=None):
    status_value, _, rule = _ecommerce_inventory_conflict_status(snapshot, rule_config)
    metric_key = rule.get('metric') or 'checkout_conflict_rate'
    target = _safe_float(rule.get('min_rate'))
    item = _ecommerce_configured_metric(
        rule_config,
        snapshot,
        metric_key,
        label=label or _ecommerce_scalar_rule(rule_config, metric_key).get('label') or rule.get('metric_label'),
        target=target if target is not None else None,
        unit='%',
        direction='lower',
    )
    if status_value:
        item['status'] = status_value
    return item


def _ecommerce_health_score(snapshot, rule_config):
    config = rule_config.get('health_score') if isinstance(rule_config.get('health_score'), dict) else {}
    weights = config.get('weights') if isinstance(config.get('weights'), dict) else {}
    defaults = config.get('defaults') if isinstance(config.get('defaults'), dict) else {}
    error_penalty = config.get('error_penalty') if isinstance(config.get('error_penalty'), dict) else {}
    extra_penalty = config.get('success_extra_penalty') if isinstance(config.get('success_extra_penalty'), dict) else {}
    success_rate = snapshot.get('checkout_success_rate')
    conflict_rate = snapshot.get('checkout_conflict_rate') or 0
    rate_5xx = snapshot.get('checkout_5xx_rate') or 0
    p95_ms = snapshot.get('checkout_p95_ms')
    checkout_rps = snapshot.get('checkout_rps')

    success_score = success_rate if success_rate is not None else (defaults.get('success_rate') or 75)
    latency_target = _safe_float(config.get('latency_target_ms')) or 500
    latency_penalty_per_ms = _safe_float(config.get('latency_penalty_per_ms')) or (1 / 15)
    if p95_ms is None:
        latency_score = defaults.get('latency') or 85
    elif p95_ms <= latency_target:
        latency_score = 100
    else:
        latency_score = max(0, 100 - (p95_ms - latency_target) * latency_penalty_per_ms)
    error_score = max(0, (defaults.get('error_budget') or 100) - rate_5xx * (error_penalty.get('checkout_5xx_rate') or 12) - conflict_rate * (error_penalty.get('checkout_conflict_rate') or 1.2))
    low_traffic_rps = _safe_float(config.get('low_traffic_rps'))
    if low_traffic_rps is None:
        low_traffic_rps = 0.001
    traffic_score = (defaults.get('traffic') or 100) if checkout_rps is None or checkout_rps > low_traffic_rps else (config.get('low_traffic_score') or 80)

    availability_scores = []
    availability_workloads = config.get('availability_workloads') if isinstance(config.get('availability_workloads'), list) else []
    for name in availability_workloads or ['api-gateway', 'cart', 'order', 'inventory', 'catalog', 'postgres', 'redis', 'kafka']:
        availability, _, _ = _deployment_availability(snapshot, name)
        if availability is not None:
            availability_scores.append(availability)
    availability_score = sum(availability_scores) / len(availability_scores) if availability_scores else (defaults.get('availability') or 90)

    score = (
        success_score * (weights.get('success_rate') or 0.62)
        + availability_score * (weights.get('availability') or 0.15)
        + latency_score * (weights.get('latency') or 0.10)
        + error_score * (weights.get('error_budget') or 0.08)
        + traffic_score * (weights.get('traffic') or 0.05)
    )
    threshold = _safe_float(extra_penalty.get('threshold'))
    if threshold is None:
        threshold = 95
    if success_rate is not None and success_rate < threshold:
        score -= min(extra_penalty.get('max') or 18, (threshold - success_rate) * (extra_penalty.get('factor') or 0.4))
    return int(max(0, min(100, round(score))))


def _ecommerce_status(snapshot, health_score, rule_config):
    status_rules = rule_config.get('status_rules') if isinstance(rule_config.get('status_rules'), dict) else {}
    critical_rules = status_rules.get('critical') if isinstance(status_rules.get('critical'), dict) else {}
    warning_rules = status_rules.get('warning') if isinstance(status_rules.get('warning'), dict) else {}
    success_rate = snapshot.get('checkout_success_rate')
    conflict_rate = snapshot.get('checkout_conflict_rate') or 0
    rate_5xx = snapshot.get('checkout_5xx_rate') or 0
    p95_ms = snapshot.get('checkout_p95_ms')
    critical_score = _safe_float(critical_rules.get('health_score_lt'))
    critical_success = _safe_float(critical_rules.get('success_rate_lt'))
    critical_5xx = _safe_float(critical_rules.get('checkout_5xx_rate_gte'))
    warning_score = _safe_float(warning_rules.get('health_score_lt'))
    warning_success = _safe_float(warning_rules.get('success_rate_lt'))
    warning_conflict = _safe_float(warning_rules.get('checkout_conflict_rate_gte'))
    warning_p95 = _safe_float(warning_rules.get('checkout_p95_ms_gt'))
    if (
        (critical_score is not None and health_score < critical_score)
        or (critical_success is not None and success_rate is not None and success_rate < critical_success)
        or (critical_5xx is not None and rate_5xx >= critical_5xx)
    ):
        return 'critical'
    if (
        (warning_score is not None and health_score < warning_score)
        or (warning_success is not None and success_rate is not None and success_rate < warning_success)
        or (warning_conflict is not None and conflict_rate >= warning_conflict)
        or (warning_p95 is not None and p95_ms is not None and p95_ms > warning_p95)
    ):
        return 'warning'
    return 'healthy'


def _build_ecommerce_interface_metrics(snapshot, rule_config, service_id, path, target_ms):
    key = (service_id, path)
    success = snapshot.get('path_success_rate', {}).get(key)
    if service_id == 'api-gateway' and path == '/api/checkout':
        success = snapshot.get('checkout_success_rate')
    elif service_id in {'order'}:
        success = snapshot.get('path_2xx_rate', {}).get(key, success)
    north_star = rule_config.get('north_star') if isinstance(rule_config.get('north_star'), dict) else {}
    success_target = _safe_float(north_star.get('target')) or 99
    rps_target = _safe_float(_ecommerce_scalar_rule(rule_config, 'checkout_rps').get('target')) or 0.01
    metrics = [
        _metric('成功率', success, success_target, '%', 'higher'),
        _metric('P95', snapshot.get('path_p95_ms', {}).get(key), target_ms, 'ms', 'lower', digits=0),
        _metric('RPS', snapshot.get('path_rps', {}).get(key), rps_target, '', 'higher', digits=3),
    ]
    if service_id == 'api-gateway' and path == '/api/checkout':
        metrics.append(_ecommerce_conflict_metric(snapshot, rule_config))
    if service_id == 'inventory' and path == '/availability':
        metrics.append(_ecommerce_conflict_metric(snapshot, rule_config, label='库存冲突率'))
    return metrics


def _build_ecommerce_live_service_specs(snapshot, rule_config):
    services = []
    conflict_status, conflict_hint, conflict_rule = _ecommerce_inventory_conflict_status(snapshot, rule_config)
    drilldown = rule_config.get('drilldown') if isinstance(rule_config.get('drilldown'), dict) else {}
    configured_services = drilldown.get('services') if isinstance(drilldown.get('services'), list) else ECOMMERCE_SERVICE_SPECS
    north_star = rule_config.get('north_star') if isinstance(rule_config.get('north_star'), dict) else {}
    success_target = _safe_float(north_star.get('target')) or 99
    rps_target = _safe_float(_ecommerce_scalar_rule(rule_config, 'checkout_rps').get('target')) or 0.01
    for item in configured_services:
        if not isinstance(item, dict):
            continue
        service_id = item.get('id')
        if not service_id:
            continue
        availability, available, desired = _deployment_availability(snapshot, service_id)
        success = snapshot.get('service_success_rate', {}).get(service_id)
        if service_id == 'api-gateway':
            success = snapshot.get('checkout_success_rate') or success
        metrics = [
            _metric('成功率', success, success_target, '%', 'higher'),
            _metric('P95', snapshot.get('service_p95_ms', {}).get(service_id), item.get('target_ms') or 500, 'ms', 'lower', digits=0),
            _metric('RPS', snapshot.get('service_rps', {}).get(service_id), rps_target, '', 'higher', digits=3),
            _metric('副本可用率', availability, 100, '%', 'higher'),
        ]
        if service_id == conflict_rule.get('target_service_id') and conflict_status:
            metrics.append(_ecommerce_conflict_metric(snapshot, rule_config, label=conflict_rule.get('metric_label') or '库存冲突率'))
        if available is not None and desired is not None:
            metrics.append(_metric('可用副本', available, desired, '个', 'higher', digits=0))

        interfaces = []
        for path in item.get('paths') or []:
            if not isinstance(path, dict):
                continue
            path_metrics = _build_ecommerce_interface_metrics(snapshot, rule_config, service_id, path.get('path'), path.get('target_ms') or item.get('target_ms') or 500)
            interface_hint = path.get('hint') or ''
            interface_status = _metric_status_rank(path_metrics)
            if (
                service_id == conflict_rule.get('target_service_id')
                and path.get('id') == conflict_rule.get('target_interface_id')
                and conflict_status
            ):
                interface_hint = conflict_hint
                if _status_rank(conflict_status) > _status_rank(interface_status):
                    interface_status = conflict_status
            interfaces.append({
                'id': path.get('id') or f'{service_id}-{_system_posture_slug(path.get("path"), "path")}',
                'name': path.get('name') or path.get('path') or '接口',
                'base_status': interface_status,
                'hint': interface_hint,
                'metrics': path_metrics,
            })
        service_status = _availability_status(availability)
        metric_status = _metric_status_rank(metrics)
        if _status_rank(metric_status) > _status_rank(service_status):
            service_status = metric_status
        if service_id == conflict_rule.get('target_service_id') and conflict_status and _status_rank(conflict_status) > _status_rank(service_status):
            service_status = conflict_status
        services.append({
            'id': service_id,
            'name': item.get('name') or service_id,
            'role': item.get('role') or '',
            'base_status': service_status,
            'metrics': metrics,
            'hint': conflict_hint if service_id == conflict_rule.get('target_service_id') and conflict_status else item.get('role') or '',
            'interfaces': interfaces,
        })
    return services


def _build_ecommerce_live_dependencies(snapshot, rule_config):
    dependencies = []
    drilldown = rule_config.get('drilldown') if isinstance(rule_config.get('drilldown'), dict) else {}
    configured_dependencies = drilldown.get('dependencies') if isinstance(drilldown.get('dependencies'), list) else ECOMMERCE_DEPENDENCIES
    for item in configured_dependencies:
        if not isinstance(item, dict):
            continue
        dependency_id = item.get('id')
        if not dependency_id:
            continue
        availability, available, desired = _deployment_availability(snapshot, dependency_id)
        metrics = [_metric('副本可用率', availability, 100, '%', 'higher')]
        if available is not None and desired is not None:
            metrics.append(_metric('可用副本', available, desired, '个', 'higher', digits=0))
        dependencies.append({
            **item,
            'base_status': _availability_status(availability),
            'metrics': metrics,
        })
    return dependencies


def _build_ecommerce_overview_metrics(snapshot, rule_config):
    metric_keys = rule_config.get('overview_metrics') if isinstance(rule_config.get('overview_metrics'), list) else []
    metrics = []
    for metric_key in metric_keys or ['checkout_conflict_rate', 'checkout_5xx_rate', 'checkout_p95_ms', 'checkout_rps']:
        metric_key = str(metric_key or '').strip()
        if not metric_key:
            continue
        if metric_key == 'checkout_conflict_rate':
            metrics.append(_ecommerce_conflict_metric(snapshot, rule_config))
            continue
        digits = 0 if metric_key.endswith('_ms') else 3 if metric_key.endswith('_rps') else 1
        metrics.append(_ecommerce_configured_metric(rule_config, snapshot, metric_key, digits=digits))
    return metrics


def _load_ecommerce_recent_tempo_traces(access, rule_config):
    if not access.get('trace'):
        return [], {}
    datasource = TracingDataSource.objects.filter(provider='tempo', is_enabled=True).order_by('-is_default', 'name').first()
    if not datasource:
        return [], {}
    tempo_config = rule_config.get('tempo') if isinstance(rule_config.get('tempo'), dict) else {}
    service_id = str(tempo_config.get('service_id') or 'api-gateway').strip() or 'api-gateway'
    keyword = str(tempo_config.get('keyword') or 'POST /api/checkout').strip() or 'POST /api/checkout'
    duration_minutes = _config_int(tempo_config.get('duration_minutes'), 30)
    limit = _config_int(tempo_config.get('limit'), 8)
    try:
        result = search_tracing({
            'provider': 'tempo',
            'datasource_id': datasource.id,
            'service_id': service_id,
            'duration_minutes': duration_minutes,
            'limit': limit,
        })
    except Exception:
        return [], {}
    traces = result.get('traces') or []
    context = {
        'provider': 'tempo',
        'datasource_id': datasource.id,
        'service_id': service_id,
        'service': service_id,
        'keyword': keyword,
    }
    if traces:
        context['traceId'] = traces[0].get('trace_id') or ''
        context['trace_id'] = traces[0].get('trace_id') or ''
    return traces, context


def _apply_ecommerce_live_template(template, access):
    if not _is_ecommerce_system_posture_template(template):
        return template
    rule_config = _system_posture_rule_config(template)
    if not rule_config.get('enabled', True):
        return {**template, 'rule_config': rule_config}
    client = _resolve_prometheus_client()
    if not client.get('ready'):
        return {**template, 'rule_config': rule_config}
    try:
        snapshot = _ecommerce_prometheus_snapshot(client, rule_config)
    except Exception:
        return {**template, 'rule_config': rule_config}
    if not snapshot.get('ready'):
        return {**template, 'rule_config': rule_config}

    health_score = _ecommerce_health_score(snapshot, rule_config)
    status_value = _ecommerce_status(snapshot, health_score, rule_config)
    north_star_config = rule_config.get('north_star') if isinstance(rule_config.get('north_star'), dict) else {}
    north_metric_key = north_star_config.get('metric') or 'checkout_success_rate'
    north_metric_rule = _ecommerce_scalar_rule(rule_config, north_metric_key)
    north_value = snapshot.get(north_metric_key)
    success_rate = snapshot.get('checkout_success_rate')
    conflict_rate = snapshot.get('checkout_conflict_rate')
    p95_ms = snapshot.get('checkout_p95_ms')
    rps = snapshot.get('checkout_rps')
    conflict_status, conflict_hint, conflict_rule = _ecommerce_inventory_conflict_status(snapshot, rule_config)
    recent_traces, trace_context = _load_ecommerce_recent_tempo_traces(access, rule_config)
    source_text = 'Grafana 代理 Prometheus' if snapshot.get('source') == 'grafana' else 'Prometheus'
    summary_parts = [
        f'过去 {snapshot.get("window") or ECOMMERCE_PROMQL_WINDOW} {north_star_config.get("label") or north_metric_rule.get("label") or "北极星指标"} {_round_system_posture_value(north_value)}{north_star_config.get("unit") or north_metric_rule.get("unit") or ""}',
        f'Checkout 409 占比 {_round_system_posture_value(conflict_rate)}%' if conflict_rate is not None and conflict_rate >= 1 else '',
        f'网关 P95 {_round_system_posture_value(p95_ms, digits=0)}ms' if p95_ms is not None else '',
        f'Checkout RPS {_round_system_posture_value(rps, digits=3)}' if rps is not None else '',
    ]
    live_summary = '，'.join([part for part in summary_parts if part]) + f'，数据来自 {source_text}。'
    if conflict_hint:
        live_summary = f'{live_summary}{conflict_hint}'
    focus_service_id = 'api-gateway'
    focus_interface_id = 'gateway-checkout'
    focus_keyword = 'POST /api/checkout'
    if conflict_status and conflict_rule:
        focus_service_id = conflict_rule.get('target_service_id') or focus_service_id
        focus_interface_id = conflict_rule.get('target_interface_id') or focus_interface_id
        focus_keyword = conflict_rule.get('label') or focus_keyword
    tempo_config = rule_config.get('tempo') if isinstance(rule_config.get('tempo'), dict) else {}
    focus_keyword = tempo_config.get('keyword') or focus_keyword

    return {
        **template,
        'rule_config': rule_config,
        'base_status': status_value,
        'health_score': health_score,
        'keywords': list(dict.fromkeys([
            *(template.get('keywords') or []),
            'api-gateway',
            'cart',
            'order',
            'inventory',
            'catalog',
            '/api/checkout',
            'ecommerce',
        ])),
        'north_star': {
            'label': north_star_config.get('label') or north_metric_rule.get('label') or '下单成功率',
            'value': _round_system_posture_value(north_value),
            'target': north_star_config.get('target') if north_star_config.get('target') is not None else north_metric_rule.get('target', 99),
            'unit': north_star_config.get('unit') or north_metric_rule.get('unit') or '%',
            'direction': north_star_config.get('direction') or north_metric_rule.get('direction') or 'higher',
        },
        'metrics': _build_ecommerce_overview_metrics(snapshot, rule_config),
        'summary': live_summary or template.get('summary') or '',
        'service_specs': _build_ecommerce_live_service_specs(snapshot, rule_config),
        'dependencies': _build_ecommerce_live_dependencies(snapshot, rule_config),
        'focus_service_id': focus_service_id,
        'focus_interface_id': focus_interface_id,
        'focus_keyword': focus_keyword,
        'playbook': rule_config.get('playbook') if isinstance(rule_config.get('playbook'), list) else template.get('playbook') or [],
        'live': {
            'enabled': True,
            'source': snapshot.get('source'),
            'description': snapshot.get('description'),
            'window': snapshot.get('window'),
            'namespace': snapshot.get('namespace'),
            'rule_version': rule_config.get('version'),
            'north_star_metric': north_metric_key,
            'health_formula': (rule_config.get('health_score') or {}).get('formula') if isinstance(rule_config.get('health_score'), dict) else '',
            'warnings': snapshot.get('warnings')[:3],
        },
        'live_recent_traces': recent_traces,
        'live_trace_context': trace_context,
    }


def _build_system_posture_system_payload(template, access, catalog=None):
    if _is_ecommerce_system_posture_template(template):
        live_template = _apply_ecommerce_live_template(template, access)
        if live_template:
            template = live_template
    rule_config = _system_posture_rule_config(template)
    trace_catalog = catalog or {}
    traces = trace_catalog.get('recent_traces') or []
    keywords = template.get('keywords') or []
    service_specs = template.get('service_specs') or []
    dependency_specs = template.get('dependencies') or []
    matched_alerts = []
    matched_logs = []
    matched_events = []
    matched_traces = []

    if access.get('alerts'):
        for alert in Alert.objects.select_related('host').order_by('-created_at')[:80]:
            record_text = _text_block(alert.title, alert.source, alert.message, getattr(alert.host, 'hostname', ''), getattr(alert.host, 'business_line', ''))
            if _record_matches_keywords(record_text, keywords):
                matched_alerts.append(alert)

    if access.get('log_query') or access.get('log_entry'):
        for entry in LogEntry.objects.select_related('host').order_by('-timestamp')[:80]:
            record_text = _text_block(entry.service, entry.message, getattr(entry.host, 'hostname', ''))
            if _record_matches_keywords(record_text, keywords):
                matched_logs.append(entry)

    if access.get('eventwall'):
        event_queryset = EventRecord.objects.order_by('-occurred_at')[:120]
        for event in event_queryset:
            record_text = _text_block(event.title, event.summary, event.detail, event.resource_name, event.application, event.business_line, event.environment, event.action, event.category, event.metadata, event.changes)
            if _record_matches_keywords(record_text, keywords):
                matched_events.append(event)

    if access.get('trace'):
        for trace in traces:
            record_text = _text_block(trace.get('trace_id'), trace.get('service_name'), trace.get('summary'), trace.get('instance_name'), trace.get('endpoint_names'))
            if _record_matches_keywords(record_text, keywords):
                matched_traces.append(trace)
    if template.get('live_recent_traces') and access.get('trace'):
        matched_traces = list(template.get('live_recent_traces') or [])

    alert_critical = sum(1 for alert in matched_alerts if alert.level == 'critical' and not _has_claimants(alert))
    alert_warning = sum(1 for alert in matched_alerts if alert.level == 'warning' and not _has_claimants(alert))
    log_error = sum(1 for entry in matched_logs if entry.level == 'error')
    log_warning = sum(1 for entry in matched_logs if entry.level == 'warning')
    event_failed = sum(1 for event in matched_events if event.result in {EventRecord.RESULT_FAILED, EventRecord.RESULT_REJECTED})
    trace_error = sum(1 for trace in matched_traces if trace.get('is_error'))

    service_children = []
    system_nodes = []
    topology_nodes = []
    topology_links = []

    base_score = {
        'critical': 62,
        'warning': 76,
        'healthy': 90,
    }.get(template.get('base_status') or 'healthy', 84)
    if template.get('health_score') is not None:
        try:
            base_score = max(0, min(100, int(template.get('health_score'))))
        except (TypeError, ValueError):
            pass
    if (template.get('live') or {}).get('enabled'):
        health_score = base_score
        status = template.get('base_status') or 'healthy'
    else:
        score_penalty = alert_critical * 12 + alert_warning * 6 + log_error * 4 + log_warning * 2 + event_failed * 3 + trace_error * 3
        health_score = max(0, min(100, base_score - score_penalty))
        status_rank = _status_rank(template.get('base_status') or 'healthy')
        if health_score < 50 or alert_critical or trace_error >= 2:
            status = 'critical'
        elif health_score < 78 or alert_warning or log_warning or event_failed:
            status = 'warning'
        else:
            status = template.get('base_status') or 'healthy'
        if status_rank > _status_rank(status):
            status = template.get('base_status') or status
        if alert_critical:
            status = 'critical'

    for service_index, service in enumerate(service_specs):
        service_status = service.get('base_status') or status
        service_metrics = [_normalize_metric(metric) for metric in service.get('metrics') or []]
        service_children_nodes = []
        for interface_index, interface in enumerate(service.get('interfaces') or []):
            interface_metrics = [_normalize_metric(metric) for metric in interface.get('metrics') or []]
            interface_status = interface.get('base_status') or service_status
            if any(metric['status'] == 'critical' for metric in interface_metrics):
                interface_status = 'critical'
            elif any(metric['status'] == 'warning' for metric in interface_metrics):
                interface_status = 'warning' if interface_status != 'critical' else interface_status
            service_children_nodes.append({
                'id': interface['id'],
                'name': interface['name'],
                'kind': 'interface',
                'status': interface_status,
                'tone': _status_tone(interface_status),
                'hint': interface.get('hint') or '',
                'metrics': interface_metrics,
                'children': [],
                'level': 2,
                'order': interface_index + 1,
            })
            topology_nodes.append({
                'id': interface['id'],
                'name': interface['name'],
                'kind': 'interface',
                'category': 'interface',
                'status': interface_status,
            })
            topology_links.append({
                'source': service['id'],
                'target': interface['id'],
                'value': 1,
                'kind': 'drilldown',
            })
        if any(child['status'] == 'critical' for child in service_children_nodes):
            service_status = 'critical'
        elif any(child['status'] == 'warning' for child in service_children_nodes):
            service_status = 'warning' if service_status != 'critical' else service_status
        service_children.append({
            'id': service['id'],
            'name': service['name'],
            'kind': 'service',
            'role': service.get('role') or '',
            'status': service_status,
            'tone': _status_tone(service_status),
            'metrics': service_metrics,
            'hint': service.get('hint') or service.get('role') or '',
            'children': service_children_nodes,
            'level': 1,
            'order': service_index + 1,
        })
        system_nodes.append({
            'id': service['id'],
            'name': service['name'],
            'kind': 'service',
            'role': service.get('role') or '',
            'status': service_status,
        })
        topology_nodes.append({
            'id': service['id'],
            'name': service['name'],
            'kind': 'service',
            'category': 'service',
            'status': service_status,
        })
        topology_links.append({
            'source': template['id'],
            'target': service['id'],
            'value': max(1, len(service_children_nodes)),
            'kind': 'drilldown',
        })

    for dep_index, dep in enumerate(dependency_specs):
        dep_status = dep.get('base_status') or 'healthy'
        dep_metrics = [_normalize_metric(metric) for metric in dep.get('metrics') or []]
        if any(metric['status'] == 'critical' for metric in dep_metrics):
            dep_status = 'critical'
        elif any(metric['status'] == 'warning' for metric in dep_metrics):
            dep_status = 'warning' if dep_status != 'critical' else dep_status
        topology_nodes.append({
            'id': dep['id'],
            'name': dep['name'],
            'kind': 'dependency',
            'category': dep.get('role') or 'dependency',
            'status': dep_status,
        })
        topology_links.append({
            'source': dep['id'] if dep.get('role') == 'upstream' else template['id'],
            'target': template['id'] if dep.get('role') == 'upstream' else dep['id'],
            'value': 1 + dep_index,
            'kind': dep.get('role') or 'dependency',
        })

    recent_alerts = [
        {
            'id': alert.id,
            'title': alert.title,
            'level': alert.level,
            'source': alert.source,
            'message': alert.message,
            'time': alert.created_at.isoformat() if alert.created_at else '',
            'host_name': getattr(alert.host, 'hostname', ''),
        }
        for alert in matched_alerts[:4]
    ]
    recent_logs = [
        {
            'id': entry.id,
            'service': entry.service,
            'level': entry.level,
            'message': entry.message,
            'time': entry.timestamp.isoformat() if entry.timestamp else '',
            'host_name': getattr(entry.host, 'hostname', ''),
        }
        for entry in matched_logs[:4]
    ]
    recent_events = [
        {
            'id': event.id,
            'title': event.title,
            'summary': event.summary,
            'result': event.result,
            'severity': event.severity,
            'time': event.occurred_at.isoformat() if event.occurred_at else '',
            'resource_name': event.resource_name,
            'action': event.action,
        }
        for event in matched_events[:4]
    ]
    recent_traces = [
        {
            'trace_id': trace.get('trace_id'),
            'service_name': trace.get('service_name'),
            'summary': trace.get('summary'),
            'instance_name': trace.get('instance_name'),
            'is_error': bool(trace.get('is_error')),
            'duration_ms': trace.get('duration_ms'),
        }
        for trace in matched_traces[:4]
    ]

    trace_context = {}
    if access.get('trace') and trace_catalog.get('tracing'):
        trace_context = {
            'provider': trace_catalog['tracing'].get('provider') or '',
            'datasource_id': trace_catalog['tracing'].get('datasource_id') or '',
            'service_id': template.get('focus_service_id') or '',
            'service': template.get('focus_service_id') or '',
            'keyword': template.get('focus_keyword') or template['name'],
        }
        if recent_traces:
            trace_context['traceId'] = recent_traces[0]['trace_id'] or ''
            trace_context['trace_id'] = recent_traces[0]['trace_id'] or ''
    if template.get('live_trace_context') and access.get('trace'):
        trace_context = dict(template.get('live_trace_context') or trace_context)
        if matched_traces:
            trace_context['traceId'] = matched_traces[0].get('trace_id') or trace_context.get('traceId') or ''
            trace_context['trace_id'] = trace_context.get('traceId') or trace_context.get('trace_id') or ''

    log_context = {}
    if access.get('log_query'):
        log_context = {
            'service': template.get('focus_service_id') or '',
            'keyword': template.get('focus_keyword') or template['name'],
            'traceId': recent_traces[0]['trace_id'] if recent_traces else '',
        }

    selected_metrics = [
        _normalize_metric(metric)
        for metric in template.get('north_star') and [
            {
                'label': template['north_star']['label'],
                'value': template['north_star']['value'],
                'target': template['north_star']['target'],
                'unit': template['north_star']['unit'],
                'direction': template['north_star']['direction'],
            }
        ] or []
    ]
    selected_metric_labels = {metric.get('label') for metric in selected_metrics}
    for metric in template.get('metrics') or []:
        if not isinstance(metric, dict) or metric.get('label') in selected_metric_labels:
            continue
        selected_metrics.append(_normalize_metric(metric))
        selected_metric_labels.add(metric.get('label'))
    if matched_alerts:
        selected_metrics.append(_normalize_metric({'label': '未认领告警', 'value': sum(1 for alert in matched_alerts if not _has_claimants(alert)), 'target': 0, 'unit': '条', 'direction': 'lower'}))
    if matched_traces:
        selected_metrics.append(_normalize_metric({'label': '错误 Trace', 'value': trace_error, 'target': 0, 'unit': '条', 'direction': 'lower'}))
    if matched_logs:
        selected_metrics.append(_normalize_metric({'label': '错误日志', 'value': log_error, 'target': 0, 'unit': '条', 'direction': 'lower'}))

    topology = {
        'node_count': len(topology_nodes) + 1,
        'call_count': len(topology_links),
        'selected_node_id': template.get('focus_service_id') or template['id'],
        'nodes': [
            {
                'id': template['id'],
                'name': template['name'],
                'kind': 'system',
                'category': 'system',
                'status': status,
            },
            *topology_nodes,
        ],
        'links': topology_links,
    }

    if not recent_alerts and template.get('summary'):
        recent_alerts = [{
            'id': f"{template['id']}-hint",
            'title': template['name'],
            'level': status,
            'source': 'system_posture',
            'message': template['summary'],
            'time': timezone.now().isoformat(),
            'host_name': '',
        }]

    return {
        'id': template['id'],
        'name': template['name'],
        'environment': template.get('environment') or 'prod',
        'domain': template['domain'],
        'owner': template['owner'],
        'tier': template['tier'],
        'status': status,
        'tone': _status_tone(status),
        'health_score': health_score,
        'summary': template['summary'],
        'keywords': template['keywords'],
        'north_star': {**template['north_star'], 'status': _metric_status(template['north_star'])},
        'metrics': selected_metrics,
        'children': service_children,
        'dependencies': [
            {
                'id': dep['id'],
                'name': dep['name'],
                'role': dep.get('role') or 'dependency',
                'kind': dep.get('kind') or '依赖',
                'status': dep.get('base_status') or 'healthy',
                'tone': _status_tone(dep.get('base_status') or 'healthy'),
                'metrics': [_normalize_metric(metric) for metric in dep.get('metrics') or []],
                'impact': dep.get('impact') or '',
            }
            for dep in dependency_specs
        ],
        'playbook': template.get('playbook') or [],
        'rule_config': rule_config,
        'source': template.get('source') or 'builtin',
        'source_id': template.get('source_id') or '',
        'editable': bool(template.get('editable')),
        'builtin_backed': bool(template.get('builtin_backed')),
        'base_status': template.get('base_status') or 'healthy',
        'live': template.get('live') or {},
        'form': {**(template.get('form') or {}), 'rule_config': rule_config},
        'focus': {
            'service_id': template.get('focus_service_id') or '',
            'interface_id': template.get('focus_interface_id') or '',
            'keyword': template.get('focus_keyword') or template['name'],
        },
        'trace_context': trace_context,
        'log_context': log_context,
        'recent_alerts': recent_alerts,
        'recent_logs': recent_logs,
        'recent_events': recent_events,
        'recent_traces': recent_traces,
        'topology': topology,
    }


def _system_posture_data_sources(access, catalog=None, grafana=None, logs=None, alerts=None, system_count=None):
    sources = []
    if access.get('trace') and catalog:
        tracing = catalog.get('tracing') or {}
        if catalog.get('error'):
            sources.append({
                'id': 'trace',
                'name': '链路追踪',
                'status': 'warning',
                'count': catalog.get('summary', {}).get('trace_count', 0),
                'description': catalog.get('error') or 'Trace 查询异常，已回退',
                'path': '/observability/tracing',
            })
        else:
            sources.append({
                'id': 'trace',
                'name': '链路追踪',
                'status': 'healthy' if tracing.get('source') != 'demo' else 'warning',
                'count': catalog.get('summary', {}).get('trace_count', 0),
                'description': tracing.get('provider_name') or tracing.get('source') or 'Trace 观测',
                'path': '/observability/tracing',
            })
    if access.get('log_query') or access.get('log_entry'):
        sources.append({
            'id': 'log',
            'name': '日志中心',
            'status': 'healthy' if logs and logs.get('enabled_count') else 'warning',
            'count': logs.get('datasource_count', 0) if logs else 0,
            'description': '按 trace_id 回放日志与错误现场',
            'path': '/logs/query',
        })
    if access.get('alerts') and alerts:
        sources.append({
            'id': 'alert',
            'name': '告警中心',
            'status': 'critical' if alerts.get('unacknowledged') else 'healthy',
            'count': alerts.get('unacknowledged', 0),
            'description': '未认领与高优先级告警',
            'path': '/alerts',
        })
    if access.get('grafana') and grafana:
        sources.append({
            'id': 'grafana',
            'name': 'Grafana',
            'status': 'healthy' if grafana.get('configured') else 'warning',
            'count': grafana.get('dashboard_count', 0),
            'description': grafana.get('status_text') or '推荐看板',
            'path': '/observability/grafana',
        })
    if access.get('eventwall'):
        sources.append({
            'id': 'eventwall',
            'name': '事件墙',
            'status': 'warning',
            'count': EventRecord.objects.count(),
            'description': '变更、同步与审计事件',
            'path': '/events/wall',
        })
    sources.append({
        'id': 'system-posture',
        'name': '系统态势',
        'status': 'healthy',
        'count': system_count if system_count is not None else len(FIREMAP_SYSTEM_TEMPLATES),
        'description': '业务系统健康与 SLA 总览入口',
        'path': '/observability/system-posture',
    })
    return sources


def _system_posture_quick_actions(system, access=None):
    access = access or {}
    actions = []
    trace_context = system.get('trace_context') or {}
    log_context = system.get('log_context') or {}
    if trace_context and access.get('trace'):
        actions.append({
            'key': 'trace',
            'title': '打开链路',
            'path': '/observability/tracing',
            'query': {
                key: value
                for key, value in {
                    'provider': trace_context.get('provider') or '',
                    'datasourceId': trace_context.get('datasource_id') or '',
                    'service': trace_context.get('service') or '',
                    'keyword': trace_context.get('keyword') or '',
                    'traceId': trace_context.get('traceId') or '',
                }.items()
                if value
            },
        })
    if log_context and access.get('log_query'):
        actions.append({
            'key': 'log',
            'title': '打开日志',
            'path': '/logs/query',
            'query': {
                key: value
                for key, value in {
                    'traceId': log_context.get('traceId') or '',
                    'service': log_context.get('service') or '',
                    'keyword': log_context.get('keyword') or '',
                    'title': system.get('name') or '',
                }.items()
                if value
            },
        })
    if access.get('alerts'):
        actions.append({'key': 'alert', 'title': '查看告警', 'path': '/alerts', 'query': {}})
    if access.get('eventwall'):
        actions.append({'key': 'events', 'title': '查看事件', 'path': '/events/wall', 'query': {}})
    if access.get('grafana'):
        actions.append({'key': 'grafana', 'title': '查看看板', 'path': '/observability/grafana', 'query': {}})
    return actions


def _system_posture_summary(systems, access, catalog=None, grafana=None, logs=None, alerts=None):
    alert_total = sum(len(system.get('recent_alerts') or []) for system in systems)
    critical_count = sum(1 for system in systems if system['status'] == 'critical')
    warning_count = sum(1 for system in systems if system['status'] == 'warning')
    healthy_count = sum(1 for system in systems if system['status'] == 'healthy')
    trace_count = catalog.get('summary', {}).get('trace_count', 0) if catalog else 0
    return {
        'system_count': len(systems),
        'critical_systems': critical_count,
        'warning_systems': warning_count,
        'healthy_systems': healthy_count,
        'impacting_systems': critical_count + warning_count,
        'alert_count': alerts.get('unacknowledged', 0) if alerts else alert_total,
        'trace_count': trace_count,
        'datasource_count': logs.get('datasource_count', 0) if logs else 0,
        'dashboard_count': grafana.get('dashboard_count', 0) if grafana else 0,
        'event_count': EventRecord.objects.count() if access.get('eventwall') else 0,
    }


def _system_posture_timeline(template):
    keywords = template.get('keywords') or []
    items = []

    for deployment in Deployment.objects.order_by('-deployed_at')[:40]:
        record_text = _text_block(
            deployment.app_name,
            deployment.business_line,
            deployment.version,
            deployment.description,
            deployment.change_summary,
            deployment.release_name,
            deployment.namespace,
            deployment.deploy_log,
        )
        if not _record_matches_keywords(record_text, keywords):
            continue
        status = deployment.approval_status if deployment.approval_status in {'pending', 'approved', 'rejected'} else deployment.status
        items.append({
            'id': f'deployment-{deployment.id}',
            'kind': 'deployment',
            'title': f'{deployment.app_name} {deployment.version}',
            'summary': deployment.change_summary or deployment.description or deployment.release_name or deployment.deploy_mode,
            'time': deployment.deployed_at.isoformat() if deployment.deployed_at else '',
            'path': '/workorders/releases',
            'status': status,
            'tone': 'danger' if deployment.status in {'failed', 'removed'} or deployment.approval_status == 'rejected' else 'warning' if deployment.status in {'pending', 'deploying'} or deployment.approval_status == 'pending' else 'success',
            'meta': f'{deployment.business_line or "未设置业务线"} / {deployment.environment or "test"}',
        })

    if template.get('focus_service_id'):
        for event in EventRecord.objects.order_by('-occurred_at')[:80]:
            record_text = _text_block(
                event.title,
                event.summary,
                event.detail,
                event.resource_name,
                event.application,
                event.business_line,
                event.environment,
                event.action,
                event.category,
                event.metadata,
                event.changes,
            )
            if not _record_matches_keywords(record_text, keywords):
                continue
            items.append({
                'id': f'event-{event.id}',
                'kind': 'event',
                'title': event.title,
                'summary': event.summary or event.detail or event.resource_name or event.application,
                'time': event.occurred_at.isoformat() if event.occurred_at else '',
                'path': '/events/wall',
                'status': event.result,
                'tone': 'danger' if event.result in {EventRecord.RESULT_FAILED, EventRecord.RESULT_REJECTED} else 'warning' if event.result in {EventRecord.RESULT_PENDING, EventRecord.RESULT_PARTIAL} else 'info',
                'meta': event.category or event.action or '事件墙',
            })

    items.sort(key=lambda item: item.get('time') or '', reverse=True)
    return items[:8]


class SystemPostureEnvironmentViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = SystemPostureEnvironment.objects.all()
    serializer_class = SystemPostureEnvironmentSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'system_posture_environment'
    event_resource_label = '系统态势环境'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.observability.system_posture.view'],
        'retrieve': ['ops.observability.system_posture.view'],
        'create': ['ops.observability.system_posture.manage'],
        'update': ['ops.observability.system_posture.manage'],
        'partial_update': ['ops.observability.system_posture.manage'],
        'destroy': ['ops.observability.system_posture.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        is_enabled = self.request.query_params.get('is_enabled')
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset.order_by('sort_order', 'id')

    def perform_create(self, serializer):
        username = getattr(self.request.user, 'username', '') or 'system'
        serializer.save(created_by=username, updated_by=username)

    def perform_update(self, serializer):
        username = getattr(self.request.user, 'username', '') or 'system'
        serializer.save(updated_by=username)


class SystemPostureSystemViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = SystemPostureSystem.objects.all()
    serializer_class = SystemPostureSystemSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'system_posture_system'
    event_resource_label = '系统态势卡片'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.observability.system_posture.view'],
        'retrieve': ['ops.observability.system_posture.view'],
        'create': ['ops.observability.system_posture.manage'],
        'update': ['ops.observability.system_posture.manage'],
        'partial_update': ['ops.observability.system_posture.manage'],
        'destroy': ['ops.observability.system_posture.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        is_enabled = self.request.query_params.get('is_enabled')
        keyword = str(self.request.query_params.get('keyword') or '').strip()
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        return queryset.order_by('sort_order', 'name', '-id')

    def perform_create(self, serializer):
        username = getattr(self.request.user, 'username', '') or 'system'
        serializer.save(created_by=username, updated_by=username)

    def perform_update(self, serializer):
        username = getattr(self.request.user, 'username', '') or 'system'
        serializer.save(updated_by=username)


SystemPostureSystemViewSet = SystemPostureSystemViewSet


class ObservabilityDataSourceLinkViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').all()
    serializer_class = ObservabilityDataSourceLinkSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'observability_datasource_link'
    event_resource_label = '可观测数据源关联'
    event_resource_name_fields = ('name',)
    demo_account_allowed_actions = {'resolve_trace_to_logs', 'resolve_log_to_trace', 'resolve_trace_to_grafana', 'resolve_log_to_grafana', 'resolve_grafana_to_logs', 'resolve_grafana_to_trace'}
    rbac_permissions = {
        'list': ['ops.observability.link.view'],
        'retrieve': ['ops.observability.link.view'],
        'create': ['ops.observability.link.manage'],
        'update': ['ops.observability.link.manage'],
        'partial_update': ['ops.observability.link.manage'],
        'destroy': ['ops.observability.link.manage'],
        'resolve_trace_to_logs': ['ops.observability.link.view', 'ops.log.query'],
        'resolve_log_to_trace': ['ops.observability.link.view', 'ops.trace.view'],
        'resolve_trace_to_grafana': ['ops.observability.link.view', 'ops.grafana.view'],
        'resolve_log_to_grafana': ['ops.observability.link.view', 'ops.grafana.view'],
        'resolve_grafana_to_logs': ['ops.observability.link.view', 'ops.log.query'],
        'resolve_grafana_to_trace': ['ops.observability.link.view', 'ops.trace.view'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        log_datasource_id = self.request.query_params.get('log_datasource_id')
        tracing_datasource_id = self.request.query_params.get('tracing_datasource_id')
        is_enabled = self.request.query_params.get('is_enabled')
        if log_datasource_id:
            queryset = queryset.filter(log_datasource_id=log_datasource_id)
        if tracing_datasource_id:
            queryset = queryset.filter(tracing_datasource_id=tracing_datasource_id)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset.order_by('-is_default', 'name')

    @action(detail=False, methods=['post'])
    def resolve_trace_to_logs(self, request):
        trace_id = str(request.data.get('trace_id') or '').strip()
        if not trace_id:
            return Response({'detail': '缺少 trace_id'}, status=status.HTTP_400_BAD_REQUEST)
        link = _resolve_observability_link(
            tracing_datasource_id=request.data.get('tracing_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.trace_to_log_enabled:
            return Response({'detail': '未找到可用的链路到日志数据源关联'}, status=status.HTTP_404_NOT_FOUND)
        tags = request.data.get('tags') if isinstance(request.data.get('tags'), dict) else {}
        query = _render_log_query(link, trace_id, tags=tags)
        return Response({
            'link': _link_payload(link),
            'trace_id': trace_id,
            'log_datasource': {
                'id': link.log_datasource_id,
                'name': link.log_datasource.name,
                'provider': link.log_datasource.provider,
            },
            'query': query,
            'source': link.log_datasource.name,
            'window_minutes': link.window_minutes,
            'span_start_shift': link.span_start_shift,
            'span_end_shift': link.span_end_shift,
        })

    @action(detail=False, methods=['post'])
    def resolve_log_to_trace(self, request):
        link = _resolve_observability_link(
            log_datasource_id=request.data.get('log_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.log_to_trace_enabled:
            return Response({'detail': '未找到可用的日志到链路数据源关联'}, status=status.HTTP_404_NOT_FOUND)

        attributes = request.data.get('attributes') if isinstance(request.data.get('attributes'), dict) else {}
        message = request.data.get('message') or ''
        trace_id = (
            str(request.data.get('trace_id') or '').strip()
            or _trace_id_from_mapping(attributes, fields=link.trace_id_fields, message=message, regex=link.trace_id_regex)
        )
        if not trace_id:
            return Response({'detail': '未能从日志内容中解析 Trace ID'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'link': _link_payload(link),
            'trace_id': trace_id,
            'tracing_datasource': {
                'id': link.tracing_datasource_id,
                'name': link.tracing_datasource.name,
                'provider': link.tracing_datasource.provider,
            },
        })

    @action(detail=False, methods=['post'])
    def resolve_trace_to_grafana(self, request):
        trace_id = str(request.data.get('trace_id') or '').strip()
        if not trace_id:
            return Response({'detail': '缺少 trace_id'}, status=status.HTTP_400_BAD_REQUEST)
        link = _resolve_observability_link(
            tracing_datasource_id=request.data.get('tracing_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.trace_to_grafana_enabled:
            return Response({'detail': '未找到可用的链路到 Grafana 看板关联'}, status=status.HTTP_404_NOT_FOUND)
        tags = request.data.get('tags') if isinstance(request.data.get('tags'), dict) else {}
        payload = _grafana_resolve_payload(link, trace_id, tags=tags, request_data=request.data)
        if not payload:
            return Response({'detail': '未找到可用的 Grafana 看板配置'}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)

    @action(detail=False, methods=['post'])
    def resolve_log_to_grafana(self, request):
        link = _resolve_observability_link(
            log_datasource_id=request.data.get('log_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.log_to_grafana_enabled:
            return Response({'detail': '未找到可用的日志到 Grafana 看板关联'}, status=status.HTTP_404_NOT_FOUND)

        attributes = request.data.get('attributes') if isinstance(request.data.get('attributes'), dict) else {}
        message = request.data.get('message') or ''
        trace_id = ''
        if not request.data.get('ignore_trace_id'):
            trace_id = (
                str(request.data.get('trace_id') or '').strip()
                or _trace_id_from_mapping(attributes, fields=link.trace_id_fields, message=message, regex=link.trace_id_regex)
            )
        tags = _tags_from_log_attributes(link, attributes)
        if not trace_id and not (tags.get('service.name') or tags.get('service')):
            return Response({'detail': '日志内容缺少可用于看板筛选的 workload/service 标签'}, status=status.HTTP_400_BAD_REQUEST)
        payload = _grafana_resolve_payload(link, trace_id, tags=tags, request_data=request.data)
        if not payload:
            return Response({'detail': '未找到可用的 Grafana 看板配置'}, status=status.HTTP_404_NOT_FOUND)
        payload['query']['source'] = 'log'
        return Response(payload)

    @action(detail=False, methods=['post'])
    def resolve_grafana_to_logs(self, request):
        dashboard_key = request.data.get('dashboard_key') or request.data.get('dashboard') or request.data.get('grafana_dashboard_key') or ''
        link = _resolve_observability_link_for_dashboard(dashboard_key)
        if not link or not link.grafana_to_log_enabled:
            return Response({'detail': '未找到可用的 Grafana 看板到日志关联'}, status=status.HTTP_404_NOT_FOUND)
        context = _dashboard_context_from_request(request.data)
        tags = _tags_from_grafana_context(link, context)
        if not tags:
            return Response({'detail': '看板上下文缺少可用于日志查询的变量'}, status=status.HTTP_400_BAD_REQUEST)
        trace_id = str(context.get('traceId') or context.get('trace_id') or '').strip()
        query = _render_log_query(link, trace_id, tags=tags)
        if not query:
            return Response({'detail': '看板上下文缺少可用于日志查询的变量'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'link': _link_payload(link),
            'dashboard_key': dashboard_key,
            'trace_id': trace_id,
            'tags': tags,
            'log_datasource': {
                'id': link.log_datasource_id,
                'name': link.log_datasource.name,
                'provider': link.log_datasource.provider,
            },
            'query': query,
            'window_minutes': link.window_minutes,
        })

    @action(detail=False, methods=['post'])
    def resolve_grafana_to_trace(self, request):
        dashboard_key = request.data.get('dashboard_key') or request.data.get('dashboard') or request.data.get('grafana_dashboard_key') or ''
        link = _resolve_observability_link_for_dashboard(dashboard_key)
        if not link or not link.grafana_to_trace_enabled:
            return Response({'detail': '未找到可用的 Grafana 看板到链路关联'}, status=status.HTTP_404_NOT_FOUND)
        context = _dashboard_context_from_request(request.data)
        tags = _tags_from_grafana_context(link, context)
        service = tags.get('service.name') or context.get('service') or context.get('var-service') or ''
        trace_id = str(context.get('traceId') or context.get('trace_id') or '').strip()
        return Response({
            'link': _link_payload(link),
            'dashboard_key': dashboard_key,
            'trace_id': trace_id,
            'tags': tags,
            'service': service,
            'tracing_datasource': {
                'id': link.tracing_datasource_id,
                'name': link.tracing_datasource.name,
                'provider': link.tracing_datasource.provider,
            },
            'window_minutes': link.window_minutes,
        })


class TracingDataSourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TracingDataSource.objects.all().order_by('provider', 'name')
    serializer_class = TracingDataSourceSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'tracing_datasource'
    event_resource_label = '链路数据源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.trace.datasource.view'],
        'retrieve': ['ops.trace.datasource.view'],
        'create': ['ops.trace.datasource.manage'],
        'update': ['ops.trace.datasource.manage'],
        'partial_update': ['ops.trace.datasource.manage'],
        'destroy': ['ops.trace.datasource.manage'],
        'test_connection': ['ops.trace.datasource.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        provider = self.request.query_params.get('provider')
        is_enabled = self.request.query_params.get('is_enabled')
        if provider:
            queryset = queryset.filter(provider=provider)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        datasource = self.get_object()
        try:
            preview = test_tracing_connection(datasource.provider, datasource.config or {})
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试成功',
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'preview_kind': preview.get('kind'), 'count': preview.get('count', 0)},
            )
            return Response({
                'success': True,
                'message': f'{datasource.name} 连接成功',
                'preview_count': preview.get('count', 0),
                'preview_kind': preview.get('kind'),
            })
        except ObservabilityError as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response({'success': False, 'message': str(exc), 'detail': exc.detail}, status=exc.status_code)
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response(
                {'success': False, 'message': '连接测试失败', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.trace.datasource.view')])
def tracing_providers(request):
    return Response({'providers': tracing_provider_info()})


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.grafana.view')])
def grafana_setting_view(request):
    instance = _get_grafana_setting()
    if request.method == 'GET':
        config = _grafana_config()
        payload = {
            'id': instance.id if instance else None,
            'name': instance.name if instance else 'default',
            'enabled': bool(config.get('enabled')),
            'url': config.get('url') or '',
            'default_path': config.get('default_path') or '',
            'folders': config.get('folders') or [],
            'dashboards': config.get('dashboards') or DEMO_GRAFANA_DASHBOARDS,
            'updated_by': instance.updated_by if instance else '',
            'created_at': instance.created_at if instance else None,
            'updated_at': instance.updated_at if instance else None,
            'persisted': bool(instance),
        }
        return Response(payload)

    if not user_has_permissions(request.user, ['ops.grafana.manage']):
        return Response({'detail': '缺少 ops.grafana.manage 权限'}, status=status.HTTP_403_FORBIDDEN)

    if instance is None:
        instance = GrafanaSetting(name='default')
    serializer = GrafanaSettingSerializer(instance=instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    saved = serializer.save(updated_by=request.user.username)
    record_event(
        request=request,
        module='ops',
        category='configuration',
        action='update_grafana_setting',
        title='更新 Grafana 配置',
        summary='已更新监控看板接入配置',
        resource_type='grafana_setting',
        resource_id=saved.id,
        resource_name=saved.name,
        correlation_id=f'grafana-setting:{saved.id}',
        metadata={'url': saved.url, 'enabled': saved.enabled, 'default_path': saved.default_path},
    )
    response_data = GrafanaSettingSerializer(saved).data
    response_data['persisted'] = True
    return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.observability.system_posture.view')])
def observability_system_posture(request):
    access = _observability_access(request)
    provider = request.query_params.get('provider', '')
    layer = request.query_params.get('layer', '')
    selected_key = str(request.query_params.get('system') or request.query_params.get('focus') or '').strip()

    catalog = None
    if access.get('trace'):
        try:
            catalog = load_tracing_catalog(
                provider=provider,
                layer=layer,
                datasource_id=request.query_params.get('datasource_id', ''),
            )
        except ObservabilityError as exc:
            catalog = {'error': str(exc), 'detail': exc.detail}

    grafana = _grafana_meta() if access.get('grafana') else None
    logs = _log_module_summary() if (access.get('log_query') or access.get('log_datasource') or access.get('log_entry')) else None
    alerts = _alert_module_summary() if access.get('alerts') else None

    templates = _system_posture_templates()
    systems = [_build_system_posture_system_payload(template, access, catalog if isinstance(catalog, dict) else None) for template in templates]
    selected_system = None
    if selected_key:
        selected_system = next(
            (
                item
                for item in systems
                if selected_key in {item['id'], item['name']} or selected_key.lower() in item['name'].lower()
            ),
            None,
        )
    if not selected_system:
        selected_system = next((item for item in systems if item['status'] == 'critical'), None) or next((item for item in systems if item['status'] == 'warning'), None) or systems[0]

    selected_template = next((item for item in templates if item['id'] == selected_system['id']), templates[0])
    selected_system['actions'] = _system_posture_quick_actions(selected_system, access)
    selected_system['timeline'] = _system_posture_timeline(selected_template)
    selected_system['signals'] = {
        'alerts': len(selected_system.get('recent_alerts') or []),
        'logs': len(selected_system.get('recent_logs') or []),
        'events': len(selected_system.get('recent_events') or []),
        'traces': len(selected_system.get('recent_traces') or []),
    }

    summary = _system_posture_summary(systems, access, catalog if isinstance(catalog, dict) else None, grafana=grafana, logs=logs, alerts=alerts)
    summary['impact_nodes'] = sum(len(system.get('dependencies') or []) for system in systems if system['status'] != 'healthy')

    navigation = []
    if access.get('system_posture'):
        navigation.append({'title': '系统态势', 'path': '/observability/system-posture', 'description': '查看业务系统健康、SLA 指标与依赖影响。', 'tone': 'danger'})
    if access.get('trace'):
        navigation.append({'title': '链路追踪', 'path': '/observability/tracing', 'description': '查看 Trace、Span 和调用拓扑。', 'tone': 'success'})
    if access.get('log_query') or access.get('log_datasource'):
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': '按关键字和 Trace ID 回放日志。', 'tone': 'info'})
    if access.get('alerts'):
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '查看未认领告警与高风险动态。', 'tone': 'warning'})
    if access.get('grafana'):
        navigation.append({'title': '监控看板', 'path': '/observability/grafana', 'description': '打开 Grafana 推荐看板。', 'tone': 'accent'})
    if access.get('eventwall'):
        navigation.append({'title': '事件墙', 'path': '/events/wall', 'description': '查看变更、同步和审计事件。', 'tone': 'success'})

    selected_changes = selected_system.get('timeline') or []
    return Response({
        'summary': summary,
        'systems': systems,
        'environments': _system_posture_environments(templates),
        'selected_system_id': selected_system['id'],
        'selected_system': selected_system,
        'topology': selected_system.get('topology') or {'node_count': 0, 'call_count': 0, 'selected_node_id': '', 'nodes': [], 'links': []},
        'data_sources': _system_posture_data_sources(access, catalog if isinstance(catalog, dict) else None, grafana=grafana, logs=logs, alerts=alerts, system_count=len(systems)),
        'navigation': navigation,
        'timeline': selected_changes,
        'quick_actions': selected_system.get('actions') or [],
        'tips': [
            '先看顶部高风险系统，再沿着中间的依赖图下钻到服务和接口。',
            '从告警、日志、链路和事件四种证据同时对齐故障时间线，减少误判。',
            '系统态势负责汇总业务健康、依赖影响和证据入口，真正处理仍然回到原始观测数据。',
        ],
        'context': {
            'provider': provider,
            'layer': layer,
            'datasource_id': request.query_params.get('datasource_id', ''),
            'can_manage': access.get('system_posture_manage'),
        },
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_overview(request):
    access = _observability_access(request)
    denied = _deny_if_missing_any(
        request,
        ['ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view', 'ops.grafana.view'],
    )
    if denied:
        return denied

    provider = request.query_params.get('provider', '')
    layer = request.query_params.get('layer', '')
    try:
        catalog = load_tracing_catalog(
            provider=provider,
            layer=layer,
            datasource_id=request.query_params.get('datasource_id', ''),
        ) if access['trace'] else None
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
    grafana = _grafana_meta() if access['grafana'] else None
    logs = _log_module_summary() if (access['log_query'] or access['log_datasource']) else None
    alerts = _alert_module_summary() if access['alerts'] else None

    navigation = []
    if access['log_query'] or access['log_datasource']:
        log_description = '统一进入日志查询与数据源管理。' if access['log_query'] and access['log_datasource'] else '进入日志中心并按当前权限查看可用标签。'
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': log_description, 'tone': 'info'})
    if access['alerts']:
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '集中处理当前未认领和高优先级告警。', 'tone': 'danger'})
    if access['trace']:
        navigation.append({'title': '链路追踪', 'path': '/observability/tracing', 'description': '统一查看 SkyWalking 与 OpenTelemetry Trace、Span 和调用拓扑。', 'tone': 'success'})
    if access['trace_datasource']:
        navigation.append({'title': '链路数据源', 'path': '/observability/tracing/datasources', 'description': '维护 SkyWalking、Tempo、Jaeger、Zipkin 查询入口与默认数据源。', 'tone': 'warning'})
    if access['grafana']:
        navigation.append({'title': 'Grafana 大屏', 'path': '/observability/grafana', 'description': '打开监控看板和推荐大屏。', 'tone': 'accent'})

    return Response({
        'modules': {
            'tracing': catalog['tracing'] if catalog else None,
            'grafana': grafana,
            'logs': logs,
            'alerts': alerts,
        },
        'summary': {
            'service_count': catalog['summary']['service_count'] if catalog else 0,
            'trace_count': catalog['summary']['trace_count'] if catalog else 0,
            'error_count': catalog['summary']['error_count'] if catalog else 0,
            'topology_nodes': catalog['summary']['topology_nodes'] if catalog else 0,
            'dashboard_count': grafana['dashboard_count'] if grafana else 0,
            'datasource_count': logs['datasource_count'] if logs else 0,
            'unacknowledged_alerts': alerts['unacknowledged'] if alerts else 0,
        },
        'navigation': navigation,
        'recent_traces': catalog['recent_traces'] if catalog else [],
        'providers': catalog['providers'] if catalog else [
            {
                'provider': item['id'],
                'provider_name': item['name'],
                'source': 'demo' if not item['configured'] else item['id'],
                'configured': item['configured'],
                'active': False,
            }
            for item in (tracing_provider_info() if access['trace_datasource'] else [])
        ],
        'recent_alerts': alerts['recent'] if alerts else [],
        'tips': [
            '链路追踪优先接入 SkyWalking、Tempo、Jaeger 或 Zipkin；未配置时自动展示演示数据。',
            'Tempo、Jaeger、Zipkin 统一按 OpenTelemetry 风格归一化为标准 Trace / Span 模型。',
            '日志中心、告警中心与链路追踪已收敛到可观测性菜单，便于统一排障。',
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_tracing_catalog(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_tracing_catalog(
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
            service_id=request.query_params.get('service_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def observability_tracing_search(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(search_tracing(request.data or {}))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_trace_detail(request, trace_id):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_trace_detail(
            trace_id,
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
