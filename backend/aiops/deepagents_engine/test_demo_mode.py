"""
离线演示模式测试 — DemoMockChatModel 驱动真实 DeepAgents 循环。

运行: cd backend && python manage.py test aiops.deepagents_engine.test_demo_mode
"""

from __future__ import annotations

import os
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase


class DemoMockModelUnitTests(TestCase):
    """DemoMockChatModel 单元测试（不依赖种子数据）。"""

    def test_is_demo_mode_flag(self):
        from aiops.deepagents_engine.demo_mock_model import is_demo_mode

        self.assertFalse(is_demo_mode())
        with patch.dict(os.environ, {'SXDEVOPS_DEMO_MODE': '1'}):
            self.assertTrue(is_demo_mode())

    def test_llm_demo_mock_flag_combinations(self):
        """SXDEVOPS_LLM_DEMO_MOCK 优先，未设置时回落 SXDEVOPS_DEMO_MODE。"""
        from aiops.deepagents_engine.demo_mock_model import llm_demo_mock_enabled

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(llm_demo_mock_enabled())
        with patch.dict(os.environ, {'SXDEVOPS_DEMO_MODE': '1'}):
            self.assertTrue(llm_demo_mock_enabled())
        with patch.dict(os.environ, {'SXDEVOPS_DEMO_MODE': '1', 'SXDEVOPS_LLM_DEMO_MOCK': '0'}):
            self.assertFalse(llm_demo_mock_enabled(), msg='真实模型开关应压过 DEMO_MODE')
        with patch.dict(os.environ, {'SXDEVOPS_LLM_DEMO_MOCK': '1'}):
            self.assertTrue(llm_demo_mock_enabled())

    def test_question_override_routing(self):
        """演示问题精确覆盖表优先命中。"""
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        tool, args, pending = model._build_tool_plan('帮我生成一个对订单相关主机的巡检任务')
        self.assertEqual(tool, 'query_zabbix_hosts_tool')
        self.assertEqual(args['search'], 'order')
        self.assertIsNotNone(pending)

    def test_question_override_routing_new_capabilities(self):
        """新增演示问题覆盖：智能问数 / 趋势预测 / 告警统计。"""
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        tool, args, pending = model._build_tool_plan('生产环境 order 服务的请求量和错误率是多少')
        self.assertEqual(tool, 'query_metrics_promql_tool')
        self.assertIn('rate(http_requests_total', args['promql'])
        self.assertIsNone(pending)

        tool, args, _ = model._build_tool_plan('order-api-ecs-01 磁盘使用率趋势和预测')
        self.assertEqual(tool, 'query_resource_forecast_tool')
        self.assertEqual(args['hostname'], 'order-api-ecs-01')
        self.assertEqual(args['metric'], 'disk')

        tool, args, _ = model._build_tool_plan('统计一下本周生产环境的告警')
        self.assertEqual(tool, 'query_alerts_tool')
        self.assertEqual(args['date_filter'], 'week')

    def test_render_metrics_chart_block(self):
        """指标问数渲染包含结论与 ```chart 折线。"""
        from aiops.deepagents_engine.demo_mock_model import render_answer

        data = {
            'summary': {'series_count': 1, 'source': 'prometheus_demo', 'range': True},
            'sections': [{'title': '指标查询结果', 'items': ['http_requests_total: 120 req/s']}],
            'promql': {
                'result': [{'metric': {'service': 'order-service'},
                            'values': [[1728000000.0 + i * 60, str(100 + i)] for i in range(24)]}],
            },
        }
        answer = render_answer('query_metrics_promql_tool', data)
        self.assertIn('## 结论', answer)
        self.assertIn('```chart', answer)
        self.assertIn('http_requests_total', answer)

    def test_render_forecast_threshold_text(self):
        """趋势预测渲染包含阈值到达时间与置信区间说明。"""
        from aiops.deepagents_engine.demo_mock_model import render_answer

        data = {
            'summary': {
                'hostname': 'order-api-ecs-01', 'metric_label': '磁盘使用率',
                'current': 92.0, 'trend': '上升',
                'threshold_eta_text': '按当前增速约 3 天后达到 95%',
            },
            'sections': [{'title': '预测结论', 'items': ['未来 6 小时预测：92.0% → 94.5%（置信带宽 ±1.2%）']}],
            'chart': {
                'type': 'line', 'title': 'order-api-ecs-01 磁盘使用率趋势与预测',
                'categories': ['09-22 10:00', '09-22 11:00', '09-22 12:00', '09-22 13:00', '09-22 14:00'],
                'values': [90.0, 91.0, 92.0],
                'forecast': [92.5, 93.0],
                'upper': [93.5, 94.0],
                'lower': [91.5, 92.0],
            },
        }
        answer = render_answer('query_resource_forecast_tool', data)
        self.assertIn('92.0%', answer)
        self.assertIn('3 天后达到 95%', answer)
        self.assertIn('```chart', answer)

    def test_greeting_answer(self):
        """无工具路由的寒暄问题返回引导语。"""
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        content = model._greeting_answer('你好')
        self.assertIn('SxDevOps', content)

    def test_strip_env_prefix(self):
        from aiops.deepagents_engine.demo_mock_model import _strip_env_prefix

        self.assertEqual(
            _strip_env_prefix('[环境: 默认环境] 生产环境当前有哪些告警'),
            '生产环境当前有哪些告警',
        )
        self.assertEqual(_strip_env_prefix('无前缀问题'), '无前缀问题')

    def test_render_answer_two_phase_structure(self):
        """答案渲染保持二阶段结构且只引用工具数据。"""
        from aiops.deepagents_engine.demo_mock_model import render_answer

        data = {
            'summary': {'count': 3, 'critical': 1},
            'sections': [{
                'title': '告警明细',
                'items': [
                    'ID 1 / 严重 / 库存服务响应超时 / APM / 活跃',
                    'ID 2 / 警告 / 重试风暴 / APM / 活跃',
                ],
            }],
        }
        answer = render_answer('query_alerts_tool', data)
        self.assertIn('## 结论', answer)
        self.assertIn('## 关键证据', answer)
        self.assertIn('## 建议操作', answer)
        self.assertIn('库存服务响应超时', answer)

    def test_render_answer_zabbix_hosts_shape(self):
        """Zabbix hosts 直接键形状渲染。"""
        from aiops.deepagents_engine.demo_mock_model import render_answer

        data = {
            'hosts': [
                {'hostid': '10001', 'host': 'order-api-ecs-01', 'status': '0'},
                {'hostid': '10002', 'host': 'order-api-ecs-02', 'status': '0'},
            ],
            'total': 2,
        }
        answer = render_answer('query_zabbix_hosts_tool', data)
        self.assertIn('2 台 Zabbix 监控主机', answer)
        self.assertIn('order-api-ecs-01', answer)

    def test_pending_plan_shape(self):
        """待确认动作计划满足 confirm_action 的 payload 形状。"""
        from aiops.deepagents_engine.demo_mock_model import build_demo_task_pending_plan

        plan = build_demo_task_pending_plan('帮我生成一个巡检任务')
        payload = plan['payload']
        for key in ('name', 'task_type', 'target_type', 'host_ids', 'payload', 'execution_mode'):
            self.assertIn(key, payload)


class DemoMockModelIntegrationTests(TransactionTestCase):
    """演示模式集成测试 — 假模型驱动真实 agent 循环（空测试库仅验证机制）。

    使用 TransactionTestCase：LangGraph ToolNode 在线程池中执行工具，
    TestCase 的事务包裹会导致 SQLite 测试库写锁冲突。
    """

    reset_sequences = True

    def setUp(self):
        from django.contrib.auth import get_user_model
        from aiops.models import AIOpsChatSession

        User = get_user_model()
        self.user = User.objects.create_user(
            username='demo-test-user', password='x',
        )
        self.session = AIOpsChatSession.objects.create(title='demo-test', user=self.user)

    def test_agent_loop_with_fake_model(self):
        """假模型在真实 DeepAgents 循环内：发工具调用 → 工具执行 → 模板答案。"""
        from aiops.deepagents_engine.agent import create_sxdevops_agent
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        agent = create_sxdevops_agent(
            model=model,  # type: ignore[arg-type]
            knowledge_environment={'name': '默认环境'},
            analysis_scope={},
            user=self.user,
            session_id=self.session.id,
            assistant_message_id=None,
            action_code=None,
            active_skills=[],
            external_tools=None,
            mcp_diagnostics=[],
            agent_mode='react',
            enable_subagents=False,
            enable_audit=False,
            enable_rbac=False,
        )
        result = agent.invoke(
            {'messages': [{'role': 'user', 'content': '生产环境当前有哪些告警'}]},
            config={
                'configurable': {
                    'thread_id': 'demo-test-thread',
                    'user_id': self.user.id,
                    'session_id': self.session.id,
                }
            },
        )
        messages = result.get('messages', [])
        # 有工具消息（工具真实执行了）
        tool_msgs = [m for m in messages if getattr(m, 'type', '') == 'tool']
        self.assertGreaterEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0].name, 'query_alerts_tool')
        # 最终 AI 答案为二阶段结构
        final = ''
        for msg in reversed(messages):
            if getattr(msg, 'type', '') == 'ai' and getattr(msg, 'content', ''):
                final = str(msg.content)
                break
        self.assertIn('## 结论', final)

    def test_attach_demo_pending_action(self):
        """生成任务类问题附着待确认动作；普通问题不附着。"""
        from aiops.deepagents_engine.demo_mock_model import attach_demo_pending_action

        result = {'messages': []}
        attach_demo_pending_action(result, '生产环境当前有哪些告警')
        self.assertNotIn('pending_actions', result)

        result2 = {'messages': []}
        attach_demo_pending_action(result2, '帮我生成一个对订单相关主机的巡检任务')
        self.assertIn('pending_actions', result2)
        pa = result2['pending_actions'][0]
        self.assertEqual(pa['type'], 'execute_host_task')
        self.assertEqual(pa['risk_level'], 'low')


class OracleDemoQuestionTests(TestCase):
    """Oracle 域演示问答：覆盖表路由、闭包渲染器、fastpath 路由。"""

    def test_oracle_override_routing(self):
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        tool, args, _ = model._build_tool_plan('ORCL01 为什么报 ORA-01653')
        self.assertEqual(tool, 'query_alert_root_cause_tool')
        self.assertIn('ORA-01653', args.get('query', ''))

        tool, args, _ = model._build_tool_plan('ORCL01 表空间满影响了哪些下游')
        self.assertEqual(tool, 'query_knowledge_graph_closure_tool')
        self.assertEqual(args.get('node_name'), 'TS_ORDER')

    def test_closure_renderer_registered_and_outputs_paths(self):
        from aiops.deepagents_engine.demo_mock_model import _ANSWER_RENDERERS

        renderer = _ANSWER_RENDERERS.get('query_knowledge_graph_closure_tool')
        self.assertIsNotNone(renderer, '闭包工具应注册渲染器')
        data = {
            'summary': {'path_count': 1, 'node_count': 3, 'truncated': False, 'cycle_detected': False},
            'sections': [{'title': '因果闭包（≤5 跳）', 'content': 'TS_ORDER --包含--> ts_order_01.dbf'}],
        }
        text = renderer(data)
        self.assertIn('TS_ORDER', text)
        self.assertIn('1 条依赖路径', text)

    def test_fastpath_closure_routing(self):
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('TS_ORDER 影响哪些下游')
        self.assertEqual(tool, 'query_knowledge_graph_closure_tool')
