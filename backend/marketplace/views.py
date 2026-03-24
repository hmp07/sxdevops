import threading

from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin, build_rbac_permission

from . import deployer
from .models import ServiceDeployment, ServiceTemplate
from .serializers import (
    DeployRequestSerializer,
    ServiceDeploymentSerializer,
    ServiceTemplateSerializer,
)


def _default_release_name(template):
    return slugify(template.name) or f'service-{template.pk}'


class ServiceTemplateViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    """服务模板，只读列表与详情"""

    queryset = ServiceTemplate.objects.filter(is_active=True)
    serializer_class = ServiceTemplateSerializer
    pagination_class = None
    rbac_permissions = {
        'list': ['marketplace.template.view'],
        'retrieve': ['marketplace.template.view'],
    }


class ServiceDeploymentViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """服务部署实例"""

    queryset = ServiceDeployment.objects.select_related('template', 'host', 'cluster')
    serializer_class = ServiceDeploymentSerializer
    rbac_permissions = {
        'list': ['marketplace.deployment.view'],
        'retrieve': ['marketplace.deployment.view'],
        'create': ['marketplace.deployment.manage'],
        'update': ['marketplace.deployment.manage'],
        'partial_update': ['marketplace.deployment.manage'],
        'destroy': ['marketplace.deployment.manage'],
        'stop': ['marketplace.deployment.manage'],
        'start': ['marketplace.deployment.manage'],
        'remove': ['marketplace.deployment.manage'],
        'logs': ['marketplace.deployment.view'],
    }

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        dep = self.get_object()
        deployer.stop_service(dep)
        return Response(ServiceDeploymentSerializer(dep).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        dep = self.get_object()
        deployer.start_service(dep)
        return Response(ServiceDeploymentSerializer(dep).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        dep = self.get_object()
        result = deployer.remove_service(dep)
        if result is None:
            return Response({'detail': '服务已卸载'}, status=status.HTTP_204_NO_CONTENT)
        return Response(ServiceDeploymentSerializer(result).data)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        dep = self.get_object()
        tail = int(request.query_params.get('tail', 100))
        return Response({'logs': deployer.get_service_logs(dep, tail=tail)})


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('marketplace.deployment.manage')])
def deploy_service_view(request):
    """发起部署"""

    ser = DeployRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    try:
        template = ServiceTemplate.objects.get(pk=data['template_id'])
    except ServiceTemplate.DoesNotExist:
        return Response({'detail': '模板不存在'}, status=status.HTTP_404_NOT_FOUND)

    deploy_mode = data['deploy_mode']
    if not template.supports_deploy_mode(deploy_mode):
        return Response({'detail': '当前模板暂不支持所选部署模式'}, status=status.HTTP_400_BAD_REQUEST)

    dep_kwargs = {
        'template': template,
        'deploy_mode': deploy_mode,
        'version': data['version'],
        'env_config': data.get('env_config', {}),
        'deployer': request.user.username,
        'replicas': data.get('replicas', 1),
    }

    if deploy_mode == 'docker_compose':
        from ops.models import Host

        try:
            host = Host.objects.get(pk=data['host_id'])
        except Host.DoesNotExist:
            return Response({'detail': '目标主机不存在'}, status=status.HTTP_404_NOT_FOUND)

        if ServiceDeployment.objects.filter(
            template=template,
            host=host,
            deploy_mode='docker_compose',
        ).exists():
            return Response(
                {'detail': f'{template.name} 已在 {host.hostname} 上部署'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dep_kwargs['host'] = host
    else:
        from ops.models import K8sCluster

        try:
            cluster = K8sCluster.objects.get(pk=data['cluster_id'])
        except K8sCluster.DoesNotExist:
            return Response({'detail': '目标集群不存在'}, status=status.HTTP_404_NOT_FOUND)

        namespace = data.get('namespace') or 'default'
        if ServiceDeployment.objects.filter(
            template=template,
            cluster=cluster,
            namespace=namespace,
            deploy_mode='k8s',
        ).exists():
            return Response(
                {'detail': f'{template.name} 已在 {cluster.name} 的 {namespace} 命名空间部署'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dep_kwargs.update({
            'cluster': cluster,
            'namespace': namespace,
            'release_name': data.get('release_name') or _default_release_name(template),
        })

    dep = ServiceDeployment.objects.create(**dep_kwargs)

    thread = threading.Thread(target=deployer.deploy_service, args=(dep.id,), daemon=True)
    thread.start()

    return Response(ServiceDeploymentSerializer(dep).data, status=status.HTTP_201_CREATED)
