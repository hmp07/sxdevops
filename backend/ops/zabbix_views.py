"""Zabbix 数据源管理 ViewSet + 代理查询端点."""
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action as drf_action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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

    @drf_action(detail=True, methods=['post'],
                  permission_classes=[IsAuthenticated, build_rbac_permission('ops.zabbix.datasource.manage')])
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
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    result = client.get_hosts(
        group_ids=request.GET.getlist('group_ids') or None,
        search=request.GET.get('search', '').strip() or None,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_host_groups(request):
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    result = client.get_host_groups()
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_items(request):
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    result = client.get_items(
        host_ids=request.GET.getlist('host_ids') or None,
        search=request.GET.get('search', '').strip() or None,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_history(request):
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    item_ids = request.GET.getlist('item_ids')
    if not item_ids:
        return Response({'error': '请提供 item_ids'}, status=status.HTTP_400_BAD_REQUEST)
    time_from = request.GET.get('time_from')
    time_to = request.GET.get('time_to')
    result = client.get_history(
        item_ids,
        time_from=int(time_from) if time_from else None,
        time_to=int(time_to) if time_to else None,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_trends(request):
    """获取 Zabbix 趋势数据（>1天历史）"""
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    item_ids = request.GET.getlist('item_ids')
    if not item_ids:
        return Response({'error': '请提供 item_ids'}, status=status.HTTP_400_BAD_REQUEST)
    time_from = request.GET.get('time_from')
    time_to = request.GET.get('time_to')
    result = client.get_trends(
        item_ids,
        time_from=int(time_from) if time_from else None,
        time_to=int(time_to) if time_to else None,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_triggers(request):
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    result = client.get_triggers(
        host_ids=request.GET.getlist('host_ids') or None,
        min_severity=int(request.GET.get('min_severity', 0)) or None,
        active_only=request.GET.get('only_true', '0') == '1',
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.zabbix.view')])
def zabbix_problems(request):
    client, err = _get_client(request.GET.get('datasource_id'))
    if err: return err
    result = client.get_problems(
        host_ids=request.GET.getlist('host_ids') or None,
        severities=[int(s) for s in request.GET.getlist('severities')] or None,
    )
    if 'error' in result:
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
