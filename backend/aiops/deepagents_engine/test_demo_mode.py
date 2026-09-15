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

    def test_question_override_routing(self):
        """演示问题精确覆盖表优先命中。"""
        from aiops.deepagents_engine.demo_mock_model import DemoMockChatModel

        model = DemoMockChatModel()
        tool, args, pending = model._build_tool_plan('帮我生成一个对订单相关主机的巡检任务')
        self.assertEqual(tool, 'query_zabbix_hosts_tool')
        self.assertEqual(args['search'], 'order')
        self.assertIsNotNone(pending)

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
