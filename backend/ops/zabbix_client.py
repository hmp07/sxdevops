"""Zabbix JSON-RPC API Client.

参考 ZBXScreen 项目已测试的 Zabbix API 调用模式，兼容 Zabbix 5.x/6.x/7.x。
"""
import threading
import time
import requests


class ZabbixClient:
    """Zabbix JSON-RPC API 客户端（兼容 5.x/6.x/7.x）"""

    def __init__(self, datasource):
        self.api_url = datasource.api_url.rstrip('/')
        self.auth_type = datasource.auth_type
        self.auth_token = datasource.auth_token
        self.username = datasource.username
        self.password = datasource.password
        self.tls_verify = datasource.tls_verify
        self.timeout = min(max(datasource.timeout or 15, 5), 60)
        self.datasource_id = datasource.id
        self._token_lock = threading.Lock()
        self._cached_token = None
        self._token_expires = 0
        self._zabbix_version = None
        self._rpc_id = 0

    def _next_id(self):
        self._rpc_id += 1
        return self._rpc_id

    # ---- Auth ----

    def _detect_version(self):
        """检测 Zabbix 主版本号"""
        if self._zabbix_version is not None:
            return self._zabbix_version
        result = self._call_raw({
            'jsonrpc': '2.0', 'method': 'apiinfo.version',
            'params': [], 'id': self._next_id(),
        })
        if isinstance(result, str):
            self._zabbix_version = int(result.split('.')[0])
        return self._zabbix_version or 5

    def _get_auth_header(self):
        """Zabbix 7.x: Bearer Token 在 HTTP Header"""
        if self._is_token_valid():
            return f'Bearer {self._cached_token}'
        if self.auth_type == 'token':
            return f'Bearer {self.auth_token}'
        return None

    def _is_token_valid(self):
        if not self._cached_token:
            return False
        if self._token_expires and time.time() > self._token_expires:
            self._cached_token = None
            return False
        return True

    def _login(self):
        """用户密码认证，获取 session token"""
        with self._token_lock:
            if self._is_token_valid():
                return True
            raw = self._call_raw({
                'jsonrpc': '2.0',
                'method': 'user.login',
                'params': {'username': self.username, 'password': self.password},
                'id': self._next_id(),
            })
            if isinstance(raw, str) and len(raw) == 32:
                self._cached_token = raw
                self._token_expires = time.time() + 3600  # 1h TTL
                self._zabbix_version = self._detect_version()
                if self._zabbix_version >= 7:
                    self._call_raw({
                        'jsonrpc': '2.0', 'method': 'user.checkAuthentication',
                        'params': {'sessionid': raw}, 'id': self._next_id(),
                    })
                return True
        return False

    def _ensure_auth(self):
        if self.auth_type == 'token' and self.auth_token:
            if not self._zabbix_version:
                self._zabbix_version = self._detect_version()
            return True
        if self._is_token_valid():
            return True
        return self._login()

    # ---- JSON-RPC call ----

    def _call(self, method, params=None):
        """调用 Zabbix JSON-RPC API"""
        payload = {
            'jsonrpc': '2.0', 'method': method,
            'params': params or {}, 'id': self._next_id(),
        }
        headers = {'Content-Type': 'application/json-rpc'}
        auth_header = self._get_auth_header()
        if auth_header:
            headers['Authorization'] = auth_header

        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers,
                timeout=self.timeout, verify=self.tls_verify,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            return {'error': str(e)}

        if 'error' in result:
            err = result['error']
            if err.get('code') == -32602 and self.auth_type == 'userpass':
                self._cached_token = None
                self._token_expires = 0
                if self._login():
                    headers['Authorization'] = f'Bearer {self._cached_token}'
                    return self._call_raw(payload, headers)
            return {'error': err.get('message', str(err)), 'data': err.get('data', '')}
        return result.get('result', {})

    def _call_raw(self, payload, extra_headers=None):
        headers = {'Content-Type': 'application/json-rpc'}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers,
                timeout=self.timeout, verify=self.tls_verify,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            return {'error': str(e)}
        if 'error' in result:
            return {'error': result['error'].get('message', str(result['error']))}
        return result.get('result', {})

    # ---- Zabbix API Methods ----

    def test_connection(self):
        """测试连接"""
        return self._call('apiinfo.version')

    def get_hosts(self, group_ids=None, host_ids=None, search=None):
        """获取主机列表（无限 limit）"""
        params = {
            'output': ['hostid', 'host', 'name', 'status', 'description', 'available'],
            'selectInterfaces': ['ip', 'dns', 'type', 'main', 'available'],
            'selectGroups': ['groupid', 'name'],
            'selectHostGroups': ['groupid', 'name'],
        }
        if group_ids:
            params['groupids'] = group_ids
        if host_ids:
            params['hostids'] = host_ids
        if search:
            params['search'] = {'host': search}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        result = self._call('host.get', params)
        # 统一 Zabbix 7.x 的 hostgroups → groups
        hosts = result if isinstance(result, list) else []
        for h in hosts:
            if 'hostgroups' in h and 'groups' not in h:
                h['groups'] = h.pop('hostgroups')
        return hosts

    def get_host_groups(self):
        """获取主机组列表"""
        params = {'output': ['groupid', 'name']}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('hostgroup.get', params)

    def get_items(self, host_ids=None, search=None):
        """获取监控项列表。有 host_ids 时 limit=50000，否则限制 200"""
        params = {
            'output': ['itemid', 'hostid', 'name', 'key_', 'lastvalue', 'lastclock', 'units', 'value_type'],
            'limit': 50000 if host_ids else 200,
        }
        if host_ids:
            params['hostids'] = host_ids
        if search:
            params['search'] = {'key_': search, 'name': search}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('item.get', params)

    def get_history(self, item_ids, time_from=None, time_to=None, limit=500):
        """获取历史数据（ASC 时间升序）"""
        params = {
            'output': 'extend',
            'itemids': item_ids,
            'sortfield': 'clock',
            'sortorder': 'ASC',
            'limit': limit,
        }
        if time_from:
            params['time_from'] = time_from
        if time_to:
            params['time_till'] = time_to
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('history.get', params)

    def get_trends(self, item_ids, time_from=None, time_to=None, limit=500):
        """获取趋势数据（>1天历史，limit=500）"""
        params = {
            'output': 'extend',
            'itemids': item_ids,
            'sortfield': 'clock',
            'sortorder': 'ASC',
            'limit': limit,
        }
        if time_from:
            params['time_from'] = time_from
        if time_to:
            params['time_till'] = time_to
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('trend.get', params)

    def get_triggers(self, host_ids=None, trigger_ids=None, min_severity=None, active_only=False):
        """获取触发器列表"""
        params = {
            'output': ['triggerid', 'description', 'priority', 'value', 'lastchange'],
            'selectHosts': ['hostid', 'host', 'name'],
            'selectGroups': ['groupid', 'name'],
            'sortfield': 'lastchange',
            'sortorder': 'DESC',
        }
        if host_ids:
            params['hostids'] = host_ids
        if trigger_ids:
            params['triggerids'] = trigger_ids
        if min_severity is not None and min_severity > 0:
            params['min_severity'] = str(min_severity)
        if active_only:
            params['filter'] = {'value': 1}
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('trigger.get', params)

    def get_problems(self, host_ids=None, severities=None):
        """获取当前问题（Zabbix 7.4 problem.get 不支持 selectHosts/sortfield）"""
        params = {
            'output': ['eventid', 'name', 'severity', 'clock', 'source', 'objectid',
                       'acknowledged', 'r_eventid'],
        }
        if host_ids:
            params['hostids'] = host_ids
        if severities:
            params['severities'] = severities
        if not self._ensure_auth():
            return {'error': '认证失败'}
        return self._call('problem.get', params)
