from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from rbac.permissions import RBACPermissionMixin

from .models import EventRecord, EventSource
from .serializers import EventRecordSerializer, EventSourceIngestSerializer, EventSourceSerializer
from .services import record_event


DEMO_WINDOW_MINUTES = 7 * 24 * 60 - 1

DEFAULT_EVENT_SOURCES = [
    {
        'code': 'builtin-workorder',
        'name': '工单系统',
        'source_kind': EventSource.KIND_BUILTIN,
        'source_type': EventSource.TYPE_BUILTIN_WORKORDER,
        'description': '沉淀应用发布、SQL 审计、事务工单、审批流等变更事件。',
        'enabled': True,
        'status': EventSource.STATUS_HEALTHY,
        'auth_type': EventSource.AUTH_NONE,
        'field_mapping': {'time': 'occurred_at', 'title': 'title', 'status': 'result', 'operator': 'actor_username'},
        'config': {'resource_types': ['deployment', 'sql_order', 'transaction_ticket', 'deployment_approval_flow']},
    },
    {
        'code': 'builtin-task-center',
        'name': '任务中心',
        'source_kind': EventSource.KIND_BUILTIN,
        'source_type': EventSource.TYPE_BUILTIN_TASK,
        'description': '沉淀主机任务、定时编排、批量执行、重跑和终止等操作事件。',
        'enabled': True,
        'status': EventSource.STATUS_HEALTHY,
        'auth_type': EventSource.AUTH_NONE,
        'field_mapping': {'time': 'occurred_at', 'target': 'resource_name', 'status': 'result'},
        'config': {'resource_types': ['host_task', 'host_task_batch', 'host_task_schedule']},
    },
    {
        'code': 'builtin-k8s',
        'name': 'K8s 事件',
        'source_kind': EventSource.KIND_BUILTIN,
        'source_type': EventSource.TYPE_BUILTIN_K8S,
        'description': '汇总集群资源事件、配置修订、扩缩容、Pod 操作与异常调度线索。',
        'enabled': True,
        'status': EventSource.STATUS_HEALTHY,
        'auth_type': EventSource.AUTH_NONE,
        'field_mapping': {'type': 'severity', 'reason': 'action', 'message': 'summary', 'resource': 'resource_name'},
        'config': {'resource_types': ['k8s_cluster', 'k8s_event', 'k8s_config_revision']},
    },
    {'code': 'jira', 'name': 'Jira', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_JIRA, 'description': '接入 Jira issue 创建、流转、发布关联和故障工单事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'issue.key': 'resource_id', 'issue.fields.summary': 'title', 'user.name': 'actor'}},
    {'code': 'jenkins', 'name': 'Jenkins', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_JENKINS, 'description': '接入 Jenkins 构建开始、成功、失败、回滚和部署流水线事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'job_name': 'application', 'build_number': 'resource_id', 'status': 'result'}},
    {'code': 'argocd', 'name': 'ArgoCD', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_ARGOCD, 'description': '接入 ArgoCD 应用同步、健康状态、回滚和 GitOps 发布事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'app.metadata.name': 'application', 'app.status.health.status': 'severity'}},
    {'code': 'gitlab', 'name': 'GitLab', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_GITLAB, 'description': '接入 GitLab push、merge request、tag、pipeline 和 deployment 事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'project.name': 'application', 'user_username': 'actor', 'object_kind': 'event_type'}},
    {'code': 'custom', 'name': '自定义事件源', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_CUSTOM, 'description': '为内部自研系统提供统一 webhook 规范，写入事件墙后可参与故障分析。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'event_id': 'event_id', 'occurred_at': 'occurred_at', 'title': 'title'}},
]

BUILTIN_RESOURCE_TYPES = {
    EventSource.TYPE_BUILTIN_WORKORDER: ['deployment', 'sql_order', 'transaction_ticket', 'deployment_approval_flow'],
    EventSource.TYPE_BUILTIN_TASK: ['host_task', 'host_task_batch', 'host_task_schedule'],
    EventSource.TYPE_BUILTIN_K8S: ['k8s_cluster', 'k8s_event', 'k8s_config_revision'],
}

INGEST_SPEC = {
    'method': 'POST',
    'auth': 'Authorization: Bearer <token> 或 X-Event-Token: <token>',
    'content_type': 'application/json',
    'endpoint_template': '/api/event-sources/{code}/ingest/',
    'required_fields': ['title'],
    'recommended_fields': ['event_id', 'occurred_at', 'summary', 'event_type', 'action', 'result', 'severity', 'actor', 'business_line', 'environment', 'application', 'resource_type', 'resource_id', 'resource_name', 'correlation_id', 'tags', 'related_resources', 'changes', 'metadata'],
    'result_values': [choice[0] for choice in EventRecord.RESULT_CHOICES],
    'severity_values': [choice[0] for choice in EventRecord.SEVERITY_CHOICES],
    'example': {
        'event_id': 'deploy-20260506-001',
        'occurred_at': '2026-05-06T10:15:00+08:00',
        'title': 'payment-api 发布失败',
        'summary': 'Jenkins 构建 #184 发布到 prod 失败',
        'event_type': 'deployment',
        'action': 'deploy',
        'result': 'failed',
        'severity': 'danger',
        'actor': 'jenkins',
        'business_line': '交易',
        'environment': 'prod',
        'application': 'payment-api',
        'resource_type': 'jenkins_build',
        'resource_id': 'payment-api#184',
        'resource_name': 'payment-api #184',
        'correlation_id': 'payment-api:20260506',
        'tags': ['change', 'ci'],
        'metadata': {'job_url': 'https://jenkins.example/job/payment-api/184/'},
    },
}


def _ensure_default_event_sources():
    for item in DEFAULT_EVENT_SOURCES:
        source, created = EventSource.objects.get_or_create(code=item['code'], defaults={key: value for key, value in item.items() if key != 'code'})
        if created:
            continue
        update_fields = []
        for key in ('name', 'source_kind', 'source_type', 'description', 'auth_type', 'field_mapping', 'config'):
            if key in item and getattr(source, key) != item[key]:
                setattr(source, key, item[key])
                update_fields.append(key)
        if source.source_kind == EventSource.KIND_BUILTIN:
            for key in ('enabled', 'status'):
                if getattr(source, key) != item[key]:
                    setattr(source, key, item[key])
                    update_fields.append(key)
        if update_fields:
            update_fields.append('updated_at')
            source.save(update_fields=update_fields)


def _extract_event_source_token(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    return request.META.get('HTTP_X_EVENT_TOKEN', '').strip()


def _safe_get(payload, path, default=''):
    current = payload
    for part in str(path or '').split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current if current is not None else default


def _normalize_provider_payload(source, payload):
    if source.source_type == EventSource.TYPE_JIRA:
        issue = payload.get('issue') or {}
        fields = issue.get('fields') or {}
        return {'event_id': payload.get('webhookEvent') or issue.get('id') or issue.get('key'), 'title': fields.get('summary') or f"Jira {issue.get('key', '')}".strip(), 'summary': payload.get('webhookEvent') or 'Jira 事件', 'event_type': 'jira_issue', 'action': payload.get('webhookEvent') or 'issue_event', 'result': EventRecord.RESULT_SUCCESS, 'actor': _safe_get(payload, 'user.name') or _safe_get(payload, 'user.displayName'), 'resource_type': 'jira_issue', 'resource_id': issue.get('key') or issue.get('id') or '', 'resource_name': fields.get('summary') or issue.get('key') or '', 'metadata': payload}
    if source.source_type == EventSource.TYPE_GITLAB:
        return {'event_id': payload.get('checkout_sha') or payload.get('object_kind') or payload.get('event_name'), 'title': payload.get('object_kind') or payload.get('event_name') or 'GitLab 事件', 'summary': payload.get('message') or payload.get('ref') or '', 'event_type': payload.get('object_kind') or 'gitlab', 'action': payload.get('event_name') or payload.get('object_kind') or 'gitlab_event', 'result': EventRecord.RESULT_SUCCESS, 'actor': payload.get('user_username') or payload.get('user_name') or '', 'application': _safe_get(payload, 'project.name'), 'resource_type': 'gitlab_project', 'resource_id': _safe_get(payload, 'project.id') or '', 'resource_name': _safe_get(payload, 'project.path_with_namespace') or _safe_get(payload, 'project.name'), 'metadata': payload}
    if source.source_type == EventSource.TYPE_JENKINS:
        status_value = str(payload.get('status') or _safe_get(payload, 'build.status') or '').lower()
        result = EventRecord.RESULT_FAILED if status_value in {'failed', 'failure', 'aborted'} else EventRecord.RESULT_SUCCESS
        job_name = payload.get('job_name') or payload.get('name') or _safe_get(payload, 'build.full_url')
        build_number = payload.get('build_number') or _safe_get(payload, 'build.number')
        return {'event_id': f'{job_name}#{build_number}' if job_name and build_number else '', 'title': f'Jenkins {job_name or "构建事件"}', 'summary': payload.get('message') or status_value or 'Jenkins 构建事件', 'event_type': 'jenkins_build', 'action': payload.get('phase') or 'build', 'result': result, 'severity': EventRecord.SEVERITY_DANGER if result == EventRecord.RESULT_FAILED else EventRecord.SEVERITY_INFO, 'actor': payload.get('user') or 'jenkins', 'application': job_name or '', 'resource_type': 'jenkins_build', 'resource_id': str(build_number or ''), 'resource_name': str(job_name or ''), 'metadata': payload}
    if source.source_type == EventSource.TYPE_ARGOCD:
        app = payload.get('app') or payload.get('application') or {}
        app_name = _safe_get(app, 'metadata.name') or payload.get('app_name') or payload.get('application')
        health = str(_safe_get(app, 'status.health.status') or payload.get('health') or '').lower()
        result = EventRecord.RESULT_FAILED if health in {'degraded', 'missing', 'unknown'} else EventRecord.RESULT_SUCCESS
        return {'event_id': payload.get('event_id') or app_name, 'title': payload.get('title') or f'ArgoCD {app_name or "应用同步"}', 'summary': payload.get('summary') or _safe_get(app, 'status.sync.status') or 'ArgoCD 应用事件', 'event_type': 'argocd_app', 'action': payload.get('action') or 'sync', 'result': result, 'severity': EventRecord.SEVERITY_DANGER if result == EventRecord.RESULT_FAILED else EventRecord.SEVERITY_INFO, 'actor': payload.get('actor') or 'argocd', 'application': app_name or '', 'resource_type': 'argocd_application', 'resource_id': app_name or '', 'resource_name': app_name or '', 'metadata': payload}
    return payload


def _event_source_counts(days=7):
    start = timezone.now() - timedelta(days=days)
    result = defaultdict(int)
    builtin_code_map = {item['source_type']: item['code'] for item in DEFAULT_EVENT_SOURCES if item['source_kind'] == EventSource.KIND_BUILTIN}
    for item in EventRecord.objects.filter(occurred_at__gte=start).values('resource_type', 'metadata'):
        source_code = (item.get('metadata') or {}).get('event_source_code')
        if source_code:
            result[source_code] += 1
            continue
        resource_type = item.get('resource_type') or ''
        for source_type, resource_types in BUILTIN_RESOURCE_TYPES.items():
            if resource_type in resource_types:
                result[builtin_code_map.get(source_type, source_type)] += 1
    return result


def _source_catalog():
    _ensure_default_event_sources()
    catalog = {}
    for source in EventSource.objects.all():
        catalog[source.code] = {
            'code': source.code,
            'name': source.name,
            'source_kind': source.source_kind,
            'source_type': source.source_type,
            'status': source.status,
            'enabled': source.enabled,
        }
    return catalog


def _classify_event_source(event, catalog=None):
    catalog = catalog or _source_catalog()
    metadata = event.metadata or {}
    source_code = metadata.get('event_source_code') or ''
    if source_code and source_code in catalog:
        return catalog[source_code]

    resource_type = event.resource_type or ''
    for item in DEFAULT_EVENT_SOURCES:
        if item['source_kind'] != EventSource.KIND_BUILTIN:
            continue
        resource_types = item.get('config', {}).get('resource_types') or []
        if resource_type in resource_types:
            return catalog.get(item['code']) or {
                'code': item['code'],
                'name': item['name'],
                'source_kind': item['source_kind'],
                'source_type': item['source_type'],
                'status': item.get('status'),
                'enabled': item.get('enabled'),
            }

    fallback_code = f'module-{event.module or "unknown"}'
    return {
        'code': fallback_code,
        'name': event.module or '其他事件',
        'source_kind': 'module',
        'source_type': event.module or 'unknown',
        'status': '',
        'enabled': True,
    }


def _event_suspicion(event, fault_at=None):
    score = 0
    reasons = []
    if event.result == EventRecord.RESULT_FAILED:
        score += 45
        reasons.append('结果失败')
    elif event.result in {EventRecord.RESULT_PARTIAL, EventRecord.RESULT_PENDING}:
        score += 24
        reasons.append('结果未完全成功')
    if event.severity == EventRecord.SEVERITY_DANGER:
        score += 32
        reasons.append('高风险级别')
    elif event.severity == EventRecord.SEVERITY_WARNING:
        score += 14
        reasons.append('需要关注')
    if event.category in {'execution', 'resource_change', 'external_event', 'workflow'}:
        score += 16
        reasons.append('变更或执行类事件')
    if event.action in {'deploy', 'rollback', 'run_schedule', 'create_task', 'rerun_task', 'config_resource_update', 'sync', 'build'}:
        score += 12
        reasons.append('关键操作')
    if event.changes:
        score += 10
        reasons.append('包含变更内容')
    minutes_from_fault = None
    if fault_at:
        minutes_from_fault = round((event.occurred_at - fault_at).total_seconds() / 60, 1)
        abs_minutes = abs(minutes_from_fault)
        if -120 <= minutes_from_fault <= 15:
            score += 22
            reasons.append('靠近故障前窗口')
        elif abs_minutes <= 360:
            score += 8
            reasons.append('处于故障分析窗口')
    return score, reasons, minutes_from_fault


def _refresh_demo_event_timestamps():
    now = timezone.localtime().replace(second=0, microsecond=0)
    changed = []
    for item in EventRecord.objects.filter(is_demo=True).only('id', 'occurred_at', 'metadata'):
        metadata = item.metadata or {}
        offset = metadata.get('demo_offset_minutes')
        if offset is None:
            continue
        try:
            offset_minutes = max(0, min(int(offset), DEMO_WINDOW_MINUTES))
        except (TypeError, ValueError):
            continue
        target = now - timedelta(minutes=offset_minutes)
        if item.occurred_at != target:
            item.occurred_at = target
            changed.append(item)
    if changed:
        EventRecord.objects.bulk_update(changed, ['occurred_at'])


def _parse_time_range(params):
    start_at = params.get('start_at', '').strip()
    end_at = params.get('end_at', '').strip()
    start = parse_datetime(start_at) if start_at else None
    end = parse_datetime(end_at) if end_at else None
    if start and timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    if end and timezone.is_naive(end):
        end = timezone.make_aware(end, timezone.get_current_timezone())
    return start, end


def _build_window(queryset, params, default_days=7):
    start, end = _parse_time_range(params)
    if start:
        queryset = queryset.filter(occurred_at__gte=start)
    if end:
        queryset = queryset.filter(occurred_at__lte=end)
    if start or end:
        return queryset, start, end

    days = params.get('days', '').strip()
    if days.isdigit():
        start = timezone.now() - timedelta(days=int(days))
        return queryset.filter(occurred_at__gte=start), start, None

    if default_days is not None:
        start = timezone.now() - timedelta(days=default_days)
        return queryset.filter(occurred_at__gte=start), start, None

    return queryset, None, None


class EventRecordViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = EventRecord.objects.select_related('parent_event').all()
    serializer_class = EventRecordSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        'title',
        'summary',
        'detail',
        'actor_username',
        'resource_name',
        'resource_type',
        'correlation_id',
    ]
    rbac_permissions = {
        'list': ['eventwall.view'],
        'retrieve': ['eventwall.view'],
        'overview': ['eventwall.view'],
        'associations': ['eventwall.view'],
        'filter_options': ['eventwall.view'],
        'analysis_wall': ['eventwall.view'],
        'operation_audit': ['rbac.audit.view'],
        'prune_operation_audit': ['rbac.audit.manage'],
    }

    def get_queryset(self):
        _refresh_demo_event_timestamps()
        queryset = super().get_queryset().exclude(result=EventRecord.RESULT_REJECTED)
        params = self.request.query_params
        mapping = {
            'module': 'module',
            'category': 'category',
            'action': 'action',
            'result': 'result',
            'actor': 'actor_username',
            'resource_type': 'resource_type',
            'resource_id': 'resource_id',
            'environment': 'environment',
            'business_line': 'business_line',
            'application': 'application',
            'correlation_id': 'correlation_id',
        }
        for key, field in mapping.items():
            value = params.get(key, '').strip()
            if value:
                queryset = queryset.filter(**{field: value})
        event_source_code = params.get('event_source_code', '').strip()
        if event_source_code:
            source_def = next((item for item in DEFAULT_EVENT_SOURCES if item['code'] == event_source_code), None)
            if source_def and source_def['source_kind'] == EventSource.KIND_BUILTIN:
                queryset = queryset.filter(resource_type__in=source_def.get('config', {}).get('resource_types') or [])
            else:
                queryset = queryset.filter(metadata__event_source_code=event_source_code)
        if params.get('is_demo') in {'true', 'false'}:
            queryset = queryset.filter(is_demo=params.get('is_demo') == 'true')
        queryset, _, _ = _build_window(queryset, params, default_days=None)
        return queryset

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        queryset = self.get_queryset()
        return Response({
            'business_lines': list(queryset.exclude(business_line='').values_list('business_line', flat=True).distinct().order_by('business_line')[:50]),
            'environments': list(queryset.exclude(environment='').values_list('environment', flat=True).distinct().order_by('environment')[:50]),
            'applications': list(queryset.exclude(application='').values_list('application', flat=True).distinct().order_by('application')[:100]),
        })

    @action(detail=False, methods=['get'])
    def overview(self, request):
        recent, start, end = _build_window(self.get_queryset(), request.query_params, default_days=7)
        module_counts = list(recent.values('module').annotate(count=Count('id')).order_by('-count'))
        action_counts = list(recent.values('action').annotate(count=Count('id')).order_by('-count')[:8])
        applications = list(
            recent.exclude(application='')
            .values('application')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        business_lines = list(
            recent.exclude(business_line='')
            .values('business_line')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        environments = list(
            recent.exclude(environment='')
            .values('environment')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        scopes = [
            {
                'business_line': item['business_line'],
                'environment': item['environment'],
                'count': item['count'],
                'label': f"{item['business_line']} / {item['environment']}",
            }
            for item in (
                recent.exclude(business_line='')
                .exclude(environment='')
                .values('business_line', 'environment')
                .annotate(count=Count('id'))
                .order_by('-count')[:8]
            )
        ]
        actors = list(
            recent.exclude(actor_username='')
            .values('actor_username')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        recent_items = EventRecordSerializer(recent[:12], many=True).data
        priority_events = EventRecordSerializer(
            recent.filter(category='execution', result__in=[EventRecord.RESULT_FAILED, EventRecord.RESULT_PARTIAL])[:8],
            many=True,
        ).data
        return Response({
            'summary': {
                'total_7d': recent.count(),
                'failed_7d': recent.filter(result=EventRecord.RESULT_FAILED).count(),
                'pending_7d': recent.filter(result=EventRecord.RESULT_PENDING).count(),
                'unique_actors_7d': recent.exclude(actor_username='').values('actor_username').distinct().count(),
                'tracked_resources_7d': recent.exclude(resource_type='').values('resource_type', 'resource_id').distinct().count(),
            },
            'window': {
                'start_at': start,
                'end_at': end,
            },
            'modules': module_counts,
            'actions': action_counts,
            'top_actors': actors,
            'top_applications': applications,
            'top_business_lines': business_lines,
            'top_environments': environments,
            'top_scopes': scopes,
            'recent': recent_items,
            'high_risk': priority_events,
            'priority_events': priority_events,
            'failed_deployments': [],
            'rejected_sql': [],
            'execution_watchlist': priority_events,
            'tips': [
                '事件墙默认只保留最终执行结果和关键写操作，驳回但未执行的审批流不会进入事件墙。',
                '排查问题时优先按业务线、环境、应用缩小范围，再结合操作人和失败结果快速定位。',
            ],
        })

    @action(detail=False, methods=['get'])
    def associations(self, request):
        recent, _, _ = _build_window(self.get_queryset(), request.query_params, default_days=14)
        recent = recent[:400]
        chains = defaultdict(list)
        hot_resources = Counter()
        module_links = Counter()

        for item in recent:
            if item.correlation_id:
                chains[item.correlation_id].append(item)
            resource_key = f'{item.resource_type}:{item.resource_name or item.resource_id}'
            if item.resource_type:
                hot_resources[resource_key] += 1
            related_modules = {entry.get('module') for entry in (item.related_resources or []) if entry.get('module')}
            for related_module in related_modules:
                if related_module != item.module:
                    module_links[f'{item.module}->{related_module}'] += 1

        chain_payload = []
        for correlation_id, items in sorted(chains.items(), key=lambda pair: len(pair[1]), reverse=True)[:8]:
            ordered = sorted(items, key=lambda record: (record.occurred_at, record.id))
            chain_payload.append({
                'correlation_id': correlation_id,
                'count': len(ordered),
                'title': ordered[0].title,
                'modules': list(dict.fromkeys(item.module for item in ordered)),
                'latest_at': ordered[-1].occurred_at,
                'events': EventRecordSerializer(ordered[:6], many=True).data,
            })

        hot_resource_payload = [{'resource': key, 'count': count} for key, count in hot_resources.most_common(10)]
        module_link_payload = [{'link': key, 'count': count} for key, count in module_links.most_common(10)]
        return Response({
            'chains': chain_payload,
            'hot_resources': hot_resource_payload,
            'module_links': module_link_payload,
        })

    @action(detail=False, methods=['get'])
    def operation_audit(self, request):
        queryset = self.filter_queryset(
            self.get_queryset()
            .exclude(source_type=EventRecord.SOURCE_EXTERNAL)
            .exclude(category='external_event')
            .order_by('-occurred_at', '-id')
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(EventRecordSerializer(page, many=True).data)
        return Response(EventRecordSerializer(queryset[:100], many=True).data)

    @action(detail=False, methods=['post'])
    def prune_operation_audit(self, request):
        cutoff_raw = (request.data.get('before_at') or '').strip()
        cutoff = parse_datetime(cutoff_raw) if cutoff_raw else None
        if not cutoff:
            return Response({'detail': '请提供有效的截止时间 before_at。'}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff, timezone.get_current_timezone())

        queryset = (
            self.get_queryset()
            .exclude(source_type=EventRecord.SOURCE_EXTERNAL)
            .exclude(category='external_event')
            .filter(occurred_at__lt=cutoff)
        )
        deleted_count = queryset.count()
        queryset.delete()
        record_event(
            module='rbac',
            category='resource_change',
            action='prune_operation_audit',
            title='批量删除操作审计',
            summary=f'删除 {cutoff.isoformat()} 之前的操作审计记录 {deleted_count} 条',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_WARNING,
            actor_username=getattr(request.user, 'username', '') or '',
            actor_display=getattr(request.user, 'get_full_name', lambda: '')() or getattr(request.user, 'username', '') or '',
            actor_type=EventRecord.ACTOR_USER,
            source_type=EventRecord.SOURCE_HTTP,
            request_method=request.method,
            source_path=request.path,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''),
            resource_module='rbac',
            resource_type='operation_audit',
            resource_id=cutoff.isoformat(),
            resource_name='操作审计',
            metadata={'before_at': cutoff.isoformat(), 'deleted': deleted_count},
        )
        return Response({'deleted': deleted_count, 'before_at': cutoff})

    @action(detail=False, methods=['get'])
    def analysis_wall(self, request):
        params = request.query_params
        queryset = self.get_queryset()
        fault_at = parse_datetime(params.get('fault_at', '').strip()) if params.get('fault_at') else None
        if fault_at and timezone.is_naive(fault_at):
            fault_at = timezone.make_aware(fault_at, timezone.get_current_timezone())

        if fault_at and not (params.get('start_at') or params.get('end_at')):
            try:
                lookback_minutes = min(max(int(params.get('lookback_minutes', 240)), 15), 7 * 24 * 60)
            except (TypeError, ValueError):
                lookback_minutes = 240
            try:
                after_minutes = min(max(int(params.get('after_minutes', 60)), 0), 24 * 60)
            except (TypeError, ValueError):
                after_minutes = 60
            start = fault_at - timedelta(minutes=lookback_minutes)
            end = fault_at + timedelta(minutes=after_minutes)
            queryset = queryset.filter(occurred_at__gte=start, occurred_at__lte=end)
        else:
            queryset, start, end = _build_window(queryset, params, default_days=3)

        try:
            limit = min(max(int(params.get('limit', 160)), 20), 500)
        except (TypeError, ValueError):
            limit = 160

        catalog = _source_catalog()
        ordered_events = list(queryset.order_by('occurred_at', 'id')[:limit])
        serialized = EventRecordSerializer(ordered_events, many=True).data
        lanes = {}
        suspects = []
        events = []

        for event, payload in zip(ordered_events, serialized):
            source = _classify_event_source(event, catalog)
            score, reasons, minutes_from_fault = _event_suspicion(event, fault_at=fault_at)
            payload['event_source'] = source
            payload['minutes_from_fault'] = minutes_from_fault
            payload['suspicion_score'] = score
            payload['suspicion_reasons'] = reasons
            events.append(payload)

            lane = lanes.setdefault(source['code'], {
                'source': source,
                'count': 0,
                'failed': 0,
                'warning': 0,
                'before_fault': 0,
                'after_fault': 0,
                'events': [],
            })
            lane['count'] += 1
            lane['failed'] += 1 if event.result == EventRecord.RESULT_FAILED else 0
            lane['warning'] += 1 if event.severity in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
            if fault_at and event.occurred_at <= fault_at:
                lane['before_fault'] += 1
            elif fault_at:
                lane['after_fault'] += 1
            lane['events'].append(payload)

            if score >= 35:
                suspects.append(payload)

        suspects = sorted(suspects, key=lambda item: (-item['suspicion_score'], abs(item['minutes_from_fault'] or 999999), item['occurred_at']))[:12]
        lane_payload = sorted(lanes.values(), key=lambda item: (-item['failed'], -item['warning'], -item['count'], item['source']['name']))
        source_breakdown = [
            {
                'code': lane['source']['code'],
                'name': lane['source']['name'],
                'source_kind': lane['source']['source_kind'],
                'count': lane['count'],
                'failed': lane['failed'],
                'warning': lane['warning'],
            }
            for lane in lane_payload
        ]
        suspect_ids = {item['id'] for item in suspects}
        impact_map = {}
        correlation_map = {}
        for item in events:
            scope_key = (
                item.get('business_line') or '未标注业务线',
                item.get('environment') or '未标注环境',
                item.get('application') or item.get('resource_name') or '未标注应用',
            )
            impact = impact_map.setdefault(scope_key, {
                'business_line': scope_key[0],
                'environment': scope_key[1],
                'application': scope_key[2],
                'count': 0,
                'failed': 0,
                'warning': 0,
                'suspects': 0,
                'source_codes': set(),
                'source_names': set(),
                'latest_at': '',
            })
            impact['count'] += 1
            impact['failed'] += 1 if item.get('result') == EventRecord.RESULT_FAILED else 0
            impact['warning'] += 1 if item.get('severity') in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
            impact['suspects'] += 1 if item.get('id') in suspect_ids else 0
            impact['source_codes'].add((item.get('event_source') or {}).get('code') or item.get('module') or 'unknown')
            impact['source_names'].add((item.get('event_source') or {}).get('name') or item.get('module') or '其他事件')
            if not impact['latest_at'] or str(item.get('occurred_at') or '') > impact['latest_at']:
                impact['latest_at'] = item.get('occurred_at') or ''

            correlation_id = item.get('correlation_id') or ''
            if correlation_id:
                chain = correlation_map.setdefault(correlation_id, {
                    'correlation_id': correlation_id,
                    'title': item.get('title') or correlation_id,
                    'count': 0,
                    'failed': 0,
                    'warning': 0,
                    'suspects': 0,
                    'source_names': set(),
                    'events': [],
                    'latest_at': '',
                })
                chain['count'] += 1
                chain['failed'] += 1 if item.get('result') == EventRecord.RESULT_FAILED else 0
                chain['warning'] += 1 if item.get('severity') in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
                chain['suspects'] += 1 if item.get('id') in suspect_ids else 0
                chain['source_names'].add((item.get('event_source') or {}).get('name') or item.get('module') or '其他事件')
                chain['events'].append(item)
                if not chain['latest_at'] or str(item.get('occurred_at') or '') > chain['latest_at']:
                    chain['latest_at'] = item.get('occurred_at') or ''

        affected_scopes = []
        for item in impact_map.values():
            source_codes = item.pop('source_codes')
            source_names = item.pop('source_names')
            item['source_count'] = len(source_codes)
            item['source_names'] = sorted(source_names)
            item['risk_score'] = item['failed'] * 30 + item['warning'] * 12 + item['suspects'] * 18 + item['source_count'] * 4
            affected_scopes.append(item)
        affected_scopes = sorted(affected_scopes, key=lambda item: (-item['risk_score'], -item['failed'], -item['count'], item['application']))[:10]

        correlation_chains = []
        for item in correlation_map.values():
            if item['count'] < 2 and not item['failed'] and not item['suspects']:
                continue
            item['source_names'] = sorted(item['source_names'])
            item['events'] = item['events'][:6]
            item['risk_score'] = item['failed'] * 32 + item['warning'] * 12 + item['suspects'] * 20 + item['count']
            correlation_chains.append(item)
        correlation_chains = sorted(correlation_chains, key=lambda item: (-item['risk_score'], -item['count'], item['correlation_id']))[:8]

        recommendations = []
        if suspects:
            first = suspects[0]
            recommendations.append(f"先核查「{first.get('title')}」，它的风险分最高且{'; '.join(first.get('suspicion_reasons') or ['靠近故障窗口'])}。")
        if affected_scopes:
            scope = affected_scopes[0]
            recommendations.append(f"优先收敛到 {scope['business_line']} / {scope['environment']} / {scope['application']}，该范围内有 {scope['failed']} 个失败事件、{scope['suspects']} 个疑似事件。")
        if correlation_chains:
            chain = correlation_chains[0]
            recommendations.append(f"检查关联链路 {chain['correlation_id']}，它串起 {chain['count']} 个事件和 {len(chain['source_names'])} 个来源。")
        if not recommendations:
            recommendations.append('当前窗口未发现明显高风险线索，可扩大时间窗口或按应用、环境继续收敛。')

        return Response({
            'window': {
                'start_at': start,
                'end_at': end,
                'fault_at': fault_at,
            },
            'summary': {
                'total': len(events),
                'failed': sum(1 for item in events if item['result'] == EventRecord.RESULT_FAILED),
                'warning': sum(1 for item in events if item['severity'] in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER}),
                'suspects': len(suspects),
                'source_count': len(lane_payload),
                'scope_count': len(affected_scopes),
                'chain_count': len(correlation_chains),
            },
            'source_breakdown': source_breakdown,
            'affected_scopes': affected_scopes,
            'correlation_chains': correlation_chains,
            'lanes': lane_payload,
            'suspects': suspects,
            'events': events,
            'recommendations': recommendations,
            'tips': [
                '先确定故障时刻，再看故障前 1-4 小时内失败、高风险和变更类事件。',
                '同一应用、环境、业务线内靠近故障时刻的发布、配置、任务和 K8s 异常优先排查。',
            ],
        })


class EventSourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = EventSourceSerializer
    lookup_field = 'code'
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['source_kind', 'source_type', 'enabled', 'status']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['eventwall.source.view'],
        'retrieve': ['eventwall.source.view'],
        'create': ['eventwall.source.manage'],
        'update': ['eventwall.source.manage'],
        'partial_update': ['eventwall.source.manage'],
        'destroy': ['eventwall.source.manage'],
        'summary': ['eventwall.source.view'],
        'ingest_spec': ['eventwall.source.view'],
        'issue_token': ['eventwall.source.manage'],
        'toggle_enabled': ['eventwall.source.manage'],
    }

    def get_queryset(self):
        _ensure_default_event_sources()
        return EventSource.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['recent_event_counts'] = _event_source_counts()
        return context

    @action(detail=False, methods=['get'])
    def summary(self, request):
        queryset = self.get_queryset()
        recent_counts = _event_source_counts()
        total_recent = sum(recent_counts.values())
        external_enabled = queryset.filter(source_kind=EventSource.KIND_EXTERNAL, enabled=True).count()
        warning = queryset.filter(status__in=[EventSource.STATUS_WARNING, EventSource.STATUS_NOT_CONFIGURED]).count()
        latest = EventRecord.objects.filter(source_type=EventRecord.SOURCE_EXTERNAL).order_by('-occurred_at').first()
        return Response({
            'total_sources': queryset.count(),
            'builtin_sources': queryset.filter(source_kind=EventSource.KIND_BUILTIN).count(),
            'external_sources': queryset.filter(source_kind=EventSource.KIND_EXTERNAL).count(),
            'external_enabled': external_enabled,
            'warning_sources': warning,
            'recent_events_7d': total_recent,
            'latest_external_event_at': latest.occurred_at if latest else None,
        })

    @action(detail=False, methods=['get'])
    def ingest_spec(self, request):
        return Response(INGEST_SPEC)

    @action(detail=True, methods=['post'])
    def issue_token(self, request, code=None):
        source = self.get_object()
        if source.source_kind != EventSource.KIND_EXTERNAL:
            return Response({'detail': '平台内置事件源不需要接入令牌。'}, status=status.HTTP_400_BAD_REQUEST)
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.last_error = ''
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'last_error', 'updated_at'])
        return Response({'token': token, 'token_preview': source.token_preview})

    @action(detail=True, methods=['post'])
    def toggle_enabled(self, request, code=None):
        source = self.get_object()
        source.enabled = not source.enabled
        if source.enabled and source.status == EventSource.STATUS_DISABLED:
            source.status = EventSource.STATUS_HEALTHY if source.source_kind == EventSource.KIND_BUILTIN or source.token_hash else EventSource.STATUS_NOT_CONFIGURED
        elif not source.enabled:
            source.status = EventSource.STATUS_DISABLED
        source.save(update_fields=['enabled', 'status', 'updated_at'])
        return Response(self.get_serializer(source).data)


class ExternalEventIngestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, code):
        _ensure_default_event_sources()
        try:
            source = EventSource.objects.get(code=code, source_kind=EventSource.KIND_EXTERNAL)
        except EventSource.DoesNotExist:
            return Response({'detail': '事件源不存在。'}, status=status.HTTP_404_NOT_FOUND)

        if not source.enabled:
            return Response({'detail': '事件源未启用。'}, status=status.HTTP_403_FORBIDDEN)
        if not source.verify_token(_extract_event_source_token(request)):
            source.status = EventSource.STATUS_WARNING
            source.last_error = '接入令牌校验失败'
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response({'detail': '接入令牌无效。'}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data if isinstance(request.data, dict) else {}
        normalized = _normalize_provider_payload(source, payload)
        serializer = EventSourceIngestSerializer(data=normalized)
        if not serializer.is_valid():
            source.status = EventSource.STATUS_WARNING
            source.last_error = '事件载荷不符合接入规范'
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        metadata = dict(data.get('metadata') or {})
        metadata.update({
            'event_source_code': source.code,
            'event_source_name': source.name,
            'event_source_type': source.source_type,
            'external_event_id': data.get('event_id', ''),
        })
        event = record_event(
            module='eventwall',
            category='external_event',
            action=data.get('action') or data.get('event_type') or 'ingest',
            title=data['title'],
            summary=data.get('summary') or data['title'],
            detail=data.get('detail', ''),
            result=data.get('result') or EventRecord.RESULT_SUCCESS,
            severity=data.get('severity') or EventRecord.SEVERITY_INFO,
            actor_username=data.get('actor') or source.code,
            actor_display=data.get('actor') or source.name,
            actor_type=EventRecord.ACTOR_SYSTEM,
            source_type=EventRecord.SOURCE_EXTERNAL,
            source_path=request.path,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''),
            resource_module='eventwall',
            resource_type=data.get('resource_type') or source.source_type,
            resource_id=data.get('resource_id') or data.get('event_id', ''),
            resource_name=data.get('resource_name') or data['title'],
            business_line=data.get('business_line', ''),
            environment=data.get('environment', ''),
            application=data.get('application', ''),
            tags=data.get('tags') or [],
            related_resources=data.get('related_resources') or [],
            changes=data.get('changes') or {},
            metadata=metadata,
            correlation_id=data.get('correlation_id') or f'{source.code}:{data.get("event_id") or timezone.now().strftime("%Y%m%d%H%M%S")}',
            occurred_at=data.get('occurred_at'),
        )
        source.status = EventSource.STATUS_HEALTHY
        source.last_error = ''
        source.last_sync_at = timezone.now()
        source.last_event_at = event.occurred_at if event else timezone.now()
        source.save(update_fields=['status', 'last_error', 'last_sync_at', 'last_event_at', 'updated_at'])
        return Response(EventRecordSerializer(event).data, status=status.HTTP_201_CREATED)

