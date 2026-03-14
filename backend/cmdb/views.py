from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.db.models import Count, Sum, Avg, F, Q
from django.utils import timezone
from .models import CIType, ConfigItem, CIRelation, CostRecord, ResourceRequest, ResourceNode
from .serializers import (
    CITypeSerializer, ConfigItemSerializer, CIRelationSerializer,
    CostRecordSerializer, ResourceRequestSerializer, ResourceNodeSerializer
)

class CITypeViewSet(viewsets.ModelViewSet):
    """CI 类型管理"""
    queryset = CIType.objects.annotate(ci_count=Count('instances'))
    serializer_class = CITypeSerializer
    search_fields = ['name']
    pagination_class = None

class ConfigItemViewSet(viewsets.ModelViewSet):
    """配置项管理"""
    queryset = ConfigItem.objects.select_related('ci_type').all()
    serializer_class = ConfigItemSerializer
    search_fields = ['name', 'admin_user', 'business_line']
    filterset_fields = ['ci_type', 'business_line', 'environment', 'status']

    @action(detail=False, methods=['get'])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        by_type = list(qs.values('ci_type__name', 'ci_type__color').annotate(count=Count('id')).order_by('-count'))
        for item in by_type:
            item['ci_type__color'] = item.get('ci_type__color') or '#9c27b0'
        by_status = dict(qs.values_list('status').annotate(count=Count('id')))
        by_env = dict(qs.values_list('environment').annotate(count=Count('id')))
        return Response({
            'total': qs.count(),
            'by_type': by_type,
            'by_status': by_status,
            'by_env': by_env,
        })

class ResourceNodeViewSet(viewsets.ModelViewSet):
    """资源节点(业务线/环境)树管理"""
    queryset = ResourceNode.objects.all().order_by('sort_order', 'id')
    serializer_class = ResourceNodeSerializer
    filterset_fields = ['node_type', 'parent']
    pagination_class = None

    @action(detail=False, methods=['get'])
    def tree(self, request):
        nodes = list(ResourceNode.objects.all().order_by('sort_order', 'id').values())
        return Response(self._build_tree(nodes, None))

    def _build_tree(self, nodes, parent_id):
        tree = []
        for node in nodes:
            if node['parent_id'] == parent_id:
                children = self._build_tree(nodes, node['id'])
                if children:
                    node['children'] = children
                tree.append(node)
        return tree

class CIRelationViewSet(viewsets.ModelViewSet):
    """CI 关系管理"""
    queryset = CIRelation.objects.select_related('source', 'target').all()
    serializer_class = CIRelationSerializer
    filterset_fields = ['source', 'target', 'relation_type']

class CostRecordViewSet(viewsets.ModelViewSet):
    """成本记录管理"""
    queryset = CostRecord.objects.select_related('ci').all()
    serializer_class = CostRecordSerializer
    filterset_fields = ['ci', 'month']

class ResourceRequestViewSet(viewsets.ModelViewSet):
    """资源申请管理"""
    queryset = ResourceRequest.objects.all()
    serializer_class = ResourceRequestSerializer
    search_fields = ['applicant', 'resource_type', 'reason']
    filterset_fields = ['status', 'resource_type']

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'pending':
            return Response({'detail': '只能审批待审批资源'}, status=400)
        obj.status = 'approved'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'pending':
            return Response({'detail': '只能审批待审批资源'}, status=400)
        obj.status = 'rejected'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'approved':
            return Response({'detail': '只能完成已批准资源'}, status=400)
        obj.status = 'provisioned'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)

@api_view(['GET'])
def cmdb_dashboard(request):
    ci_total = ConfigItem.objects.count()
    ci_active = ConfigItem.objects.filter(status='active').count()
    ci_by_type = list(ConfigItem.objects.values(type_name=F('ci_type__name'), color=F('ci_type__color')).annotate(count=Count('id')).order_by('-count'))
    for item in ci_by_type:
        item['color'] = item.get('color') or '#9c27b0'
    ci_by_env = list(ConfigItem.objects.values('environment').annotate(count=Count('id')).order_by('-count'))
    ci_by_biz = list(ConfigItem.objects.exclude(business_line='').values('business_line').annotate(count=Count('id'), total_cost=Sum('costs__amount')).order_by('-total_cost'))
    for item in ci_by_biz:
        item['total_cost'] = item['total_cost'] or 0
    total_monthly_cost = CostRecord.objects.filter(month=timezone.now().strftime('%Y-%m')).aggregate(total=Sum('amount'))['total'] or 0
    relation_count = CIRelation.objects.count()
    pending_requests = ResourceRequest.objects.filter(status='pending').count()

    return Response({
        'ci_total': ci_total,
        'ci_active': ci_active,
        'ci_by_type': ci_by_type,
        'ci_by_env': ci_by_env,
        'ci_by_business': ci_by_biz,
        'total_monthly_cost': float(total_monthly_cost),
        'relation_count': relation_count,
        'pending_requests': pending_requests,
    })

@api_view(['GET'])
def cmdb_topology(request):
    ci_type_id = request.query_params.get('ci_type')
    business_line = request.query_params.get('business_line')
    environment = request.query_params.get('environment')

    ci_qs = ConfigItem.objects.select_related('ci_type').all()
    if ci_type_id:
        ci_qs = ci_qs.filter(ci_type_id=ci_type_id)
    if business_line:
        ci_qs = ci_qs.filter(business_line=business_line)
    if environment:
        ci_qs = ci_qs.filter(environment=environment)

    nodes, ci_ids = [], set()
    for ci in ci_qs:
        ci_ids.add(ci.id)
        nodes.append({
            'id': ci.id, 'name': ci.name, 'type': ci.ci_type.name,
            'icon': ci.ci_type.icon, 'color': ci.ci_type.color or '#9c27b0',
            'status': ci.status, 'ip': ci.attributes.get('ip', ''),
            'env': ci.environment, 'business_line': ci.business_line,
        })

    relations = CIRelation.objects.filter(Q(source_id__in=ci_ids) | Q(target_id__in=ci_ids)).select_related('source', 'target')
    
    extra_ids = set()
    for rel in relations:
        if rel.source_id not in ci_ids: extra_ids.add(rel.source_id)
        if rel.target_id not in ci_ids: extra_ids.add(rel.target_id)
        
    for ci in ConfigItem.objects.select_related('ci_type').filter(id__in=extra_ids):
        # Exclude nodes outside filters
        if business_line and ci.business_line != business_line:
            continue
        if environment and ci.environment != environment:
            continue
        ci_ids.add(ci.id) # Include them so edges are drawn
        nodes.append({
            'id': ci.id, 'name': ci.name, 'type': ci.ci_type.name,
            'icon': ci.ci_type.icon, 'color': ci.ci_type.color or '#9c27b0',
            'status': ci.status, 'ip': ci.attributes.get('ip', ''),
            'env': ci.environment, 'business_line': ci.business_line,
        })

    # Only include edges where both nodes are in the final ci_ids
    filtered_edges = []
    for r in relations:
        if r.source_id in ci_ids and r.target_id in ci_ids:
            filtered_edges.append({'id': r.id, 'source': r.source_id, 'target': r.target_id, 'type': r.relation_type, 'label': r.get_relation_type_display()})
            
    return Response({'nodes': nodes, 'edges': filtered_edges})

@api_view(['GET'])
def cmdb_cost_report(request):
    month = request.query_params.get('month', timezone.now().strftime('%Y-%m'))
    qs = CostRecord.objects.filter(month=month)
    
    by_biz = list(qs.values('ci__business_line').annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True)).order_by('-total_cost'))
    by_env = list(qs.values('ci__environment').annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True)).order_by('-total_cost'))
    by_type = list(qs.values(type_name=F('ci__ci_type__name')).annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True)).order_by('-total_cost'))
    top_cost = list(qs.values(ci_id=F('ci__id'), name=F('ci__name'), business_line=F('ci__business_line'), environment=F('ci__environment'), type_name=F('ci__ci_type__name'), monthly_cost=F('amount')).order_by('-amount')[:10])
    
    cost_trend = list(CostRecord.objects.values('month').annotate(total=Sum('amount')).order_by('month'))[-6:]
    total = qs.aggregate(total=Sum('amount'))['total'] or 0

    return Response({
        'total_monthly_cost': float(total),
        'by_business': [{'business_line': i['ci__business_line'] or 'Uncategorized', 'total_cost': i['total_cost'], 'count': i['count']} for i in by_biz],
        'by_environment': [{'environment': i['ci__environment'], 'total_cost': i['total_cost'], 'count': i['count']} for i in by_env],
        'by_type': by_type,
        'top_cost_items': top_cost,
        'cost_trend': [{'period': i['month'], 'total': i['total']} for i in cost_trend],
    })

@api_view(['GET'])
def cmdb_optimization(request):
    suggestions = []
    return Response({
        'suggestions': suggestions,
        'total_potential_saving': 0,
        'suggestion_count': 0,
    })
