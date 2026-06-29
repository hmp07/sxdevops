"""Zabbix 数据源管理 ViewSet + 代理查询端点."""
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action as drf_action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils.timezone import now

from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from .models import ZabbixDataSource
from .serializers import ZabbixDataSourceSerializer
from .zabbix_client import ZabbixClient


def _get_client(datasource_id):
    """根据数据源 ID 获取 Zabbix 客户端"""
    try:
        ds = ZabbixDataSource.objects.get(id=datasource_id, is_enabled=True)
    except ZabbixDataSource.DoesNotExist:
        return None, Response({'error': '数据源不存在或未启用'}, status=status.HTTP_404_NOT_FOUND)
    return ZabbixClient(ds), None


class ZabbixDataSourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """Zabbix 数据源管理"""
    queryset = ZabbixDataSource.objects.all().order_by('-is_default', 'name')
    serializer_class = ZabbixDataSourceSerializer
    rbac_permissions = {
        'list': 'ops.zabbix.datasource.view',
        'retrieve': 'ops.zabbix.datasource.view',
        'create': 'ops.zabbix.datasource.manage',
        'update': 'ops.zabbix.datasource.manage',
        'partial_update': 'ops.zabbix.datasource.manage',
        'destroy': 'ops.zabbix.datasource.manage',
    }

    def perform_destroy(self, instance):
        if instance.is_default:
            raise PermissionError('不能删除默认数据源')
        instance.delete()

    @drf_action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, build_rbac_permission('ops.zabbix.datasource.manage')])
    def test_connection(self, request, pk=None):
        """测试 Zabbix API 连接"""
        ds = self.get_object()
        client = ZabbixClient(ds)
        result = client.test_connection()
        if 'error' in result:
            return Response({'status': 'error', 'message': result['error']}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': 'success', 'version': str(result)})


# ---- Zabbix 代理查询端点 ----

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_hosts(request):
    """获取 Zabbix 主机列表"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    group_ids = request.GET.getlist('group_ids')
    search = request.GET.get('search', '').strip() or None
    limit = int(request.GET.get('limit', 100))
    result = client.get_hosts(group_ids=group_ids or None, search=search, limit=limit)
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_host_groups(request):
    """获取 Zabbix 主机组"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    result = client.get_host_groups()
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_items(request):
    """获取 Zabbix 监控项"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    host_ids = request.GET.getlist('host_ids')
    search = request.GET.get('search', '').strip() or None
    limit = int(request.GET.get('limit', 100))
    result = client.get_items(host_ids=host_ids or None, search=search, limit=limit)
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_history(request):
    """获取 Zabbix 监控项历史数据"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    item_ids = request.GET.getlist('item_ids')
    if not item_ids:
        return Response({'error': '请提供 item_ids'}, status=status.HTTP_400_BAD_REQUEST)
    history_type = int(request.GET.get('history_type', 0))
    time_from = request.GET.get('time_from')
    time_to = request.GET.get('time_to')
    limit = int(request.GET.get('limit', 100))
    result = client.get_history(
        item_ids, history_type=history_type,
        time_from=int(time_from) if time_from else None,
        time_to=int(time_to) if time_to else None,
        limit=limit,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_triggers(request):
    """获取 Zabbix 触发器"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    host_ids = request.GET.getlist('host_ids')
    min_severity = request.GET.get('min_severity')
    only_true = request.GET.get('only_true', '0') == '1'
    limit = int(request.GET.get('limit', 100))
    result = client.get_triggers(
        host_ids=host_ids or None,
        min_severity=int(min_severity) if min_severity else None,
        only_true=only_true,
        limit=limit,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_problems(request):
    """获取 Zabbix 当前问题"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err:
        return err
    host_ids = request.GET.getlist('host_ids')
    severities = request.GET.getlist('severities')
    limit = int(request.GET.get('limit', 100))
    result = client.get_problems(
        host_ids=host_ids or None,
        severities=[int(s) for s in severities] if severities else None,
        limit=limit,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
