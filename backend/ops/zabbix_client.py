"""Zabbix JSON-RPC API Client."""
import threading
import requests
from django.conf import settings
from django.core.cache import cache as django_cache


class ZabbixClient:
    """Zabbix JSON-RPC API 客户端"""

    def __init__(self, datasource):
        self.api_url = datasource.api_url.rstrip('/')
        self.auth_type = datasource.auth_type
        self.auth_token = datasource.auth_token
        self.username = datasource.username
        self.password = datasource.password
        self.tls_verify = datasource.tls_verify
        self.timeout = datasource.timeout or 15
        self.datasource_id = datasource.id
        self._token_lock = threading.Lock()
        self._cached_token = None
        self._rpc_id = 0

    def _next_id(self):
        self._rpc_id += 1
        return self._rpc_id

    def _get_auth_header(self):
        """构建认证 HTTP Header"""
        if self._cached_token:
            return f'Bearer {self._cached_token}'
        if self.auth_type == 'token':
            return f'Bearer {self.auth_token}'
        return None

    def _call(self, method, params=None):
        """调用 Zabbix JSON-RPC API"""
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': self._next_id(),
        }
        headers = {'Content-Type': 'application/json-rpc'}
        auth_header = self._get_auth_header()
        if auth_header:
            headers['Authorization'] = auth_header

        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=self.tls_verify,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            return {'error': f'请求失败: {str(e)}'}

        if 'error' in result:
            err = result['error']
            # Re-authenticate on session errors and retry once
            if self.auth_type == 'userpass' and not self._cached_token:
                if self._login():
                    headers['Authorization'] = f'Bearer {self._cached_token}'
                    return self._call_raw(payload, headers)
            return {'error': err.get('message', str(err)), 'data': err.get('data', '')}

        return result.get('result', {})

    def _call_raw(self, payload, extra_headers=None):
        """Raw JSON-RPC call without auth handling"""
        headers = {'Content-Type': 'application/json-rpc'}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=self.tls_verify,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            return {'error': f'请求失败: {str(e)}'}
        if 'error' in result:
            return {'error': result['error'].get('message', str(result['error']))}
        return result.get('result', {})

    def _login(self):
        """用户密码认证，获取 auth token"""
        with self._token_lock:
            if self._cached_token:
                return True
            raw = self._call_raw({
                'jsonrpc': '2.0',
                'method': 'user.login',
                'params': {'username': self.username, 'password': self.password},
                'id': self._next_id(),
            })
            # user.login returns a string token directly (not a dict)
            if isinstance(raw, str) and len(raw) == 32:
                self._cached_token = raw
                return True
            if isinstance(raw, dict) and 'error' not in raw:
                self._cached_token = raw
                return True
        return False

    def _ensure_auth(self):
        """确保已认证"""
        if self.auth_type == 'token' and self.auth_token:
            return True
        if self._cached_token:
            return True
        return self._login()

    # ---- Zabbix API Methods ----

    def test_connection(self):
        """测试连接：调用 apiinfo.version"""
        return self._call('apiinfo.version')

    def get_hosts(self, group_ids=None, search=None, limit=100):
        """获取主机列表"""
        params = {'output': ['hostid', 'host', 'name', 'status', 'available', 'maintenance_status'],
                  'selectInterfaces': ['ip', 'dns', 'port', 'type'],
                  'selectGroups': ['groupid', 'name'],
                  'limit': limit}
        if group_ids:
            params['groupids'] = group_ids
        if search:
            params['search'] = {'host': search, 'name': search}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('host.get', params)

    def get_host_groups(self):
        """获取主机组列表"""
        params = {'output': ['groupid', 'name']}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('hostgroup.get', params)

    def get_items(self, host_ids=None, search=None, limit=100):
        """获取监控项列表"""
        params = {'output': ['itemid', 'name', 'key_', 'lastvalue', 'lastclock', 'units', 'status',
                             'value_type', 'hostid'],
                  'selectHosts': ['hostid', 'host', 'name'],
                  'sortfield': 'name',
                  'limit': limit}
        if host_ids:
            params['hostids'] = host_ids
        if search:
            params['search'] = {'key_': search, 'name': search}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('item.get', params)

    def get_history(self, item_ids, history_type=0, time_from=None, time_to=None, limit=100):
        """获取监控项历史数据"""
        params = {'output': 'extend',
                  'itemids': item_ids,
                  'history': history_type,
                  'sortfield': 'clock',
                  'sortorder': 'DESC',
                  'limit': limit}
        if time_from:
            params['time_from'] = time_from
        if time_to:
            params['time_till'] = time_to
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('history.get', params)

    def get_triggers(self, host_ids=None, min_severity=None, only_true=False, limit=100):
        """获取触发器列表"""
        params = {'output': ['triggerid', 'description', 'priority', 'status', 'value',
                             'lastchange', 'hosts', 'expression'],
                  'selectHosts': ['hostid', 'host', 'name'],
                  'sortfield': 'priority',
                  'sortorder': 'DESC',
                  'limit': limit}
        if host_ids:
            params['hostids'] = host_ids
        if min_severity is not None:
            params['min_severity'] = min_severity
        if only_true:
            params['filter'] = {'value': 1}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('trigger.get', params)

    def get_problems(self, host_ids=None, severities=None, recent=True, limit=100):
        """获取当前问题（Zabbix 7.4 不支持 selectHosts/sortfield）"""
        params = {'output': ['eventid', 'name', 'severity', 'clock', 'source', 'objectid',
                             'acknowledged', 'r_eventid'],
                  'limit': limit}
        if host_ids:
            params['hostids'] = host_ids
        if severities:
            params['severities'] = severities
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('problem.get', params)
