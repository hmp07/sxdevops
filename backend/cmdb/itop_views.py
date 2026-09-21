"""iTop 数据源管理 ViewSet."""
import logging
import threading

from rest_framework import viewsets, status
from rest_framework.decorators import action as drf_action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.models import EventRecord
from eventwall.services import record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from sxdevops.background import push_background_job_notification, start_background_thread
from .models import iTopDataSource
from .serializers import iTopDataSourceSerializer
from .itop_sync import test_connection, run_full_sync

logger = logging.getLogger(__name__)

_SYNC_IN_FLIGHT = set()
_SYNC_IN_FLIGHT_LOCK = threading.Lock()


class iTopDataSourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = iTopDataSource.objects.all().order_by('name')
    serializer_class = iTopDataSourceSerializer
    rbac_permissions = {
        'list': 'cmdb.itop.datasource.view',
        'retrieve': 'cmdb.itop.datasource.view',
        'create': 'cmdb.itop.datasource.manage',
        'update': 'cmdb.itop.datasource.manage',
        'partial_update': 'cmdb.itop.datasource.manage',
        'destroy': 'cmdb.itop.datasource.manage',
    }

    def create(self, request, *args, **kwargs):
        """创建数据源：先连接测试（失败 400 不落库），落库后后台线程全量同步。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = iTopDataSource(**serializer.validated_data)
        try:
            ok = test_connection(instance, timeout=10)
        except Exception as e:
            logger.warning('iTop 保存前连接测试异常: %s', e)
            return Response({'status': 'error', 'message': str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        if not ok:
            return Response({'status': 'error', 'message': '连接测试失败，请检查地址与凭据'},
                            status=status.HTTP_400_BAD_REQUEST)
        instance.save()
        _start_sync_thread(instance.id)
        headers = self.get_success_headers(self.get_serializer(instance).data)
        return Response(self.get_serializer(instance).data,
                        status=status.HTTP_201_CREATED, headers=headers)

    @drf_action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, build_rbac_permission('cmdb.itop.datasource.manage')])
    def test_connection(self, request, pk=None):
        ds = self.get_object()
        try:
            ok = test_connection(ds)
            return Response({'status': 'success' if ok else 'error', 'authorized': ok})
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)})

    @drf_action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, build_rbac_permission('cmdb.itop.datasource.manage')])
    def trigger_sync(self, request, pk=None):
        ds = self.get_object()
        if ds.sync_status == 'running':
            return Response({'status': 'error', 'message': '同步正在进行中'}, status=status.HTTP_409_CONFLICT)
        if not _start_sync_thread(ds.id):
            return Response({'status': 'error', 'message': '同步已在后台进行中'}, status=status.HTTP_409_CONFLICT)
        return Response({'status': 'running', 'message': '同步已触发，完成后将收到站内通知'},
                        status=status.HTTP_202_ACCEPTED)


def _start_sync_thread(ds_id):
    """启动 iTop 全量同步后台线程（防并发重复启动）。"""
    return start_background_thread(_SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK,
                                   f'itop:{ds_id}', _sync_worker, ds_id)


def _sync_worker(ds_id):
    """后台线程：重取数据源执行全量同步，完成后写事件墙 + 站内广播。"""
    ds = iTopDataSource.objects.filter(id=ds_id).first()
    if ds is None:
        return
    try:
        run_full_sync(ds)
        ds.refresh_from_db()
        # 状态：ok / ok (设备映射: ...) / error: ...
        ok = (ds.sync_status or '').startswith('ok')
    except Exception as e:
        ok = False
        logger.warning('iTop 同步线程失败 datasource=%s: %s', ds_id, e)
    level = 'success' if ok else 'error'
    message = '全量同步完成' if ok else f'全量同步失败（状态: {ds.sync_status}）'
    record_event(
        module='cmdb', category='external_event', action='itop_sync_finish',
        title=f'iTop 数据源 {ds.name} 全量同步{"完成" if ok else "失败"}',
        summary=message,
        result=EventRecord.RESULT_SUCCESS if ok else EventRecord.RESULT_FAILED,
        severity=EventRecord.SEVERITY_INFO if ok else EventRecord.SEVERITY_WARNING,
        source_type=EventRecord.SOURCE_ASYNC, actor_type=EventRecord.ACTOR_SYSTEM,
        resource_type='itop_datasource', resource_id=ds.id, resource_name=ds.name,
        correlation_id=f'itop-sync:{ds.id}',
        metadata={'event_category': 'config_change', 'sync_status': ds.sync_status},
    )
    push_background_job_notification(
        'itop_sync',
        title=f'iTop 数据源同步{"完成" if ok else "失败"}',
        message=f'{ds.name}: {message}',
        level=level, route='/cmdb/datasources/itop', job_id=ds.id,
    )
