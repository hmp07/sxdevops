import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rbac.models import PermissionDefinition, Role
from rbac.services import ensure_builtin_rbac
from ops.models import Host

from .models import CIType, CIRelation, ConfigItem, CostRecord, ResourceNode, ResourceRequest


class AuthenticatedTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser('cmdb-admin', 'cmdb@example.com', 'Admin@123456')
        self.client.force_login(self.user)


class CmdbCostAnalysisTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.current_month = timezone.now().strftime('%Y-%m')
        self.previous_month = (
            timezone.now().replace(day=1) - timezone.timedelta(days=1)
        ).strftime('%Y-%m')

        host_type = CIType.objects.create(name='Host')
        db_type = CIType.objects.create(name='Database')

        self.prod_ci = ConfigItem.objects.create(
            name='prod-db-01',
            ci_type=db_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'monthly_cost': 1200, 'cpu': 16, 'memory_gb': 32},
        )
        self.test_ci = ConfigItem.objects.create(
            name='test-host-01',
            ci_type=host_type,
            business_line='core',
            environment='test',
            status='active',
            attributes={'monthly_cost': 600, 'cpu': 8, 'memory_gb': 16},
        )
        self.idle_ci = ConfigItem.objects.create(
            name='idle-host-01',
            ci_type=host_type,
            business_line='shared',
            environment='prod',
            status='idle',
            attributes={'monthly_cost': 300, 'cpu': 4, 'memory_gb': 8},
        )
        CostRecord.objects.create(
            ci=self.prod_ci,
            month=self.previous_month,
            amount=Decimal('1000.00'),
            provider='history',
        )

    def test_cost_report_uses_current_month_fallbacks_without_writing_cost_records(self):
        response = self.client.get('/api/cmdb/cost/report/', {'month': self.current_month})

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['month'], self.current_month)
        self.assertEqual(payload['total_monthly_cost'], 2100.0)
        self.assertEqual(payload['top_cost_items'][0]['name'], 'prod-db-01')
        self.assertEqual(payload['by_business'][0]['business_line'], 'core')
        self.assertEqual(payload['by_business'][0]['total_cost'], 1800.0)
        self.assertEqual(payload['by_environment'][0]['environment'], 'prod')
        self.assertEqual(payload['total_potential_saving'], 870.0)
        self.assertEqual(payload['optimized_monthly_cost'], 1230.0)
        self.assertEqual(payload['optimization_preview']['suggestion_count'], 3)
        self.assertTrue(
            any(point['period'] == self.current_month for point in payload['cost_trend'])
        )
        self.assertEqual(
            CostRecord.objects.filter(month=self.current_month).count(),
            0,
        )

    def test_cost_report_supports_historical_months_without_resync(self):
        response = self.client.get('/api/cmdb/cost/report/', {'month': self.previous_month})

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['total_monthly_cost'], 1000.0)
        self.assertEqual(len(payload['top_cost_items']), 1)
        self.assertEqual(payload['top_cost_items'][0]['name'], 'prod-db-01')
        self.assertEqual(payload['optimization_preview']['suggestion_count'], 1)

    def test_optimization_returns_actionable_suggestions(self):
        response = self.client.get(
            '/api/cmdb/optimization/suggestions/',
            {'month': self.current_month},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['month'], self.current_month)
        self.assertGreaterEqual(payload['suggestion_count'], 3)
        self.assertGreater(payload['total_potential_saving'], 0)
        self.assertEqual(payload['optimized_monthly_cost'], 1230.0)
        self.assertAlmostEqual(payload['saving_rate'], 41.4)
        self.assertTrue(any(item['label'] for item in payload['by_type']))
        titles = [item['title'] for item in payload['suggestions']]
        self.assertTrue(any('prod-db-01' in title for title in titles))
        self.assertTrue(any('test-host-01' in title for title in titles))
        self.assertTrue(any('idle-host-01' in title for title in titles))

    def test_cost_endpoints_fallback_when_month_is_invalid(self):
        cost_response = self.client.get('/api/cmdb/cost/report/', {'month': '2026-13'})
        optimization_response = self.client.get('/api/cmdb/optimization/suggestions/', {'month': 'not-a-month'})

        self.assertEqual(cost_response.status_code, 200)
        self.assertEqual(optimization_response.status_code, 200)
        self.assertEqual(cost_response.json()['month'], self.current_month)
        self.assertEqual(optimization_response.json()['month'], self.current_month)

    def test_current_month_cost_endpoints_do_not_persist_cost_records(self):
        cost_response = self.client.get('/api/cmdb/cost/report/', {'month': self.current_month})
        optimization_response = self.client.get(
            '/api/cmdb/optimization/suggestions/',
            {'month': self.current_month},
        )

        self.assertEqual(cost_response.status_code, 200)
        self.assertEqual(optimization_response.status_code, 200)
        self.assertEqual(
            CostRecord.objects.filter(month=self.current_month).count(),
            0,
        )


class CmdbTopologyTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        app_type = CIType.objects.create(name='Application')
        host_type = CIType.objects.create(name='Host')

        self.core_prod = ConfigItem.objects.create(
            name='core-app-prod',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.0.10', 'monthly_cost': 500},
        )
        self.core_db = ConfigItem.objects.create(
            name='core-db-prod',
            ci_type=host_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.0.11', 'monthly_cost': 800},
        )
        self.shared_cache = ConfigItem.objects.create(
            name='shared-cache-prod',
            ci_type=host_type,
            business_line='shared',
            environment='prod',
            status='active',
            attributes={'ip_address': '10.0.1.10', 'monthly_cost': 300},
        )
        CIRelation.objects.create(
            source=self.core_prod,
            target=self.core_db,
            relation_type_id='depends_on',
            description='Primary dependency',
        )
        CIRelation.objects.create(
            source=self.core_prod,
            target=self.shared_cache,
            relation_type_id='connects_to',
            description='Cross business dependency',
        )

    def test_topology_scope_neighbors_keeps_cross_scope_neighbors(self):
        response = self.client.get(
            '/api/cmdb/topology/data/',
            {
                'business_line': 'core',
                'environment': 'prod',
                'scope': 'neighbors',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        node_names = {node['name'] for node in payload['nodes']}
        self.assertEqual(payload['meta']['scope'], 'neighbors')
        self.assertIn('core-app-prod', node_names)
        self.assertIn('core-db-prod', node_names)
        self.assertIn('shared-cache-prod', node_names)
        self.assertEqual(len(payload['meta']['matched_node_ids']), 2)
        self.assertTrue(any(edge['target_name'] == 'shared-cache-prod' for edge in payload['edges']))
        self.assertTrue(any(edge['type'] == 'connects_to' for edge in payload['edges']))

    def test_topology_scope_exact_only_returns_matching_nodes(self):
        response = self.client.get(
            '/api/cmdb/topology/data/',
            {
                'business_line': 'core',
                'environment': 'prod',
                'scope': 'exact',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        node_names = {node['name'] for node in payload['nodes']}
        self.assertEqual(payload['meta']['scope'], 'exact')
        self.assertEqual(node_names, {'core-app-prod', 'core-db-prod'})
        self.assertFalse(any(edge['target_name'] == 'shared-cache-prod' for edge in payload['edges']))


class CmdbRelationValidationTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        app_type = CIType.objects.create(name='Application')
        self.app_a = ConfigItem.objects.create(
            name='app-a',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
        )
        self.app_b = ConfigItem.objects.create(
            name='app-b',
            ci_type=app_type,
            business_line='core',
            environment='prod',
            status='active',
        )

    def test_relation_api_rejects_self_reference(self):
        response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_a.id,
                'relation_type': 'depends_on',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CIRelation.objects.count(), 0)

    def test_relation_api_rejects_duplicate_relation(self):
        response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_b.id,
                'relation_type': 'depends_on',
            },
        )
        self.assertEqual(response.status_code, 201)

        duplicate_response = self.client.post(
            '/api/cmdb/ci-relations/',
            {
                'source': self.app_a.id,
                'target': self.app_b.id,
                'relation_type': 'depends_on',
            },
        )

        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(CIRelation.objects.count(), 1)


class CmdbResourceRequestTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        core = ResourceNode.objects.create(name='core', node_type='biz')
        ResourceNode.objects.create(name='prod', node_type='env', parent=core)
        ResourceNode.objects.create(name='test', node_type='env', parent=core)

    def test_request_workflow_records_applicant_approver_and_completion(self):
        create_response = self.client.post(
            '/api/cmdb/resource-requests/',
            data=json.dumps({
                'title': 'Order service prod host expansion',
                'resource_type': 'host',
                'specification': '4C8G',
                'business_line': 'core',
                'environment': 'prod',
                'quantity': 1,
                'priority': 'high',
                'reason': 'Traffic increase requires one more node',
                'specs': {
                    'hostname': 'order-api-ecs-03',
                    'ip_address': '10.0.0.23',
                    'os_type': 'Alibaba Cloud Linux 3',
                    'admin_user': 'sre-core',
                    'instance_type': 'ecs.g7.xlarge',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(create_response.status_code, 201)
        request_id = create_response.json()['id']
        request_obj = ResourceRequest.objects.get(pk=request_id)
        self.assertEqual(request_obj.applicant, 'cmdb-admin')
        self.assertEqual(request_obj.status, 'pending')

        approve_response = self.client.post(
            f'/api/cmdb/resource-requests/{request_id}/approve/',
            {'comment': 'capacity approved'},
        )
        self.assertEqual(approve_response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, 'approved')
        self.assertEqual(request_obj.approver, 'cmdb-admin')
        self.assertEqual(request_obj.approval_comment, 'capacity approved')
        self.assertIsNotNone(request_obj.approved_at)

        complete_response = self.client.post(
            f'/api/cmdb/resource-requests/{request_id}/complete/',
            {'note': 'host provisioned and synced'},
        )
        self.assertEqual(complete_response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, 'completed')
        self.assertEqual(request_obj.fulfillment_note, 'host provisioned and synced')
        self.assertIsNotNone(request_obj.completed_at)

        host = Host.objects.get(hostname='order-api-ecs-03')
        self.assertEqual(host.ip_address, '10.0.0.23')
        self.assertEqual(host.business_line, 'core')
        self.assertEqual(host.environment, 'prod')
        self.assertEqual(host.admin_user, 'sre-core')
        self.assertEqual(host.status, 'online')

        ci = ConfigItem.objects.get(name='order-api-ecs-03')
        self.assertIn('ECS', ci.ci_type.name)
        self.assertEqual(ci.business_line, 'core')
        self.assertEqual(ci.environment, 'prod')
        self.assertEqual(ci.admin_user, 'sre-core')
        self.assertEqual(ci.status, 'active')
        self.assertEqual(ci.attributes['ip_address'], '10.0.0.23')
        self.assertEqual(ci.attributes['os_type'], 'Alibaba Cloud Linux 3')
        self.assertEqual(ci.attributes['instance_type'], 'ecs.g7.xlarge')
        self.assertEqual(ci.attributes['source'], 'host_request')
        self.assertEqual(ci.attributes['request_id'], request_id)

    def test_complete_requires_hostname_and_ip(self):
        request_obj = ResourceRequest.objects.create(
            title='Host request without delivery target',
            applicant='cmdb-admin',
            approver='cmdb-admin',
            resource_type='host',
            specification='2C4G',
            business_line='core',
            environment='prod',
            priority='medium',
            quantity=1,
            status='approved',
            reason='missing delivery info',
            specs={'os_type': 'Linux'},
            approved_at=timezone.now(),
        )

        response = self.client.post(
            f'/api/cmdb/resource-requests/{request_obj.id}/complete/',
            {'note': 'try to fulfill'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.json())
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, 'approved')
        self.assertEqual(Host.objects.count(), 0)

    def test_submitter_only_sees_own_requests(self):
        ensure_builtin_rbac()
        submit_permission = PermissionDefinition.objects.get(code='cmdb.request.submit')
        role = Role.objects.create(code='request-submit-only', name='Request Submit Only')
        role.permissions.add(submit_permission)

        submitter = get_user_model().objects.create_user('submitter', 'submitter@example.com', 'Admin@123456')
        role.users.add(submitter)

        ResourceRequest.objects.create(
            title='鎴戠殑鐢宠',
            applicant='submitter',
            resource_type='涓绘満',
            business_line='core',
            environment='prod',
            reason='self',
        )
        ResourceRequest.objects.create(
            title='someone else request',
            applicant='someone-else',
            resource_type='Redis',
            business_line='core',
            environment='test',
            reason='other',
        )

        self.client.force_login(submitter)
        response = self.client.get('/api/cmdb/resource-requests/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rows = payload['results'] if 'results' in payload else payload
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['applicant'], 'submitter')

    def test_request_api_only_accepts_host_resource_type(self):
        response = self.client.post(
            '/api/cmdb/resource-requests/',
            {
                'title': '鐢宠 Redis',
                'resource_type': 'Redis',
                'business_line': 'core',
                'environment': 'prod',
                'reason': 'not allowed',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('resource_type', response.json())


class CmdbSearchAndSyncTests(AuthenticatedTestCase):
    def test_ci_type_list_hides_alias_rows(self):
        CIType.objects.create(name='云主机(ECS)', color='#64748b')
        CIType.objects.create(name='云主机', color='#64748b')
        CIType.objects.create(name='K8s 集群', color='#0ea5e9')
        CIType.objects.create(name='K8s集群', color='#0ea5e9')

        response = self.client.get('/api/cmdb/ci-types/')
        self.assertEqual(response.status_code, 200)

        names = [item['name'] for item in response.json()]
        self.assertEqual(names.count('云主机(ECS)'), 1)
        self.assertEqual(names.count('K8s 集群'), 1)
        self.assertNotIn('云主机', names)
        self.assertNotIn('K8s集群', names)

    def test_config_item_api_search_supports_ip_and_ci_type_name(self):
        ci_type = CIType.objects.create(name='云主机(ECS)')
        ConfigItem.objects.create(
            name='order-api-ecs-01',
            ci_type=ci_type,
            business_line='core',
            environment='prod',
            admin_user='sre-core',
            status='active',
            attributes={
                'ip_address': '10.10.1.10',
                'description': '订单服务生产主机',
                'instance_type': 'ecs.g7.large',
            },
        )

        response = self.client.get('/api/cmdb/config-items/', {'search': '10.10.1.10'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

        response = self.client.get('/api/cmdb/config-items/', {'search': '云主机'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

    def test_config_item_api_fills_standard_ip_from_private_ip(self):
        ci_type = CIType.objects.create(name='云数据库')
        ConfigItem.objects.create(
            name='shared-rds-01',
            ci_type=ci_type,
            business_line='core',
            environment='prod',
            status='active',
            attributes={'private_ip': '10.20.2.20'},
        )

        response = self.client.get('/api/cmdb/config-items/', {'search': '10.20.2.20'})
        self.assertEqual(response.status_code, 200)
        row = response.json()['results'][0]
        self.assertEqual(row['attributes']['ip_address'], '10.20.2.20')

    def test_host_create_update_delete_syncs_to_cmdb(self):
        host = Host.objects.create(
            hostname='sync-host-01',
            ip_address='10.0.0.21',
            business_line='core',
            environment='prod',
            admin_user='ops-admin',
            os_type='Linux',
            description='由主机中心创建',
            status='online',
        )

        ci = ConfigItem.objects.get(name='sync-host-01')
        self.assertEqual(ci.attributes['ip_address'], '10.0.0.21')
        self.assertEqual(ci.business_line, 'core')
        self.assertEqual(ci.status, 'active')
        self.assertIn('ECS', ci.ci_type.name)

        host.ip_address = '10.0.0.22'
        host.description = '由主机中心更新'
        host.status = 'offline'
        host.save()

        ci.refresh_from_db()
        self.assertEqual(ci.attributes['ip_address'], '10.0.0.22')
        self.assertEqual(ci.attributes['description'], '由主机中心更新')
        self.assertEqual(ci.status, 'offline')

        host.delete()
        self.assertFalse(ConfigItem.objects.filter(name='sync-host-01').exists())

    def test_host_like_config_item_syncs_back_to_host(self):
        ci_type = CIType.objects.create(name='云主机(ECS)')
        ci = ConfigItem.objects.create(
            name='cmdb-host-01',
            ci_type=ci_type,
            business_line='retail',
            environment='test',
            admin_user='cmdb-owner',
            status='active',
            attributes={
                'ip_address': '10.0.1.15',
                'os_type': 'Alibaba Cloud Linux 3',
                'description': '由 CMDB 创建',
            },
        )

        host = Host.objects.get(hostname='cmdb-host-01')
        self.assertEqual(host.ip_address, '10.0.1.15')
        self.assertEqual(host.business_line, 'retail')
        self.assertEqual(host.environment, 'test')
        self.assertEqual(host.status, 'online')

        ci.status = 'offline'
        ci.attributes['description'] = '由 CMDB 更新'
        ci.save()

        host.refresh_from_db()
        self.assertEqual(host.status, 'offline')
        self.assertEqual(host.description, '由 CMDB 更新')

    def test_stats_merge_garbled_ci_type_names(self):
        good_type = CIType.objects.create(name='应用服务', color='#3b82f6')
        bad_type = CIType.objects.create(name='搴旂敤鏈嶅姟', color='#3b82f6')
        cloud_type = CIType.objects.create(name='云主机(ECS)', color='#64748b')
        cloud_alias_type = CIType.objects.create(name='云主机', color='#64748b')
        k8s_type = CIType.objects.create(name='K8s 集群', color='#0ea5e9')
        k8s_alias_type = CIType.objects.create(name='K8s集群', color='#0ea5e9')
        ConfigItem.objects.create(name='app-a', ci_type=good_type, status='active')
        ConfigItem.objects.create(name='app-b', ci_type=bad_type, status='active')
        ConfigItem.objects.create(name='host-a', ci_type=cloud_type, status='active')
        ConfigItem.objects.create(name='host-b', ci_type=cloud_alias_type, status='active')
        ConfigItem.objects.create(name='cluster-a', ci_type=k8s_type, status='active')
        ConfigItem.objects.create(name='cluster-b', ci_type=k8s_alias_type, status='active')

        response = self.client.get('/api/cmdb/config-items/stats/')
        self.assertEqual(response.status_code, 200)

        by_type = response.json()['by_type']
        app_entry = next(item for item in by_type if item['ci_type__name'] == '应用服务')
        host_entry = next(item for item in by_type if item['ci_type__name'] == '云主机(ECS)')
        k8s_entry = next(item for item in by_type if item['ci_type__name'] == 'K8s 集群')
        self.assertEqual(app_entry['count'], 2)
        self.assertEqual(host_entry['count'], 2)
        self.assertEqual(k8s_entry['count'], 2)




class iTopDataSourceAsyncTests(AuthenticatedTestCase):
    """iTop 数据源保存异步化：连接测试门禁 + 后台同步线程 + 完成通知。"""

    def _post_create(self, **overrides):
        payload = {
            'name': 'itop-prod',
            'api_url': 'http://itop.example.com/webservices/rest.php',
            'api_version': '1.4',
            'auth_user': 'admin',
            'auth_password': 'secret',
            'organization': 'demo',
        }
        payload.update(overrides)
        return self.client.post('/api/cmdb/itop/datasources/', payload, format='json')

    def test_create_rejects_when_connection_fails(self):
        from unittest.mock import patch

        from .models import iTopDataSource

        with patch('cmdb.itop_views.test_connection', return_value=False):
            response = self._post_create()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(iTopDataSource.objects.count(), 0, '连接失败不落库')

    def test_create_saves_and_starts_sync_thread(self):
        from unittest.mock import patch

        from .models import iTopDataSource

        with patch('cmdb.itop_views.test_connection', return_value=True), \
             patch('cmdb.itop_views._start_sync_thread', return_value=True) as start_mock:
            response = self._post_create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(iTopDataSource.objects.count(), 1)
        start_mock.assert_called_once_with(iTopDataSource.objects.get().id)

    def test_trigger_sync_running_conflict(self):
        from unittest.mock import patch

        from .models import iTopDataSource

        with patch('cmdb.itop_views.test_connection', return_value=True), \
             patch('cmdb.itop_views._start_sync_thread', return_value=True):
            self._post_create()
        ds = iTopDataSource.objects.get()
        ds.sync_status = 'running'
        ds.save(update_fields=['sync_status'])
        response = self.client.post(f'/api/cmdb/itop/datasources/{ds.id}/trigger_sync/')
        self.assertEqual(response.status_code, 409)

    def test_trigger_sync_starts_thread_returns_202(self):
        from unittest.mock import patch

        from .models import iTopDataSource

        with patch('cmdb.itop_views.test_connection', return_value=True), \
             patch('cmdb.itop_views._start_sync_thread', return_value=True):
            self._post_create()
        ds = iTopDataSource.objects.get()
        with patch('cmdb.itop_views._start_sync_thread', return_value=True) as start_mock:
            response = self.client.post(f'/api/cmdb/itop/datasources/{ds.id}/trigger_sync/')
        self.assertEqual(response.status_code, 202)
        start_mock.assert_called_once_with(ds.id)

    def test_worker_success_writes_wall_event_and_notification(self):
        from unittest.mock import patch

        from eventwall.models import EventRecord

        from .itop_views import _sync_worker
        from .models import iTopDataSource

        ds = iTopDataSource.objects.create(name='itop-worker', api_url='http://x/rest.php',
                                           auth_user='u', auth_password='p')

        def fake_sync(ds_obj):
            ds_obj.sync_status = 'ok'
            ds_obj.save(update_fields=['sync_status'])

        with patch('cmdb.itop_views.run_full_sync', side_effect=fake_sync), \
             patch('cmdb.itop_views.push_background_job_notification') as notify_mock:
            _sync_worker(ds.id)
        event = EventRecord.objects.filter(action='itop_sync_finish').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.result, EventRecord.RESULT_SUCCESS)
        self.assertEqual(event.metadata.get('event_category'), 'config_change')
        notify_mock.assert_called_once()
        self.assertEqual(notify_mock.call_args.args[0], 'itop_sync')
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs['level'], 'success')
        self.assertEqual(kwargs['job_id'], ds.id)

    def test_worker_failure_level_error(self):
        from unittest.mock import patch

        from eventwall.models import EventRecord

        from .itop_views import _sync_worker
        from .models import iTopDataSource

        ds = iTopDataSource.objects.create(name='itop-worker-fail', api_url='http://x/rest.php',
                                           auth_user='u', auth_password='p')
        with patch('cmdb.itop_views.run_full_sync', side_effect=Exception('boom')), \
             patch('cmdb.itop_views.push_background_job_notification') as notify_mock:
            _sync_worker(ds.id)
        self.assertEqual(notify_mock.call_args.kwargs['level'], 'error')
        event = EventRecord.objects.filter(action='itop_sync_finish').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.result, EventRecord.RESULT_FAILED)

    def test_sync_status_accepts_long_error(self):
        # 迁移 0008 将 sync_status 扩至 255；SQLite 不强制长度，本用例作为 MySQL 生产的回归护栏
        from .models import iTopDataSource

        ds = iTopDataSource.objects.create(name='itop-long-status', api_url='http://x/rest.php',
                                           auth_user='u', auth_password='p')
        ds.sync_status = 'error: ' + 'x' * 150
        ds.save()
        ds.refresh_from_db()
        self.assertIn('error:', ds.sync_status)


class CITypeHierarchyTests(AuthenticatedTestCase):
    """CIType 层级扩展（parent/layer/is_abstract）的模型、序列化与 API 行为。"""

    def test_layer_defaults_to_zero_and_fields_serialized(self):
        host_type = CIType.objects.create(name='Host')
        self.assertEqual(host_type.layer, 0)
        self.assertFalse(host_type.is_abstract)
        self.assertIsNone(host_type.parent_id)

        payload = self.client.get('/api/cmdb/ci-types/').json()
        row = next(item for item in payload if item['name'] == 'Host')
        self.assertIn('layer', row)
        self.assertIn('is_abstract', row)
        self.assertIn('parent', row)
        self.assertEqual(row['layer'], 0)

    def test_parent_child_saved(self):
        infra = CIType.objects.create(name='InfraResource', is_abstract=True, layer=0)
        host = CIType.objects.create(name='Host', parent=infra, layer=1)
        host.refresh_from_db()
        self.assertEqual(host.parent_id, infra.id)
        self.assertEqual(host.layer, 1)
        self.assertTrue(infra.is_abstract)

    def test_tree_action_returns_hierarchy(self):
        infra = CIType.objects.create(name='InfraResource', is_abstract=True)
        CIType.objects.create(name='Host', parent=infra, layer=1)
        response = self.client.get('/api/cmdb/ci-types/tree/')
        self.assertEqual(response.status_code, 200)
        tree = response.json()
        infra_node = next(node for node in tree if node['name'] == 'InfraResource')
        self.assertTrue(infra_node.get('children'), '抽象父类型应包含子类型节点')
        child = infra_node['children'][0]
        self.assertEqual(child['name'], 'Host')

    def test_list_alias_merge_preserves_hierarchy(self):
        parent = CIType.objects.create(name='InfraResource', is_abstract=True)
        CIType.objects.create(name='云主机(ECS)', parent=parent, layer=1)
        CIType.objects.create(name='云主机', parent=parent, layer=1)

        payload = self.client.get('/api/cmdb/ci-types/').json()
        row = next(item for item in payload if item['name'] == '云主机(ECS)')
        self.assertEqual(row['layer'], 1)
        self.assertEqual(row['parent'], parent.id)
        self.assertFalse(row['is_abstract'])


class RelationTypeRegistryTests(AuthenticatedTestCase):
    """RelationType 关系类型注册表：迁移种入、模型约束与 API 行为。"""

    def test_default_types_seeded_by_migration(self):
        from .models import RelationType

        codes = set(RelationType.objects.values_list('code', flat=True))
        for code in ['depends_on', 'runs_on', 'connects_to', 'hosted_on', 'contains']:
            self.assertIn(code, codes)

        depends = RelationType.objects.get(code='depends_on')
        self.assertTrue(depends.is_system)
        self.assertEqual(depends.color, '#8b5cf6')
        self.assertEqual(depends.line_style, 'solid')
        self.assertEqual(depends.ontology_property, 'dependsOn')
        self.assertEqual(depends.direction, 'forward')

    def test_seed_is_idempotent(self):
        from .models import RelationType
        from cmdb.models import seed_default_relation_types

        before = RelationType.objects.count()
        seed_default_relation_types()
        seed_default_relation_types()
        self.assertEqual(RelationType.objects.count(), before)

    def test_code_is_unique(self):
        from .models import RelationType
        from django.db import IntegrityError

        RelationType.objects.create(code='dup_x', name='重复类型')
        with self.assertRaises(IntegrityError):
            RelationType.objects.create(code='dup_x', name='重复类型2')

    def test_api_list_returns_registry_metadata(self):
        response = self.client.get('/api/cmdb/ci-relation-types/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        codes = {item['code'] for item in payload}
        self.assertIn('depends_on', codes)
        self.assertIn('contains', codes)
        row = next(item for item in payload if item['code'] == 'contains')
        self.assertEqual(row['display_name'], '包含')
        self.assertEqual(row['ontology_property'], 'contains')


class CIRelationRelationTypeFkTests(AuthenticatedTestCase):
    """CIRelation 关系类型 FK 化：code 字符串往返、类型约束、attributes、拓扑边元数据。"""

    def setUp(self):
        super().setUp()
        from .models import RelationType

        self.host_type = CIType.objects.create(name='Host')
        self.db_type = CIType.objects.create(name='Database')
        self.source_ci = ConfigItem.objects.create(name='app-01', ci_type=self.db_type)
        self.target_ci = ConfigItem.objects.create(name='host-01', ci_type=self.host_type)
        RelationType.objects.get_or_create(
            code='custom_link', defaults={
                'name': '自定义关联', 'display_name': '自定义关联',
                'allowed_source_types': ['Database'], 'allowed_target_types': ['Host'],
                'ontology_property': 'customLink',
            },
        )

    def test_api_relation_type_code_roundtrip(self):
        response = self.client.post('/api/cmdb/ci-relations/',
                                    json.dumps({
                                        'source': self.source_ci.id, 'target': self.target_ci.id,
                                        'relation_type': 'depends_on', 'description': 'API 创建',
                                    }), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['relation_type'], 'depends_on')

        payload = self.client.get('/api/cmdb/ci-relations/').json()
        self.assertEqual(payload['results'][0]['relation_type'], 'depends_on')

    def test_attributes_field_saved(self):
        response = self.client.post('/api/cmdb/ci-relations/',
                                    json.dumps({
                                        'source': self.source_ci.id, 'target': self.target_ci.id,
                                        'relation_type': 'depends_on', 'attributes': {'itop_raw': 'x'},
                                    }), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['attributes'], {'itop_raw': 'x'})

    def test_type_constraint_matrix(self):
        # custom_link 仅允许 Database→Host
        ok = self.client.post('/api/cmdb/ci-relations/',
                              json.dumps({
                                  'source': self.source_ci.id, 'target': self.target_ci.id,
                                  'relation_type': 'custom_link',
                              }), content_type='application/json')
        self.assertEqual(ok.status_code, 201, ok.content)

        bad_source = ConfigItem.objects.create(name='host-02', ci_type=self.host_type)
        bad = self.client.post('/api/cmdb/ci-relations/',
                               json.dumps({
                                   'source': bad_source.id, 'target': self.target_ci.id,
                                   'relation_type': 'custom_link',
                               }), content_type='application/json')
        self.assertEqual(bad.status_code, 400, bad.content)

    def test_self_loop_rejected(self):
        response = self.client.post('/api/cmdb/ci-relations/',
                                    json.dumps({
                                        'source': self.source_ci.id, 'target': self.source_ci.id,
                                        'relation_type': 'depends_on',
                                    }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_topology_edge_carries_relation_type_metadata(self):
        from .models import RelationType

        RelationType.objects.filter(code='depends_on').update(
            color='#8b5cf6', line_style='solid', direction='forward', ontology_property='dependsOn',
        )
        CIRelation.objects.create(source=self.source_ci, target=self.target_ci, relation_type_id='depends_on')

        response = self.client.get('/api/cmdb/topology/data/', {'scope': 'exact', 'environment': 'prod'})
        self.assertEqual(response.status_code, 200)
        edge = response.json()['edges'][0]
        self.assertEqual(edge['type'], 'depends_on')
        self.assertEqual(edge['relation_code'], 'depends_on')
        self.assertEqual(edge['color'], '#8b5cf6')
        self.assertEqual(edge['line_style'], 'solid')
        self.assertEqual(edge['direction'], 'forward')
        self.assertEqual(edge['ontology_property'], 'dependsOn')


class OracleCITypeSeedTests(TestCase):
    """Oracle 域自定义 CI 类型种子：幂等、分层约定、别名安全。"""

    def test_seed_idempotent(self):
        from cmdb.oracle_demo_seed import ORACLE_CI_TYPES, seed_oracle_ci_types

        seed_oracle_ci_types()
        count1 = CIType.objects.count()
        seed_oracle_ci_types()
        self.assertEqual(CIType.objects.count(), count1)

        names = {entry['name'] for entry in ORACLE_CI_TYPES}
        created = set(CIType.objects.filter(name__in=names).values_list('name', flat=True))
        self.assertEqual(created, names)

    def test_layer_conventions(self):
        from cmdb.oracle_demo_seed import seed_oracle_ci_types

        seed_oracle_ci_types()
        self.assertEqual(CIType.objects.get(name='存储系统').layer, 0)
        self.assertEqual(CIType.objects.get(name='Oracle实例').layer, 2)
        self.assertEqual(CIType.objects.get(name='表空间').layer, 3)
        self.assertEqual(CIType.objects.get(name='数据文件').layer, 4)
        self.assertEqual(CIType.objects.get(name='归档日志').layer, 4)

    def test_names_survive_alias_normalization(self):
        from cmdb.oracle_demo_seed import seed_oracle_ci_types
        from cmdb.sync import is_placeholder_ci_type_name, normalize_ci_type_name

        seed_oracle_ci_types()
        for name in ['存储系统', '存储卷', 'Oracle监听', 'Oracle实例', '表空间', '数据文件', '归档日志']:
            self.assertEqual(normalize_ci_type_name(name), name)
            self.assertFalse(is_placeholder_ci_type_name(name))


class iTopRelationSyncTests(TestCase):
    """itop_sync.sync_relations 引擎级测试（mock _call_itop_api）。"""

    def setUp(self):
        from unittest import mock
        from cmdb.itop_sync import sync_relations

        self.mock = mock
        self.sync_relations = sync_relations
        self.server_type = CIType.objects.create(name='Server')
        self.app_type = CIType.objects.create(name='ApplicationSolution')
        self.group_type = CIType.objects.create(name='Group')
        self.ds = None
        # iTopDataSource 需要密码字段，直接建
        from .models import iTopDataSource
        self.ds = iTopDataSource.objects.create(
            name='itop-rel-test', api_url='http://itop.example/rest.php',
            auth_user='u', auth_password='p',
            config={'ci_class_map': {'Server': 'Server', 'ApplicationSolution': 'ApplicationSolution',
                                     'Group': 'Group'}},
        )
        self.server1 = ConfigItem.objects.create(
            name='srv-1', ci_type=self.server_type, external_id='itop:Server:1', itop_datasource=self.ds)
        self.server2 = ConfigItem.objects.create(
            name='srv-2', ci_type=self.server_type, external_id='itop:Server:2', itop_datasource=self.ds)
        self.group1 = ConfigItem.objects.create(
            name='grp-1', ci_type=self.group_type, external_id='itop:Group:1', itop_datasource=self.ds)

    def _mock_itop(self, relation_returns):
        """core/get 返回 Server::1；core/get_related 按 relation 名返回给定结果。"""
        import json

        def side_effect(ds, payload):
            data = json.loads(payload)
            op = data.get('operation')
            if op == 'core/get_related':
                rel_name = data.get('relation')
                payload_direction = data.get('direction')
                return {'code': 0, 'relations': relation_returns.get(
                    (rel_name, payload_direction), {})}
            if op == 'core/get':
                return {'code': 0, 'objects': {'Server::1': {'key': '1'}}}
            return {'code': 1, 'message': 'unexpected op'}

        patch = self.mock.patch('cmdb.itop_sync._call_itop_api', side_effect=side_effect)
        patch.start()
        self.addCleanup(patch.stop)
        return side_effect

    def test_lnk_relation_mapped_to_registry_code(self):
        self._mock_itop({('impacts', 'down'): {'Server::1': [{'key': 'Server::2'}]}})
        self.ds.config['ci_classes'] = ['Server']
        self.ds.config['relation_types'] = ['impacts']
        self.ds.save()

        stats = self.sync_relations(self.ds)
        self.assertEqual(stats['created'], 1)
        rel = CIRelation.objects.get(source=self.server1, target=self.server2)
        self.assertEqual(rel.relation_type_id, 'depends_on')

    def test_dict_config_direction_up_swaps_source_target(self):
        self._mock_itop({('impacts', 'up'): {'Server::1': [{'key': 'Server::2'}]}})
        self.ds.config['ci_classes'] = ['Server']
        self.ds.config['relation_types'] = {'impacts': {'code': 'depends_on', 'direction': 'up'}}
        self.ds.save()

        self.sync_relations(self.ds)
        rel = CIRelation.objects.get(source=self.server2, target=self.server1)
        self.assertEqual(rel.relation_type_id, 'depends_on')

    def test_attributes_mode_writes_owner_attribute(self):
        self._mock_itop({('lnkGroupToCI', 'down'): {'Server::1': [{'key': 'Group::1'}]}})
        self.ds.config['ci_classes'] = ['Server']
        self.ds.config['relation_types'] = {'lnkGroupToCI': {
            'code': 'depends_on', 'direction': 'down', 'mode': 'attributes', 'attribute': 'owner_group',
        }}
        self.ds.save()

        self.sync_relations(self.ds)
        self.assertFalse(CIRelation.objects.filter(source=self.server1).exists())
        self.server1.refresh_from_db()
        self.assertIn('Group::1', self.server1.attributes.get('owner_group', []))

    def test_cleanup_disabled_by_default_and_enabled_removes_stale(self):
        stale = CIRelation.objects.create(
            source=self.server1, target=self.server2, relation_type_id='depends_on')
        self._mock_itop({('impacts', 'down'): {}})
        self.ds.config['ci_classes'] = ['Server']
        self.ds.config['relation_types'] = ['impacts']
        self.ds.save()

        # 默认不清理：iTop 已消失的关系保留
        self.sync_relations(self.ds)
        self.assertTrue(CIRelation.objects.filter(id=stale.id).exists())

        # 开启清理：消失关系被删除并计数
        self.ds.config['relation_cleanup'] = True
        self.ds.save()
        stats = self.sync_relations(self.ds)
        self.assertFalse(CIRelation.objects.filter(id=stale.id).exists())
        self.assertEqual(stats['removed'], 1)

    def test_relation_map_covers_all_lnk_classes(self):
        from cmdb.itop_sync import ITOP_LNK_CLASSES, ITOP_RELATION_MAP

        self.assertEqual(len(ITOP_LNK_CLASSES), 13)
        missing = set(ITOP_LNK_CLASSES) - set(ITOP_RELATION_MAP.keys())
        self.assertFalse(missing, f'映射表缺少: {missing}')
