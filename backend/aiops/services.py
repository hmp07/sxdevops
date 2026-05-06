import json
import os
import queue
import re
import shlex
import socket
import subprocess
import threading
import time
import uuid
from collections import Counter
from decimal import Decimal
from urllib.parse import urlparse

import requests
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from cmdb.models import ConfigItem
from eventwall.models import EventRecord
from eventwall.services import record_event
from iac.models import TerraformExecution, TerraformStack
from multicloud.models import CloudAsset
from ops.host_tasks import start_host_task
from ops.models import (
    Alert,
    Deployment,
    DockerHost,
    Host,
    HostTask,
    K8sCluster,
    LogDataSource,
    LogEntry,
    NginxEnvironment,
    TracingDataSource,
    TransactionTicket,
)
from ops.tracing_providers import (
    DEMO_TRACES,
    ObservabilityError,
    _provider_handlers,
    _resolve_provider,
    load_tracing_catalog,
)
from ops.middleware_views import _build_payload as build_middleware_payload
from ops.middleware_views import _get_demo_state as get_middleware_demo_state
from rbac.services import is_demo_account, user_has_permissions

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsSkill,
    AIOpsToolInvocation,
)

User = get_user_model()
DEMO_SYNC_SOURCE_USERNAME = 'admin'
DEMO_SYNC_TARGET_USERNAME = 'demo'
DEFAULT_WELCOME_MESSAGE = (
    '\u4f60\u597d\uff0c\u6211\u53ef\u4ee5\u5e2e\u4f60\u7ed3\u5408\u5e73\u53f0\u4e0a\u4e0b\u6587'
    '\u67e5\u8be2\u8d44\u6e90\u3001\u5206\u6790\u544a\u8b66\u3001\u6210\u672c\u5206\u6790\u3001'
    '\u751f\u6210\u5f85\u6267\u884c\u4efb\u52a1\u7b49\u3002'
)
LEGACY_DEFAULT_WELCOME_MESSAGE = (
    '\u4f60\u597d\uff0c\u6211\u53ef\u4ee5\u5e2e\u4f60\u67e5\u8be2\u8d44\u6e90\u3001'
    '\u544a\u8b66\u548c\u751f\u6210\u8fd0\u7ef4\u4efb\u52a1\u3002'
)


def _repair_utf8_mojibake(value):
    text = str(value or '')
    if not text:
        return text
    try:
        repaired = text.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if repaired != text and any('\u4e00' <= char <= '\u9fff' for char in repaired):
        return repaired
    return text
DEFAULT_WELCOME_MESSAGE = '你好，我可以帮你结合平台上下文查询资源、分析告警、成本分析、生成待执行任务等。'


DEFAULT_SUGGESTED_QUESTIONS = [
    '当前未确认的严重告警有哪些？',
    '生成一份 Redis 巡检任务。',
    '分析生产order-center最近异常',
    '数据平台生产环境月成本多少',
    'app-prod-k8s集群有没有异常的pod',
    '最近电商线生产有哪些工单',
]

DEFAULT_SYSTEM_PROMPT = (
    '你是 SxDevOps 平台内的 AIOps 智能助手。'
    '必须优先通过可用的 MCP 工具获取平台内结构化数据，严禁编造不存在的资源、告警、日志、链路和执行结果。'
    '回答时区分事实、推断和建议；涉及执行类动作时，未确认前只能生成草稿。'
)

ANSWER_FORMATTER_SKILL_SLUG = 'answer-formatter'

STOPWORDS = {
    '帮我', '一下', '当前', '最近', '平台', '资源', '信息', '告警', '分析', '排查', '问题',
    '哪些', '多少', '怎么', '情况', '查看', '查询', '生成', '执行', '触发', '自动', '任务', '中心',
}

CMDB_QUERY_NOISE_PATTERNS = [
    'cmdb', 'CMDB', '配置项', '配置', '资产', '信息', '详情', '查下', '查一下', '查询', '查看', '获取', '告诉我',
    'ip地址', 'IP地址', '地址', 'IP', 'ip', '是多少', '是什么', '是哪个CI', '是哪个ci', '哪个CI', '哪个ci',
    '生产', '测试', '开发', 'prod', 'test', 'dev', '的', '吗', '呢',
]

ALERT_QUERY_NOISE_PATTERNS = [
    '\u5f53\u524d', '\u76ee\u524d', '\u6700\u8fd1', '\u6709\u54ea\u4e9b', '\u6709\u4ec0\u4e48', '\u54ea\u4e9b', '\u4ec0\u4e48', '\u544a\u8b66\u4e2d\u5fc3',
    '\u544a\u8b66', '\u4e25\u91cd', '\u9ad8\u5371', '\u8b66\u544a', '\u4fe1\u606f', '\u672a\u786e\u8ba4', '\u5df2\u786e\u8ba4', '\u786e\u8ba4',
    '\u72b6\u6001', '\u67e5\u770b', '\u67e5\u8be2', '\u5217\u51fa', '\u5e2e\u6211', '\u770b\u4e0b', '\u4e00\u4e0b', '\u5168\u90e8', '\u6240\u6709',
]

DANGEROUS_COMMAND_PATTERNS = [
    'rm -rf',
    'shutdown',
    'reboot',
    'mkfs',
    'userdel',
    'kill -9',
]

MCP_PROTOCOL_VERSION = '2025-03-26'
MCP_CLIENT_INFO = {'name': 'SxDevOps AIOps', 'version': '1.0.0'}

PROCESSING_STATUS_PENDING = 'pending'
PROCESSING_STATUS_RUNNING = 'running'
PROCESSING_STATUS_STREAMING = 'streaming'
PROCESSING_STATUS_COMPLETED = 'completed'
PROCESSING_STATUS_FAILED = 'failed'

BUILTIN_MCP_SERVERS = [
    {
        'name': 'CMDB MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 CMDB 配置项与资源关系。',
        'tool_whitelist': ['query_cmdb_items', 'query_hosts', 'query_cost_report'],
    },
    {
        'name': '可观测性 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询告警、日志、链路与最近变更。',
        'tool_whitelist': ['query_observability', 'query_alerts', 'query_events', 'query_logs', 'query_traces', 'query_recent_changes'],
    },
    {
        'name': '工单系统 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询事务工单与当前处理状态。',
        'tool_whitelist': ['query_workorders'],
    },
    {
        'name': '任务中心 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询主机任务并生成任务草稿。',
        'tool_whitelist': ['query_task_center', 'query_host_tasks', 'generate_host_task'],
    },
    {
        'name': '事件墙 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询事件墙中的关键事件与最近动态。',
        'tool_whitelist': ['query_event_wall'],
    },
    {
        'name': '容器管理 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 Kubernetes 集群与 Docker 主机。',
        'tool_whitelist': ['query_container_assets', 'query_k8s_cluster_summary'],
    },
    {
        'name': '中间件 MCP',
        'server_type': AIOpsMCPServer.SERVER_PLATFORM_BUILTIN,
        'description': '查询 Nginx、Redis、RocketMQ、Elasticsearch 等中间件状态。',
        'tool_whitelist': ['query_middleware_assets'],
    },
    {
        'name': 'N9E 监控 MCP',
        'server_type': AIOpsMCPServer.SERVER_STDIO,
        'description': '对接 Nightingale（N9E）官方 MCP Server，查询告警、监控目标、数据源、事件流水线与团队信息。',
        'endpoint_or_command': 'npx -y @n9e/n9e-mcp-server stdio',
        'auth_config': {
            'timeout_seconds': 20,
            'env': {
                'N9E_TOKEN': 'demo-n9e-token',
                'N9E_BASE_URL': 'http://nightingale.example.com:17000',
                'N9E_READ_ONLY': 'true',
                'N9E_TOOLSETS': 'alerts,targets,datasource,mutes,busi_groups,notify_rules,alert_subscribes,event_pipelines,users',
            },
        },
        'tool_whitelist': [
            'list_active_alerts',
            'get_active_alert',
            'list_history_alerts',
            'get_history_alert',
            'list_alert_rules',
            'get_alert_rule',
            'list_targets',
            'list_datasources',
            'list_mutes',
            'get_mute',
            'create_mute',
            'update_mute',
            'list_notify_rules',
            'get_notify_rule',
            'list_alert_subscribes',
            'list_alert_subscribes_by_gids',
            'get_alert_subscribe',
            'list_event_pipelines',
            'get_event_pipeline',
            'list_event_pipeline_executions',
            'list_all_event_pipeline_executions',
            'get_event_pipeline_execution',
            'list_users',
            'get_user',
            'list_user_groups',
            'get_user_group',
            'list_busi_groups',
        ],
    },
    {
        'name': 'SkyWalking MCP',
        'server_type': AIOpsMCPServer.SERVER_STDIO,
        'description': '对接 Apache SkyWalking 官方 MCP Server，查询 APM、拓扑、链路与相关可观测性数据。',
        'endpoint_or_command': 'swmcp stdio --read-only --sw-url http://skywalking-oap.example.com:12800 --sw-username ${SW_USERNAME} --sw-password ${SW_PASSWORD}',
        'auth_config': {
            'timeout_seconds': 20,
            'env': {
                'SW_USERNAME': 'demo-skywalking-admin',
                'SW_PASSWORD': 'demo-skywalking-password',
                'SKYWALKING_OAP_URL': 'http://skywalking-oap.example.com:12800',
            },
        },
        'tool_whitelist': [
            'query_traces',
            'query_logs',
            'execute_mqe_expression',
            'list_mqe_metrics',
            'get_mqe_metric_type',
            'list_layers',
            'list_services',
            'list_instances',
            'list_endpoints',
            'list_processes',
        ],
    },
    {
        'name': 'Grafana MCP',
        'server_type': AIOpsMCPServer.SERVER_HTTP,
        'description': '对接 Grafana MCP Server，通过 HTTP 方式查询仪表盘、数据源、Prometheus 与 Loki 等能力。',
        'endpoint_or_command': 'http://grafana-mcp.example.com/mcp',
        'auth_config': {
            'timeout_seconds': 20,
            'headers': {
                'Authorization': 'Bearer demo-grafana-service-account-token',
                'X-Grafana-URL': 'http://grafana.example.com',
            },
            'grafana_url': 'http://grafana.example.com',
            'service_account_token': 'demo-grafana-service-account-token',
        },
        'tool_whitelist': [
            'search_dashboards',
            'get_dashboard_by_uid',
            'get_dashboard_summary',
            'get_dashboard_property',
            'get_dashboard_panel_queries',
            'list_datasources',
            'get_datasource',
            'query_prometheus',
            'query_loki_logs',
            'list_incidents',
        ],
    },
]

BUILTIN_SKILLS = [
    {
        'name': '证据优先应答',
        'slug': 'evidence-first-responder',
        'description': '优先调用工具取证，再输出事实、推断与建议。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '先调用 MCP 工具获取平台事实，再作答。输出结构优先为：事实、推断、建议。',
        'allowed_role_codes': [],
    },
    {
        'name': '故障关联分析',
        'slug': 'incident-investigator',
        'description': '围绕告警、事件、日志、链路和变更做关联分析。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '异常、故障、根因类问题优先组合调用告警、事件、日志、链路和最近变更工具。',
        'allowed_role_codes': [],
    },
    {
        'name': '回答整形器',
        'slug': 'answer-formatter',
        'description': '基于工具事实重组最终回答，输出更稳定的结构化结果。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '拿到 MCP 工具结果后，优先整理为结论、关键信息、风险与建议；如果涉及生成任务，要明确写出当前是任务草稿、待确认创建，还是已经在任务中心创建待执行任务，并给出目标、执行方式、风险和下一步；不要只返回一句泛化结论，也不要脱离工具事实自由发挥。',
        'allowed_role_codes': [],
    },
    {
        'name': '自动化安全护栏',
        'slug': 'automation-safety-guard',
        'description': '执行类任务先生成草稿，强调范围、风险与确认。',
        'source_type': AIOpsSkill.SOURCE_INLINE,
        'content': '涉及任务执行时，先生成草稿，列出目标、执行方式、执行策略与风险等级，未确认前不能声称已执行。',
        'allowed_role_codes': [],
    },
]

BUILTIN_MODEL_PROVIDER = {
    'name': '智能助手体验版',
    'provider_type': AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
    'base_url': 'https://api.openai.example.com/v1',
    'default_model': 'gpt-4o-mini',
    'backup_model': 'gpt-4.1-mini',
    'temperature': 0.2,
    'max_tokens': 1600,
    'timeout_seconds': 30,
    'api_key': 'demo-openai-compatible-key',
    'last_test_message': '预置体验配置，需替换为真实 API Key 后使用',
}


def _is_builtin_experience_provider(provider):
    return bool(provider and provider.name == BUILTIN_MODEL_PROVIDER['name'])


def _builtin_experience_provider_needs_setup(provider):
    if not _is_builtin_experience_provider(provider):
        return False
    base_url = (provider.base_url or '').strip()
    api_key = provider.get_api_key().strip()
    default_model = (provider.default_model or '').strip()
    return (
        not base_url
        or base_url == BUILTIN_MODEL_PROVIDER['base_url']
        or not api_key
        or api_key == BUILTIN_MODEL_PROVIDER['api_key']
        or not default_model
    )


def get_model_provider_setup_hint(provider):
    if _builtin_experience_provider_needs_setup(provider):
        return '“智能助手体验版”只是预置模板，请先填写真实 Base URL 和 API Key。'
    if not provider:
        return '请先启用并配置一个可用的模型提供商。'
    missing_items = []
    if not (provider.base_url or '').strip():
        missing_items.append('Base URL')
    if not (provider.default_model or '').strip():
        missing_items.append('默认模型')
    if not provider.get_api_key().strip():
        missing_items.append('API Key')
    if missing_items:
        return f"请先补全：{'、'.join(missing_items)}"
    return ''


def _normalize_json_id_list(values):
    normalized = []
    for value in values or []:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def _ensure_builtin_runtime_assets(config):
    builtin_mcp_ids = []
    builtin_skill_ids = []
    builtin_mcp_names = {item['name'] for item in BUILTIN_MCP_SERVERS}
    builtin_skill_slugs = {item['slug'] for item in BUILTIN_SKILLS}

    for definition in BUILTIN_MCP_SERVERS:
        server, _ = AIOpsMCPServer.objects.get_or_create(
            name=definition['name'],
            defaults={
                'server_type': definition['server_type'],
                'description': definition['description'],
                'endpoint_or_command': definition.get('endpoint_or_command', ''),
                'auth_config': definition.get('auth_config', {}),
                'tool_whitelist': definition['tool_whitelist'],
                'is_builtin': True,
                'is_enabled': True,
            },
        )
        changed_fields = []
        if not server.is_builtin:
            server.is_builtin = True
            changed_fields.append('is_builtin')
        if server.server_type != definition['server_type']:
            server.server_type = definition['server_type']
            changed_fields.append('server_type')
        if server.tool_whitelist != definition['tool_whitelist']:
            server.tool_whitelist = definition['tool_whitelist']
            changed_fields.append('tool_whitelist')
        if server.description != definition['description']:
            server.description = definition['description']
            changed_fields.append('description')
        if definition.get('endpoint_or_command') and not server.endpoint_or_command:
            server.endpoint_or_command = definition['endpoint_or_command']
            changed_fields.append('endpoint_or_command')
        if definition.get('auth_config') and not server.auth_config:
            server.auth_config = definition['auth_config']
            changed_fields.append('auth_config')
        if changed_fields:
            server.save(update_fields=changed_fields)
        builtin_mcp_ids.append(server.id)

    AIOpsMCPServer.objects.filter(is_builtin=True).exclude(name__in=builtin_mcp_names).delete()

    for definition in BUILTIN_SKILLS:
        skill, _ = AIOpsSkill.objects.get_or_create(
            slug=definition['slug'],
            defaults={
                'name': definition['name'],
                'description': definition['description'],
                'source_type': definition['source_type'],
                'content': definition['content'],
                'allowed_role_codes': definition['allowed_role_codes'],
                'is_builtin': True,
                'is_enabled': True,
            },
        )
        changed_fields = []
        if not skill.is_builtin:
            skill.is_builtin = True
            changed_fields.append('is_builtin')
        if skill.name != definition['name']:
            skill.name = definition['name']
            changed_fields.append('name')
        if skill.source_type != definition['source_type']:
            skill.source_type = definition['source_type']
            changed_fields.append('source_type')
        if not skill.content:
            skill.content = definition['content']
            changed_fields.append('content')
        if not skill.description:
            skill.description = definition['description']
            changed_fields.append('description')
        if changed_fields:
            skill.save(update_fields=changed_fields)
        builtin_skill_ids.append(skill.id)

    AIOpsSkill.objects.filter(is_builtin=True).exclude(slug__in=builtin_skill_slugs).delete()

    update_fields = []
    valid_mcp_ids = set(AIOpsMCPServer.objects.values_list('id', flat=True))
    valid_skill_ids = set(AIOpsSkill.objects.values_list('id', flat=True))
    current_mcp_ids = [item for item in _normalize_json_id_list(config.enabled_mcp_server_ids) if item in valid_mcp_ids and item not in builtin_mcp_ids]
    current_skill_ids = [item for item in _normalize_json_id_list(config.enabled_skill_ids) if item in valid_skill_ids and item not in builtin_skill_ids]
    next_mcp_ids = list(dict.fromkeys([*builtin_mcp_ids, *current_mcp_ids]))
    next_skill_ids = list(dict.fromkeys([*builtin_skill_ids, *current_skill_ids]))
    if next_mcp_ids != (config.enabled_mcp_server_ids or []):
        config.enabled_mcp_server_ids = next_mcp_ids
        update_fields.append('enabled_mcp_server_ids')
    if next_skill_ids != (config.enabled_skill_ids or []):
        config.enabled_skill_ids = next_skill_ids
        update_fields.append('enabled_skill_ids')
    if update_fields:
        config.save(update_fields=update_fields)


def _ensure_builtin_model_provider(config):
    definition = BUILTIN_MODEL_PROVIDER
    provider, created = AIOpsModelProvider.objects.get_or_create(
        name=definition['name'],
        defaults={
            'provider_type': definition['provider_type'],
            'base_url': definition['base_url'],
            'default_model': definition['default_model'],
            'backup_model': definition['backup_model'],
            'temperature': definition['temperature'],
            'max_tokens': definition['max_tokens'],
            'timeout_seconds': definition['timeout_seconds'],
            'is_enabled': True,
            'last_test_status': AIOpsModelProvider.STATUS_UNKNOWN,
            'last_test_message': definition['last_test_message'],
        },
    )
    changed_fields = []
    for field in ['provider_type', 'base_url', 'default_model', 'backup_model']:
        if not getattr(provider, field):
            setattr(provider, field, definition[field])
            changed_fields.append(field)
    for field in ['temperature', 'max_tokens', 'timeout_seconds']:
        if not getattr(provider, field):
            setattr(provider, field, definition[field])
            changed_fields.append(field)
    if created and not provider.is_enabled:
        provider.is_enabled = True
        changed_fields.append('is_enabled')
    if not provider.last_test_message:
        provider.last_test_message = definition['last_test_message']
        changed_fields.append('last_test_message')
    if provider.get_api_key().strip() == definition['api_key']:
        provider.set_api_key('')
        changed_fields.append('api_key_encrypted')
    if _builtin_experience_provider_needs_setup(provider):
        if provider.last_test_status != AIOpsModelProvider.STATUS_UNKNOWN:
            provider.last_test_status = AIOpsModelProvider.STATUS_UNKNOWN
            changed_fields.append('last_test_status')
        if provider.last_test_message != definition['last_test_message']:
            provider.last_test_message = definition['last_test_message']
            changed_fields.append('last_test_message')
    if changed_fields:
        provider.save(update_fields=list(dict.fromkeys(changed_fields)))

    if not config.default_provider_id:
        config.default_provider = provider
        config.save(update_fields=['default_provider'])

    return provider


def get_agent_config():
    config, _ = AIOpsAgentConfig.objects.get_or_create(
        name='default',
        defaults={
            'suggested_questions': DEFAULT_SUGGESTED_QUESTIONS,
            'system_prompt': DEFAULT_SYSTEM_PROMPT,
            'welcome_message': DEFAULT_WELCOME_MESSAGE,
        },
    )
    update_fields = []
    if not config.suggested_questions:
        config.suggested_questions = DEFAULT_SUGGESTED_QUESTIONS
        update_fields.append('suggested_questions')
    if not config.system_prompt:
        config.system_prompt = DEFAULT_SYSTEM_PROMPT
        update_fields.append('system_prompt')
    repaired_welcome_message = _repair_utf8_mojibake(config.welcome_message)
    if repaired_welcome_message != (config.welcome_message or ''):
        config.welcome_message = repaired_welcome_message
        update_fields.append('welcome_message')
    if (
        not config.welcome_message
        or config.welcome_message == '你好，我可以帮你查询资源、告警和生成运维任务。'
        or '?' in config.welcome_message
    ):
        config.welcome_message = DEFAULT_WELCOME_MESSAGE
        update_fields.append('welcome_message')
    if update_fields:
        config.save(update_fields=update_fields)
    _ensure_builtin_runtime_assets(config)
    _ensure_builtin_model_provider(config)
    return config


def get_active_provider(config=None):
    config = config or get_agent_config()
    provider = config.default_provider
    if provider and provider.is_enabled and _provider_is_ready(provider):
        return provider
    for item in AIOpsModelProvider.objects.filter(is_enabled=True).order_by('id'):
        if _provider_is_ready(item):
            return item
    return provider if provider and provider.is_enabled else AIOpsModelProvider.objects.filter(is_enabled=True).order_by('id').first()


def _get_selected_mcp_servers(config):
    selected_ids = _normalize_json_id_list(config.enabled_mcp_server_ids)
    queryset = AIOpsMCPServer.objects.filter(is_enabled=True)
    if selected_ids:
        queryset = queryset.filter(id__in=selected_ids)
    return list(queryset.order_by('is_builtin', 'id'))


def _get_selected_skills(config, user=None):
    selected_ids = _normalize_json_id_list(config.enabled_skill_ids)
    queryset = AIOpsSkill.objects.filter(is_enabled=True)
    if selected_ids:
        queryset = queryset.filter(id__in=selected_ids)
    skills = list(queryset.order_by('is_builtin', 'name', 'id'))
    if not user:
        return skills
    role_codes = set(user.rbac_roles.values_list('code', flat=True))
    filtered = []
    for skill in skills:
        allowed_codes = set(skill.allowed_role_codes or [])
        if allowed_codes and not (allowed_codes & role_codes):
            continue
        filtered.append(skill)
    return filtered


def _get_demo_sync_users():
    admin_user = User.objects.filter(username=DEMO_SYNC_SOURCE_USERNAME).first()
    demo_user = User.objects.filter(username=DEMO_SYNC_TARGET_USERNAME).first()
    if not admin_user or not demo_user or admin_user.id == demo_user.id:
        return None, None
    return admin_user, demo_user


def _sync_mirror_timestamps(model_cls, object_id, source):
    model_cls.objects.filter(pk=object_id).update(
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _sync_chat_session_to_demo(source_session, demo_user):
    if not source_session or source_session.mirror_source_id or source_session.user_id == demo_user.id:
        return None

    mirror_session, _ = AIOpsChatSession.objects.get_or_create(
        user=demo_user,
        mirror_source=source_session,
        defaults={
            'title': source_session.title,
            'status': source_session.status,
            'last_message_at': source_session.last_message_at,
        },
    )
    AIOpsChatSession.objects.filter(pk=mirror_session.pk).update(
        title=source_session.title,
        status=source_session.status,
        last_message_at=source_session.last_message_at,
    )
    _sync_mirror_timestamps(AIOpsChatSession, mirror_session.pk, source_session)
    mirror_session.refresh_from_db()

    source_messages = list(source_session.messages.order_by('created_at', 'id'))
    source_message_ids = [item.id for item in source_messages]
    AIOpsChatMessage.objects.filter(session=mirror_session, mirror_source__isnull=False).exclude(
        mirror_source_id__in=source_message_ids
    ).delete()

    message_id_map = {}
    for source_message in source_messages:
        mirror_message, _ = AIOpsChatMessage.objects.get_or_create(
            session=mirror_session,
            mirror_source=source_message,
            defaults={
                'role': source_message.role,
                'message_type': source_message.message_type,
                'content': source_message.content,
                'citations': source_message.citations,
                'tool_calls': source_message.tool_calls,
                'metadata': source_message.metadata,
            },
        )
        AIOpsChatMessage.objects.filter(pk=mirror_message.pk).update(
            role=source_message.role,
            message_type=source_message.message_type,
            content=source_message.content,
            citations=source_message.citations,
            tool_calls=source_message.tool_calls,
            metadata=source_message.metadata,
            created_at=source_message.created_at,
        )
        mirror_message.refresh_from_db(fields=['id'])
        message_id_map[source_message.id] = mirror_message.id

    source_actions = list(source_session.pending_actions.order_by('created_at', 'id'))
    source_action_ids = [item.id for item in source_actions]
    AIOpsPendingAction.objects.filter(session=mirror_session, mirror_source__isnull=False).exclude(
        mirror_source_id__in=source_action_ids
    ).delete()

    for source_action in source_actions:
        mirror_action, _ = AIOpsPendingAction.objects.get_or_create(
            session=mirror_session,
            mirror_source=source_action,
            defaults={
                'message_id': message_id_map.get(source_action.message_id),
                'action_type': source_action.action_type,
                'title': source_action.title,
                'risk_level': source_action.risk_level,
                'status': source_action.status,
                'action_payload': source_action.action_payload,
                'result_payload': source_action.result_payload,
                'confirmed_by': source_action.confirmed_by,
                'confirmed_at': source_action.confirmed_at,
            },
        )
        AIOpsPendingAction.objects.filter(pk=mirror_action.pk).update(
            message_id=message_id_map.get(source_action.message_id),
            action_type=source_action.action_type,
            title=source_action.title,
            risk_level=source_action.risk_level,
            status=source_action.status,
            action_payload=source_action.action_payload,
            result_payload=source_action.result_payload,
            confirmed_by=source_action.confirmed_by,
            confirmed_at=source_action.confirmed_at,
            created_at=source_action.created_at,
            updated_at=source_action.updated_at,
        )

    return mirror_session


def sync_admin_sessions_to_demo(source_session=None):
    admin_user, demo_user = _get_demo_sync_users()
    if not admin_user or not demo_user:
        return 0

    queryset = AIOpsChatSession.objects.filter(user=admin_user, mirror_source__isnull=True).order_by('created_at', 'id')
    if source_session is not None:
        if source_session.user_id != admin_user.id or source_session.mirror_source_id:
            return 0
        queryset = queryset.filter(pk=source_session.pk)

    source_sessions = list(queryset)
    if source_session is None:
        source_ids = [item.id for item in source_sessions]
        AIOpsChatSession.objects.filter(user=demo_user, mirror_source__isnull=False).exclude(
            mirror_source_id__in=source_ids
        ).delete()

    for item in source_sessions:
        _sync_chat_session_to_demo(item, demo_user)
    return len(source_sessions)


def sync_session_to_demo_if_needed(session):
    if not session or session.mirror_source_id:
        return None
    if getattr(session.user, 'username', '') != DEMO_SYNC_SOURCE_USERNAME:
        return None
    admin_user, demo_user = _get_demo_sync_users()
    if not admin_user or not demo_user or session.user_id != admin_user.id:
        return None
    return _sync_chat_session_to_demo(session, demo_user)


def bootstrap_payload_for_user(user):
    if is_demo_account(user):
        sync_admin_sessions_to_demo()
    config = get_agent_config()
    provider = get_active_provider(config)
    selected_mcp_servers = _get_selected_mcp_servers(config)
    selected_skills = _get_selected_skills(config, user=user)
    return {
        'enabled': config.is_enabled and user_has_permissions(user, ['aiops.chat.view']),
        'welcome_message': config.welcome_message,
        'suggested_questions': config.suggested_questions or DEFAULT_SUGGESTED_QUESTIONS,
        'permissions': {
            'chat': user_has_permissions(user, ['aiops.chat.view']),
            'analyze': user_has_permissions(user, ['aiops.chat.analyze']),
            'generate_task': user_has_permissions(user, ['aiops.task.generate']),
            'execute_task': user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']),
            'config_view': user_has_permissions(user, ['aiops.config.view']),
            'config_manage': user_has_permissions(user, ['aiops.config.manage']),
        },
        'provider': {
            'name': provider.name if provider else '未配置模型',
            'model': provider.default_model if provider else '',
        },
        'runtime': {
            'allow_action_execution': config.allow_action_execution,
            'require_confirmation': config.require_confirmation,
            'show_evidence': config.show_evidence,
            'allow_analysis': config.allow_analysis,
        },
        'active_mcp_servers': [
            {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'tool_whitelist': item.tool_whitelist,
                'is_builtin': item.is_builtin,
            }
            for item in selected_mcp_servers
        ],
        'active_skills': [
            {
                'id': item.id,
                'name': item.name,
                'slug': item.slug,
                'description': item.description,
                'is_builtin': item.is_builtin,
            }
            for item in selected_skills
        ],
    }


def recover_masked_suggested_question(content):
    text = (content or '').strip()
    if not text or '?' not in text:
        return text

    def mask_question(value):
        masked = []
        for char in value:
            if ord(char) < 128 and char.isprintable():
                masked.append(char)
            else:
                masked.append('?')
        return ''.join(masked)

    config = get_agent_config()
    candidates = list(dict.fromkeys((config.suggested_questions or []) + DEFAULT_SUGGESTED_QUESTIONS))
    for item in candidates:
        if mask_question(item) == text:
            return item
    return text


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _clean_tokens(text):
    chunks = re.split(r'[\s,，。！？；:：/\\|()\[\]{}]+', text or '')
    tokens = []
    for chunk in chunks:
        token = chunk.strip().strip('"\'')
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens[:8]


def _clean_cmdb_query_tokens(text):
    cleaned = text or ''
    for pattern in CMDB_QUERY_NOISE_PATTERNS:
        if pattern:
            cleaned = cleaned.replace(pattern, ' ')
    tokens = _clean_tokens(cleaned)
    deduped = []
    for token in tokens:
        normalized = (token or '').strip()
        lowered = normalized.lower()
        if lowered in {'ci', 'ip'}:
            continue
        if any(keyword in normalized for keyword in ['哪个', '多少', '什么']):
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped[:8]


def _clean_alert_query_tokens(text):
    cleaned = text or ''
    for pattern in ALERT_QUERY_NOISE_PATTERNS:
        if pattern:
            cleaned = cleaned.replace(pattern, ' ')
    tokens = _clean_tokens(cleaned)
    deduped = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:8]


def _normalize_alert_query_request(query='', level='', only_unacknowledged=False):
    raw_query = query or ''
    normalized_query = raw_query
    resolved_level = (level or '').strip().lower()
    resolved_unacknowledged = bool(only_unacknowledged)

    level_match = re.search(r'\b(?:severity|level)\s*[:=]\s*(critical|warning|info)\b', raw_query, re.IGNORECASE)
    if not resolved_level and level_match:
        resolved_level = level_match.group(1).lower()
    if not resolved_level:
        if '严重' in raw_query or '高危' in raw_query:
            resolved_level = 'critical'
        elif '警告' in raw_query:
            resolved_level = 'warning'
        elif '信息' in raw_query:
            resolved_level = 'info'

    acknowledged_match = re.search(
        r'\b(?:acknowledged|is_acknowledged)\s*[:=]\s*(true|false|1|0|yes|no)\b',
        raw_query,
        re.IGNORECASE,
    )
    if not resolved_unacknowledged and acknowledged_match:
        resolved_unacknowledged = acknowledged_match.group(1).lower() in {'false', '0', 'no'}
    if not resolved_unacknowledged and any(keyword in raw_query for keyword in ['未确认', '未认领', '未处理']):
        resolved_unacknowledged = True

    filter_patterns = [
        r'\b(?:type|kind)\s*[:=]\s*alert\b',
        r'\b(?:severity|level)\s*[:=]\s*(?:critical|warning|info)\b',
        r'\b(?:acknowledged|is_acknowledged)\s*[:=]\s*(?:true|false|1|0|yes|no)\b',
        r'\bstatus\s*[:=]\s*(?:active|open|pending|closed)\b',
        r'\bAND\b',
    ]
    for pattern in filter_patterns:
        normalized_query = re.sub(pattern, ' ', normalized_query, flags=re.IGNORECASE)
    normalized_query = re.sub(r'\s+', ' ', normalized_query).strip()

    return normalized_query, resolved_level, resolved_unacknowledged


def _extract_environment(text):
    mapping = {'生产': 'prod', 'prod': 'prod', '测试': 'test', 'test': 'test', '开发': 'dev', 'dev': 'dev'}
    lowered = (text or '').lower()
    for keyword, code in mapping.items():
        if keyword in lowered:
            return code
    return ''


def _extract_business_line(text):
    value = text or ''
    mappings = [
        ('电商线', '电商线'),
        ('电商', '电商线'),
        ('commerce', '电商线'),
        ('数据平台', '数据平台'),
        ('数据线', '数据平台'),
        ('data', '数据平台'),
        ('基础架构', '基础架构'),
        ('基础设施', '基础架构'),
        ('infra', '基础架构'),
    ]
    lowered = value.lower()
    for keyword, normalized in mappings:
        if keyword.lower() in lowered:
            return normalized
    return ''


def _contains_any(text, keywords):
    lowered = (text or '').lower()
    return any(keyword in lowered for keyword in keywords)


def _is_unhelpful_answer(content):
    lowered = (content or '').strip().lower()
    if not lowered:
        return True
    patterns = [
        '我没看懂', '我不确定', '请补充', '请说明', '请澄清', '没理解',
        "i'm not sure", 'could you clarify', 'tell me what', 'need more context',
    ]
    return any(pattern in lowered for pattern in patterns)


def _queryset_search(queryset, fields, tokens):
    if not tokens:
        return queryset
    condition = Q()
    for token in tokens:
        token_condition = Q()
        for field in fields:
            token_condition |= Q(**{f'{field}__icontains': token})
        condition &= token_condition
    return queryset.filter(condition)


def _strip_common_query_phrases(text, phrases):
    cleaned = text or ''
    for phrase in phrases:
        if phrase:
            cleaned = cleaned.replace(phrase, ' ')
    return re.sub(r'\s+', ' ', cleaned).strip()


def _query_cmdb_queryset(queryset, tokens):
    return _queryset_search(
        queryset,
        [
            'name',
            'business_line',
            'admin_user',
            'ci_type__name',
            'attributes__ip_address',
            'attributes__ip',
            'attributes__private_ip',
            'attributes__public_ip',
            'attributes__host_ip',
            'attributes__docker_environment_ip',
            'attributes__description',
            'attributes__specification',
            'attributes__instance_type',
            'attributes__cloud_provider',
        ],
        tokens,
    )


def _serialize_cmdb_item(item):
    attributes = dict(item.attributes or {})
    ip_address = (
        attributes.get('ip_address')
        or attributes.get('private_ip')
        or attributes.get('public_ip')
        or attributes.get('host_ip')
        or attributes.get('docker_environment_ip')
        or ''
    )
    return {
        'id': item.id,
        'name': item.name,
        'ci_type': item.ci_type.name,
        'business_line': item.business_line,
        'environment': item.environment,
        'admin_user': item.admin_user,
        'status': item.status,
        'status_display': item.get_status_display(),
        'ip_address': ip_address,
        'attributes': attributes,
    }


def _dedupe_citations(citations):
    deduped = []
    seen = set()
    for item in citations or []:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _create_tool_invocation(session, user_message, tool_name, request_payload):
    return AIOpsToolInvocation.objects.create(
        session=session,
        message=user_message,
        tool_name=tool_name,
        request_payload=request_payload,
    )


def _finish_tool_invocation(invocation, response_summary, started_at, success=True):
    invocation.status = AIOpsToolInvocation.STATUS_SUCCESS if success else AIOpsToolInvocation.STATUS_FAILED
    invocation.response_summary = response_summary
    invocation.latency_ms = max(int((time.time() - started_at) * 1000), 1)
    invocation.save(update_fields=['status', 'response_summary', 'latency_ms'])


def _append_limited_event(items, event, max_items=24):
    entries = list(items or [])
    entries.append(event)
    if len(entries) > max_items:
        entries = entries[-max_items:]
    return entries


def _update_chat_message_processing(
    message_id,
    *,
    status_value=None,
    text=None,
    step=None,
    tool_event=None,
    content=None,
    message_type=None,
    citations=None,
    tool_calls=None,
    metadata_updates=None,
):
    message = AIOpsChatMessage.objects.filter(pk=message_id).first()
    if not message:
        return None

    metadata = dict(message.metadata or {})
    changed_fields = []

    if status_value:
        metadata['processing_status'] = status_value
    if text is not None:
        metadata['processing_text'] = text
    if step:
        metadata['processing_steps'] = _append_limited_event(
            metadata.get('processing_steps'),
            {
                'title': step.get('title') or '',
                'detail': step.get('detail') or '',
                'status': step.get('status') or PROCESSING_STATUS_COMPLETED,
                'timestamp': timezone.now().isoformat(),
            },
            max_items=18,
        )
    if tool_event:
        metadata['tool_events'] = _append_limited_event(
            metadata.get('tool_events'),
            {
                'name': tool_event.get('name') or '',
                'detail': tool_event.get('detail') or '',
                'status': tool_event.get('status') or PROCESSING_STATUS_COMPLETED,
                'timestamp': timezone.now().isoformat(),
            },
            max_items=24,
        )
    if metadata_updates:
        metadata.update(metadata_updates)

    if message.metadata != metadata:
        message.metadata = metadata
        changed_fields.append('metadata')
    if content is not None and message.content != content:
        message.content = content
        changed_fields.append('content')
    if message_type and message.message_type != message_type:
        message.message_type = message_type
        changed_fields.append('message_type')
    if citations is not None and message.citations != citations:
        message.citations = citations
        changed_fields.append('citations')
    if tool_calls is not None and message.tool_calls != tool_calls:
        message.tool_calls = tool_calls
        changed_fields.append('tool_calls')

    if changed_fields:
        message.save(update_fields=changed_fields)
    return message


def _make_processing_callback(message_id):
    def emit(**kwargs):
        return _update_chat_message_processing(message_id, **kwargs)
    return emit


def _touch_chat_session(session, question=''):
    session.last_message_at = timezone.now()
    new_session_title = '\u65b0\u4f1a\u8bdd'
    if session.title == new_session_title:
        session.title = (question or new_session_title)[:48]
    session.save(update_fields=['last_message_at', 'title', 'updated_at'])
    sync_session_to_demo_if_needed(session)


def _summarize_tool_result(tool_result):
    section_count = len(tool_result.get('sections') or [])
    citation_count = len(tool_result.get('citations') or [])
    if section_count and citation_count:
        return f'\u8fd4\u56de {section_count} \u4e2a\u7ed3\u679c\u5206\u7ec4\uff0c\u9644\u5e26 {citation_count} \u4e2a\u5f15\u7528\u3002'
    if section_count:
        return f'\u8fd4\u56de {section_count} \u4e2a\u7ed3\u679c\u5206\u7ec4\u3002'
    if citation_count:
        return f'\u8fd4\u56de {citation_count} \u4e2a\u5f15\u7528\u3002'
    tool_output = tool_result.get('tool_output') or {}
    if isinstance(tool_output, dict) and tool_output.get('error'):
        return str(tool_output.get('error'))
    return '\u8c03\u7528\u5b8c\u6210\u3002'


def query_resources(session, user_message, user, query='', environment='', limit=6):
    started_at = time.time()
    lowered_query = (query or '').lower()
    if any(keyword in lowered_query for keyword in ['离线', 'offline']) and any(keyword in lowered_query for keyword in ['主机', '服务器', 'host']):
        return query_hosts(session, user_message, user, query=query, environment=environment, status='offline', limit=limit)
    if any(keyword in lowered_query for keyword in ['月成本', '成本', 'cost']):
        return query_cost_report(session, user_message, user, query=query, environment=environment, limit=max(3, min(limit, 8)))

    tokens = _clean_cmdb_query_tokens(query)
    environment = environment or _extract_environment(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_resources',
        {'query': query, 'tokens': tokens, 'environment': environment, 'limit': limit},
    )
    sections = []
    citations = []
    summary = {}

    if user_has_permissions(user, ['ops.host.view']):
        host_queryset = Host.objects.all()
        if environment:
            host_queryset = host_queryset.filter(environment=environment)
        host_queryset = _queryset_search(host_queryset, ['hostname', 'ip_address', 'business_line', 'admin_user', 'description'], tokens)
        hosts = list(host_queryset.order_by('-updated_at')[:limit])
        if hosts:
            sections.append({
                'title': '主机资源',
                'items': [f'{host.hostname} ({host.ip_address}) / {host.get_status_display()}' for host in hosts],
            })
            summary['hosts'] = len(hosts)
            citations.append({'title': '主机中心', 'path': '/hosts/assets'})

    if user_has_permissions(user, ['cmdb.ci.view']):
        ci_queryset = ConfigItem.objects.select_related('ci_type').all()
        if environment:
            ci_queryset = ci_queryset.filter(environment=environment)
        ci_queryset = _query_cmdb_queryset(ci_queryset, tokens)
        items = list(ci_queryset.order_by('-updated_at')[:limit])
        if items:
            sections.append({
                'title': 'CMDB 配置项',
                'items': [f'{item.name} / {item.ci_type.name} / {item.get_status_display()}' for item in items],
            })
            summary['cmdb_items'] = len(items)
            citations.append({'title': 'CMDB', 'path': '/cmdb', 'query': {'tab': 'items'}})

    if user_has_permissions(user, ['ops.multicloud.view']):
        asset_queryset = CloudAsset.objects.select_related('environment').all()
        asset_queryset = _queryset_search(asset_queryset, ['name', 'resource_id', 'resource_type', 'region', 'vpc_name'], tokens)
        assets = list(asset_queryset.order_by('-updated_at')[:limit])
        if assets:
            sections.append({
                'title': '多云资源',
                'items': [f'{asset.name} / {asset.resource_type} / {asset.get_status_display()}' for asset in assets],
            })
            summary['cloud_assets'] = len(assets)
            citations.append({'title': '多云环境', 'path': '/multicloud'})

    if user_has_permissions(user, ['ops.iac.view']):
        stack_queryset = _queryset_search(TerraformStack.objects.all(), ['name', 'description', 'region', 'zone'], tokens)
        stacks = list(stack_queryset.order_by('-updated_at')[:4])
        if stacks:
            sections.append({
                'title': 'IaC 方案',
                'items': [f'{stack.name} / {stack.get_cloud_provider_display()} / {stack.region}' for stack in stacks],
            })
            summary['iac_stacks'] = len(stacks)
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})

    if user_has_permissions(user, ['ops.k8s.view']):
        cluster_queryset = _queryset_search(K8sCluster.objects.all(), ['name', 'api_server', 'description'], tokens)
        clusters = list(cluster_queryset.order_by('-updated_at')[:5])
        if clusters:
            sections.append({
                'title': 'K8s 集群',
                'items': [f'{cluster.name} / {cluster.get_status_display()}' for cluster in clusters],
            })
            summary['k8s_clusters'] = len(clusters)
            citations.append({'title': 'K8s 集群', 'path': '/containers/k8s'})

    if user_has_permissions(user, ['ops.docker.view']):
        docker_queryset = _queryset_search(DockerHost.objects.all(), ['name', 'ip_address', 'description'], tokens)
        docker_hosts = list(docker_queryset.order_by('-updated_at')[:5])
        if docker_hosts:
            sections.append({
                'title': 'Docker 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in docker_hosts],
            })
            summary['docker_hosts'] = len(docker_hosts)
            citations.append({'title': 'Docker 环境', 'path': '/containers/docker'})

    if user_has_permissions(user, ['ops.nginx.view']):
        nginx_queryset = _queryset_search(NginxEnvironment.objects.all(), ['name', 'ip_address', 'description'], tokens)
        nginx_envs = list(nginx_queryset.order_by('-updated_at')[:5])
        if nginx_envs:
            sections.append({
                'title': 'Nginx 环境',
                'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in nginx_envs],
            })
            summary['nginx_envs'] = len(nginx_envs)
            citations.append({'title': 'Nginx 管理', 'path': '/middleware/nginx'})

    if user_has_permissions(user, ['ops.log.datasource.view']):
        datasource_queryset = _queryset_search(LogDataSource.objects.all(), ['name', 'provider', 'description'], tokens)
        datasources = list(datasource_queryset.order_by('-updated_at')[:5])
        if datasources:
            sections.append({
                'title': '日志数据源',
                'items': [f'{item.name} / {item.get_provider_display()} / {"启用" if item.is_enabled else "停用"}' for item in datasources],
            })
            summary['log_datasources'] = len(datasources)
            citations.append({'title': '日志数据源', 'path': '/logs/datasources'})

    response_summary = {'summary': summary, 'section_count': len(sections)}
    _finish_tool_invocation(invocation, response_summary, started_at, success=bool(sections))
    return {'summary': summary, 'sections': sections, 'citations': citations}


def query_hosts(session, user_message, user, query='', environment='', status='', limit=6):
    started_at = time.time()
    environment = environment or _extract_environment(query)
    resolved_status = (status or '').strip().lower()
    if not resolved_status:
        lowered = (query or '').lower()
        if any(keyword in lowered for keyword in ['离线', 'offline']):
            resolved_status = 'offline'
        elif any(keyword in lowered for keyword in ['在线', 'online']):
            resolved_status = 'online'
    search_query = _strip_common_query_phrases(
        query,
        [
            '当前', '最近', '有哪些', '什么', '环境', '主机', '服务器', '机器',
            '生产', '测试', '开发', 'prod', 'test', 'dev',
            '离线', '在线', 'offline', 'online',
        ],
    )
    tokens = _clean_tokens(search_query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_hosts',
        {'query': query, 'environment': environment, 'status': resolved_status, 'tokens': tokens, 'limit': limit},
    )
    if not user_has_permissions(user, ['ops.host.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    queryset = Host.objects.all()
    if environment:
        queryset = queryset.filter(environment=environment)
    if resolved_status:
        queryset = queryset.filter(status=resolved_status)
    queryset = _queryset_search(queryset, ['hostname', 'ip_address', 'business_line', 'admin_user', 'description'], tokens)
    hosts = list(queryset.order_by('-updated_at', '-id')[:limit])
    sections = [{
        'title': '主机列表',
        'items': [
            f'{item.hostname} ({item.ip_address}) / {item.business_line or "未标注业务线"} / {item.get_environment_display()} / {item.get_status_display()}'
            for item in hosts
        ],
    }] if hosts else []
    summary = {'count': len(hosts), 'environment': environment, 'status': resolved_status}
    _finish_tool_invocation(invocation, summary, started_at, success=True)
    return {'summary': summary, 'sections': sections, 'citations': [{'title': '主机中心', 'path': '/hosts/assets'}], 'hosts': hosts}


def query_cost_report(session, user_message, user, query='', environment='', business_line='', month='', limit=5):
    started_at = time.time()
    environment = environment or _extract_environment(query)
    business_line = business_line or _extract_business_line(query)
    month = (month or timezone.localdate().strftime('%Y-%m')).strip()
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_cost_report',
        {'query': query, 'environment': environment, 'business_line': business_line, 'month': month, 'limit': limit},
    )
    if not user_has_permissions(user, ['cmdb.ci.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    from cmdb.views import _cost_rows_for_month

    rows = _cost_rows_for_month(month)
    filtered_rows = []
    for row in rows:
        ci = row['ci']
        if environment and ci.environment != environment:
            continue
        if business_line and ci.business_line != business_line:
            continue
        filtered_rows.append(row)

    total = sum((row['amount'] for row in filtered_rows), Decimal('0'))
    top_items = sorted(filtered_rows, key=lambda item: (-item['amount'], item['ci'].name))[:limit]
    sections = [{
        'title': '成本概览',
        'items': [
            f"月份：{month}",
            f"业务线：{business_line or '全部业务线'}",
            f"环境：{environment or '全部环境'}",
            f"月成本合计：{float(total):.2f} 元",
        ],
    }]
    if top_items:
        sections.append({
            'title': '高成本资源',
            'items': [
                f"{item['ci'].name} / {item['ci'].ci_type.name} / {float(item['amount']):.2f} 元"
                for item in top_items
            ],
        })
    summary = {
        'month': month,
        'count': len(filtered_rows),
        'environment': environment,
        'business_line': business_line,
        'total_monthly_cost': float(total),
    }
    _finish_tool_invocation(invocation, summary, started_at, success=True)
    return {'summary': summary, 'sections': sections, 'citations': [{'title': 'CMDB 成本分析', 'path': '/cmdb/cost'}], 'items': top_items}


def query_alerts(session, user_message, user, query='', level='', only_unacknowledged=False, limit=8):
    started_at = time.time()
    normalized_query, level, only_unacknowledged = _normalize_alert_query_request(query, level, only_unacknowledged)
    environment = _extract_environment(normalized_query)
    service_query = _strip_common_query_phrases(
        normalized_query,
        [
            '分析', '排查', '异常', '根因', '最近', '当前', '生产', '测试', '开发',
            'prod', 'test', 'dev', '服务', '告警', '有哪些', '是什么', '情况',
        ],
    )
    tokens = _clean_alert_query_tokens(service_query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_alerts',
        {
            'raw_query': query,
            'query': normalized_query,
            'environment': environment,
            'service_query': service_query,
            'tokens': tokens,
            'level': level,
            'only_unacknowledged': only_unacknowledged,
            'limit': limit,
        },
    )
    if not user_has_permissions(user, ['ops.alert.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'error': '当前账号无权查看告警。', 'sections': [], 'citations': []}

    queryset = Alert.objects.select_related('host').all()
    if environment:
        queryset = queryset.filter(Q(host__environment=environment) | Q(message__icontains=environment))
    if only_unacknowledged:
        queryset = queryset.filter(is_acknowledged=False)
    if level:
        queryset = queryset.filter(level=level)
    if tokens:
        queryset = _queryset_search(queryset, ['title', 'source', 'message', 'host__hostname'], tokens)
    alerts = list(queryset.order_by('-created_at')[:limit])
    counter = Counter(alert.level for alert in alerts)
    sections = [{
        'title': '告警明细',
        'items': [
            f'{alert.get_level_display()} / {alert.title} / {alert.source} / {alert.host.hostname if alert.host else "无主机关联"}'
            for alert in alerts
        ],
    }] if alerts else [{
        'title': '告警明细',
        'items': ['当前没有符合筛选条件的告警。'],
    }]
    citations = [{'title': '告警中心', 'path': '/alerts'}]
    response_summary = {
        'count': len(alerts),
        'critical': counter.get('critical', 0),
        'warning': counter.get('warning', 0),
        'info': counter.get('info', 0),
    }
    _finish_tool_invocation(invocation, response_summary, started_at, success=True)
    return {'summary': response_summary, 'sections': sections, 'citations': citations, 'alerts': alerts}


def query_events(session, user_message, user, query='', limit=8):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_events', {'query': query, 'tokens': tokens, 'limit': limit})
    if not user_has_permissions(user, ['eventwall.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = EventRecord.objects.all()
    queryset = _queryset_search(queryset, ['title', 'summary', 'resource_name', 'application', 'module'], tokens)
    events = list(queryset.order_by('-occurred_at')[:limit])
    sections = [{
        'title': '关键事件',
        'items': [f'{event.title} / {event.module} / {event.result}' for event in events],
    }] if events else []
    _finish_tool_invocation(invocation, {'count': len(events)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '事件墙', 'path': '/events/wall'}], 'events': events}


def query_logs(session, user_message, user, query='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_logs', {'query': query, 'tokens': tokens, 'limit': limit})
    allowed = user_has_permissions(user, ['ops.log.entry.view']) or user_has_permissions(user, ['ops.log.query'])
    if not allowed:
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = _queryset_search(LogEntry.objects.select_related('host').all(), ['service', 'message', 'host__hostname'], tokens)
    logs = list(queryset.order_by('-timestamp')[:limit])
    sections = [{
        'title': '相关日志',
        'items': [f'{log.get_level_display()} / {log.service} / {log.message[:80]}' for log in logs],
    }] if logs else []
    _finish_tool_invocation(invocation, {'count': len(logs)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '日志中心', 'path': '/logs/query'}], 'logs': logs}


def _extract_quoted_trace_query(query):
    text = str(query or '').strip()
    for pattern in [r'"([^"]{2,})"', r'“([^”]{2,})”', r"'([^']{2,})'", r'服务\s*([^\s，。？！,?]+)']:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return text


def _match_trace_service(services, query):
    target = _extract_quoted_trace_query(query)
    normalized_target = target.lower().strip()
    if not normalized_target:
        return None
    for service in services or []:
        values = [
            str(service.get('id') or ''),
            str(service.get('name') or ''),
            str(service.get('short_name') or service.get('shortName') or ''),
        ]
        for value in values:
            normalized_value = value.lower().strip()
            if normalized_target == normalized_value:
                return service
    for service in services or []:
        values = [
            str(service.get('id') or ''),
            str(service.get('name') or ''),
            str(service.get('short_name') or service.get('shortName') or ''),
        ]
        if any(normalized_target in value.lower() or value.lower() in normalized_target for value in values if value):
            return service
    tokens = [token.lower() for token in _clean_tokens(target)]
    if tokens:
        for service in services or []:
            haystack = ' '.join([
                str(service.get('id') or ''),
                str(service.get('name') or ''),
                str(service.get('short_name') or service.get('shortName') or ''),
            ]).lower()
            if all(token in haystack for token in tokens):
                return service
    return None


def _format_trace_item(item):
    endpoints = '、'.join((item.get('endpoint_names') or [])[:2]) or '未知 Endpoint'
    trace_id = item.get('trace_id') or ''
    short_trace_id = trace_id[:24] + '...' if len(trace_id) > 28 else trace_id
    return f"{item.get('service_name') or item.get('service_id') or '-'} / {item.get('state') or '-'} / {item.get('duration_ms') or 0}ms / {item.get('start') or '-'} / {endpoints} / {short_trace_id}"


def _query_live_traces(query='', errors_only=False, limit=6, duration_minutes=60):
    datasource = (
        TracingDataSource.objects.filter(is_enabled=True, is_default=True).order_by('id').first()
        or TracingDataSource.objects.filter(is_enabled=True).order_by('id').first()
    )
    provider = datasource.provider if datasource else ''
    datasource_id = str(datasource.id) if datasource else ''
    provider_id, config = _resolve_provider(provider, datasource_id=datasource_id)
    handlers = _provider_handlers()
    endpoint = ''
    if provider_id == 'skywalking':
        endpoint = (config.get('oap_url') or config.get('query_url') or '').strip()
    else:
        endpoint = (config.get('query_url') or '').strip()
    if endpoint:
        parsed = urlparse(endpoint)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if host:
            try:
                with socket.create_connection((host, port), timeout=3):
                    pass
            except OSError as exc:
                raise ObservabilityError(f'链路数据源不可达：{host}:{port}（{exc}）')
    if provider_id == 'demo':
        catalog = load_tracing_catalog(provider='demo')
        tracing_meta = catalog.get('tracing') or {}
        services = catalog.get('services') or []
    else:
        services = handlers[provider_id]['services'](config, layer='') if provider_id == 'skywalking' else handlers[provider_id]['services'](config)
        tracing_meta = {
            'provider': provider_id,
            'provider_name': datasource.get_provider_display() if datasource else provider_id,
            'source': provider_id,
            'datasource_id': datasource_id,
            'datasource_name': datasource.name if datasource else '',
        }
    service = _match_trace_service(services, query)
    trace_query = _extract_quoted_trace_query(query)
    payload = {
        'provider': tracing_meta.get('provider') or provider_id,
        'datasource_id': tracing_meta.get('datasource_id') or datasource_id,
        'service_id': service.get('id') if service else '',
        'keyword': '' if service else trace_query,
        'trace_state': 'ERROR' if errors_only else 'ALL',
        'duration_minutes': duration_minutes,
        'limit': limit,
    }
    if provider_id == 'demo':
        catalog = load_tracing_catalog(provider='demo')
        result = {
            'tracing': catalog.get('tracing') or tracing_meta,
            'summary': catalog.get('summary') or {},
            'traces': [item for item in (catalog.get('recent_traces') or []) if (not errors_only or item.get('is_error'))][:limit],
        }
    else:
        traces = handlers[provider_id]['search'](config, payload, services)
        result = {
            'tracing': tracing_meta,
            'summary': {
                'match_count': len(traces),
                'error_match_count': len([item for item in traces if item.get('is_error')]),
            },
            'traces': traces,
    }
    return result, service, trace_query


def _is_trace_focused_question(question):
    lowered = str(question or '').lower()
    return any(keyword in lowered for keyword in ['链路追踪', '调用链', 'trace', 'tracing'])


def query_traces(session, user_message, user, query='', errors_only=False, limit=6, duration_minutes=60):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_traces',
        {'query': query, 'tokens': tokens, 'errors_only': errors_only, 'limit': limit, 'duration_minutes': duration_minutes},
    )
    if not user_has_permissions(user, ['ops.trace.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    try:
        live_result, matched_service, trace_query = _query_live_traces(
            query=query,
            errors_only=errors_only,
            limit=limit,
            duration_minutes=duration_minutes,
        )
        traces = (live_result.get('traces') or [])[:limit]
        tracing_meta = live_result.get('tracing') or {}
        summary = live_result.get('summary') or {}
        service_name = (matched_service or {}).get('name') or trace_query or '全部服务'
        if traces:
            title = '链路追踪异常' if errors_only else '链路追踪'
            sections = [{
                'title': title,
                'items': [
                    f"服务：{service_name}；最近 {duration_minutes} 分钟匹配 {summary.get('match_count', len(traces))} 条，异常 {summary.get('error_match_count', len([item for item in traces if item.get('is_error')]))} 条。",
                    *[_format_trace_item(item) for item in traces],
                ],
            }]
        elif matched_service:
            sections = [{
                'title': '链路追踪异常' if errors_only else '链路追踪',
                'items': [f"服务：{service_name}；最近 {duration_minutes} 分钟未查询到{'异常 ' if errors_only else ''}Trace。"],
            }]
        else:
            sections = [{
                'title': '链路追踪服务未匹配',
                'items': [f"未在当前链路数据源中匹配到服务：{trace_query or query or '-'}。"],
            }]
        _finish_tool_invocation(
            invocation,
            {
                'count': len(traces),
                'match_count': summary.get('match_count', len(traces)),
                'error_match_count': summary.get('error_match_count', len([item for item in traces if item.get('is_error')])),
                'provider': tracing_meta.get('provider'),
                'datasource_id': tracing_meta.get('datasource_id'),
                'service': service_name,
            },
            started_at,
            success=True,
        )
        return {
            'sections': sections,
            'citations': [{'title': f"链路追踪 / {tracing_meta.get('provider_name') or tracing_meta.get('provider') or 'Tracing'}", 'path': '/observability/tracing'}],
            'traces': traces,
            'summary': summary,
            'service': matched_service,
            'tracing': tracing_meta,
        }
    except Exception as exc:
        if not isinstance(exc, ObservabilityError):
            error_message = str(exc)
        else:
            error_message = str(exc)
        _finish_tool_invocation(invocation, {'detail': error_message[:300]}, started_at, success=False)
        return {
            'sections': [{'title': '链路追踪查询失败', 'items': [error_message[:300]]}],
            'citations': [{'title': '链路追踪', 'path': '/observability/tracing'}],
            'traces': [],
            'error': error_message,
        }

    traces = []
    for item in DEMO_TRACES:
        haystack = ' '.join([item['trace_id'], item['service_name'], item['summary'], *item['endpoint_names']]).lower()
        if tokens and not all(token.lower() in haystack for token in tokens):
            continue
        if errors_only and not item['is_error']:
            continue
        traces.append(item)
    traces = traces[:limit]
    sections = [{
        'title': '链路追踪',
        'items': [f"{item['service_name']} / {item['state']} / {item['duration_ms']}ms / {item['summary']}" for item in traces],
    }] if traces else []
    _finish_tool_invocation(invocation, {'count': len(traces)}, started_at, success=True)
    return {'sections': sections, 'citations': [{'title': '链路追踪', 'path': '/observability/tracing'}], 'traces': traces}


def query_recent_changes(session, user_message, user, limit=5):
    started_at = time.time()
    invocation = _create_tool_invocation(session, user_message, 'query_recent_changes', {'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.deployment.view']):
        deployments = list(Deployment.objects.order_by('-deployed_at', '-executed_at', '-id')[:limit])
        if deployments:
            sections.append({
                'title': '最近发布',
                'items': [f'{item.app_name} / {item.version} / {item.get_status_display()}' for item in deployments],
            })
            citations.append({'title': '应用发布', 'path': '/deployments'})
    if user_has_permissions(user, ['ops.iac.view']):
        executions = list(TerraformExecution.objects.select_related('stack').order_by('-created_at')[:limit])
        if executions:
            sections.append({
                'title': '最近 IaC 执行',
                'items': [f'{item.stack.name} / {item.get_action_display()} / {item.get_status_display()}' for item in executions],
            })
            citations.append({'title': 'IaC 编排', 'path': '/terraform'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': citations}


def query_host_tasks(session, user_message, user, query='', status='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_host_tasks',
        {'query': query, 'tokens': tokens, 'status': status, 'limit': limit},
    )
    if not user_has_permissions(user, ['ops.host.execute']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    queryset = HostTask.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    queryset = _queryset_search(queryset, ['name', 'description', 'created_by', 'summary'], tokens)
    tasks = list(queryset.order_by('-created_at')[:limit])
    sections = [{
        'title': '任务中心',
        'items': [f'{task.name} / {task.get_status_display()} / {task.created_by}' for task in tasks],
    }] if tasks else []
    summary = {'count': len(tasks)}
    _finish_tool_invocation(invocation, summary, started_at, success=True)
    return {'summary': summary, 'sections': sections, 'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}], 'tasks': tasks}


def query_cmdb_items(session, user_message, user, query='', environment='', limit=6):
    started_at = time.time()
    tokens = _clean_cmdb_query_tokens(query)
    environment = environment or _extract_environment(query)
    invocation = _create_tool_invocation(session, user_message, 'query_cmdb_items', {'query': query, 'environment': environment, 'limit': limit})
    if not user_has_permissions(user, ['cmdb.ci.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}
    queryset = ConfigItem.objects.select_related('ci_type').all()
    if environment:
        queryset = queryset.filter(environment=environment)
    queryset = _query_cmdb_queryset(queryset, tokens)
    items = list(queryset.order_by('-updated_at')[:limit])
    serialized_items = [_serialize_cmdb_item(item) for item in items]
    sections = [{
        'title': 'CMDB 配置项',
        'items': [f"{item['name']} / {item['ci_type']} / {item['ip_address'] or item['status_display']}" for item in serialized_items],
    }] if items else []
    _finish_tool_invocation(invocation, {'count': len(items)}, started_at, success=True)
    return {
        'summary': {'count': len(serialized_items), 'tokens': tokens, 'environment': environment},
        'sections': sections,
        'citations': [{'title': 'CMDB', 'path': '/cmdb', 'query': {'tab': 'items'}}],
        'items': serialized_items,
    }


def query_observability(session, user_message, user, query='', limit=6):
    alert_payload = query_alerts(session, user_message, user, query=query, limit=limit)
    log_payload = query_logs(session, user_message, user, query=query, limit=limit)
    trace_payload = query_traces(session, user_message, user, query=query, errors_only='异常' in (query or '') or '错误' in (query or ''), limit=limit)
    change_payload = query_recent_changes(session, user_message, user, limit=4)
    sections = []
    citations = []
    for payload in [alert_payload, log_payload, trace_payload, change_payload]:
        sections.extend(payload.get('sections', []))
        citations.extend(payload.get('citations', []))
    return {'sections': sections, 'citations': _dedupe_citations(citations)}


def query_workorders(session, user_message, user, query='', status='', limit=6):
    started_at = time.time()
    environment = _extract_environment(query)
    business_line = _extract_business_line(query)
    normalized_status = (status or '').strip().lower()
    if normalized_status in {'all', 'any', '全部', '全部状态', '不限', '不限制'}:
        normalized_status = ''
    search_query = _strip_common_query_phrases(
        query,
        [
            '最近', '当前', '有哪些', '什么', '工单', '事务工单', '审批单',
            '生产', '测试', '开发', 'prod', 'test', 'dev',
            '电商线', '电商', 'commerce', '数据平台', '数据线', 'data', '基础架构', '基础设施', 'infra',
        ],
    )
    tokens = _clean_tokens(search_query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_workorders',
        {'query': query, 'status': normalized_status, 'raw_status': status, 'limit': limit, 'environment': environment, 'business_line': business_line, 'tokens': tokens},
    )
    can_view_tickets = user_has_permissions(user, ['ops.ticket.view'])
    can_view_deployments = user_has_permissions(user, ['ops.deployment.view'])
    if not can_view_tickets and not can_view_deployments:
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    tickets = []
    deployments = []
    sections = []
    citations = []

    if can_view_tickets:
        queryset = TransactionTicket.objects.all()
        if normalized_status:
            queryset = queryset.filter(status=normalized_status)
        if environment:
            queryset = queryset.filter(environment=environment)
        if business_line:
            queryset = queryset.filter(business_line=business_line)
        queryset = _queryset_search(queryset, ['title', 'description', 'applicant', 'business_line', 'owner'], tokens)
        tickets = list(queryset.order_by('-updated_at')[:limit])
        if tickets:
            sections.append({
                'title': '事务工单',
                'items': [
                    f'{item.title} / {item.business_line or "未标注业务线"} / {item.get_environment_display() if item.environment else "全部环境"} / {item.get_status_display()}'
                    for item in tickets
                ],
            })
            citations.append({'title': '工单系统', 'path': '/workorders'})

    if can_view_deployments:
        deployment_queryset = Deployment.objects.select_related('docker_host', 'cluster', 'host').all()
        if environment:
            deployment_queryset = deployment_queryset.filter(environment=environment)
        if business_line:
            deployment_queryset = deployment_queryset.filter(business_line=business_line)
        if normalized_status:
            deployment_queryset = deployment_queryset.filter(Q(status=normalized_status) | Q(approval_status=normalized_status))
        deployment_queryset = _queryset_search(
            deployment_queryset,
            ['app_name', 'version', 'image', 'submitter', 'approver', 'change_summary', 'description', 'business_line'],
            tokens,
        )
        deployments = list(deployment_queryset.order_by('-deployed_at', '-id')[:limit])
        if deployments:
            sections.append({
                'title': '应用发布',
                'items': [
                    f'{item.app_name} {item.version} / {item.business_line or "未标注业务线"} / {item.get_environment_display()} / {item.get_approval_status_display()} / {item.get_status_display()}'
                    for item in deployments
                ],
            })
            citations.append({'title': '应用发布', 'path': '/deployments'})

    summary = {
        'count': len(tickets) + len(deployments),
        'ticket_count': len(tickets),
        'deployment_count': len(deployments),
        'environment': environment,
        'business_line': business_line,
    }
    _finish_tool_invocation(invocation, summary, started_at, success=True)
    return {
        'summary': summary,
        'sections': sections,
        'citations': _dedupe_citations(citations),
        'tickets': tickets,
        'deployments': deployments,
    }


def query_task_center(session, user_message, user, query='', status='', limit=6):
    return query_host_tasks(session, user_message, user, query=query, status=status, limit=limit)


def query_event_wall(session, user_message, user, query='', limit=8):
    return query_events(session, user_message, user, query=query, limit=limit)


def query_container_assets(session, user_message, user, query='', limit=6):
    started_at = time.time()
    lowered_query = (query or '').lower()
    if any(keyword in lowered_query for keyword in ['pod', 'pods', '异常pod', '异常的pod', '异常 pod']):
        return query_k8s_cluster_summary(session, user_message, user, query=query, limit=1)

    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_container_assets', {'query': query, 'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.k8s.view']):
        clusters = list(_queryset_search(K8sCluster.objects.all(), ['name', 'api_server', 'description'], tokens).order_by('-updated_at')[:limit])
        if clusters:
            sections.append({'title': 'Kubernetes 集群', 'items': [f'{item.name} / {item.get_status_display()}' for item in clusters]})
            citations.append({'title': 'K8s 集群', 'path': '/containers/k8s'})
    if user_has_permissions(user, ['ops.docker.view']):
        hosts = list(_queryset_search(DockerHost.objects.all(), ['name', 'ip_address', 'description'], tokens).order_by('-updated_at')[:limit])
        if hosts:
            sections.append({'title': 'Docker 主机', 'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in hosts]})
            citations.append({'title': 'Docker 环境', 'path': '/containers/docker'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': citations}


def query_k8s_cluster_summary(session, user_message, user, query='', cluster_name='', limit=1):
    started_at = time.time()
    cluster_query = cluster_name or _strip_common_query_phrases(
        query,
        ['有没有', '是否', '异常', 'pod', 'Pod', '集群', 'k8s', 'K8s', 'Kubernetes', '的', '吗', '情况'],
    )
    tokens = _clean_tokens(cluster_query)
    invocation = _create_tool_invocation(
        session,
        user_message,
        'query_k8s_cluster_summary',
        {'query': query, 'cluster_name': cluster_name, 'cluster_query': cluster_query, 'tokens': tokens, 'limit': limit},
    )
    if not user_has_permissions(user, ['ops.k8s.view']):
        _finish_tool_invocation(invocation, {'detail': 'missing_permission'}, started_at, success=False)
        return {'sections': [], 'citations': []}

    queryset = K8sCluster.objects.all()
    if cluster_name:
        queryset = queryset.filter(name__icontains=cluster_name)
    elif tokens:
        queryset = _queryset_search(queryset, ['name', 'api_server', 'description'], tokens)
    cluster = queryset.order_by('-updated_at', '-id').first()
    if not cluster:
        _finish_tool_invocation(invocation, {'count': 0}, started_at, success=True)
        return {'summary': {'count': 0}, 'sections': [], 'citations': [{'title': 'K8s 集群', 'path': '/containers/k8s'}]}

    from ops.k8s_views import _build_demo_summary, _build_live_summary, _is_demo

    summary_payload = _build_demo_summary(cluster) if _is_demo(cluster) else _build_live_summary(cluster)
    sections = [{
        'title': '集群概览',
        'items': [
            f"{cluster.name} / 状态 {summary_payload.get('status')}",
            f"异常 Pod：{summary_payload.get('pods_abnormal', 0)} / 重启 Pod：{summary_payload.get('pods_restarting', 0)} / 总重启次数：{summary_payload.get('total_restarts', 0)}",
            f"副本未就绪工作负载：{summary_payload.get('workloads_degraded', 0)} / 待绑定 PVC：{summary_payload.get('pvcs_pending', 0)}",
        ],
    }]
    alerts = summary_payload.get('alerts') or []
    if alerts:
        sections.append({
            'title': '异常摘要',
            'items': [f"{item.get('level')} / {item.get('message')}" for item in alerts[:limit + 2]],
        })
    tool_summary = {
        'count': 1,
        'cluster_name': cluster.name,
        'pods_abnormal': summary_payload.get('pods_abnormal', 0),
        'pods_restarting': summary_payload.get('pods_restarting', 0),
        'workloads_degraded': summary_payload.get('workloads_degraded', 0),
    }
    _finish_tool_invocation(invocation, tool_summary, started_at, success=True)
    return {'summary': tool_summary, 'sections': sections, 'citations': [{'title': 'K8s 集群', 'path': '/containers/k8s'}], 'cluster': summary_payload}


def query_middleware_assets(session, user_message, user, query='', limit=6):
    started_at = time.time()
    tokens = _clean_tokens(query)
    invocation = _create_tool_invocation(session, user_message, 'query_middleware_assets', {'query': query, 'limit': limit})
    sections = []
    citations = []
    if user_has_permissions(user, ['ops.nginx.view']):
        nginx_envs = list(_queryset_search(NginxEnvironment.objects.all(), ['name', 'ip_address', 'description'], tokens).order_by('-updated_at')[:limit])
        if nginx_envs:
            sections.append({'title': 'Nginx 环境', 'items': [f'{item.name} ({item.ip_address}) / {item.get_status_display()}' for item in nginx_envs]})
            citations.append({'title': 'Nginx 管理', 'path': '/middleware/nginx'})
    if user_has_permissions(user, ['ops.middleware.view']):
        payload = build_middleware_payload(get_middleware_demo_state())
        redis_summary = payload.get('redis', {}).get('summary', {})
        rocketmq_summary = payload.get('rocketmq', {}).get('summary', {})
        es_summary = payload.get('elasticsearch', {}).get('summary', {})
        sections.append({
            'title': '中间件概览',
            'items': [
                f"Redis / 集群 {redis_summary.get('cluster_count', 0)} / 告警 {redis_summary.get('warning_count', 0)}",
                f"RocketMQ / 集群 {rocketmq_summary.get('cluster_count', 0)} / 告警 {rocketmq_summary.get('warning_count', 0)}",
                f"Elasticsearch / 集群 {es_summary.get('cluster_count', 0)} / 告警 {es_summary.get('warning_count', 0)}",
            ],
        })
        citations.append({'title': '中间件', 'path': '/middleware/manage'})
    _finish_tool_invocation(invocation, {'section_count': len(sections)}, started_at, success=True)
    return {'sections': sections, 'citations': _dedupe_citations(citations)}


def build_markdown_answer(title, sections, citations, intro=''):
    lines = []
    if intro:
        lines.append(intro)
        lines.append('')
    if title:
        lines.append(f'**{title}**')
    for section in sections:
        lines.append(f"- {section['title']}")
        for item in section.get('items', []):
            lines.append(f'  {item}')
    if citations:
        lines.append('')
        lines.append(_format_followup_line(item['title'] for item in _dedupe_citations(citations)))
    return '\n'.join(lines).strip()


def _normalize_followup_titles(values):
    titles = []
    seen = set()

    def clean_title_part(value):
        part = str(value or '').strip(' 。，；;、')
        if not part:
            return ''
        markdown_link = re.match(r'^\[([^\]]+)\]\((?:/|https?://)[^)]+\)$', part)
        if markdown_link:
            part = markdown_link.group(1).strip()
        inline_code_route = re.match(r'^([^:：]+)\s*[:：]\s*`((?:/|https?://)[^`]+)`$', part)
        if inline_code_route:
            part = inline_code_route.group(1).strip()
        route_suffix = re.match(r'^([^:：]+)\s*[:：]\s*(?:/|https?://).+$', part)
        if route_suffix:
            part = route_suffix.group(1).strip()
        parenthesized_route = re.match(r'^(.+?)\s*[（(]\s*(?:/|https?://)[^)）]+\s*[)）]$', part)
        if parenthesized_route:
            part = parenthesized_route.group(1).strip()
        return part.strip(' 。，；;、')

    for value in values or []:
        text = str(value or '').strip()
        if not text:
            continue
        text = re.sub(r'^\s*(?:[-*+]\s+|\d+\.\s+)?', '', text)
        text = text.replace('：', ':')
        if ':' in text:
            prefix, suffix = text.split(':', 1)
            if prefix.strip() in {'可继续查看', '延伸查看', '相关入口'}:
                text = suffix.strip()
        parts = [
            clean_title_part(part)
            for part in re.split(r'[、，,；;]\s*', text)
            if clean_title_part(part)
        ]
        if not parts:
            parts = [clean_title_part(text)]
        for part in parts:
            if not part or part in seen:
                continue
            seen.add(part)
            titles.append(part)
    return titles


def _format_followup_line(values):
    titles = _normalize_followup_titles(values)
    if not titles:
        return '可继续查看：相关平台入口。'
    return '可继续查看：' + '、'.join(titles) + '。'


def _ensure_followup_line(content, citations=None):
    text = _normalize_formatter_output(content)
    if not citations:
        return text
    followup_line = _format_followup_line(item.get('title') for item in _dedupe_citations(citations))
    lines = [line for line in text.splitlines()]
    followup_indexes = [index for index, line in enumerate(lines) if str(line or '').strip().startswith('可继续查看：')]
    if not followup_indexes:
        if lines and lines[-1].strip():
            lines.append('')
        lines.append(followup_line)
        return '\n'.join(lines).strip()
    first_index = followup_indexes[0]
    lines[first_index] = followup_line
    for index in reversed(followup_indexes[1:]):
        lines.pop(index)
    return '\n'.join(lines).strip()


def _find_skill_by_slug(skills, slug):
    for skill in skills or []:
        if getattr(skill, 'slug', '') == slug:
            return skill
    return None


def _extract_analysis_subject(question=''):
    raw = (question or '').strip().strip('。？！!?')
    patterns = [
        r'分析\s*(.+?)\s*最近异常',
        r'分析\s*(.+?)\s*异常',
        r'排查\s*(.+?)\s*最近异常',
        r'排查\s*(.+?)\s*异常',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(' ：:，,。')
            if value:
                return value
    return ''


def _collect_alert_context(collected_tool_outputs, sections):
    entries = []
    sources = Counter()
    hosts = Counter()
    title_counter = Counter()
    total_count = 0

    for item in collected_tool_outputs or []:
        if item.get('tool_name') != 'query_alerts':
            continue
        tool_output = item.get('tool_output') or {}
        alerts = tool_output.get('alerts') or []
        summary = tool_output.get('summary') or {}
        try:
            total_count = max(total_count, int(summary.get('count', len(alerts))))
        except (TypeError, ValueError):
            total_count = max(total_count, len(alerts))
        for alert in alerts:
            host_name = alert.host.hostname if getattr(alert, 'host', None) else '无主机关联'
            line = f'{alert.get_level_display()} / {alert.title} / {alert.source} / {host_name}'
            entries.append(line)
            sources[alert.source] += 1
            hosts[host_name] += 1
            title_counter[alert.title] += 1

    if not entries:
        for section in sections or []:
            if section.get('title') == '告警明细':
                entries.extend(section.get('items') or [])
        if entries:
            total_count = len(entries)
            for line in entries:
                parts = [item.strip() for item in line.split('/')]
                if len(parts) >= 4:
                    title_counter[parts[1]] += 1
                    sources[parts[2]] += 1
                    hosts[parts[3]] += 1

    return {
        'count': total_count or len(entries),
        'entries': entries,
        'sources': sources,
        'hosts': hosts,
        'titles': title_counter,
    }


def _summarize_alert_focus(alert_context):
    focus = []
    titles = list((alert_context.get('titles') or Counter()).keys())
    source_names = list((alert_context.get('sources') or Counter()).keys())
    raw_text = ' '.join([*titles, *source_names])
    mapping = [
        ('Deployment', 'K8s Deployment 可用性或发布状态'),
        ('超时', '调用超时'),
        ('重试', '依赖重试风暴'),
        ('磁盘', '磁盘容量风险'),
        ('CPU', 'CPU 负载升高'),
        ('Prometheus', '监控指标持续越阈'),
        ('Zabbix', '基础设施容量或主机风险'),
        ('APM', '应用链路异常'),
    ]
    for keyword, label in mapping:
        if keyword in raw_text and label not in focus:
            focus.append(label)
    return focus[:4]


def _build_alert_suggestions(question, alert_context):
    suggestions = []
    titles_text = ' '.join((alert_context.get('titles') or Counter()).keys())
    sources = set((alert_context.get('sources') or Counter()).keys())
    subject = _extract_analysis_subject(question)
    if 'Deployment' in titles_text:
        suggestions.append('优先检查相关 Deployment 的副本数、事件、滚动发布进度与 Pod 就绪状态。')
    if any(keyword in titles_text for keyword in ['超时', '重试']):
        target = subject or '相关服务'
        suggestions.append(f'重点排查 {target} 的下游依赖、连接池、超时阈值与错误重试情况。')
    if 'Prometheus' in sources:
        suggestions.append('结合 Prometheus 指标看近 15~30 分钟错误率、延迟、资源利用率和告警触发窗口。')
    if 'Zabbix' in sources or '磁盘' in titles_text or 'CPU' in titles_text:
        suggestions.append('对主机类严重告警优先确认容量与负载变化，必要时立即派单并保留排障证据。')
    if not suggestions:
        suggestions.append('优先确认告警影响范围、最近变更窗口与关联资源状态，并安排后续排障。')
    return suggestions[:4]


def _build_alert_structured_answer(question, sections, citations, collected_tool_outputs):
    alert_context = _collect_alert_context(collected_tool_outputs, sections)
    if not alert_context.get('entries'):
        return ''

    count = alert_context.get('count') or len(alert_context.get('entries') or [])
    focus = _summarize_alert_focus(alert_context)
    subject = _extract_analysis_subject(question)

    lines = ['结论：']
    if '异常' in (question or '') or '分析' in (question or ''):
        target = subject or '目标服务'
        base = f'已定位到 {target} 的近期异常：发现 {count} 条相关告警。'
        if focus:
            base += '异常点主要集中在' + '、'.join(focus) + '。'
        lines.append(base)
    else:
        base = f'当前未确认的严重告警共 {count} 条。'
        if focus:
            base += '风险主要集中在' + '、'.join(focus) + '。'
        lines.append(base)

    lines.append('依据：')
    lines.append('告警明细')
    for item in alert_context.get('entries', [])[:8]:
        lines.append(f'- {item}')

    suggestions = _build_alert_suggestions(question, alert_context)
    if suggestions:
        lines.append('建议操作：')
        for item in suggestions:
            lines.append(f'- {item}')

    if citations:
        lines.append(_format_followup_line(item['title'] for item in _dedupe_citations(citations)))
    return '\n'.join(lines).strip()


def _should_prefer_structured_alert_answer(content, structured_answer, collected_tool_outputs):
    if not structured_answer or not _collect_alert_context(collected_tool_outputs, []).get('entries'):
        return False
    text = _normalize_formatter_output(content)
    if not text:
        return True
    required_markers = [['结论：'], ['依据：'], ['建议操作：']]
    if any(not _has_any_heading(text, marker_aliases) for marker_aliases in required_markers):
        return True
    alert_context = _collect_alert_context(collected_tool_outputs, [])
    alert_titles = list(alert_context.get('titles', Counter()).keys())[:2]
    alert_hosts = list(alert_context.get('hosts', Counter()).keys())[:2]
    alert_sources = list(alert_context.get('sources', Counter()).keys())[:2]
    if alert_titles and not any(title in text for title in alert_titles):
        if not any(host in text for host in alert_hosts) and not any(source in text for source in alert_sources):
            return True
    if '告警明细' not in text and '异常明细' not in text and not any(line.strip().startswith('- ') for line in text.splitlines()):
        return True
    return False


def _build_fallback_answer(sections, citations, pending_action_draft=None, question='', collected_tool_outputs=None):
    structured_alert_answer = _build_alert_structured_answer(question, sections, citations, collected_tool_outputs or [])
    if structured_alert_answer:
        return structured_alert_answer
    intro = '已通过已启用的 MCP 与 Skills 获取平台内能力结果。'
    if pending_action_draft:
        intro = '已生成任务草稿，确认后将在任务中心创建或执行对应任务。'
    return build_markdown_answer('智能助手回复', sections, citations, intro=intro)


def _detect_formatter_profile(question, pending_action_draft, message_type, collected_tool_outputs=None):
    text = (question or '').strip()
    alert_context = _collect_alert_context(collected_tool_outputs or [], [])
    if pending_action_draft or message_type == AIOpsChatMessage.TYPE_ACTION:
        return 'task'
    if alert_context.get('entries'):
        if any(keyword in text for keyword in ['异常', '分析', '排查', '根因']):
            return 'incident'
        return 'alerts'
    if any(keyword in text for keyword in ['异常', '分析', '排查', '根因']):
        return 'incident'
    return 'general'


def _formatter_template_for_profile(profile):
    templates = {
        'alerts': '\n'.join([
            '必须按以下结构输出：',
            '结论：',
            '一句话先说清数量、范围和主要风险。',
            '依据：',
            '先写“告警明细”，再列出 3~8 条关键事实。',
            '建议操作：',
            '给出 2~4 条可执行建议。',
            '可继续查看：',
            '列出相关平台入口。',
        ]),
        'incident': '\n'.join([
            '必须按以下结构输出：',
            '结论：',
            '先写“已定位到 目标服务 的近期异常：发现 N 条相关告警/异常”，再概括主要异常面。',
            '依据：',
            '先写“告警明细”或“异常明细”，再列出 3~8 条关键事实。',
            '建议操作：',
            '给出 3~4 条排障建议，优先写最近变更、依赖排查、日志/链路定位。',
            '可继续查看：',
            '列出相关平台入口。',
        ]),
        'task': '\n'.join([
            '必须按以下结构输出：',
            '结论：',
            '明确当前是任务草稿、待确认创建，还是已在任务中心创建待执行任务。',
            '执行概要：',
            '列出目标主机、任务类型、执行方式、风险等级。',
            '下一步：',
            '说明用户接下来要确认、查看或执行什么。',
            '可继续查看：',
            '列出任务中心或相关平台入口。',
        ]),
        'general': '\n'.join([
            '必须按以下结构输出：',
            '结论：',
            '先给一句明确结论。',
            '关键点：',
            '列出 2~5 条事实。',
            '建议：',
            '列出 1~3 条建议。',
            '可继续查看：',
            '列出相关平台入口。',
        ]),
    }
    return templates.get(profile, templates['general'])


def _formatter_example_for_profile(profile):
    examples = {
        'alerts': '\n'.join([
            '示例输出：',
            '结论：当前未确认的严重告警共 3 条，风险主要集中在 K8s Deployment 可用性与核心服务依赖超时。',
            '依据：',
            '告警明细',
            '- 严重 / payment-worker Deployment 副本不可用 / Prometheus / k8s-node-01',
            '- 严重 / order-center 库存校验超时 / APM / order-api-ecs-01',
            '建议操作：',
            '- 优先检查 Deployment 副本状态、事件与最近发布变更。',
            '- 结合链路与日志确认下游依赖超时范围。',
            '可继续查看：告警中心、链路追踪',
        ]),
        'incident': '\n'.join([
            '示例输出：',
            '结论：已定位到 order-center 的近期异常：发现 4 条相关告警。异常点主要集中在库存校验链路超时与发布后可用性下降。',
            '依据：',
            '告警明细',
            '- 严重 / order-center 库存校验超时 / APM / order-api-ecs-01',
            '- 严重 / order-center 下游依赖重试激增 / APM / order-api-ecs-02',
            '建议操作：',
            '- 优先核对最近发布记录与异常时间窗是否重叠。',
            '- 检查 inventory-service 的耗时、错误率与连接池状态。',
            '- 结合链路追踪定位超时 Span 与失败调用。',
            '可继续查看：告警中心、日志中心、链路追踪',
        ]),
        'task': '\n'.join([
            '示例输出：',
            '结论：已生成 Redis 巡检任务草稿，当前待你确认后再在任务中心创建待执行任务。',
            '执行概要：',
            '- 目标主机：order-api-ecs-02（10.10.1.11）',
            '- 任务类型：巡检任务',
            '- 执行方式：远程命令',
            '- 风险等级：低',
            '下一步：确认任务范围与命令内容，确认后将在任务中心创建 1 条待执行任务。',
            '可继续查看：任务中心',
        ]),
        'general': '\n'.join([
            '示例输出：',
            '结论：已定位到你关注的对象，并汇总了当前最关键的信息。',
            '关键点：',
            '- 当前结果来自已启用的 MCP 工具。',
            '- 已提取最关键的对象、状态与数量。',
            '建议：',
            '- 先查看相关平台页面确认详情。',
            '可继续查看：相关平台入口',
        ]),
    }
    return examples.get(profile, examples['general'])


def _build_formatter_fact_digest(collected_tool_outputs, citations=None, pending_action_draft=None):
    lines = []
    alert_context = _collect_alert_context(collected_tool_outputs or [], citations or [])
    if alert_context.get('entries'):
        lines.append(f"- 告警事实：共 {alert_context.get('count') or len(alert_context.get('entries') or [])} 条相关告警。")
        titles = list((alert_context.get('titles') or Counter()).keys())[:3]
        if titles:
            lines.append(f"- 关键告警：{'；'.join(titles)}")
        hosts = list((alert_context.get('hosts') or Counter()).keys())[:3]
        if hosts:
            lines.append(f"- 涉及主机：{'、'.join(hosts)}")
        sources = list((alert_context.get('sources') or Counter()).keys())[:3]
        if sources:
            lines.append(f"- 告警来源：{'、'.join(sources)}")
    if pending_action_draft:
        target_hosts = pending_action_draft.get('target_hosts') or []
        lines.append(f"- 任务事实：目标主机 {pending_action_draft.get('host_count') or len(target_hosts)} 台，任务类型 {pending_action_draft.get('task_type') or '未说明'}。")
        if target_hosts:
            host_labels = [f"{item.get('hostname')}({item.get('ip_address')})" for item in target_hosts[:3]]
            lines.append(f"- 任务目标：{'、'.join(host_labels)}")
    if citations:
        lines.append(f"- 相关入口：{'、'.join(item.get('title') for item in _dedupe_citations(citations)[:4] if item.get('title'))}")
    return '\n'.join(lines) if lines else '- 当前没有额外摘要，请严格依据事实对象输出。'


def _build_answer_formatter_messages(question, draft_content, sections, citations, tool_calls, pending_action_draft, message_type, formatter_skill, active_skills, collected_tool_outputs=None, attempt=1, previous_issue='', reference_answer=''):
    skill_lines = [f"- {skill.name}：{skill.content}" for skill in active_skills or []]
    profile = _detect_formatter_profile(question, pending_action_draft, message_type, collected_tool_outputs=collected_tool_outputs)
    facts = {
        'question': question or '',
        'draft_answer': draft_content or '',
        'sections': sections or [],
        'citations': citations or [],
        'tool_calls': tool_calls or [],
        'message_type': message_type or AIOpsChatMessage.TYPE_TEXT,
        'pending_action_draft': pending_action_draft or None,
        'formatter_profile': profile,
    }
    required_headings = {
        'alerts': '结论：/ 依据：/ 建议操作：/ 可继续查看：',
        'incident': '结论：/ 依据：/ 建议操作：/ 可继续查看：',
        'task': '结论：/ 执行概要：/ 下一步：/ 可继续查看：',
        'general': '结论：/ 关键点：/ 建议：/ 可继续查看：',
    }.get(profile, '结论：/ 关键点：/ 建议：/ 可继续查看：')
    system_prompt = '\n'.join([
        '你是 AIOps 智能助手的二阶段回答整形器。',
        '你的职责是基于 MCP 工具事实、回答草稿和 Skill 模板，生成最终给用户看的中文答案。',
        '禁止编造工具未返回的事实；禁止省略关键对象、数量、状态、风险和下一步。',
        '如果事实不足，要明确说明“当前工具结果未覆盖该信息”。',
        '如果涉及任务生成：必须明确区分“任务草稿 / 待确认创建 / 已在任务中心创建待执行任务”，不能混淆为已执行完成。',
        '输出保持简洁、结构化、可读，优先使用短标题和项目符号，不要输出你的推理过程。',
        '所有问答默认都应输出结构化结果，不要只写一两句泛化描述。',
        f'本轮必须包含这些一级标题：{required_headings}',
        '一级标题请直接用纯文本，不要用 #、##、###、**标题** 代替。',
        '如果有告警或任务事实，必须把数量、对象、状态写进结论或依据，不要只写“已定位”“已查询到”。',
        _formatter_template_for_profile(profile),
        _formatter_example_for_profile(profile),
        f"回答整形 Skill：{formatter_skill.content if formatter_skill else '未配置'}",
        '当前启用 Skill：',
        '\n'.join(skill_lines) if skill_lines else '- 无',
    ])
    user_prompt = '\n'.join([
        '请基于下面事实整形最终回答：',
        json.dumps(facts, ensure_ascii=False, default=_json_default, indent=2),
        '额外事实摘要：',
        _build_formatter_fact_digest(collected_tool_outputs or [], citations=citations, pending_action_draft=pending_action_draft),
        f'当前是第 {attempt} 次整形。',
        (f'上一次整形存在的问题：{previous_issue}' if previous_issue else '请直接给出高质量最终回答。'),
        ('请严格按要求输出完整结构，不要解释格式，不要输出“好的/如下”。' if attempt == 1 else '这是修复重写，请严格保留要求的一级标题，并补全缺失事实。'),
        (f'参考结构化答案草稿（仅作结构参考，不要照抄，请基于事实重新组织输出）：\n{reference_answer}' if reference_answer else ''),
    ])
    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]


def _content_conflicts_with_tool_facts(content, collected_tool_outputs):
    text = _normalize_formatter_output(_sanitize_assistant_content(content))
    if not text:
        return False
    compact = re.sub(r'\s+', '', text)
    negative_patterns = [
        '0条',
        '暂无',
        '未查到',
        '没有严重告警',
        '没有未确认',
        '当前无告警',
    ]
    positive_count_match = re.search(r'([1-9]\d*)条', compact)

    for item in collected_tool_outputs or []:
        if item.get('tool_name') != 'query_alerts':
            continue
        tool_output = item.get('tool_output') or {}
        summary = tool_output.get('summary') or {}
        alerts = tool_output.get('alerts') or []
        try:
            count = int(summary.get('count', len(alerts)))
        except (TypeError, ValueError):
            count = len(alerts)
        if count > 0 and any(pattern in compact for pattern in negative_patterns):
            return True
        if count == 0 and positive_count_match and '告警' in compact:
            return True
    return False


def _normalize_formatter_output(content):
    text = _sanitize_assistant_content(content)
    if not text:
        return ''

    heading_aliases = {
        '结论：': ['结论'],
        '依据：': ['依据', '证据', '事实依据'],
        '建议操作：': ['建议操作', '建议', '处理建议'],
        '执行概要：': ['执行概要', '任务概要', '执行计划'],
        '下一步：': ['下一步', '后续动作', '后续建议'],
        '可继续查看：': ['可继续查看', '延伸查看', '相关入口'],
        '关键点：': ['关键点', '关键信息', '要点'],
    }

    def normalize_line(line):
        stripped = line.strip()
        if not stripped:
            return ''
        plain = re.sub(r'^\s*(?:[-*+]\s+)?(?:#{1,6}\s+)?', '', stripped)
        plain = plain.replace('**', '').replace('__', '').strip()
        for canonical, aliases in heading_aliases.items():
            for alias in aliases:
                match = re.match(rf'^{re.escape(alias)}\s*[：:]?\s*(.*)$', plain)
                if match:
                    tail = (match.group(1) or '').strip()
                    return canonical if not tail else f'{canonical}{tail}'
        return line

    normalized_lines = [normalize_line(line) for line in text.splitlines()]
    collapsed_lines = []
    canonical_headings = set(heading_aliases.keys())
    index = 0
    while index < len(normalized_lines):
        current = (normalized_lines[index] or '').strip()
        if current.startswith('可继续查看：'):
            followup_values = []
            inline_value = current[len('可继续查看：'):].strip()
            if inline_value:
                followup_values.append(inline_value)
            cursor = index + 1
            while cursor < len(normalized_lines):
                candidate = (normalized_lines[cursor] or '').strip()
                if not candidate:
                    cursor += 1
                    continue
                if any(
                    candidate == heading or candidate.startswith(heading)
                    for heading in canonical_headings
                    if heading != '可继续查看：'
                ):
                    break
                followup_values.append(candidate)
                cursor += 1
            collapsed_lines.append(_format_followup_line(followup_values))
            index = cursor
            continue
        collapsed_lines.append(normalized_lines[index])
        index += 1
    normalized = '\n'.join(collapsed_lines).strip()
    return re.sub(r'\n{3,}', '\n\n', normalized)


def _has_any_heading(text, aliases):
    normalized = _normalize_formatter_output(text)
    if not normalized:
        return False
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    for line in lines:
        for alias in aliases:
            if line == alias or line.startswith(alias):
                return True
    return False


def _count_present_headings(text, aliases_list):
    return sum(1 for aliases in aliases_list if _has_any_heading(text, aliases))


def _missing_required_headings(text, profile):
    required_markers = {
        'alerts': [('结论：', ['结论：']), ('依据：', ['依据：']), ('建议操作：', ['建议操作：']), ('可继续查看：', ['可继续查看：'])],
        'incident': [('结论：', ['结论：']), ('依据：', ['依据：']), ('建议操作：', ['建议操作：']), ('可继续查看：', ['可继续查看：'])],
        'task': [('结论：', ['结论：']), ('执行概要：', ['执行概要：']), ('下一步：', ['下一步：']), ('可继续查看：', ['可继续查看：'])],
        'general': [('结论：', ['结论：']), ('关键点：', ['关键点：']), ('建议：', ['建议操作：']), ('可继续查看：', ['可继续查看：'])],
    }.get(profile, [('结论：', ['结论：'])])
    missing = []
    for label, aliases in required_markers:
        if not _has_any_heading(text, aliases):
            missing.append(label)
    return missing


def _is_formatted_answer_valid(content, *, pending_action_draft=None, message_type=AIOpsChatMessage.TYPE_TEXT, profile='general'):
    text = _normalize_formatter_output(content)
    if not text:
        return False
    compact = re.sub(r'\s+', '', text)
    if len(compact) < 24:
        return False
    required_markers = {
        'alerts': [['结论：'], ['依据：'], ['建议操作：']],
        'incident': [['结论：'], ['依据：'], ['建议操作：']],
        'task': [['结论：'], ['执行概要：'], ['下一步：']],
        'general': [['结论：']],
    }.get(profile, [['结论：']])
    if any(not _has_any_heading(text, marker_aliases) for marker_aliases in required_markers):
        return False
    if pending_action_draft or message_type == AIOpsChatMessage.TYPE_ACTION:
        if not any(keyword in text for keyword in ['任务', '草稿', '确认', '待执行', '任务中心']):
            return False
    elif _count_present_headings(text, [['结论：'], ['依据：'], ['建议操作：'], ['关键点：'], ['可继续查看：']]) < 2:
        return False
    elif not any(token in text for token in ['- ', '1.', '2.', '可继续查看', '建议操作：', '关键点：', '依据：']):
        return False
    return True


def _formatter_repair_issue(content, *, fallback_content='', collected_tool_outputs=None, pending_action_draft=None, message_type=AIOpsChatMessage.TYPE_TEXT, profile='general'):
    if _content_conflicts_with_tool_facts(content, collected_tool_outputs or []):
        return '回答内容与工具事实冲突，请严格按工具事实重写。'
    if not _is_formatted_answer_valid(content, pending_action_draft=pending_action_draft, message_type=message_type, profile=profile):
        text = _normalize_formatter_output(content)
        missing = _missing_required_headings(text, profile)
        details = []
        if missing:
            details.append('缺少标题：' + '、'.join(missing))
        if text and not any(token in text for token in ['- ', '1.', '2.']):
            details.append('缺少列表化事实或建议项')
        if pending_action_draft and text and not any(keyword in text for keyword in ['任务', '草稿', '确认', '待执行', '任务中心']):
            details.append('缺少任务状态说明')
        if not details:
            details.append('结构不完整或信息过少')
        return '输出不够结构化，请重写并修复：' + '；'.join(details) + '。'
    if _should_prefer_structured_alert_answer(content, fallback_content, collected_tool_outputs or []):
        return '告警类回答缺少关键告警事实或结构不完整，请参考结构化草稿重写。'
    return ''


def _run_answer_formatter(provider, *, question, draft_content, sections, citations, tool_calls, pending_action_draft, message_type, active_skills, collected_tool_outputs=None):
    formatter_skill = _find_skill_by_slug(active_skills, ANSWER_FORMATTER_SKILL_SLUG)
    fallback_content = _build_fallback_answer(
        sections,
        citations,
        pending_action_draft=pending_action_draft,
        question=question,
        collected_tool_outputs=collected_tool_outputs or [],
    )
    if not formatter_skill:
        return {
            'used': False,
            'content': draft_content or fallback_content,
            'fallback_content': fallback_content,
            'reason': 'formatter_skill_disabled',
        }

    profile = _detect_formatter_profile(question, pending_action_draft, message_type, collected_tool_outputs=collected_tool_outputs)
    previous_issue = ''
    for attempt in [1, 2, 3]:
        messages = _build_answer_formatter_messages(
            question=question,
            draft_content=draft_content,
            sections=sections,
            citations=citations,
            tool_calls=tool_calls,
            pending_action_draft=pending_action_draft,
            message_type=message_type,
            formatter_skill=formatter_skill,
            active_skills=active_skills,
            collected_tool_outputs=collected_tool_outputs,
            attempt=attempt,
            previous_issue=previous_issue,
            reference_answer=fallback_content if attempt >= 2 else '',
        )
        completion = _request_model_completion(provider, {
            'model': provider.default_model,
            'temperature': min(provider.temperature or 0.2, 0.2),
            'max_tokens': provider.max_tokens,
            'messages': messages,
        })
        choice = ((completion or {}).get('choices') or [{}])[0]
        message = choice.get('message') or {}
        content = _normalize_formatter_output(_extract_message_content(message))
        previous_issue = _formatter_repair_issue(
            content,
            fallback_content=fallback_content,
            collected_tool_outputs=collected_tool_outputs,
            pending_action_draft=pending_action_draft,
            message_type=message_type,
            profile=profile,
        )
        if previous_issue:
            continue
        return {
            'used': True,
            'content': content,
            'fallback_content': fallback_content,
            'fell_back': False,
            'reason': 'formatted',
            'attempts': attempt,
        }

    return {
        'used': True,
        'content': fallback_content,
        'fallback_content': fallback_content,
        'fell_back': True,
        'reason': 'invalid_formatter_output',
        'attempts': 3,
    }


def _build_task_sections(draft):
    sections = [{
        'title': '任务草稿',
        'items': [
            f"任务名称：{draft['name']}",
            f"任务类型：{draft['task_type']}",
            f"目标主机：{draft['host_count']} 台",
            f"执行方式：{draft['execution_mode']}",
            f"执行策略：{draft['execution_strategy']}",
            f"风险等级：{draft['risk_level']}",
        ],
    }]
    target_hosts = draft.get('target_hosts') or []
    if target_hosts:
        sections.append({
            'title': '目标主机',
            'items': [f"{item['hostname']} ({item['ip_address']})" for item in target_hosts[:6]],
        })
    payload = draft.get('payload') or {}
    if payload.get('command'):
        sections.append({'title': '命令内容', 'items': [payload['command']]})
    if payload.get('service_name'):
        sections.append({'title': '服务名称', 'items': [payload['service_name']]})
    if payload.get('playbook_content'):
        sections.append({'title': 'Playbook 摘要', 'items': ['已生成内联 Playbook 草稿']})
    return sections


def _resolve_host_targets_for_task(question='', environment='', target_status='all', explicit_host_ids=None, max_hosts=20):
    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if target_status == 'offline':
        host_queryset = host_queryset.filter(status='offline')

    explicit_host_ids = explicit_host_ids or []
    if explicit_host_ids:
        hosts = list(Host.objects.filter(id__in=explicit_host_ids))
        host_map = {host.id: host for host in hosts}
        return [host_map[host_id] for host_id in explicit_host_ids if host_id in host_map][:max_hosts]

    candidates = []
    seen_ids = set()

    for ip_value in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', question or ''):
        for host in host_queryset.filter(ip_address=ip_value):
            if host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

    normalized_question = (question or '').strip()
    if normalized_question:
        for host in host_queryset.filter(hostname__iexact=normalized_question)[:max_hosts]:
            if host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

    tokens = _clean_cmdb_query_tokens(question)
    if tokens:
        for host in host_queryset.filter(hostname__in=tokens)[:max_hosts]:
            if host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

        config_items = list(_query_cmdb_queryset(ConfigItem.objects.select_related('ci_type').all(), tokens).order_by('-updated_at')[: max_hosts * 2])
        for item in config_items:
            attributes = item.attributes or {}
            possible_ips = [
                attributes.get('host_ip'),
                attributes.get('docker_environment_ip'),
                attributes.get('ip_address'),
                attributes.get('private_ip'),
                attributes.get('public_ip'),
            ]
            possible_names = [item.name, attributes.get('host_name'), attributes.get('docker_environment_name')]
            host = None
            for ip_value in [value for value in possible_ips if value]:
                host = host_queryset.filter(ip_address=ip_value).order_by('id').first()
                if host:
                    break
            if not host:
                for hostname in [value for value in possible_names if value]:
                    host = host_queryset.filter(hostname=hostname).order_by('id').first()
                    if host:
                        break
            if host and host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

    return candidates[:max_hosts]


def build_task_draft(user, question='', draft_request=None):
    if not user_has_permissions(user, ['aiops.task.generate']):
        return {'error': '当前账号无权生成任务草稿。'}

    draft_request = draft_request or {}
    environment = draft_request.get('environment') or _extract_environment(question)
    target_status = draft_request.get('target_status') or ('offline' if '离线' in (question or '') else 'all')
    max_hosts = draft_request.get('max_hosts') or 20

    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if target_status == 'offline':
        host_queryset = host_queryset.filter(status='offline')

    explicit_host_ids = draft_request.get('target_host_ids') or []
    if explicit_host_ids:
        host_ids = list(Host.objects.filter(id__in=explicit_host_ids).values_list('id', flat=True))
    else:
        host_ids = list(host_queryset.values_list('id', flat=True)[:max_hosts])
    if not host_ids:
        host_ids = list(Host.objects.values_list('id', flat=True)[: min(max_hosts, 10)])
    if not host_ids:
        return {'error': '当前没有可用主机，无法生成任务。'}

    task_kind = draft_request.get('task_kind') or ''
    service_name = (draft_request.get('service_name') or '').strip()
    command = (draft_request.get('command') or '').strip()
    playbook_content = (draft_request.get('playbook_content') or '').strip()
    request_summary = (draft_request.get('request_summary') or question or '').strip()

    if not task_kind:
        service_match = re.search(r'(nginx|redis|rocketmq|mysql|docker|kubelet|sshd)', question or '', re.IGNORECASE)
        command_match = re.search(r'(?:执行|运行|命令)\s+([a-zA-Z0-9_\-./ ]{3,120})', question or '')
        if service_name or service_match:
            task_kind = 'service_status'
            service_name = service_name or service_match.group(1)
        elif command or command_match:
            task_kind = 'run_command'
            command = command or command_match.group(1).strip()
        elif _contains_any(question, ['连通', '连通性', 'ssh']):
            task_kind = 'check_connection'
        elif _contains_any(question, ['playbook']):
            task_kind = 'run_playbook'
        else:
            task_kind = 'refresh_metrics'

    task_type = HostTask.TASK_REFRESH_METRICS
    payload = {}
    execution_mode = HostTask.EXECUTION_MODE_SSH
    execution_strategy = HostTask.STRATEGY_CONTINUE
    timeout_seconds = 30
    title = '智能巡检任务'
    description = '由 AIOps 智能助手生成的任务草稿'

    if task_kind == 'service_status':
        task_type = HostTask.TASK_SERVICE_STATUS
        payload = {'service_name': service_name or 'nginx'}
        title = f"{payload['service_name']} 服务状态巡检"
        description = f"检查 {payload['service_name']} 服务状态"
    elif task_kind == 'run_command':
        task_type = HostTask.TASK_RUN_COMMAND
        payload = {'command': command or 'hostname && uptime'}
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        execution_strategy = HostTask.STRATEGY_STOP_ON_ERROR
        title = f"批量命令执行：{payload['command'][:32]}"
        description = '由聊天助手从自然语言生成的批量命令任务'
    elif task_kind == 'check_connection':
        task_type = HostTask.TASK_CHECK_CONNECTION
        title = 'SSH 连通性检查'
        description = '检查目标主机 SSH 连通性'
    elif task_kind == 'run_playbook':
        task_type = HostTask.TASK_RUN_PLAYBOOK
        payload = {
            'playbook_name': 'aiops_generated',
            'playbook_content': playbook_content or '- hosts: all\n  gather_facts: false\n  tasks:\n    - name: ping\n      ping:\n',
        }
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        title = 'Ansible Playbook 执行'
        description = '由 AIOps 智能助手生成的 Playbook 任务'

    risk_level = AIOpsPendingAction.RISK_LOW
    if task_type == HostTask.TASK_RUN_COMMAND:
        risk_level = AIOpsPendingAction.RISK_HIGH
        lowered_command = payload.get('command', '').lower()
        if any(pattern in lowered_command for pattern in DANGEROUS_COMMAND_PATTERNS):
            risk_level = AIOpsPendingAction.RISK_CRITICAL
    elif task_type == HostTask.TASK_RUN_PLAYBOOK:
        risk_level = AIOpsPendingAction.RISK_HIGH
    elif task_type == HostTask.TASK_SERVICE_STATUS:
        risk_level = AIOpsPendingAction.RISK_MEDIUM

    return {
        'name': title,
        'description': description,
        'task_type': task_type,
        'payload': payload,
        'host_ids': host_ids,
        'execution_mode': execution_mode,
        'execution_strategy': execution_strategy,
        'timeout_seconds': timeout_seconds,
        'host_count': len(host_ids),
        'risk_level': risk_level,
        'request_summary': request_summary,
    }


def _resolve_host_targets_for_task(question='', environment='', target_status='all', explicit_host_ids=None, max_hosts=20):
    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if target_status == 'offline':
        host_queryset = host_queryset.filter(status='offline')

    explicit_host_ids = explicit_host_ids or []
    if explicit_host_ids:
        hosts = list(Host.objects.filter(id__in=explicit_host_ids))
        host_map = {host.id: host for host in hosts}
        return [host_map[host_id] for host_id in explicit_host_ids if host_id in host_map][:max_hosts]

    candidates = []
    seen_ids = set()

    for ip_value in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', question or ''):
        for host in host_queryset.filter(ip_address=ip_value).order_by('id'):
            if host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

    tokens = _clean_cmdb_query_tokens(question)
    if tokens:
        for host in host_queryset.filter(hostname__in=tokens).order_by('id'):
            if host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

        config_items = list(
            _query_cmdb_queryset(ConfigItem.objects.select_related('ci_type').all(), tokens)
            .order_by('-updated_at')[: max_hosts * 2]
        )
        for item in config_items:
            attributes = item.attributes or {}
            possible_ips = [
                attributes.get('host_ip'),
                attributes.get('docker_environment_ip'),
                attributes.get('ip_address'),
                attributes.get('private_ip'),
                attributes.get('public_ip'),
            ]
            possible_names = [item.name, attributes.get('host_name'), attributes.get('docker_environment_name')]
            host = None
            for ip_value in [value for value in possible_ips if value]:
                host = host_queryset.filter(ip_address=ip_value).order_by('id').first()
                if host:
                    break
            if not host:
                for hostname in [value for value in possible_names if value]:
                    host = host_queryset.filter(hostname=hostname).order_by('id').first()
                    if host:
                        break
            if host and host.id not in seen_ids:
                candidates.append(host)
                seen_ids.add(host.id)

    return candidates[:max_hosts]


def build_task_draft(user, question='', draft_request=None):
    if not user_has_permissions(user, ['aiops.task.generate']):
        return {'error': '当前账号无权生成任务草稿。'}

    draft_request = draft_request or {}
    environment = draft_request.get('environment') or _extract_environment(question)
    target_status = draft_request.get('target_status') or ('offline' if '离线' in (question or '') else 'all')
    max_hosts = draft_request.get('max_hosts') or 20
    explicit_host_ids = draft_request.get('target_host_ids') or []
    hosts = _resolve_host_targets_for_task(
        question=question,
        environment=environment,
        target_status=target_status,
        explicit_host_ids=explicit_host_ids,
        max_hosts=max_hosts,
        draft_request=draft_request,
    )
    host_ids = [host.id for host in hosts]
    if not host_ids:
        return {'error': '未识别到明确的目标主机，请在问题中指定主机名、应用名或 IP 后再生成任务。'}

    task_kind = draft_request.get('task_kind') or ''
    service_name = (draft_request.get('service_name') or '').strip()
    command = (draft_request.get('command') or '').strip()
    playbook_content = (draft_request.get('playbook_content') or '').strip()
    request_summary = (draft_request.get('request_summary') or question or '').strip()

    if not task_kind:
        service_match = re.search(r'(nginx|redis|rocketmq|mysql|docker|kubelet|sshd)', question or '', re.IGNORECASE)
        command_match = re.search(r'(?:执行|运行|命令)\s+([a-zA-Z0-9_\-./ ]{3,120})', question or '')
        if service_name or service_match:
            task_kind = 'service_status'
            service_name = service_name or service_match.group(1)
        elif command or command_match:
            task_kind = 'run_command'
            command = command or command_match.group(1).strip()
        elif _contains_any(question, ['连通', '连通性', 'ssh']):
            task_kind = 'check_connection'
        elif _contains_any(question, ['playbook']):
            task_kind = 'run_playbook'
        else:
            task_kind = 'refresh_metrics'

    task_type = HostTask.TASK_REFRESH_METRICS
    payload = {}
    execution_mode = HostTask.EXECUTION_MODE_SSH
    execution_strategy = HostTask.STRATEGY_CONTINUE
    timeout_seconds = 30
    title = '智能巡检任务'
    description = '由 AIOps 智能助手生成的任务草稿'

    if task_kind == 'service_status':
        task_type = HostTask.TASK_SERVICE_STATUS
        payload = {'service_name': service_name or 'nginx'}
        title = f"{payload['service_name']} 服务状态巡检"
        description = f"检查 {payload['service_name']} 服务状态"
    elif task_kind == 'run_command':
        task_type = HostTask.TASK_RUN_COMMAND
        payload = {'command': command or 'hostname && uptime'}
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        execution_strategy = HostTask.STRATEGY_STOP_ON_ERROR
        title = f"批量命令执行：{payload['command'][:32]}"
        description = '由聊天助手从自然语言生成的批量命令任务'
    elif task_kind == 'check_connection':
        task_type = HostTask.TASK_CHECK_CONNECTION
        title = 'SSH 连通性检查'
        description = '检查目标主机 SSH 连通性'
    elif task_kind == 'run_playbook':
        task_type = HostTask.TASK_RUN_PLAYBOOK
        payload = {
            'playbook_name': 'aiops_generated',
            'playbook_content': playbook_content or '- hosts: all\n  gather_facts: false\n  tasks:\n    - name: ping\n      ping:\n',
        }
        execution_mode = HostTask.EXECUTION_MODE_ANSIBLE
        title = 'Ansible Playbook 执行'
        description = '由 AIOps 智能助手生成的 Playbook 任务'

    risk_level = AIOpsPendingAction.RISK_LOW
    if task_type == HostTask.TASK_RUN_COMMAND:
        risk_level = AIOpsPendingAction.RISK_HIGH
        lowered_command = payload.get('command', '').lower()
        if any(pattern in lowered_command for pattern in DANGEROUS_COMMAND_PATTERNS):
            risk_level = AIOpsPendingAction.RISK_CRITICAL
    elif task_type == HostTask.TASK_RUN_PLAYBOOK:
        risk_level = AIOpsPendingAction.RISK_HIGH
    elif task_type == HostTask.TASK_SERVICE_STATUS:
        risk_level = AIOpsPendingAction.RISK_MEDIUM

    return {
        'name': title,
        'description': description,
        'task_type': task_type,
        'payload': payload,
        'host_ids': host_ids,
        'target_hosts': _build_host_target_snapshot(hosts),
        'execution_mode': execution_mode,
        'execution_strategy': execution_strategy,
        'timeout_seconds': timeout_seconds,
        'host_count': len(host_ids),
        'risk_level': risk_level,
        'request_summary': request_summary,
    }


def _coerce_int_list(value):
    if value in (None, ''):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        return [int(item) for item in re.findall(r'\d+', value)]
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            try:
                values.append(int(item))
            except (TypeError, ValueError):
                continue
        return values
    return []


def _append_unique_host(candidates, seen_ids, host):
    if host and host.id not in seen_ids:
        candidates.append(host)
        seen_ids.add(host.id)


def _host_from_config_item(config_item, host_queryset=None):
    if not config_item:
        return None
    host_queryset = host_queryset or Host.objects.all()
    attributes = config_item.attributes or {}
    for hostname in [config_item.name, attributes.get('host_name'), attributes.get('docker_environment_name')]:
        if hostname:
            host = host_queryset.filter(hostname=hostname).order_by('id').first()
            if host:
                return host
    for ip_value in [
        attributes.get('host_ip'),
        attributes.get('docker_environment_ip'),
        attributes.get('ip_address'),
        attributes.get('private_ip'),
        attributes.get('public_ip'),
    ]:
        if ip_value:
            host = host_queryset.filter(ip_address=ip_value).order_by('id').first()
            if host:
                return host
    return None


def _resolve_host_targets_for_task(question='', environment='', target_status='all', explicit_host_ids=None, max_hosts=20, draft_request=None):
    draft_request = draft_request or {}
    host_queryset = Host.objects.all()
    if environment:
        host_queryset = host_queryset.filter(environment=environment)
    if target_status == 'offline':
        host_queryset = host_queryset.filter(status='offline')

    candidates = []
    seen_ids = set()
    question_text = question or ''

    explicit_ids = []
    explicit_ids.extend(_coerce_int_list(explicit_host_ids))
    explicit_ids.extend(_coerce_int_list(draft_request.get('host_id')))
    explicit_ids.extend(_coerce_int_list(draft_request.get('target_host_id')))
    explicit_ids.extend(_coerce_int_list(draft_request.get('ci_id')))
    explicit_ids.extend(_coerce_int_list(draft_request.get('config_item_id')))
    explicit_ids.extend(_coerce_int_list(draft_request.get('target_ci_ids')))
    explicit_ids.extend(int(item) for item in re.findall(r'\b(?:host_id|ci_id|config_item_id)\s*[=:：]\s*(\d+)\b', question_text, flags=re.IGNORECASE))

    for target_id in dict.fromkeys(explicit_ids):
        host = host_queryset.filter(id=target_id).order_by('id').first()
        if not host:
            host = _host_from_config_item(ConfigItem.objects.filter(id=target_id).first(), host_queryset=host_queryset)
        _append_unique_host(candidates, seen_ids, host)

    explicit_names = []
    for key in ['hostname', 'host_name', 'target_host', 'target_hostname']:
        if draft_request.get(key):
            explicit_names.append(str(draft_request[key]).strip())

    tokens = _clean_cmdb_query_tokens(question_text)
    explicit_names.extend(tokens)
    for hostname in [item for item in explicit_names if item]:
        for host in host_queryset.filter(hostname=hostname).order_by('id'):
            _append_unique_host(candidates, seen_ids, host)

    if tokens:
        config_items = list(
            _query_cmdb_queryset(ConfigItem.objects.select_related('ci_type').all(), tokens)
            .order_by('-updated_at')[: max_hosts * 2]
        )
        for item in config_items:
            _append_unique_host(candidates, seen_ids, _host_from_config_item(item, host_queryset=host_queryset))

    if not candidates:
        for ip_value in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', question_text):
            for host in host_queryset.filter(ip_address=ip_value).order_by('id'):
                _append_unique_host(candidates, seen_ids, host)

    return candidates[:max_hosts]


def create_pending_task_action_from_draft(session, assistant_message, draft):
    return AIOpsPendingAction.objects.create(
        session=session,
        message=assistant_message,
        action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
        title=draft['name'],
        risk_level=draft['risk_level'],
        action_payload=draft,
    )


def create_pending_task_action(session, assistant_message, user, question):
    draft = build_task_draft(user, question)
    if draft.get('error'):
        return None, draft['error']
    return create_pending_task_action_from_draft(session, assistant_message, draft), ''


def _build_host_target_snapshot(hosts):
    return [
        {
            'id': host.id,
            'hostname': host.hostname,
            'ip_address': host.ip_address,
            'business_line': host.business_line,
            'environment': host.environment,
            'status': host.status,
        }
        for host in hosts
    ]


def _create_host_task_record_from_draft(draft, user, session=None, request=None):
    payload = dict(draft or {})
    host_ids = payload.get('host_ids') or []
    host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
    hosts = [host_map[item] for item in host_ids if item in host_map]
    if not hosts:
        raise ValueError('没有找到有效的目标主机。')

    task = HostTask.objects.create(
        name=payload.get('name') or 'AIOps 智能任务',
        task_type=payload.get('task_type') or HostTask.TASK_REFRESH_METRICS,
        description=payload.get('description', ''),
        payload=payload.get('payload') or {},
        selection_filters={
            'source': 'aiops',
            'session_id': session.id if session else None,
            'request_summary': payload.get('request_summary', ''),
        },
        target_snapshot=_build_host_target_snapshot(hosts),
        target_count=len(hosts),
        execution_mode=payload.get('execution_mode') or HostTask.EXECUTION_MODE_SSH,
        execution_strategy=payload.get('execution_strategy') or HostTask.STRATEGY_CONTINUE,
        timeout_seconds=payload.get('timeout_seconds') or 30,
        created_by=user.username,
        summary='任务已由 AIOps 智能助手创建，等待在任务中心执行',
    )
    record_event(
        request=request,
        module='aiops',
        category='execution',
        action='create_host_task_record',
        title='AIOps 创建任务中心任务',
        summary=f'已创建任务中心任务 {task.name}',
        result=EventRecord.RESULT_PENDING,
        resource_type='host_task',
        resource_id=task.id,
        resource_name=task.name,
        correlation_id=f'aiops-host-task:{task.id}',
        metadata={
            'task_type': task.task_type,
            'execution_mode': task.execution_mode,
            'target_count': len(hosts),
            'created_by': user.username,
            'source': 'aiops',
        },
    )
    return task


def _should_materialize_host_task(question, result, draft):
    if not draft or draft.get('error'):
        return False
    tool_calls = set(result.get('tool_calls') or [])
    if 'generate_host_task' not in tool_calls:
        return False
    text = (question or '').strip().lower()
    if not text:
        return True
    negative_markers = ['草稿', '待确认', '不要创建', '先别创建', '不要落任务', '不要生成任务中心']
    return not any(marker in text for marker in negative_markers)


def _execute_host_task_action(action, user, request=None):
    payload = dict(action.action_payload or {})
    host_ids = payload.get('host_ids') or []
    host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
    hosts = [host_map[item] for item in host_ids if item in host_map]
    if not hosts:
        raise ValueError('没有找到有效的目标主机。')

    task = HostTask.objects.create(
        name=payload.get('name') or 'AIOps 智能任务',
        task_type=payload.get('task_type') or HostTask.TASK_REFRESH_METRICS,
        description=payload.get('description', ''),
        payload=payload.get('payload') or {},
        selection_filters={'source': 'aiops', 'session_id': action.session_id},
        execution_mode=payload.get('execution_mode') or HostTask.EXECUTION_MODE_SSH,
        execution_strategy=payload.get('execution_strategy') or HostTask.STRATEGY_CONTINUE,
        timeout_seconds=payload.get('timeout_seconds') or 30,
        created_by=user.username,
        summary='任务已由 AIOps 智能助手创建，等待执行完成',
    )
    start_host_task(task, hosts)
    action.status = AIOpsPendingAction.STATUS_EXECUTED
    action.result_payload = {'task_id': task.id, 'task_name': task.name}
    action.save(update_fields=['status', 'result_payload', 'updated_at'])
    record_event(
        request=request,
        module='aiops',
        category='execution',
        action='confirm_execute_task',
        title='AIOps 执行主机任务',
        summary=f'已通过 AIOps 执行主机任务 {task.name}',
        resource_type='aiops_action',
        resource_id=action.id,
        resource_name=action.title,
        correlation_id=f'aiops-action:{action.id}',
        related_resources=[{'module': 'ops', 'type': 'host_task', 'id': str(task.id), 'name': task.name}],
        metadata={'host_count': len(hosts), 'created_by': user.username},
    )
    return task


def confirm_action(action, user, request=None):
    config = get_agent_config()
    if not config.allow_action_execution:
        raise ValueError('管理员已关闭机器人动作执行。')
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可确认。')
    if action.session.user_id != user.id:
        raise ValueError('只能确认自己的动作。')
    if action.action_type == AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK:
        if not user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
            raise ValueError('当前账号无权执行机器人任务。')
        action.status = AIOpsPendingAction.STATUS_CONFIRMED
        action.confirmed_by = user.username
        action.confirmed_at = timezone.now()
        action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
        return _execute_host_task_action(action, user, request=request)
    raise ValueError('不支持的动作类型。')


def _should_materialize_host_task(question, result, draft):
    return False


def confirm_action(action, user, request=None):
    config = get_agent_config()
    if not config.allow_action_execution:
        raise ValueError('管理员已关闭机器人动作执行。')
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可确认。')
    if action.session.user_id != user.id:
        raise ValueError('只能确认自己的动作。')
    if action.action_type != AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK:
        raise ValueError('不支持的动作类型。')
    if not user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
        raise ValueError('当前账号无权执行机器人任务。')

    action.status = AIOpsPendingAction.STATUS_CONFIRMED
    action.confirmed_by = user.username
    action.confirmed_at = timezone.now()
    action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])

    task = _create_host_task_record_from_draft(action.action_payload or {}, user, session=action.session, request=request)
    action.status = AIOpsPendingAction.STATUS_EXECUTED
    action.result_payload = {
        'task_id': task.id,
        'task_name': task.name,
        'materialized_in_task_center': True,
    }
    action.save(update_fields=['status', 'result_payload', 'updated_at'])
    return task


def cancel_action(action, user):
    if action.status != AIOpsPendingAction.STATUS_PENDING:
        raise ValueError('当前动作状态不可取消。')
    if action.session.user_id != user.id:
        raise ValueError('只能取消自己的动作。')
    action.status = AIOpsPendingAction.STATUS_CANCELED
    action.confirmed_by = user.username
    action.confirmed_at = timezone.now()
    action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
    return action


def _provider_is_ready(provider):
    return bool(
        provider
        and provider.base_url
        and provider.get_api_key()
        and provider.default_model
        and not _builtin_experience_provider_needs_setup(provider)
    )


def _build_dispatch_error_result(detail='', code='error', message='问答失败，请稍后重试。'):
    error_detail = (detail or '')[:500]
    content = message
    if error_detail:
        content = f'{content}\n\n{error_detail}'
    return {
        'content': content,
        'citations': [],
        'tool_calls': [],
        'message_type': AIOpsChatMessage.TYPE_ERROR,
        'pending_action_draft': None,
        'metadata': {'execution_mode': 'error', 'error_code': code, 'error_detail': error_detail},
    }


def _candidate_model_names(model_name):
    model_name = (model_name or '').strip()
    if not model_name:
        return []
    candidates = [model_name]
    if re.fullmatch(r'gpt-5(?:\.\d+)?', model_name):
        candidates.extend([f'{model_name}-low', f'{model_name}-medium'])
        candidates.append(f'cc-{model_name}')
    else:
        family_match = re.fullmatch(r'(gpt-5(?:\.\d+)?(?:-codex)?)(?:-(low|medium|high|xhigh))', model_name)
        if family_match:
            candidates.append(f"cc-{family_match.group(1)}")
    return list(dict.fromkeys(candidates))


def _model_prefers_developer_role(model_name):
    return bool(re.match(r'^(cc-)?gpt-5', str(model_name or '').strip()))


def _convert_system_messages_to_developer(messages):
    converted = []
    for message in messages or []:
        if not isinstance(message, dict):
            converted.append(message)
            continue
        if message.get('role') == 'system':
            converted.append({**message, 'role': 'developer'})
        else:
            converted.append(message)
    return converted


def _message_has_tool_role(messages):
    return any(isinstance(message, dict) and message.get('role') == 'tool' for message in messages or [])


def _convert_tool_messages_to_user_summaries(messages):
    converted = []
    for message in messages or []:
        if not isinstance(message, dict):
            converted.append(message)
            continue
        if message.get('role') == 'tool':
            tool_call_id = message.get('tool_call_id') or ''
            content = str(message.get('content') or '')
            converted.append({
                'role': 'user',
                'content': f'工具调用结果（tool_call_id={tool_call_id}）：\n{content}',
            })
            continue
        if message.get('role') == 'assistant' and message.get('tool_calls'):
            function_names = [
                ((tool_call.get('function') or {}).get('name') or '')
                for tool_call in message.get('tool_calls') or []
            ]
            function_names = [item for item in function_names if item]
            assistant_content = str(message.get('content') or '').strip()
            converted.append({
                'role': 'assistant',
                'content': assistant_content or f"已请求工具调用：{'、'.join(function_names) or '未知工具'}",
            })
            continue
        converted.append(message)
    return converted


def _provider_error_code(error_payload):
    if not isinstance(error_payload, dict):
        return ''
    error = error_payload.get('error') if isinstance(error_payload.get('error'), dict) else {}
    return str(error.get('code') or error.get('type') or '').strip()


def _should_retry_with_developer_role(error_payload, request_payload):
    if _provider_error_code(error_payload) != 'bad_response_status_code':
        return False
    return any(isinstance(message, dict) and message.get('role') == 'system' for message in request_payload.get('messages') or [])


def _should_retry_without_tool_role(error_payload, request_payload):
    if _provider_error_code(error_payload) != 'invalid_value':
        return False
    error_message = ''
    if isinstance(error_payload, dict) and isinstance(error_payload.get('error'), dict):
        error_message = str(error_payload['error'].get('message') or '')
    return "'tool'" in error_message and _message_has_tool_role(request_payload.get('messages') or [])


def _model_request_payload_variants(payload, model_name):
    request_payload = {**payload, 'model': model_name}
    messages = request_payload.get('messages') or []
    has_system_role = any(isinstance(message, dict) and message.get('role') == 'system' for message in messages)
    has_tool_role = _message_has_tool_role(messages)
    if has_system_role:
        developer_messages = _convert_system_messages_to_developer(messages)
    else:
        developer_messages = messages
    developer_payload = {**request_payload, 'messages': developer_messages}
    tool_compatible_payload = {**developer_payload, 'messages': _convert_tool_messages_to_user_summaries(developer_messages)}
    if has_tool_role and _model_prefers_developer_role(model_name):
        return [tool_compatible_payload, developer_payload, request_payload]
    if has_tool_role:
        return [request_payload, tool_compatible_payload]
    if not has_system_role:
        return [request_payload]
    if _model_prefers_developer_role(model_name):
        return [developer_payload, request_payload]
    return [request_payload, developer_payload]


def _model_provider_api_base(provider):
    endpoint = (provider.base_url or '').strip().rstrip('/')
    if endpoint.endswith('/chat/completions'):
        endpoint = endpoint[:-len('/chat/completions')]
    return endpoint


def _normalize_model_catalog_items(payload):
    raw_items = payload
    if isinstance(payload, dict):
        raw_items = payload.get('data') or payload.get('models') or []
    if not isinstance(raw_items, list):
        return []
    models = []
    for item in raw_items:
        if isinstance(item, str):
            model_id = item.strip()
            if model_id:
                models.append({'id': model_id})
            continue
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id') or item.get('name') or '').strip()
        if not model_id:
            continue
        models.append({
            'id': model_id,
            'owned_by': item.get('owned_by') or item.get('owner') or '',
            'supported_endpoint_types': item.get('supported_endpoint_types') or [],
        })
    return models


def _build_model_probe_candidates(provider, model_ids):
    model_id_set = set(model_ids)
    candidates = []

    def add(value):
        value = str(value or '').strip()
        if value and value not in candidates and (not model_id_set or value in model_id_set):
            candidates.append(value)

    for value in [provider.default_model, provider.backup_model]:
        add(value)
        for candidate in _candidate_model_names(value):
            add(candidate)

    preferred_patterns = [
        r'^cc-gpt-5\.3-codex$',
        r'^cc-gpt-5\.4$',
        r'^cc-gpt-5\.2$',
        r'^cc-gpt-5',
        r'^gpt-5\.4-mini$',
        r'^gpt-5\.2-low$',
        r'^gpt-5\.2',
        r'^gpt-5',
    ]
    for pattern in preferred_patterns:
        for model_id in model_ids:
            if re.search(pattern, model_id):
                add(model_id)
    for model_id in model_ids[:20]:
        add(model_id)
    return candidates


def _probe_model_text_completion(provider, model_name):
    result = _request_model_completion(provider, {
        'model': model_name,
        'temperature': 0,
        'max_tokens': 32,
        'messages': [{'role': 'user', 'content': 'reply with ping only'}],
    })
    return ((result or {}).get('_meta') or {}).get('resolved_model') or model_name


def _probe_model_tool_calling(provider, model_name):
    result = _request_model_completion(provider, {
        'model': model_name,
        'temperature': 0,
        'max_tokens': 96,
        'messages': [{'role': 'user', 'content': 'please call the ping_tool'}],
        'tools': [{
            'type': 'function',
            'function': {
                'name': 'ping_tool',
                'description': 'return pong',
                'parameters': {'type': 'object', 'properties': {}},
            },
        }],
        'tool_choice': 'auto',
    })
    choice = ((result or {}).get('choices') or [{}])[0]
    message = choice.get('message') or {}
    resolved_model = ((result or {}).get('_meta') or {}).get('resolved_model') or model_name
    return resolved_model, bool(message.get('tool_calls') or [])


def list_model_provider_models(provider, probe=True, max_probe=8):
    if not provider or not (provider.base_url or '').strip() or not provider.get_api_key().strip():
        raise ValueError('请先保存 Base URL 和 API Key 后再拉取模型列表')

    endpoint = f"{_model_provider_api_base(provider)}/models"
    response = requests.get(
        endpoint,
        headers={'Authorization': f'Bearer {provider.get_api_key()}'},
        timeout=max(provider.timeout_seconds, 5),
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {'status_code': response.status_code, 'text': response.text[:800]}
    if response.status_code >= 400:
        raise ValueError(payload)

    models = _normalize_model_catalog_items(payload)
    model_ids = [item['id'] for item in models]
    candidates = _build_model_probe_candidates(provider, model_ids)
    recommendation = None
    last_probe_error = ''
    text_verified_model = None

    if probe:
        for candidate in candidates[:max_probe]:
            try:
                resolved_model = _probe_model_text_completion(provider, candidate)
                if not text_verified_model:
                    text_verified_model = resolved_model
                tool_model, supports_tool_calling = _probe_model_tool_calling(provider, resolved_model)
                recommendation = {
                    'model': tool_model,
                    'requested_model': candidate,
                    'verified': True,
                    'supports_tool_calling': supports_tool_calling,
                    'message': '已验证可返回文本并支持 Tool Calling' if supports_tool_calling else '已验证可返回文本，Tool Calling 需在问答中进一步确认',
                }
                if supports_tool_calling:
                    break
            except Exception as exc:
                last_probe_error = str(exc)[:300]
                continue
    if not recommendation and text_verified_model:
        recommendation = {
            'model': text_verified_model,
            'requested_model': text_verified_model,
            'verified': True,
            'supports_tool_calling': False,
            'message': '已验证可返回文本，Tool Calling 需在问答中进一步确认',
        }

    return {
        'models': models,
        'count': len(models),
        'recommendation': recommendation,
        'probe_candidates': candidates[:max_probe],
        'probe_error': '' if recommendation else last_probe_error,
    }


def _extract_message_content(message):
    content = (message or {}).get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                parts.append(item['text'])
        return '\n'.join(parts)
    return ''


def _sanitize_assistant_content(content):
    text = (content or '').strip()
    if not text:
        return ''
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.S | re.I)
    return text.strip()


def _request_model_completion(provider, payload):
    endpoint = provider.base_url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint = f'{endpoint}/chat/completions'
    headers = {
        'Authorization': f'Bearer {provider.get_api_key()}',
        'Content-Type': 'application/json',
    }
    last_error = '模型调用失败'

    for model_name in _candidate_model_names(payload.get('model')):
        for request_payload in _model_request_payload_variants(payload, model_name):
            response = requests.post(
                endpoint,
                headers=headers,
                json=request_payload,
                timeout=max(provider.timeout_seconds, 5),
            )
            try:
                data = response.json()
            except ValueError:
                data = {'status_code': response.status_code, 'text': response.text[:800]}
            if response.status_code >= 400:
                last_error = data
                if not (
                    _should_retry_with_developer_role(data, request_payload)
                    or _should_retry_without_tool_role(data, request_payload)
                ):
                    break
                continue
            choice = ((data or {}).get('choices') or [{}])[0]
            message = choice.get('message') or {}
            content = _sanitize_assistant_content(_extract_message_content(message))
            if content or (message.get('tool_calls') or []):
                if content != _extract_message_content(message):
                    message['content'] = content
                    choice['message'] = message
                    data['choices'][0] = choice
                if model_name != payload.get('model'):
                    data.setdefault('_meta', {})['resolved_model'] = model_name
                return data
            last_error = {'error': {'message': f'model {model_name} returned empty content', 'type': 'empty_content'}}
            break

    raise ValueError(last_error)


def test_model_provider_connection(provider):
    if not _provider_is_ready(provider):
        return {'status': 'failed', 'message': get_model_provider_setup_hint(provider) or '请完善 Base URL、模型和 API Key'}
    result = _request_model_completion(provider, {
        'model': provider.default_model,
        'temperature': 0,
        'max_tokens': 32,
        'messages': [{'role': 'user', 'content': '请只回复：连接成功'}],
    })
    resolved_model = ((result or {}).get('_meta') or {}).get('resolved_model') or provider.default_model
    return {
        'status': 'success',
        'message': f'模型连接成功（实际调用模型：{resolved_model}）',
        'resolved_model': resolved_model,
    }


def _safe_tool_name(value):
    normalized = re.sub(r'[^a-zA-Z0-9_]+', '_', str(value or '').strip())
    normalized = re.sub(r'_+', '_', normalized).strip('_')
    return normalized or 'tool'


def _build_mcp_tool_alias(server, raw_tool_name):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        return raw_tool_name
    return f"mcp__{_safe_tool_name(server.name)}__{_safe_tool_name(raw_tool_name)}"


def _extract_mcp_headers(response):
    headers = {}
    for key, value in response.headers.items():
        headers[key.lower()] = value
    return headers


def _parse_sse_json_messages(payload_text):
    messages = []
    data_lines = []
    for line in (payload_text or '').splitlines():
        if line.startswith('data:'):
            data_lines.append(line[5:].strip())
            continue
        if not line.strip() and data_lines:
            chunk = '\n'.join(data_lines)
            data_lines = []
            if not chunk:
                continue
            try:
                messages.append(json.loads(chunk))
            except (TypeError, ValueError):
                continue
    if data_lines:
        try:
            messages.append(json.loads('\n'.join(data_lines)))
        except (TypeError, ValueError):
            pass
    return messages


def _extract_jsonrpc_messages_from_http_response(response):
    content_type = (response.headers.get('Content-Type') or '').lower()
    if 'text/event-stream' in content_type:
        return _parse_sse_json_messages(response.text)
    if not response.content:
        return []
    payload = response.json()
    if isinstance(payload, list):
        return payload
    return [payload]


class _BaseMCPClientSession:
    def __init__(self, server):
        self.server = server
        self.protocol_version = MCP_PROTOCOL_VERSION

    def initialize(self):
        raise NotImplementedError

    def list_tools(self):
        raise NotImplementedError

    def call_tool(self, name, arguments):
        raise NotImplementedError

    def close(self):
        return None


class _HTTPMCPClientSession(_BaseMCPClientSession):
    def __init__(self, server):
        super().__init__(server)
        self.session = requests.Session()
        self.session_id = ''
        auth_config = server.auth_config or {}
        self.timeout_seconds = max(int(auth_config.get('timeout_seconds') or 20), 5)
        self.extra_headers = dict(auth_config.get('headers') or {})
        if auth_config.get('bearer_token'):
            self.extra_headers.setdefault('Authorization', f"Bearer {auth_config['bearer_token']}")

    def _post(self, message, include_session=True):
        headers = {
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
            'MCP-Protocol-Version': self.protocol_version,
            **self.extra_headers,
        }
        if include_session and self.session_id:
            headers['MCP-Session-Id'] = self.session_id
        response = self.session.post(
            self.server.endpoint_or_command,
            json=message,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise ValueError(response.text or f'HTTP {response.status_code}')
        header_map = _extract_mcp_headers(response)
        if header_map.get('mcp-session-id'):
            self.session_id = header_map['mcp-session-id']
        return _extract_jsonrpc_messages_from_http_response(response)

    def _delete_session(self):
        if not self.session_id:
            return
        headers = {'MCP-Session-Id': self.session_id, **self.extra_headers}
        try:
            self.session.delete(self.server.endpoint_or_command, headers=headers, timeout=self.timeout_seconds)
        except Exception:
            pass

    def _request(self, method, params=None):
        request_id = uuid.uuid4().hex
        responses = self._post({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        for item in responses:
            if str(item.get('id')) != request_id:
                continue
            if item.get('error'):
                raise ValueError(item['error'])
            return item.get('result') or {}
        return {}

    def _notify(self, method, params=None):
        self._post({'jsonrpc': '2.0', 'method': method, 'params': params or {}}, include_session=True)

    def initialize(self):
        result = self._request(
            'initialize',
            {'protocolVersion': self.protocol_version, 'capabilities': {}, 'clientInfo': MCP_CLIENT_INFO},
        )
        self.protocol_version = result.get('protocolVersion') or self.protocol_version
        self._notify('notifications/initialized', {})
        return result

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            params = {'cursor': cursor} if cursor else {}
            result = self._request('tools/list', params)
            tools.extend(result.get('tools') or [])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(self, name, arguments):
        return self._request('tools/call', {'name': name, 'arguments': arguments or {}})

    def close(self):
        self._delete_session()
        self.session.close()


class _StdioMCPClientSession(_BaseMCPClientSession):
    def __init__(self, server):
        super().__init__(server)
        auth_config = server.auth_config or {}
        command = shlex.split(server.endpoint_or_command or '', posix=False)
        if not command:
            raise ValueError('MCP STDIO command is empty')
        env = dict(os.environ)
        env.update(auth_config.get('env') or {})
        self.timeout_seconds = max(int(auth_config.get('timeout_seconds') or 20), 5)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
        )
        self.stdout_queue = queue.Queue()
        self.stderr_queue = queue.Queue()
        self._start_reader(self.process.stdout, self.stdout_queue)
        self._start_reader(self.process.stderr, self.stderr_queue)

    def _start_reader(self, stream, target_queue):
        def pump():
            for line in iter(stream.readline, ''):
                target_queue.put(line)
        thread = threading.Thread(target=pump, daemon=True)
        thread.start()

    def _send(self, payload):
        if not self.process.stdin:
            raise ValueError('MCP STDIO stdin unavailable')
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def _request(self, method, params=None):
        request_id = uuid.uuid4().hex
        self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}})
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            try:
                line = self.stdout_queue.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except (TypeError, ValueError):
                continue
            if str(message.get('id')) != request_id:
                continue
            if message.get('error'):
                raise ValueError(message['error'])
            return message.get('result') or {}
        stderr_output = []
        while not self.stderr_queue.empty():
            stderr_output.append(self.stderr_queue.get_nowait().strip())
        raise TimeoutError('MCP STDIO request timed out: ' + ' '.join(item for item in stderr_output if item))

    def _notify(self, method, params=None):
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def initialize(self):
        result = self._request(
            'initialize',
            {'protocolVersion': self.protocol_version, 'capabilities': {}, 'clientInfo': MCP_CLIENT_INFO},
        )
        self.protocol_version = result.get('protocolVersion') or self.protocol_version
        self._notify('notifications/initialized', {})
        return result

    def list_tools(self):
        tools = []
        cursor = None
        while True:
            params = {'cursor': cursor} if cursor else {}
            result = self._request('tools/list', params)
            tools.extend(result.get('tools') or [])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(self, name, arguments):
        return self._request('tools/call', {'name': name, 'arguments': arguments or {}})

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _create_mcp_client_session(server):
    if server.server_type == AIOpsMCPServer.SERVER_HTTP:
        return _HTTPMCPClientSession(server)
    if server.server_type == AIOpsMCPServer.SERVER_STDIO:
        return _StdioMCPClientSession(server)
    raise ValueError(f'Unsupported MCP server type: {server.server_type}')


def test_mcp_server_connection(server):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        return {
            'status': 'success',
            'message': '内置 MCP 无需额外握手，当前可直接使用。',
            'server_info': {'name': server.name, 'type': server.server_type},
        }

    client_session = _create_mcp_client_session(server)
    try:
        result = client_session.initialize()
        return {
            'status': 'success',
            'message': 'MCP 连接成功。',
            'server_info': result.get('serverInfo') or {'name': server.name},
            'protocol_version': result.get('protocolVersion') or MCP_PROTOCOL_VERSION,
            'capabilities': result.get('capabilities') or {},
        }
    finally:
        try:
            client_session.close()
        except Exception:
            pass


def list_mcp_server_tools(server):
    if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
        tool_names = server.tool_whitelist or []
        return {
            'tools': [
                {'name': item, 'description': '平台内置 MCP 工具', 'inputSchema': {'type': 'object', 'properties': {}}}
                for item in tool_names
            ],
            'count': len(tool_names),
        }

    client_session = _create_mcp_client_session(server)
    try:
        client_session.initialize()
        tools = _discover_external_mcp_tools(server, client_session)
        return {'tools': tools, 'count': len(tools)}
    finally:
        try:
            client_session.close()
        except Exception:
            pass


def _build_runtime_prompt(config, active_mcp_servers, active_skills, user):
    mcp_lines = [
        f"- {server.name}：{server.description}；工具：{'、'.join(server.tool_whitelist or [])}"
        for server in active_mcp_servers
    ]
    skill_lines = [f"- {skill.name}：{skill.content}" for skill in active_skills]
    permission_lines = [
        f"- 可聊天：{'是' if user_has_permissions(user, ['aiops.chat.view']) else '否'}",
        f"- 可分析：{'是' if user_has_permissions(user, ['aiops.chat.analyze']) else '否'}",
        f"- 可生成任务：{'是' if user_has_permissions(user, ['aiops.task.generate']) else '否'}",
        f"- 可执行任务：{'是' if user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']) else '否'}",
    ]
    runtime_lines = [
        f"- allow_action_execution={config.allow_action_execution}",
        f"- require_confirmation={config.require_confirmation}",
        f"- show_evidence={config.show_evidence}",
    ]
    parts = [
        config.system_prompt or DEFAULT_SYSTEM_PROMPT,
        '你当前接入的是平台内置 MCP 与 Skills 运行时。',
        '可用 MCP：',
        '\n'.join(mcp_lines) if mcp_lines else '- 当前无可用 MCP',
        '启用 Skill：',
        '\n'.join(skill_lines) if skill_lines else '- 当前无启用 Skill',
        '当前用户权限：',
        '\n'.join(permission_lines),
        '运行约束：',
        '\n'.join(runtime_lines),
        '要求：优先调用工具获取事实；未确认前不能声称任务已执行；如果数据不足，请明确说明。',
        '如果用户明确要求生成、创建、新建、安排任务或巡检任务，不要只做查询，必须调用 generate_host_task。',
        '只要已经调用 generate_host_task，就要在最终回答里明确说明：是生成任务草稿，还是已经在任务中心创建真实任务。',
        '工具选择示例：',
        '- “当前未确认的严重告警有哪些” => 优先调用 query_alerts，并设置 level=critical、only_unacknowledged=true。',
        '- “分析生产 order-center 最近异常” => 优先调用 query_alerts；需要补充上下文时再追加 query_recent_changes、query_logs 或 query_traces。',
        '- “链路追踪里的服务 xxx 最近有没有异常 / trace 中服务 xxx 是否有错误” => 必须优先调用 query_traces，query 只传服务名，errors_only=true。',
        '- “最近电商线生产有哪些工单” => 调用 query_workorders，并把业务线、环境信息体现在参数中。',
        '- “生产环境有哪些离线主机” => 调用 query_hosts，并设置 environment=prod、status=offline。',
        '- “数据平台生产环境月成本多少” => 调用 query_cost_report，并设置 business_line=数据平台、environment=prod。',
        '- “app-prod-k8s集群有没有异常的pod” => 调用 query_k8s_cluster_summary，并传 cluster_name=app-prod-k8s。',
        '- “生成一份 Redis 巡检任务” => 调用 generate_host_task，而不是只做查询。',
    ]
    return '\n'.join(parts)


def _build_history_messages(session, config):
    history = list(session.messages.order_by('-created_at', '-id')[: max(config.max_history_messages, 4)])
    history.reverse()
    return [
        {'role': item.role, 'content': item.content}
        for item in history
        if item.role in {AIOpsChatMessage.ROLE_USER, AIOpsChatMessage.ROLE_ASSISTANT}
    ]


def _tool_allowed(user, tool_name):
    if tool_name == 'query_cmdb_items':
        return user_has_permissions(user, ['cmdb.ci.view'])
    if tool_name == 'query_hosts':
        return user_has_permissions(user, ['ops.host.view'])
    if tool_name == 'query_cost_report':
        return user_has_permissions(user, ['cmdb.ci.view'])
    if tool_name == 'query_observability':
        return any([
            user_has_permissions(user, ['ops.alert.view']),
            user_has_permissions(user, ['ops.log.entry.view']),
            user_has_permissions(user, ['ops.log.query']),
            user_has_permissions(user, ['ops.trace.view']),
            user_has_permissions(user, ['ops.deployment.view']),
            user_has_permissions(user, ['ops.iac.view']),
        ])
    if tool_name == 'query_workorders':
        return user_has_permissions(user, ['ops.ticket.view']) or user_has_permissions(user, ['ops.deployment.view'])
    if tool_name == 'query_task_center':
        return user_has_permissions(user, ['ops.host.execute'])
    if tool_name == 'query_event_wall':
        return user_has_permissions(user, ['eventwall.view'])
    if tool_name == 'query_container_assets':
        return user_has_permissions(user, ['ops.k8s.view']) or user_has_permissions(user, ['ops.docker.view'])
    if tool_name == 'query_k8s_cluster_summary':
        return user_has_permissions(user, ['ops.k8s.view'])
    if tool_name == 'query_middleware_assets':
        return user_has_permissions(user, ['ops.nginx.view']) or user_has_permissions(user, ['ops.middleware.view'])
    if tool_name == 'query_resources':
        return any([
            user_has_permissions(user, ['ops.host.view']),
            user_has_permissions(user, ['cmdb.ci.view']),
            user_has_permissions(user, ['ops.multicloud.view']),
            user_has_permissions(user, ['ops.iac.view']),
            user_has_permissions(user, ['ops.k8s.view']),
            user_has_permissions(user, ['ops.docker.view']),
            user_has_permissions(user, ['ops.nginx.view']),
            user_has_permissions(user, ['ops.log.datasource.view']),
        ])
    if tool_name == 'query_alerts':
        return user_has_permissions(user, ['ops.alert.view'])
    if tool_name == 'query_events':
        return user_has_permissions(user, ['eventwall.view'])
    if tool_name == 'query_logs':
        return user_has_permissions(user, ['ops.log.entry.view']) or user_has_permissions(user, ['ops.log.query'])
    if tool_name == 'query_traces':
        return user_has_permissions(user, ['ops.trace.view'])
    if tool_name == 'query_recent_changes':
        return user_has_permissions(user, ['ops.deployment.view']) or user_has_permissions(user, ['ops.iac.view'])
    if tool_name == 'query_host_tasks':
        return user_has_permissions(user, ['ops.host.execute'])
    if tool_name == 'generate_host_task':
        return user_has_permissions(user, ['aiops.task.generate'])
    return False


def _tool_specs_for_runtime(active_mcp_servers, user):
    tool_names = []
    for server in active_mcp_servers:
        for tool_name in server.tool_whitelist or []:
            if tool_name not in tool_names and _tool_allowed(user, tool_name):
                tool_names.append(tool_name)

    catalog = {
        'query_cmdb_items': {
            'description': '查询平台 CMDB 配置项。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_hosts': {
            'description': '查询主机中心中的主机，适合“生产环境有哪些离线主机”这类问题。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'status': {'type': 'string', 'enum': ['online', 'offline']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_cost_report': {
            'description': '查询 CMDB 成本分析，适合“数据平台生产环境月成本多少”这类问题。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'business_line': {'type': 'string'}, 'month': {'type': 'string', 'description': 'YYYY-MM'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_observability': {
            'description': '查询可观测性信息，包括告警、日志、链路与最近变更。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_workorders': {
            'description': '查询工单系统中的事务工单与应用发布单，支持按业务线、环境、标题和状态筛选。适合“最近电商线生产有哪些工单”这类问题。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_task_center': {
            'description': '查询任务中心中的主机任务。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['pending', 'running', 'success', 'partial', 'failed', 'canceled']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_event_wall': {
            'description': '查询事件墙中的关键事件。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_container_assets': {
            'description': '查询容器管理中的 Kubernetes 集群与 Docker 主机。若用户明确问某个集群是否有异常 Pod，优先使用 query_k8s_cluster_summary。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_k8s_cluster_summary': {
            'description': '查询 K8s 集群摘要，适合“app-prod-k8s集群有没有异常的pod”这类问题。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'cluster_name': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_middleware_assets': {
            'description': '查询中间件管理中的 Nginx、Redis、RocketMQ、Elasticsearch 状态。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_resources': {
            'description': '查询平台资源，包括主机、CMDB、多云、IaC、中间件与日志数据源。若用户明确问离线主机、成本、K8s 异常 Pod，优先改用 query_hosts、query_cost_report、query_k8s_cluster_summary。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_alerts': {
            'description': '查询告警中心中的告警。注意：如果用户明确提到“链路追踪、Trace、调用链、tracing 里的服务”，不要使用本工具，必须改用 query_traces。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'level': {'type': 'string', 'enum': ['critical', 'warning', 'info']}, 'only_unacknowledged': {'type': 'boolean'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_events': {
            'description': '查询事件墙中的关键事件。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_logs': {
            'description': '查询日志中心日志。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_traces': {
            'description': '查询链路追踪/Trace/调用链数据，支持 SkyWalking、Jaeger、Zipkin、Tempo 真实数据源。用户问“链路追踪里的服务 xxx 最近有没有异常/错误/慢调用”时必须使用本工具；query 只保留服务名或 traceId，例如 bcp-server@梧桐港-SaaS-PRO；有“异常/错误/失败”时 errors_only=true。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'errors_only': {'type': 'boolean'}, 'duration_minutes': {'type': 'integer', 'minimum': 5, 'maximum': 1440}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_recent_changes': {
            'description': '查询最近发布与 IaC 变更。',
            'parameters': {'type': 'object', 'properties': {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'query_host_tasks': {
            'description': '查询任务中心的主机任务。',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['pending', 'running', 'success', 'partial', 'failed', 'canceled']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}},
        },
        'generate_host_task': {
            'description': '生成任务中心主机任务；当用户明确要求生成、创建、新建巡检任务或运维任务时必须调用。',
            'parameters': {
                'type': 'object',
                'required': ['request_summary'],
                'properties': {
                    'request_summary': {'type': 'string', 'description': '原始任务诉求，例如“生成一份 Redis 巡检任务”。'},
                    'task_kind': {'type': 'string', 'enum': ['refresh_metrics', 'service_status', 'run_command', 'check_connection', 'run_playbook']},
                    'environment': {'type': 'string', 'enum': ['prod', 'test', 'dev']},
                    'target_status': {'type': 'string', 'enum': ['all', 'offline']},
                    'service_name': {'type': 'string'},
                    'command': {'type': 'string'},
                    'playbook_content': {'type': 'string'},
                    'target_host_ids': {'type': 'array', 'items': {'type': 'integer'}},
                    'max_hosts': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                },
            },
        },
    }

    catalog['query_alerts'] = {
        'description': '查询告警中心中的告警。适合“当前未确认的严重告警有哪些”“分析生产 order-center 最近异常”这类问题。涉及级别或确认状态时，优先填写 level 与 only_unacknowledged；query 只保留环境、主机名、服务名、告警标题等关键词，不要把 severity、acknowledged、status 之类过滤条件写进 query。',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': '仅用于主机名、服务名、告警标题、来源等文本检索；不用于级别和确认状态过滤。',
                },
                'level': {
                    'type': 'string',
                    'enum': ['critical', 'warning', 'info'],
                    'description': '告警级别。用户提到严重/高危时填 critical，提到警告时填 warning。',
                },
                'only_unacknowledged': {
                    'type': 'boolean',
                    'description': '只看未确认告警。用户提到未确认、未认领、未处理时填 true。',
                },
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
        },
    }

    catalog['query_observability'] = {
        'description': '查询可观测性综合信息，用于跨告警、日志、链路、变更做关联分析。若用户只是在直接查询告警列表、告警数量、严重级别或确认状态，优先使用 query_alerts，不要改用本工具。',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
        },
    }

    catalog['query_alerts']['description'] += ' 如果用户明确提到“链路追踪、Trace、调用链、tracing 里的服务”，不要使用本工具，必须改用 query_traces。'
    catalog['query_traces']['description'] = '查询链路追踪/Trace/调用链数据，支持 SkyWalking、Jaeger、Zipkin、Tempo 真实数据源。用户问“链路追踪里的服务 xxx 最近有没有异常/错误/慢调用”时必须使用本工具；query 只保留服务名或 traceId，例如 bcp-server@梧桐港-SaaS-PRO；有“异常/错误/失败”时 errors_only=true。'
    catalog['query_traces']['parameters'] = {
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'description': '服务名或 traceId，例如 bcp-server@梧桐港-SaaS-PRO。不要把“链路追踪、最近、有无异常”等描述词放进 query。'},
            'errors_only': {'type': 'boolean'},
            'duration_minutes': {'type': 'integer', 'minimum': 5, 'maximum': 1440},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
        },
    }

    return [
        {'type': 'function', 'function': {'name': tool_name, 'description': catalog[tool_name]['description'], 'parameters': catalog[tool_name]['parameters']}}
        for tool_name in tool_names
        if tool_name in catalog
    ]


def _discover_external_mcp_tools(server, client_session):
    whitelist = set(server.tool_whitelist or [])
    discovered = []
    for tool in client_session.list_tools():
        raw_name = tool.get('name')
        if not raw_name:
            continue
        if whitelist and raw_name not in whitelist:
            continue
        discovered.append(tool)
    return discovered


def _build_runtime_tool_registry(active_mcp_servers, user):
    tool_specs = []
    registry = {}
    managed_clients = []

    builtin_specs = _tool_specs_for_runtime([item for item in active_mcp_servers if item.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN], user)
    tool_specs.extend(builtin_specs)
    for spec in builtin_specs:
        registry[spec['function']['name']] = {'kind': 'internal', 'tool_name': spec['function']['name']}

    for server in active_mcp_servers:
        if server.server_type == AIOpsMCPServer.SERVER_PLATFORM_BUILTIN:
            continue
        try:
            client_session = _create_mcp_client_session(server)
            client_session.initialize()
            managed_clients.append(client_session)
            for tool in _discover_external_mcp_tools(server, client_session):
                raw_name = tool.get('name')
                alias_name = _build_mcp_tool_alias(server, raw_name)
                description = tool.get('description') or f'{server.name} / {raw_name}'
                input_schema = tool.get('inputSchema') or {'type': 'object', 'properties': {}}
                tool_specs.append({
                    'type': 'function',
                    'function': {'name': alias_name, 'description': description, 'parameters': input_schema},
                })
                registry[alias_name] = {
                    'kind': 'external',
                    'server': server,
                    'client_session': client_session,
                    'raw_tool_name': raw_name,
                }
        except Exception:
            if 'client_session' in locals():
                try:
                    client_session.close()
                except Exception:
                    pass
            continue
    return tool_specs, registry, managed_clients


def _summarize_external_tool_result(registry_entry, result):
    server = registry_entry['server']
    raw_tool_name = registry_entry['raw_tool_name']
    items = []
    for content_item in result.get('content') or []:
        if content_item.get('type') == 'text' and content_item.get('text'):
            items.append(content_item['text'][:200])
    if not items and result.get('structuredContent'):
        items.append(json.dumps(result.get('structuredContent'), ensure_ascii=False, default=_json_default)[:240])
    if not items:
        items.append('外部 MCP 工具已返回结果。')
    return {
        'tool_output': result,
        'sections': [{'title': f"{server.name} / {raw_tool_name}", 'items': items[:4]}],
        'citations': [],
        'message_type': AIOpsChatMessage.TYPE_TEXT,
    }


def _parse_tool_arguments(raw_arguments):
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not raw_arguments:
        return {}
    try:
        return json.loads(raw_arguments)
    except (TypeError, ValueError):
        return {}


def _run_tool_call(session, user_message, user, tool_name, arguments, registry_entry=None):
    if registry_entry and registry_entry.get('kind') == 'external':
        started_at = time.time()
        invocation = _create_tool_invocation(
            session,
            user_message,
            f"mcp::{registry_entry['server'].name}::{registry_entry['raw_tool_name']}",
            arguments,
        )
        try:
            result = registry_entry['client_session'].call_tool(registry_entry['raw_tool_name'], arguments)
            _finish_tool_invocation(
                invocation,
                {'server': registry_entry['server'].name, 'tool': registry_entry['raw_tool_name'], 'is_error': bool(result.get('isError'))},
                started_at,
                success=not bool(result.get('isError')),
            )
            return _summarize_external_tool_result(registry_entry, result)
        except Exception as exc:
            _finish_tool_invocation(invocation, {'error': str(exc)}, started_at, success=False)
            return {
                'tool_output': {'error': str(exc)},
                'sections': [{'title': f"{registry_entry['server'].name} / {registry_entry['raw_tool_name']}", 'items': [str(exc)]}],
                'citations': [],
                'message_type': AIOpsChatMessage.TYPE_TEXT,
            }

    if tool_name == 'query_cmdb_items':
        result = query_cmdb_items(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_hosts':
        result = query_hosts(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_cost_report':
        result = query_cost_report(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), business_line=arguments.get('business_line', ''), month=arguments.get('month', ''), limit=arguments.get('limit') or 5)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_observability':
        result = query_observability(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_workorders':
        result = query_workorders(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_task_center':
        result = query_task_center(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_event_wall':
        result = query_event_wall(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_container_assets':
        result = query_container_assets(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_k8s_cluster_summary':
        result = query_k8s_cluster_summary(session, user_message, user, query=arguments.get('query', ''), cluster_name=arguments.get('cluster_name', ''), limit=arguments.get('limit') or 1)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_middleware_assets':
        result = query_middleware_assets(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_resources':
        result = query_resources(session, user_message, user, query=arguments.get('query', ''), environment=arguments.get('environment', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'query_alerts':
        result = query_alerts(session, user_message, user, query=arguments.get('query', ''), level=arguments.get('level', ''), only_unacknowledged=bool(arguments.get('only_unacknowledged')), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_events':
        result = query_events(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 8)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_logs':
        result = query_logs(session, user_message, user, query=arguments.get('query', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_traces':
        result = query_traces(
            session,
            user_message,
            user,
            query=arguments.get('query', ''),
            errors_only=bool(arguments.get('errors_only')),
            limit=arguments.get('limit') or 6,
            duration_minutes=arguments.get('duration_minutes') or 60,
        )
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_recent_changes':
        result = query_recent_changes(session, user_message, user, limit=arguments.get('limit') or 5)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_ANALYSIS}
    if tool_name == 'query_host_tasks':
        result = query_host_tasks(session, user_message, user, query=arguments.get('query', ''), status=arguments.get('status', ''), limit=arguments.get('limit') or 6)
        return {'tool_output': result, 'sections': result.get('sections', []), 'citations': result.get('citations', []), 'message_type': AIOpsChatMessage.TYPE_TEXT}
    if tool_name == 'generate_host_task':
        started_at = time.time()
        invocation = _create_tool_invocation(session, user_message, 'generate_host_task', arguments)
        draft = build_task_draft(user, arguments.get('request_summary', ''), draft_request=arguments)
        if draft.get('error'):
            _finish_tool_invocation(invocation, {'detail': draft['error']}, started_at, success=False)
            return {
                'tool_output': draft,
                'sections': [{
                    'title': '任务生成限制',
                    'items': [
                        draft['error'],
                        '请补充目标主机名、应用名或 IP，例如：在生产环境对主机 order-api-ecs-02（10.10.1.11）生成 Redis 巡检任务。',
                    ],
                }],
                'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}],
                'message_type': AIOpsChatMessage.TYPE_ACTION,
            }
        summary = {'name': draft['name'], 'task_type': draft['task_type'], 'host_count': draft['host_count'], 'risk_level': draft['risk_level']}
        _finish_tool_invocation(invocation, summary, started_at, success=True)
        return {
            'tool_output': {'draft': summary, 'requires_confirmation': True},
            'sections': _build_task_sections(draft),
            'citations': [{'title': '任务中心', 'path': '/hosts/tasks'}],
            'message_type': AIOpsChatMessage.TYPE_ACTION,
            'pending_action_draft': draft,
        }
    raise ValueError(f'Unsupported tool: {tool_name}')


def _dispatch_with_tool_runtime(session, user_message, user, question, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    config = get_agent_config()
    provider = get_active_provider(config)
    if not _provider_is_ready(provider):
        setup_hint = get_model_provider_setup_hint(provider)
        emit(
            step={
                'title': '未配置可用模型',
                'detail': setup_hint or '请先在智能体配置中启用并测试默认模型提供商。',
                'status': PROCESSING_STATUS_FAILED,
            },
            text='当前没有可用模型',
        )
        return _build_dispatch_error_result(
            setup_hint or '未配置可用模型，请先在“智能体配置 / 模型提供商”中启用并测试默认模型。',
            code='provider_unavailable',
            message='当前没有可用模型，无法发起问答。',
        )

    active_mcp_servers = _get_selected_mcp_servers(config)
    active_skills = _get_selected_skills(config, user=user)
    if _is_trace_focused_question(question):
        trace_arguments = {
            'query': _extract_quoted_trace_query(question),
            'errors_only': any(keyword in question for keyword in ['异常', '错误', '失败']),
            'duration_minutes': 60 if '最近' in question else 30,
            'limit': 10,
        }
        emit(
            step={
                'title': '链路追踪直连查询',
                'detail': f"针对服务 {trace_arguments['query'] or '-'} 直接查询 Trace。",
                'status': PROCESSING_STATUS_COMPLETED,
            },
            text='正在直连链路追踪查询',
        )
        tool_result = _run_tool_call(session, user_message, user, 'query_traces', trace_arguments)
        citations = _dedupe_citations(tool_result.get('citations', []))
        final_content = _ensure_followup_line(
            _normalize_formatter_output(_build_fallback_answer(
                tool_result.get('sections', []),
                citations,
                question=question,
                collected_tool_outputs=[{'tool_name': 'query_traces', 'tool_output': tool_result.get('tool_output') or {}}],
            )),
            citations,
        )
        return {
            'content': final_content,
            'citations': citations,
            'tool_calls': ['query_traces'],
            'message_type': tool_result.get('message_type') or AIOpsChatMessage.TYPE_ANALYSIS,
            'pending_action_draft': None,
            'metadata': {
                'execution_mode': 'trace_fastpath',
                'formatter_mode': 'fallback',
                'formatter_attempts': 0,
            },
        }
    tools, registry, managed_clients = _build_runtime_tool_registry(active_mcp_servers, user)
    if not tools:
        emit(
            step={
                'title': '\u672a\u53d1\u73b0\u53ef\u7528 MCP \u5de5\u5177',
                'detail': '当前未启用任何 MCP 工具，请先在智能体配置中启用至少一个 MCP。',
                'status': PROCESSING_STATUS_FAILED,
            },
            text='当前没有可用工具',
        )
        return _build_dispatch_error_result(
            '当前未启用任何 MCP 工具，请先在“智能体配置 / MCP”中启用至少一个工具。',
            code='tool_unavailable',
            message='当前没有可用工具，无法处理该问题。',
        )

    emit(
        step={
            'title': '\u52a0\u8f7d MCP \u4e0e Skill',
            'detail': f'\u5df2\u542f\u7528 {len(active_mcp_servers)} \u4e2a MCP\uff0c{len(active_skills)} \u4e2a Skill\u3002',
            'status': PROCESSING_STATUS_COMPLETED,
        },
        text='\u6b63\u5728\u89c4\u5212\u5de5\u5177\u8c03\u7528',
    )

    executed_tool_names = []
    sections = []
    citations = []
    pending_action_draft = None
    message_type = AIOpsChatMessage.TYPE_TEXT
    final_content = ''
    collected_tool_outputs = []

    messages = [
        {'role': 'system', 'content': _build_runtime_prompt(config, active_mcp_servers, active_skills, user)},
        *_build_history_messages(session, config),
    ]
    if any(keyword in question.lower() for keyword in ['链路追踪', '调用链', 'trace', 'tracing']):
        messages.append({
            'role': 'user',
            'content': '路由约束：本问题明确限定在链路追踪/Trace/调用链中排查服务异常，必须调用 query_traces；不要改用 query_alerts。query 参数只传服务名或 traceId，若用户问异常/错误则 errors_only=true。',
        })

    try:
        for round_index in range(6):
            emit(
                step={
                    'title': '\u6a21\u578b\u89c4\u5212',
                    'detail': f'\u7b2c {round_index + 1} \u8f6e\u51b3\u7b56',
                    'status': PROCESSING_STATUS_RUNNING,
                },
                text='\u6b63\u5728\u8bf7\u6c42\u5927\u6a21\u578b\u89c4\u5212',
            )
            completion = _request_model_completion(provider, {
                'model': provider.default_model,
                'temperature': provider.temperature,
                'max_tokens': provider.max_tokens,
                'messages': messages,
                'tools': tools,
                'tool_choice': 'auto',
            })
            choice = ((completion or {}).get('choices') or [{}])[0]
            message = choice.get('message') or {}
            content = (message.get('content') or '').strip()
            tool_calls = message.get('tool_calls') or []

            if tool_calls:
                emit(
                    step={
                        'title': '\u751f\u6210\u5de5\u5177\u8ba1\u5212',
                        'detail': f'\u672c\u8f6e\u51c6\u5907\u8c03\u7528 {len(tool_calls)} \u4e2a\u5de5\u5177\u3002',
                        'status': PROCESSING_STATUS_COMPLETED,
                    },
                    text=f'\u51c6\u5907\u8c03\u7528 {len(tool_calls)} \u4e2a\u5de5\u5177',
                )
                messages.append({'role': 'assistant', 'content': content or '', 'tool_calls': tool_calls})
                for tool_call in tool_calls:
                    function_payload = tool_call.get('function') or {}
                    tool_name = function_payload.get('name', '')
                    registry_entry = registry.get(tool_name)
                    if not registry_entry:
                        continue
                    arguments = _parse_tool_arguments(function_payload.get('arguments'))
                    emit(
                        tool_event={'name': tool_name, 'detail': '\u5f00\u59cb\u8c03\u7528', 'status': PROCESSING_STATUS_RUNNING},
                        text=f'\u6b63\u5728\u8c03\u7528 {tool_name}',
                    )
                    tool_result = _run_tool_call(session, user_message, user, tool_name, arguments, registry_entry=registry_entry)
                    executed_tool_names.append(tool_name)
                    collected_tool_outputs.append({'tool_name': tool_name, 'tool_output': tool_result.get('tool_output') or {}})
                    sections.extend(tool_result.get('sections', []))
                    citations.extend(tool_result.get('citations', []))
                    if tool_result.get('pending_action_draft'):
                        pending_action_draft = tool_result['pending_action_draft']
                    if tool_result.get('message_type') == AIOpsChatMessage.TYPE_ACTION:
                        message_type = AIOpsChatMessage.TYPE_ACTION
                    elif tool_result.get('message_type') == AIOpsChatMessage.TYPE_ANALYSIS and message_type != AIOpsChatMessage.TYPE_ACTION:
                        message_type = AIOpsChatMessage.TYPE_ANALYSIS
                    tool_output = tool_result.get('tool_output') or {}
                    tool_status = PROCESSING_STATUS_FAILED if isinstance(tool_output, dict) and tool_output.get('error') else PROCESSING_STATUS_COMPLETED
                    emit(
                        tool_event={'name': tool_name, 'detail': _summarize_tool_result(tool_result), 'status': tool_status},
                        text=f'{tool_name} \u8c03\u7528\u5b8c\u6210',
                    )
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call.get('id'),
                        'content': json.dumps(tool_result.get('tool_output') or {}, ensure_ascii=False, default=_json_default),
                    })
                continue

            final_content = content
            if not executed_tool_names:
                if round_index < 1:
                    messages.append({
                        'role': 'user',
                        'content': '你上一轮没有调用任何工具。请重新决策，并且这一次必须至少调用 1 个最相关的工具后再回答；不要直接自由作答。',
                    })
                    continue
                emit(
                    step={
                        'title': '未命中任何工具',
                        'detail': '模型未调用任何工具，当前策略不允许直接自由回答。',
                        'status': PROCESSING_STATUS_FAILED,
                    },
                    text='模型未命中任何工具',
                )
                return _build_dispatch_error_result(
                    '模型未调用任何工具，请检查当前模型是否支持 tool-calling，或检查 MCP/Skill 配置是否完整。',
                    code='no_tool_called',
                    message='模型未调用任何工具，无法完成问答。',
                )
            emit(
                step={
                    'title': '\u751f\u6210\u56de\u590d',
                    'detail': '\u6a21\u578b\u5df2\u8fd4\u56de\u6700\u7ec8\u56de\u7b54\u3002',
                    'status': PROCESSING_STATUS_COMPLETED,
                },
                text='\u6b63\u5728\u6574\u7406\u56de\u7b54',
            )
            break
    except Exception as exc:
        emit(
            step={
                'title': 'MCP \u5de5\u5177\u94fe\u5f02\u5e38',
                'detail': str(exc)[:120],
                'status': PROCESSING_STATUS_FAILED,
            },
            text='模型或工具调用失败',
        )
        if sections or collected_tool_outputs:
            citations = _dedupe_citations(citations)
            final_content = _ensure_followup_line(
                _normalize_formatter_output(_build_fallback_answer(
                    sections,
                    citations,
                    pending_action_draft=pending_action_draft,
                    question=question,
                    collected_tool_outputs=collected_tool_outputs,
                )),
                citations,
            )
            return {
                'content': final_content,
                'citations': citations,
                'tool_calls': executed_tool_names,
                'message_type': message_type,
                'pending_action_draft': pending_action_draft,
                'metadata': {
                    'execution_mode': 'mcp_skills',
                    'formatter_mode': 'fallback',
                    'formatter_attempts': 0,
                    'fallback_reason': str(exc)[:300],
                },
            }
        return _build_dispatch_error_result(
            str(exc),
            code='runtime_error',
            message='模型或工具调用失败，请检查模型与 MCP 配置。',
        )
    finally:
        for client in managed_clients:
            try:
                client.close()
            except Exception:
                pass

    citations = _dedupe_citations(citations)
    emit(
        step={
            'title': '生成回复',
            'detail': '已基于工具结果直接生成回答草稿。',
            'status': PROCESSING_STATUS_COMPLETED,
        },
        text='正在准备 Skill 模板整形',
    )
    if not final_content:
        final_content = _build_fallback_answer(
            sections,
            citations,
            pending_action_draft=pending_action_draft,
            question=question,
            collected_tool_outputs=collected_tool_outputs,
        )
    elif _content_conflicts_with_tool_facts(final_content, collected_tool_outputs):
        final_content = _build_fallback_answer(
            sections,
            citations,
            pending_action_draft=pending_action_draft,
            question=question,
            collected_tool_outputs=collected_tool_outputs,
        )

    formatter_result = None
    if provider:
        emit(
            step={
                'title': 'Skill 模板整形',
                'detail': '基于回答草稿与 MCP 工具事实进行二阶段回答整形。',
                'status': PROCESSING_STATUS_COMPLETED,
            },
            text='正在进行 Skill 模板整形',
        )
        try:
            formatter_result = _run_answer_formatter(
                provider,
                question=question,
                draft_content=final_content,
                sections=sections,
                citations=citations,
                tool_calls=executed_tool_names,
                pending_action_draft=pending_action_draft,
                message_type=message_type,
                active_skills=active_skills,
                collected_tool_outputs=collected_tool_outputs,
            )
            if formatter_result.get('used'):
                final_content = _normalize_formatter_output(formatter_result.get('content') or final_content)
            if (
                formatter_result.get('fell_back')
                or _content_conflicts_with_tool_facts(final_content, collected_tool_outputs)
                or _should_prefer_structured_alert_answer(final_content, formatter_result.get('fallback_content', ''), collected_tool_outputs)
            ):
                final_content = formatter_result.get('fallback_content') or _build_fallback_answer(
                    sections,
                    citations,
                    pending_action_draft=pending_action_draft,
                    question=question,
                    collected_tool_outputs=collected_tool_outputs,
                )
                emit(
                    step={
                        'title': 'Skill 模板整形',
                        'detail': '二阶段回复不符合约束，已回退到代码兜底模板。',
                        'status': PROCESSING_STATUS_FAILED,
                    },
                    text='Skill 模板整形已回退到代码模板',
                )
        except Exception:
            final_content = _build_fallback_answer(
                sections,
                citations,
                pending_action_draft=pending_action_draft,
                question=question,
                collected_tool_outputs=collected_tool_outputs,
            )
            emit(
                step={
                    'title': 'Skill 模板整形',
                    'detail': '二阶段回复不符合约束，已回退到代码兜底模板。',
                    'status': PROCESSING_STATUS_FAILED,
                },
                text='Skill 模板整形已回退到代码模板',
            )
    final_content = _ensure_followup_line(_normalize_formatter_output(final_content), citations)

    return {
        'content': final_content,
        'citations': citations,
        'tool_calls': executed_tool_names,
        'message_type': message_type,
        'pending_action_draft': pending_action_draft,
        'metadata': {
            'execution_mode': 'mcp_skills',
            'formatter_mode': (
                'fallback'
                if formatter_result and formatter_result.get('fell_back')
                else 'skill'
                if formatter_result and formatter_result.get('used')
                else 'draft_only'
            ),
            'formatter_attempts': (formatter_result or {}).get('attempts', 0),
        },
    }


def _build_chat_result(session, user_message, user, question, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    emit(
        status_value=PROCESSING_STATUS_RUNNING,
        text='已收到问题，正在准备上下文',
    )
    try:
        result = _dispatch_with_tool_runtime(session, user_message, user, question, progress_callback=emit)
        if result:
            return result
    except Exception as exc:
        emit(
            step={'title': '\u5904\u7406\u5f02\u5e38', 'detail': str(exc)[:120], 'status': PROCESSING_STATUS_FAILED},
            text='\u95ee\u7b54\u5931\u8d25',
        )
        return _build_dispatch_error_result(str(exc))
    return _build_dispatch_error_result('\u672a\u83b7\u5f97\u5230\u6709\u6548\u56de\u7b54')



def _stream_dispatch_result(message_id, payload, progress_callback=None):
    emit = progress_callback or (lambda **kwargs: None)
    final_content = payload.get('content') or ''
    message_type = payload.get('message_type') or AIOpsChatMessage.TYPE_TEXT
    citations = payload.get('citations') or []
    tool_calls = payload.get('tool_calls') or []
    metadata_updates = dict(payload.get('metadata') or {})

    emit(
        status_value=PROCESSING_STATUS_STREAMING,
        text='\u6b63\u5728\u8f93\u51fa\u56de\u590d',
    )

    if not final_content:
        _update_chat_message_processing(
            message_id,
            status_value=PROCESSING_STATUS_COMPLETED,
            text='\u5206\u6790\u5b8c\u6210',
            content=final_content,
            message_type=message_type,
            citations=citations,
            tool_calls=tool_calls,
            metadata_updates=metadata_updates,
        )
        return

    frame_count = min(10, max(3, (len(final_content) + 119) // 120))
    chunk_size = max(1, (len(final_content) + frame_count - 1) // frame_count)
    for cursor in range(chunk_size, len(final_content), chunk_size):
        _update_chat_message_processing(
            message_id,
            status_value=PROCESSING_STATUS_STREAMING,
            text='\u6b63\u5728\u8f93\u51fa\u56de\u590d',
            content=final_content[:cursor],
            message_type=message_type,
            metadata_updates=metadata_updates,
        )
        time.sleep(0.08)

    _update_chat_message_processing(
        message_id,
        status_value=PROCESSING_STATUS_COMPLETED,
        text='\u5206\u6790\u5b8c\u6210',
        content=final_content,
        message_type=message_type,
        citations=citations,
        tool_calls=tool_calls,
        metadata_updates=metadata_updates,
    )



def _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=False, progress_callback=None, question=''):
    config = get_agent_config()
    assistant_message.refresh_from_db()
    final_content = result.get('content', '')
    merged_metadata = {**(assistant_message.metadata or {}), **(result.get('metadata') or {})}
    pending_action = None
    draft = result.get('pending_action_draft')

    if draft and not draft.get('error'):
        if _should_materialize_host_task(question, result, draft):
            try:
                task = _create_host_task_record_from_draft(draft, user, session=session)
                pending_action = create_pending_task_action_from_draft(session, assistant_message, draft)
                pending_action.status = AIOpsPendingAction.STATUS_CONFIRMED
                pending_action.confirmed_by = user.username
                pending_action.confirmed_at = timezone.now()
                pending_action.result_payload = {
                    'task_id': task.id,
                    'task_name': task.name,
                    'materialized_in_task_center': True,
                }
                pending_action.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'result_payload', 'updated_at'])
                merged_metadata['pending_action_id'] = pending_action.id
                merged_metadata['created_task_id'] = task.id
                merged_metadata['task_materialized_in_center'] = True
                final_content = f"{final_content}\n\n已在任务中心创建待执行任务：{task.name}（#{task.id}）。"
            except ValueError as exc:
                merged_metadata['task_materialization_error'] = str(exc)[:200]
                final_content = f"{final_content}\n\n任务中心创建失败：{exc}"
        elif not config.allow_action_execution:
            merged_metadata['action_execution_disabled'] = True
        else:
            pending_action = create_pending_task_action_from_draft(session, assistant_message, draft)
            merged_metadata['pending_action_id'] = pending_action.id
            if not config.require_confirmation and user_has_permissions(user, ['aiops.task.execute', 'ops.host.execute']):
                try:
                    task = confirm_action(pending_action, user)
                    pending_action.refresh_from_db()
                    final_content = f"{final_content}\n\n\u5df2\u6839\u636e\u5f53\u524d\u914d\u7f6e\u81ea\u52a8\u6267\u884c\u4efb\u52a1\uff1a{task.name}\uff08#{task.id}\uff09\u3002"
                except ValueError:
                    pending_action.refresh_from_db()

    payload = {
        'content': final_content,
        'message_type': result.get('message_type') or AIOpsChatMessage.TYPE_TEXT,
        'citations': result.get('citations') or [],
        'tool_calls': result.get('tool_calls') or [],
        'metadata': {**merged_metadata, 'processing_status': PROCESSING_STATUS_COMPLETED, 'processing_text': '\u5206\u6790\u5b8c\u6210'},
    }

    if enable_stream:
        _stream_dispatch_result(assistant_message.id, payload, progress_callback=progress_callback)
    else:
        assistant_message.message_type = payload['message_type']
        assistant_message.content = payload['content']
        assistant_message.citations = payload['citations']
        assistant_message.tool_calls = payload['tool_calls']
        assistant_message.metadata = payload['metadata']
        assistant_message.save(update_fields=['message_type', 'content', 'citations', 'tool_calls', 'metadata'])

    _touch_chat_session(session, question=question or payload['content'] or session.title)
    return assistant_message, pending_action



def _run_async_chat_worker(session_id, user_message_id, user_id, assistant_message_id, question):
    close_old_connections()
    try:
        session = AIOpsChatSession.objects.select_related('user').get(pk=session_id)
        user_message = AIOpsChatMessage.objects.get(pk=user_message_id)
        assistant_message = AIOpsChatMessage.objects.get(pk=assistant_message_id)
        user = session.user if session.user_id == user_id else session.user.__class__.objects.get(pk=user_id)
        emit = _make_processing_callback(assistant_message_id)
        result = _build_chat_result(session, user_message, user, question, progress_callback=emit)
        _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=True, progress_callback=emit, question=question)
    except Exception as exc:
        _update_chat_message_processing(
            assistant_message_id,
            status_value=PROCESSING_STATUS_FAILED,
            text='\u95ee\u7b54\u5931\u8d25',
            step={'title': '\u5904\u7406\u5931\u8d25', 'detail': str(exc)[:120], 'status': PROCESSING_STATUS_FAILED},
            content=f'\u95ee\u7b54\u5931\u8d25\uff1a{str(exc)}',
            message_type=AIOpsChatMessage.TYPE_ERROR,
            metadata_updates={'execution_mode': 'error', 'error_detail': str(exc)[:500]},
        )
        session = AIOpsChatSession.objects.filter(pk=session_id).first()
        if session:
            _touch_chat_session(session, question=question)
    finally:
        close_old_connections()



def start_async_chat_processing(session, user_message, user, assistant_message):
    worker = threading.Thread(
        target=_run_async_chat_worker,
        kwargs={
            'session_id': session.id,
            'user_message_id': user_message.id,
            'user_id': user.id,
            'assistant_message_id': assistant_message.id,
            'question': user_message.content,
        },
        daemon=True,
        name=f'aiops-chat-{assistant_message.id}',
    )
    worker.start()
    return worker



def dispatch_chat(session, user_message, user, question):
    assistant_message = AIOpsChatMessage.objects.create(
        session=session,
        role=AIOpsChatMessage.ROLE_ASSISTANT,
        message_type=AIOpsChatMessage.TYPE_TEXT,
        content='',
        citations=[],
        tool_calls=[],
        metadata={},
    )
    emit = _make_processing_callback(assistant_message.id)
    result = _build_chat_result(session, user_message, user, question, progress_callback=emit)
    return _apply_dispatch_result_to_message(session, assistant_message, result, user, enable_stream=False, progress_callback=emit, question=question)


def build_audit_overview():
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        'sessions_today': AIOpsChatSession.objects.filter(created_at__gte=today_start, mirror_source__isnull=True).count(),
        'messages_today': AIOpsChatMessage.objects.filter(created_at__gte=today_start, session__mirror_source__isnull=True).count(),
        'actions_today': AIOpsPendingAction.objects.filter(created_at__gte=today_start, mirror_source__isnull=True, session__mirror_source__isnull=True).count(),
        'failed_actions_today': AIOpsPendingAction.objects.filter(created_at__gte=today_start, status=AIOpsPendingAction.STATUS_FAILED, mirror_source__isnull=True, session__mirror_source__isnull=True).count(),
        'providers_total': AIOpsModelProvider.objects.count(),
        'mcp_total': AIOpsMCPServer.objects.filter(is_enabled=True).count(),
    }
