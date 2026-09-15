"""独立验证脚本 — 绕过 Django 测试框架验证 Grafana 端点 SSRF 加固行为。

运行: cd backend && python -X utf8 ops/verify_grafana_endpoints.py
使用 dev 数据库（验证结束后清理 GrafanaSetting 变更），http_requests 全程 mock，
APIClient 走真实路由（认证 + CSRF 处理与生产一致）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sxdevops.settings')

import django  # noqa: E402

django.setup()

from unittest.mock import MagicMock, patch  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from ops.models import GrafanaSetting  # noqa: E402


def _client():
    client = APIClient()
    user = get_user_model().objects.filter(username='admin').first()
    client.force_authenticate(user=user)
    return client


def _cleanup():
    GrafanaSetting.objects.all().delete()


def run(name, fn, expect):
    try:
        ok = fn()
    except Exception as exc:
        print(f'[FAIL] {name}: {type(exc).__name__}: {exc}')
        return False
    print(f'[{"PASS" if ok == expect else "FAIL"}] {name}')
    return ok == expect


results = []


def t1_link_local_rejected():
    """169.254.169.254 应被拒绝且不发请求"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://grafana.internal.local')
    with patch('ops.observability_views.http_requests.get') as mock_get:
        resp = _client().post('/api/observability/grafana/test/', {'url': 'http://169.254.169.254/latest/meta-data/'}, format='json')
        return resp.status_code == 400 and not mock_get.called


def t2_non_http_rejected():
    """file:// 应被拒绝且不发请求"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://grafana.internal.local')
    with patch('ops.observability_views.http_requests.get') as mock_get:
        resp = _client().post('/api/observability/grafana/test/', {'url': 'file:///etc/passwd'}, format='json')
        return resp.status_code == 400 and not mock_get.called


def t2b_link_local_trailing_dot_rejected():
    """尾点形式 169.254.169.254. 不得绕过字面量检查"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://grafana.internal.local')
    with patch('ops.observability_views.http_requests.get') as mock_get:
        resp = _client().post('/api/observability/grafana/test/', {'url': 'http://169.254.169.254./'}, format='json')
        return resp.status_code == 400 and not mock_get.called


def t3_stored_token_not_leaked_to_custom_url():
    """自定义 URL 未显式提供 token：不得附加存储凭据"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://grafana.saved.internal.local', api_token='glsa_stored_secret')
    health = MagicMock(status_code=200)
    health.json.return_value = {'version': '11.0.0'}
    org = MagicMock(status_code=200)
    org.json.return_value = {'id': 1, 'name': 'Main Org.'}
    with patch('ops.observability_views.http_requests.get', side_effect=[health, org]) as mock_get:
        resp = _client().post('/api/observability/grafana/test/', {'url': 'http://10.9.9.9'}, format='json')
        if resp.status_code != 200:
            return False
        headers = mock_get.call_args_list[0][1]['headers']
        return 'Authorization' not in headers


def t4_stored_token_attached_to_configured_url():
    """与已保存配置一致时正常附带存储 Token"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://10.9.9.8', api_token='glsa_stored_secret')
    health = MagicMock(status_code=200)
    health.json.return_value = {'version': '11.0.0'}
    org = MagicMock(status_code=200)
    org.json.return_value = {'id': 1, 'name': 'Main Org.'}
    with patch('ops.observability_views.http_requests.get', side_effect=[health, org]) as mock_get:
        resp = _client().post('/api/observability/grafana/test/', {}, format='json')
        if resp.status_code != 200:
            return False
        headers = mock_get.call_args_list[0][1]['headers']
        return headers.get('Authorization') == 'Bearer glsa_stored_secret'


def t5_discover_returns_dashboards():
    """自动发现端点返回目录与看板"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://10.9.9.8', api_token='glsa_disc')
    folders = MagicMock(status_code=200)
    folders.json.return_value = [{'uid': 'f1', 'title': '基础设施'}]
    dashboards = MagicMock(status_code=200)
    dashboards.json.return_value = [{
        'uid': 'infra-overview', 'title': '基础设施总览', 'slug': 'infra-overview',
        'url': '/d/infra-overview', 'folderUid': 'f1', 'folderTitle': '基础设施', 'tags': ['infra'],
    }]
    with patch('ops.observability_views.http_requests.get', side_effect=[folders, dashboards]):
        resp = _client().post('/api/observability/grafana/discover/', {}, format='json')
        if resp.status_code != 200:
            return False
        payload = resp.json()
        return payload['dashboard_count'] == 1 and payload['dashboards'][0]['uid'] == 'infra-overview'


def t6_discover_uses_no_redirects():
    """discover 的 api/search 调用必须带 allow_redirects=False"""
    _cleanup()
    GrafanaSetting.objects.create(name='default', url='http://10.9.9.8', api_token='glsa_disc')
    folders = MagicMock(status_code=200)
    folders.json.return_value = []
    dashboards = MagicMock(status_code=200)
    dashboards.json.return_value = []
    with patch('ops.observability_views.http_requests.get', side_effect=[folders, dashboards]) as mock_get:
        resp = _client().post('/api/observability/grafana/discover/', {}, format='json')
        if resp.status_code != 200:
            return False
        return len(mock_get.call_args_list) > 0 and all(call[1].get('allow_redirects') is False for call in mock_get.call_args_list)


results.append(run('link-local 云元数据拒绝', t1_link_local_rejected, True))
results.append(run('非 http 协议拒绝', t2_non_http_rejected, True))
results.append(run('尾点形式链路本地拒绝', t2b_link_local_trailing_dot_rejected, True))
results.append(run('自定义 URL 不泄露存储 Token', t3_stored_token_not_leaked_to_custom_url, True))
results.append(run('已保存 URL 正常附加 Token', t4_stored_token_attached_to_configured_url, True))
results.append(run('自动发现返回看板', t5_discover_returns_dashboards, True))
results.append(run('api/search 禁止重定向', t6_discover_uses_no_redirects, True))

_cleanup()
print()
print('=' * 50)
print(f'通过 {sum(results)} / {len(results)}')
sys.exit(0 if all(results) else 1)
