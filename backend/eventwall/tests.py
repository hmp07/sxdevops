from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import EventRecord, EventSource
from .views import _ensure_default_event_sources


class EventSourceTests(TestCase):
    def test_default_event_sources_include_builtin_and_external_sources(self):
        _ensure_default_event_sources()

        self.assertEqual(EventSource.objects.count(), 8)
        self.assertTrue(EventSource.objects.filter(code='builtin-workorder', source_kind=EventSource.KIND_BUILTIN).exists())
        self.assertTrue(EventSource.objects.filter(code='builtin-task-center', source_kind=EventSource.KIND_BUILTIN).exists())
        self.assertTrue(EventSource.objects.filter(code='builtin-k8s', source_kind=EventSource.KIND_BUILTIN).exists())
        self.assertTrue(EventSource.objects.filter(code='jira', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='jenkins', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='argocd', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='gitlab', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='custom', source_kind=EventSource.KIND_EXTERNAL).exists())

    def test_external_ingest_records_event_with_source_metadata(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {
                'event_id': 'unit-001',
                'title': '自研系统变更事件',
                'summary': '自研系统推送变更事件',
                'result': EventRecord.RESULT_SUCCESS,
                'severity': EventRecord.SEVERITY_INFO,
                'application': 'payment-api',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__event_source_code='custom', metadata__external_event_id='unit-001')
        self.assertEqual(event.title, '自研系统变更事件')
        self.assertEqual(event.source_type, EventRecord.SOURCE_EXTERNAL)
        self.assertEqual(event.application, 'payment-api')

    def test_analysis_wall_groups_events_by_source_and_returns_suspects(self):
        user = get_user_model().objects.create_superuser(username='analysis-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now - timedelta(minutes=20),
            module='ops',
            category='execution',
            action='deploy',
            result=EventRecord.RESULT_FAILED,
            severity=EventRecord.SEVERITY_DANGER,
            title='发布失败',
            summary='payment-api 发布失败',
            resource_type='deployment',
            resource_id='1',
            resource_name='payment-api',
            business_line='trade',
            environment='prod',
            application='payment-api',
            correlation_id='payment-api:deploy:1',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/analysis_wall/', {'fault_at': now.isoformat(), 'lookback_minutes': 60, 'after_minutes': 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['total'], 1)
        self.assertEqual(response.data['summary']['suspects'], 1)
        self.assertEqual(response.data['summary']['scope_count'], 1)
        self.assertEqual(response.data['affected_scopes'][0]['application'], 'payment-api')
        self.assertEqual(response.data['lanes'][0]['source']['code'], 'builtin-workorder')
        self.assertEqual(response.data['suspects'][0]['title'], '发布失败')
        self.assertTrue(response.data['recommendations'])

    def test_operation_audit_excludes_external_ingest_events(self):
        user = get_user_model().objects.create_superuser(username='audit-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now,
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='更新用户',
            resource_type='user',
            resource_id='1',
            source_type=EventRecord.SOURCE_HTTP,
        )
        EventRecord.objects.create(
            occurred_at=now,
            module='eventwall',
            category='external_event',
            action='ingest',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='外部流水线事件',
            source_type=EventRecord.SOURCE_EXTERNAL,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/operation_audit/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], '更新用户')

    def test_prune_operation_audit_deletes_records_before_cutoff_only(self):
        user = get_user_model().objects.create_superuser(username='audit-cleaner', password='pass')
        now = timezone.now()
        old_event = EventRecord.objects.create(
            occurred_at=now - timedelta(days=10),
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='旧操作',
            source_type=EventRecord.SOURCE_HTTP,
        )
        recent_event = EventRecord.objects.create(
            occurred_at=now - timedelta(hours=1),
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='新操作',
            source_type=EventRecord.SOURCE_HTTP,
        )
        external_event = EventRecord.objects.create(
            occurred_at=now - timedelta(days=10),
            module='eventwall',
            category='external_event',
            action='ingest',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='外部事件',
            source_type=EventRecord.SOURCE_EXTERNAL,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post('/api/events/prune_operation_audit/', {'before_at': (now - timedelta(days=1)).isoformat()}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['deleted'], 1)
        self.assertFalse(EventRecord.objects.filter(id=old_event.id).exists())
        self.assertTrue(EventRecord.objects.filter(id=recent_event.id).exists())
        self.assertTrue(EventRecord.objects.filter(id=external_event.id).exists())
