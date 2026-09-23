"""演示指标引擎：确定性 Prometheus 时序生成器 + PromQL 子集求值器。

设计对齐 ops/zabbix_demo_data.py：
- 纯函数、无存储、无外部依赖；MetricDataSource(config={'demo_mode': True})
  由 observability_views 的三个分发点路由到本模块
- 值函数是绝对时间 t 的连续函数（sin+相位种子+线性趋势+高斯脉冲），
  同一时间窗口内任意时刻查询结果一致
- 故事线与种子告警/Zabbix/日志对齐：order-api-ecs-01 磁盘 24h 55%→92%、
  member-api 内存 7 天泄漏、payment-worker 每日对账 CPU 高峰、
  order-service 库存校验超时（错误率/延迟最近 2h 脉冲）

PromQL 支持子集：选择器+标签过滤（= != =~ !~）、[5m] 时间窗口、
rate/irate、sum/avg/min/max by/without、算术 + - * /、比较运算、
数字、括号、一元负号。其余语法（topk/histogram_quantile/*_over_time/
offset/子查询/集合运算/on 修饰符等）解析即抛 ValueError（前端直接展示）。
"""
import itertools
import math
import re
import time

# ── 标签域（对齐 zabbix_demo_data.DEMO_HOSTS 与 tracing demo services）──

DEMO_HOSTS = ['order-api-ecs-01', 'order-api-ecs-02', 'k8s-node-01', 'member-api', 'payment-worker', 'gateway']
DEMO_SERVICES = ['gateway-service', 'order-service', 'payment-service', 'member-service']
DEMO_HTTP_CODES = ['200', '500']

_HOST_SEED = {host: idx for idx, host in enumerate(DEMO_HOSTS)}
_SERVICE_SEED = {svc: idx for idx, svc in enumerate(DEMO_SERVICES)}

_CPU_BASE = {
    'order-api-ecs-01': 45.0, 'order-api-ecs-02': 38.0, 'k8s-node-01': 55.0,
    'member-api': 62.0, 'payment-worker': 68.0, 'gateway': 48.0,
}
_MEM_BASE = {
    'order-api-ecs-01': 58.0, 'order-api-ecs-02': 52.0, 'k8s-node-01': 66.0,
    'payment-worker': 61.0, 'gateway': 55.0,
}
_RPS_BASE = {'gateway-service': 200.0, 'order-service': 120.0, 'member-service': 60.0, 'payment-service': 35.0}
_LATENCY_BASE = {'gateway-service': 0.12, 'order-service': 0.22, 'member-service': 0.18, 'payment-service': 0.35}


# ── 基础波形 ───────────────────────────────────────────────────

def _wave(t, seed, period, amp):
    return amp * math.sin(2 * math.pi * t / period + seed * 1.7)


def _gauss(t, center, width, amp):
    x = (t - center) / max(1.0, width)
    return amp * math.exp(-0.5 * x * x)


def _erf_step(t, center, width, amp):
    """erf 平滑阶跃（用于累计计数器上的"速率脉冲"，rate 后呈尖峰）。"""
    x = (t - center) / max(1.0, width)
    return amp * 0.5 * (1.0 + math.erf(x))


# ── 指标值函数（labels: dict, t: 绝对秒 → float）───────────────

def _cpu(labels, t):
    host = labels['host']
    seed = _HOST_SEED[host]
    value = _CPU_BASE[host] + _wave(t, seed, 4 * 3600, 12.0) + _wave(t, seed + 3, 45 * 60, 3.0)
    if host == 'payment-worker':
        # 每日 14:00 对账高峰脉冲（对齐 trigger 20002 故事）
        value += _gauss(t % 86400, 14 * 3600, 3600, 15.0)
    return max(5.0, value)


def _mem(labels, t):
    host = labels['host']
    now = time.time()
    if host == 'member-api':
        # 7 天 40%→78% 线性泄漏，封顶 85%（对齐 trigger 20003 故事）
        frac = (t - (now - 7 * 86400)) / (7 * 86400)
        return min(85.0, max(40.0, 40.0 + 38.0 * frac))
    seed = _HOST_SEED[host]
    return max(20.0, _MEM_BASE[host] + _wave(t, seed + 5, 8 * 3600, 5.0))


def _disk(labels, t):
    host = labels['host']
    now = time.time()
    if host == 'order-api-ecs-01':
        # 24h 前 55% → 现在 92%，封顶 92%（对齐 trigger 20001 故事）
        frac = (t - (now - 86400)) / 86400
        return min(92.0, 55.0 + 37.0 * max(0.0, frac))
    # 其余主机 15% 左右（对齐 zabbix _DISK_LOW），缓慢增长 + 噪声
    seed = _HOST_SEED[host]
    return max(5.0, 15.0 + 0.02 * (t - now) / 86400 + _wave(t, seed + 2, 12 * 3600, 1.5))


def _net(labels, t):
    host = labels['host']
    seed = _HOST_SEED[host]
    t0 = time.time() - 86400
    bytes_per_second = (12.0 + seed * 2.0) * 1e6 / 8
    return max(0.0, (t - t0) * bytes_per_second + _wave(t, seed, 3600, 30e6))


def _rps(labels, t):
    service = labels['service']
    code = labels['code']
    now = time.time()
    base = _RPS_BASE[service]
    if code == '500':
        base *= 0.01
    total = (t - (now - 86400)) * base
    if service == 'order-service' and code == '500':
        # 库存校验超时：最近 2h 错误速率脉冲（erf 累积，rate 后呈尖峰）
        total += _erf_step(t, now - 3600, 1200, 25.0) * 1800
    return max(0.0, total)


def _latency(labels, t):
    service = labels['service']
    seed = _SERVICE_SEED[service]
    now = time.time()
    base = _LATENCY_BASE[service]
    value = base + _wave(t, seed + 1, 30 * 60, base * 0.3)
    if service == 'order-service':
        # 最近 2h 延迟尖峰至 ~1.8s（对齐 LogEntry "downstream latency increased to 1.8s"）
        value += _gauss(t, now - 3600, 1800, 1.6)
    return max(0.001, value)


def _errors(labels, t):
    service = labels['service']
    now = time.time()
    base = 0.8 if service == 'order-service' else 0.3
    total = max(0.0, (t - (now - 86400)) * base)
    if service == 'order-service':
        total += _erf_step(t, now - 3600, 1200, 0.8) * 1800
    return total


def _inv(labels, t):
    service = labels['service']
    seed = _SERVICE_SEED[service]
    now = time.time()
    base = 2.4 if service == 'order-service' else 2.2
    value = base + _wave(t, seed + 4, 20 * 60, 0.4)
    if service == 'order-service':
        # 库存校验超时：峰值 ~5.5s
        value += _gauss(t, now - 3600, 1800, 3.0)
    return max(0.01, value)


DEMO_METRIC_SPECS = {
    'node_cpu_usage_percent': {'type': 'gauge', 'labels': {'host': DEMO_HOSTS}, 'func': _cpu},
    'node_memory_usage_percent': {'type': 'gauge', 'labels': {'host': DEMO_HOSTS}, 'func': _mem},
    'node_disk_usage_percent': {'type': 'gauge', 'labels': {'host': DEMO_HOSTS}, 'func': _disk},
    'node_network_receive_bytes_total': {'type': 'counter', 'labels': {'host': DEMO_HOSTS}, 'func': _net},
    'http_requests_total': {'type': 'counter', 'labels': {'service': DEMO_SERVICES, 'code': DEMO_HTTP_CODES}, 'func': _rps},
    'http_request_duration_seconds': {'type': 'gauge', 'labels': {'service': DEMO_SERVICES}, 'func': _latency},
    'http_errors_total': {'type': 'counter', 'labels': {'service': DEMO_SERVICES}, 'func': _errors},
    'inventory_check_duration_seconds': {'type': 'gauge', 'labels': {'service': DEMO_SERVICES}, 'func': _inv},
}


def list_metric_names():
    return list(DEMO_METRIC_SPECS.keys())


def list_label_values(label):
    values = []
    for spec in DEMO_METRIC_SPECS.values():
        if label in spec['labels']:
            for value in spec['labels'][label]:
                if value not in values:
                    values.append(value)
    return values


def _all_series():
    series = []
    for name, spec in DEMO_METRIC_SPECS.items():
        keys = list(spec['labels'].keys())
        for combo in itertools.product(*[spec['labels'][k] for k in keys]):
            labels = dict(zip(keys, combo))
            series.append((name, labels, spec['func']))
    return series


# ── PromQL 子集：词法与语法 ────────────────────────────────────

_TOKEN_RE = re.compile(
    r'(?P<ws>\s+)'
    r'|(?P<duration>\d+(?:ms|s|m|h|d|w))'
    r'|(?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'|(?P<string>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
    r'|(?P<op>=~|!~|==|!=|>=|<=|[{}()\[\],=+\-*/<>])'
)

_DURATION_UNITS = {'ms': 0.001, 's': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}

_UNSUPPORTED_FUNCS = {
    'topk', 'bottomk', 'quantile', 'histogram_quantile', 'count', 'stddev', 'stdvar',
    'absent', 'label_replace', 'label_join', 'sort', 'sort_desc', 'time', 'vector', 'scalar',
}
_UNSUPPORTED_KEYWORDS = {'offset', 'and', 'or', 'unless', 'on', 'ignoring', 'group_left', 'group_right'}


def _unsupported(what):
    raise ValueError(f'演示指标引擎不支持: {what}')


def _duration_seconds(text):
    m = re.match(r'(\d+)(ms|s|m|h|d|w)', text)
    return float(m.group(1)) * _DURATION_UNITS[m.group(2)]


def _tokenize(expr):
    tokens = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            _unsupported(f'无法解析 "{expr[pos:pos + 20]}"')
        if m.lastgroup == 'ws':
            pos = m.end()
            continue
        value = m.group(0)
        if m.lastgroup == 'string':
            value = value[1:-1]
        tokens.append((m.lastgroup, value))
        pos = m.end()
    tokens.append(('EOF', ''))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, value, what):
        kind, val = self.peek()
        if val != value:
            _unsupported(f'期望 {what}，实际 {val!r}')
        return self.next()

    def parse(self):
        node = self.parse_expr()
        kind, val = self.peek()
        if kind != 'EOF':
            _unsupported(f'多余内容 {val!r}')
        return node

    def parse_expr(self):
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_add()
        kind, val = self.peek()
        if val in ('>', '>=', '<', '<=', '==', '!='):
            self.next()
            right = self.parse_add()
            return ('cmp', val, left, right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while True:
            kind, val = self.peek()
            if val in ('+', '-'):
                self.next()
                left = ('bin', val, left, self.parse_mul())
            elif kind == 'name' and val in _UNSUPPORTED_KEYWORDS:
                _unsupported(f'{val} 语法')
            else:
                return left

    def parse_mul(self):
        left = self.parse_unary()
        while True:
            kind, val = self.peek()
            if val in ('*', '/'):
                self.next()
                left = ('bin', val, left, self.parse_unary())
            elif kind == 'name' and val in _UNSUPPORTED_KEYWORDS:
                _unsupported(f'{val} 语法')
            else:
                return left

    def parse_unary(self):
        kind, val = self.peek()
        if val == '-':
            self.next()
            return ('neg', self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        kind, val = self.peek()
        if val == '(':
            self.next()
            node = self.parse_expr()
            self.expect(')', '右括号')
            return node
        if kind == 'number':
            self.next()
            return ('num', float(val))
        if kind == 'name':
            return self.parse_name_expr()
        _unsupported(f'意外记号 {val!r}')

    def parse_name_expr(self):
        kind, name = self.next()
        if name in _UNSUPPORTED_KEYWORDS:
            _unsupported(f'{name} 语法')
        if name.endswith('_over_time'):
            _unsupported(f'{name}(...)')
        kind2, val2 = self.peek()
        if val2 == '(':
            return self.parse_call(name)
        # sum by (host) (expr)：修饰符前置形式
        if name in ('sum', 'avg', 'min', 'max') and kind2 == 'name' and val2 in ('by', 'without'):
            return self.parse_call(name)
        return self.parse_selector(name)

    def parse_call(self, name):
        grouping = None
        group_labels = []
        kind, val = self.peek()
        if kind == 'name' and val in ('by', 'without'):
            self.next()
            self.expect('(', '分组左括号')
            group_labels = self.parse_label_list()
            grouping = val
        self.expect('(', '函数左括号')
        if name in ('sum', 'avg', 'min', 'max'):
            arg = self.parse_expr()
            self.expect(')', '右括号')
            if grouping is None:
                kind2, val2 = self.peek()
                if kind2 == 'name' and val2 in ('by', 'without'):
                    self.next()
                    self.expect('(', '分组左括号')
                    group_labels = self.parse_label_list()
                    grouping = val2
            return ('agg', name, arg, grouping, group_labels)
        if name in ('rate', 'irate'):
            arg = self.parse_primary()
            self.expect(')', '右括号')
            if arg[0] != 'selector' or arg[3] is None:
                _unsupported(f'{name} 参数必须是带时间窗口的选择器，如 rate(x[5m])')
            return ('func', name, arg)
        if name in _UNSUPPORTED_FUNCS:
            _unsupported(f'{name}(...)')
        _unsupported(f'{name}(...)')

    def parse_label_list(self):
        labels = []
        while True:
            kind, label = self.peek()
            if kind != 'name':
                _unsupported('分组标签名缺失')
            self.next()
            labels.append(label)
            kind2, sep = self.peek()
            if sep == ',':
                self.next()
                continue
            if sep == ')':
                self.next()
                return labels
            _unsupported('分组标签列表语法')

    def parse_selector(self, name):
        matchers = []
        kind, val = self.peek()
        if val == '{':
            self.next()
            while True:
                k, label = self.next()
                if k != 'name':
                    _unsupported('标签名缺失')
                k2, op = self.next()
                if op not in ('=', '!=', '=~', '!~'):
                    _unsupported(f'标签匹配符 {op!r}')
                k3, value = self.next()
                if k3 != 'string':
                    _unsupported('标签值必须是字符串')
                matchers.append((label, op, value))
                k4, sep = self.peek()
                if sep == ',':
                    self.next()
                    continue
                if sep == '}':
                    self.next()
                    break
                _unsupported('标签列表语法')
        range_seconds = None
        kind, val = self.peek()
        if val == '[':
            self.next()
            k, dur = self.next()
            if k != 'duration':
                _unsupported('时间窗口必须是数字+单位，如 5m')
            self.expect(']', '右方括号')
            range_seconds = _duration_seconds(dur)
            kind2, val2 = self.peek()
            if val2 == ':':
                _unsupported('子查询 [5m:1m]')
        return ('selector', name, matchers, range_seconds)


# ── 求值 ───────────────────────────────────────────────────────

def _match_matchers(metric_labels, matchers):
    for label, op, value in matchers:
        actual = metric_labels.get(label, '')
        if op == '=':
            if actual != value:
                return False
        elif op == '!=':
            if actual == value:
                return False
        elif op == '=~':
            if not re.fullmatch(value, actual):
                return False
        elif op == '!~':
            if re.fullmatch(value, actual):
                return False
    return True


def _eval_timestamps(start, end, step):
    if end < start:
        _unsupported('end 早于 start')
    timestamps = []
    t = start
    while t <= end + 1e-9:
        timestamps.append(t)
        t += step
    return timestamps


def _eval(node, timestamps):
    """返回 ('scalar', float) 或 ('series', [{'metric': dict, 'points': [float]}])。"""
    kind = node[0]
    if kind == 'num':
        return ('scalar', node[1])

    if kind == 'selector':
        name = node[1]
        if name not in DEMO_METRIC_SPECS:
            _unsupported(f'未知指标 {name}')
        if node[3] is not None:
            _unsupported('裸时间窗口选择器（仅 rate/irate 内可用）')
        series = []
        for s_name, labels, func in _all_series():
            if s_name != name or not _match_matchers(labels, node[2]):
                continue
            series.append({'metric': {'__name__': name, **labels},
                           'points': [func(labels, t) for t in timestamps]})
        return ('series', series)

    if kind == 'func':
        # rate/irate：arg = ('selector', name, matchers, range_seconds)
        _, name, matchers, range_seconds = node[2]
        if name not in DEMO_METRIC_SPECS:
            _unsupported(f'未知指标 {name}')
        func_name = node[1]
        window = range_seconds if func_name == 'rate' else max(60.0, timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 60.0)
        series = []
        for s_name, labels, func in _all_series():
            if s_name != name or not _match_matchers(labels, matchers):
                continue
            points = []
            for t in timestamps:
                if func_name == 'irate' and len(timestamps) > 1:
                    window = timestamps[1] - timestamps[0]
                now_val = func(labels, t)
                prev_val = func(labels, t - window)
                points.append((now_val - prev_val) / window)
            series.append({'metric': {'__name__': name, **labels}, 'points': points})
        return ('series', series)

    if kind == 'neg':
        sub_kind, sub = _eval(node[1], timestamps)
        if sub_kind == 'scalar':
            return ('scalar', -sub)
        return ('series', [{'metric': s['metric'], 'points': [-v for v in s['points']]} for s in sub])

    if kind == 'bin':
        op = node[1]
        left_kind, left = _eval(node[2], timestamps)
        right_kind, right = _eval(node[3], timestamps)
        if left_kind == 'scalar' and right_kind == 'scalar':
            return ('scalar', _apply_bin(op, left, right))
        if left_kind == 'scalar':
            return ('series', [{'metric': s['metric'], 'points': [_apply_bin(op, left, v) for v in s['points']]} for s in right])
        if right_kind == 'scalar':
            return ('series', [{'metric': s['metric'], 'points': [_apply_bin(op, v, right) for v in s['points']]} for s in left])
        # series ⊙ series：按完整标签集合对齐
        by_metric = {tuple(sorted(s['metric'].items())): s for s in right}
        out = []
        for s in left:
            key = tuple(sorted(s['metric'].items()))
            if key in by_metric:
                other = by_metric[key]
                out.append({'metric': s['metric'],
                            'points': [_apply_bin(op, a, b) for a, b in zip(s['points'], other['points'])]})
        return ('series', out)

    if kind == 'cmp':
        op = node[1]
        left_kind, left = _eval(node[2], timestamps)
        right_kind, right = _eval(node[3], timestamps)
        if right_kind != 'scalar':
            _unsupported('序列对序列比较')
        if left_kind == 'scalar':
            return ('scalar', float(_apply_cmp(op, left, right)))
        # 演示简化：按序列末点值过滤整个序列（与瞬时查询语义一致）
        out = [s for s in left if _apply_cmp(op, s['points'][-1], right)]
        return ('series', out)

    if kind == 'agg':
        op, arg, grouping, group_labels = node[1], node[2], node[3], node[4]
        _, series = _eval(arg, timestamps)
        groups = {}
        for s in series:
            if grouping == 'by':
                key = tuple((k, s['metric'].get(k, '')) for k in group_labels)
                out_metric = {k: s['metric'].get(k, '') for k in group_labels}
            elif grouping == 'without':
                key = tuple((k, v) for k, v in sorted(s['metric'].items()) if k not in group_labels)
                out_metric = {k: v for k, v in s['metric'].items() if k not in group_labels}
            else:
                key = ()
                out_metric = {}
            groups.setdefault(key, {'metric': out_metric, 'points': [0.0] * len(timestamps), 'count': 0})
            target = groups[key]
            target['count'] += 1
            for i, v in enumerate(s['points']):
                if op == 'sum':
                    target['points'][i] += v
                elif op == 'avg':
                    target['points'][i] += v
                elif op == 'min':
                    target['points'][i] = v if target['count'] == 1 else min(target['points'][i], v)
                elif op == 'max':
                    target['points'][i] = v if target['count'] == 1 else max(target['points'][i], v)
        out = []
        for entry in groups.values():
            points = entry['points']
            if op == 'avg' and entry['count']:
                points = [v / entry['count'] for v in points]
            out.append({'metric': entry['metric'], 'points': points})
        return ('series', out)

    _unsupported(f'内部节点 {kind}')


def _apply_bin(op, a, b):
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        if b == 0:
            return float('nan')
        return a / b
    _unsupported(f'算术运算符 {op}')


def _apply_cmp(op, a, b):
    if op == '>':
        return a > b
    if op == '>=':
        return a >= b
    if op == '<':
        return a < b
    if op == '<=':
        return a <= b
    if op == '==':
        return a == b
    if op == '!=':
        return a != b
    _unsupported(f'比较运算符 {op}')


def _fmt(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return 'NaN'
    return format(value, '.10g')


# ── 入口 ───────────────────────────────────────────────────────

def evaluate_promql(expr, start_ts=None, end_ts=None, step=60, range_query=True):
    """求值 PromQL 子集，返回 Prometheus 兼容载荷。

    range_query=True:  {'resultType': 'matrix', 'result': [{'metric': {...}, 'values': [[ts, 'v'], ...]}]}
    range_query=False: {'resultType': 'vector', 'result': [{'metric': {...}, 'value': [ts, 'v']}]}
    顶层标量:          {'resultType': 'scalar', 'result': [ts, 'v']}
    """
    now = time.time()
    if end_ts is None:
        end_ts = now
    if start_ts is None:
        start_ts = end_ts - 3600
    step = max(1, float(step))
    timestamps = _eval_timestamps(float(start_ts), float(end_ts), step) if range_query else [float(end_ts)]
    node = _Parser(_tokenize(expr)).parse()
    kind, payload = _eval(node, timestamps)
    if kind == 'scalar':
        return {'resultType': 'scalar', 'result': [float(end_ts), _fmt(payload)]}
    if not range_query:
        return {
            'resultType': 'vector',
            'result': [{'metric': s['metric'], 'value': [float(end_ts), _fmt(s['points'][-1])]} for s in payload],
        }
    return {
        'resultType': 'matrix',
        'result': [
            {'metric': s['metric'], 'values': [[ts, _fmt(v)] for ts, v in zip(timestamps, s['points'])]}
            for s in payload
        ],
    }
