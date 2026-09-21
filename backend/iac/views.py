import io
import zipfile

from django.http import HttpResponse
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin, build_rbac_permission

from .cmdb_sync import sync_stack_to_cmdb
from .executor import submit_terraform_action
from .models import TerraformExecution, TerraformStack
from .serializers import (
    TerraformExecutionRequestSerializer,
    TerraformExecutionSerializer,
    TerraformRenderSerializer,
    TerraformStackListSerializer,
    TerraformStackSerializer,
)
from .terraform import PROVIDER_CATALOG


class TerraformStackViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TerraformStack.objects.all().prefetch_related('resource_bindings__cmdb_item__ci_type', 'executions')
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description', 'cloud_provider', 'region', 'zone', 'created_by']
    rbac_permissions = {
        'list': ['ops.iac.view'],
        'retrieve': ['ops.iac.view'],
        'create': ['ops.iac.manage'],
        'update': ['ops.iac.manage'],
        'partial_update': ['ops.iac.manage'],
        'destroy': ['ops.iac.manage'],
        'download': ['ops.iac.view'],
        'executions': ['ops.iac.view'],
        'execute': ['ops.iac.execute'],
        'sync_cmdb': ['ops.iac.execute', 'cmdb.ci.manage'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return TerraformStackListSerializer
        if self.action == 'execute':
            return TerraformExecutionRequestSerializer
        return TerraformStackSerializer

    def get_serializer(self, *args, **kwargs):
        if getattr(self, 'action', None) == 'execute':
            kwargs.setdefault('stack', self.get_object())
        return super().get_serializer(*args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user.username,
            updated_by=self.request.user.username,
            summary=serializer.validated_data.pop('_rendered_summary'),
            generated_files=serializer.validated_data.pop('_rendered_files'),
        )

    def perform_update(self, serializer):
        serializer.save(
            updated_by=self.request.user.username,
            summary=serializer.validated_data.pop('_rendered_summary'),
            generated_files=serializer.validated_data.pop('_rendered_files'),
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        stack = self.get_object()
        response = HttpResponse(
            _build_zip_bytes(stack.generated_files),
            content_type='application/zip',
        )
        response['Content-Disposition'] = f'attachment; filename="{stack.name}-terraform.zip"'
        return response

    @action(detail=True, methods=['get'])
    def executions(self, request, pk=None):
        stack = self.get_object()
        serializer = TerraformExecutionSerializer(stack.executions.all(), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        stack = self.get_object()
        # 防重入：同一方案已有在途执行（pending/running）直接 409
        if TerraformExecution.objects.filter(
                stack=stack,
                status__in=[TerraformExecution.STATUS_PENDING, TerraformExecution.STATUS_RUNNING]).exists():
            return Response({'message': '该方案已有执行任务在进行中，请稍后再试'},
                            status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        execution = submit_terraform_action(
            stack,
            serializer.validated_data['action'],
            secrets=serializer.validated_data.get('secrets') or {},
            operator=request.user.username,
        )
        stack.refresh_from_db()
        if execution.status == TerraformExecution.STATUS_FAILED:  # 线程启动失败的兜底
            return Response(
                {
                    'message': execution.stderr or '执行任务提交失败',
                    'execution': TerraformExecutionSerializer(execution).data,
                    'stack': TerraformStackSerializer(stack).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                'message': '执行任务已提交，完成后将收到站内通知',
                'execution': TerraformExecutionSerializer(execution).data,
                'stack': TerraformStackSerializer(stack).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['post'])
    def sync_cmdb(self, request, pk=None):
        stack = self.get_object()
        summary = sync_stack_to_cmdb(stack, operator=request.user.username)
        stack.refresh_from_db()
        return Response(
            {
                'message': 'CMDB 同步完成。',
                'summary': summary,
                'stack': TerraformStackSerializer(stack).data,
            },
            status=status.HTTP_200_OK,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.iac.view')])
def terraform_catalog_view(request):
    return Response({'providers': PROVIDER_CATALOG})


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.iac.manage', allow_demo_write=True)])
def terraform_render_view(request):
    serializer = TerraformRenderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    rendered = serializer.validated_data['rendered']
    return Response(rendered)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.iac.manage', allow_demo_write=True)])
def terraform_bundle_view(request):
    serializer = TerraformRenderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    rendered = serializer.validated_data['rendered']
    response = HttpResponse(
        _build_zip_bytes(rendered['files']),
        content_type='application/zip',
        status=status.HTTP_200_OK,
    )
    filename = f'{serializer.validated_data["payload"]["name"]}-terraform.zip'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _build_zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in (files or {}).items():
            archive.writestr(filename, content)
    buffer.seek(0)
    return buffer.read()
