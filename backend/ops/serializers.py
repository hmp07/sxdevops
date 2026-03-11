from rest_framework import serializers
from .models import Host, Deployment, Alert, LogEntry, K8sCluster, DockerHost, NginxEnvironment, NginxDomain, NginxRoute


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = '__all__'


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Deployment
        fields = '__all__'


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Alert
        fields = '__all__'


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'


class K8sClusterSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = K8sCluster
        fields = '__all__'
        extra_kwargs = {
            'kubeconfig': {'write_only': True},  # 安全: kubeconfig 不在列表中返回
        }


class DockerHostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DockerHost
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }

class NginxEnvironmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NginxEnvironment
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }

class NginxDomainSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)

    class Meta:
        model = NginxDomain
        fields = '__all__'
        extra_kwargs = {
            'cert_content': {'write_only': True},
            'key_content': {'write_only': True},
            'cert_path': {'read_only': True},
            'key_path': {'read_only': True},
        }

class NginxRouteSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(source='nginx_domain.domain', read_only=True)
    environment_name = serializers.CharField(source='nginx_domain.environment.name', read_only=True)

    class Meta:
        model = NginxRoute
        fields = '__all__'

