from rest_framework import serializers

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsExternalTask,
    AIOpsKnowledgeEnvironment,
    AIOpsMCPServer,
    AIOpsModelInvocation,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsRunbook,
    AIOpsSkill,
    AIOpsToolInvocation,
)
from .services import get_model_provider_setup_hint


class AIOpsModelProviderSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_api_key = serializers.BooleanField(read_only=True)
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = [
            'id', 'name', 'provider_type', 'base_url', 'api_key', 'has_api_key', 'default_model', 'backup_model',
            'temperature', 'max_tokens', 'timeout_seconds', 'is_enabled', 'runtime_ready', 'setup_hint',
            'input_token_price_per_1m', 'output_token_price_per_1m',
            'last_test_status', 'last_test_message',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['runtime_ready', 'setup_hint', 'last_test_status', 'last_test_message', 'created_at', 'updated_at', 'has_api_key']

    def create(self, validated_data):
        api_key = validated_data.pop('api_key', '')
        instance = super().create(validated_data)
        if api_key:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop('api_key', None)
        instance = super().update(instance, validated_data)
        if api_key is not None:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsModelProviderLiteSerializer(serializers.ModelSerializer):
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = ['id', 'name', 'provider_type', 'default_model', 'is_enabled', 'runtime_ready', 'setup_hint']

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsAgentConfigSerializer(serializers.ModelSerializer):
    default_provider_id = serializers.PrimaryKeyRelatedField(
        queryset=AIOpsModelProvider.objects.all(),
        source='default_provider',
        write_only=True,
        allow_null=True,
        required=False,
    )
    default_provider = AIOpsModelProviderLiteSerializer(read_only=True)

    class Meta:
        model = AIOpsAgentConfig
        fields = [
            'id', 'name', 'default_provider', 'default_provider_id', 'system_prompt', 'welcome_message',
            'suggested_questions', 'is_enabled', 'allow_action_execution', 'require_confirmation', 'show_evidence',
            'allow_analysis', 'enabled_mcp_server_ids', 'enabled_skill_ids', 'max_history_messages',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class AIOpsMCPServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsMCPServer
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('name', None)
            validated_data.pop('server_type', None)
        return super().update(instance, validated_data)


class AIOpsSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsSkill
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def validate(self, attrs):
        list_fields = [
            'allowed_role_codes',
            'applicable_actions',
            'examples',
            'builtin_tools',
            'recommended_tools',
        ]
        for field in list_fields:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
                continue
            if not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
            normalized = []
            for item in value:
                normalized_item = str(item or '').strip()
                if normalized_item and normalized_item not in normalized:
                    normalized.append(normalized_item)
            attrs[field] = normalized

        if 'output_contract' in attrs:
            value = attrs.get('output_contract')
            if value in (None, ''):
                attrs['output_contract'] = {}
            elif not isinstance(value, dict):
                raise serializers.ValidationError({'output_contract': '必须为对象'})

        if 'max_iterations' in attrs and attrs.get('max_iterations') is None:
            attrs['max_iterations'] = 0
        return attrs

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('slug', None)
            validated_data.pop('source_type', None)
        return super().update(instance, validated_data)


class AIOpsKnowledgeEnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsKnowledgeEnvironment
        fields = [
            'id', 'name', 'aliases', 'description', 'event_environments', 'grafana_folder_keys',
            'log_datasource_ids', 'tracing_datasource_ids', 'observability_link_ids', 'alert_environments',
            'posture_environments', 'k8s_cluster_ids', 'k8s_namespaces', 'docker_host_ids',
            'task_resource_environment_ids',
            'is_enabled', 'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('请填写知识图谱环境名')
        return value

    def validate(self, attrs):
        list_fields = [
            'aliases',
            'event_environments',
            'grafana_folder_keys',
            'log_datasource_ids',
            'tracing_datasource_ids',
            'observability_link_ids',
            'alert_environments',
            'posture_environments',
            'k8s_cluster_ids',
            'docker_host_ids',
            'task_resource_environment_ids',
        ]
        for field in list_fields:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
                continue
            if not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
            normalized = []
            for item in value:
                if field.endswith('_ids'):
                    try:
                        normalized_item = int(item)
                    except (TypeError, ValueError):
                        continue
                else:
                    normalized_item = str(item or '').strip()
                if normalized_item and normalized_item not in normalized:
                    normalized.append(normalized_item)
            attrs[field] = normalized

        if 'k8s_namespaces' in attrs:
            value = attrs.get('k8s_namespaces')
            if value in (None, ''):
                attrs['k8s_namespaces'] = {}
            elif not isinstance(value, dict):
                raise serializers.ValidationError({'k8s_namespaces': '必须为对象'})
            else:
                normalized = {}
                for cluster_id, namespaces in value.items():
                    try:
                        normalized_cluster_id = str(int(cluster_id))
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(namespaces, list):
                        continue
                    normalized_namespaces = []
                    for namespace in namespaces:
                        namespace = str(namespace or '').strip()
                        if namespace and namespace not in normalized_namespaces:
                            normalized_namespaces.append(namespace)
                    if normalized_namespaces:
                        normalized[normalized_cluster_id] = normalized_namespaces
                attrs['k8s_namespaces'] = normalized

        instance = self.instance
        association_fields = [field for field in list_fields if field != 'aliases']
        has_association = any(
            attrs.get(field, getattr(instance, field, [])) for field in association_fields
        )
        if not has_association:
            raise serializers.ValidationError('请至少选择一个事件中心、看板目录、日志、链路、告警、系统态势、K8s 集群、Docker 环境或任务资源底座来源')
        return attrs


class AIOpsPendingActionSerializer(serializers.ModelSerializer):
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsPendingAction
        fields = [
            'id', 'action_type', 'title', 'risk_level', 'risk_level_display', 'status', 'status_display',
            'action_payload', 'result_payload', 'confirmed_by', 'confirmed_at', 'created_at', 'updated_at',
        ]


class AIOpsChatMessageSerializer(serializers.ModelSerializer):
    pending_action = serializers.SerializerMethodField()
    blocks = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatMessage
        fields = ['id', 'role', 'message_type', 'content', 'citations', 'tool_calls', 'metadata', 'blocks', 'pending_action', 'created_at']

    def get_pending_action(self, obj):
        action = obj.pending_actions.order_by('-id').first()
        return AIOpsPendingActionSerializer(action).data if action else None

    def get_blocks(self, obj):
        metadata = obj.metadata or {}
        blocks = metadata.get('response_blocks') or metadata.get('blocks') or []
        return blocks if isinstance(blocks, list) else []


class AIOpsChatSessionSerializer(serializers.ModelSerializer):
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatSession
        fields = ['id', 'title', 'status', 'context', 'last_message_at', 'created_at', 'updated_at', 'latest_message']

    def get_latest_message(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        if not message:
            return None
        return {
            'role': message.role,
            'content': message.content[:120],
            'created_at': message.created_at,
        }


class AIOpsAuditSessionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AIOpsChatSession
        fields = ['id', 'title', 'status', 'username', 'message_count', 'last_message_at', 'created_at', 'updated_at']


class AIOpsChatInputSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000)


class AIOpsCreateSessionSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')


class AIOpsToolInvocationSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(source='session.title', read_only=True)
    username = serializers.CharField(source='session.user.username', read_only=True)

    class Meta:
        model = AIOpsToolInvocation
        fields = [
            'id', 'session', 'session_title', 'username', 'message', 'tool_name', 'status', 'latency_ms',
            'request_payload', 'response_summary', 'created_at',
        ]


class AIOpsModelInvocationSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    session_title = serializers.CharField(source='session.title', read_only=True)
    purpose_display = serializers.CharField(source='get_purpose_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsModelInvocation
        fields = [
            'id', 'provider', 'provider_name', 'session', 'session_title', 'message', 'username',
            'purpose', 'purpose_display', 'requested_model', 'resolved_model', 'status', 'status_display',
            'latency_ms', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'estimated_cost_usd',
            'request_summary', 'response_summary', 'created_at',
        ]


class AIOpsExternalTaskSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsExternalTask
        fields = [
            'id', 'public_id', 'source_agent', 'title', 'action_code', 'agent_mode', 'status', 'status_display',
            'input_payload', 'plan_steps', 'result_payload', 'error_message', 'created_by', 'created_by_username',
            'created_at', 'updated_at', 'completed_at', 'canceled_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'agent_mode', 'status', 'status_display', 'plan_steps', 'result_payload',
            'error_message', 'created_by', 'created_by_username', 'created_at', 'updated_at',
            'completed_at', 'canceled_at',
        ]

    def validate(self, attrs):
        input_payload = attrs.get('input_payload')
        if input_payload in (None, ''):
            attrs['input_payload'] = {}
        elif not isinstance(input_payload, dict):
            raise serializers.ValidationError({'input_payload': '必须为对象'})
        return attrs


class AIOpsRunbookSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsRunbook
        fields = [
            'id', 'title', 'slug', 'environment', 'service', 'status', 'status_display',
            'content', 'evidence', 'tags', 'source_task', 'source_session',
            'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        for field in ['evidence', 'tags']:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
            elif not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
        return attrs
