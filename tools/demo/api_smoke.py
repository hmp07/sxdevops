"""演示容器 API 烟幕测试 — 覆盖 6 个演示问答与待确认动作链路。

运行: python tools/demo/api_smoke.py [--base http://localhost:8000]
"""

import argparse
import json
import urllib.request


BASE = 'http://localhost:8000'
_base = BASE


def api(method, path, token=None, payload=None):
    url = _BASE + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Token {token}')
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        print(f'HTTP {exc.code}: {body[:300]}')
        raise


def login():
    r = api('POST', '/api/auth/login/', payload={'username': 'admin', 'password': 'Admin@123456'})
    return r['token']


QUESTIONS = [
    '生产环境当前有哪些告警',
    '分析 order-center 库存校验超时的根因',
    '查一下 order-center 最近的错误日志',
    'Zabbix 上有哪些严重级别的磁盘问题',
    '帮我生成一个对订单相关主机的巡检任务',
    'CMDB 里订单中心依赖哪些系统',
]


def main():
    global _BASE
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default=BASE)
    args = parser.parse_args()
    _BASE = args.base

    token = login()
    print('登录成功\n')

    session = api('POST', '/api/aiops/sessions/', token, {'title': 'api-smoke'})
    sid = session['id']
    print(f'会话: {sid}\n')

    pending_id = None
    for q in QUESTIONS:
        print('=' * 72)
        print('Q:', q)
        r = api('POST', f'/api/aiops/sessions/{sid}/send_message/', token, {'content': q})
        am = r.get('assistant_message') or {}
        content = (am.get('content') or '')[:180].replace('\n', ' | ')
        meta = am.get('metadata') or {}
        tools = [t.get('name') for t in (am.get('tool_calls') or [])]
        pa = am.get('pending_action') or r.get('pending_action')
        print('A:', content)
        print('   engine:', meta.get('engine'), '| tools:', tools)
        if pa:
            pending_id = pa.get('id')
            print('   pending:', pa.get('action_type'), '|', pa.get('title'), '|', pa.get('status'))
        assert content, f'Q 无回答: {q}'

    if pending_id:
        print('=' * 72)
        print('确认待确认动作:', pending_id)
        r = api('POST', f'/api/aiops/actions/{pending_id}/confirm/', token, {})
        draft = r.get('task_draft') or r
        print('任务草稿:', draft.get('name'), '| hosts:', draft.get('host_count'),
              '| target:', draft.get('target_type'))

    print('\nSMOKE PASSED')


if __name__ == '__main__':
    main()
