"""iTop 数据源管理 ViewSet."""
from rest_framework import viewsets, status
from rest_framework.decorators import action as drf_action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from .models import iTopDataSource
from .serializers import iTopDataSourceSerializer
from .itop_sync import test_connection, run_full_sync


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

    @drf_action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def test_connection(self, request, pk=None):
        ds = self.get_object()
        try:
            ok = test_connection(ds)
            return Response({'status': 'success' if ok else 'error', 'authorized': ok})
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)})

    @drf_action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def trigger_sync(self, request, pk=None):
        ds = self.get_object()
        if ds.sync_status == 'running':
            return Response({'status': 'error', 'message': '同步正在进行中'}, status=status.HTTP_409_CONFLICT)
        try:
            result = run_full_sync(ds)
            return Response({'status': 'success', 'result': result})
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
