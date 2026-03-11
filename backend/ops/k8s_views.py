"""
Kubernetes 集群管理 API
使用 kubernetes Python 客户端连接并管理 K8s 集群
支持 demo 模式：kubeconfig 为 'demo' 时返回模拟数据
"""
import logging
import tempfile
import os
import yaml
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response

from .models import K8sCluster
from .serializers import K8sClusterSerializer

logger = logging.getLogger(__name__)


def _is_demo(cluster):
    return cluster.kubeconfig.strip() == 'demo'


# ====== Demo 模拟数据 ======
DEMO_NAMESPACES = [
    {'name': 'default', 'status': 'Active', 'created': '2026-01-15T08:00:00+08:00', 'labels': {}},
    {'name': 'kube-system', 'status': 'Active', 'created': '2026-01-15T08:00:00+08:00', 'labels': {}},
    {'name': 'monitoring', 'status': 'Active', 'created': '2026-02-01T10:30:00+08:00', 'labels': {}},
    {'name': 'production', 'status': 'Active', 'created': '2026-02-10T14:00:00+08:00', 'labels': {'env': 'prod'}},
    {'name': 'staging', 'status': 'Active', 'created': '2026-02-10T14:00:00+08:00', 'labels': {'env': 'staging'}},
]

DEMO_PODS = [
    {'name': 'nginx-deployment-7c5b4f9d8-x2k9p', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.15', 'containers': [{'name': 'nginx', 'image': 'nginx:1.25', 'ready': True}], 'restarts': 0, 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'nginx-deployment-7c5b4f9d8-m3h7q', 'namespace': 'production', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.22', 'containers': [{'name': 'nginx', 'image': 'nginx:1.25', 'ready': True}], 'restarts': 0, 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-server-5f8b7c6d4-r9p2w', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.18', 'containers': [{'name': 'api', 'image': 'myapp/api:v2.1.0', 'ready': True}], 'restarts': 1, 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'api-server-5f8b7c6d4-t4n8k', 'namespace': 'production', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.10', 'containers': [{'name': 'api', 'image': 'myapp/api:v2.1.0', 'ready': True}], 'restarts': 0, 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'redis-master-0', 'namespace': 'production', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.30', 'containers': [{'name': 'redis', 'image': 'redis:7.2-alpine', 'ready': True}], 'restarts': 0, 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'mysql-primary-0', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.25', 'containers': [{'name': 'mysql', 'image': 'mysql:8.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'web-frontend-6d9f8b7c5-j2m4n', 'namespace': 'staging', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.15', 'containers': [{'name': 'frontend', 'image': 'myapp/web:v2.2.0-rc1', 'ready': True}], 'restarts': 0, 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'web-frontend-6d9f8b7c5-k7p3q', 'namespace': 'staging', 'status': 'Pending', 'node': '', 'ip': '', 'containers': [{'name': 'frontend', 'image': 'myapp/web:v2.2.0-rc1', 'ready': False}], 'restarts': 0, 'created': '2026-03-08T16:05:00+08:00'},
    {'name': 'prometheus-server-0', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.40', 'containers': [{'name': 'prometheus', 'image': 'prom/prometheus:v2.51.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'grafana-7f8c9d6b5-w3x2y', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.35', 'containers': [{'name': 'grafana', 'image': 'grafana/grafana:10.4.0', 'ready': True}], 'restarts': 2, 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'alertmanager-0', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.42', 'containers': [{'name': 'alertmanager', 'image': 'prom/alertmanager:v0.27.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-01T10:40:00+08:00'},
    {'name': 'coredns-5d78c9689-b8k4m', 'namespace': 'kube-system', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.3', 'containers': [{'name': 'coredns', 'image': 'registry.k8s.io/coredns:v1.11.1', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'etcd-master', 'namespace': 'kube-system', 'status': 'Running', 'node': 'master', 'ip': '10.0.0.1', 'containers': [{'name': 'etcd', 'image': 'registry.k8s.io/etcd:3.5.12', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'kube-proxy-n7x2k', 'namespace': 'kube-system', 'status': 'Running', 'node': 'node-01', 'ip': '192.168.1.21', 'containers': [{'name': 'kube-proxy', 'image': 'registry.k8s.io/kube-proxy:v1.29.3', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'debug-pod-manual', 'namespace': 'default', 'status': 'Failed', 'node': 'node-02', 'ip': '10.244.2.99', 'containers': [{'name': 'debug', 'image': 'busybox:latest', 'ready': False}], 'restarts': 5, 'created': '2026-03-07T20:00:00+08:00'},
]

DEMO_SERVICES = [
    {'name': 'nginx-service', 'namespace': 'production', 'type': 'LoadBalancer', 'cluster_ip': '10.96.10.50', 'external_ip': '47.95.15.100', 'ports': '80→30080/TCP, 443→30443/TCP', 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-service', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.20.100', 'external_ip': '', 'ports': '8080/TCP', 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'redis-master', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.30.10', 'external_ip': '', 'ports': '6379/TCP', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'mysql-primary', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.30.20', 'external_ip': '', 'ports': '3306/TCP', 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'web-frontend', 'namespace': 'staging', 'type': 'NodePort', 'cluster_ip': '10.96.50.10', 'external_ip': '', 'ports': '3000→31000/TCP', 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'prometheus', 'namespace': 'monitoring', 'type': 'NodePort', 'cluster_ip': '10.96.60.10', 'external_ip': '', 'ports': '9090→30090/TCP', 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'grafana', 'namespace': 'monitoring', 'type': 'NodePort', 'cluster_ip': '10.96.60.20', 'external_ip': '', 'ports': '3000→30300/TCP', 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'kubernetes', 'namespace': 'default', 'type': 'ClusterIP', 'cluster_ip': '10.96.0.1', 'external_ip': '', 'ports': '443/TCP', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'kube-dns', 'namespace': 'kube-system', 'type': 'ClusterIP', 'cluster_ip': '10.96.0.10', 'external_ip': '', 'ports': '53/UDP, 53/TCP, 9153/TCP', 'created': '2026-01-15T08:00:00+08:00'},
]

DEMO_DEPLOYMENTS = [
    {'name': 'nginx-deployment', 'namespace': 'production', 'replicas': 2, 'ready_replicas': 2, 'available_replicas': 2, 'images': 'nginx:1.25', 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-server', 'namespace': 'production', 'replicas': 2, 'ready_replicas': 2, 'available_replicas': 2, 'images': 'myapp/api:v2.1.0', 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'web-frontend', 'namespace': 'staging', 'replicas': 2, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'myapp/web:v2.2.0-rc1', 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'grafana', 'namespace': 'monitoring', 'replicas': 1, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'grafana/grafana:10.4.0', 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'coredns', 'namespace': 'kube-system', 'replicas': 1, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'registry.k8s.io/coredns:v1.11.1', 'created': '2026-01-15T08:00:00+08:00'},
]

DEMO_NODES = [
    {'name': 'master-01', 'status': 'Ready', 'roles': 'control-plane', 'version': 'v1.29.3', 'internal_ip': '192.168.1.10', 'os_image': 'Ubuntu 22.04.3 LTS', 'cpu': '8000m', 'memory': '16Gi', 'pods_count': 12, 'age': '53d', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'node-01', 'status': 'Ready', 'roles': 'worker', 'version': 'v1.29.3', 'internal_ip': '192.168.1.21', 'os_image': 'Ubuntu 22.04.3 LTS', 'cpu': '8000m', 'memory': '14.8Gi', 'pods_count': 8, 'age': '53d', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'node-02', 'status': 'Ready', 'roles': 'worker', 'version': 'v1.29.3', 'internal_ip': '192.168.1.22', 'os_image': 'Ubuntu 22.04.3 LTS', 'cpu': '8000m', 'memory': '14.8Gi', 'pods_count': 6, 'age': '53d', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'node-03', 'status': 'Ready', 'roles': 'worker', 'version': 'v1.29.3', 'internal_ip': '192.168.1.23', 'os_image': 'Ubuntu 22.04.3 LTS', 'cpu': '8000m', 'memory': '14.8Gi', 'pods_count': 5, 'age': '30d', 'created': '2026-02-07T10:00:00+08:00'},
]

DEMO_STATEFULSETS = [
    {'name': 'redis-master', 'namespace': 'production', 'replicas': 1, 'ready_replicas': 1, 'images': 'redis:7.2-alpine', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'mysql-primary', 'namespace': 'production', 'replicas': 1, 'ready_replicas': 1, 'images': 'mysql:8.0', 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'prometheus-server', 'namespace': 'monitoring', 'replicas': 1, 'ready_replicas': 1, 'images': 'prom/prometheus:v2.51.0', 'created': '2026-02-01T10:30:00+08:00'},
]

DEMO_DAEMONSETS = [
    {'name': 'kube-proxy', 'namespace': 'kube-system', 'desired': 4, 'current': 4, 'ready': 4, 'images': 'registry.k8s.io/kube-proxy:v1.29.3', 'node_selector': '', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'calico-node', 'namespace': 'kube-system', 'desired': 4, 'current': 4, 'ready': 4, 'images': 'calico/node:v3.27.0', 'node_selector': '', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'node-exporter', 'namespace': 'monitoring', 'desired': 3, 'current': 3, 'ready': 3, 'images': 'prom/node-exporter:v1.7.0', 'node_selector': 'worker', 'created': '2026-02-01T10:30:00+08:00'},
]

DEMO_JOBS = [
    {'name': 'db-backup-20260309', 'namespace': 'production', 'completions': '1/1', 'duration': '45s', 'status': 'Complete', 'images': 'mysql:8.0', 'created': '2026-03-09T02:00:00+08:00'},
    {'name': 'data-migration-v2', 'namespace': 'production', 'completions': '3/3', 'duration': '12m', 'status': 'Complete', 'images': 'myapp/migrator:v2.1', 'created': '2026-03-08T10:00:00+08:00'},
]

DEMO_CRONJOBS = [
    {'name': 'db-backup', 'namespace': 'production', 'schedule': '0 2 * * *', 'suspend': False, 'active': 0, 'last_schedule': '2026-03-09T02:00:00+08:00', 'images': 'mysql:8.0', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'log-cleanup', 'namespace': 'kube-system', 'schedule': '0 3 * * 0', 'suspend': False, 'active': 0, 'last_schedule': '2026-03-09T03:00:00+08:00', 'images': 'busybox:latest', 'created': '2026-01-20T08:00:00+08:00'},
    {'name': 'cert-renew', 'namespace': 'default', 'schedule': '0 0 1 * *', 'suspend': True, 'active': 0, 'last_schedule': '2026-03-01T00:00:00+08:00', 'images': 'certbot:latest', 'created': '2026-02-01T08:00:00+08:00'},
]

DEMO_INGRESSES = [
    {'name': 'web-ingress', 'namespace': 'production', 'class': 'nginx', 'hosts': 'app.example.com', 'address': '47.95.15.100', 'ports': '80, 443', 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-ingress', 'namespace': 'production', 'class': 'nginx', 'hosts': 'api.example.com', 'address': '47.95.15.100', 'ports': '80, 443', 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'grafana-ingress', 'namespace': 'monitoring', 'class': 'nginx', 'hosts': 'grafana.example.com', 'address': '47.95.15.100', 'ports': '80, 443', 'created': '2026-02-01T10:35:00+08:00'},
]

DEMO_PVS = [
    {'name': 'pv-mysql-data', 'capacity': '50Gi', 'access_modes': 'RWO', 'reclaim_policy': 'Retain', 'status': 'Bound', 'claim': 'production/mysql-data-mysql-primary-0', 'storage_class': 'local-path', 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'pv-redis-data', 'capacity': '10Gi', 'access_modes': 'RWO', 'reclaim_policy': 'Retain', 'status': 'Bound', 'claim': 'production/redis-data-redis-master-0', 'storage_class': 'local-path', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'pv-prometheus', 'capacity': '100Gi', 'access_modes': 'RWO', 'reclaim_policy': 'Delete', 'status': 'Bound', 'claim': 'monitoring/prometheus-data', 'storage_class': 'nfs', 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'pv-available-01', 'capacity': '20Gi', 'access_modes': 'RWX', 'reclaim_policy': 'Retain', 'status': 'Available', 'claim': '', 'storage_class': 'nfs', 'created': '2026-03-01T08:00:00+08:00'},
]

DEMO_PVCS = [
    {'name': 'mysql-data-mysql-primary-0', 'namespace': 'production', 'status': 'Bound', 'volume': 'pv-mysql-data', 'capacity': '50Gi', 'access_modes': 'RWO', 'storage_class': 'local-path', 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'redis-data-redis-master-0', 'namespace': 'production', 'status': 'Bound', 'volume': 'pv-redis-data', 'capacity': '10Gi', 'access_modes': 'RWO', 'storage_class': 'local-path', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'prometheus-data', 'namespace': 'monitoring', 'status': 'Bound', 'volume': 'pv-prometheus', 'capacity': '100Gi', 'access_modes': 'RWO', 'storage_class': 'nfs', 'created': '2026-02-01T10:30:00+08:00'},
]

DEMO_STORAGECLASSES = [
    {'name': 'local-path', 'provisioner': 'rancher.io/local-path', 'reclaim_policy': 'Delete', 'binding_mode': 'WaitForFirstConsumer', 'allow_expansion': True, 'is_default': True, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'nfs', 'provisioner': 'nfs.csi.k8s.io', 'reclaim_policy': 'Delete', 'binding_mode': 'Immediate', 'allow_expansion': True, 'is_default': False, 'created': '2026-01-20T08:00:00+08:00'},
]

DEMO_CONFIGMAPS = [
    {'name': 'nginx-config', 'namespace': 'production', 'data_count': 3, 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-config', 'namespace': 'production', 'data_count': 5, 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'prometheus-config', 'namespace': 'monitoring', 'data_count': 2, 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'grafana-dashboards', 'namespace': 'monitoring', 'data_count': 8, 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'coredns', 'namespace': 'kube-system', 'data_count': 1, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'kube-proxy', 'namespace': 'kube-system', 'data_count': 2, 'created': '2026-01-15T08:00:00+08:00'},
]

DEMO_SECRETS = [
    {'name': 'mysql-credentials', 'namespace': 'production', 'type': 'Opaque', 'data_count': 2, 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'tls-cert-production', 'namespace': 'production', 'type': 'kubernetes.io/tls', 'data_count': 2, 'created': '2026-03-01T08:00:00+08:00'},
    {'name': 'registry-credentials', 'namespace': 'production', 'type': 'kubernetes.io/dockerconfigjson', 'data_count': 1, 'created': '2026-02-15T08:00:00+08:00'},
    {'name': 'grafana-admin', 'namespace': 'monitoring', 'type': 'Opaque', 'data_count': 2, 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'default-token', 'namespace': 'default', 'type': 'kubernetes.io/service-account-token', 'data_count': 3, 'created': '2026-01-15T08:00:00+08:00'},
]


def _get_k8s_client(cluster):
    """根据 kubeconfig 创建 K8s API 客户端"""
    from kubernetes import client, config

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    tmp.write(cluster.kubeconfig)
    tmp.flush()
    tmp.close()

    try:
        config.load_kube_config(config_file=tmp.name)
        return client
    finally:
        os.unlink(tmp.name)


def _filter_by_ns(data, namespace):
    if namespace == '_all':
        return data
    return [d for d in data if d['namespace'] == namespace]


class K8sClusterViewSet(viewsets.ModelViewSet):
    """K8s 集群连接管理"""
    queryset = K8sCluster.objects.all()
    serializer_class = K8sClusterSerializer
    pagination_class = None

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试集群连接"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response({'success': True, 'message': '连接成功 (Kubernetes v1.29.3) [演示模式]'})
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            version = k8s.VersionApi().get_code()
            cluster.status = 'connected'
            cluster.save(update_fields=['status'])
            return Response({
                'success': True,
                'message': f'连接成功 (Kubernetes {version.git_version})',
            })
        except Exception as e:
            cluster.status = 'error'
            cluster.save(update_fields=['status'])
            return Response({'success': False, 'message': f'连接失败: {str(e)}'})

    @action(detail=True, methods=['get'])
    def namespaces(self, request, pk=None):
        """获取命名空间列表"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response(DEMO_NAMESPACES)
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            ns_list = v1.list_namespace()
            data = [{
                'name': ns.metadata.name,
                'status': ns.status.phase,
                'created': ns.metadata.creation_timestamp.isoformat() if ns.metadata.creation_timestamp else '',
                'labels': ns.metadata.labels or {},
            } for ns in ns_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取命名空间失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def pods(self, request, pk=None):
        """获取 Pod 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_PODS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            if namespace == '_all':
                pod_list = v1.list_pod_for_all_namespaces()
            else:
                pod_list = v1.list_namespaced_pod(namespace=namespace)

            data = []
            for pod in pod_list.items:
                containers = [{
                    'name': c.name,
                    'image': c.image,
                    'ready': False,
                } for c in (pod.spec.containers or [])]

                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        for c in containers:
                            if c['name'] == cs.name:
                                c['ready'] = cs.ready or False
                                c['restart_count'] = cs.restart_count or 0

                data.append({
                    'name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'status': pod.status.phase,
                    'node': pod.spec.node_name or '',
                    'ip': pod.status.pod_ip or '',
                    'containers': containers,
                    'restarts': sum(c.get('restart_count', 0) for c in containers),
                    'created': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else '',
                })
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Pod 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def services(self, request, pk=None):
        """获取 Service 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_SERVICES, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            if namespace == '_all':
                svc_list = v1.list_service_for_all_namespaces()
            else:
                svc_list = v1.list_namespaced_service(namespace=namespace)

            data = [{
                'name': svc.metadata.name,
                'namespace': svc.metadata.namespace,
                'type': svc.spec.type,
                'cluster_ip': svc.spec.cluster_ip or '',
                'external_ip': ','.join(svc.spec.external_i_ps or []) if svc.spec.external_i_ps else '',
                'ports': ', '.join([
                    f"{p.port}{'→'+str(p.node_port) if p.node_port else ''}/{p.protocol}"
                    for p in (svc.spec.ports or [])
                ]),
                'created': svc.metadata.creation_timestamp.isoformat() if svc.metadata.creation_timestamp else '',
            } for svc in svc_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Service 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def deployments(self, request, pk=None):
        """获取 Deployment 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_DEPLOYMENTS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            apps_v1 = k8s.AppsV1Api()
            if namespace == '_all':
                dep_list = apps_v1.list_deployment_for_all_namespaces()
            else:
                dep_list = apps_v1.list_namespaced_deployment(namespace=namespace)

            data = [{
                'name': dep.metadata.name,
                'namespace': dep.metadata.namespace,
                'replicas': dep.spec.replicas or 0,
                'ready_replicas': dep.status.ready_replicas or 0,
                'available_replicas': dep.status.available_replicas or 0,
                'images': ', '.join([c.image for c in dep.spec.template.spec.containers]),
                'created': dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else '',
            } for dep in dep_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Deployment 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['post'], url_path='pods/(?P<pod_name>[^/]+)/restart')
    def restart_pod(self, request, pk=None, pod_name=None):
        """删除 Pod 以触发重启"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response({'success': True, 'message': f'Pod {pod_name} 正在重启 [演示模式]'})
        namespace = request.data.get('namespace', 'default')
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return Response({'success': True, 'message': f'Pod {pod_name} 正在重启'})
        except Exception as e:
            return Response({'success': False, 'message': f'重启失败: {str(e)}'}, status=400)

    # ====== 节点管理 ======
    @action(detail=True, methods=['get'])
    def nodes(self, request, pk=None):
        """获取节点列表"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response(DEMO_NODES)
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            node_list = v1.list_node()
            data = []
            for node in node_list.items:
                conditions = {c.type: c.status for c in (node.status.conditions or [])}
                roles = ','.join([l.replace('node-role.kubernetes.io/', '') for l in (node.metadata.labels or {}) if l.startswith('node-role.kubernetes.io/')])
                capacity = node.status.capacity or {}
                data.append({
                    'name': node.metadata.name,
                    'status': 'Ready' if conditions.get('Ready') == 'True' else 'NotReady',
                    'roles': roles or 'worker',
                    'version': node.status.node_info.kubelet_version if node.status.node_info else '',
                    'internal_ip': next((a.address for a in (node.status.addresses or []) if a.type == 'InternalIP'), ''),
                    'os_image': node.status.node_info.os_image if node.status.node_info else '',
                    'cpu': capacity.get('cpu', ''),
                    'memory': capacity.get('memory', ''),
                    'pods_count': 0,
                    'age': '',
                    'created': node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else '',
                })
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取节点失败: {str(e)}'}, status=400)

    # ====== 工作负载扩展 ======
    @action(detail=True, methods=['get'])
    def statefulsets(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_STATEFULSETS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            apps_v1 = k8s.AppsV1Api()
            items = (apps_v1.list_stateful_set_for_all_namespaces() if namespace == '_all'
                     else apps_v1.list_namespaced_stateful_set(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'replicas': i.spec.replicas or 0, 'ready_replicas': i.status.ready_replicas or 0,
                     'images': ', '.join([c.image for c in i.spec.template.spec.containers]),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def daemonsets(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_DAEMONSETS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            apps_v1 = k8s.AppsV1Api()
            items = (apps_v1.list_daemon_set_for_all_namespaces() if namespace == '_all'
                     else apps_v1.list_namespaced_daemon_set(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'desired': i.status.desired_number_scheduled or 0, 'current': i.status.current_number_scheduled or 0,
                     'ready': i.status.number_ready or 0,
                     'images': ', '.join([c.image for c in i.spec.template.spec.containers]),
                     'node_selector': str(i.spec.template.spec.node_selector or ''),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def jobs(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_JOBS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            batch_v1 = k8s.BatchV1Api()
            items = (batch_v1.list_job_for_all_namespaces() if namespace == '_all'
                     else batch_v1.list_namespaced_job(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'completions': f'{i.status.succeeded or 0}/{i.spec.completions or 1}',
                     'duration': '', 'status': 'Complete' if (i.status.succeeded or 0) >= (i.spec.completions or 1) else 'Running',
                     'images': ', '.join([c.image for c in i.spec.template.spec.containers]),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def cronjobs(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_CRONJOBS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            batch_v1 = k8s.BatchV1Api()
            items = (batch_v1.list_cron_job_for_all_namespaces() if namespace == '_all'
                     else batch_v1.list_namespaced_cron_job(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'schedule': i.spec.schedule, 'suspend': i.spec.suspend or False,
                     'active': len(i.status.active or []),
                     'last_schedule': i.status.last_schedule_time.isoformat() if i.status.last_schedule_time else '',
                     'images': ', '.join([c.image for c in i.spec.job_template.spec.template.spec.containers]),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ====== 网络管理 ======
    @action(detail=True, methods=['get'])
    def ingresses(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_INGRESSES, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            net_v1 = k8s.NetworkingV1Api()
            items = (net_v1.list_ingress_for_all_namespaces() if namespace == '_all'
                     else net_v1.list_namespaced_ingress(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'class': i.spec.ingress_class_name or '',
                     'hosts': ', '.join([r.host for r in (i.spec.rules or []) if r.host]),
                     'address': ', '.join([lb.ip or lb.hostname or '' for lb in (i.status.load_balancer.ingress or [])]) if i.status.load_balancer and i.status.load_balancer.ingress else '',
                     'ports': '80, 443' if i.spec.tls else '80',
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ====== 存储管理 ======
    @action(detail=True, methods=['get'])
    def pvs(self, request, pk=None):
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response(DEMO_PVS)
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            items = v1.list_persistent_volume().items
            data = [{'name': i.metadata.name, 'capacity': (i.spec.capacity or {}).get('storage', ''),
                     'access_modes': ','.join(i.spec.access_modes or []),
                     'reclaim_policy': i.spec.persistent_volume_reclaim_policy or '',
                     'status': i.status.phase, 'claim': f'{i.spec.claim_ref.namespace}/{i.spec.claim_ref.name}' if i.spec.claim_ref else '',
                     'storage_class': i.spec.storage_class_name or '',
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def pvcs(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_PVCS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            items = (v1.list_persistent_volume_claim_for_all_namespaces() if namespace == '_all'
                     else v1.list_namespaced_persistent_volume_claim(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'status': i.status.phase, 'volume': i.spec.volume_name or '',
                     'capacity': (i.status.capacity or {}).get('storage', ''),
                     'access_modes': ','.join(i.spec.access_modes or []),
                     'storage_class': i.spec.storage_class_name or '',
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def storageclasses(self, request, pk=None):
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response(DEMO_STORAGECLASSES)
        try:
            k8s = _get_k8s_client(cluster)
            storage_v1 = k8s.StorageV1Api()
            items = storage_v1.list_storage_class().items
            data = [{'name': i.metadata.name, 'provisioner': i.provisioner,
                     'reclaim_policy': i.reclaim_policy or 'Delete',
                     'binding_mode': i.volume_binding_mode or 'Immediate',
                     'allow_expansion': i.allow_volume_expansion or False,
                     'is_default': (i.metadata.annotations or {}).get('storageclass.kubernetes.io/is-default-class') == 'true',
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ====== 配置管理 ======
    @action(detail=True, methods=['get'])
    def configmaps(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_CONFIGMAPS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            items = (v1.list_config_map_for_all_namespaces() if namespace == '_all'
                     else v1.list_namespaced_config_map(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'data_count': len(i.data or {}),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def secrets(self, request, pk=None):
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_SECRETS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            items = (v1.list_secret_for_all_namespaces() if namespace == '_all'
                     else v1.list_namespaced_secret(namespace=namespace)).items
            data = [{'name': i.metadata.name, 'namespace': i.metadata.namespace,
                     'type': i.type or 'Opaque', 'data_count': len(i.data or {}),
                     'created': i.metadata.creation_timestamp.isoformat() if i.metadata.creation_timestamp else ''
                     } for i in items]
            return Response(data)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ====== YAML 查看 ======
    def _build_demo_yaml(self, resource_type, name, namespace, demo_list):
        """从 demo 数据生成模拟的 YAML"""
        item = None
        for d in demo_list:
            if d.get('name') == name:
                if namespace and namespace != '_all' and d.get('namespace') and d['namespace'] != namespace:
                    continue
                item = d
                break

        if not item:
            item = demo_list[0] if demo_list else {'name': name}

        # 构建一个类似真实 K8s YAML 的结构
        api_version_map = {
            'pod': 'v1', 'service': 'v1', 'namespace': 'v1', 'node': 'v1',
            'configmap': 'v1', 'secret': 'v1', 'pv': 'v1', 'pvc': 'v1',
            'deployment': 'apps/v1', 'statefulset': 'apps/v1', 'daemonset': 'apps/v1',
            'job': 'batch/v1', 'cronjob': 'batch/v1',
            'ingress': 'networking.k8s.io/v1', 'storageclass': 'storage.k8s.io/v1',
        }
        kind_map = {
            'pod': 'Pod', 'service': 'Service', 'namespace': 'Namespace', 'node': 'Node',
            'configmap': 'ConfigMap', 'secret': 'Secret', 'pv': 'PersistentVolume',
            'pvc': 'PersistentVolumeClaim', 'deployment': 'Deployment',
            'statefulset': 'StatefulSet', 'daemonset': 'DaemonSet',
            'job': 'Job', 'cronjob': 'CronJob', 'ingress': 'Ingress',
            'storageclass': 'StorageClass',
        }

        metadata = {'name': item.get('name', name)}
        if item.get('namespace'):
            metadata['namespace'] = item['namespace']
        if item.get('labels'):
            metadata['labels'] = item['labels']
        if item.get('created'):
            metadata['creationTimestamp'] = item['created']

        result = {
            'apiVersion': api_version_map.get(resource_type, 'v1'),
            'kind': kind_map.get(resource_type, resource_type.capitalize()),
            'metadata': metadata,
        }

        # 根据资源类型添加 spec
        if resource_type == 'deployment':
            result['spec'] = {
                'replicas': item.get('replicas', 1),
                'selector': {'matchLabels': {'app': item.get('name', name)}},
                'template': {
                    'metadata': {'labels': {'app': item.get('name', name)}},
                    'spec': {'containers': [{'name': item.get('name', name), 'image': item.get('images', 'nginx:latest'), 'ports': [{'containerPort': 80}]}]},
                },
            }
            result['status'] = {'replicas': item.get('replicas', 1), 'readyReplicas': item.get('ready_replicas', 0), 'availableReplicas': item.get('available_replicas', 0)}
        elif resource_type == 'pod':
            result['spec'] = {
                'containers': [{'name': c.get('name', 'main'), 'image': c.get('image', 'nginx:latest')} for c in item.get('containers', [{'name': 'main', 'image': 'nginx'}])],
                'nodeName': item.get('node', ''),
            }
            result['status'] = {'phase': item.get('status', 'Running'), 'podIP': item.get('ip', '')}
        elif resource_type == 'service':
            result['spec'] = {
                'type': item.get('type', 'ClusterIP'),
                'clusterIP': item.get('cluster_ip', ''),
                'ports': [{'port': 80, 'protocol': 'TCP'}],
                'selector': {'app': item.get('name', name)},
            }
        elif resource_type == 'node':
            result['spec'] = {}
            result['status'] = {
                'conditions': [{'type': 'Ready', 'status': 'True' if item.get('status') == 'Ready' else 'False'}],
                'nodeInfo': {'kubeletVersion': item.get('version', ''), 'osImage': item.get('os_image', '')},
                'addresses': [{'type': 'InternalIP', 'address': item.get('internal_ip', '')}],
                'capacity': {'cpu': item.get('cpu', ''), 'memory': item.get('memory', '')},
            }
        elif resource_type == 'namespace':
            result['status'] = {'phase': item.get('status', 'Active')}
        elif resource_type == 'statefulset':
            result['spec'] = {
                'replicas': item.get('replicas', 1),
                'selector': {'matchLabels': {'app': item.get('name', name)}},
                'template': {
                    'metadata': {'labels': {'app': item.get('name', name)}},
                    'spec': {'containers': [{'name': item.get('name', name), 'image': item.get('images', 'nginx:latest')}]},
                },
            }
            result['status'] = {'replicas': item.get('replicas', 1), 'readyReplicas': item.get('ready_replicas', 0)}
        elif resource_type == 'daemonset':
            result['spec'] = {
                'selector': {'matchLabels': {'app': item.get('name', name)}},
                'template': {
                    'metadata': {'labels': {'app': item.get('name', name)}},
                    'spec': {'containers': [{'name': item.get('name', name), 'image': item.get('images', '')}]},
                },
            }
            result['status'] = {'desiredNumberScheduled': item.get('desired', 0), 'currentNumberScheduled': item.get('current', 0), 'numberReady': item.get('ready', 0)}
        elif resource_type == 'job':
            result['spec'] = {
                'template': {'spec': {'containers': [{'name': 'job', 'image': item.get('images', '')}], 'restartPolicy': 'Never'}},
            }
            result['status'] = {'succeeded': 1 if item.get('status') == 'Complete' else 0}
        elif resource_type == 'cronjob':
            result['spec'] = {
                'schedule': item.get('schedule', ''),
                'suspend': item.get('suspend', False),
                'jobTemplate': {
                    'spec': {'template': {'spec': {'containers': [{'name': 'job', 'image': item.get('images', '')}], 'restartPolicy': 'Never'}}},
                },
            }
        elif resource_type == 'ingress':
            result['spec'] = {
                'ingressClassName': item.get('class', 'nginx'),
                'rules': [{'host': h.strip(), 'http': {'paths': [{'path': '/', 'pathType': 'Prefix', 'backend': {'service': {'name': item.get('name', ''), 'port': {'number': 80}}}}]}} for h in item.get('hosts', '').split(',') if h.strip()],
            }
        elif resource_type == 'pv':
            result['spec'] = {
                'capacity': {'storage': item.get('capacity', '')},
                'accessModes': [item.get('access_modes', 'ReadWriteOnce')],
                'persistentVolumeReclaimPolicy': item.get('reclaim_policy', 'Retain'),
                'storageClassName': item.get('storage_class', ''),
            }
            if item.get('claim'):
                parts = item['claim'].split('/')
                result['spec']['claimRef'] = {'namespace': parts[0] if len(parts) > 1 else '', 'name': parts[-1]}
            result['status'] = {'phase': item.get('status', '')}
        elif resource_type == 'pvc':
            result['spec'] = {
                'accessModes': [item.get('access_modes', 'ReadWriteOnce')],
                'storageClassName': item.get('storage_class', ''),
                'resources': {'requests': {'storage': item.get('capacity', '')}},
                'volumeName': item.get('volume', ''),
            }
            result['status'] = {'phase': item.get('status', '')}
        elif resource_type == 'storageclass':
            result['provisioner'] = item.get('provisioner', '')
            result['reclaimPolicy'] = item.get('reclaim_policy', 'Delete')
            result['volumeBindingMode'] = item.get('binding_mode', 'Immediate')
            result['allowVolumeExpansion'] = item.get('allow_expansion', False)
        elif resource_type == 'configmap':
            result['data'] = {f'key{i+1}': f'value{i+1}' for i in range(item.get('data_count', 1))}
        elif resource_type == 'secret':
            result['type'] = item.get('type', 'Opaque')
            result['data'] = {f'key{i+1}': 'base64encodedvalue' for i in range(item.get('data_count', 1))}

        return yaml.dump(result, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @action(detail=True, methods=['get'], url_path='resource_yaml')
    def resource_yaml(self, request, pk=None):
        """获取指定资源的 YAML 定义"""
        cluster = self.get_object()
        resource_type = request.query_params.get('type', '')
        name = request.query_params.get('name', '')
        namespace = request.query_params.get('namespace', 'default')

        if not resource_type or not name:
            return Response({'detail': '缺少 type 或 name 参数'}, status=400)

        if _is_demo(cluster):
            demo_map = {
                'node': DEMO_NODES, 'namespace': DEMO_NAMESPACES, 'pod': DEMO_PODS,
                'deployment': DEMO_DEPLOYMENTS, 'statefulset': DEMO_STATEFULSETS,
                'daemonset': DEMO_DAEMONSETS, 'job': DEMO_JOBS, 'cronjob': DEMO_CRONJOBS,
                'service': DEMO_SERVICES, 'ingress': DEMO_INGRESSES,
                'pv': DEMO_PVS, 'pvc': DEMO_PVCS, 'storageclass': DEMO_STORAGECLASSES,
                'configmap': DEMO_CONFIGMAPS, 'secret': DEMO_SECRETS,
            }
            demo_list = demo_map.get(resource_type, [])
            yaml_content = self._build_demo_yaml(resource_type, name, namespace, demo_list)
            return Response({'yaml': yaml_content})

        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            apps_v1 = k8s.AppsV1Api()
            batch_v1 = k8s.BatchV1Api()
            net_v1 = k8s.NetworkingV1Api()
            storage_v1 = k8s.StorageV1Api()

            read_funcs = {
                'node': lambda: v1.read_node(name),
                'namespace': lambda: v1.read_namespace(name),
                'pod': lambda: v1.read_namespaced_pod(name, namespace),
                'service': lambda: v1.read_namespaced_service(name, namespace),
                'deployment': lambda: apps_v1.read_namespaced_deployment(name, namespace),
                'statefulset': lambda: apps_v1.read_namespaced_stateful_set(name, namespace),
                'daemonset': lambda: apps_v1.read_namespaced_daemon_set(name, namespace),
                'job': lambda: batch_v1.read_namespaced_job(name, namespace),
                'cronjob': lambda: batch_v1.read_namespaced_cron_job(name, namespace),
                'ingress': lambda: net_v1.read_namespaced_ingress(name, namespace),
                'pv': lambda: v1.read_persistent_volume(name),
                'pvc': lambda: v1.read_namespaced_persistent_volume_claim(name, namespace),
                'storageclass': lambda: storage_v1.read_storage_class(name),
                'configmap': lambda: v1.read_namespaced_config_map(name, namespace),
                'secret': lambda: v1.read_namespaced_secret(name, namespace),
            }

            read_func = read_funcs.get(resource_type)
            if not read_func:
                return Response({'detail': f'不支持的资源类型: {resource_type}'}, status=400)

            resource_obj = read_func()
            api_client = k8s.ApiClient()
            resource_dict = api_client.sanitize_for_serialization(resource_obj)
            yaml_content = yaml.dump(resource_dict, default_flow_style=False, allow_unicode=True, sort_keys=False)
            return Response({'yaml': yaml_content})
        except Exception as e:
            return Response({'detail': f'获取 YAML 失败: {str(e)}'}, status=400)

    # ------ 工作负载 Pod 列表 ------
    @action(detail=True, methods=['get'])
    def workload_pods(self, request, pk=None):
        cluster = self.get_object()
        workload_type = request.query_params.get('workload_type', '')
        workload_name = request.query_params.get('name', '')
        namespace = request.query_params.get('namespace', 'default')

        if _is_demo(cluster):
            # Demo: match pods whose name starts with the workload name
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)
            prefix = workload_name
            pods = []
            for p in DEMO_PODS:
                if p['name'].startswith(prefix) and (namespace == '_all' or p['namespace'] == namespace):
                    created = _dt.datetime.fromisoformat(p['created'])
                    age_delta = now - created
                    days = age_delta.days
                    hours = age_delta.seconds // 3600
                    age_str = f'{days}d' if days > 0 else f'{hours}h'
                    host_ip = ''
                    for n in DEMO_NODES:
                        if n['name'] == p.get('node', ''):
                            host_ip = n['internal_ip']
                            break
                    containers = p.get('containers', [])
                    cpu_req = '100m'
                    mem_req = '128Mi'
                    if containers:
                        img = containers[0].get('image', '')
                        if 'mysql' in img: cpu_req, mem_req = '500m', '1Gi'
                        elif 'redis' in img: cpu_req, mem_req = '250m', '256Mi'
                        elif 'prometheus' in img: cpu_req, mem_req = '500m', '512Mi'
                        elif 'nginx' in img: cpu_req, mem_req = '100m', '128Mi'
                    pods.append({
                        'name': p['name'],
                        'namespace': p['namespace'],
                        'status': p['status'],
                        'node': p.get('node', ''),
                        'pod_ip': p.get('ip', ''),
                        'host_ip': host_ip,
                        'containers': [c['name'] for c in containers],
                        'restarts': p.get('restarts', 0),
                        'cpu_request': cpu_req,
                        'memory_request': mem_req,
                        'age': age_str,
                        'created': p['created'],
                    })
            return Response(pods)

        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            apps_v1 = k8s.AppsV1Api()
            batch_v1 = k8s.BatchV1Api()

            # Get label selector from the workload
            label_selector = ''
            if workload_type == 'deployment':
                obj = apps_v1.read_namespaced_deployment(workload_name, namespace)
                label_selector = ','.join(f'{k}={v}' for k, v in (obj.spec.selector.match_labels or {}).items())
            elif workload_type == 'statefulset':
                obj = apps_v1.read_namespaced_stateful_set(workload_name, namespace)
                label_selector = ','.join(f'{k}={v}' for k, v in (obj.spec.selector.match_labels or {}).items())
            elif workload_type == 'daemonset':
                obj = apps_v1.read_namespaced_daemon_set(workload_name, namespace)
                label_selector = ','.join(f'{k}={v}' for k, v in (obj.spec.selector.match_labels or {}).items())
            elif workload_type in ('job', 'cronjob'):
                if workload_type == 'cronjob':
                    label_selector = f'job-name={workload_name}'
                else:
                    obj = batch_v1.read_namespaced_job(workload_name, namespace)
                    label_selector = ','.join(f'{k}={v}' for k, v in (obj.spec.selector.match_labels or {}).items())

            pod_list = v1.list_namespaced_pod(namespace, label_selector=label_selector)
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)
            pods = []
            for p in pod_list.items:
                age_delta = now - p.metadata.creation_timestamp.replace(tzinfo=_dt.timezone.utc)
                days = age_delta.days
                hours = age_delta.seconds // 3600
                age_str = f'{days}d' if days > 0 else f'{hours}h'
                restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
                containers = [c.name for c in p.spec.containers]
                cpu_req = '0m'
                mem_req = '0Mi'
                if p.spec.containers:
                    res = p.spec.containers[0].resources
                    if res and res.requests:
                        cpu_req = res.requests.get('cpu', '0m')
                        mem_req = res.requests.get('memory', '0Mi')
                pods.append({
                    'name': p.metadata.name,
                    'namespace': p.metadata.namespace,
                    'status': p.status.phase,
                    'node': p.spec.node_name or '',
                    'pod_ip': p.status.pod_ip or '',
                    'host_ip': p.status.host_ip or '',
                    'containers': containers,
                    'restarts': restarts,
                    'cpu_request': cpu_req,
                    'memory_request': mem_req,
                    'age': age_str,
                    'created': p.metadata.creation_timestamp.isoformat(),
                })
            return Response(pods)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ------ Pod 日志 ------
    @action(detail=True, methods=['get'])
    def pod_logs(self, request, pk=None):
        cluster = self.get_object()
        pod_name = request.query_params.get('pod_name', '')
        namespace = request.query_params.get('namespace', 'default')
        container = request.query_params.get('container', '')
        tail_lines = int(request.query_params.get('tail_lines', 200))

        if _is_demo(cluster):
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)
            lines = []
            for i in range(min(tail_lines, 50)):
                ts = (now - _dt.timedelta(minutes=50 - i)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
                if 'nginx' in pod_name:
                    msgs = [
                        f'{ts} 10.244.1.1 - - [GET /api/health HTTP/1.1] 200 15 "-" "kube-probe/1.29"',
                        f'{ts} 10.244.2.5 - - [GET / HTTP/1.1] 200 612 "-" "Mozilla/5.0"',
                        f'{ts} 10.244.1.8 - - [GET /static/css/main.css HTTP/1.1] 304 0',
                        f'{ts} 10.244.3.2 - - [POST /api/data HTTP/1.1] 201 89 "-" "curl/7.88"',
                    ]
                elif 'api' in pod_name:
                    msgs = [
                        f'{ts} INFO  [main] Application started on port 8080',
                        f'{ts} DEBUG [http] GET /api/users -> 200 (12ms)',
                        f'{ts} INFO  [db] Connection pool: active=5, idle=15, total=20',
                        f'{ts} WARN  [cache] Cache miss rate: 15.2%',
                    ]
                elif 'redis' in pod_name:
                    msgs = [
                        f'{ts} # Server initialized',
                        f'{ts} * Ready to accept connections tcp',
                        f'{ts} # 1 changes in 900 seconds. Saving...',
                        f'{ts} * Background saving started by pid 42',
                    ]
                elif 'mysql' in pod_name:
                    msgs = [
                        f'{ts} [Note] [MY-010131] [Server] mysqld: ready for connections. Version: 8.0.36',
                        f'{ts} [Note] [MY-012487] [InnoDB] DDL log recovery: begin',
                        f'{ts} [Note] [MY-012488] [InnoDB] DDL log recovery: end',
                        f'{ts} [Note] [MY-010747] [Server] Plugin \'mysql_native_password\' is marked as deprecated',
                    ]
                else:
                    msgs = [
                        f'{ts} level=info msg="Starting process"',
                        f'{ts} level=info msg="Health check passed"',
                        f'{ts} level=debug msg="Processing request" duration=5ms',
                        f'{ts} level=info msg="Metrics collected" count=42',
                    ]
                lines.append(msgs[i % len(msgs)])
            return Response({'logs': '\n'.join(lines), 'container': container or 'main'})

        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            kwargs = {'name': pod_name, 'namespace': namespace, 'tail_lines': tail_lines}
            if container:
                kwargs['container'] = container
            log_content = v1.read_namespaced_pod_log(**kwargs)
            return Response({'logs': log_content, 'container': container or ''})
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

    # ------ 资源事件 ------
    @action(detail=True, methods=['get'])
    def resource_events(self, request, pk=None):
        cluster = self.get_object()
        resource_type = request.query_params.get('type', '')
        resource_name = request.query_params.get('name', '')
        namespace = request.query_params.get('namespace', 'default')

        if _is_demo(cluster):
            import datetime as _dt, random as _rand
            now = _dt.datetime.now(_dt.timezone.utc)
            events = []
            # Generate plausible events
            normal_events = [
                ('Scheduled', f'Successfully assigned {namespace}/{resource_name} to node-01'),
                ('Pulling', f'Pulling image for {resource_name}'),
                ('Pulled', f'Successfully pulled image'),
                ('Created', f'Created container for {resource_name}'),
                ('Started', f'Started container for {resource_name}'),
                ('ScalingReplicaSet', f'Scaled up replica set {resource_name}-7c5b4f9d8 to 2'),
            ]
            warning_events = [
                ('BackOff', f'Back-off restarting failed container in pod {resource_name}'),
                ('Unhealthy', f'Readiness probe failed: connection refused'),
                ('FailedScheduling', f'0/4 nodes are available: insufficient memory'),
            ]

            # Add 3-6 normal events
            for i, (reason, msg) in enumerate(normal_events[:_rand.randint(3, 5)]):
                t = (now - _dt.timedelta(hours=_rand.randint(1, 48))).isoformat()
                events.append({
                    'type': 'Normal',
                    'reason': reason,
                    'message': msg,
                    'first_time': t,
                    'last_time': t,
                    'count': 1,
                    'source': 'kubelet, node-01',
                })

            # Maybe add 1 warning for some resources
            if resource_name in ('web-frontend', 'debug-pod-manual') or 'pending' in resource_name.lower():
                warn = warning_events[_rand.randint(0, len(warning_events) - 1)]
                t = (now - _dt.timedelta(minutes=_rand.randint(5, 120))).isoformat()
                events.append({
                    'type': 'Warning',
                    'reason': warn[0],
                    'message': warn[1],
                    'first_time': t,
                    'last_time': t,
                    'count': _rand.randint(1, 8),
                    'source': 'kubelet, node-02',
                })

            # Sort by last_time desc
            events.sort(key=lambda e: e['last_time'], reverse=True)
            return Response(events)

        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            kind_map = {
                'pod': 'Pod', 'node': 'Node', 'deployment': 'Deployment',
                'statefulset': 'StatefulSet', 'daemonset': 'DaemonSet',
                'job': 'Job', 'cronjob': 'CronJob', 'service': 'Service',
                'ingress': 'Ingress', 'pvc': 'PersistentVolumeClaim',
                'pv': 'PersistentVolume', 'configmap': 'ConfigMap', 'secret': 'Secret',
            }
            kind = kind_map.get(resource_type, resource_type)

            # Cluster-scoped resources (Node, PV)
            if resource_type in ('node', 'pv'):
                event_list = v1.list_event_for_all_namespaces(
                    field_selector=f'involvedObject.name={resource_name},involvedObject.kind={kind}'
                )
            else:
                event_list = v1.list_namespaced_event(
                    namespace,
                    field_selector=f'involvedObject.name={resource_name},involvedObject.kind={kind}'
                )
            events = []
            for e in event_list.items:
                events.append({
                    'type': e.type or 'Normal',
                    'reason': e.reason or '',
                    'message': e.message or '',
                    'first_time': e.first_timestamp.isoformat() if e.first_timestamp else '',
                    'last_time': e.last_timestamp.isoformat() if e.last_timestamp else '',
                    'count': e.count or 1,
                    'source': f'{e.source.component}, {e.source.host}' if e.source else '',
                })
            events.sort(key=lambda ev: ev['last_time'], reverse=True)
            return Response(events)
        except Exception as e:
            return Response({'detail': str(e)}, status=400)
