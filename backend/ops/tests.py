from urllib.parse import quote
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from ops.models import DockerHost, K8sCluster, K8sConfigRevision


TEST_LOG_PROVIDER_CONFIGS = {
    'loki': {
        'endpoint': 'http://loki.example:3100',
    },
    'elk': {
        'endpoint': 'https://es.example.com:9200',
        'auth_type': 'none',
        'index_pattern': 'logs-*',
        'time_field': '@timestamp',
        'message_fields': 'message,log,msg',
    },
    'sls': {
        'endpoint': 'cn-hangzhou.log.aliyuncs.com',
        'project': 'demo-project',
        'logstore': 'app-logstore',
        'topic': '',
        'access_key_id': 'test-ak',
        'access_key_secret': 'test-sk',
    },
}


class MockHttpResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self.payload


@override_settings(LOG_PROVIDER_CONFIGS=TEST_LOG_PROVIDER_CONFIGS)
class LogViewsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('ops-admin', 'ops@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_log_providers_returns_loki_elk_and_sls(self):
        response = self.client.get('/api/log/providers/')

        self.assertEqual(response.status_code, 200)
        providers = response.json()['providers']
        self.assertEqual([item['id'] for item in providers], ['loki', 'elk', 'sls'])
        self.assertEqual(providers[0]['defaults']['endpoint'], 'http://loki.example:3100')

    def test_can_create_log_datasource(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Production Loki',
                'provider': 'loki',
                'description': 'Production application logs',
                'is_enabled': True,
                'is_default': True,
                'config': {'endpoint': 'http://loki.internal:3100'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['name'], 'Production Loki')
        self.assertEqual(payload['config']['endpoint'], 'http://loki.internal:3100')

    @patch('ops.log_views.http_requests.get')
    def test_datasource_test_connection_uses_saved_config(self, mock_get):
        create_response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Test Source',
                'provider': 'loki',
                'config': {'endpoint': 'http://saved-loki:3100'},
            },
            format='json',
        )
        datasource_id = create_response.json()['id']

        mock_get.return_value = MockHttpResponse({'data': ['job', 'namespace']})

        response = self.client.post(f'/api/log/datasources/{datasource_id}/test_connection/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['preview_kind'], 'labels')
        mock_get.assert_called_once()

    @patch('ops.log_views.http_requests.get')
    def test_loki_query_normalizes_response(self, mock_get):
        mock_get.return_value = MockHttpResponse(
            {
                'data': {
                    'result': [
                        {
                            'stream': {'job': 'gateway', 'level': 'error'},
                            'values': [
                                ['1710000000000000000', 'request timeout'],
                                ['1710000001000000000', 'handled request'],
                            ],
                        }
                    ]
                }
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'loki',
                'query': '{job="gateway"}',
                'start_ms': '1710000000000',
                'end_ms': '1710003600000',
                'limit': 100,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'loki')
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['logs'][0]['source'], 'gateway')
        self.assertEqual(payload['logs'][0]['level'], 'error')
        self.assertTrue(payload['logs'][0]['timestamp'].endswith('Z'))
        mock_get.assert_called_once()

    @patch('ops.log_views.http_requests.get')
    def test_loki_query_can_use_saved_datasource(self, mock_get):
        create_response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Saved Loki',
                'provider': 'loki',
                'config': {'endpoint': 'http://saved-loki:3100'},
            },
            format='json',
        )
        datasource_id = create_response.json()['id']
        mock_get.return_value = MockHttpResponse(
            {
                'data': {
                    'result': [
                        {
                            'stream': {'job': 'api'},
                            'values': [['1710000000000000000', 'api started']],
                        }
                    ]
                }
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': '{job="api"}',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['logs'][0]['source'], 'api')

    def test_demo_loki_catalog_and_query_return_fake_logs(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Demo CN',
                'provider': 'loki',
                'config': {
                    'endpoint': 'http://demo-loki.example.com:3100',
                    'demo_mode': True,
                },
            },
            format='json',
        )
        datasource_id = response.json()['id']

        catalog_response = self.client.post(
            '/api/log/providers/loki/catalog/',
            {
                'datasource_id': datasource_id,
                'action': 'labels',
            },
            format='json',
        )
        self.assertEqual(catalog_response.status_code, 200)
        self.assertIn('job', catalog_response.json()['items'])

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': '{job="gateway-service"} |= "timeout"',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['provider'], 'loki')
        self.assertGreaterEqual(payload['total'], 1)
        self.assertEqual(payload['logs'][0]['source'], 'gateway-service')
        self.assertIn('timeout', payload['logs'][0]['message'])
        self.assertIn('trace_id', payload['logs'][0]['attributes'])

        label_values_response = self.client.post(
            '/api/log/providers/loki/catalog/',
            {
                'datasource_id': datasource_id,
                'action': 'label_values',
                'label': 'release',
            },
            format='json',
        )
        self.assertEqual(label_values_response.status_code, 200)
        self.assertIn('gray', label_values_response.json()['items'])

    def test_demo_loki_supports_stacktrace_and_gray_release_queries(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Demo Spring Cloud',
                'provider': 'loki',
                'config': {
                    'endpoint': 'http://demo-loki.example.com:3100',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        stack_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '{job="payment-service"} |= "NullPointerException"',
                'limit': 20,
            },
            format='json',
        )
        self.assertEqual(stack_response.status_code, 200)
        self.assertGreaterEqual(stack_response.json()['total'], 1)
        self.assertIn('PaymentCallbackController', stack_response.json()['logs'][0]['message'])

        gray_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '{release="gray"} |= "tenantId"',
                'limit': 20,
            },
            format='json',
        )
        self.assertEqual(gray_response.status_code, 200)
        self.assertGreaterEqual(gray_response.json()['total'], 1)
        self.assertEqual(gray_response.json()['logs'][0]['attributes']['release'], 'gray')

    @patch('ops.log_views.http_requests.request')
    def test_elk_catalog_lists_indices(self, mock_request):
        mock_request.return_value = MockHttpResponse(
            [
                {'index': 'logs-prod-2026.03.15', 'docs.count': '12', 'store.size': '48kb'},
                {'index': 'logs-stage-2026.03.15', 'docs.count': '6', 'store.size': '18kb'},
            ]
        )

        response = self.client.post(
            '/api/log/providers/elk/catalog/',
            {
                'config': {'endpoint': 'https://es.example.com:9200'},
                'index_pattern': 'logs-*',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['kind'], 'indices')
        self.assertEqual(payload['items'][0]['name'], 'logs-prod-2026.03.15')
        self.assertEqual(payload['items'][1]['docs_count'], '6')

    @patch('ops.log_views.http_requests.request')
    def test_elk_query_accepts_iso_timestamps(self, mock_request):
        mock_request.return_value = MockHttpResponse(
            {
                'took': 21,
                'hits': {
                    'total': {'value': 1},
                    'hits': [
                        {
                            '_index': 'logs-prod-2026.03.15',
                            '_source': {
                                '@timestamp': '2026-03-15T08:30:00Z',
                                'message': 'payment error in checkout',
                                'level': 'ERROR',
                                'service': {'name': 'payment'},
                            },
                        }
                    ],
                },
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'elk',
                'query': 'service.name:"payment"',
                'source': 'logs-prod-*',
                'start_ms': '1710000000000',
                'end_ms': '1710003600000',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'elk')
        self.assertEqual(payload['took_ms'], 21)
        self.assertEqual(payload['logs'][0]['timestamp'], '2026-03-15T08:30:00Z')
        self.assertEqual(payload['logs'][0]['level'], 'error')
        self.assertEqual(payload['logs'][0]['source'], 'logs-prod-2026.03.15')

    def test_demo_elk_query_returns_fake_logs_without_network(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'ELK Demo CN',
                'provider': 'elk',
                'config': {
                    'endpoint': 'https://demo-elastic.example.com:9200',
                    'index_pattern': 'logs-demo-*',
                    'time_field': '@timestamp',
                    'message_fields': 'message,log,msg',
                    'demo_mode': True,
                    'demo_indices': ['logs-demo-app-2026.03.15', 'logs-demo-security-2026.03.15'],
                },
            },
            format='json',
        )
        datasource_id = response.json()['id']

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': 'payment error',
                'source': 'logs-demo-*',
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['provider'], 'elk')
        self.assertGreaterEqual(payload['total'], 1)
        self.assertIn('payment', payload['logs'][0]['message'])
        self.assertIn('trace_id', payload['logs'][0]['attributes'])
        self.assertIn('com.agdevops', payload['logs'][0]['message'])

    def test_demo_elk_query_honors_high_limit_when_matches_are_available(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'ELK Demo Large',
                'provider': 'elk',
                'config': {
                    'endpoint': 'https://demo-elastic.example.com:9200',
                    'index_pattern': 'logs-demo-*',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '',
                'source': 'logs-demo-*',
                'limit': 200,
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertGreaterEqual(payload['total'], 200)
        self.assertEqual(len(payload['logs']), 200)

    @patch('ops.log_views.http_requests.request')
    def test_sls_catalog_lists_logstores(self, mock_request):
        mock_request.return_value = MockHttpResponse({'logstores': ['frontend', 'backend']})

        response = self.client.post('/api/log/providers/sls/catalog/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['kind'], 'logstores')
        self.assertEqual(payload['items'][0]['name'], 'frontend')
        self.assertEqual(payload['items'][1]['name'], 'backend')

    def test_demo_sls_query_returns_fake_logs(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'SLS Demo CN',
                'provider': 'sls',
                'config': {
                    'endpoint': 'cn-hangzhou.log.aliyuncs.com',
                    'project': 'demo-project',
                    'logstore': 'demo-hz-logstore',
                    'topic': 'order',
                    'access_key_id': 'demo-ak-id',
                    'access_key_secret': 'demo-ak-secret',
                    'demo_mode': True,
                    'demo_logstores': ['demo-hz-logstore', 'demo-hz-audit'],
                },
            },
            format='json',
        )
        datasource_id = response.json()['id']

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': 'timeout',
                'source': 'demo-hz-logstore',
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['provider'], 'sls')
        self.assertGreaterEqual(payload['total'], 1)
        self.assertEqual(payload['progress'], 'Complete')
        self.assertIn('trace_id', payload['logs'][0]['attributes'])
        self.assertIn('timeout', payload['logs'][0]['message'])

    def test_demo_sls_query_honors_high_limit_when_matches_are_available(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'SLS Demo Large',
                'provider': 'sls',
                'config': {
                    'endpoint': 'cn-shanghai.log.aliyuncs.com',
                    'project': 'demo-project',
                    'logstore': 'demo-sh-logstore',
                    'access_key_id': 'demo-ak-id',
                    'access_key_secret': 'demo-ak-secret',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '*',
                'source': 'demo-sh-logstore',
                'limit': 200,
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertGreaterEqual(payload['total'], 200)
        self.assertEqual(len(payload['logs']), 200)


class ContainerManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('container-admin', 'container@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        cache.clear()

    def test_k8s_summary_returns_demo_cluster_metrics(self):
        cluster = K8sCluster.objects.create(
            name='demo-cluster',
            kubeconfig='demo',
            status='connected',
        )

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['cluster_name'], 'demo-cluster')
        self.assertEqual(payload['nodes_total'], 4)
        self.assertEqual(payload['nodes_ready'], 4)
        self.assertEqual(payload['pods_total'], 15)
        self.assertEqual(payload['pods_abnormal'], 2)
        self.assertEqual(payload['total_restarts'], 8)
        self.assertEqual(payload['workloads_total'], 16)
        self.assertGreaterEqual(len(payload['alerts']), 1)

    @patch('ops.k8s_views._build_demo_summary')
    def test_k8s_summary_uses_short_cache(self, mock_build_demo_summary):
        cluster = K8sCluster.objects.create(
            name='demo-cluster-cache',
            kubeconfig='demo',
            status='connected',
        )
        mock_build_demo_summary.return_value = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 4,
            'nodes_ready': 4,
            'pods_total': 15,
            'pods_abnormal': 0,
            'pods_restarting': 0,
            'total_restarts': 0,
            'services_total': 0,
            'ingresses_total': 0,
            'workloads_total': 0,
            'workloads_degraded': 0,
            'pvcs_total': 0,
            'pvcs_pending': 0,
            'configmaps_total': 0,
            'secrets_total': 0,
            'alerts': [],
        }

        first = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')
        second = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(mock_build_demo_summary.call_count, 1)

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_list_containers_uses_json_line_format_for_broader_docker_compatibility(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-01', ip_address='10.0.0.10')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, '{"ID":"abc123","Names":"web","Image":"nginx:1.25","State":"running","Status":"Up 2h"}\n', '')

        response = self.client.get('/api/docker/containers/', {'host_id': host.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['name'], 'web')
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn("--format '{{json .}}'", issued_command)
        client.close.assert_called_once()

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_container_logs_quote_identifier_and_clamp_tail(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-02', ip_address='10.0.0.11')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'demo logs', '')
        container_id = 'demo; echo hacked'

        response = self.client.get(
            f"/api/docker/containers/{quote(container_id, safe='')}/logs/",
            {'host_id': host.id, 'tail': 99999},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['logs'], 'demo logs')
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn('docker logs --tail=2000', issued_command)
        self.assertIn("'demo; echo hacked'", issued_command)
        client.close.assert_called_once()

    def test_k8s_pod_exec_returns_demo_output(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-exec', kubeconfig='demo', status='connected')

        response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/pod_exec/',
            {
                'pod_name': 'api-server-5f8b7c6d4-r9p2w',
                'namespace': 'production',
                'command': 'whoami && pwd',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertIn('whoami && pwd', payload['output'])

    def test_k8s_scale_workload_updates_demo_state(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-scale', kubeconfig='demo', status='connected')

        scale_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/scale_workload/',
            {
                'workload_type': 'deployment',
                'name': 'nginx-deployment',
                'namespace': 'production',
                'replicas': 4,
            },
            format='json',
        )
        list_response = self.client.get(f'/api/k8s/clusters/{cluster.id}/deployments/', {'namespace': 'production'})

        self.assertEqual(scale_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        deployment = next(item for item in list_response.json() if item['name'] == 'nginx-deployment')
        self.assertEqual(deployment['replicas'], 4)

    def test_k8s_config_resource_update_and_rollback_preview_use_demo_snapshot(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-config', kubeconfig='demo', status='connected')

        detail_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_detail/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )
        update_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: auto\nkeepalive_timeout: 65\n',
            },
            format='json',
        )
        rollback_preview = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_rollback_preview/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(rollback_preview.status_code, 200)
        self.assertTrue(update_response.json()['resource']['rollback_available'])
        self.assertIn('worker_processes', update_response.json()['resource']['text'])
        self.assertIn('rollback', rollback_preview.json()['diff'])
        self.assertEqual(K8sConfigRevision.objects.filter(cluster=cluster).count(), 1)

    def test_k8s_config_resource_revisions_list_preview_and_targeted_rollback(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-revisions', kubeconfig='demo', status='connected')

        first_update = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: auto\nkeepalive_timeout: 65\n',
            },
            format='json',
        )
        second_update = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: 4\nkeepalive_timeout: 75\n',
            },
            format='json',
        )
        revisions_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_revisions/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(first_update.status_code, 200)
        self.assertEqual(second_update.status_code, 200)
        self.assertEqual(revisions_response.status_code, 200)
        items = revisions_response.json()['items']
        self.assertGreaterEqual(len(items), 2)
        target_revision = items[-1]
        self.assertEqual(target_revision['action'], 'update')

        preview_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_revision_preview/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'revision_id': target_revision['id'],
            },
        )
        rollback_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_rollback_to_revision/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'revision_id': target_revision['id'],
            },
            format='json',
        )
        detail_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_detail/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(rollback_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn('revision-', preview_response.json()['diff'])
        self.assertIn('key1', detail_response.json()['text'])
        self.assertIn('key3', detail_response.json()['text'])
        self.assertGreaterEqual(K8sConfigRevision.objects.filter(cluster=cluster).count(), 3)

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_remove_images_quotes_each_identifier(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-03', ip_address='10.0.0.12')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'deleted', '')

        response = self.client.delete(
            '/api/docker/images/remove/',
            {'host_id': host.id, 'image_ids': ['sha256:abc', 'bad; echo hacked']},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn("docker rmi", issued_command)
        self.assertIn("'bad; echo hacked'", issued_command)
        client.close.assert_called_once()

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_prune_dangling_images_uses_docker_image_prune(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-04', ip_address='10.0.0.13')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'Total reclaimed space: 0B', '')

        response = self.client.post('/api/docker/images/prune/', {'host_id': host.id}, format='json')

        self.assertEqual(response.status_code, 200)
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertEqual(issued_command, 'docker image prune -f 2>&1')
        client.close.assert_called_once()
