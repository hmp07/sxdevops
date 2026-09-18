from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PermissionDefinition, Role, UserGroup
from .services import DEMO_ACCOUNT_MUTATION_MESSAGE, ensure_builtin_rbac, get_user_effective_permissions


User = get_user_model()


class RbacPermissionTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.dashboard_permission = PermissionDefinition.objects.get(code='ops.dashboard.view')
        self.user_view_permission = PermissionDefinition.objects.get(code='rbac.user.view')

    def test_group_role_grants_effective_permission(self):
        role = Role.objects.create(code='dashboard-viewer', name='Dashboard Viewer')
        role.permissions.add(self.dashboard_permission)
        group = UserGroup.objects.create(code='observers', name='Observers')
        group.roles.add(role)

        user = User.objects.create_user(username='observer', password='Admin@123456')
        group.users.add(user)
        self.client.force_login(user)

        response = self.client.get('/api/dashboard/stats/')
        self.assertEqual(response.status_code, 200)

        denied = self.client.get('/api/hosts/')
        self.assertEqual(denied.status_code, 403)

    def test_view_only_user_cannot_create_users(self):
        role = Role.objects.create(code='user-auditor', name='User Auditor')
        role.permissions.add(self.user_view_permission)

        user = User.objects.create_user(username='auditor', password='Admin@123456')
        role.users.add(user)
        self.client.force_login(user)

        list_response = self.client.get('/api/users/')
        self.assertEqual(list_response.status_code, 200)

        create_response = self.client.post(
            '/api/users/',
            {
                'username': 'blocked-user',
                'password': 'Admin@123456',
                'email': 'blocked@example.com',
            },
        )
        self.assertEqual(create_response.status_code, 403)

    def test_demo_account_has_full_permissions(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        permissions = get_user_effective_permissions(demo_user)

        self.assertIn('rbac.user.manage', permissions)
        self.assertIn('ops.k8s.manage', permissions)
        self.assertIn('ops.deployment.manage', permissions)

    def test_demo_account_cannot_create_users(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        self.client.force_login(demo_user)

        response = self.client.post(
            '/api/users/',
            {
                'username': 'blocked-demo-created-user',
                'password': 'Admin@123456',
                'email': 'blocked-demo-created-user@example.com',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], DEMO_ACCOUNT_MUTATION_MESSAGE)

    def test_demo_account_cannot_call_custom_write_action(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        target_user = User.objects.create_user(username='reset-target', password='Admin@123456')
        self.client.force_login(demo_user)

        response = self.client.post(
            f'/api/users/{target_user.id}/reset_password/',
            {'password': 'Admin@654321'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], DEMO_ACCOUNT_MUTATION_MESSAGE)


class RbacSecurityHardeningTests(TestCase):
    """安全加固回归：未认证端点、垂直提权防护、登录锁定。"""

    def setUp(self):
        ensure_builtin_rbac()
        manage_perm = PermissionDefinition.objects.get(code='rbac.user.manage')
        self.escalating_role = Role.objects.create(code='user-manager', name='User Manager')
        self.escalating_role.permissions.add(manage_perm)

    def _make_manager(self, username):
        manager = User.objects.create_user(username=username, password='Admin@123456')
        self.escalating_role.users.add(manager)
        return manager

    def test_dashboard_stats_requires_authentication(self):
        response = self.client.get('/api/dashboard/stats/')
        self.assertEqual(response.status_code, 401)

    def test_non_superuser_cannot_set_superuser_flags(self):
        manager = self._make_manager('manager-flag')
        self.client.force_login(manager)
        response = self.client.patch(
            f'/api/users/{manager.id}/',
            {'is_superuser': True},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        manager.refresh_from_db()
        self.assertFalse(manager.is_superuser)

    def test_non_superuser_cannot_assign_platform_admin_role(self):
        manager = self._make_manager('manager-role')
        self.client.force_login(manager)
        platform_admin = Role.objects.get(code='platform-admin')
        response = self.client.patch(
            f'/api/users/{manager.id}/',
            {'role_ids': [platform_admin.id]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_non_superuser_cannot_reset_superuser_password(self):
        manager = self._make_manager('manager-reset')
        superuser = User.objects.create_superuser(username='root-admin', password='Admin@123456')
        self.client.force_login(manager)
        response = self.client.post(
            f'/api/users/{superuser.id}/reset_password/',
            {'password': 'Admin@654321'},
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_still_manage_flags(self):
        superuser = User.objects.create_superuser(username='root-admin2', password='Admin@123456')
        target = User.objects.create_user(username='promote-target', password='Admin@123456')
        self.client.force_login(superuser)
        response = self.client.patch(
            f'/api/users/{target.id}/',
            {'is_staff': True},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertTrue(target.is_staff)

    def test_rbac_fail_closed_undeclared_action_denied(self):
        """fail-closed：未声明权限码的 action 一律拒绝（防遗漏登记导致越权）。"""
        from rest_framework.test import APIRequestFactory
        from rest_framework.views import APIView

        from .permissions import RBACPermission

        class _UndeclaredActionView(APIView):
            action = 'custom_action'

            def get_required_permissions(self):
                return []

        factory = APIRequestFactory()
        request = factory.post('/x/')
        request.user = self._make_manager('fail-closed-user')

        self.assertFalse(RBACPermission().has_permission(request, _UndeclaredActionView()))

    def test_login_failure_lockout(self):
        for _ in range(10):
            response = self.client.post(
                '/api/auth/login/',
                {'username': 'nobody', 'password': 'wrong'},
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 400)
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'nobody', 'password': 'wrong'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 429)

    def test_login_with_default_password_reports_warning(self):
        from django.core.cache import cache

        cache.clear()  # 清空登录限流/锁定计数（前置锁定测试耗尽限流预算）
        ensure_builtin_rbac()
        User.objects.create_superuser(username='warn-admin', password='Admin@123456')
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'warn-admin', 'password': 'Admin@123456'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('default_password_warning'))

    def test_login_with_custom_password_has_no_warning(self):
        from django.core.cache import cache

        cache.clear()  # 清空登录限流/锁定计数（前置锁定测试耗尽限流预算）
        ensure_builtin_rbac()
        User.objects.create_superuser(username='safe-admin', password='Str0ng#Custom!Pass')
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'safe-admin', 'password': 'Str0ng#Custom!Pass'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('default_password_warning', response.json())


class TokenLifecycleTests(TestCase):
    """Token 生命周期：超龄 token 自动失效并删除。"""

    def test_expired_token_rejected(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        ensure_builtin_rbac()
        user = User.objects.create_user(username='expiring-user', password='Admin@123456')
        token = Token.objects.create(user=user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(days=31))

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists(), '超龄 token 应被删除')

    def test_fresh_token_accepted(self):
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        ensure_builtin_rbac()
        user = User.objects.create_user(username='fresh-user', password='Admin@123456')
        token = Token.objects.create(user=user)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 200)
