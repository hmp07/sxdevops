from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.models import EventRecord
from eventwall.services import record_event
from ops.models import Alert, DockerHost, GrafanaSetting, K8sCluster, LogDataSource, ObservabilityDataSourceLink, SystemPostureEnvironment, TaskResource, TaskResourceGroup, TracingDataSource
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import is_demo_account, user_has_permissions

from .models import (
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsKnowledgeEnvironment,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsSkill,
    AIOpsToolInvocation,
)
from .serializers import (
    AIOpsAgentConfigSerializer,
    AIOpsAuditSessionSerializer,
    AIOpsChatInputSerializer,
    AIOpsChatMessageSerializer,
    AIOpsChatSessionSerializer,
    AIOpsCreateSessionSerializer,
    AIOpsKnowledgeEnvironmentSerializer,
    AIOpsMCPServerSerializer,
    AIOpsModelProviderSerializer,
    AIOpsPendingActionSerializer,
    AIOpsSkillSerializer,
    AIOpsToolInvocationSerializer,
)
from .services import (
    bootstrap_payload_for_user,
    build_audit_overview,
    cancel_action,
    confirm_action,
    dispatch_chat,
    get_agent_config,
    list_model_provider_models,
    list_model_provider_presets,
    list_mcp_server_tools,
    recover_masked_suggested_question,
    start_async_chat_processing,
    sync_admin_sessions_to_demo,
    sync_session_to_demo_if_needed,
    test_model_provider_connection,
    test_mcp_server_connection,
)
from .knowledge_graph import build_knowledge_graph

K8S_NAMESPACE_OPTIONS_CACHE_TTL = 60
K8S_NAMESPACE_OPTIONS_STALE_CACHE_TTL = 300


DEMO_CHAT_DISABLED_MESSAGE = '演示账号问答权限已临时关闭，如需体验请联系作者：592095766@qq.com'


class AIOpsModelProviderViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AIOpsModelProvider.objects.all()
    serializer_class = AIOpsModelProviderSerializer
    pagination_class = None
    search_fields = ['name', 'provider_type', 'base_url', 'default_model']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
        'test_connection': ['aiops.config.manage'],
        'list_models': ['aiops.config.manage'],
        'presets': ['aiops.config.view'],
    }

    @action(detail=False, methods=['get'])
    def presets(self, request):
        return Response({'presets': list_model_provider_presets()})

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        provider = self.get_object()
        try:
            result = test_model_provider_connection(provider)
            provider.last_test_status = (
                AIOpsModelProvider.STATUS_SUCCESS
                if result.get('status') == 'success'
                else AIOpsModelProvider.STATUS_FAILED
            )
            provider.last_test_message = result.get('message') or '模型测试完成'
            payload = result
            status_code = status.HTTP_200_OK if result.get('status') == 'success' else status.HTTP_400_BAD_REQUEST
        except Exception as exc:
            provider.last_test_status = AIOpsModelProvider.STATUS_FAILED
            provider.last_test_message = str(exc)[:255]
            payload = {'status': 'failed', 'message': str(exc)}
            status_code = status.HTTP_400_BAD_REQUEST
        provider.save(update_fields=['last_test_status', 'last_test_message', 'updated_at'])
        return Response(payload, status=status_code)

    @action(detail=True, methods=['get'], url_path='models')
    def list_models(self, request, pk=None):
        provider = self.get_object()
        probe = str(request.query_params.get('probe', 'true')).lower() not in {'0', 'false', 'no'}
        try:
            return Response(list_model_provider_models(provider, probe=probe))
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.config.view')])
def model_provider_presets(request):
    return Response({'presets': list_model_provider_presets()})


class AIOpsMCPServerViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsMCPServerSerializer
    pagination_class = None
    search_fields = ['name', 'description', 'endpoint_or_command']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
        'test_connection': ['aiops.config.manage'],
        'list_tools': ['aiops.config.manage'],
    }

    def get_queryset(self):
        get_agent_config()
        return AIOpsMCPServer.objects.all().order_by('is_builtin', 'name', 'id')

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        server = self.get_object()
        try:
            result = test_mcp_server_connection(server)
            return Response(result)
        except Exception as exc:
            return Response({'status': 'failed', 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def list_tools(self, request, pk=None):
        server = self.get_object()
        try:
            result = list_mcp_server_tools(server)
            return Response(result)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_builtin:
            return Response({'detail': '内置 MCP 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class AIOpsSkillViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsSkillSerializer
    pagination_class = None
    search_fields = ['name', 'slug', 'description']
    rbac_permissions = {
        'list': ['aiops.config.view'],
        'retrieve': ['aiops.config.view'],
        'create': ['aiops.config.manage'],
        'update': ['aiops.config.manage'],
        'partial_update': ['aiops.config.manage'],
        'destroy': ['aiops.config.manage'],
    }

    def get_queryset(self):
        get_agent_config()
        return AIOpsSkill.objects.all().order_by('is_builtin', 'name', 'id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_builtin:
            return Response({'detail': '内置 Skill 不允许删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


def _clean_catalog_value(value):
    return str(value or '').strip()


def _is_demoish_catalog_item(*values):
    text = ' '.join(str(value or '') for value in values).lower()
    return any(keyword in text for keyword in ['demo', '演示', '示例', '样例'])


def _is_invalid_environment_value(value):
    text = _clean_catalog_value(value)
    if not text:
        return True
    lowered = text.lower()
    return (
        lowered.startswith('env-')
        or set(text) == {'?'}
        or text in {'未知', 'unknown', 'null', 'none', '-'}
    )


def _grafana_folder_key(value):
    text = _clean_catalog_value(value)
    return text


def _k8s_namespace_options_cache_key(cluster_id):
    return f'aiops:k8s:namespaces:{cluster_id}'


def _k8s_namespace_options(cluster):
    try:
        from ops.k8s_views import DEMO_NAMESPACES, _get_k8s_client, _is_demo
    except Exception:
        return []
    try:
        if _is_demo(cluster):
            return [
                item.get('name')
                for item in DEMO_NAMESPACES
                if item.get('name')
            ]
        cache_key = _k8s_namespace_options_cache_key(cluster.id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        k8s = _get_k8s_client(cluster)
        v1 = k8s.CoreV1Api()
        data = sorted([
            item.metadata.name
            for item in v1.list_namespace().items
            if item.metadata and item.metadata.name
        ])
        cache.set(cache_key, data, K8S_NAMESPACE_OPTIONS_CACHE_TTL)
        cache.set(f'{cache_key}:stale', data, K8S_NAMESPACE_OPTIONS_STALE_CACHE_TTL)
        return data
    except Exception:
        stale = cache.get(f"{_k8s_namespace_options_cache_key(cluster.id)}:stale")
        if stale is not None:
            return stale
        return []


class AIOpsKnowledgeEnvironmentViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsKnowledgeEnvironmentSerializer
    pagination_class = None
    search_fields = ['name', 'description']
    demo_account_allowed_actions = {'create', 'update', 'partial_update', 'destroy'}
    rbac_permissions = {
        'list': ['aiops.knowledge.view'],
        'retrieve': ['aiops.knowledge.view'],
        'catalog': ['aiops.knowledge.view'],
        'create': ['aiops.knowledge.manage'],
        'update': ['aiops.knowledge.manage'],
        'partial_update': ['aiops.knowledge.manage'],
        'destroy': ['aiops.knowledge.manage'],
    }

    def get_queryset(self):
        return AIOpsKnowledgeEnvironment.objects.all().order_by('name', 'id')

    @action(detail=False, methods=['get'])
    def catalog(self, request):
        event_environments = list(
            EventRecord.objects
            .filter(is_demo=False)
            .exclude(source_type=EventRecord.SOURCE_SEED)
            .exclude(environment='')
            .values_list('environment', flat=True)
            .distinct()
            .order_by('environment')[:100]
        )
        alert_environments = list(
            Alert.objects
            .exclude(environment='')
            .values_list('environment', flat=True)
            .distinct()
            .order_by('environment')[:100]
        )
        posture_environments = [
            {
                'key': item.key,
                'name': item.name,
            }
            for item in SystemPostureEnvironment.objects.filter(is_enabled=True).order_by('sort_order', 'id')
        ]
        log_datasources = [
            {
                'id': item.id,
                'name': item.name,
                'provider': item.provider,
                'provider_display': item.get_provider_display(),
                'description': item.description,
            }
            for item in LogDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
            if not _is_demoish_catalog_item(item.name, item.description, item.provider)
        ]
        tracing_datasources = [
            {
                'id': item.id,
                'name': item.name,
                'provider': item.provider,
                'provider_display': item.get_provider_display(),
                'description': item.description,
            }
            for item in TracingDataSource.objects.filter(is_enabled=True).order_by('provider', 'name')
            if not _is_demoish_catalog_item(item.name, item.description, item.provider)
        ]
        observability_links = [
            {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'log_datasource_id': item.log_datasource_id,
                'log_datasource_name': item.log_datasource.name if item.log_datasource else '',
                'tracing_datasource_id': item.tracing_datasource_id,
                'tracing_datasource_name': item.tracing_datasource.name if item.tracing_datasource else '',
                'grafana_dashboard_key': item.grafana_dashboard_key,
                'is_default': item.is_default,
            }
            for item in ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True).order_by('-is_default', 'name')
            if not _is_demoish_catalog_item(
                item.name,
                item.description,
                getattr(item.log_datasource, 'name', ''),
                getattr(item.tracing_datasource, 'name', ''),
            )
        ]
        k8s_clusters = [
            {
                'id': item.id,
                'name': item.name,
                'api_server': item.api_server,
                'status': item.status,
                'description': item.description,
                'namespaces': _k8s_namespace_options(item),
            }
            for item in K8sCluster.objects.order_by('name', 'id')
            if not _is_demoish_catalog_item(item.name, item.description, item.api_server)
        ]
        docker_hosts = [
            {
                'id': item.id,
                'name': item.name,
                'ip_address': item.ip_address,
                'status': item.status,
                'description': item.description,
            }
            for item in DockerHost.objects.order_by('name', 'id')
            if not _is_demoish_catalog_item(item.name, item.description, item.ip_address)
        ]
        resource_counts = TaskResource.objects.values('environment_id').annotate(total=Count('id'))
        env_counts = {}
        for item in resource_counts:
            env_counts[item['environment_id']] = env_counts.get(item['environment_id'], 0) + item['total']
        task_resource_environments = [
            {
                'id': item.id,
                'name': item.name,
                'code': item.code,
                'description': item.description,
                'resource_count': env_counts.get(item.id, 0),
            }
            for item in TaskResourceGroup.objects.filter(group_type=TaskResourceGroup.GROUP_ENVIRONMENT).order_by('sort_order', 'name', 'id')
        ]

        folder_map = {}
        for setting in GrafanaSetting.objects.filter(enabled=True).order_by('name'):
            folders = setting.folders if isinstance(setting.folders, list) else []
            dashboards = setting.dashboards if isinstance(setting.dashboards, list) else []
            for folder in folders:
                key = _grafana_folder_key(folder.get('path') or folder.get('folder') or folder.get('name'))
                if _is_demoish_catalog_item(key, folder.get('description')):
                    continue
                if key:
                    folder_map.setdefault(key, {'key': key, 'label': key, 'setting': setting.name, 'dashboard_count': 0})
            for dashboard in dashboards:
                if _is_demoish_catalog_item(dashboard.get('key'), dashboard.get('title'), dashboard.get('name'), dashboard.get('description')):
                    continue
                folder_key = _grafana_folder_key(dashboard.get('folder'))
                if not folder_key:
                    continue
                item = folder_map.setdefault(folder_key, {'key': folder_key, 'label': folder_key, 'setting': setting.name, 'dashboard_count': 0})
                item['dashboard_count'] += 1

        return Response({
            'event_environments': [
                _clean_catalog_value(item)
                for item in event_environments
                if not _is_invalid_environment_value(item)
            ],
            'grafana_folders': sorted(folder_map.values(), key=lambda item: item['label']),
            'log_datasources': log_datasources,
            'tracing_datasources': tracing_datasources,
            'observability_links': observability_links,
            'alert_environments': [_clean_catalog_value(item) for item in alert_environments if _clean_catalog_value(item)],
            'posture_environments': posture_environments,
            'k8s_clusters': k8s_clusters,
            'docker_hosts': docker_hosts,
            'task_resource_environments': task_resource_environments,
        })

    def perform_create(self, serializer):
        instance = serializer.save(
            created_by=getattr(self.request.user, 'username', ''),
            updated_by=getattr(self.request.user, 'username', ''),
        )
        record_event(
            request=self.request,
            module='aiops',
            category='knowledge',
            action='create_knowledge_environment',
            title='创建知识图谱环境关联',
            summary=f'已创建知识图谱环境《{instance.name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=instance.id,
            resource_name=instance.name,
            correlation_id=f'aiops-knowledge-env:{instance.id}',
        )

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=getattr(self.request.user, 'username', ''))
        record_event(
            request=self.request,
            module='aiops',
            category='knowledge',
            action='update_knowledge_environment',
            title='更新知识图谱环境关联',
            summary=f'已更新知识图谱环境《{instance.name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=instance.id,
            resource_name=instance.name,
            correlation_id=f'aiops-knowledge-env:{instance.id}',
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        resource_id = instance.id
        resource_name = instance.name
        response = super().destroy(request, *args, **kwargs)
        record_event(
            request=request,
            module='aiops',
            category='knowledge',
            action='delete_knowledge_environment',
            title='删除知识图谱环境关联',
            summary=f'已删除知识图谱环境《{resource_name}》',
            resource_type='aiops_knowledge_environment',
            resource_id=resource_id,
            resource_name=resource_name,
            correlation_id=f'aiops-knowledge-env:{resource_id}',
        )
        return response


class AIOpsChatSessionViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsChatSessionSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    demo_account_allowed_actions = {'create', 'send_message', 'send_message_async'}
    rbac_permissions = {
        'list': ['aiops.chat.view'],
        'retrieve': ['aiops.chat.view'],
        'create': ['aiops.chat.view'],
        'messages': ['aiops.chat.view'],
        'send_message': ['aiops.chat.view'],
        'send_message_async': ['aiops.chat.view'],
    }

    def get_queryset(self):
        if getattr(self.request.user, 'username', '') == 'demo':
            sync_admin_sessions_to_demo()
        return AIOpsChatSession.objects.filter(user=self.request.user).prefetch_related('messages').order_by('-last_message_at', '-id')

    def create(self, request, *args, **kwargs):
        serializer = AIOpsCreateSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AIOpsChatSession.objects.create(
            user=request.user,
            title=serializer.validated_data.get('title') or '新会话',
        )
        sync_session_to_demo_if_needed(session)
        return Response(AIOpsChatSessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        session = self.get_object()
        messages = session.messages.order_by('created_at', 'id')
        return Response(AIOpsChatMessageSerializer(messages, many=True).data)

    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        session = self.get_object()
        if is_demo_account(request.user):
            return Response({'detail': DEMO_CHAT_DISABLED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        if getattr(request.user, 'username', '') == 'demo' and session.mirror_source_id:
            return Response({'detail': '演示账号同步会话为只读，请先新建会话后提问。'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AIOpsChatInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = recover_masked_suggested_question(serializer.validated_data['content'].strip())
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content=content,
        )
        assistant_message, pending_action = dispatch_chat(session, user_message, request.user, user_message.content)
        return Response({
            'user_message': AIOpsChatMessageSerializer(user_message).data,
            'assistant_message': AIOpsChatMessageSerializer(assistant_message).data,
            'pending_action': AIOpsPendingActionSerializer(pending_action).data if pending_action else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def send_message_async(self, request, pk=None):
        session = self.get_object()
        if is_demo_account(request.user):
            return Response({'detail': DEMO_CHAT_DISABLED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)
        if getattr(request.user, 'username', '') == 'demo' and session.mirror_source_id:
            return Response({'detail': '演示账号同步会话为只读，请先新建会话后提问。'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AIOpsChatInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = recover_masked_suggested_question(serializer.validated_data['content'].strip())
        user_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content=content,
        )
        assistant_message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            message_type=AIOpsChatMessage.TYPE_TEXT,
            content='正在分析平台数据，请稍等...',
            metadata={
                'processing_status': 'pending',
                'processing_text': '请求已提交，正在排队处理',
                'processing_steps': [{
                    'title': '排队中',
                    'detail': '已收到问题，正在准备上下文',
                    'status': 'pending',
                    'timestamp': timezone.now().isoformat(),
                }],
                'tool_events': [],
            },
        )
        session.last_message_at = timezone.now()
        if session.title == '新会话':
            session.title = content[:48] or '新会话'
        session.save(update_fields=['last_message_at', 'title', 'updated_at'])
        sync_session_to_demo_if_needed(session)
        start_async_chat_processing(session, user_message, request.user, assistant_message)
        return Response({
            'user_message': AIOpsChatMessageSerializer(user_message).data,
            'assistant_message': AIOpsChatMessageSerializer(assistant_message).data,
            'pending_action': None,
        }, status=status.HTTP_201_CREATED)


class AIOpsAuditSessionViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = AIOpsAuditSessionSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
        'destroy': ['aiops.audit.manage'],
    }

    def get_queryset(self):
        return AIOpsChatSession.objects.filter(mirror_source__isnull=True).select_related('user').annotate(message_count=Count('messages')).order_by('-last_message_at', '-id')

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        session_id = instance.id
        session_title = instance.title
        session_user = getattr(instance.user, 'username', '')
        response = super().destroy(request, *args, **kwargs)
        if session_user == 'admin':
            sync_admin_sessions_to_demo()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='delete_session',
            title='删除 AIOps 审计会话',
            summary=f'已删除会话《{session_title}》',
            resource_type='aiops_session',
            resource_id=session_id,
            resource_name=session_title,
            correlation_id=f'aiops-session:{session_id}',
            metadata={'session_user': session_user},
        )
        return response

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        session_ids = request.data.get('session_ids')
        if not isinstance(session_ids, list):
            return Response({'detail': 'session_ids 必须为数组'}, status=status.HTTP_400_BAD_REQUEST)
        normalized_ids = [int(item) for item in session_ids if str(item).isdigit()]
        if not normalized_ids:
            return Response({'detail': '请至少选择一个会话'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(id__in=normalized_ids)
        sessions = list(queryset)
        if not sessions:
            return Response({'detail': '未找到可删除的会话'}, status=status.HTTP_404_NOT_FOUND)

        deleted_count = len(sessions)
        deleted_titles = [item.title for item in sessions[:5]]
        admin_deleted = any(getattr(item.user, 'username', '') == 'admin' for item in sessions)
        session_meta = [
            {'id': item.id, 'title': item.title, 'username': getattr(item.user, 'username', '')}
            for item in sessions
        ]
        queryset.delete()
        if admin_deleted:
            sync_admin_sessions_to_demo()
        record_event(
            request=request,
            module='aiops',
            category='audit',
            action='bulk_delete_sessions',
            title='批量删除 AIOps 审计会话',
            summary=f'已批量删除 {deleted_count} 个会话',
            resource_type='aiops_session',
            resource_id=deleted_count,
            resource_name='、'.join(deleted_titles),
            correlation_id=f'aiops-session-bulk:{deleted_count}',
            metadata={'sessions': session_meta},
        )
        return Response({'deleted': deleted_count}, status=status.HTTP_200_OK)


class AIOpsToolInvocationViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AIOpsToolInvocationSerializer
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
    }

    def get_queryset(self):
        return AIOpsToolInvocation.objects.select_related('session', 'session__user', 'message').order_by('-created_at', '-id')


class AIOpsPendingActionViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AIOpsPendingActionSerializer
    rbac_permissions = {
        'list': ['aiops.audit.view'],
        'retrieve': ['aiops.audit.view'],
    }

    def get_queryset(self):
        return AIOpsPendingAction.objects.filter(mirror_source__isnull=True, session__mirror_source__isnull=True).select_related('session', 'session__user', 'message').order_by('-created_at', '-id')


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.chat.view')])
def bootstrap(request):
    return Response(bootstrap_payload_for_user(request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.knowledge.view')])
def knowledge_graph(request):
    return Response(build_knowledge_graph(request.query_params))


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.config.view')])
def agent_config_view(request):
    config = get_agent_config()
    if request.method == 'GET':
        return Response(AIOpsAgentConfigSerializer(config).data)
    if not user_has_permissions(request.user, ['aiops.config.manage']):
        return Response({'detail': '缺少 aiops.config.manage 权限'}, status=status.HTTP_403_FORBIDDEN)
    serializer = AIOpsAgentConfigSerializer(instance=config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    record_event(
        request=request,
        module='aiops',
        category='configuration',
        action='update_agent_config',
        title='更新 AIOps 配置',
        summary='已更新 AIOps 机器人配置',
        resource_type='aiops_config',
        resource_id=config.id,
        resource_name=config.name,
        correlation_id=f'aiops-config:{config.id}',
    )
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.audit.view')])
def audit_overview(request):
    data = build_audit_overview()
    data['session_status'] = list(AIOpsChatSession.objects.filter(mirror_source__isnull=True).values('status').annotate(count=Count('id')).order_by('status'))
    data['action_status'] = list(AIOpsPendingAction.objects.filter(mirror_source__isnull=True, session__mirror_source__isnull=True).values('status').annotate(count=Count('id')).order_by('status'))
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.task.execute')])
def confirm_pending_action(request, pk):
    action = AIOpsPendingAction.objects.select_related('session', 'message').filter(pk=pk).first()
    if not action:
        return Response({'detail': '动作不存在'}, status=status.HTTP_404_NOT_FOUND)
    try:
        task_draft = confirm_action(action, request.user, request=request)
        return Response({'success': True, 'task_name': task_draft['name'], 'task_draft': task_draft})
    except ValueError as exc:
        action.status = AIOpsPendingAction.STATUS_FAILED
        action.result_payload = {'error': str(exc)}
        action.save(update_fields=['status', 'result_payload', 'updated_at'])
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('aiops.task.generate')])
def cancel_pending_action(request, pk):
    action = AIOpsPendingAction.objects.select_related('session', 'message').filter(pk=pk).first()
    if not action:
        return Response({'detail': '动作不存在'}, status=status.HTTP_404_NOT_FOUND)
    try:
        cancel_action(action, request.user)
        return Response({'success': True})
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
