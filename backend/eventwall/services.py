import json
import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.utils import timezone

from .models import EventRecord

logger = logging.getLogger(__name__)

MASK = '***'
SENSITIVE_KEYWORDS = {
    'password',
    'secret',
    'token',
    'access_key',
    'private_key',
    'cert_content',
    'key_content',
    'ssh_password',
    'kubeconfig',
}

RESOURCE_NAME_FIELDS = (
    'name',
    'title',
    'code',
    'username',
    'hostname',
    'domain',
    'app_name',
    'service_name',
    'group',
)


def _is_sensitive_key(key):
    lowered = str(key or '').lower()
    return any(token in lowered for token in SENSITIVE_KEYWORDS)


def sanitize_value(value, key=''):
    if _is_sensitive_key(key):
        return MASK
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, dict):
        return {str(k): sanitize_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, key) for item in value]
    return value


def summarize_sql(value):
    sql = str(value or '').strip()
    if not sql:
        return ''
    normalized = ' '.join(sql.split())
    return normalized[:160]


def snapshot_instance(instance, exclude_fields=None):
    exclude_fields = set(exclude_fields or [])
    data = {}
    for field in instance._meta.fields:
        if field.name in exclude_fields:
            continue
        raw = getattr(instance, field.name)
        if field.is_relation:
            data[field.name] = getattr(instance, f'{field.name}_id')
            continue
        if field.name == 'sql_content':
            data[field.name] = summarize_sql(raw)
            continue
        data[field.name] = sanitize_value(raw, field.name)
    return data


def diff_snapshots(before, after):
    changes = {}
    keys = sorted(set(before.keys()) | set(after.keys()))
    for key in keys:
        if before.get(key) == after.get(key):
            continue
        changes[key] = {
            'before': before.get(key),
            'after': after.get(key),
        }
    return changes


def infer_resource_name(instance, custom_fields=None):
    for field_name in custom_fields or RESOURCE_NAME_FIELDS:
        value = getattr(instance, field_name, '')
        if value:
            return str(value)
    return str(instance)


def infer_application_name(instance):
    for field_name in ('app_name', 'application', 'database', 'release_name'):
        value = getattr(instance, field_name, '')
        if value:
            return str(value)
    template = getattr(instance, 'template', None)
    if getattr(template, 'name', ''):
        return str(template.name)
    return ''


def build_resource(module, resource_type, resource_id='', resource_name='', **extra):
    payload = {
        'module': module,
        'type': resource_type,
        'id': str(resource_id or ''),
        'name': str(resource_name or ''),
    }
    payload.update({key: value for key, value in extra.items() if value not in (None, '', [], {})})
    return payload


def build_correlation_id(prefix, resource_id='', fallback=''):
    base = str(resource_id or fallback or uuid4().hex[:12])
    return f'{prefix}:{base}'


def build_request_context(request=None):
    if not request:
        return {
            'actor_type': EventRecord.ACTOR_SYSTEM,
            'source_type': EventRecord.SOURCE_SYSTEM,
            'actor_username': 'system',
            'actor_display': 'System',
            'request_method': '',
            'source_path': '',
            'ip_address': '',
        }
    username = getattr(getattr(request, 'user', None), 'username', '') or 'anonymous'
    display_name = username
    if getattr(request.user, 'first_name', '') or getattr(request.user, 'last_name', ''):
        display_name = f'{request.user.first_name}{request.user.last_name}'.strip() or username
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
    source_type = getattr(request, '_eventwall_source_type', EventRecord.SOURCE_HTTP)
    return {
        'actor_type': EventRecord.ACTOR_USER,
        'source_type': source_type,
        'actor_username': username,
        'actor_display': display_name,
        'request_method': getattr(request, 'method', ''),
        'source_path': getattr(request, 'path', ''),
        'ip_address': ip,
    }


def record_event(
    *,
    module,
    category,
    action,
    title,
    summary='',
    detail='',
    result=EventRecord.RESULT_SUCCESS,
    severity=EventRecord.SEVERITY_INFO,
    request=None,
    actor_username='',
    actor_display='',
    actor_type='',
    source_type='',
    request_method='',
    source_path='',
    ip_address='',
    resource_module='',
    resource_type='',
    resource_id='',
    resource_name='',
    business_line='',
    environment='',
    application='',
    tags=None,
    related_resources=None,
    changes=None,
    metadata=None,
    correlation_id='',
    parent_event=None,
    is_demo=False,
    occurred_at=None,
):
    if result == EventRecord.RESULT_REJECTED:
        return None
    try:
        context = build_request_context(request)
        payload = EventRecord.objects.create(
            occurred_at=occurred_at or timezone.now(),
            module=module,
            category=category,
            action=action,
            result=result,
            severity=severity,
            title=title,
            summary=summary or title,
            detail=detail,
            actor_type=actor_type or context['actor_type'],
            actor_username=actor_username or context['actor_username'],
            actor_display=actor_display or context['actor_display'],
            source_type=source_type or context['source_type'],
            request_method=request_method or context['request_method'],
            source_path=source_path or context['source_path'],
            ip_address=ip_address or context['ip_address'],
            correlation_id=correlation_id,
            parent_event=parent_event,
            resource_module=resource_module or module,
            resource_type=resource_type,
            resource_id=str(resource_id or ''),
            resource_name=resource_name,
            business_line=business_line,
            environment=environment,
            application=application,
            tags=sanitize_value(tags or [], 'tags'),
            related_resources=sanitize_value(related_resources or [], 'related_resources'),
            changes=sanitize_value(changes or {}, 'changes'),
            metadata=sanitize_value(metadata or {}, 'metadata'),
            is_demo=is_demo,
        )
        return payload
    except Exception:
        logger.exception('record_event failed: %s %s', module, title)
        return None


def record_model_event(
    *,
    request,
    module,
    resource_type,
    resource_label,
    instance,
    action,
    before=None,
    after=None,
    category='resource_change',
    result=EventRecord.RESULT_SUCCESS,
    severity=EventRecord.SEVERITY_INFO,
    related_resources=None,
    metadata=None,
    tags=None,
    correlation_id='',
    name_fields=None,
    application='',
):
    resource_name = infer_resource_name(instance, custom_fields=name_fields)
    if action == 'create':
        title = f'创建{resource_label}'
        summary = f'{resource_label} {resource_name} 已创建'
    elif action == 'delete':
        title = f'删除{resource_label}'
        summary = f'{resource_label} {resource_name} 已删除'
    else:
        title = f'更新{resource_label}'
        changes = diff_snapshots(before or {}, after or {})
        summary = f'{resource_label} {resource_name} 已更新'
        if changes:
            summary = f'{summary}，变更字段 {len(changes)} 个'
    changes = diff_snapshots(before or {}, after or {}) if action == 'update' else {}
    return record_event(
        request=request,
        module=module,
        category=category,
        action=action,
        result=result,
        severity=severity,
        title=title,
        summary=summary,
        resource_type=resource_type,
        resource_id=instance.pk,
        resource_name=resource_name,
        business_line=getattr(instance, 'business_line', '') or '',
        environment=getattr(instance, 'environment', '') or '',
        application=application or infer_application_name(instance),
        related_resources=related_resources or [],
        changes=changes,
        metadata=metadata or {},
        tags=tags or [],
        correlation_id=correlation_id or build_correlation_id(resource_type, instance.pk),
    )


def build_json_preview(payload):
    try:
        text = json.dumps(sanitize_value(payload or {}, 'payload'), ensure_ascii=False)
    except TypeError:
        text = str(payload)
    return text[:200]

def prune_event_records_before(cutoff, queryset=None, **audit):
    """滚动清理 cutoff 之前的非外部接入事件。

    外部接入事件（source_type=SOURCE_EXTERNAL 或 category='external_event'）受保护不删。
    queryset：调用方可传入已施加行级作用域（RBAC/视图过滤）的查询集；
    不传则基于 EventRecord.objects 全量（供系统级调度清理使用）。
    audit 关键字参数用于自审计事件（调用方按需携带请求上下文或系统上下文；
    不传则只删除不记录）。返回删除条数。
    """
    if cutoff and timezone.is_naive(cutoff):
        cutoff = timezone.make_aware(cutoff, timezone.get_current_timezone())
    base = queryset if queryset is not None else EventRecord.objects
    queryset = (
        base
        .exclude(source_type=EventRecord.SOURCE_EXTERNAL)
        .exclude(category='external_event')
        .filter(occurred_at__lt=cutoff)
    )
    deleted_count = queryset.count()
    queryset.delete()
    if audit:
        record_event(
            module=audit.pop('module', 'rbac'),
            category=audit.pop('category', 'resource_change'),
            action=audit.pop('action', 'prune_operation_audit'),
            title=audit.pop('title', '批量删除操作审计'),
            summary=audit.pop('summary', f'删除 {cutoff.isoformat()} 之前的操作审计记录 {deleted_count} 条'),
            result=audit.pop('result', EventRecord.RESULT_SUCCESS),
            severity=audit.pop('severity', EventRecord.SEVERITY_WARNING),
            actor_username=audit.pop('actor_username', ''),
            actor_display=audit.pop('actor_display', ''),
            actor_type=audit.pop('actor_type', EventRecord.ACTOR_SYSTEM),
            source_type=audit.pop('source_type', EventRecord.SOURCE_SYSTEM),
            resource_module=audit.pop('resource_module', 'rbac'),
            resource_type=audit.pop('resource_type', 'operation_audit'),
            resource_id=audit.pop('resource_id', cutoff.isoformat()),
            resource_name=audit.pop('resource_name', '操作审计'),
            metadata=audit.pop('metadata', {'before_at': cutoff.isoformat(), 'deleted': deleted_count}),
            **audit,
        )
    return deleted_count
