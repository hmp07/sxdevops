from urllib.parse import quote
import copy
from datetime import datetime, timedelta
from decimal import Decimal
import ssl
import sys
from unittest.mock import MagicMock, patch

import uuid

import requests

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from django.core.cache import cache
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from ops.models import (
    Alert,
    AlertAction,
    AlertIntegration,
    AlertNotificationChannel,
    AlertNotificationRule,
    AlertRecipient,
    AlertRecipientGroup,
    DockerHost,
    GrafanaSetting,
    Host,
    HostTask,
    K8sCluster,
    K8sConfigRevision,
    LogDataSource,
    MetricDataSource,
    ObservabilityDataSourceLink,
    TracingDataSource,
    ZabbixDataSource,
)
from ops.k8s_views import _K8sApiProxy, _prepare_kubeconfig, _resource_stale_cache_key, _summary_stale_cache_key
from ops.tracing_providers import ObservabilityError, _build_topology_from_trace_details, _http_get, _tempo_flatten_trace, _trace_detail_from_spans
from ops.forecast import linear_forecast, moving_average, summarize_series, threshold_eta
from ops.prometheus_demo import evaluate_promql, list_label_values, list_metric_names


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

TEST_OBSERVABILITY_CONFIG = {
    'skywalking': {
        'enabled': True,
        'ui_url': 'http://skywalking.example.com',
        'oap_url': 'http://skywalking-oap.example.com',
        'graphql_path': '/graphql',
        'default_layer': '',
        'demo_mode': True,
    },
    'grafana': {
        'enabled': True,
        'url': 'http://grafana.example.com',
        'default_path': '/d/apm-overview',
        'demo_mode': True,
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
        self.assertIn('com.sxdevops', payload['logs'][0]['message'])

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


@override_settings(LOG_PROVIDER_CONFIGS=TEST_LOG_PROVIDER_CONFIGS, OBSERVABILITY_CONFIG=TEST_OBSERVABILITY_CONFIG)
class ObservabilityViewsTests(TestCase):
    def setUp(self):
        cache.clear()  # 追踪 catalog/数据源缓存跨用例隔离
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('observer-admin', 'observer@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_datasource_link_resolves_trace_to_loki_query(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            trace_id_fields=['trace_id', 'traceId'],
            log_query_template='${__tags} | json | trace_id="${__trace.traceId}"',
            log_label_mappings=[{'trace_tag': 'service.name', 'log_label': 'container'}],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_trace_to_logs/',
            {
                'trace_id': '0123456789abcdef0123456789abcdef',
                'tracing_datasource_id': trace_source.id,
                'tags': {'service.name': 'checkout'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['log_datasource']['id'], log_source.id)
        self.assertEqual(payload['query'], '{container="checkout"} | json | trace_id="0123456789abcdef0123456789abcdef"')

    def test_datasource_link_resolves_trace_to_loki_query_with_zero_padded_trace_id(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            trace_id_fields=['trace_id', 'traceId'],
            log_query_template='${__tags} | json | trace_id="${__trace.traceId}"',
            log_label_mappings=[{'trace_tag': 'service.name', 'log_label': 'container'}],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_trace_to_logs/',
            {
                'trace_id': '8e3554cc72d7f903d71408b205ab5a2',
                'tracing_datasource_id': trace_source.id,
                'tags': {'service.name': 'api-gateway'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload['query'],
            '{container="api-gateway"} | json | trace_id="08e3554cc72d7f903d71408b205ab5a2"',
        )

    def test_datasource_link_resolves_trace_to_loki_query_with_multi_zero_padding(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            trace_id_fields=['trace_id', 'traceId'],
            log_query_template='${__tags} | json | trace_id="${__trace.traceId}"',
            log_label_mappings=[{'trace_tag': 'service.name', 'log_label': 'container'}],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_trace_to_logs/',
            {
                'trace_id': '1234567890abcdef1234567890abcd',
                'tracing_datasource_id': trace_source.id,
                'tags': {'service.name': 'order-service'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload['query'],
            '{container="order-service"} | json | trace_id="001234567890abcdef1234567890abcd"',
        )

    def test_datasource_link_resolves_trace_to_grafana_dashboard(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            trace_to_grafana_enabled=True,
            grafana_dashboard_key='apm-overview',
            grafana_variable_mappings=[{'trace_tag': 'service.name', 'variable': 'service'}],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_trace_to_grafana/',
            {
                'trace_id': '0123456789abcdef0123456789abcdef',
                'tracing_datasource_id': trace_source.id,
                'tags': {'service.name': 'checkout'},
                'from': 1710000000000,
                'to': 1710000300000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard']['key'], 'apm-overview')
        self.assertEqual(payload['query']['dashboard'], 'apm-overview')
        self.assertEqual(payload['query']['traceId'], '0123456789abcdef0123456789abcdef')
        self.assertEqual(payload['query']['var-service'], 'checkout')
        self.assertEqual(payload['query']['from'], 1710000000000)

    def test_datasource_link_resolves_log_to_grafana_dashboard(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            log_to_grafana_enabled=True,
            grafana_dashboard_key='apm-overview',
            log_label_mappings=[{'trace_tag': 'service.name', 'log_label': 'container'}],
            grafana_variable_mappings=[{'trace_tag': 'service.name', 'variable': 'service'}],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_log_to_grafana/',
            {
                'trace_id': '0123456789abcdef0123456789abcdef',
                'log_datasource_id': log_source.id,
                'attributes': {'container': 'checkout'},
                'message': 'checkout failed',
                'from': 1710000000000,
                'to': 1710000300000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard']['key'], 'apm-overview')
        self.assertEqual(payload['query']['dashboard'], 'apm-overview')
        self.assertEqual(payload['query']['source'], 'log')
        self.assertEqual(payload['query']['traceId'], '0123456789abcdef0123456789abcdef')
        self.assertEqual(payload['query']['var-service'], 'checkout')

    def test_datasource_link_resolves_trace_to_workload_dashboard(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            trace_to_grafana_enabled=True,
            grafana_dashboard_key='apm-overview',
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
                {'trace_tag': 'workload.type', 'variable': 'workload_type'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_trace_to_grafana/',
            {
                'trace_id': '0123456789abcdef0123456789abcdef',
                'tracing_datasource_id': trace_source.id,
                'dashboard_key': 'Kubernetes / Compute Resources / Workload',
                'tags': {'service.name': 'checkout', 'service.namespace': 'default'},
                'from': 1710000000000,
                'to': 1710000300000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard']['key'], 'kubernetes-compute-resources-workload')
        self.assertEqual(payload['query']['dashboard'], 'kubernetes-compute-resources-workload')
        self.assertEqual(payload['query']['traceId'], '0123456789abcdef0123456789abcdef')
        self.assertEqual(payload['query']['var-workload'], 'checkout')
        self.assertEqual(payload['query']['var-namespace'], 'default')
        self.assertEqual(payload['query']['from'], 1710000000000)

    def test_datasource_link_resolves_log_to_workload_dashboard(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            log_to_grafana_enabled=True,
            grafana_dashboard_key='apm-overview',
            log_label_mappings=[
                {'trace_tag': 'service.name', 'log_label': 'app'},
                {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
            ],
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_log_to_grafana/',
            {
                'trace_id': '0123456789abcdef0123456789abcdef',
                'log_datasource_id': log_source.id,
                'attributes': {'app': 'checkout', 'namespace': 'default'},
                'message': 'checkout failed',
                'dashboard_key': 'Kubernetes / Compute Resources / Workload',
                'from': 1710000000000,
                'to': 1710000300000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard']['key'], 'kubernetes-compute-resources-workload')
        self.assertEqual(payload['query']['dashboard'], 'kubernetes-compute-resources-workload')
        self.assertEqual(payload['query']['source'], 'log')
        self.assertEqual(payload['query']['traceId'], '0123456789abcdef0123456789abcdef')
        self.assertEqual(payload['query']['var-workload'], 'checkout')
        self.assertEqual(payload['query']['var-namespace'], 'default')
        self.assertEqual(payload['query']['var-workload_type'], 'deployment')

    def test_datasource_link_resolves_log_to_workload_dashboard_without_trace_id(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            log_to_grafana_enabled=True,
            grafana_dashboard_key='kubernetes-compute-resources-workload',
            log_label_mappings=[
                {'trace_tag': 'service.name', 'log_label': 'app'},
                {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
            ],
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
                {'trace_tag': 'workload.type', 'variable': 'workload_type'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_log_to_grafana/',
            {
                'log_datasource_id': log_source.id,
                'attributes': {'app': 'checkout', 'namespace': 'default', 'workload_type': 'deployment', 'trace_id': '0123456789abcdef0123456789abcdef'},
                'message': 'checkout failed trace_id=0123456789abcdef0123456789abcdef',
                'dashboard_key': 'Kubernetes / Compute Resources / Workload',
                'ignore_trace_id': True,
                'from': 1710000000000,
                'to': 1710000300000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard']['key'], 'kubernetes-compute-resources-workload')
        self.assertNotIn('traceId', payload['query'])
        self.assertEqual(payload['query']['var-workload'], 'checkout')
        self.assertEqual(payload['query']['var-namespace'], 'default')
        self.assertEqual(payload['query']['var-workload_type'], 'deployment')

    def test_datasource_link_resolves_workload_dashboard_to_loki_query(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            grafana_dashboard_key='kubernetes-compute-resources-workload',
            log_label_mappings=[
                {'trace_tag': 'service.name', 'log_label': 'container'},
                {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
            ],
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_grafana_to_logs/',
            {
                'dashboard_key': 'kubernetes-compute-resources-workload',
                'var-workload': 'checkout',
                'var-namespace': 'default',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['log_datasource']['id'], log_source.id)
        self.assertEqual(payload['tags']['service.name'], 'checkout')
        self.assertEqual(payload['tags']['service.namespace'], 'default')
        self.assertEqual(payload['query'], '{container="checkout",namespace="default"}')

    def test_datasource_link_resolves_workload_dashboard_to_trace_target(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            grafana_dashboard_key='kubernetes-compute-resources-workload',
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_grafana_to_trace/',
            {
                'dashboard_key': 'Kubernetes / Compute Resources / Workload',
                'query': {
                    'var-workload': 'checkout',
                    'var-namespace': 'default',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['tracing_datasource']['id'], trace_source.id)
        self.assertEqual(payload['service'], 'checkout')
        self.assertEqual(payload['tags']['service.namespace'], 'default')

    def test_datasource_link_resolve_grafana_to_trace_requires_dashboard_match(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            grafana_dashboard_key='kubernetes-compute-resources-workload',
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
                {'trace_tag': 'service.namespace', 'variable': 'namespace'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_grafana_to_trace/',
            {
                'dashboard_key': 'Node Exporter / Nodes',
                'query': {
                    'var-job': 'node-exporter',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['detail'], '未找到可用的 Grafana 看板到链路关联')

    def test_datasource_link_resolve_grafana_to_logs_requires_dashboard_match(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            is_default=True,
            grafana_dashboard_key='kubernetes-compute-resources-workload',
            log_label_mappings=[
                {'trace_tag': 'service.name', 'log_label': 'container'},
            ],
            grafana_variable_mappings=[
                {'trace_tag': 'service.name', 'variable': 'workload'},
            ],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_grafana_to_logs/',
            {
                'dashboard_key': 'Node Exporter / Nodes',
                'query': {
                    'var-job': 'node-exporter',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['detail'], '未找到可用的 Grafana 看板到日志关联')

    def test_datasource_link_resolves_log_to_trace_target(self):
        log_source = LogDataSource.objects.create(
            name='电商-k3s-loki',
            provider='loki',
            config={'endpoint': 'http://loki.example:3100'},
        )
        trace_source = TracingDataSource.objects.create(
            name='电商-k3s-tempo',
            provider='tempo',
            config={'query_url': 'http://tempo.example:3200'},
        )
        ObservabilityDataSourceLink.objects.create(
            name='电商 k3s Loki ↔ Tempo',
            log_datasource=log_source,
            tracing_datasource=trace_source,
            trace_id_fields=['trace_id'],
        )

        response = self.client.post(
            '/api/observability/datasource-links/resolve_log_to_trace/',
            {
                'log_datasource_id': log_source.id,
                'attributes': {'trace_id': 'abcdef0123456789abcdef0123456789'},
                'message': 'checkout failed',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['trace_id'], 'abcdef0123456789abcdef0123456789')
        self.assertEqual(payload['tracing_datasource']['id'], trace_source.id)

    def test_observability_overview_falls_back_to_demo_without_skywalking_oap(self):
        with override_settings(
            OBSERVABILITY_CONFIG={
                'skywalking': {
                    'enabled': True,
                    'ui_url': '',
                    'oap_url': '',
                    'graphql_path': '/graphql',
                    'default_layer': '',
                    'demo_mode': True,
                },
                'grafana': {
                    'enabled': True,
                    'url': '',
                    'default_path': '',
                    'demo_mode': True,
                },
            }
        ):
            response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['modules']['tracing']['source'], 'demo')
        self.assertEqual(payload['modules']['tracing']['provider'], 'skywalking')
        self.assertEqual(payload['modules']['grafana']['source'], 'demo')
        self.assertEqual(payload['summary']['dashboard_count'], 5)
        self.assertGreaterEqual(payload['summary']['service_count'], 1)
        self.assertTrue(any(item['provider'] == 'demo' for item in payload['providers']))

    @patch('ops.observability_views.user_has_permissions')
    def test_observability_overview_allows_log_only_user_without_trace_visibility(self, mock_permissions):
        existing_payload = self.client.get('/api/log/datasources/').json()
        existing_count = existing_payload.get('count', 0) if isinstance(existing_payload, dict) else len(existing_payload)
        self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Overview Loki',
                'provider': 'loki',
                'config': {'endpoint': 'http://overview-loki:3100'},
            },
            format='json',
        )
        limited_user = get_user_model().objects.create_user('log-viewer', password='Admin@123456')
        self.client.force_authenticate(user=limited_user)

        def permission_side_effect(user, codes):
            code = codes[0] if codes else ''
            return code == 'ops.log.datasource.view'

        mock_permissions.side_effect = permission_side_effect

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload['modules']['tracing'])
        self.assertIsNone(payload['modules']['grafana'])
        self.assertEqual(payload['modules']['logs']['datasource_count'], existing_count + 1)
        self.assertEqual(len(payload['navigation']), 1)
        self.assertEqual(payload['navigation'][0]['path'], '/logs')

    def test_observability_overview_uses_configured_grafana_dashboards(self):
        with override_settings(
            OBSERVABILITY_CONFIG={
                **TEST_OBSERVABILITY_CONFIG,
                'grafana': {
                    'enabled': True,
                    'url': 'http://grafana.example.com',
                    'default_path': '',
                    'demo_mode': True,
                    'dashboards': [
                        {
                            'key': 'custom-trace',
                            'title': '自定义链路总览',
                            'slug': 'custom-trace',
                            'path': '/d/custom-trace',
                            'panel_count': 6,
                            'tags': ['custom', 'trace'],
                            'description': '自定义链路看板',
                        }
                    ],
                },
            }
        ):
            response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['modules']['grafana']['dashboard_count'], 1)
        self.assertEqual(payload['modules']['grafana']['dashboards'][0]['key'], 'custom-trace')
        self.assertEqual(payload['modules']['grafana']['dashboards'][0]['url'], 'http://grafana.example.com/d/custom-trace')

    def test_grafana_config_endpoint_returns_defaults_when_not_persisted(self):
        response = self.client.get('/api/observability/grafana/config/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['persisted'])
        self.assertEqual(payload['url'], 'http://grafana.example.com')
        self.assertEqual(payload['default_path'], '/d/apm-overview')
        self.assertEqual(payload['folders'], [])
        self.assertGreaterEqual(len(payload['dashboards']), 1)

    def test_grafana_config_endpoint_can_persist_page_config(self):
        response = self.client.put(
            '/api/observability/grafana/config/',
            {
                'enabled': True,
                'url': '',
                'default_path': '',
                'folders': [
                    {'path': '基础设施', 'folder_collapsed': False},
                    {'path': '基础设施/节点', 'folder_collapsed': True},
                ],
                'dashboards': [
                    {
                        'key': 'infra-overview',
                        'title': '基础设施总览',
                        'slug': 'infra-overview',
                        'description': '基础设施看板',
                        'folder': '基础设施',
                        'path': '',
                        'full_url': 'http://grafana.internal.local/d/infra-overview',
                        'panel_count': 12,
                        'tags': ['infra'],
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['persisted'])
        self.assertEqual(payload['url'], '')
        self.assertEqual(payload['default_path'], '')
        self.assertEqual(len(payload['folders']), 2)
        self.assertEqual(payload['folders'][1]['path'], '基础设施/节点')

        setting = GrafanaSetting.objects.get(name='default')
        self.assertEqual(setting.url, '')
        self.assertEqual(setting.default_path, '')
        self.assertEqual(setting.folders[0]['path'], '基础设施')
        self.assertEqual(setting.dashboards[0]['folder'], '基础设施')
        self.assertEqual(setting.updated_by, 'observer-admin')

    def test_grafana_config_put_with_url_persists_url(self):
        """修复回归：看板配置保存不再清空已存 Grafana URL。"""
        GrafanaSetting.objects.create(
            name='default',
            enabled=True,
            url='http://grafana.keep.example.com',
            default_path='/d/keep',
            api_token='glsa_keep_token',
        )
        response = self.client.put(
            '/api/observability/grafana/config/',
            {
                'enabled': True,
                'url': 'http://grafana.keep.example.com',
                'default_path': '/d/keep',
                'folders': [],
                'dashboards': [
                    {
                        'key': 'keep-overview',
                        'title': '保留配置看板',
                        'slug': 'keep-overview',
                        'description': '',
                        'folder': '基础设施',
                        'path': '',
                        'full_url': 'http://grafana.keep.example.com/d/keep-overview',
                        'panel_count': 3,
                        'tags': [],
                        'uid': 'keep-uid',
                    }
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        setting = GrafanaSetting.objects.get(name='default')
        self.assertEqual(setting.url, 'http://grafana.keep.example.com')
        self.assertEqual(setting.default_path, '/d/keep')
        # 未传 api_token（write_only）时保留已存 Token
        self.assertEqual(setting.api_token, 'glsa_keep_token')

    def test_grafana_config_get_reports_has_token_flags(self):
        GrafanaSetting.objects.create(
            name='default',
            url='http://grafana.token.example.com',
            api_token='glsa_test_token',
            jwt_secret='demo-secret',
        )
        response = self.client.get('/api/observability/grafana/config/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['has_api_token'])
        self.assertTrue(payload['has_jwt_secret'])
        # Token/secret 永不回传
        self.assertNotIn('api_token', payload)
        self.assertNotIn('jwt_secret', payload)

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_success(self, mock_get):
        GrafanaSetting.objects.create(
            name='default',
            url='http://grafana.health.internal.local',
            api_token='glsa_test_token',
        )
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '11.3.1', 'commit': 'abc', 'database': 'ok'}
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Main Org.'}
        login_resp = MagicMock()
        login_resp.status_code = 302
        login_resp.headers = {'Location': '/'}
        mock_get.side_effect = [health_resp, login_resp, org_resp]

        response = self.client.post('/api/observability/grafana/test/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['version'], '11.3.1')
        self.assertEqual(payload['org']['name'], 'Main Org.')
        # Bearer token 从 DB 读取
        auth_headers = mock_get.call_args_list[0][1]['headers']
        self.assertEqual(auth_headers['Authorization'], 'Bearer glsa_test_token')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_with_unsaved_overrides(self, mock_get):
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '10.4.0'}
        login_resp = MagicMock()
        login_resp.status_code = 302
        login_resp.headers = {'Location': '/'}
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Demo Org'}
        mock_get.side_effect = [health_resp, login_resp, org_resp]

        response = self.client.post(
            '/api/observability/grafana/test/',
            {'url': 'http://grafana.override.internal.local', 'api_token': 'glsa_override'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['version'], '10.4.0')
        first_url = mock_get.call_args_list[0][0][0]
        self.assertIn('grafana.override.internal.local', first_url)
        auth_headers = mock_get.call_args_list[0][1]['headers']
        self.assertEqual(auth_headers['Authorization'], 'Bearer glsa_override')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_does_not_leak_token_to_custom_url(self, mock_get):
        """SSRF 防护：自定义 URL 未显式提供 token 时，不得附带存储凭据。"""
        GrafanaSetting.objects.create(
            name='default',
            url='http://grafana.saved.internal.local',
            api_token='glsa_stored_secret',
        )
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '11.0.0'}
        login_resp = MagicMock()
        login_resp.status_code = 302
        login_resp.headers = {'Location': '/'}
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Main Org.'}
        mock_get.side_effect = [health_resp, login_resp, org_resp]

        response = self.client.post(
            '/api/observability/grafana/test/',
            {'url': 'http://attacker.internal.local'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        auth_headers = mock_get.call_args_list[0][1]['headers']
        self.assertNotIn('Authorization', auth_headers, '存储 Token 不得附加到自定义 URL')
        first_url = mock_get.call_args_list[0][0][0]
        self.assertIn('attacker.internal.local', first_url)

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_rejects_non_http_scheme(self, mock_get):
        GrafanaSetting.objects.create(name='default', url='http://grafana.saved.internal.local')
        response = self.client.post(
            '/api/observability/grafana/test/',
            {'url': 'file:///etc/passwd'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        mock_get.assert_not_called()

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_rejects_link_local_metadata(self, mock_get):
        """SSRF 防护：拒绝云元数据地址（169.254.169.254）与链路本地网段。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.saved.internal.local')
        for bad_url in ('http://169.254.169.254/latest/meta-data/', 'http://169.254.10.10/api/health'):
            response = self.client.post(
                '/api/observability/grafana/test/',
                {'url': bad_url},
                format='json',
            )
            self.assertEqual(response.status_code, 400, f'{bad_url} 应被拒绝')
        mock_get.assert_not_called()

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_discover_returns_dashboards(self, mock_get):
        GrafanaSetting.objects.create(name='default', url='http://grafana.disc.internal.local', api_token='glsa_disc')
        folders_resp = MagicMock()
        folders_resp.status_code = 200
        folders_resp.json.return_value = [{'uid': 'f1', 'title': '基础设施'}]
        dashboards_resp = MagicMock()
        dashboards_resp.status_code = 200
        dashboards_resp.json.return_value = [
            {
                'uid': 'infra-overview',
                'title': '基础设施总览',
                'slug': 'infra-overview',
                'url': '/d/infra-overview/ji-chu-she-shi-zong-lan',
                'folderUid': 'f1',
                'folderTitle': '基础设施',
                'tags': ['infra'],
            }
        ]
        mock_get.side_effect = [folders_resp, dashboards_resp]

        response = self.client.post('/api/observability/grafana/discover/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['folder_count'], 1)
        self.assertEqual(payload['dashboard_count'], 1)
        self.assertEqual(payload['dashboards'][0]['uid'], 'infra-overview')
        self.assertEqual(payload['dashboards'][0]['folderTitle'], '基础设施')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_discover_uses_uri_segment_as_slug_fallback(self, mock_get):
        """Grafana 12 返回 slug 为空、uri 形如 "db/{slug}"：取末段作为 slug，避免拼出错误路径。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.disc.internal.local', api_token='glsa_disc')
        folders_resp = MagicMock()
        folders_resp.status_code = 200
        folders_resp.json.return_value = []
        dashboards_resp = MagicMock()
        dashboards_resp.status_code = 200
        dashboards_resp.json.return_value = [
            {
                'uid': 'fe0ylyg4cdd6oc',
                'title': 'Zabbix Server Dashboard',
                'slug': '',
                'uri': 'db/zabbix-server-dashboard',
                'url': '/d/fe0ylyg4cdd6oc/zabbix-server-dashboard',
                'tags': [],
            }
        ]
        mock_get.side_effect = [folders_resp, dashboards_resp]

        response = self.client.post('/api/observability/grafana/discover/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard_count'], 1)
        self.assertEqual(payload['dashboards'][0]['slug'], 'zabbix-server-dashboard')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_follows_same_host_redirect_once(self, mock_get):
        """反代强制 HTTP→HTTPS（同主机 301）：跟随一次并成功返回版本。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.redirect.internal.local', api_token='glsa_redir')
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {'Location': 'https://grafana.redirect.internal.local/api/health'}
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '12.4.2'}
        login_resp = MagicMock()
        login_resp.status_code = 302
        login_resp.headers = {'Location': '/'}
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Main Org.'}
        mock_get.side_effect = [redirect_resp, health_resp, login_resp, org_resp]

        response = self.client.post('/api/observability/grafana/test/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['version'], '12.4.2')
        self.assertEqual(payload['org']['name'], 'Main Org.')
        # 第二次调用为同主机重定向目标，认证头原样携带
        self.assertEqual(mock_get.call_args_list[1][1]['headers']['Authorization'], 'Bearer glsa_redir')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_rejects_cross_host_redirect(self, mock_get):
        """SSRF 边界：跨主机重定向不跟随，返回可读错误。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.redirect.internal.local', api_token='glsa_redir')
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {'Location': 'http://attacker.internal.local/api/health'}
        org_resp = MagicMock()
        org_resp.status_code = 401
        mock_get.side_effect = [redirect_resp, org_resp]

        response = self.client.post('/api/observability/grafana/test/', {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('重定向', response.json()['message'])
        self.assertEqual(mock_get.call_count, 2, '跨主机重定向不得被跟随')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_html_response_readable_error(self, mock_get):
        """2xx 但返回 HTML（如登录页/反代拦截）：报可读错误而非 JSONDecodeError 原文。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.html.internal.local', api_token='glsa_html')
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.side_effect = ValueError('Expecting value: line 1 column 1 (char 0)')
        org_resp = MagicMock()
        org_resp.status_code = 401
        mock_get.side_effect = [health_resp, org_resp]

        response = self.client.post('/api/observability/grafana/test/', {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('非 JSON', response.json()['message'])

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_honors_body_tls_and_timeout(self, mock_get):
        """请求体 tls_verify/timeout 覆盖已保存配置，测试弹窗开关真正生效。"""
        GrafanaSetting.objects.create(
            name='default', url='http://grafana.body.internal.local', api_token='glsa_body', tls_verify=True, timeout=10
        )
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '12.4.2'}
        login_resp = MagicMock()
        login_resp.status_code = 302
        login_resp.headers = {'Location': '/'}
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Main Org.'}
        mock_get.side_effect = [health_resp, login_resp, org_resp]

        response = self.client.post(
            '/api/observability/grafana/test/',
            {'url': 'http://grafana.body.internal.local', 'api_token': 'glsa_body', 'tls_verify': False, 'timeout': 17},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        first_call_kwargs = mock_get.call_args_list[0][1]
        self.assertIs(first_call_kwargs['verify'], False)
        self.assertEqual(first_call_kwargs['timeout'], 17)

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_test_connection_embed_probe_reports_anonymous_off(self, mock_get):
        """匿名访问未开启（匿名 /api/org 返回 401）时给出可读的嵌入预警。"""
        GrafanaSetting.objects.create(name='default', url='http://grafana.embed.internal.local', api_token='glsa_embed')
        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json.return_value = {'version': '12.4.2'}
        probe_resp = MagicMock()
        probe_resp.status_code = 401
        org_resp = MagicMock()
        org_resp.status_code = 200
        org_resp.json.return_value = {'id': 1, 'name': 'Main Org.'}
        mock_get.side_effect = [health_resp, probe_resp, org_resp]

        response = self.client.post('/api/observability/grafana/test/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('匿名访问未开启', payload['embed_warning'])

    def test_observability_overview_degrades_when_tracing_provider_unconfigured(self):
        """链路追踪未配置时 overview 降级返回 200 + warnings，不再 400 阻断聚合页。"""
        with override_settings(
            OBSERVABILITY_CONFIG={
                'skywalking': {
                    'enabled': True,
                    'ui_url': '',
                    'oap_url': '',
                    'graphql_path': '/graphql',
                    'default_layer': '',
                    'demo_mode': False,
                },
                'grafana': {'enabled': True, 'url': '', 'default_path': '', 'demo_mode': True},
            }
        ):
            response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('warnings'))
        self.assertIn('查询地址未配置', payload['warnings'][0])
        self.assertIsNotNone(payload['modules']['grafana'])

    def test_grafana_embed_token_requires_jwt_secret(self):
        response = self.client.post('/api/observability/grafana/embed-token/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['token'], '')
        self.assertEqual(payload['mode'], 'anonymous')

    def test_grafana_embed_token_signs_jwt(self):
        import jwt as pyjwt

        GrafanaSetting.objects.create(name='default', jwt_secret='demo-shared-secret')
        response = self.client.post('/api/observability/grafana/embed-token/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['mode'], 'jwt')
        claims = pyjwt.decode(payload['token'], 'demo-shared-secret', algorithms=['HS256'])
        self.assertEqual(claims['sub'], 'observer-admin')
        self.assertIn('exp', claims)

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_dashboard_panels_flattens_rows(self, mock_get):
        GrafanaSetting.objects.create(name='default', url='http://grafana.panels.internal.local', api_token='glsa_panels')
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            'dashboard': {
                'uid': 'k8s-workload',
                'slug': 'kubernetes-compute-resources-workload',
                'title': 'K8s 工作负载资源',
                'panels': [
                    {'id': 1, 'title': 'CPU 使用率', 'type': 'timeseries'},
                    {'id': 2, 'title': '行容器', 'type': 'row', 'panels': [
                        {'id': 3, 'title': '内存使用率', 'type': 'timeseries'},
                    ]},
                ],
                'templating': {'list': [{'name': 'cluster', 'current': {'text': 'prod-k8s'}}]},
            }
        }
        mock_get.return_value = resp

        response = self.client.get('/api/observability/grafana/dashboard/panels/?uid=k8s-workload')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # row 类型被过滤，嵌套面板被拍平
        titles = [item['title'] for item in payload['panels']]
        self.assertIn('CPU 使用率', titles)
        self.assertIn('内存使用率', titles)
        self.assertNotIn('行容器', titles)
        self.assertEqual(payload['variables'][0]['name'], 'cluster')

    def test_observability_overview_prefers_persisted_grafana_setting(self):
        GrafanaSetting.objects.create(
            name='default',
            enabled=True,
            url='http://grafana.persisted.example.com',
            default_path='/d/persisted-overview',
            dashboards=[
                {
                    'key': 'persisted-overview',
                    'title': '持久化看板',
                    'slug': 'persisted-overview',
                    'path': '/d/persisted-overview',
                    'panel_count': 8,
                    'tags': ['ops'],
                    'description': '来自页面保存的 Grafana 配置',
                }
            ],
            updated_by='observer-admin',
        )

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['modules']['grafana']['url'], 'http://grafana.persisted.example.com')
        self.assertEqual(payload['modules']['grafana']['dashboards'][0]['key'], 'persisted-overview')
        self.assertEqual(
            payload['modules']['grafana']['dashboards'][0]['url'],
            'http://grafana.persisted.example.com/d/persisted-overview',
        )

    def test_observability_overview_uses_dashboard_full_url_when_provided(self):
        GrafanaSetting.objects.create(
            name='default',
            enabled=True,
            url='',
            default_path='',
            dashboards=[
                {
                    'key': 'nightingale-style',
                    'title': '夜莺式看板',
                    'slug': 'nightingale-style',
                    'path': '',
                    'full_url': 'http://203.0.113.209:3000/d/custom-board?orgId=1&kiosk=true',
                    'panel_count': 9,
                    'tags': ['容器', '全局'],
                    'description': '直接写完整 Grafana 链接',
                }
            ],
            updated_by='observer-admin',
        )

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['modules']['grafana']['configured'])
        self.assertEqual(
            payload['modules']['grafana']['dashboards'][0]['url'],
            'http://203.0.113.209:3000/d/custom-board?orgId=1&kiosk=true',
        )
        self.assertEqual(
            payload['modules']['grafana']['dashboards'][0]['full_url'],
            'http://203.0.113.209:3000/d/custom-board?orgId=1&kiosk=true',
        )
        self.assertEqual(
            payload['modules']['grafana']['embed_url'],
            'http://203.0.113.209:3000/d/custom-board?orgId=1&kiosk=true',
        )

    def test_observability_overview_returns_configured_grafana_folders(self):
        GrafanaSetting.objects.create(
            name='default',
            enabled=True,
            url='',
            default_path='',
            folders=[
                {'path': '基础设施', 'folder_collapsed': False},
                {'path': '基础设施/节点', 'folder_collapsed': True},
                {'path': '应用服务', 'folder_collapsed': False},
            ],
            dashboards=[
                {
                    'key': 'node-overview',
                    'title': '节点总览',
                    'slug': 'node-overview',
                    'folder': '基础设施/节点',
                    'path': '',
                    'full_url': 'http://grafana.example.com/d/node-overview',
                    'panel_count': 6,
                    'tags': ['node'],
                    'description': '节点资源看板',
                }
            ],
            updated_by='observer-admin',
        )

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['modules']['grafana']['folders']), 3)
        self.assertEqual(payload['modules']['grafana']['folders'][1]['path'], '基础设施/节点')
        self.assertEqual(payload['modules']['grafana']['dashboards'][0]['folder'], '基础设施/节点')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_promql_query_uses_grafana_datasource_proxy(self, mock_get):
        mock_get.side_effect = [
            MockHttpResponse({'id': 12, 'uid': 'prometheus-infra'}),
            MockHttpResponse({
                'status': 'success',
                'data': {
                    'resultType': 'vector',
                    'result': [{'metric': {'job': 'api'}, 'value': [1710000000, '1']}],
                },
            }),
        ]

        response = self.client.post(
            '/api/observability/grafana/promql/query/',
            {'query': 'up{job="api"}', 'datasource_uid': 'prometheus-infra', 'grafana_url': 'http://grafana.internal.local'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['source'], 'grafana')
        self.assertEqual(payload['series_count'], 1)
        self.assertIn('/api/datasources/uid/prometheus-infra', mock_get.call_args_list[0].args[0])
        self.assertIn('/api/datasources/proxy/12/api/v1/query', mock_get.call_args_list[1].args[0])

    @patch('ops.observability_views.http_requests.get')
    def test_metrics_query_uses_metric_datasource(self, mock_get):
        datasource = MetricDataSource.objects.create(
            name='Retail Test Prometheus',
            environment='test',
            is_default=True,
            config={
                'query_url': 'http://prometheus.test.local:9090',
                'auth_type': 'bearer',
                'bearer_token': 'secret-token',
                'headers': {'X-Scope-OrgID': 'retail'},
            },
        )
        mock_get.return_value = MockHttpResponse({
            'status': 'success',
            'data': {
                'resultType': 'vector',
                'result': [{'metric': {'job': 'api'}, 'value': [1710000000, '1']}],
            },
        })

        response = self.client.post(
            '/api/observability/metrics/query/',
            {'query': 'up', 'metric_datasource_id': datasource.id},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['source'], 'metric_datasource')
        self.assertEqual(payload['metric_datasource']['id'], datasource.id)
        self.assertIn('/api/v1/query', mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs['headers']['Authorization'], 'Bearer secret-token')

    @patch('ops.observability_views.http_requests.get')
    def test_metrics_series_names_uses_prometheus_label_values(self, mock_get):
        datasource = MetricDataSource.objects.create(
            name='Retail Metrics',
            environment='test',
            is_default=True,
            config={
                'query_url': 'http://prometheus.test.local:9090',
                'headers': {'X-Scope-OrgID': 'retail'},
            },
        )
        mock_get.return_value = MockHttpResponse({
            'status': 'success',
            'data': [
                'http_requests_total',
                'node_cpu_seconds_total',
                'node_memory_MemAvailable_bytes',
                'process_cpu_seconds_total',
            ],
        })

        response = self.client.get(
            '/api/observability/metrics/series-names/',
            {'metric_datasource_id': datasource.id, 'q': 'node_', 'limit': 5},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['metrics'], ['node_cpu_seconds_total', 'node_memory_MemAvailable_bytes'])
        self.assertEqual(payload['metric_datasource']['id'], datasource.id)
        self.assertIn('/api/v1/label/__name__/values', mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs['headers']['X-Scope-OrgID'], 'retail')
        self.assertEqual(mock_get.call_args.kwargs['params']['match[]'], '{__name__=~".*node_.*"}')

    def test_metric_datasource_serializer_masks_secrets(self):
        datasource = MetricDataSource.objects.create(
            name='Secure Prometheus',
            config={
                'query_url': 'http://prometheus.local:9090',
                'password': 'secret',
                'bearer_token': 'token',
                'headers': {'Authorization': 'Bearer token', 'X-Team': 'ops'},
                'prometheus.basic': {'prometheus.user': 'admin', 'prometheus.password': 'secret'},
            },
        )

        response = self.client.get(f'/api/observability/metric/datasources/{datasource.id}/')

        self.assertEqual(response.status_code, 200)
        config = response.json()['config']
        self.assertEqual(config['password'], 'configured')
        self.assertEqual(config['bearer_token'], 'configured')
        self.assertEqual(config['headers']['Authorization'], 'configured')
        self.assertEqual(config['headers']['X-Team'], 'ops')
        self.assertEqual(config['prometheus.basic']['prometheus.password'], 'configured')

    @patch('ops.observability_views.http_requests.get')
    def test_grafana_panel_query_fetches_dashboard_targets_and_runs_range_query(self, mock_get):
        GrafanaSetting.objects.create(name='default', enabled=True, url='http://grafana.internal.local')
        mock_get.side_effect = [
            MockHttpResponse({
                'dashboard': {
                    'title': 'K8s Workload',
                    'panels': [{
                        'id': 7,
                        'title': 'CPU 使用率',
                        'targets': [{'expr': 'sum(rate(container_cpu_usage_seconds_total{namespace="$namespace"}[5m]))'}],
                    }],
                },
            }),
            MockHttpResponse({'id': 12, 'uid': 'prometheus-infra'}),
            MockHttpResponse({
                'status': 'success',
                'data': {
                    'resultType': 'matrix',
                    'result': [{'metric': {'namespace': 'prod'}, 'values': [[1710000000, '0.4'], [1710000060, '0.5']]}],
                },
            }),
        ]

        response = self.client.post(
            '/api/observability/grafana/panel/query/',
            {
                'dashboard_key': 'k8s-workload',
                'panel_title': 'CPU',
                'variables': {'namespace': 'prod'},
                'step': '60s',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['dashboard_uid'], 'k8s-workload')
        self.assertEqual(payload['panel_id'], 7)
        self.assertEqual(payload['queries'][0]['series_count'], 1)
        self.assertIn('/api/dashboards/uid/k8s-workload', mock_get.call_args_list[0].args[0])
        self.assertIn('query_range', mock_get.call_args_list[2].args[0])

    @patch('ops.tracing_providers.http_requests.post')
    def test_tracing_catalog_uses_skywalking_graphql_when_configured(self, mock_post):
        mock_post.side_effect = [
            MockHttpResponse({
                'data': {
                    'listServices': [
                        {'id': 'service-1', 'name': 'gateway-service', 'shortName': 'gateway', 'group': 'sxdevops', 'layers': ['GENERAL']},
                        {'id': 'service-2', 'name': 'payment-service', 'shortName': 'payment', 'group': 'sxdevops', 'layers': ['GENERAL']},
                    ]
                }
            }),
            MockHttpResponse({
                'data': {
                    'getGlobalTopology': {
                        'nodes': [{'id': 'service-1', 'name': 'gateway-service', 'type': 'SERVICE', 'layers': ['GENERAL']}],
                        'calls': [{'id': 'call-1', 'source': 'service-1', 'target': 'service-2'}],
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'queryBasicTraces': {
                        'traces': [
                            {
                                'segmentId': 'segment-1',
                                'endpointNames': ['GET /api/orders/{id}'],
                                'duration': 212,
                                'start': '2026-03-29 09:15',
                                'isError': False,
                                'traceIds': ['trace-1'],
                            }
                        ]
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'queryTrace': {
                        'spans': [
                            {
                                'traceId': 'trace-1',
                                'segmentId': 'segment-1',
                                'spanId': 0,
                                'parentSpanId': -1,
                                'serviceCode': 'gateway-service',
                                'serviceInstanceName': 'gateway-prod-01',
                                'startTime': 1711674900000,
                                'endTime': 1711674900212,
                                'endpointName': 'GET /api/orders/{id}',
                                'type': 'Entry',
                                'peer': '',
                                'component': 'SpringMVC',
                                'isError': False,
                                'layer': 'HTTP',
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'logs': [],
                            }
                        ]
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'getServiceInstances': [
                        {'id': 'gateway-prod-01', 'name': 'gateway-prod-01'},
                    ]
                }
            }),
        ]

        response = self.client.get('/api/observability/tracing/catalog/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['tracing']['source'], 'skywalking')
        self.assertEqual(payload['summary']['service_count'], 2)
        self.assertEqual(payload['summary']['topology_calls'], 1)
        self.assertEqual(payload['recent_traces'][0]['trace_id'], 'trace-1')
        self.assertEqual(payload['recent_traces'][0]['summary'], '')
        self.assertTrue(any(item['provider'] == 'demo' for item in payload['providers']))
        self.assertEqual(mock_post.call_count, 5)

    def test_tracing_catalog_can_force_demo_provider(self):
        response = self.client.get('/api/observability/tracing/catalog/?provider=demo')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['tracing']['provider'], 'demo')
        self.assertEqual(payload['tracing']['source'], 'demo')
        self.assertGreaterEqual(len(payload['recent_traces']), 1)
        self.assertGreaterEqual(len(payload['instances']), 1)

    def test_tracing_search_can_filter_demo_instance(self):
        response = self.client.post(
            '/api/observability/tracing/search/',
            {
                'provider': 'demo',
                'service_id': 'svc-order',
                'instance_name': 'order-prod-02',
                'limit': 20,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['query']['instance_name'], 'order-prod-02')
        self.assertEqual(len(payload['traces']), 1)
        self.assertEqual(payload['traces'][0]['instance_name'], 'order-prod-02')
        self.assertTrue(any(item['name'] == 'order-prod-02' for item in payload['instances']))

    def test_can_create_tracing_datasource(self):
        response = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Production Tempo',
                'provider': 'tempo',
                'description': 'OTel Tempo 查询入口',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://tempo.example.com',
                    'ui_url': 'http://grafana.example.com/explore',
                    'authorization': 'Bearer secret-token',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['provider'], 'tempo')
        self.assertIs(payload['config']['demo_mode'], False)
        self.assertEqual(payload['config']['authorization'], 'configured')

        list_response = self.client.get('/api/observability/tracing/datasources/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()[0]['name'], 'Production Tempo')

    @patch('ops.observability_views.test_tracing_connection')
    def test_can_test_tracing_datasource_connection(self, mock_test_connection):
        create_response = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Production Jaeger',
                'provider': 'jaeger',
                'description': 'Jaeger 查询入口',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger.example.com',
                    'ui_url': 'http://jaeger-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        datasource_id = create_response.json()['id']
        mock_test_connection.return_value = {'kind': 'services', 'count': 3, 'items': [{'id': 'svc-a'}]}

        response = self.client.post(f'/api/observability/tracing/datasources/{datasource_id}/test_connection/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['preview_count'], 3)
        mock_test_connection.assert_called_once()

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_catalog_uses_jaeger_query_when_configured(self, mock_get):
        mock_get.side_effect = [
            MockHttpResponse({'data': ['gateway-service', 'order-service']}),
            MockHttpResponse({
                'data': [
                    {
                        'traceID': 'jaeger-trace-1',
                        'processes': {'p1': {'serviceName': 'gateway-service'}, 'p2': {'serviceName': 'order-service'}},
                        'spans': [
                            {
                                'spanID': 'span-root',
                                'processID': 'p1',
                                'operationName': 'GET /api/orders',
                                'startTime': 1711674900000000,
                                'duration': 250000,
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'references': [],
                            },
                            {
                                'spanID': 'span-child',
                                'processID': 'p2',
                                'operationName': 'queryOrder',
                                'startTime': 1711674900040000,
                                'duration': 120000,
                                'tags': [],
                                'references': [{'refType': 'CHILD_OF', 'spanID': 'span-root'}],
                            },
                        ],
                    }
                ]
            }),
            MockHttpResponse({
                'data': [
                    {
                        'traceID': 'jaeger-trace-1',
                        'processes': {'p1': {'serviceName': 'gateway-service'}, 'p2': {'serviceName': 'order-service'}},
                        'spans': [
                            {
                                'spanID': 'span-root',
                                'processID': 'p1',
                                'operationName': 'GET /api/orders',
                                'startTime': 1711674900000000,
                                'duration': 250000,
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'references': [],
                            },
                            {
                                'spanID': 'span-child',
                                'processID': 'p2',
                                'operationName': 'queryOrder',
                                'startTime': 1711674900040000,
                                'duration': 120000,
                                'tags': [],
                                'references': [{'refType': 'CHILD_OF', 'spanID': 'span-root'}],
                            },
                        ],
                    }
                ]
            }),
            MockHttpResponse({
                'data': [
                    {
                        'traceID': 'jaeger-trace-1',
                        'processes': {'p1': {'serviceName': 'gateway-service'}, 'p2': {'serviceName': 'order-service'}},
                        'spans': [
                            {
                                'spanID': 'span-root',
                                'processID': 'p1',
                                'operationName': 'GET /api/orders',
                                'startTime': 1711674900000000,
                                'duration': 250000,
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'references': [],
                            },
                            {
                                'spanID': 'span-child',
                                'processID': 'p2',
                                'operationName': 'queryOrder',
                                'startTime': 1711674900040000,
                                'duration': 120000,
                                'tags': [],
                                'references': [{'refType': 'CHILD_OF', 'spanID': 'span-root'}],
                            },
                        ],
                    }
                ]
            }),
        ]

        with override_settings(
            OBSERVABILITY_CONFIG={
                **TEST_OBSERVABILITY_CONFIG,
                'tracing': {'default_provider': 'jaeger'},
                'skywalking': {**TEST_OBSERVABILITY_CONFIG['skywalking'], 'enabled': False},
                'jaeger': {
                    'provider': 'jaeger',
                    'enabled': True,
                    'query_url': 'http://jaeger.example.com',
                    'ui_url': 'http://jaeger-ui.example.com',
                    'demo_mode': False,
                },
            }
        ):
            response = self.client.get('/api/observability/tracing/catalog/?provider=jaeger')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['tracing']['source'], 'jaeger')
        self.assertEqual(payload['providers'][0]['provider'], 'jaeger')
        self.assertEqual(payload['summary']['service_count'], 2)
        self.assertEqual(payload['recent_traces'][0]['trace_id'], 'jaeger-trace-1')
        self.assertEqual(payload['topology']['call_count'], 1)

    def _jaeger_trace_payload(self, trace_id, service_name='gateway-service'):
        return {
            'traceID': trace_id,
            'processes': {'p1': {'serviceName': service_name}},
            'spans': [
                {
                    'spanID': 'span-root',
                    'processID': 'p1',
                    'operationName': 'GET /api/orders',
                    'startTime': 1711674900000000,
                    'duration': 250000,
                    'tags': [{'key': 'http.status_code', 'value': '200'}],
                    'references': [],
                }
            ],
        }

    def _jaeger_catalog_side_effects(self, trace_id='jaeger-cache-1'):
        payload = self._jaeger_trace_payload(trace_id)
        return [
            MockHttpResponse({'data': ['gateway-service']}),
            MockHttpResponse({'data': [payload]}),
            MockHttpResponse({'data': [payload]}),
            MockHttpResponse({'data': [payload]}),
        ]

    def _jaeger_cache_config(self):
        return {
            **TEST_OBSERVABILITY_CONFIG,
            'tracing': {'default_provider': 'jaeger'},
            'skywalking': {**TEST_OBSERVABILITY_CONFIG['skywalking'], 'enabled': False},
            'jaeger': {
                'provider': 'jaeger',
                'enabled': True,
                'query_url': 'http://jaeger-cache.example.com',
                'ui_url': 'http://jaeger-cache-ui.example.com',
                'demo_mode': False,
            },
        }

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_catalog_cache_serves_second_request_without_external_calls(self, mock_get):
        mock_get.side_effect = self._jaeger_catalog_side_effects()
        with override_settings(OBSERVABILITY_CONFIG=self._jaeger_cache_config()):
            first = self.client.get('/api/observability/tracing/catalog/?provider=jaeger')
            second = self.client.get('/api/observability/tracing/catalog/?provider=jaeger')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['summary'], second.json()['summary'])
        self.assertEqual(mock_get.call_count, 4, '第二次请求应命中缓存，不再打外部系统')

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_search_reuses_cached_catalog(self, mock_get):
        # search 内部携带 service_id 加载 catalog：预热需带相同参数使缓存键一致
        mock_get.side_effect = self._jaeger_catalog_side_effects() + [MockHttpResponse({'data': []})]
        with override_settings(OBSERVABILITY_CONFIG=self._jaeger_cache_config()):
            warm = self.client.get('/api/observability/tracing/catalog/?provider=jaeger&service_id=gateway-service')
            self.assertEqual(warm.status_code, 200)
            response = self.client.post(
                '/api/observability/tracing/search/',
                {'provider': 'jaeger', 'service_id': 'gateway-service', 'limit': 10},
                format='json',
            )
        self.assertEqual(response.status_code, 200)
        services_calls = [call for call in mock_get.call_args_list if '/api/services' in str(call.args)]
        self.assertEqual(len(services_calls), 1, 'search 应复用 catalog 缓存，不重复拉取 services')
        self.assertEqual(mock_get.call_count, 5, '仅预热 4 次 + 搜索 1 次')

    @patch('ops.tracing_providers.http_requests.get')
    def test_trace_detail_reuses_cached_catalog(self, mock_get):
        trace_id = 'jaeger-cache-1'
        mock_get.side_effect = self._jaeger_catalog_side_effects(trace_id=trace_id) + [
            MockHttpResponse({'data': [self._jaeger_trace_payload(trace_id)]}),
        ]
        with override_settings(OBSERVABILITY_CONFIG=self._jaeger_cache_config()):
            self.client.get('/api/observability/tracing/catalog/?provider=jaeger')
            response = self.client.get(f'/api/observability/tracing/traces/{trace_id}/?provider=jaeger')
        self.assertEqual(response.status_code, 200)
        services_calls = [call for call in mock_get.call_args_list if '/api/services' in str(call.args)]
        self.assertEqual(len(services_calls), 1, 'trace 详情应复用 catalog 缓存')

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_datasource_update_invalidates_catalog_cache(self, mock_get):
        create_response = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Cache Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger-cache.example.com',
                    'ui_url': 'http://jaeger-cache-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, 201)
        ds_id = create_response.json()['id']
        mock_get.side_effect = (
            self._jaeger_catalog_side_effects()
            + self._jaeger_catalog_side_effects(trace_id='jaeger-cache-2')
        )
        warm = self.client.get(f'/api/observability/tracing/catalog/?provider=jaeger&datasource_id={ds_id}')
        self.assertEqual(warm.status_code, 200)
        update = self.client.patch(
            f'/api/observability/tracing/datasources/{ds_id}/', {'description': 'changed'}, format='json')
        self.assertEqual(update.status_code, 200)
        again = self.client.get(f'/api/observability/tracing/catalog/?provider=jaeger&datasource_id={ds_id}')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(mock_get.call_count, 8, '数据源更新后应重新实时拉取 catalog')

    def test_resolve_provider_caches_datasource_lookup(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from ops.tracing_providers import _resolve_provider

        ds = TracingDataSource.objects.create(
            name='Resolve Cache', provider='jaeger', is_enabled=True,
            config={'query_url': 'http://jaeger-resolve.example.com', 'demo_mode': False},
        )
        with CaptureQueriesContext(connection) as warm_queries:
            _resolve_provider('', datasource_id=str(ds.id))
        with CaptureQueriesContext(connection) as cached_queries:
            provider_id, config = _resolve_provider('', datasource_id=str(ds.id))
        self.assertEqual(provider_id, 'jaeger')
        self.assertEqual(config['datasource_name'], 'Resolve Cache')
        # 预热含 provider 配置读取 + 数据源查询；命中缓存后仅剩配置读取（少 1 次）
        self.assertEqual(len(cached_queries.captured_queries), len(warm_queries.captured_queries) - 1,
                         '命中缓存后不再查数据源')

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_http_get_retries_once_on_connection_error(self, mock_get):
        mock_get.side_effect = [
            requests.ConnectionError('connection refused'),
            MockHttpResponse({'data': ['ok']}),
        ]
        result = _http_get('http://jaeger-retry.example.com/api/services')
        self.assertEqual(result, {'data': ['ok']})
        self.assertEqual(mock_get.call_count, 2, '瞬时连接失败应重试一次后成功')

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_http_get_raises_502_after_connection_error_retries(self, mock_get):
        mock_get.side_effect = [
            requests.ConnectionError('connection refused'),
            requests.ConnectionError('still refused'),
        ]
        with self.assertRaises(ObservabilityError) as ctx:
            _http_get('http://jaeger-retry.example.com/api/services')
        self.assertEqual(ctx.exception.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(mock_get.call_count, 2, '重试一次后仍失败才报 502')

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_http_get_timeout_stays_504_without_retry(self, mock_get):
        mock_get.side_effect = requests.Timeout('read timed out')
        with self.assertRaises(ObservabilityError) as ctx:
            _http_get('http://jaeger-retry.example.com/api/services')
        self.assertEqual(ctx.exception.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertEqual(mock_get.call_count, 1, '超时不应重试')

    def test_collect_instance_options_loads_details_for_traces_without_instance(self):
        from ops.tracing_providers import _collect_instance_options
        traces = [
            {'trace_id': f't{i}', 'service_id': 'svc', 'service_name': 'svc'}
            for i in range(5)
        ]
        loaded = []

        def fake_loader(trace):
            loaded.append(trace['trace_id'])
            return {'spans': [{'service_instance_name': f'inst-{trace["trace_id"]}', 'service_code': 'svc'}]}

        options = _collect_instance_options(traces, detail_loader=fake_loader)
        self.assertEqual(len(loaded), 5, '缺失实例名的 trace 应逐个补拉详情')
        self.assertEqual({item['name'] for item in options}, {f'inst-t{i}' for i in range(5)})
        self.assertEqual({item['service_name'] for item in options}, {'svc'})

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_search_uses_requested_datasource_config(self, mock_get):
        create_default = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Default Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger-default.example.com',
                    'ui_url': 'http://jaeger-default-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        create_alternate = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Alternate Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': False,
                'config': {
                    'query_url': 'http://jaeger-alt.example.com',
                    'ui_url': 'http://jaeger-alt-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        datasource_id = create_alternate.json()['id']
        trace_payload = {
            'traceID': 'jaeger-trace-alt',
            'processes': {'p1': {'serviceName': 'gateway-service'}},
            'spans': [
                {
                    'spanID': 'span-root',
                    'processID': 'p1',
                    'operationName': 'GET /api/orders',
                    'startTime': 1711674900000000,
                    'duration': 250000,
                    'tags': [{'key': 'http.status_code', 'value': '200'}],
                    'references': [],
                }
            ],
        }
        mock_get.side_effect = [
            MockHttpResponse({'data': ['gateway-service']}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
        ]

        response = self.client.post(
            '/api/observability/tracing/search/',
            {
                'provider': 'jaeger',
                'datasource_id': datasource_id,
                'service_id': 'gateway-service',
                'limit': 10,
            },
            format='json',
        )

        self.assertEqual(create_default.status_code, 201)
        self.assertEqual(create_alternate.status_code, 201)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload['tracing']['datasource_id']), str(datasource_id))
        self.assertEqual(payload['traces'][0]['trace_id'], 'jaeger-trace-alt')
        self.assertIn(
            'http://jaeger-alt.example.com/api/traces',
            [call.args[0] for call in mock_get.call_args_list],
        )
        self.assertEqual(
            mock_get.call_args_list[-1].args[0],
            'http://jaeger-alt.example.com/api/traces/jaeger-trace-alt',
        )

    @patch('ops.tracing_providers.http_requests.get')
    def test_tracing_search_supports_absolute_time_range(self, mock_get):
        self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Absolute Range Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger-absolute.example.com',
                    'ui_url': 'http://jaeger-absolute-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        trace_payload = {
            'traceID': 'jaeger-trace-range',
            'processes': {'p1': {'serviceName': 'gateway-service'}},
            'spans': [
                {
                    'spanID': 'span-root',
                    'processID': 'p1',
                    'operationName': 'GET /api/orders',
                    'startTime': 1711674900000000,
                    'duration': 250000,
                    'tags': [{'key': 'http.status_code', 'value': '200'}],
                    'references': [],
                }
            ],
        }
        mock_get.side_effect = [
            MockHttpResponse({'data': ['gateway-service']}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
        ]

        start_time = '2026-04-10T11:00:00+08:00'
        end_time = '2026-04-10T11:45:00+08:00'
        response = self.client.post(
            '/api/observability/tracing/search/',
            {
                'provider': 'jaeger',
                'service_id': 'gateway-service',
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': 5,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['query']['start_time'], start_time)
        self.assertEqual(payload['query']['end_time'], end_time)
        trace_calls = [
            call
            for call in mock_get.call_args_list
            if call.args[0] == 'http://jaeger-absolute.example.com/api/traces'
        ]
        params = trace_calls[-1].kwargs['params']
        self.assertEqual(params['start'], int(datetime.fromisoformat(start_time).timestamp() * 1000000))
        self.assertEqual(params['end'], int(datetime.fromisoformat(end_time).timestamp() * 1000000))

    @patch('ops.tracing_providers.http_requests.get')
    def test_trace_detail_uses_requested_datasource_config(self, mock_get):
        self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Primary Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger-primary.example.com',
                    'ui_url': 'http://jaeger-primary-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        create_alternate = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Focused Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': False,
                'config': {
                    'query_url': 'http://jaeger-focused.example.com',
                    'ui_url': 'http://jaeger-focused-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        datasource_id = create_alternate.json()['id']
        trace_payload = {
            'traceID': 'jaeger-trace-detail',
            'processes': {'p1': {'serviceName': 'gateway-service'}},
            'spans': [
                {
                    'spanID': 'span-root',
                    'processID': 'p1',
                    'operationName': 'GET /api/orders',
                    'startTime': 1711674900000000,
                    'duration': 250000,
                    'tags': [{'key': 'http.status_code', 'value': '200'}],
                    'references': [],
                }
            ],
        }
        mock_get.side_effect = [
            MockHttpResponse({'data': ['gateway-service']}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
            MockHttpResponse({'data': [trace_payload]}),
        ]

        response = self.client.get(
            f'/api/observability/tracing/traces/jaeger-trace-detail/?provider=jaeger&datasource_id={datasource_id}'
        )

        self.assertEqual(create_alternate.status_code, 201)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['trace']['trace_id'], 'jaeger-trace-detail')
        self.assertEqual(payload['trace']['summary'], '')
        self.assertEqual(str(payload['tracing']['datasource_id']), str(datasource_id))
        self.assertEqual(
            mock_get.call_args_list[-1].args[0],
            'http://jaeger-focused.example.com/api/traces/jaeger-trace-detail',
        )

    def test_tracing_catalog_rejects_provider_datasource_mismatch(self):
        create_response = self.client.post(
            '/api/observability/tracing/datasources/',
            {
                'name': 'Mismatch Jaeger',
                'provider': 'jaeger',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'query_url': 'http://jaeger-mismatch.example.com',
                    'ui_url': 'http://jaeger-mismatch-ui.example.com',
                    'demo_mode': False,
                },
            },
            format='json',
        )
        datasource_id = create_response.json()['id']

        catalog_response = self.client.get(
            f'/api/observability/tracing/catalog/?provider=tempo&datasource_id={datasource_id}'
        )
        search_response = self.client.post(
            '/api/observability/tracing/search/',
            {'provider': 'tempo', 'datasource_id': datasource_id},
            format='json',
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(catalog_response.status_code, 400)
        self.assertEqual(search_response.status_code, 400)
        self.assertIn('provider 与链路数据源类型不一致', catalog_response.json()['detail'])
        self.assertIn('provider 与链路数据源类型不一致', search_response.json()['detail'])

    def test_trace_detail_preserves_tempo_resource_and_scope_attributes(self):
        detail = _trace_detail_from_spans('tempo-trace-1', [
            {
                'span_id': 'span-root',
                'parent_span_id': '',
                'service_code': 'api-gateway',
                'endpoint_name': 'GET /api/products',
                'start_time': '2026-05-03T12:00:00+00:00',
                'end_time': '2026-05-03T12:00:01+00:00',
                'duration_ms': 1000,
                'tags': [{'key': 'http.method', 'value': 'GET'}],
                'resource_tags': [
                    {'key': 'service.name', 'value': 'api-gateway'},
                    {'key': 'k8s.pod.name', 'value': 'api-gateway-123'},
                ],
                'scope_tags': [{'key': 'telemetry.scope.name', 'value': 'opentelemetry.instrumentation.django'}],
            }
        ])

        span = detail['spans'][0]
        self.assertEqual(span['resource_tags'][1]['key'], 'k8s.pod.name')
        self.assertEqual(span['scope_tags'][0]['value'], 'opentelemetry.instrumentation.django')

    def test_trace_topology_includes_runtime_component_dependencies(self):
        detail = _trace_detail_from_spans('tempo-runtime-trace', [
            {
                'span_id': 'root',
                'parent_span_id': '',
                'service_code': 'checkout',
                'endpoint_name': 'GET /checkout',
                'start_time': '2026-05-03T12:00:00+00:00',
                'end_time': '2026-05-03T12:00:01+00:00',
            },
            {
                'span_id': 'redis',
                'parent_span_id': 'root',
                'service_code': 'checkout',
                'endpoint_name': 'Redis GET cart',
                'start_time': '2026-05-03T12:00:00.100+00:00',
                'end_time': '2026-05-03T12:00:00.140+00:00',
                'component': 'Jedis',
                'peer': 'redis:6379',
                'layer': 'CACHE',
            },
            {
                'span_id': 'postgres',
                'parent_span_id': 'root',
                'service_code': 'checkout',
                'endpoint_name': 'SELECT products',
                'start_time': '2026-05-03T12:00:00.200+00:00',
                'end_time': '2026-05-03T12:00:00.320+00:00',
                'tags': [{'key': 'db.system', 'value': 'postgresql'}],
                'layer': 'DATABASE',
            },
        ])

        topology = _build_topology_from_trace_details([detail])

        node_ids = {node['id'] for node in topology['nodes']}
        self.assertIn('checkout', node_ids)
        self.assertIn('runtime:redis', node_ids)
        self.assertIn('runtime:postgresql', node_ids)
        self.assertTrue(any(call['source'] == 'checkout' and call['target'] == 'runtime:redis' for call in topology['calls']))
        self.assertTrue(any(call['source'] == 'checkout' and call['target'] == 'runtime:postgresql' for call in topology['calls']))

    def test_trace_topology_keeps_multi_hop_service_dependencies(self):
        detail = _trace_detail_from_spans('tempo-layered-trace', [
            {
                'span_id': 'root',
                'parent_span_id': '',
                'service_code': 'api-gateway',
                'endpoint_name': 'POST /checkout',
                'start_time': '2026-05-03T12:00:00+00:00',
                'end_time': '2026-05-03T12:00:01+00:00',
                'layer': 'HTTP',
            },
            {
                'span_id': 'order',
                'parent_span_id': 'root',
                'service_code': 'order-service',
                'endpoint_name': 'POST /orders',
                'start_time': '2026-05-03T12:00:00.100+00:00',
                'end_time': '2026-05-03T12:00:00.600+00:00',
                'layer': 'RPC_FRAMEWORK',
            },
            {
                'span_id': 'inventory',
                'parent_span_id': 'order',
                'service_code': 'inventory-service',
                'endpoint_name': 'GET /availability',
                'start_time': '2026-05-03T12:00:00.200+00:00',
                'end_time': '2026-05-03T12:00:00.500+00:00',
                'layer': 'RPC_FRAMEWORK',
            },
            {
                'span_id': 'redis',
                'parent_span_id': 'inventory',
                'service_code': 'inventory-service',
                'endpoint_name': 'Redis GET stock',
                'start_time': '2026-05-03T12:00:00.250+00:00',
                'end_time': '2026-05-03T12:00:00.300+00:00',
                'component': 'Jedis',
                'peer': 'redis-inventory:6379',
                'layer': 'CACHE',
            },
        ])

        topology = _build_topology_from_trace_details([detail])
        call_pairs = {(call['source'], call['target']) for call in topology['calls']}

        self.assertIn(('api-gateway', 'order-service'), call_pairs)
        self.assertIn(('order-service', 'inventory-service'), call_pairs)
        self.assertIn(('inventory-service', 'runtime:redis-inventory'), call_pairs)

    def test_tempo_flatten_trace_keeps_full_resource_attributes(self):
        spans = _tempo_flatten_trace({
            'batches': [
                {
                    'resource': {
                        'attributes': {
                            'service.name': {'stringValue': 'api-gateway'},
                            'k8s.namespace.name': {'stringValue': 'default'},
                            'k8s.pod.name': {'stringValue': 'api-gateway-123'},
                            'telemetry.sdk.language': {'stringValue': 'python'},
                        }
                    },
                    'scopeSpans': [
                        {
                            'scope': {'name': 'opentelemetry.instrumentation.django', 'version': '0.45b0'},
                            'spans': [
                                {
                                    'spanId': 'span-root',
                                    'name': 'GET /api/products',
                                    'startTimeUnixNano': '1770000000000000000',
                                    'endTimeUnixNano': '1770000001000000000',
                                    'attributes': [{'key': 'http.method', 'value': {'stringValue': 'GET'}}],
                                }
                            ],
                        }
                    ],
                }
            ]
        })

        self.assertEqual(len(spans), 1)
        resource_keys = {item['key'] for item in spans[0]['resource_tags']}
        scope_keys = {item['key'] for item in spans[0]['scope_tags']}
        self.assertIn('k8s.namespace.name', resource_keys)
        self.assertIn('k8s.pod.name', resource_keys)
        self.assertIn('telemetry.sdk.language', resource_keys)
        self.assertIn('telemetry.scope.name', scope_keys)

    @patch('ops.tracing_providers.http_requests.post')
    def test_trace_detail_returns_span_summary_from_skywalking(self, mock_post):
        mock_post.side_effect = [
            MockHttpResponse({
                'data': {
                    'listServices': [
                        {'id': 'service-1', 'name': 'gateway-service', 'shortName': 'gateway', 'group': 'sxdevops', 'layers': ['GENERAL']},
                    ]
                }
            }),
            MockHttpResponse({
                'data': {
                    'getGlobalTopology': {
                        'nodes': [{'id': 'service-1', 'name': 'gateway-service', 'type': 'SERVICE', 'layers': ['GENERAL']}],
                        'calls': [],
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'queryBasicTraces': {
                        'traces': [
                            {
                                'segmentId': 'segment-1',
                                'endpointNames': ['GET /api/orders/{id}'],
                                'duration': 212,
                                'start': '2026-03-29 09:15',
                                'isError': False,
                                'traceIds': ['trace-1'],
                            }
                        ]
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'queryTrace': {
                        'spans': [
                            {
                                'traceId': 'trace-1',
                                'segmentId': 'segment-1',
                                'spanId': 0,
                                'parentSpanId': -1,
                                'serviceCode': 'gateway-service',
                                'serviceInstanceName': 'gateway-prod-01',
                                'startTime': 1711674900000,
                                'endTime': 1711674900212,
                                'endpointName': 'GET /api/orders/{id}',
                                'type': 'Entry',
                                'peer': '',
                                'component': 'SpringMVC',
                                'isError': False,
                                'layer': 'HTTP',
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'logs': [],
                            }
                        ]
                    }
                }
            }),
            MockHttpResponse({
                'data': {
                    'getServiceInstances': [
                        {'id': 'gateway-prod-01', 'name': 'gateway-prod-01'},
                    ]
                }
            }),
            MockHttpResponse({
                'data': {
                    'queryTrace': {
                        'spans': [
                            {
                                'traceId': 'trace-1',
                                'segmentId': 'segment-1',
                                'spanId': 0,
                                'parentSpanId': -1,
                                'serviceCode': 'gateway-service',
                                'serviceInstanceName': 'gateway-prod-01',
                                'startTime': 1711674900000,
                                'endTime': 1711674900212,
                                'endpointName': 'GET /api/orders/{id}',
                                'type': 'Entry',
                                'peer': '',
                                'component': 'SpringMVC',
                                'isError': False,
                                'layer': 'HTTP',
                                'tags': [{'key': 'http.status_code', 'value': '200'}],
                                'logs': [],
                            }
                        ]
                    }
                }
            }),
        ]

        response = self.client.get('/api/observability/tracing/traces/trace-1/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['trace']['trace_id'], 'trace-1')
        self.assertEqual(payload['trace']['span_count'], 1)
        self.assertEqual(payload['trace']['duration_ms'], 212)
        self.assertEqual(payload['trace'].get('summary', ''), '')
        self.assertIn('gateway-service', payload['trace']['services'])

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

    def test_k8s_api_proxy_preserves_bound_method_owner_for_stream(self):
        class FakeApi:
            def __init__(self):
                self.api_client = object()
                self.kwargs = None

            def connect_get_namespaced_pod_exec(self, **kwargs):
                self.kwargs = kwargs
                return 'connected'

        fake_api = FakeApi()
        proxy = _K8sApiProxy(fake_api)
        wrapped = proxy.connect_get_namespaced_pod_exec

        self.assertIs(wrapped.__self__, fake_api)
        self.assertIs(wrapped.__self__.api_client, fake_api.api_client)
        self.assertEqual(wrapped(name='pod-a'), 'connected')
        self.assertEqual(fake_api.kwargs['_request_timeout'], (1.5, 3))

    def test_prepare_kubeconfig_overrides_active_cluster_server(self):
        cluster = K8sCluster.objects.create(
            name='prod-k8s',
            api_server='https://k8s.example.com:6443',
            kubeconfig=(
                'apiVersion: v1\n'
                'kind: Config\n'
                'current-context: prod\n'
                'contexts:\n'
                '  - name: prod\n'
                '    context:\n'
                '      cluster: prod-cluster\n'
                '      user: prod-user\n'
                'clusters:\n'
                '  - name: prod-cluster\n'
                '    cluster:\n'
                '      server: https://203.0.113.176:6443\n'
            ),
        )

        rendered = _prepare_kubeconfig(cluster)

        self.assertIn('server: https://k8s.example.com:6443', rendered)
        self.assertNotIn('server: https://203.0.113.176:6443', rendered)

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_connection_reports_certificate_hint_on_ssl_error(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='broken-k8s',
            api_server='https://203.0.113.176:6443',
            kubeconfig='apiVersion: v1\nkind: Config\ncurrent-context: broken\nclusters: []\ncontexts: []\n',
        )
        mock_get_client.side_effect = ssl.SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')

        response = self.client.post(f'/api/k8s/clusters/{cluster.id}/test_connection/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('证书校验失败', payload['message'])
        self.assertEqual(K8sCluster.objects.get(id=cluster.id).status, 'error')

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

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_summary_marks_payload_degraded_when_live_queries_timeout(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='timeout-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )

        class FailingCoreV1Api:
            def list_namespace(self):
                raise TimeoutError('connect timed out')

            def list_node(self):
                raise TimeoutError('connect timed out')

            def list_pod_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_service_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_persistent_volume_claim_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_config_map_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_secret_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingAppsV1Api:
            def list_deployment_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_stateful_set_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_daemon_set_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingBatchV1Api:
            def list_job_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_cron_job_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingNetworkingV1Api:
            def list_ingress_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        mock_get_client.return_value = MagicMock(
            CoreV1Api=MagicMock(return_value=FailingCoreV1Api()),
            AppsV1Api=MagicMock(return_value=FailingAppsV1Api()),
            BatchV1Api=MagicMock(return_value=FailingBatchV1Api()),
            NetworkingV1Api=MagicMock(return_value=FailingNetworkingV1Api()),
        )

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertIn('pods', payload['unavailable_resources'])
        self.assertTrue(any(item['level'] == 'warning' for item in payload['alerts']))
        self.assertFalse(any(item['level'] == 'success' for item in payload['alerts']))

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_pods_returns_stale_cache_when_cluster_times_out(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='stale-cache-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        stale_items = [{'name': 'cached-pod', 'namespace': 'default', 'status': 'Running', 'node': 'node-01', 'ip': '10.0.0.5', 'containers': [], 'restarts': 0, 'created': ''}]
        cache.set(_resource_stale_cache_key(cluster.id, 'pods', 'default'), stale_items, 300)
        mock_get_client.side_effect = TimeoutError('connect timed out')

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/pods/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stale_items)

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_summary_returns_stale_snapshot_when_build_fails(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='summary-stale-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        cached_summary = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 3,
            'nodes_ready': 3,
            'pods_total': 10,
            'pods_abnormal': 0,
            'pods_restarting': 0,
            'total_restarts': 0,
            'services_total': 4,
            'ingresses_total': 1,
            'workloads_total': 6,
            'workloads_degraded': 0,
            'pvcs_total': 2,
            'pvcs_pending': 0,
            'configmaps_total': 5,
            'secrets_total': 4,
            'alerts': [{'level': 'success', 'message': 'cached'}],
        }
        cache.set(_summary_stale_cache_key(cluster.id), cached_summary, 300)
        mock_get_client.side_effect = RuntimeError('cluster unavailable')

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['pods_total'], 10)
        self.assertIn('cached snapshot', payload['alerts'][0]['message'])

    @patch('ops.k8s_views._build_live_summary')
    def test_k8s_summary_does_not_cache_unreliable_zero_snapshot(self, mock_build_live_summary):
        cluster = K8sCluster.objects.create(
            name='summary-zero-degraded-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        cached_summary = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 2,
            'nodes_ready': 2,
            'pods_total': 8,
            'pods_abnormal': 1,
            'pods_restarting': 1,
            'total_restarts': 3,
            'services_total': 4,
            'ingresses_total': 1,
            'workloads_total': 5,
            'workloads_degraded': 0,
            'pvcs_total': 2,
            'pvcs_pending': 0,
            'configmaps_total': 5,
            'secrets_total': 4,
            'alerts': [{'level': 'success', 'message': 'cached'}],
        }
        mock_build_live_summary.return_value = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'namespaces_total': 0,
            'nodes_total': 0,
            'nodes_ready': 0,
            'pods_total': 0,
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
            'degraded': True,
            'unavailable_resources': ['pods', 'deployments'],
            'alerts': [{'level': 'warning', 'message': 'partial collection failed'}],
        }
        cache.set(_summary_stale_cache_key(cluster.id), cached_summary, 300)

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['pods_total'], 8)
        self.assertEqual(payload['workloads_total'], 5)
        self.assertIn('cached snapshot', payload['alerts'][0]['message'])

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_pod_logs_degrade_to_empty_payload_on_timeout(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='pod-logs-timeout-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        mock_get_client.side_effect = TimeoutError('connect timed out')

        response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/pod_logs/',
            {'pod_name': 'api-server-1', 'namespace': 'default'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['logs'], '')

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

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    def test_demo_docker_host_returns_cached_container_and_image_inventory(self, mock_get_client):
        host = DockerHost.objects.create(name='app-release-test', ip_address='192.168.1.120', docker_api_version='24.0')

        container_response = self.client.get('/api/docker/containers/', {'host_id': host.id})
        image_response = self.client.get('/api/docker/images/', {'host_id': host.id})

        self.assertEqual(container_response.status_code, 200)
        self.assertEqual(image_response.status_code, 200)
        self.assertTrue(any(item['name'] == 'order-center-batch-1' for item in container_response.json()))
        self.assertTrue(any(item['repository'] == 'registry.demo.local/order-center' for item in image_response.json()))
        mock_get_client.assert_not_called()

    def test_demo_docker_container_action_logs_and_inspect_update_cached_state(self):
        host = DockerHost.objects.create(name='gateway-prod', ip_address='192.168.1.121', docker_api_version='24.0')

        container_response = self.client.get('/api/docker/containers/', {'host_id': host.id})
        self.assertEqual(container_response.status_code, 200)
        target = next(item for item in container_response.json() if item['name'] == 'member-center-failed')

        stop_response = self.client.post(
            f"/api/docker/containers/{quote(target['id'], safe='')}/action/",
            {'host_id': host.id, 'action': 'start'},
            format='json',
        )
        self.assertEqual(stop_response.status_code, 200)

        updated_list = self.client.get('/api/docker/containers/', {'host_id': host.id}).json()
        updated = next(item for item in updated_list if item['id'] == target['id'])
        self.assertEqual(updated['state'], 'running')

        logs_response = self.client.get(
            f"/api/docker/containers/{quote(target['id'], safe='')}/logs/",
            {'host_id': host.id, 'tail': 50},
        )
        inspect_response = self.client.get(
            f"/api/docker/containers/{quote(target['id'], safe='')}/inspect/",
            {'host_id': host.id},
        )

        self.assertEqual(logs_response.status_code, 200)
        self.assertEqual(inspect_response.status_code, 200)
        self.assertIn('member-center-failed', logs_response.json()['logs'])
        self.assertEqual(inspect_response.json()['State']['Status'], 'running')

    def test_demo_docker_image_remove_and_prune_update_cached_state(self):
        host = DockerHost.objects.create(name='member-prod', ip_address='192.168.1.122', docker_api_version='24.0')

        initial_images = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        dangling = next(item for item in initial_images if item['repository'] == '<none>')
        in_use = next(item for item in initial_images if item['repository'] == 'redis')

        remove_response = self.client.delete(
            '/api/docker/images/remove/',
            {'host_id': host.id, 'image_ids': [dangling['id'], in_use['id']]},
            format='json',
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertIn('跳过 1', remove_response.json()['message'])

        after_remove = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        self.assertFalse(any(item['id'] == dangling['id'] for item in after_remove))
        self.assertTrue(any(item['id'] == in_use['id'] for item in after_remove))

        prune_response = self.client.post('/api/docker/images/prune/', {'host_id': host.id}, format='json')
        self.assertEqual(prune_response.status_code, 200)
        after_prune = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        self.assertFalse(any(item['repository'] == '<none>' or item['tag'] == '<none>' for item in after_prune))


class MiddlewareViewsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('middleware-admin', 'middleware@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_middleware_overview_returns_all_sections(self):
        response = self.client.get('/api/middleware/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('overview', payload)
        self.assertIn('redis', payload)
        self.assertIn('rocketmq', payload)
        self.assertIn('elasticsearch', payload)
        self.assertTrue(any(item['cluster'] == 'order-cache' for item in payload['redis']['instances']))
        self.assertTrue(any(item['group'] == 'GID_AUDIT_ETL' for item in payload['rocketmq']['consumer_groups']))
        self.assertTrue(any(item['health'] == 'yellow' for item in payload['elasticsearch']['clusters']))

    def test_redis_promote_action_swaps_master_role(self):
        initial = self.client.get('/api/middleware/overview/').json()
        replica = next(item for item in initial['redis']['instances'] if item['id'] == 'redis-order-replica-01')

        response = self.client.post(
            '/api/middleware/action/',
            {'module': 'redis', 'target_id': replica['id'], 'action': 'promote'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        updated_instances = response.json()['data']['redis']['instances']
        promoted = next(item for item in updated_instances if item['id'] == 'redis-order-replica-01')
        previous_master = next(item for item in updated_instances if item['id'] == 'redis-order-master')
        self.assertEqual(promoted['role'], 'master')
        self.assertEqual(promoted['replication_delay_ms'], 0)
        self.assertEqual(previous_master['role'], 'replica')
        self.assertEqual(previous_master['status'], 'warning')

    def test_elasticsearch_reroute_clears_yellow_cluster(self):
        response = self.client.post(
            '/api/middleware/action/',
            {'module': 'elasticsearch', 'target_id': 'es-observe-logs', 'action': 'reroute'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        updated_clusters = response.json()['data']['elasticsearch']['clusters']
        updated_cluster = next(item for item in updated_clusters if item['id'] == 'es-observe-logs')
        self.assertEqual(updated_cluster['health'], 'green')
        self.assertEqual(updated_cluster['unassigned_shards'], 0)

    def test_create_redis_cluster_and_instance_updates_demo_state(self):
        create_cluster = self.client.post(
            '/api/middleware/action/',
            {
                'module': 'redis',
                'action': 'create_cluster',
                'payload': {
                    'name': 'promo-cache',
                    'environment': 'test',
                    'mode': 'Sentinel',
                    'memory_total_gb': 24,
                },
            },
            format='json',
        )
        self.assertEqual(create_cluster.status_code, 200)
        self.assertTrue(any(item['name'] == 'promo-cache' for item in create_cluster.json()['data']['redis']['clusters']))

        create_instance = self.client.post(
            '/api/middleware/action/',
            {
                'module': 'redis',
                'action': 'create_instance',
                'payload': {
                    'cluster': 'promo-cache',
                    'name': 'redis-promo-master',
                    'environment': 'test',
                    'role': 'master',
                    'endpoint': '10.99.0.10:6379',
                },
            },
            format='json',
        )
        self.assertEqual(create_instance.status_code, 200)
        self.assertTrue(any(item['name'] == 'redis-promo-master' for item in create_instance.json()['data']['redis']['instances']))

    def test_create_elasticsearch_node_updates_cluster_size(self):
        response = self.client.post(
            '/api/middleware/action/',
            {
                'module': 'elasticsearch',
                'action': 'create_instance',
                'payload': {
                    'cluster': 'search-prod',
                    'name': 'es-search-07',
                    'endpoint': '10.23.0.17:9200',
                    'role': 'data_hot,ingest',
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']['elasticsearch']
        self.assertTrue(any(item['name'] == 'es-search-07' for item in data['nodes']))
        updated_cluster = next(item for item in data['clusters'] if item['name'] == 'search-prod')
        self.assertEqual(updated_cluster['nodes'], 3)

    def test_update_rocketmq_cluster_renames_related_records(self):
        response = self.client.post(
            '/api/middleware/action/',
            {
                'module': 'rocketmq',
                'target_id': 'rmq-cls-audit',
                'action': 'update_cluster',
                'payload': {
                    'name': 'audit-mq-v2',
                    'environment': 'prod',
                    'status': 'healthy',
                    'nameserver_count': 3,
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']['rocketmq']
        self.assertTrue(any(item['name'] == 'audit-mq-v2' for item in data['clusters']))
        self.assertTrue(any(item['cluster'] == 'audit-mq-v2' for item in data['brokers']))

    def test_delete_redis_cluster_removes_instances(self):
        response = self.client.post(
            '/api/middleware/action/',
            {'module': 'redis', 'target_id': 'redis-cls-member', 'action': 'delete_cluster'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']['redis']
        self.assertFalse(any(item['id'] == 'redis-cls-member' for item in data['clusters']))
        self.assertFalse(any(item['cluster'] == 'member-session' for item in data['instances']))

    def test_import_rocketmq_instance_template_creates_demo_broker(self):
        response = self.client.post(
            '/api/middleware/action/',
            {
                'module': 'rocketmq',
                'action': 'import_template',
                'payload': {
                    'scope': 'instance',
                    'template_key': 'slave',
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        brokers = response.json()['data']['rocketmq']['brokers']
        self.assertTrue(any(item['name'].startswith('broker-template-slave') for item in brokers))


class AlertViewSetFilterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('alert-admin', 'alert@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.host = Host.objects.create(hostname='alert-host-01', ip_address='10.0.1.10', environment='prod', status='warning')
        Alert.objects.create(title='Critical alert', level='critical', source='monitor', message='critical issue', is_acknowledged=False, host=self.host)
        Alert.objects.create(title='Warning alert', level='warning', source='monitor', message='warning issue', is_acknowledged=True, host=self.host)

    def test_alert_list_supports_level_and_ack_filters(self):
        response = self.client.get('/api/alerts/', {'level': 'critical', 'is_acknowledged': False})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['level'], 'critical')
        self.assertFalse(results[0]['is_acknowledged'])


class AlertWebhookIngestTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.integration = AlertIntegration.objects.create(name='Prometheus', provider='prometheus', default_labels={'environment': 'prod'})

    def test_prometheus_webhook_creates_normalized_alert(self):
        response = self.client.post(
            f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
            {
                'status': 'firing',
                'groupKey': 'service=order',
                'commonLabels': {'service': 'order-center'},
                'alerts': [{
                    'status': 'firing',
                    'fingerprint': 'fp-001',
                    'labels': {'alertname': 'HighErrorRate', 'severity': 'critical', 'instance': '10.0.1.10:9100'},
                    'annotations': {'summary': 'Order error rate high', 'description': '5xx ratio above threshold'},
                    'startsAt': '2026-05-04T10:00:00+08:00',
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 202)
        alert = Alert.objects.get()
        self.assertEqual(alert.source_type, 'prometheus')
        self.assertEqual(alert.level, 'critical')
        self.assertEqual(alert.service, 'order-center')
        self.assertEqual(alert.labels['environment'], 'prod')
        self.assertEqual(alert.status, Alert.STATUS_ACTIVE)
        self.assertTrue(AlertAction.objects.filter(alert=alert, action=AlertAction.ACTION_WEBHOOK).exists())

    def test_prometheus_webhook_prefers_app_then_job_name_then_service_for_service_field(self):
        response = self.client.post(
            f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
            {
                'status': 'firing',
                'alerts': [{
                    'status': 'firing',
                    'fingerprint': 'fp-002',
                    'labels': {
                        'alertname': 'KubeJobFailed',
                        'severity': 'warning',
                        'app': 'traffic-generator',
                        'job_name': 'traffic-generator-29633802',
                        'service': 'kube-prometheus-stack-kube-state-metrics',
                    },
                    'annotations': {'summary': 'Job failed to complete.'},
                    'startsAt': '2026-05-04T10:00:00+08:00',
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 202)
        alert = Alert.objects.get(fingerprint__isnull=False)
        self.assertEqual(alert.service, 'traffic-generator')

    def test_prometheus_webhook_falls_back_to_job_name_before_service(self):
        response = self.client.post(
            f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
            {
                'status': 'firing',
                'alerts': [{
                    'status': 'firing',
                    'fingerprint': 'fp-003',
                    'labels': {
                        'alertname': 'KubeJobFailed',
                        'severity': 'warning',
                        'job_name': 'traffic-generator-29633802',
                        'service': 'kube-prometheus-stack-kube-state-metrics',
                    },
                    'annotations': {'summary': 'Job failed to complete.'},
                    'startsAt': '2026-05-04T10:00:00+08:00',
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 202)
        alert = Alert.objects.get(fingerprint__isnull=False)
        self.assertEqual(alert.service, 'traffic-generator-29633802')

    def test_invalid_webhook_token_is_rejected(self):
        response = self.client.post('/api/alerts/webhooks/prometheus/bad-token/', {'alerts': []}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_provider_webhook_requires_token(self):
        response = self.client.post('/api/alerts/webhooks/prometheus/', {'alerts': []}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_generic_webhook_requires_configured_token(self):
        """generic 接入必须配置并携带 SXDEVOPS_GENERIC_WEBHOOK_TOKEN（安全整改后行为）。"""
        response = self.client.post(
            '/api/alerts/webhooks/generic/',
            {'title': 'Generic alert', 'level': 'warning', 'resource': 'demo-resource'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_generic_webhook_accepts_configured_token(self):
        with override_settings(GENERIC_WEBHOOK_TOKEN='shared-secret'):
            response = self.client.post(
                '/api/alerts/webhooks/generic/?token=shared-secret',
                {'title': 'Generic alert', 'level': 'warning', 'resource': 'demo-resource'},
                format='json',
            )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(Alert.objects.filter(title='Generic alert', source_type='generic').exists())


class AlertActionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('alert-operator', 'operator@example.com', 'Admin@123456')
        self.second_user = get_user_model().objects.create_superuser('backup-operator', 'backup@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.alert = Alert.objects.create(title='CPU high', level='warning', source='monitor', source_type='generic', message='cpu high')

    def test_claim_and_mute_alert(self):
        claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(claim_response.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.claimed_by, 'alert-operator')
        self.assertEqual(self.alert.claim_records.count(), 1)

        mute_response = self.client.post(f'/api/alerts/{self.alert.id}/mute/', {'minutes': 30}, format='json')
        self.assertEqual(mute_response.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.STATUS_MUTED)
        self.assertTrue(self.alert.is_suppressed)

    def test_multiple_users_can_claim_same_alert(self):
        first_claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(first_claim_response.status_code, 200)

        self.client.force_authenticate(user=self.second_user)
        second_claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(second_claim_response.status_code, 200)

        detail_response = self.client.get(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()
        self.assertEqual(payload['claimant_count'], 2)
        self.assertCountEqual([item['claimant'] for item in payload['claimants']], ['alert-operator', 'backup-operator'])
        self.assertTrue(payload['current_user_claimed'])

        unclaim_response = self.client.post(f'/api/alerts/{self.alert.id}/unclaim/')
        self.assertEqual(unclaim_response.status_code, 200)

        self.client.force_authenticate(user=self.user)
        detail_after_unclaim = self.client.get(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(detail_after_unclaim.status_code, 200)
        payload_after_unclaim = detail_after_unclaim.json()
        self.assertEqual(payload_after_unclaim['claimant_count'], 1)
        self.assertEqual(payload_after_unclaim['claimants'][0]['claimant'], 'alert-operator')

    def test_notification_rule_can_be_configured(self):
        channel = AlertNotificationChannel.objects.create(name='email', channel_type='email', config={'to': ['ops@example.com']})
        recipient = AlertRecipient.objects.create(name='Ops', email='ops@example.com')
        group = AlertRecipientGroup.objects.create(name='oncall')
        group.recipients.add(recipient)
        response = self.client.post(
            '/api/alert-notification-rules/',
            {
                'name': 'critical notify',
                'min_level': 'warning',
                'matchers': [{'key': 'source_type', 'op': '==', 'value': 'generic'}],
                'channel_ids': [channel.id],
                'recipient_group_ids': [group.id],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        rule = AlertNotificationRule.objects.get(name='critical notify')
        self.assertEqual(rule.channels.count(), 1)
        self.assertEqual(rule.recipient_groups.count(), 1)


class ZabbixDataSourceSaveTests(TestCase):
    """Zabbix 数据源保存链路：主机同步已异步化，CRUD 必须即时响应。"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser(
            'zabbix-admin', 'zabbix@example.com', 'Admin@123456'
        )
        self.client.force_authenticate(user=self.user)
        # 清空跨测试的 in-flight 状态，避免真实线程残留
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()

    def _payload(self, **overrides):
        payload = {
            'name': 'Prod Zabbix',
            'api_url': 'http://zabbix.internal/api_jsonrpc.php',
            'auth_type': 'token',
            'auth_token': 'secret-token',
            'timeout': 10,
            'is_enabled': True,
        }
        payload.update(overrides)
        return payload

    def _assert_thread_spawned(self, mock_thread, ds_id):
        mock_thread.Thread.assert_called_once()
        kwargs = mock_thread.Thread.call_args.kwargs
        self.assertTrue(kwargs['daemon'])
        self.assertEqual(kwargs['target'].__name__, '_zabbix_host_sync_worker')
        self.assertEqual(kwargs['args'], (ds_id,))
        mock_thread.Thread.return_value.start.assert_called_once()

    @patch('ops.models.threading')
    @patch('ops.zabbix_client.ZabbixClient')
    def test_create_returns_201_and_sync_runs_in_background_thread(self, mock_zabbix, mock_thread):
        response = self.client.post(
            '/api/observability/zabbix/datasources/', self._payload(), format='json'
        )
        self.assertEqual(response.status_code, 201)
        ds_id = response.json()['id']
        self._assert_thread_spawned(mock_thread, ds_id)
        # 同步体绝不在请求线程内执行（含 Zabbix API 调用）
        mock_zabbix.assert_not_called()

    @patch('ops.models.threading')
    def test_update_returns_200_and_sync_runs_in_background_thread(self, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        # 清掉 create 遗留的 in-flight 标记与线程调用记录，只观察 PUT 本身
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()
        mock_thread.reset_mock()
        response = self.client.put(
            f'/api/observability/zabbix/datasources/{ds.id}/',
            self._payload(name='Prod Zabbix 2'),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self._assert_thread_spawned(mock_thread, ds.id)

    @patch('ops.models.threading')
    def test_bookkeeping_save_does_not_trigger_sync(self, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()
        mock_thread.reset_mock()
        ds.last_sync_at = timezone.now()
        ds.save(update_fields=['last_sync_at'])
        mock_thread.Thread.assert_not_called()

    @patch('ops.models.threading')
    def test_update_fields_guard_still_syncs_on_relevant_fields(self, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()
        mock_thread.reset_mock()
        ds.api_url = 'http://zabbix2.internal/api_jsonrpc.php'
        ds.save(update_fields=['api_url'])
        mock_thread.Thread.assert_called_once()

    @patch('ops.models.threading')
    def test_dedupe_skips_overlapping_sync(self, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        # mock 线程不执行 worker，in-flight 标记残留 → 第二次保存被去重跳过
        ds.save()
        mock_thread.Thread.assert_called_once()

    @patch('ops.models.threading')
    def test_demo_datasource_never_syncs(self, mock_thread):
        ZabbixDataSource.objects.create(
            name='Demo DS', api_url='demo://', auth_type='token',
            auth_token='demo-token', is_enabled=True,
        )
        mock_thread.Thread.assert_not_called()

    @patch('ops.models.threading')
    def test_disabled_or_empty_url_never_syncs(self, mock_thread):
        ZabbixDataSource.objects.create(**self._payload(name='Disabled', is_enabled=False))
        ZabbixDataSource.objects.create(**self._payload(name='EmptyUrl', api_url=''))
        mock_thread.Thread.assert_not_called()

    @patch('ops.models.threading')
    @patch('ops.zabbix_client.ZabbixClient')
    def test_delete_returns_204_without_zabbix_interaction(self, mock_zabbix, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        response = self.client.delete(f'/api/observability/zabbix/datasources/{ds.id}/')
        self.assertEqual(response.status_code, 204)
        mock_zabbix.assert_not_called()

    @patch('ops.models.threading')
    @patch('ops.zabbix_client.ZabbixClient.get_hosts', side_effect=Exception('boom'))
    def test_worker_exception_is_isolated(self, mock_get_hosts, mock_thread):
        from ops.models import _SYNC_IN_FLIGHT, _zabbix_host_sync_worker
        ds = ZabbixDataSource.objects.create(**self._payload())
        with self.assertLogs('ops.models', level='WARNING'):
            _zabbix_host_sync_worker(ds.id)
        self.assertNotIn(ds.id, _SYNC_IN_FLIGHT)
        self.assertEqual(Host.objects.count(), 0)
    @patch('ops.models.threading')
    @patch('ops.zabbix_client.ZabbixClient')
    def test_remove_action_returns_200_and_deletes(self, mock_zabbix, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._payload())
        response = self.client.post(
            f'/api/observability/zabbix/datasources/{ds.id}/remove/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertFalse(ZabbixDataSource.objects.filter(id=ds.id).exists())
        mock_zabbix.assert_not_called()

class HttpMethodOverrideTests(TestCase):
    """生产安全设备阻断 DELETE/PUT/PATCH：POST + X-HTTP-Method-Override 还原原方法。"""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser(
            'mo-admin', 'mo@example.com', 'Admin@123456'
        )
        self.client.force_authenticate(user=self.user)
        # SQLite 事务回滚会复用自增 id：清场 in-flight 防止跨测试去重误判
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()

    def _ds_payload(self, name):
        return {
            'name': name,
            'api_url': 'http://zabbix.internal/api_jsonrpc.php',
            'auth_type': 'token',
            'auth_token': 'secret-token',
            'is_enabled': True,
        }

    @patch('ops.models.threading')
    def test_delete_override_routes_to_destroy(self, mock_thread):
        ds = ZabbixDataSource.objects.create(**self._ds_payload('MO DS'))
        response = self.client.post(
            f'/api/observability/zabbix/datasources/{ds.id}/',
            HTTP_X_HTTP_METHOD_OVERRIDE='DELETE',
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ZabbixDataSource.objects.filter(id=ds.id).exists())

    def test_put_override_updates_host(self):
        host = Host.objects.create(hostname='mo-host', ip_address='10.0.0.1')
        response = self.client.post(
            f'/api/hosts/{host.id}/',
            {'hostname': 'mo-host-2', 'ip_address': '10.0.0.1'},
            format='json',
            HTTP_X_HTTP_METHOD_OVERRIDE='PUT',
        )
        self.assertEqual(response.status_code, 200)
        host.refresh_from_db()
        self.assertEqual(host.hostname, 'mo-host-2')

    def test_patch_override_updates_user(self):
        response = self.client.post(
            f'/api/users/{self.user.id}/',
            {'username': 'mo-admin', 'first_name': 'Override'},
            format='json',
            HTTP_X_HTTP_METHOD_OVERRIDE='PATCH',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Override')

    @patch('ops.models.threading')
    def test_post_without_override_stays_post(self, mock_thread):
        response = self.client.post(
            '/api/observability/zabbix/datasources/',
            self._ds_payload('MO Plain Post'),
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(mock_thread.Thread.called)

    @patch('ops.models.threading')
    def test_override_ignored_on_non_post_method(self, mock_thread):
        # 收窄：仅原始方法为 POST 时才应用覆盖；DELETE 携带 override 头仍按 DELETE 执行
        ds = ZabbixDataSource.objects.create(**self._ds_payload('MO NonPost'))
        response = self.client.delete(
            f'/api/observability/zabbix/datasources/{ds.id}/',
            HTTP_X_HTTP_METHOD_OVERRIDE='PUT',
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ZabbixDataSource.objects.filter(id=ds.id).exists())

    def test_invalid_override_is_ignored(self):
        # TRACE 不在白名单 → 按普通 POST 处理 → 创建主机成功
        response = self.client.post(
            '/api/hosts/',
            {'hostname': 'mo-invalid-host', 'ip_address': '10.0.0.9'},
            format='json',
            HTTP_X_HTTP_METHOD_OVERRIDE='TRACE',
        )
        self.assertEqual(response.status_code, 201)

class ZabbixAlertAssociationTests(TestCase):
    """Zabbix 告警→主机关联键：hostid 优先于文本匹配，标签三键齐全。"""

    @patch('ops.models.threading')
    def test_host_for_prefers_zabbix_hostid(self, mock_thread):
        host_text = Host.objects.create(hostname='za-text-host', ip_address='10.0.0.1')
        host_ext = Host.objects.create(hostname='za-ext-host', ip_address='10.0.0.2', external_id='zabbix:10001')
        from ops.alerting import _host_for
        got = _host_for('za-text-host', {'zabbix_hostid': '10001', 'host': 'za-text-host'})
        self.assertEqual(got, host_ext)
        got2 = _host_for('za-text-host', {'host': 'za-text-host'})
        self.assertEqual(got2, host_text)

    @patch('ops.models.threading')
    def test_upsert_links_alert_to_host_by_hostid(self, mock_thread):
        Host.objects.create(hostname='za-visible-01', ip_address='10.0.0.3', external_id='zabbix:10002')
        from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem
        problem = {'eventid': 'za-evt-1', 'name': '磁盘空间不足', 'severity': '4', 'objectid': 'za-trig-1', 'clock': 1700000000}
        alert, created = upsert_alert_from_zabbix_problem(
            problem, host_name='za-tech-01', host_id='10002', visible_name='za-visible-01', env_name='prod')
        self.assertTrue(created)
        alert.refresh_from_db()
        self.assertIsNotNone(alert.host_id)
        self.assertEqual(alert.host.external_id, 'zabbix:10002')
        self.assertEqual(alert.labels['zabbix_hostid'], '10002')
        self.assertEqual(alert.labels['host'], 'za-tech-01')
        self.assertEqual(alert.labels['hostname'], 'za-visible-01')


class ZabbixPollingServiceTests(TestCase):
    """内置轮询服务：环境语义、统计、last_sync_at、错误收集。"""

    @patch('ops.models.threading')
    def test_poll_once_demo_source(self, mock_thread):
        ds = ZabbixDataSource.objects.create(
            name='轮询测试源', api_url='demo://', auth_type='token',
            auth_token='d', is_enabled=True, environment='poll-prod')
        from ops.zabbix_polling import poll_zabbix_alerts_once
        stats = poll_zabbix_alerts_once()
        self.assertEqual(stats['datasource_count'], 1)
        self.assertGreaterEqual(stats['problem_count'], 1)
        self.assertEqual(stats['errors'], [])
        ds.refresh_from_db()
        self.assertIsNotNone(ds.last_sync_at)
        self.assertTrue(Alert.objects.filter(source_type='zabbix', environment='poll-prod').exists())

    @patch('ops.models.threading')
    def test_poll_once_dry_run_does_not_write(self, mock_thread):
        ZabbixDataSource.objects.create(
            name='轮询dry源', api_url='demo://', auth_type='token',
            auth_token='d', is_enabled=True)
        from ops.zabbix_polling import poll_zabbix_alerts_once
        stats = poll_zabbix_alerts_once(dry_run=True)
        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['updated'], 0)
        self.assertFalse(Alert.objects.filter(source_type='zabbix').exists())


class ZabbixSchedulerTests(TestCase):
    """内置调度器守卫：autostart 条件、单次迭代可调。"""

    def test_autostart_guards(self):
        from ops import observability_scheduler as sch
        orig = sys.argv[:]
        try:
            sys.argv = ['manage.py', 'shell']
            self.assertFalse(sch.scheduler_should_autostart())
            sys.argv = ['manage.py', 'migrate']
            self.assertFalse(sch.scheduler_should_autostart())
            sys.argv = ['manage.py', 'runserver']
            self.assertTrue(sch.scheduler_should_autostart())
        finally:
            sys.argv = orig

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
    def test_run_once_iteration(self):
        from ops import observability_scheduler as sch
        sch.run_zabbix_poll_once()  # 不抛异常即通过


class BackfillZabbixAlertHostsTests(TestCase):
    """存量告警主机关联回填：hostid 优先、dry-run、幂等。"""

    @patch('ops.models.threading')
    def test_backfill_by_hostid(self, mock_thread):
        host = Host.objects.create(hostname='bf-host', ip_address='10.0.0.4', external_id='zabbix:10003')
        alert = Alert.objects.create(
            title='bf告警', level='warning', source='zabbix_api', source_type='zabbix',
            message='m', status='active', environment='prod', is_acknowledged=False,
            labels={'zabbix_hostid': '10003', 'host': 'bf-host', 'hostname': 'bf-host'})
        self.assertIsNone(alert.host_id)
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('backfill_zabbix_alert_hosts', stdout=out)
        alert.refresh_from_db()
        self.assertIsNone(alert.host_id)  # dry-run 不写
        call_command('backfill_zabbix_alert_hosts', '--yes', stdout=StringIO())
        alert.refresh_from_db()
        self.assertEqual(alert.host, host)
        call_command('backfill_zabbix_alert_hosts', '--yes', stdout=StringIO())  # 幂等


class ExecutePromqlQueryZabbixTests(TestCase):
    """指标通路 zabbix 分支：返回形状与 Prometheus 路径不回归。"""

    @patch('ops.models.threading')
    def test_zabbix_marker_returns_matrix_shape(self, mock_thread):
        ds = ZabbixDataSource.objects.create(
            name='指标源', api_url='demo://', auth_type='token', auth_token='d', is_enabled=True)
        marker = MetricDataSource.objects.create(
            name='Zabbix - 指标源', tsdb_type='zabbix', provider='prometheus',
            is_enabled=True, config={'zabbix_datasource_id': ds.id})
        from ops.observability_views import execute_promql_query
        now = timezone.now()
        result = execute_promql_query(
            'system.cpu.util', range_query=True,
            start_time=now - timedelta(hours=1), end_time=now, step=60,
            metric_datasource_id=marker.id, prefer_metric_datasource=True)
        self.assertEqual(result['source'], 'zabbix')
        self.assertEqual(result['resultType'], 'matrix')
        self.assertGreater(result['series_count'], 0)
        self.assertIsInstance(result['result'][0]['values'][0][0], float)

    def test_prometheus_missing_url_still_raises(self):
        pm = MetricDataSource.objects.create(
            name='普通Prom源', tsdb_type='prometheus', provider='prometheus', is_enabled=True)
        from ops.observability_views import execute_promql_query
        with self.assertRaises(RuntimeError):
            execute_promql_query('up', metric_datasource_id=pm.id, prefer_metric_datasource=True)

class ZabbixClientTestConnectionTests(TestCase):
    """测试连接：apiinfo.version 必须无认证头（Zabbix 7 要求），认证校验走真实调用。"""

    def _client(self, auth_type='token'):
        from types import SimpleNamespace
        from ops.zabbix_client import ZabbixClient
        ds = SimpleNamespace(
            api_url='http://zabbix.local/api_jsonrpc.php', auth_type=auth_type,
            auth_token='secret-token' if auth_type == 'token' else '',
            username='admin' if auth_type == 'userpass' else '',
            password='pw' if auth_type == 'userpass' else '',
            tls_verify=False, timeout=10, id=1)
        return ZabbixClient(ds)

    @patch('ops.zabbix_client.ZabbixClient._call_raw', return_value='7.4.0')
    @patch('ops.zabbix_client.ZabbixClient._call', return_value=[{'hostid': '1'}])
    def test_version_probe_without_auth_and_auth_check(self, mock_call, mock_raw):
        client = self._client('token')
        result = client.test_connection()
        self.assertEqual(result, '7.4.0')
        self.assertEqual(mock_raw.call_args[0][0]['method'], 'apiinfo.version')
        self.assertEqual(mock_call.call_args[0][0], 'host.get')

    @patch('ops.zabbix_client.ZabbixClient._call_raw', return_value='7.4.0')
    @patch('ops.zabbix_client.ZabbixClient._call', return_value={'error': 'Session terminated'})
    def test_auth_failure_surfaces_real_error(self, mock_call, mock_raw):
        client = self._client('token')
        result = client.test_connection()
        self.assertEqual(result, {'error': 'Session terminated'})

class ZabbixHostAnnotationTests(TestCase):
    """主机业务线/环境默认标注：权威覆盖 + 环境仅空值写入 + 回填命令。"""

    def setUp(self):
        from ops.models import _SYNC_IN_FLIGHT, _SYNC_IN_FLIGHT_LOCK
        with _SYNC_IN_FLIGHT_LOCK:
            _SYNC_IN_FLIGHT.clear()

    @patch('ops.models.threading')
    def test_worker_writes_defaults_and_preserves_manual_environment(self, mock_thread):
        ds = ZabbixDataSource.objects.create(
            name='标注源', api_url='demo://', auth_type='token', auth_token='d',
            is_enabled=True, business_line='测试业务', host_environment='prod')
        from ops.models import _zabbix_host_sync_worker
        _zabbix_host_sync_worker(ds.id)
        hosts = Host.objects.filter(source='zabbix')
        self.assertGreater(hosts.count(), 0)
        self.assertTrue(all(h.business_line == '测试业务' for h in hosts))
        self.assertTrue(all(h.environment == 'prod' for h in hosts))
        # 人工标注环境不被覆盖
        h = hosts.first()
        h.environment = 'test'
        h.save(update_fields=['environment'])
        _zabbix_host_sync_worker(ds.id)
        h.refresh_from_db()
        self.assertEqual(h.environment, 'test')

    @patch('ops.models.threading')
    def test_backfill_command_dry_run_and_idempotent(self, mock_thread):
        ds = ZabbixDataSource.objects.create(
            name='回填源', api_url='demo://', auth_type='token', auth_token='d',
            is_enabled=True, business_line='回填业务', host_environment='dev')
        Host.objects.create(hostname='bf-host-1', ip_address='10.0.0.1', source='zabbix',
                            external_id='zabbix:1', business_line='')
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('backfill_zabbix_host_annotations', stdout=out)
        h = Host.objects.get(hostname='bf-host-1')
        self.assertEqual(h.business_line, '')  # dry-run 不写
        call_command('backfill_zabbix_host_annotations', '--yes', stdout=StringIO())
        h.refresh_from_db()
        self.assertEqual(h.business_line, '回填业务')
        self.assertEqual(h.environment, 'dev')
        call_command('backfill_zabbix_host_annotations', '--yes', stdout=StringIO())  # 幂等


class ZabbixEventGovernanceTests(TestCase):
    """事件与审计治理：轮询重复 update 不记事件/审计，状态变化才记录。"""

    @patch('ops.models.threading')
    def test_repeat_poll_does_not_add_events_or_audit_rows(self, mock_thread):
        ds = ZabbixDataSource.objects.create(
            name='治理源', api_url='demo://', auth_type='token', auth_token='d', is_enabled=True)
        from ops.zabbix_polling import poll_zabbix_alerts_once
        from eventwall.models import EventRecord
        from ops.models import AlertAction
        poll_zabbix_alerts_once(datasource_id=ds.id)
        e1 = EventRecord.objects.filter(resource_type='zabbix_event').count()
        a1 = AlertAction.objects.count()
        poll_zabbix_alerts_once(datasource_id=ds.id)
        self.assertEqual(EventRecord.objects.filter(resource_type='zabbix_event').count(), e1)
        self.assertEqual(AlertAction.objects.count(), a1)
        self.assertGreater(e1, 0)  # 首轮创建有记录

    def test_webhook_audit_update_default_keeps_action_rows(self):
        # 默认 audit_update=True：其他来源重复 update 仍记审计（现状保持）
        from ops import alerting
        from ops.models import AlertAction
        from ops.alerting import _host_for
        payload = {
            'title': 'webhook-test', 'level': 'warning', 'status': 'active',
            'source': 'webhook', 'source_type': 'generic', 'external_id': 'wh-1',
            'fingerprint': 'wh-fp-1', 'message': 'm', 'environment': 'prod',
        }
        alerting.upsert_alert(dict(payload), actor='webhook')
        alerting.upsert_alert(dict(payload), actor='webhook')
        self.assertGreaterEqual(AlertAction.objects.count(), 2)


class TaskOwnershipTests(TestCase):
    """任务中心属主隔离：普通用户仅可见自己的任务；ops.task.manage 豁免。"""

    def setUp(self):
        from rbac.services import ensure_builtin_rbac
        from rbac.models import Role, PermissionDefinition

        ensure_builtin_rbac()
        execute_perm = PermissionDefinition.objects.get(code='ops.task.execute')
        manage_perm = PermissionDefinition.objects.get(code='ops.task.manage')
        self.executor_role = Role.objects.create(code='task-executor', name='Task Executor')
        self.executor_role.permissions.add(execute_perm)
        self.manager_role = Role.objects.create(code='task-manager', name='Task Manager')
        self.manager_role.permissions.add(execute_perm, manage_perm)
        self.user_a = get_user_model().objects.create_user('task-owner-a', password='Admin@123456')
        self.user_b = get_user_model().objects.create_user('task-owner-b', password='Admin@123456')
        self.manager = get_user_model().objects.create_user('task-manager-user', password='Admin@123456')
        self.executor_role.users.add(self.user_a, self.user_b)
        self.manager_role.users.add(self.manager)
        self.client = APIClient()

    def test_owner_sees_only_own_tasks(self):
        HostTask.objects.create(name='A 的任务', task_type=HostTask.TASK_RUN_COMMAND, created_by=self.user_a.username)
        HostTask.objects.create(name='B 的任务', task_type=HostTask.TASK_RUN_COMMAND, created_by=self.user_b.username)

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get('/api/host-tasks/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        items = payload.get('results') if isinstance(payload, dict) else payload
        names = [item['name'] for item in items]
        self.assertIn('A 的任务', names)
        self.assertNotIn('B 的任务', names)

    def test_task_manage_sees_all_tasks(self):
        HostTask.objects.create(name='A 的任务', task_type=HostTask.TASK_RUN_COMMAND, created_by=self.user_a.username)
        HostTask.objects.create(name='B 的任务', task_type=HostTask.TASK_RUN_COMMAND, created_by=self.user_b.username)

        self.client.force_authenticate(user=self.manager)
        response = self.client.get('/api/host-tasks/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        items = payload.get('results') if isinstance(payload, dict) else payload
        names = [item['name'] for item in items]
        self.assertIn('A 的任务', names)
        self.assertIn('B 的任务', names)

    def test_owner_cannot_retrieve_other_task(self):
        task_b = HostTask.objects.create(name='B 的任务', task_type=HostTask.TASK_RUN_COMMAND, created_by=self.user_b.username)

        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f'/api/host-tasks/{task_b.id}/')
        self.assertEqual(response.status_code, 404)


class CredentialEncryptionTests(TestCase):
    """凭据落库加密：写入侧加密、读取侧透明解密、历史明文兼容、回填命令幂等。"""

    def _raw_value(self, model, pk, field):
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(f'SELECT {field} FROM {model._meta.db_table} WHERE id=%s', [pk])
            return cur.fetchone()[0]

    def test_host_password_encrypted_at_rest(self):
        host = Host.objects.create(hostname='enc-host', ip_address='10.0.0.99', ssh_password='secret-pass-123')
        host.refresh_from_db()
        raw = self._raw_value(host, host.id, 'ssh_password')
        self.assertTrue(str(raw).startswith('enc:'), f'库内应为密文，实际: {str(raw)[:24]}...')
        self.assertEqual(host.ssh_password, 'secret-pass-123')

    def test_legacy_plaintext_reads_transparently(self):
        host = Host.objects.create(hostname='legacy-host', ip_address='10.0.0.98')
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("UPDATE ops_host SET ssh_password='legacy-plain' WHERE id=%s", [host.id])
        host.refresh_from_db()
        self.assertEqual(host.ssh_password, 'legacy-plain')

    def test_encrypt_legacy_credentials_dry_run_and_apply(self):
        host = Host.objects.create(hostname='migrate-host', ip_address='10.0.0.97')
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("UPDATE ops_host SET ssh_password='migrate-plain' WHERE id=%s", [host.id])
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('encrypt_legacy_credentials', stdout=out)
        self.assertIn('dry-run', out.getvalue())
        raw = self._raw_value(host, host.id, 'ssh_password')
        self.assertEqual(str(raw), 'migrate-plain', 'dry-run 不得写入')

        call_command('encrypt_legacy_credentials', '--apply', stdout=out)
        raw = self._raw_value(host, host.id, 'ssh_password')
        self.assertTrue(str(raw).startswith('enc:'))
        host.refresh_from_db()
        self.assertEqual(host.ssh_password, 'migrate-plain', '解密后值不变')
        # 幂等：重复执行不改变
        call_command('encrypt_legacy_credentials', '--apply', stdout=out)
        raw_again = self._raw_value(host, host.id, 'ssh_password')
        self.assertEqual(raw, raw_again)



class ZabbixHybridIngestTests(TestCase):
    """混合接入：webhook 推送与轮询拉取双路径指纹统一、恢复事件兜底。"""

    def setUp(self):
        from rbac.services import ensure_builtin_rbac

        ensure_builtin_rbac()

    def _webhook_payload(self, triggerid, eventid='1001', event_value='1', severity='4'):
        return {
            'alerts': [{
                'triggerid': triggerid,
                'eventid': eventid,
                'trigger_name': '高 CPU 使用率',
                'host': 'prod-web-01',
                'severity': severity,
                'event_value': event_value,
                'clock': '1726617600',
            }]
        }

    def test_webhook_payload_normalizes_fingerprint_and_severity(self):
        from ops import alerting

        normalized = alerting.normalize_alert_payload('zabbix', self._webhook_payload('T100'))
        self.assertEqual(len(normalized), 1)
        item = normalized[0]
        self.assertEqual(item['level'], 'critical')
        self.assertEqual(item['status'], 'active')
        self.assertEqual(item['source_type'], 'zabbix')
        import hashlib
        self.assertEqual(item['fingerprint'], hashlib.sha256('zabbix:T100'.encode()).hexdigest())

    def test_webhook_then_poll_shares_one_alert(self):
        from ops import alerting
        from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem
        from ops.models import Alert

        alerting.ingest_webhook('zabbix', self._webhook_payload('T200'))
        self.assertEqual(Alert.objects.filter(source_type='zabbix').count(), 1)

        problem = {'eventid': '2001', 'objectid': 'T200', 'name': '高 CPU 使用率', 'severity': '4',
                   'clock': '1726617600', 'r_eventid': '0'}
        alert, created = upsert_alert_from_zabbix_problem(problem, host_name='prod-web-01', host_id='10084')
        self.assertFalse(created, '同一 triggerid 的轮询拉取不应新建告警')
        self.assertEqual(Alert.objects.filter(source_type='zabbix').count(), 1)

    def test_poll_then_webhook_shares_one_alert(self):
        from ops import alerting
        from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem
        from ops.models import Alert

        problem = {'eventid': '2002', 'objectid': 'T300', 'name': '磁盘满', 'severity': '4',
                   'clock': '1726617600', 'r_eventid': '0'}
        upsert_alert_from_zabbix_problem(problem, host_name='prod-web-02', host_id='10085')
        self.assertEqual(Alert.objects.filter(source_type='zabbix').count(), 1)

        alerting.ingest_webhook('zabbix', self._webhook_payload('T300', eventid='2002'))
        self.assertEqual(Alert.objects.filter(source_type='zabbix').count(), 1)

    def test_poll_recovery_event_resolves_alert(self):
        from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem
        from ops.models import Alert

        problem = {'eventid': '2003', 'objectid': 'T400', 'name': '内存不足', 'severity': '4',
                   'clock': '1726617600', 'r_eventid': '0'}
        alert, created = upsert_alert_from_zabbix_problem(problem, host_name='prod-web-03', host_id='10086')
        self.assertTrue(created)
        self.assertEqual(alert.status, 'active')

        recovered = {'eventid': '2003', 'objectid': 'T400', 'name': '内存不足', 'severity': '4',
                     'clock': '1726617600', 'r_eventid': '3003', 'r_clock': '1726620000'}
        alert2, created2 = upsert_alert_from_zabbix_problem(recovered, host_name='prod-web-03', host_id='10086')
        self.assertFalse(created2)
        self.assertEqual(alert2.status, 'resolved')
        self.assertEqual(Alert.objects.filter(source_type='zabbix', status='active').count(), 0)


class BackfillZabbixAlertFingerprintTests(TestCase):
    """存量指纹回填：dry-run 不写、重算、孤儿 resolved、幂等。"""

    def setUp(self):
        from rbac.services import ensure_builtin_rbac

        ensure_builtin_rbac()

    def test_dry_run_does_not_write_and_apply_recomputes(self):
        from io import StringIO

        from django.core.management import call_command
        from ops.alerting import _fingerprint
        from ops.models import Alert

        alert = Alert.objects.create(
            title='存量告警', level='critical', status='active', source='zabbix_api',
            source_type='zabbix', external_id='5001', fingerprint='zabbix:5001',
            raw_payload={'objectid': 'T500', 'eventid': '5001'},
        )
        out = StringIO()
        call_command('backfill_zabbix_alert_fingerprints', stdout=out)
        alert.refresh_from_db()
        self.assertEqual(alert.fingerprint, 'zabbix:5001', 'dry-run 不得写入')

        call_command('backfill_zabbix_alert_fingerprints', '--apply', stdout=out)
        alert.refresh_from_db()
        expected = _fingerprint('zabbix', {'fingerprint': 'T500', 'external_id': '5001'})
        self.assertEqual(alert.fingerprint, expected)

        # 幂等：再次执行不改变
        call_command('backfill_zabbix_alert_fingerprints', '--apply', stdout=out)
        alert.refresh_from_db()
        self.assertEqual(alert.fingerprint, expected)
        self.assertEqual(alert.status, 'active')

    def test_unmatchable_legacy_alert_resolved(self):
        from django.core.management import call_command
        from ops.models import Alert

        alert = Alert.objects.create(
            title='无载荷存量告警', level='critical', status='active', source='zabbix_api',
            source_type='zabbix', external_id='5002', fingerprint='zabbix:5002', raw_payload={},
        )
        call_command('backfill_zabbix_alert_fingerprints', '--apply')
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'resolved')


class AlertAIAnalysisTests(TestCase):
    """告警自动 AI 分析：触发条件、防重、冷却、单条分析、关联分析、兜底重扫。"""

    def setUp(self):
        from django.core.cache import cache
        from unittest.mock import patch

        from rbac.services import ensure_builtin_rbac

        ensure_builtin_rbac()
        cache.clear()
        self.worker_patch = patch('ops.alert_ai_analysis.start_alert_analysis_worker')
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    def tearDown(self):
        # 排空测试期间入队的任务，避免串扰其他用例
        from ops import alert_ai_analysis

        while not alert_ai_analysis._analysis_queue.empty():
            try:
                alert_ai_analysis._analysis_queue.get_nowait()
            except Exception:
                break

    def _make_alert(self, level='critical', fingerprint='fp-1', status='active', source_type='zabbix',
                    integration=None, raw_payload=None):
        from ops.models import Alert

        return Alert.objects.create(
            title='测试告警', level=level, status=status, source='zabbix', source_type=source_type,
            external_id='e1', fingerprint=fingerprint, integration=integration,
            raw_payload=raw_payload or {'objectid': fingerprint},
        )

    def _ensure_bot_user(self):
        from ops.alert_ai_analysis import _get_bot_user

        return _get_bot_user()

    def test_enqueue_above_min_level_only(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis

        info = self._make_alert(level='info', fingerprint='fp-info')
        self.assertFalse(enqueue_alert_analysis(info), '低于全局默认 warning 不触发')

        warning = self._make_alert(level='warning', fingerprint='fp-warn')
        self.assertTrue(enqueue_alert_analysis(warning), '全局默认 warning 起触发')

    def test_duplicate_enqueue_blocked_and_failure_retry_once(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis
        from ops.models import AlertAction

        alert = self._make_alert(fingerprint='fp-dup')
        self.assertTrue(enqueue_alert_analysis(alert))
        self.assertFalse(enqueue_alert_analysis(alert, ignore_cooldown=True), '排队中/完成中不重复入队')

        # 标记失败后可重试一次
        AlertAction.objects.filter(alert=alert, action='aiops_analysis').update(
            metadata={'status': 'failed', 'attempts': 1})
        self.assertTrue(enqueue_alert_analysis(alert, ignore_cooldown=True))
        AlertAction.objects.filter(alert=alert, action='aiops_analysis').update(
            metadata={'status': 'failed', 'attempts': 2})
        self.assertFalse(enqueue_alert_analysis(alert, ignore_cooldown=True), '超过重试次数不再入队')

    def test_single_analysis_produces_result(self):
        from unittest.mock import patch

        from aiops.models import AIOpsChatMessage, AIOpsChatSession
        from ops.alert_ai_analysis import _process_batch
        from ops.models import AlertAction

        alert = self._make_alert(fingerprint='fp-single')
        bot = AIOpsChatSession.objects.create(user=self._ensure_bot_user(), title='t', context={})
        assistant = AIOpsChatMessage.objects.create(
            session=bot, role='assistant',
            content='建议：检查 CPU 限流。' + chr(10) + chr(10) + '补充：关注高峰时段并评估扩容。'
        )

        with patch('ops.alert_ai_analysis._create_session_and_ask', return_value=(bot, assistant)):
            _process_batch([alert.id])

        action = AlertAction.objects.filter(alert=alert, action='aiops_analysis').last()
        self.assertEqual(action.metadata.get('status'), 'completed')
        self.assertIn('检查 CPU 限流', action.metadata.get('summary', ''))
        alert.refresh_from_db()
        self.assertIn('aiops_suggestion', alert.annotations)
        # 单条分析完成应写事件墙
        from eventwall.models import EventRecord
        wall_event = EventRecord.objects.filter(action='alert_analysis', metadata__alert_id=alert.id).first()
        self.assertIsNotNone(wall_event, '单条分析完成应写入事件墙')
        self.assertEqual(wall_event.metadata.get('analysis_kind'), 'single')
        self.assertEqual(wall_event.severity, EventRecord.SEVERITY_DANGER, 'critical 告警分析事件应映射为 danger')
        self.assertIn(chr(10), wall_event.detail or '', 'detail 应保留换行段落')
        self.assertIn('评估扩容', wall_event.detail or '')

    def test_correlation_analysis_groups_same_source_alerts(self):
        from unittest.mock import patch

        from aiops.models import AIOpsChatMessage, AIOpsChatSession
        from eventwall.models import EventRecord
        from ops.alert_ai_analysis import _process_batch
        from ops.models import AlertAction, AlertIntegration

        integration = AlertIntegration.objects.create(name='zabbix-源', provider='zabbix', token='tok-1')
        a1 = self._make_alert(fingerprint='fp-c1', integration=integration)
        a2 = self._make_alert(fingerprint='fp-c2', integration=integration)

        bot = AIOpsChatSession.objects.create(user=self._ensure_bot_user(), title='t', context={})
        assistant = AIOpsChatMessage.objects.create(
            session=bot, role='assistant', content='根因：共享存储故障。'
        )
        calls = []

        def fake_session_ask(question, title):
            calls.append(question)
            return bot, assistant

        with patch('ops.alert_ai_analysis._create_session_and_ask', side_effect=fake_session_ask):
            _process_batch([a1.id, a2.id])

        self.assertEqual(len(calls), 1, '同源两条告警应合并为一次关联分析')
        self.assertIn('关联分析', calls[0])
        for alert in (a1, a2):
            action = AlertAction.objects.filter(alert=alert, action='aiops_analysis').last()
            self.assertEqual(action.metadata.get('status'), 'completed')
            self.assertIn('corr-', action.metadata.get('correlation_group', ''))
            alert.refresh_from_db()
            self.assertIn('aiops_root_cause', alert.annotations)
        self.assertTrue(EventRecord.objects.filter(action='alert_correlation').exists())
        corr_event = EventRecord.objects.filter(action='alert_correlation').latest('id')
        self.assertTrue(corr_event.correlation_id.startswith('alert_correlation:'))
        self.assertEqual(corr_event.metadata.get('event_category'), 'alert')

    def test_requeue_unanalyzed_alerts(self):
        from ops import alert_ai_analysis
        from ops.alert_ai_analysis import requeue_unanalyzed_alerts
        from ops.models import AlertAction

        analyzed = self._make_alert(fingerprint='fp-done')
        AlertAction.objects.create(alert=analyzed, action='aiops_analysis', actor='aiops-bot',
                                   metadata={'status': 'completed'})
        unanalyzed = self._make_alert(fingerprint='fp-pending')

        enqueued = requeue_unanalyzed_alerts()
        self.assertEqual(enqueued, 1, '仅未分析的 critical 告警入队')
        queued_ids = []
        while not alert_ai_analysis._analysis_queue.empty():
            queued_ids.append(alert_ai_analysis._analysis_queue.get_nowait())
        self.assertEqual(queued_ids, [unanalyzed.id])

    def test_suppressed_alert_not_enqueued(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis
        from ops.models import AlertAction

        alert = self._make_alert(fingerprint='fp-suppressed')
        alert.is_suppressed = True
        alert.save(update_fields=['is_suppressed'])
        self.assertFalse(enqueue_alert_analysis(alert), '被抑制告警不进入 AI 分析')
        self.assertFalse(AlertAction.objects.filter(alert=alert, action='aiops_analysis').exists())

    def test_normalize_level_fail_closed(self):
        from ops.alert_ai_analysis import _normalize_level

        self.assertEqual(_normalize_level('  WARNING '), 'warning')
        self.assertEqual(_normalize_level('Critical'), 'critical')
        self.assertEqual(_normalize_level('bogus'), 'critical', '非法值 fail-closed 为 critical')
        self.assertEqual(_normalize_level(''), 'critical')

    def test_integration_invalid_min_level_fails_closed(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis
        from ops.models import AlertIntegration

        integration = AlertIntegration.objects.create(name='zabbix-坏阈值', provider='zabbix', token='tok-2')
        integration.ai_analysis_min_level = 'bogus'
        integration.save(update_fields=['ai_analysis_min_level'])
        warning = self._make_alert(level='warning', fingerprint='fp-bad-threshold', integration=integration)
        self.assertFalse(enqueue_alert_analysis(warning), '非法接入源阈值 fail-closed，不分析 warning')
        critical = self._make_alert(level='critical', fingerprint='fp-bad-threshold-2', integration=integration)
        self.assertTrue(enqueue_alert_analysis(critical), 'critical 仍触发')

    def test_requeue_not_crowded_out_by_low_level_noise(self):
        from ops import alert_ai_analysis
        from ops.alert_ai_analysis import requeue_unanalyzed_alerts

        critical = self._make_alert(fingerprint='fp-req-noise-target')
        for index in range(150):
            self._make_alert(level='info', fingerprint=f'fp-req-noise-{index}')
        enqueued = requeue_unanalyzed_alerts()
        self.assertEqual(enqueued, 1, '低级别噪音不应挤掉更早的 critical 告警')
        queued_ids = []
        while not alert_ai_analysis._analysis_queue.empty():
            queued_ids.append(alert_ai_analysis._analysis_queue.get_nowait())
        self.assertEqual(queued_ids, [critical.id])

    def test_requeue_respects_integration_relaxed_threshold(self):
        from ops.alert_ai_analysis import requeue_unanalyzed_alerts
        from ops.models import AlertIntegration

        integration = AlertIntegration.objects.create(name='zabbix-放宽源', provider='zabbix', token='tok-3',
                                                      ai_analysis_min_level='info')
        self._make_alert(level='info', fingerprint='fp-req-relaxed', integration=integration)
        self.assertEqual(requeue_unanalyzed_alerts(), 1, '接入源放宽阈值应纳入重扫预筛')

    def test_requeue_failed_action_retried_once(self):
        from ops import alert_ai_analysis
        from ops.alert_ai_analysis import requeue_unanalyzed_alerts
        from ops.models import AlertAction

        retryable = self._make_alert(fingerprint='fp-req-failed-1')
        AlertAction.objects.create(alert=retryable, action='aiops_analysis', actor='aiops-bot',
                                   metadata={'status': 'failed', 'attempts': 1})
        exhausted = self._make_alert(fingerprint='fp-req-failed-2')
        AlertAction.objects.create(alert=exhausted, action='aiops_analysis', actor='aiops-bot',
                                   metadata={'status': 'failed', 'attempts': 2})
        enqueued = requeue_unanalyzed_alerts()
        self.assertEqual(enqueued, 1, 'failed 且 attempts<2 允许重扫一次，attempts>=2 被 enqueue 拒绝')
        queued_ids = []
        while not alert_ai_analysis._analysis_queue.empty():
            queued_ids.append(alert_ai_analysis._analysis_queue.get_nowait())
        self.assertEqual(queued_ids, [retryable.id])


class ZabbixMacroAuditTests(TestCase):
    """宏对照审计修复回归：severity 全映射、点分时间、冒号标签、字段配套、external_id 保留。"""

    def setUp(self):
        from rbac.services import ensure_builtin_rbac

        ensure_builtin_rbac()

    def test_severity_numeric_full_mapping(self):
        from ops.alerting import _severity_to_level

        self.assertEqual(_severity_to_level('5', 'zabbix'), 'critical')
        self.assertEqual(_severity_to_level('4', 'zabbix'), 'critical')
        self.assertEqual(_severity_to_level('3', 'zabbix'), 'warning')
        self.assertEqual(_severity_to_level('2', 'zabbix'), 'warning')
        self.assertEqual(_severity_to_level('1', 'zabbix'), 'info')
        self.assertEqual(_severity_to_level('0', 'zabbix'), 'info')

    def test_severity_chinese_text_mapping(self):
        from ops.alerting import _severity_to_level

        self.assertEqual(_severity_to_level('灾难', 'zabbix'), 'critical')
        self.assertEqual(_severity_to_level('严重', 'zabbix'), 'critical')
        self.assertEqual(_severity_to_level('一般严重', 'zabbix'), 'warning')
        self.assertEqual(_severity_to_level('平均值', 'zabbix'), 'warning')
        self.assertEqual(_severity_to_level('信息', 'zabbix'), 'info')

    def test_parse_time_dotted_format(self):
        from django.utils import timezone as dj_timezone
        from ops.alerting import _parse_time

        parsed = _parse_time('2026.09.18 10:00:00')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 9)
        self.assertEqual(parsed.day, 18)
        self.assertEqual(parsed.hour, 10)

    def test_parse_labels_zabbix_colon_format(self):
        from ops.alerting import _parse_labels

        labels = _parse_labels('app: order-db, env: prod, desc: disk full, team: dba')
        self.assertEqual(labels.get('app'), 'order-db')
        self.assertEqual(labels.get('env'), 'prod')
        self.assertEqual(labels.get('desc'), 'disk full', '含空格的值不得被截断')
        self.assertEqual(labels.get('team'), 'dba')

    def test_parse_labels_keeps_equals_and_whitespace_compat(self):
        from ops.alerting import _parse_labels

        labels = _parse_labels('app=order-db,env=prod')
        self.assertEqual(labels.get('app'), 'order-db')
        self.assertEqual(labels.get('env'), 'prod')
        # 无逗号的空白分隔 key=value 兼容旧行为
        labels2 = _parse_labels('app=order-db env=prod')
        self.assertEqual(labels2.get('app'), 'order-db')
        self.assertEqual(labels2.get('env'), 'prod')

    def test_webhook_hostid_and_host_ip_and_acknowledged(self):
        from ops import alerting
        from ops.models import Alert

        payload = {'alerts': [{
            'triggerid': 'T900', 'eventid': 'E900', 'trigger_name': '测试',
            'severity': '4', 'event_value': '1',
            'hostid': '10888', 'host_ip': '10.0.0.55', 'acknowledged': '1',
        }]}
        result = alerting.ingest_webhook('zabbix', payload)
        alert = result['alerts'][0]
        self.assertEqual(alert.labels.get('zabbix_hostid'), '10888')
        self.assertEqual(alert.annotations.get('acknowledged'), '1')
        # host 缺失时 resource 兜底 host_ip
        self.assertEqual(alert.resource, '10.0.0.55')

    def test_webhook_recovery_event_resolves_and_keeps_external_id(self):
        from ops import alerting
        from ops.models import Alert

        problem = {'alerts': [{
            'triggerid': 'T901', 'eventid': 'E901', 'trigger_name': '测试恢复',
            'severity': '4', 'event_value': '1', 'host': 'web-01',
        }]}
        alerting.ingest_webhook('zabbix', problem)
        alert = Alert.objects.get(fingerprint__isnull=False, labels__isnull=False)
        # 恢复事件：新 eventid + event_value=0
        recovery = {'alerts': [{
            'triggerid': 'T901', 'eventid': 'E902', 'trigger_name': '测试恢复',
            'severity': '0', 'event_value': '0', 'host': 'web-01',
        }]}
        result = alerting.ingest_webhook('zabbix', recovery)
        updated = result['alerts'][0]
        self.assertEqual(updated.status, 'resolved')
        self.assertEqual(updated.external_id, 'E901', '恢复事件不得覆盖原 PROBLEM external_id')
        self.assertEqual(Alert.objects.filter(source_type='zabbix').count(), 1, '恢复不得新建告警')

    def test_poll_client_output_includes_rclock_and_opdata(self):
        """经 client 层：get_problems 输出含 r_clock/opdata，恢复 ends_at=真实恢复时间。"""
        from unittest.mock import patch

        from ops.zabbix_alert_bridge import _build_normalized, _ts_to_datetime
        from ops.zabbix_client import ZabbixClient

        output_fields = None

        def fake_ensure_auth(self):
            return True

        def fake_call(self, method, params):
            nonlocal output_fields
            output_fields = params.get('output')
            return [{
                'eventid': 'E903', 'objectid': 'T903', 'name': '测试',
                'severity': '4', 'clock': '1726617600',
                'r_eventid': 'R903', 'r_clock': '1726621200', 'opdata': '当前值 92%',
            }]

        with patch.object(ZabbixClient, '_ensure_auth', fake_ensure_auth), \
             patch.object(ZabbixClient, '_call', fake_call):
            client = ZabbixClient.__new__(ZabbixClient)
            problems = client.get_problems(recent=False)

        self.assertIn('r_clock', output_fields, 'client 必须拉取 r_clock')
        self.assertIn('opdata', output_fields, 'client 必须拉取 opdata')
        problem = problems[0]
        normalized = _build_normalized(problem, host_name='web-01', host_id='10889')
        self.assertEqual(normalized['status'], 'resolved')
        self.assertIsNotNone(normalized['ends_at'])
        self.assertEqual(
            normalized['ends_at'],
            _ts_to_datetime('1726621200'),
            'ends_at 应为真实恢复时间而非轮询时间',
        )
        self.assertEqual(normalized['annotations'].get('opdata'), '当前值 92%')

    def test_ts_to_datetime_missing_returns_none(self):
        from ops.zabbix_alert_bridge import _ts_to_datetime

        self.assertIsNone(_ts_to_datetime(None))
        self.assertIsNone(_ts_to_datetime(''))


class RunbookUrlSafetyTests(TestCase):
    """runbook_url 白名单：拒绝 javascript:/data: 伪协议。"""

    def test_javascript_url_rejected(self):
        from ops import alerting
        from ops.models import Alert

        alerting.ingest_webhook('zabbix', {'alerts': [{
            'triggerid': 'rb-1', 'eventid': 'rb-e1', 'trigger_name': 'x',
            'severity': '4', 'event_value': '1',
            'url': 'javascript:alert(1)',
        }]})
        alert = Alert.objects.filter(source_type='zabbix').latest('id')
        self.assertEqual(alert.runbook_url, '')

    def test_http_url_kept(self):
        from ops import alerting
        from ops.models import Alert

        alerting.ingest_webhook('zabbix', {'alerts': [{
            'triggerid': 'rb-2', 'eventid': 'rb-e2', 'trigger_name': 'x',
            'severity': '4', 'event_value': '1',
            'url': 'https://wiki.example.com/runbooks/disk-full',
        }]})
        alert = Alert.objects.filter(source_type='zabbix').latest('id')
        self.assertEqual(alert.runbook_url, 'https://wiki.example.com/runbooks/disk-full')



class AlertAnalysisClosedLoopTests(TestCase):
    """告警闭环：接入源级开关/阈值、更新分支触发、摘要接口权限、通知规则开关、WS 鉴权。"""

    def setUp(self):
        from django.core.cache import cache
        from unittest.mock import patch

        from rbac.services import ensure_builtin_rbac

        ensure_builtin_rbac()
        cache.clear()
        self.worker_patch = patch('ops.alert_ai_analysis.start_alert_analysis_worker')
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)

    def tearDown(self):
        from ops import alert_ai_analysis

        while not alert_ai_analysis._analysis_queue.empty():
            try:
                alert_ai_analysis._analysis_queue.get_nowait()
            except Exception:
                break

    def _make_alert(self, level='warning', fingerprint='fp-x', integration=None):
        from ops.models import Alert

        return Alert.objects.create(
            title='闭环测试', level=level, status='active', source='zabbix', source_type='zabbix',
            external_id='e1', fingerprint=fingerprint, integration=integration,
            raw_payload={'objectid': fingerprint},
        )

    def _make_integration(self, enabled=True, min_level='warning'):
        from ops.models import AlertIntegration

        return AlertIntegration.objects.create(
            name='闭环源', provider='zabbix', token=f'tok-{uuid.uuid4().hex[:10]}',
            ai_analysis_enabled=enabled, ai_analysis_min_level=min_level,
        )

    def test_integration_disabled_blocks_enqueue(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis

        integration = self._make_integration(enabled=False)
        alert = self._make_alert(level='critical', fingerprint='fp-off', integration=integration)
        self.assertFalse(enqueue_alert_analysis(alert), '接入源开关关闭时不触发')

    def test_integration_min_level_filters(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis

        integration = self._make_integration(enabled=True, min_level='critical')
        warning = self._make_alert(level='warning', fingerprint='fp-w1', integration=integration)
        critical = self._make_alert(level='critical', fingerprint='fp-c1', integration=integration)
        self.assertFalse(enqueue_alert_analysis(warning), '低于接入源阈值不触发')
        self.assertTrue(enqueue_alert_analysis(critical))

    def test_no_integration_falls_back_to_global_default(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis

        warning = self._make_alert(level='warning', fingerprint='fp-g1')
        self.assertTrue(enqueue_alert_analysis(warning), '无接入源回退全局默认（warning）')

    def test_existing_alert_update_branch_triggers_once(self):
        from ops.alert_ai_analysis import enqueue_alert_analysis

        alert = self._make_alert(level='critical', fingerprint='fp-upd')
        # 首次推送（新建）入队
        self.assertTrue(enqueue_alert_analysis(alert))
        # 模拟后续推送（更新分支）：已排队中 → 防重不重复
        self.assertFalse(enqueue_alert_analysis(alert, ignore_cooldown=True))

    def test_summaries_endpoint_requires_alert_view(self):
        from rest_framework.test import APIClient

        client = APIClient()
        no_perm_user = get_user_model().objects.create_user(username='no-alert-user', password='Admin@123456')
        client.force_authenticate(user=no_perm_user)
        response = client.get('/api/alerts/ai-analysis-summaries/')
        self.assertEqual(response.status_code, 403)

    def test_summaries_returns_analyzed_alerts(self):
        from rest_framework.test import APIClient

        from ops.models import Alert

        alert = self._make_alert(level='warning', fingerprint='fp-s1')
        alert.annotations = {'aiops_suggestion': '建议：检查磁盘。', 'opdata': ''}
        alert.save(update_fields=['annotations'])
        user = get_user_model().objects.create_superuser(username='summary-admin', password='Admin@123456')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/alerts/ai-analysis-summaries/?limit=10')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(item['alert_id'] == alert.id for item in payload))
        item = next(item for item in payload if item['alert_id'] == alert.id)
        self.assertIn('检查磁盘', item['suggestion'])

    def test_rule_aiops_analysis_switch(self):
        from ops.alerting import _rule_can_send
        from ops.models import AlertNotificationRule

        alert = self._make_alert(level='warning', fingerprint='fp-r1')
        rule_on = AlertNotificationRule.objects.create(name='r-on', notify_on_aiops_analysis=True)
        rule_off = AlertNotificationRule.objects.create(name='r-off', notify_on_aiops_analysis=False)
        self.assertTrue(_rule_can_send(rule_on, alert, 'aiops_analysis'))
        self.assertFalse(_rule_can_send(rule_off, alert, 'aiops_analysis'))
        self.assertTrue(_rule_can_send(rule_on, alert, 'fire'))

    def test_rule_serializer_includes_aiops_analysis_switch(self):
        from ops.models import AlertNotificationRule
        from ops.serializers import AlertNotificationRuleSerializer

        rule = AlertNotificationRule.objects.create(name='r-ser', notify_on_aiops_analysis=True)
        output = AlertNotificationRuleSerializer(rule).data
        self.assertTrue(output.get('notify_on_aiops_analysis'), '序列化输出应包含 AI 分析开关字段')
        serializer = AlertNotificationRuleSerializer(
            rule, data={'name': 'r-ser', 'notify_on_aiops_analysis': False}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        rule.refresh_from_db()
        self.assertFalse(rule.notify_on_aiops_analysis, '写入路径应持久化 AI 分析开关字段')

    def test_summaries_not_crowded_out_by_noise(self):
        from rest_framework.test import APIClient

        alert = self._make_alert(level='warning', fingerprint='fp-s-noise')
        alert.annotations = {'aiops_suggestion': '建议：检查磁盘。'}
        alert.save(update_fields=['annotations'])
        # 45 条更晚创建的无标注噪音告警：旧实现 [:limit*4] 先切片再过滤，会被全部挤掉
        for index in range(45):
            self._make_alert(level='info', fingerprint=f'fp-s-noise-{index}')
        user = get_user_model().objects.create_superuser(username='summary-noise-admin', password='Admin@123456')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/alerts/ai-analysis-summaries/?limit=10')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(item['alert_id'] == alert.id for item in payload),
                        '近期噪音告警不应把已分析告警挤出摘要窗口')

    def test_aiops_analysis_default_body_contains_conclusions(self):
        from ops.alerting import _default_body

        alert = self._make_alert(level='warning', fingerprint='fp-body')
        alert.annotations = {'aiops_root_cause': '根因：磁盘满', 'aiops_suggestion': '建议：清理日志'}
        alert.save(update_fields=['annotations'])
        body = _default_body(alert, 'aiops_analysis')
        self.assertIn('根因：磁盘满', body)
        self.assertIn('建议：清理日志', body)

        bare = self._make_alert(level='critical', fingerprint='fp-body-2')
        fallback_body = _default_body(bare, 'aiops_analysis')
        self.assertIn('AI 分析已完成', fallback_body)

    def test_notification_consumer_auth(self):
        from ops.notification_consumer import NotificationConsumer

        closed = {}

        def make_consumer(subprotocols=None, query_string=b''):
            consumer = NotificationConsumer()
            consumer.channel_layer = _FakeChannelLayer()
            consumer.channel_name = 'test-channel'
            consumer.scope = {'subprotocols': subprotocols or [], 'query_string': query_string, 'url_route': {}}
            consumer.close = lambda code=1000: closed.update(code=code)
            consumer.accept = lambda subprotocol=None: closed.update(code=0, subprotocol=subprotocol)
            return consumer

        # 无效 token（子协议携带）→ 4401
        make_consumer(subprotocols=['bearer.invalid']).connect()
        self.assertEqual(closed['code'], 4401)
        # 有效 token 但无告警查看权限 → 仍可连接，仅加入后台作业广播组
        user = get_user_model().objects.create_user(username='no-alert-ws', password='Admin@123456')
        token = Token.objects.create(user=user)
        consumer = make_consumer(subprotocols=[f'bearer.{token.key}'])
        consumer.connect()
        self.assertEqual(closed['code'], 0)
        self.assertEqual(consumer.channel_layer.joined, ['background-job-broadcast'])
        # 有告警查看权限 → 额外加入告警分析广播组，且回显子协议
        from rbac.models import PermissionDefinition, Role

        role = Role.objects.create(code='alert-viewer-ws', name='Alert Viewer WS')
        role.permissions.add(PermissionDefinition.objects.get(code='ops.alert.view'))
        user2 = get_user_model().objects.create_user(username='alert-ws', password='Admin@123456')
        role.users.add(user2)
        token2 = Token.objects.create(user=user2)
        consumer2 = make_consumer(subprotocols=[f'bearer.{token2.key}'])
        consumer2.connect()
        self.assertEqual(closed['code'], 0)
        self.assertEqual(closed.get('subprotocol'), f'bearer.{token2.key}')
        self.assertEqual(consumer2.channel_layer.joined,
                         ['background-job-broadcast', 'alert-analysis-broadcast'])
        # 旧式 query token 已废弃 → 4401（凭据不得进 URL/访问日志）
        user3 = get_user_model().objects.create_user(username='alert-ws-legacy', password='Admin@123456')
        role.users.add(user3)
        token3 = Token.objects.create(user=user3)
        make_consumer(query_string=f'token={token3.key}'.encode()).connect()
        self.assertEqual(closed['code'], 4401)


class _FakeChannelLayer:
    def __init__(self):
        self.joined = []

    async def group_add(self, group, channel):
        self.joined.append(group)

    async def group_discard(self, group, channel):
        pass



class AiAnalysisDetailTextTests(TestCase):
    """AI 分析全文清洗：保留换行、剥离控制字符、限长。"""

    def test_safe_multiline_preserves_newlines(self):
        from ops.alert_ai_analysis import _safe_multiline_text

        text = '根因：' + chr(0) + '磁盘满\n\n建议：\r\n- 清理日志\r- 扩容'
        result = _safe_multiline_text(text)
        self.assertIn('磁盘满', result)
        self.assertIn('\n', result)
        self.assertNotIn(chr(0), result)
        self.assertNotIn('\r', result)

    def test_safe_multiline_limit(self):
        from ops.alert_ai_analysis import _safe_multiline_text

        self.assertLessEqual(len(_safe_multiline_text('x' * 5000, limit=100)), 100)


class ForecastTests(TestCase):
    """ops.forecast 轻量时序预测：线性外推/阈值到达时间/移动平均/摘要。"""

    def _series(self, fn, start_ts=1700000000.0, step=300.0, count=60):
        return [(start_ts + step * i, fn(start_ts + step * i, i)) for i in range(count)]

    def test_linear_forecast_perfect_line(self):
        points = self._series(lambda ts, i: i * 1.0)  # y = i, 严格线性
        result = linear_forecast(points, horizon_points=6)
        self.assertAlmostEqual(result['slope'] * 300.0, 1.0, places=6, msg='每步斜率为 1')
        self.assertGreater(result['r2'], 0.999)
        # 预测首点与历史末点连续
        last_ts, last_val = points[-1]
        f_ts, f_val = result['forecast'][0]
        self.assertAlmostEqual(f_ts, last_ts + 300.0, places=6)
        self.assertAlmostEqual(f_val, last_val + 1.0, places=6)
        self.assertEqual(len(result['forecast']), 6)
        self.assertEqual(len(result['upper']), 6)
        self.assertEqual(len(result['lower']), 6)

    def test_linear_forecast_noisy_constant(self):
        points = self._series(lambda ts, i: 50.0 + ((i * 7) % 5) - 2.0)  # 均值 50 的噪声
        result = linear_forecast(points, horizon_points=12)
        mean = sum(v for _, v in result['forecast']) / len(result['forecast'])
        self.assertAlmostEqual(mean, 50.0, delta=5.0)
        self.assertEqual(result['trend'], 'flat')
        self.assertGreater(result['rmse'], 0.0, msg='噪声序列带宽应为正')

    def test_threshold_eta_rising_trend(self):
        points = self._series(lambda ts, i: 50.0 + i * 0.5)  # 末点 79.5，每 5 分钟 +0.5
        eta = threshold_eta(points, threshold=80.0)
        self.assertIsNotNone(eta)
        # 从末点 79.5 到 80 需 1 步 × 300s
        self.assertAlmostEqual(eta, 300.0, delta=60.0)

    def test_threshold_eta_falling_trend_returns_none(self):
        points = self._series(lambda ts, i: 80.0 - i * 0.5)
        self.assertIsNone(threshold_eta(points, threshold=95.0))

    def test_threshold_eta_already_exceeded_returns_zero(self):
        points = self._series(lambda ts, i: 90.0 + i * 0.5)
        self.assertEqual(threshold_eta(points, threshold=80.0), 0.0)

    def test_threshold_eta_beyond_max_days_returns_none(self):
        points = self._series(lambda ts, i: 50.0 + i * 0.001)  # 约 168 天才到 99
        self.assertIsNone(threshold_eta(points, threshold=99.0, max_days=30))

    def test_moving_average_same_shape(self):
        points = self._series(lambda ts, i: i * 1.0)
        smoothed = moving_average(points, window=5)
        self.assertEqual(len(smoothed), len(points))
        self.assertAlmostEqual(smoothed[0][1], 0.0, places=6)
        self.assertAlmostEqual(smoothed[-1][1], sum(range(55, 60)) / 5.0, places=6)

    def test_summarize_series(self):
        points = self._series(lambda ts, i: 10.0 + i * 0.1)
        summary = summarize_series(points)
        self.assertEqual(summary['count'], 60)
        self.assertEqual(summary['direction'], 'up')
        self.assertEqual(summary['min'], 10.0)
        self.assertAlmostEqual(summary['last'], 15.9, places=6)
        self.assertEqual(summary['start'], points[0][0])
        self.assertEqual(summary['end'], points[-1][0])

    def test_empty_or_single_point_raises(self):
        with self.assertRaises(ValueError):
            linear_forecast([])
        with self.assertRaises(ValueError):
            linear_forecast([(1700000000.0, 1.0)])
        with self.assertRaises(ValueError):
            threshold_eta([(1700000000.0, 1.0)], threshold=2.0)


class PromQLDemoEvaluatorTests(TestCase):
    """ops.prometheus_demo 确定性演示指标引擎：生成器 + PromQL 子集求值器。"""

    NOW = 1728000000.0  # 固定"当前时刻"，配合 patch 冻结时间

    def _patch_now(self):
        return patch('ops.prometheus_demo.time.time', return_value=self.NOW)

    def _eval(self, expr, start_ts=None, end_ts=None, step=300, range_query=True):
        with self._patch_now():
            return evaluate_promql(expr, start_ts=start_ts, end_ts=end_ts, step=step, range_query=range_query)

    def _values(self, result):
        return [float(v) for _, v in result['result'][0]['values']]

    # ── 生成器 ────────────────────────────────────────────────

    def test_list_metric_names_covers_specs(self):
        names = list_metric_names()
        for expected in [
            'node_cpu_usage_percent', 'node_memory_usage_percent', 'node_disk_usage_percent',
            'node_network_receive_bytes_total', 'http_requests_total',
            'http_request_duration_seconds', 'http_errors_total', 'inventory_check_duration_seconds',
        ]:
            self.assertIn(expected, names)

    def test_list_label_values(self):
        self.assertEqual(len(list_label_values('host')), 6)
        self.assertIn('order-api-ecs-01', list_label_values('host'))
        self.assertEqual(len(list_label_values('service')), 4)
        self.assertIn('order-service', list_label_values('service'))
        self.assertEqual(list_label_values('code'), ['200', '500'])

    def test_disk_story_ecs01_55_to_92(self):
        # 故事线：order-api-ecs-01 磁盘 24h 前 55%、现在 92%（对齐 Zabbix trigger 20001）
        day = 86400.0
        with self._patch_now():
            past = evaluate_promql('node_disk_usage_percent{host="order-api-ecs-01"}',
                                   start_ts=self.NOW - day, end_ts=self.NOW - day, step=60, range_query=False)
            current = evaluate_promql('node_disk_usage_percent{host="order-api-ecs-01"}',
                                      start_ts=self.NOW, end_ts=self.NOW, step=60, range_query=False)
        self.assertAlmostEqual(float(past['result'][0]['value'][1]), 55.0, delta=2.0)
        self.assertAlmostEqual(float(current['result'][0]['value'][1]), 92.0, delta=2.0)

    def test_memory_leak_story_member_api(self):
        # 故事线：member-api 内存 7 天 40%→78%（对齐 trigger 20003）
        week = 7 * 86400.0
        with self._patch_now():
            past = evaluate_promql('node_memory_usage_percent{host="member-api"}',
                                   start_ts=self.NOW - week, end_ts=self.NOW - week, step=60, range_query=False)
            current = evaluate_promql('node_memory_usage_percent{host="member-api"}',
                                      start_ts=self.NOW, end_ts=self.NOW, step=60, range_query=False)
        self.assertAlmostEqual(float(past['result'][0]['value'][1]), 40.0, delta=3.0)
        self.assertAlmostEqual(float(current['result'][0]['value'][1]), 78.0, delta=3.0)

    # ── 选择器与查询形态 ─────────────────────────────────────

    def test_range_selector_returns_matrix(self):
        result = self._eval('node_disk_usage_percent{host="order-api-ecs-01"}',
                            start_ts=self.NOW - 3600, end_ts=self.NOW, step=60)
        self.assertEqual(result['resultType'], 'matrix')
        self.assertEqual(len(result['result']), 1)
        self.assertEqual(len(result['result'][0]['values']), 61)
        self.assertEqual(result['result'][0]['metric']['host'], 'order-api-ecs-01')

    def test_label_filters(self):
        self.assertEqual(len(self._eval('node_cpu_usage_percent{host=~"order-api.*"}')['result']), 2)
        self.assertEqual(len(self._eval('node_cpu_usage_percent{host!="gateway"}')['result']), 5)
        self.assertEqual(len(self._eval('http_requests_total{service="order-service",code="500"}')['result']), 1)

    def test_instant_query_returns_vector(self):
        result = self._eval('node_cpu_usage_percent{host="gateway"}', range_query=False)
        self.assertEqual(result['resultType'], 'vector')
        self.assertIn('value', result['result'][0])

    # ── 函数与聚合 ────────────────────────────────────────────

    def test_rate_of_counter(self):
        result = self._eval('rate(http_requests_total{service="order-service",code="200"}[5m])',
                            start_ts=self.NOW - 3600, end_ts=self.NOW, step=60)
        values = self._values(result)
        self.assertEqual(len(result['result']), 1)
        self.assertTrue(all(v >= 0 for v in values))
        # 量级约等于基线 QPS（order-service 200 码基线 120，容差放宽）
        mean = sum(values) / len(values)
        self.assertGreater(mean, 50)
        self.assertLess(mean, 300)

    def test_sum_by_and_without(self):
        by_host = self._eval('sum(node_cpu_usage_percent) by (host)')
        self.assertEqual(len(by_host['result']), 6)
        total = self._eval('sum(node_cpu_usage_percent) without (host)')
        self.assertEqual(len(total['result']), 1)
        per_host = [float(s['values'][-1][1]) for s in by_host['result']]
        self.assertAlmostEqual(float(total['result'][0]['values'][-1][1]), sum(per_host), delta=0.01)

    def test_avg_aggregation(self):
        result = self._eval('avg(node_cpu_usage_percent)')
        value = float(result['result'][0]['values'][-1][1])
        self.assertGreater(value, 20)
        self.assertLess(value, 90)

    # ── 算术与比较 ────────────────────────────────────────────

    def test_arithmetic_scalar_broadcast(self):
        raw = self._eval('node_cpu_usage_percent{host="gateway"}', step=300)
        doubled = self._eval('node_cpu_usage_percent{host="gateway"} * 2', step=300)
        raw_val = float(raw['result'][0]['values'][-1][1])
        doubled_val = float(doubled['result'][0]['values'][-1][1])
        self.assertAlmostEqual(doubled_val, raw_val * 2, places=4)

    def test_comparison_filter(self):
        # 磁盘故事线：仅 order-api-ecs-01（92%）超过 50%，其它主机 ≤20%
        high = self._eval('node_disk_usage_percent > 50')
        self.assertEqual([s['metric']['host'] for s in high['result']], ['order-api-ecs-01'])
        empty = self._eval('node_disk_usage_percent > 999')
        self.assertEqual(empty['result'], [])

    # ── 不支持语法钉死 ───────────────────────────────────────

    def test_unsupported_expressions_raise(self):
        unsupported = [
            'topk(3, node_cpu_usage_percent)',
            'bottomk(3, node_cpu_usage_percent)',
            'histogram_quantile(0.9, node_cpu_usage_percent)',
            'avg_over_time(node_cpu_usage_percent[5m])',
            'node_cpu_usage_percent offset 5m',
            'node_cpu_usage_percent[5m]',
            'node_cpu_usage_percent and node_memory_usage_percent',
            'node_cpu_usage_percent unless node_memory_usage_percent',
            'quantile(0.9, node_cpu_usage_percent)',
            'node_cpu_usage_percent[5m:1m]',
        ]
        for expr in unsupported:
            with self.assertRaises(ValueError, msg=expr) as ctx:
                self._eval(expr)
            self.assertIn('不支持', str(ctx.exception), msg=expr)

    # ── 确定性 ────────────────────────────────────────────────

    def test_deterministic_output(self):
        with self._patch_now():
            first = evaluate_promql('sum by (host) (node_cpu_usage_percent)',
                                    start_ts=self.NOW - 3600, end_ts=self.NOW, step=60)
            second = evaluate_promql('sum by (host) (node_cpu_usage_percent)',
                                     start_ts=self.NOW - 3600, end_ts=self.NOW, step=60)
        self.assertEqual(first, second)


class DemoMetricApiTests(TestCase):
    """演示指标数据源 API：/observability/metrics/query/ 走 ops.prometheus_demo 离线引擎。"""

    NOW = 1728000000.0

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('ops-admin', 'ops@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        MetricDataSource.objects.create(
            name='Prometheus 演示数据源', provider='prometheus', tsdb_type='prometheus',
            environment='', cluster_name='', description='离线模拟',
            config={'demo_mode': True}, is_enabled=True, is_default=True)
        cache.clear()

    def _post_query(self, promql, **extra):
        payload = {'promql': promql, 'range_query': True, 'step': 60, **extra}
        with patch('ops.prometheus_demo.time.time', return_value=self.NOW):
            return self.client.post('/api/observability/metrics/query/', payload, format='json')

    def test_demo_metric_query_returns_matrix(self):
        response = self._post_query('node_disk_usage_percent{host="order-api-ecs-01"}')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['resultType'], 'matrix')
        self.assertEqual(body['series_count'], 1)
        self.assertEqual(body['source'], 'prometheus_demo')
        values = body['result'][0]['values']
        self.assertGreater(len(values), 5)
        self.assertAlmostEqual(float(values[-1][1]), 92.0, delta=2.0, msg='故事线末值 92%')

    def test_demo_metric_query_default_datasource_resolution(self):
        # 不传 metric_datasource_id：按 is_default 解析到演示源
        response = self._post_query('node_cpu_usage_percent{host="gateway"}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['series_count'], 1)

    def test_demo_metric_query_unsupported_returns_400(self):
        response = self._post_query('topk(3, node_cpu_usage_percent)')
        self.assertEqual(response.status_code, 400)
        self.assertIn('不支持', response.json()['detail'])

    def test_demo_series_names(self):
        with patch('ops.prometheus_demo.time.time', return_value=self.NOW):
            response = self.client.get('/api/observability/metrics/series-names/')
        self.assertEqual(response.status_code, 200)
        metrics = response.json()['metrics']
        for expected in ('node_cpu_usage_percent', 'http_requests_total', 'node_disk_usage_percent'):
            self.assertIn(expected, metrics)

    def test_demo_metric_query_scalar_returns_200(self):
        # 纯标量表达式（无选择器）不应让 _promql_result_sample 崩溃成 502
        response = self._post_query('1 + 2')
        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertEqual(body['resultType'], 'scalar')
        self.assertEqual(body['series_count'], 0)

    def test_demo_metric_datasource_test_connection_succeeds(self):
        ds = MetricDataSource.objects.get(name='Prometheus 演示数据源')
        with patch('ops.prometheus_demo.time.time', return_value=self.NOW):
            response = self.client.post(
                f'/api/observability/metric/datasources/{ds.id}/test_connection/',
                {'query': 'node_cpu_usage_percent'}, format='json')
        self.assertEqual(response.status_code, 200, response.json())
        self.assertTrue(response.json().get('success'))


class AlertCausalityFieldTests(TestCase):
    """Alert 因果字段（alert_code/causal_level/derived_from/evidence_chain）+ 回填命令。"""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('causality-admin', 'c@example.com', 'Admin@123456')
        self.client.force_login(self.user)

    def _create_alert(self, title='测试告警', level='critical', status='active', **kwargs):
        from ops.models import Alert
        fields = dict(
            title=title, level=level, status=status,
            source='test', source_type='generic',
            fingerprint=uuid.uuid4().hex[:32], **kwargs)
        return Alert.objects.create(**fields)

    def test_fields_default_values(self):
        alert = self._create_alert()
        self.assertEqual(alert.alert_code, '')
        self.assertEqual(alert.causal_level, 'none')
        self.assertEqual(alert.derived_from, [])
        self.assertEqual(alert.evidence_chain, [])

    def test_fields_exposed_by_list_api(self):
        alert = self._create_alert(title='ORA-01653 表空间无法扩展')
        alert.alert_code = 'ORA-01653'
        alert.causal_level = 'derived'
        alert.derived_from = [1]
        alert.evidence_chain = [{'rule_code': 'D1'}]
        alert.save(update_fields=['alert_code', 'causal_level', 'derived_from', 'evidence_chain'])

        response = self.client.get('/api/alerts/', {'alert_code': 'ORA-01653'})
        self.assertEqual(response.status_code, 200)
        rows = response.json().get('results', response.json())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['alert_code'], 'ORA-01653')
        self.assertEqual(rows[0]['causal_level'], 'derived')
        self.assertEqual(rows[0]['derived_from'], [1])
        self.assertEqual(rows[0]['evidence_chain'], [{'rule_code': 'D1'}])

    def test_filter_by_causal_level_and_fold_derived(self):
        self._create_alert(title='根因告警', level='critical')
        derived = self._create_alert(title='派生告警', level='warning')
        derived.causal_level = 'derived'
        derived.save(update_fields=['causal_level'])

        response = self.client.get('/api/alerts/', {'causal_level': 'derived'})
        rows = response.json().get('results', response.json())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], '派生告警')

        folded = self.client.get('/api/alerts/', {'fold_derived': '1'})
        folded_rows = folded.json().get('results', folded.json())
        self.assertTrue(all(row['title'] != '派生告警' for row in folded_rows))

    def test_backfill_command_dry_run(self):
        from django.core.management import call_command
        from io import StringIO

        self._create_alert(title='ORA-01653: unable to extend table', level='critical')
        self._create_alert(title='ORA-12541 TNS no listener', level='critical')
        self._create_alert(title='普通 CPU 告警', level='warning')

        out = StringIO()
        call_command('backfill_alert_codes', '--dry-run', stdout=out)
        output = out.getvalue()
        self.assertIn('ORA-01653', output)
        self.assertIn('ORA-12541', output)
        # 未执行的 dry-run 不应落库
        from ops.models import Alert
        self.assertEqual(Alert.objects.filter(alert_code__in=['ORA-01653', 'ORA-12541']).count(), 0)


class AlertCausalRuleSeedTests(TestCase):
    """L1 规则模型与告警码字典：字典完整性、规则 seed 幂等、L1 派生码覆盖。"""

    def test_dictionary_covers_codes_with_chinese(self):
        from ops.alert_causality import ALERT_CODE_DICTIONARY

        # 附录 A 31 条 + D1 前件所需 TABLESPACE_FULL（附录未列，V2.0 §4.3 D1 引用）
        self.assertEqual(len(ALERT_CODE_DICTIONARY), 32)
        for code, entry in ALERT_CODE_DICTIONARY.items():
            self.assertTrue(entry.get('name'), f'{code} 缺中文名')
            self.assertIn(entry.get('level'), ('root', 'derived', 'candidate'), f'{code} 级别非法')

    def test_default_rules_cover_l1_derived_codes(self):
        from ops.alert_causality import DEFAULT_CAUSAL_RULES

        targets = set()
        for rule in DEFAULT_CAUSAL_RULES:
            targets.update(rule['target_alert_codes'])
        for code in ['ORA-12541', 'ORA-01653', 'DB_HANG', 'DB_IO_DEGRADED',
                     'DB_WRITE_BLOCKED', 'INSTANCE_UNREACHABLE', 'NETWORK_ABNORMAL']:
            self.assertIn(code, targets, f'L1 派生码 {code} 未被默认规则覆盖')

    def test_rule_ids_align_with_v2(self):
        from ops.alert_causality import DEFAULT_CAUSAL_RULES

        codes = {rule['code'] for rule in DEFAULT_CAUSAL_RULES}
        self.assertEqual(codes, {'B3', 'D1', 'D2', 'D2b', 'D3', 'B1', 'B2'})

    def test_seed_command_idempotent(self):
        from django.core.management import call_command
        from ops.models import AlertCausalRule

        call_command('seed_alert_causality_rules', stdout=__import__('io').StringIO())
        count1 = AlertCausalRule.objects.count()
        call_command('seed_alert_causality_rules', stdout=__import__('io').StringIO())
        self.assertEqual(AlertCausalRule.objects.count(), count1)
        self.assertGreaterEqual(count1, 7)

    def test_knowledge_env_causal_rule_set_default(self):
        from aiops.models import AIOpsKnowledgeEnvironment

        env = AIOpsKnowledgeEnvironment.objects.create(
            name='causal-env', is_enabled=True, created_by='x', updated_by='x')
        self.assertEqual(env.causal_rule_set, {})


class AlertCausalityEngineTests(TestCase):
    """L1 因果执行器 evaluate_alert_causality：收敛、时间窗、环、熔断、开关、保守标记。"""

    def setUp(self):
        from django.core.management import call_command
        from cmdb.models import CIType, CIRelation, ConfigItem
        from ops.models import Alert

        call_command('seed_alert_causality_rules', stdout=__import__('io').StringIO())

        self.lun_type = CIType.objects.create(name='存储卷')
        self.df_type = CIType.objects.create(name='数据文件')
        self.ts_type = CIType.objects.create(name='表空间')
        self.inst_type = CIType.objects.create(name='Oracle实例')

        self.lun = ConfigItem.objects.create(name='lun-orders-01', ci_type=self.lun_type)
        self.df = ConfigItem.objects.create(name='ts_order_01.dbf', ci_type=self.df_type)
        self.ts = ConfigItem.objects.create(name='TS_ORDER', ci_type=self.ts_type)
        self.orcl = ConfigItem.objects.create(name='ORCL01', ci_type=self.inst_type)

        # 存储链路：LUN ← 数据文件 ← 表空间 ← 实例（contains 关系 + depends_on 到存储）
        CIRelation.objects.create(source=self.orcl, target=self.ts, relation_type_id='contains')
        CIRelation.objects.create(source=self.ts, target=self.df, relation_type_id='contains')
        CIRelation.objects.create(source=self.df, target=self.lun, relation_type_id='depends_on')

        self.Alert = Alert

    def _alert(self, code, resource, minutes_ago=2, level='critical', environment=''):
        return self.Alert.objects.create(
            title=f'{code} 测试告警', level=level, status='active',
            source='test', source_type='generic', fingerprint=uuid.uuid4().hex[:32],
            alert_code=code, resource=resource, environment=environment,
            starts_at=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def test_tablespace_full_derives_ora_01653(self):
        from ops.alert_causality import evaluate_alert_causality

        root = self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        result = evaluate_alert_causality(derived)

        self.assertIsNotNone(result)
        self.assertTrue(result['converged'])
        self.assertEqual(result['rule'], 'D1')
        self.assertEqual(result['root_alert_id'], root.id)
        derived.refresh_from_db()
        self.assertEqual(derived.causal_level, 'derived')
        self.assertIn(root.id, derived.derived_from)
        self.assertTrue(derived.evidence_chain)
        chain = derived.evidence_chain[0]
        self.assertEqual(chain['rule_code'], 'D1')
        self.assertIn('TS_ORDER', chain['path'])
        root.refresh_from_db()
        self.assertEqual(root.causal_level, 'root')

    def test_window_exceeded_skips(self):
        from ops.alert_causality import evaluate_alert_causality

        self._alert('TABLESPACE_FULL', 'TS_ORDER', minutes_ago=10)
        derived = self._alert('ORA-01653', 'ORCL01')
        result = evaluate_alert_causality(derived)
        self.assertIsNone(result)
        derived.refresh_from_db()
        self.assertEqual(derived.causal_level, 'none')

    def test_cycle_safe(self):
        from ops.alert_causality import evaluate_alert_causality
        from cmdb.models import CIRelation

        # 构造环：TS → LUN → ORCL → TS
        CIRelation.objects.create(source=self.lun, target=self.orcl, relation_type_id='depends_on')
        CIRelation.objects.create(source=self.orcl, target=self.ts, relation_type_id='depends_on')
        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        result = evaluate_alert_causality(derived)  # 不超时不崩溃
        self.assertTrue(result is None or result.get('converged') in (True, False))

    def test_storm_cutoff_truncated(self):
        from ops.alert_causality import evaluate_alert_causality
        from cmdb.models import ConfigItem, CIType, CIRelation

        node_type = CIType.objects.create(name='存储系统')
        for i in range(25):
            node = ConfigItem.objects.create(name=f'node-{i}', ci_type=node_type)
            CIRelation.objects.create(source=self.ts, target=node, relation_type_id='contains')
        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        result = evaluate_alert_causality(derived)
        self.assertIsNotNone(result)
        self.assertTrue(result['truncated'])

    def test_disabled_switch_skips(self):
        from unittest import mock
        from ops.alert_causality import evaluate_alert_causality

        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        with mock.patch('ops.alert_causality._causality_enabled', return_value=False):
            result = evaluate_alert_causality(derived)
        self.assertIsNone(result)
        derived.refresh_from_db()
        self.assertEqual(derived.causal_level, 'none')

    def test_suppressed_skips(self):
        from ops.alert_causality import evaluate_alert_causality

        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        derived.is_suppressed = True
        derived.save(update_fields=['is_suppressed'])
        self.assertIsNone(evaluate_alert_causality(derived))

    def test_idempotent(self):
        from ops.alert_causality import evaluate_alert_causality

        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        evaluate_alert_causality(derived)
        chain_len = len(derived.evidence_chain)
        evaluate_alert_causality(derived)
        derived.refresh_from_db()
        self.assertEqual(len(derived.evidence_chain), chain_len, '重复执行不应重复写证据链')

    def test_mark_only_no_mutation(self):
        from ops.alert_causality import evaluate_alert_causality

        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        evaluate_alert_causality(derived)
        derived.refresh_from_db()
        self.assertEqual(derived.status, 'active', '不得修改状态')
        self.assertFalse(derived.is_suppressed, '不得写抑制标记')
        self.assertFalse(derived.muted_by, '不得写静默字段')

    def test_cross_environment_no_false_convergence(self):
        """跨环境同名资源不得产生虚假收敛。"""
        from ops.alert_causality import evaluate_alert_causality
        from cmdb.models import CIRelation, ConfigItem

        dev_ts = ConfigItem.objects.create(name='TS_ORDER', ci_type=self.ts_type, environment='dev')
        CIRelation.objects.create(source=self.orcl, target=dev_ts, relation_type_id='contains')
        self._alert('TABLESPACE_FULL', 'TS_ORDER', environment='dev')
        derived = self._alert('ORA-01653', 'ORCL01', environment='prod')
        result = evaluate_alert_causality(derived)
        self.assertIsNone(result, '跨环境不得产生虚假收敛')
        derived.refresh_from_db()
        self.assertEqual(derived.causal_level, 'none')

    def test_anchor_prefers_same_environment_ci(self):
        """同名 CI 多环境存在时，锚点应优先取与告警同环境的 CI（即使同环境 CI 更旧）。"""
        from ops.alert_causality import _find_ci_anchor
        from cmdb.models import ConfigItem

        prod_ci = ConfigItem.objects.create(name='TS_ORDER', ci_type=self.ts_type, environment='prod')
        # 后创建的 dev CI 更新，无偏好实现下 first() 会误取它
        ConfigItem.objects.create(name='TS_ORDER', ci_type=self.ts_type, environment='dev')
        alert = self._alert('TABLESPACE_FULL', 'TS_ORDER', environment='prod')
        anchor = _find_ci_anchor(alert)
        self.assertEqual(anchor.id, prod_ci.id, '锚点应取同环境 CI')

    def test_late_root_converges_derived_out_of_order(self):
        """根因告警晚于派生告警到达（乱序 ingest）时，对称评估仍应收敛。"""
        from ops.alert_causality import _maybe_evaluate_causality

        derived = self._alert('ORA-01653', 'ORCL01')
        derived.occurrence_count = 10  # 历史实现会因次数门槛被永久跳过
        derived.save(update_fields=['occurrence_count'])
        root = self._alert('TABLESPACE_FULL', 'TS_ORDER')

        _maybe_evaluate_causality(root)
        derived.refresh_from_db()
        self.assertEqual(derived.causal_level, 'derived', '根因到达后派生告警应收敛')
        self.assertIn(root.id, derived.derived_from)

    def test_evidence_path_is_real_shortest_path_not_closure(self):
        """多分支图上，证据链 path 必须是锚点到根因的真实路径，而非整个可达闭包。"""
        from ops.alert_causality import evaluate_alert_causality
        from cmdb.models import ConfigItem, CIRelation

        sibling = ConfigItem.objects.create(name='TS_ARCHIVE', ci_type=self.ts_type)
        CIRelation.objects.create(source=self.orcl, target=sibling, relation_type_id='contains')

        self._alert('TABLESPACE_FULL', 'TS_ORDER')
        derived = self._alert('ORA-01653', 'ORCL01')
        evaluate_alert_causality(derived)
        derived.refresh_from_db()
        path = derived.evidence_chain[0]['path']
        self.assertEqual(path, ['ORCL01', 'TS_ORDER'], f'path 应为真实路径，实际: {path}')


class AlertCausalityMountTests(TestCase):
    """L1 挂载：webhook 与 Zabbix 轮询双路径触发；异常不阻断；折叠计数键。"""

    def setUp(self):
        from ops.models import AlertIntegration
        self.client = APIClient()
        self.integration = AlertIntegration.objects.create(name='Prometheus', provider='prometheus')

    def _webhook_payload(self, fingerprint='fp-causal-01'):
        return {
            'status': 'firing',
            'alerts': [{
                'status': 'firing',
                'fingerprint': fingerprint,
                'labels': {'alertname': 'CausalProbe', 'severity': 'warning'},
                'annotations': {'summary': 'causal probe alert'},
                'startsAt': '2026-05-04T10:00:00+08:00',
            }],
        }

    def test_webhook_ingest_triggers_causality(self):
        with patch('ops.alerting._maybe_evaluate_causality') as spy:
            response = self.client.post(
                f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
                self._webhook_payload(), format='json')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(spy.call_count, 1)

    def test_zabbix_bridge_triggers_causality(self):
        from ops.zabbix_alert_bridge import upsert_alert_from_zabbix_problem

        problem = {
            'eventid': 'evt-causal-01',
            'name': 'causal probe problem',
            'severity': '3',
            'clock': str(int(timezone.now().timestamp())),
        }
        with patch('ops.zabbix_alert_bridge._maybe_evaluate_causality') as spy:
            alert, created = upsert_alert_from_zabbix_problem(
                problem, host_name='causal-host-01', host_id='10001')
        self.assertIsNotNone(alert)
        self.assertTrue(created)
        self.assertEqual(spy.call_count, 1)

    def test_executor_exception_does_not_block_ingest(self):
        with patch('ops.alerting._maybe_evaluate_causality', side_effect=RuntimeError('boom')):
            response = self.client.post(
                f'/api/alerts/webhooks/prometheus/{self.integration.token}/',
                self._webhook_payload('fp-causal-02'), format='json')
        self.assertEqual(response.status_code, 202)
        from ops.models import Alert
        self.assertTrue(Alert.objects.filter(message__icontains='causal probe').exists())

class OracleDemoStorylineTests(TestCase):
    """Oracle 域演示故事线：CI 链种子与 Zabbix 演示问题（时钟差 ≤5min）。"""

    def test_seed_oracle_domain_creates_ci_chain_and_relations(self):
        from cmdb.oracle_demo_seed import seed_oracle_ci_types, seed_oracle_domain
        from cmdb.models import CIRelation, ConfigItem

        seed_oracle_ci_types()
        seed_oracle_domain()

        for name in ['orcl-db-01', 'ORCL01', 'TS_ORDER', 'ts_order_01.dbf',
                     'lun-orders-01', 'san-orders', 'listener-01', 'arch-01']:
            self.assertTrue(ConfigItem.objects.filter(name=name).exists(), f'{name} 缺失')
        self.assertGreaterEqual(CIRelation.objects.count(), 6)
        # 关键因果边：实例 contains 表空间
        orcl = ConfigItem.objects.get(name='ORCL01')
        ts = ConfigItem.objects.get(name='TS_ORDER')
        self.assertTrue(CIRelation.objects.filter(
            source=orcl, target=ts, relation_type_id='contains').exists())

    def test_seed_oracle_domain_idempotent(self):
        from cmdb.oracle_demo_seed import seed_oracle_ci_types, seed_oracle_domain
        from cmdb.models import ConfigItem

        seed_oracle_ci_types()
        seed_oracle_domain()
        count = ConfigItem.objects.count()
        seed_oracle_domain()
        self.assertEqual(ConfigItem.objects.count(), count)

    def test_demo_problems_include_oracle_storyline(self):
        from ops.zabbix_demo_data import dispatch_demo_call

        result = dispatch_demo_call('problem.get', {})
        names = {p.get('name', '') for p in result}
        self.assertTrue(any('TABLESPACE_FULL' in n for n in names), names)
        self.assertTrue(any('ORA-01653' in n for n in names), names)
        self.assertTrue(any('LISTENER_DOWN' in n for n in names), names)
        self.assertTrue(any('ORA-12541' in n for n in names), names)
        self.assertTrue(any('STORAGE_FULL' in n for n in names), names)

    def test_trigger_resolution_maps_oracle_problems_to_hosts(self):
        from ops.zabbix_alert_bridge import resolve_problem_host
        from ops.zabbix_demo_data import dispatch_demo_call

        class DemoClient:
            def get_triggers(self, trigger_ids=None):
                return dispatch_demo_call('trigger.get', {'triggerids': trigger_ids})

        host, _, _ = resolve_problem_host(DemoClient(), {'objectid': '30003'})
        self.assertEqual(host, 'ORCL01')
        host, _, _ = resolve_problem_host(DemoClient(), {'objectid': '30002'})
        self.assertEqual(host, 'TS_ORDER')
        host, _, _ = resolve_problem_host(DemoClient(), {'objectid': '30005'})
        self.assertEqual(host, 'listener-01')
        host, _, _ = resolve_problem_host(DemoClient(), {'objectid': '30001'})
        self.assertEqual(host, 'lun-orders-01')

    def test_demo_problem_clock_deltas_within_window(self):
        from ops.zabbix_demo_data import DEMO_PROBLEMS

        oracle = [p for p in DEMO_PROBLEMS if any(
            code in p.get('name', '') for code in
            ['TABLESPACE_FULL', 'ORA-01653', 'STORAGE_FULL', 'LISTENER_DOWN', 'ORA-12541'])]
        self.assertEqual(len(oracle), 5)
        clocks = sorted(int(p['clock']) for p in oracle)
        self.assertLessEqual(clocks[-1] - clocks[0], 300, '演示告警时钟差应落在 ±5min 时间窗内')


    def test_summaries_include_causality_counts(self):
        from ops.alerting import alert_group_summary, alert_summary
        from ops.models import Alert

        root = Alert.objects.create(
            title='root', level='critical', status='active', source='t', source_type='generic',
            fingerprint='fp-root-01', alert_code='STORAGE_FULL', causal_level='root')
        Alert.objects.create(
            title='derived', level='warning', status='active', source='t', source_type='generic',
            fingerprint='fp-derived-01', alert_code='DB_WRITE_BLOCKED', causal_level='derived',
            derived_from=[root.id])

        summary = alert_summary(Alert.objects.all())
        self.assertEqual(summary['root'], 1)
        self.assertEqual(summary['derived'], 1)

        groups = alert_group_summary(Alert.objects.all())
        self.assertEqual(groups[0]['root'], 1)
        self.assertEqual(groups[0]['derived'], 1)
