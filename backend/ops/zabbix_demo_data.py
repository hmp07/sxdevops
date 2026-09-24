"""Zabbix 模拟数据 — 离线演示数据源（api_url='demo://'）。

设计对齐 K8s 的 kubeconfig='demo' 先例：
- ZabbixDataSource(api_url='demo://') 为演示数据源
- ZabbixClient 在 _call/_call_raw 顶部检测 is_demo 并分发到本模块
- 数据与 seed_data 的演示故事线一致（order-center 库存校验超时）

确定性原则：hostid/itemid 固定、历史数据用确定性函数生成，保证演示逐字可复现。
"""

from __future__ import annotations

import math
import time

DEMO_API_URL = 'demo://'

# ── 主机数据（对齐 seed_data 的 Host 与 order-center 故事线）───────────

DEMO_HOSTS = [
    {
        'hostid': '10001', 'host': 'order-api-ecs-01', 'name': '订单API主机01',
        'status': '0', 'available': '1', 'description': '订单服务 API 节点（生产）',
        'interfaces': [{'ip': '10.0.1.11', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '1', 'name': '电商平台/订单服务'}],
    },
    {
        'hostid': '10002', 'host': 'order-api-ecs-02', 'name': '订单API主机02',
        'status': '0', 'available': '1', 'description': '订单服务 API 节点（生产）',
        'interfaces': [{'ip': '10.0.1.12', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '1', 'name': '电商平台/订单服务'}],
    },
    {
        'hostid': '10003', 'host': 'k8s-node-01', 'name': 'K8s节点01',
        'status': '0', 'available': '1', 'description': '生产 K8s 工作节点',
        'interfaces': [{'ip': '10.0.2.21', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '2', 'name': '基础架构/K8s'}],
    },
    {
        'hostid': '10004', 'host': 'member-api', 'name': '会员服务主机',
        'status': '0', 'available': '1', 'description': '会员中心 API（生产）',
        'interfaces': [{'ip': '10.0.3.31', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '3', 'name': '电商平台/会员中心'}],
    },
    {
        'hostid': '10005', 'host': 'payment-worker', 'name': '支付对账Worker',
        'status': '0', 'available': '1', 'description': '支付网关对账服务（生产）',
        'interfaces': [{'ip': '10.0.4.41', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '4', 'name': '电商平台/支付网关'}],
    },
    {
        'hostid': '10006', 'host': 'gateway', 'name': 'API网关',
        'status': '0', 'available': '1', 'description': '统一 API 网关（生产）',
        'interfaces': [{'ip': '10.0.5.51', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '5', 'name': '基础架构/网关'}],
    },
    {
        'hostid': '10007', 'host': 'lun-orders-01', 'name': '订单库存储卷',
        'status': '0', 'available': '1', 'description': 'Oracle 订单库存储 LUN（演示）',
        'interfaces': [{'ip': '10.40.1.21', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'hostid': '10008', 'host': 'TS_ORDER', 'name': '订单表空间',
        'status': '0', 'available': '1', 'description': 'Oracle 表空间 TS_ORDER（演示）',
        'interfaces': [{'ip': '10.40.1.22', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'hostid': '10009', 'host': 'ORCL01', 'name': 'Oracle 实例 ORCL',
        'status': '0', 'available': '1', 'description': 'Oracle 实例 ORCL01（演示）',
        'interfaces': [{'ip': '10.40.1.10', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'hostid': '10010', 'host': 'listener-01', 'name': 'Oracle 监听',
        'status': '0', 'available': '1', 'description': 'Oracle 监听进程（演示）',
        'interfaces': [{'ip': '10.40.1.10', 'dns': '', 'type': '1', 'main': '1', 'available': '1'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
]

DEMO_HOST_GROUPS = [
    {'groupid': '1', 'name': '电商平台/订单服务'},
    {'groupid': '6', 'name': '交易平台/Oracle'},
    {'groupid': '2', 'name': '基础架构/K8s'},
    {'groupid': '3', 'name': '电商平台/会员中心'},
    {'groupid': '4', 'name': '电商平台/支付网关'},
    {'groupid': '5', 'name': '基础架构/网关'},
]

# ── 监控项（order-api-ecs-01 磁盘 >90% 支撑演示故事线）────────────────

_DISK_LOW = '0.1500'  # 15% used
_DISK_HIGH = '0.9200'  # 92% used（问题主机）


def _demo_items():
    """为每台主机生成监控项（itemid 确定性分配）。"""
    items = []
    counter = [1000]
    for host in DEMO_HOSTS:
        hostid = host['hostid']
        disk_value = _DISK_HIGH if hostid == '10001' else _DISK_LOW
        cpu_value = '42.5' if hostid == '10001' else '18.3'
        mem_value = '3.8G' if hostid == '10001' else '2.1G'
        now = int(time.time())
        specs = [
            ('system.cpu.util', f'CPU利用率 [{host["host"]}]', cpu_value, '%', '0'),
            ('vm.memory[used]', f'已用内存 [{host["host"]}]', mem_value, 'B', '3'),
            ('vfs.fs.size[/,used]', f'磁盘使用率 [{host["host"]}]', disk_value, '%', '0'),
            ('net.if.in[eth0]', f'入站流量 [{host["host"]}]', '12.4M', 'bps', '3'),
            ('system.uptime', f'运行时长 [{host["host"]}]', str(35 * 24 * 3600 + int(hostid) * 3600), 'uptime', '3'),
            ('system.cpu.load[percpu,avg1]', f'CPU负载1分钟 [{host["host"]}]', '1.8', '', '0'),
        ]
        for key_, name, lastvalue, units, value_type in specs:
            counter[0] += 1
            items.append({
                'itemid': str(counter[0]),
                'hostid': hostid,
                'name': name,
                'key_': key_,
                'lastvalue': lastvalue,
                'lastclock': str(now),
                'units': units,
                'value_type': value_type,
                'status': '0',
                'state': '0',
            })
    return items


DEMO_ITEMS = _demo_items()

# ── 触发器 ──────────────────────────────────────────────────────────

DEMO_TRIGGERS = [
    {
        'triggerid': '20001',
        'description': '磁盘空间使用率超过 90%（order-api-ecs-01）',
        'priority': '4',
        'value': '1',
        'lastchange': str(int(time.time()) - 3600),
        'hosts': [{'hostid': '10001', 'host': 'order-api-ecs-01', 'name': '订单API主机01'}],
        'groups': [{'groupid': '1', 'name': '电商平台/订单服务'}],
    },
    {
        'triggerid': '20002',
        'description': 'CPU 负载持续高于阈值（payment-worker）',
        'priority': '3',
        'value': '1',
        'lastchange': str(int(time.time()) - 7200),
        'hosts': [{'hostid': '10005', 'host': 'payment-worker', 'name': '支付对账Worker'}],
        'groups': [{'groupid': '4', 'name': '电商平台/支付网关'}],
    },
    {
        'triggerid': '20003',
        'description': '可用内存低于 10%（member-api）',
        'priority': '2',
        'value': '0',
        'lastchange': str(int(time.time()) - 86400),
        'hosts': [{'hostid': '10004', 'host': 'member-api', 'name': '会员服务主机'}],
        'groups': [{'groupid': '3', 'name': '电商平台/会员中心'}],
    },
    {
        'triggerid': '30001',
        'description': '存储卷写满 STORAGE_FULL（lun-orders-01）',
        'priority': '4',
        'value': '1',
        'lastchange': str(int(time.time()) - 600),
        'hosts': [{'hostid': '10007', 'host': 'lun-orders-01', 'name': '订单库存储卷'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'triggerid': '30002',
        'description': '表空间使用率超过 99% TABLESPACE_FULL（TS_ORDER）',
        'priority': '4',
        'value': '1',
        'lastchange': str(int(time.time()) - 540),
        'hosts': [{'hostid': '10008', 'host': 'TS_ORDER', 'name': '订单表空间'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'triggerid': '30003',
        'description': 'ORA-01653 表空间无法扩展（ORCL01）',
        'priority': '3',
        'value': '1',
        'lastchange': str(int(time.time()) - 480),
        'hosts': [{'hostid': '10009', 'host': 'ORCL01', 'name': 'Oracle 实例 ORCL'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'triggerid': '30004',
        'description': '监听进程宕机 LISTENER_DOWN（listener-01）',
        'priority': '4',
        'value': '1',
        'lastchange': str(int(time.time()) - 420),
        'hosts': [{'hostid': '10010', 'host': 'listener-01', 'name': 'Oracle 监听'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
    {
        'triggerid': '30005',
        'description': 'ORA-12541 TNS no listener（listener-01）',
        'priority': '2',
        'value': '1',
        'lastchange': str(int(time.time()) - 360),
        'hosts': [{'hostid': '10010', 'host': 'listener-01', 'name': 'Oracle 监听'}],
        'groups': [{'groupid': '6', 'name': '交易平台/Oracle'}],
    },
]

# ── 活跃问题（与告警中心故事线呼应）──────────────────────────────────

DEMO_PROBLEMS = [
    {
        'eventid': '30001',
        'name': '磁盘空间使用率超过 90%（order-api-ecs-01）',
        'severity': '4',
        'clock': str(int(time.time()) - 3600),
        'source': '0',
        'objectid': '20001',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'order-api-ecs-01',
    },
    {
        'eventid': '30002',
        'name': 'CPU 负载持续高于阈值（payment-worker）',
        'severity': '3',
        'clock': str(int(time.time()) - 7200),
        'source': '0',
        'objectid': '20002',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'payment-worker',
    },
    # ── Oracle 域故事线（L1 因果收敛演示，时钟差 ≤5min 时间窗）──
    {
        'eventid': '40001',
        'name': '存储卷写满 STORAGE_FULL（lun-orders-01）',
        'severity': '4',
        'clock': str(int(time.time()) - 600),
        'source': '0',
        'objectid': '30001',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'lun-orders-01',
    },
    {
        'eventid': '40002',
        'name': '表空间使用率超过 99% TABLESPACE_FULL（TS_ORDER）',
        'severity': '4',
        'clock': str(int(time.time()) - 540),
        'source': '0',
        'objectid': '30002',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'TS_ORDER',
    },
    {
        'eventid': '40003',
        'name': 'ORA-01653 表空间无法扩展（ORCL01）',
        'severity': '3',
        'clock': str(int(time.time()) - 480),
        'source': '0',
        'objectid': '30003',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'ORCL01',
    },
    {
        'eventid': '40004',
        'name': '监听进程宕机 LISTENER_DOWN（listener-01）',
        'severity': '4',
        'clock': str(int(time.time()) - 420),
        'source': '0',
        'objectid': '30004',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'listener-01',
    },
    {
        'eventid': '40005',
        'name': 'ORA-12541 TNS no listener（listener-01）',
        'severity': '2',
        'clock': str(int(time.time()) - 360),
        'source': '0',
        'objectid': '30005',
        'acknowledged': '0',
        'r_eventid': '0',
        'hostname': 'listener-01',
    },
]


# ── 确定性历史/趋势数据生成 ─────────────────────────────────────────


def generate_history(itemid, hours=6, step=60):
    """生成确定性历史序列：正弦 + 基于 itemid 的相位偏移。

    磁盘项（vfs.fs）生成单调上升曲线，更贴近"空间被占满"的故事线。
    """
    seed = int(itemid) * 2654435761 % 997
    phase = (seed % 100) / 100.0 * math.pi
    amp = 0.2 + (seed % 40) / 100.0
    now = int(time.time())
    points = []
    for i in range(int(hours * 3600 / step)):
        clock = now - int((hours * 3600 - i * step))
        t = i / max(1, int(hours * 3600 / step))
        if 'vfs.fs' in _item_key_by_id(itemid):
            base = 0.55 + 0.35 * t  # 55% → 90%
        else:
            base = 0.5 + amp * math.sin(2 * math.pi * 2 * t + phase)
        value = max(0.0, round(base + amp * 0.15 * math.sin(13 * t + phase), 4))
        points.append({'clock': str(clock), 'value': f'{value:.4f}', 'itemid': itemid})
    return points


_item_key_cache = {}


def _item_key_by_id(itemid: str) -> str:
    if itemid not in _item_key_cache:
        for item in DEMO_ITEMS:
            if item['itemid'] == itemid:
                _item_key_cache[itemid] = item['key_']
                break
        _item_key_cache.setdefault(itemid, '')
    return _item_key_cache[itemid]


def generate_trends(itemid, hours=48, step=3600):
    """生成确定性趋势序列（小时粒度）。"""
    return generate_history(itemid, hours=hours, step=step)


# ── JSON-RPC 方法分发 ───────────────────────────────────────────────


def dispatch_demo_call(method: str, params: dict):
    """模拟 Zabbix JSON-RPC 响应。params 为客户端构造的完整参数。"""
    if method == 'apiinfo.version':
        return '6.0.24'
    if method == 'user.login':
        return 'demo' * 8  # 32 字符占位 session token
    if method == 'user.checkAuthentication':
        return True
    if method == 'hostgroup.get':
        return DEMO_HOST_GROUPS
    if method == 'host.get':
        return _filter_hosts(params)
    if method == 'item.get':
        return _filter_items(params)
    if method == 'history.get':
        return _filter_history(params)
    if method == 'trend.get':
        return _filter_history(params)
    if method == 'trigger.get':
        return _filter_triggers(params)
    if method == 'problem.get':
        return _filter_problems(params)
    return {'error': f'演示数据源不支持方法: {method}'}


def _filter_hosts(params: dict) -> list:
    hosts = [dict(h) for h in DEMO_HOSTS]
    host_ids = params.get('hostids') or []
    group_ids = params.get('groupids') or []
    search = (params.get('search') or {}).get('host', '')
    if host_ids:
        host_ids = {str(h) for h in host_ids}
        hosts = [h for h in hosts if h['hostid'] in host_ids]
    if group_ids:
        group_ids = {str(g) for g in group_ids}
        hosts = [h for h in hosts if any(g['groupid'] in group_ids for g in h['groups'])]
    if search:
        hosts = [h for h in hosts if search.lower() in h['host'].lower()]
    return hosts


def _filter_items(params: dict) -> list:
    items = [dict(i) for i in DEMO_ITEMS]
    host_ids = params.get('hostids') or []
    if host_ids:
        host_ids = {str(h) for h in host_ids}
        items = [i for i in items if i['hostid'] in host_ids]
    search = params.get('search') or {}
    for field, pattern in search.items():
        if pattern:
            items = [i for i in items if pattern.lower() in str(i.get(field, '')).lower()]
    flt = params.get('filter') or {}
    if flt.get('status'):
        items = [i for i in items if i['status'] == str(flt['status'])]
    if flt.get('state'):
        items = [i for i in items if i['state'] == str(flt['state'])]
    limit = params.get('limit')
    if limit:
        items = items[:int(limit)]
    return items


def _filter_history(params: dict) -> list:
    item_ids = params.get('itemids') or []
    limit = int(params.get('limit') or 60)
    step = 300  # 5 分钟粒度
    points = []
    for item_id in item_ids:
        points.extend(generate_history(str(item_id), hours=6, step=step))
    points.sort(key=lambda p: int(p['clock']))
    return points[-limit:] if len(points) > limit else points


def _filter_triggers(params: dict) -> list:
    triggers = [dict(t) for t in DEMO_TRIGGERS]
    trigger_ids = params.get('triggerids') or []
    if trigger_ids:
        trigger_ids = {str(t) for t in trigger_ids}
        triggers = [t for t in triggers if t['triggerid'] in trigger_ids]
    min_sev = params.get('min_severity')
    if min_sev:
        triggers = [t for t in triggers if int(t['priority']) >= int(min_sev)]
    if params.get('filter', {}).get('value') == 1:
        triggers = [t for t in triggers if t['value'] == '1']
    host_ids = params.get('hostids') or []
    if host_ids:
        host_ids = {str(h) for h in host_ids}
        triggers = [t for t in triggers if any(h['hostid'] in host_ids for h in t['hosts'])]
    return triggers


def _filter_problems(params: dict) -> list:
    problems = [dict(p) for p in DEMO_PROBLEMS]
    severities = params.get('severities') or []
    if severities:
        severities = {str(s) for s in severities}
        problems = [p for p in problems if p['severity'] in severities]
    host_ids = params.get('hostids') or []
    if host_ids:
        host_ids = {str(h) for h in host_ids}
        # problem 数据没有 hostid 字段，通过 hostname 匹配
        hostname_map = {h['hostid']: h['host'] for h in DEMO_HOSTS}
        names = {hostname_map.get(h) for h in host_ids}
        problems = [p for p in problems if p.get('hostname') in names]
    return problems
