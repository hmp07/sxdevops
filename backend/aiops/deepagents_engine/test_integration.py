"""
DeepAgents 能力集成测试 — 覆盖 Phase 1-5 所有新增功能。

运行: cd backend && python manage.py test aiops.deepagents_engine.test_integration
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ── Phase 1: Skill 系统测试 ────────────────────────────────────────────────


class SkillLoadingTests(TestCase):
    """测试 skills.py 的 load_active_skills() 和 build_skill_trace()"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 确保 services.py 中的 BUILTIN_SKILLS 已 seed
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sxdevops.settings')
        import django
        django.setup()

    def test_load_active_skills_no_config(self):
        """无配置时加载所有 enabled Skills。"""
        from aiops.deepagents_engine.skills import load_active_skills

        skills = load_active_skills(config=None, action_code=None, user=None)
        self.assertIsInstance(skills, list)
        # 应该有至少 1 个 builtin Skill (answer-formatter)
        if skills:
            skill = skills[0]
            self.assertIn('name', skill)
            self.assertIn('slug', skill)
            self.assertIn('content', skill)
            self.assertIn('tools', skill)
            self.assertIn('output_contract', skill)

    def test_load_active_skills_filter_by_action(self):
        """按 action_code 过滤 Skill。"""
        from aiops.deepagents_engine.skills import load_active_skills

        skills_alert = load_active_skills(config=None, action_code='alert.root_cause', user=None)
        skills_all = load_active_skills(config=None, action_code=None, user=None)
        # action 过滤后的 Skills 数量 ≤ 全部 Skills
        self.assertLessEqual(len(skills_alert), len(skills_all))

    def test_answer_formatter_always_appended(self):
        """answer-formatter Skill 始终在过滤后出现。"""
        from aiops.deepagents_engine.skills import load_active_skills

        skills = load_active_skills(config=None, action_code='alert.root_cause', user=None)
        slugs = [s['slug'] for s in skills]
        if 'answer-formatter' in [s['slug'] for s in load_active_skills(config=None)]:
            self.assertIn('answer-formatter', slugs,
                          "answer-formatter 应该在所有 action 过滤后始终存在")

    def test_build_skill_trace(self):
        """skill_trace 结构正确。"""
        from aiops.deepagents_engine.skills import build_skill_trace

        skills = [
            {'id': 1, 'slug': 'test-skill', 'name': 'Test',
             'applicable_actions': ['alert.root_cause'],
             'tools': ['query_alerts_tool'], 'content': 'test'}
        ]
        trace = build_skill_trace(skills, action_code='alert.root_cause',
                                  tool_calls=['query_alerts_tool'],
                                  formatter_used=True, formatter_fell_back=False)
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]['status'], 'matched')
        self.assertEqual(trace[0]['hit_reason'], 'action_router')
        self.assertEqual(trace[0]['used_tools'], ['query_alerts_tool'])

    def test_build_skills_prompt_section(self):
        """Skill prompt 段落包含关键内容。"""
        from aiops.deepagents_engine.skills import build_skills_prompt_section

        skills = [
            {'name': 'Test Skill', 'slug': 'test-skill', 'category': 'test',
             'description': 'A test skill', 'applicable_actions': ['alert.root_cause'],
             'tools': ['query_alerts_tool'], 'content': 'SOP: Do X.'}
        ]
        section = build_skills_prompt_section(skills)
        self.assertIn('Test Skill', section)
        self.assertIn('SOP: Do X.', section)
        self.assertIn('query_alerts_tool', section)

    def test_build_skills_prompt_section_empty(self):
        """无 Skills 时返回友好提示。"""
        from aiops.deepagents_engine.skills import build_skills_prompt_section

        section = build_skills_prompt_section([])
        self.assertIn('无启用 Skill', section)


# ── Phase 2: MCP 工具测试 ──────────────────────────────────────────────────


class MCPToolsTests(TestCase):
    """测试 mcp_tools.py 的 build_external_mcp_tools()"""

    def test_build_external_mcp_tools_empty(self):
        """无外部 MCP Server 时返回空列表。"""
        from aiops.deepagents_engine.mcp_tools import build_external_mcp_tools

        tools, registry, sessions, diagnostics = build_external_mcp_tools([])
        self.assertEqual(tools, [])
        self.assertEqual(registry, {})
        self.assertEqual(sessions, [])
        self.assertIsInstance(diagnostics, list)

    def test_mcp_tool_alias_format(self):
        """别名格式为 mcp__{server}__{tool}。"""
        from aiops.deepagents_engine.mcp_tools import _build_mcp_tool_alias

        mock_server = MagicMock()
        mock_server.name = 'iTop CMDB MCP'
        alias = _build_mcp_tool_alias(mock_server, 'itop_get_cis')
        self.assertTrue(alias.startswith('mcp__'))
        self.assertIn('itop', alias.lower())
        self.assertIn('get_cis', alias)


# ── Phase 3: Fastpath 扩展测试 ─────────────────────────────────────────────


class FastpathExtendedTests(TestCase):
    """测试 fastpath.py 的新增模式 (6 → 12)。"""

    def test_log_query_fastpath_hit(self):
        """日志查询模式命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('查一下最近半小时的日志')
        self.assertEqual(tool, 'query_logs_tool')
        self.assertIn('duration_minutes', params)
        self.assertEqual(params['duration_minutes'], 30)

    def test_trace_query_fastpath_hit(self):
        """链路追踪模式命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('链路追踪里有没有异常')
        self.assertEqual(tool, 'query_traces_tool')
        self.assertTrue(params.get('errors_only'))

    def test_k8s_resource_lookup_hit(self):
        """K8s 资源查询模式命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('k8s集群有哪些pod异常')
        self.assertEqual(tool, 'query_k8s_cluster_summary_tool')

    def test_knowledge_graph_lookup_hit(self):
        """知识图谱查询模式命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('查一下系统依赖关系')
        self.assertEqual(tool, 'query_knowledge_graph_tool')

    def test_alert_metrics_hit(self):
        """告警指标趋势查询命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('查一下最近的CPU趋势')
        self.assertEqual(tool, 'query_alert_metrics_tool')

    def test_workorder_query_hit(self):
        """工单查询模式命中。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        tool, params = fastpath_router('最近有哪些工单')
        self.assertEqual(tool, 'query_recent_changes_tool')

    def test_no_false_positive_on_complex_questions(self):
        """复杂分析问题不误命中 fastpath。"""
        from aiops.deepagents_engine.fastpath import fastpath_router

        # 这些应该由 LLM 处理，不该被 fastpath 拦截
        tool, _ = fastpath_router('分析一下这个变更对告警的影响')
        self.assertIsNone(tool)
        tool, _ = fastpath_router('为什么部署后CPU升高了')
        self.assertIsNone(tool)


# ── Phase 4-5: System Prompt + Agent 参数测试 ──────────────────────────────


class SystemPromptIntegrationTests(TestCase):
    """测试 system_prompt.py 的新增参数。"""

    def test_build_system_prompt_with_skills(self):
        """Skills 信息出现在 system prompt 中。"""
        from aiops.deepagents_engine.system_prompt import build_system_prompt

        skills = [
            {'name': 'Test Skill', 'slug': 'test-skill', 'category': 'test',
             'description': 'A test skill', 'applicable_actions': ['alert.root_cause'],
             'tools': ['query_alerts_tool', 'query_zabbix_problems_tool'],
             'content': 'SOP: Check alerts first, then check Zabbix.'}
        ]
        prompt = build_system_prompt(
            {'name': 'test-env'}, {'summary': {'alert_sources': 1, 'host_count': 5, 'ci_count': 10}},
            ['aiops.chat.view'], active_skills=skills,
        )
        self.assertIn('Test Skill', prompt)
        self.assertIn('SOP: Check alerts first', prompt)
        self.assertIn('query_alerts_tool', prompt)

    def test_build_system_prompt_with_mcp_diagnostics(self):
        """MCP 诊断信息出现在 system prompt 中。"""
        from aiops.deepagents_engine.system_prompt import build_system_prompt

        diag = [
            {'name': 'External MCP', 'status': 'connected',
             'server_type': 'http', 'tool_count': 5, 'message': ''},
        ]
        prompt = build_system_prompt(
            {'name': 'test'}, {'summary': {'alert_sources': 0, 'host_count': 0, 'ci_count': 0}},
            [], mcp_diagnostics=diag,
        )
        self.assertIn('External MCP', prompt)
        self.assertIn('已连接', prompt)
        self.assertIn('5 个外部工具', prompt)

    def test_build_system_prompt_with_agent_mode(self):
        """Agent mode 信息出现在 system prompt 中。"""
        from aiops.deepagents_engine.system_prompt import build_system_prompt

        prompt = build_system_prompt(
            {'name': 'test'}, {'summary': {'alert_sources': 0, 'host_count': 0, 'ci_count': 0}},
            [], agent_mode='direct',
        )
        self.assertIn('Direct', prompt)

    def test_build_system_prompt_without_skills(self):
        """无 Skills 时显示友好提示。"""
        from aiops.deepagents_engine.system_prompt import build_system_prompt

        prompt = build_system_prompt(
            {'name': 'test'}, {'summary': {'alert_sources': 0, 'host_count': 0, 'ci_count': 0}},
            [],
        )
        self.assertIn('无启用 Skill', prompt)


# ── Agent Mode 测试 ─────────────────────────────────────────────────────────


class AgentModeTests(TestCase):
    """测试 _resolve_agent_mode()。"""

    def test_resolve_agent_mode_default(self):
        """无 action_code 时默认 react。"""
        from aiops.deepagents_engine.adapter import _resolve_agent_mode

        mode = _resolve_agent_mode(None)
        self.assertEqual(mode, 'react')

    def test_resolve_agent_mode_unknown_code(self):
        """未知 action_code 回退 react。"""
        from aiops.deepagents_engine.adapter import _resolve_agent_mode

        mode = _resolve_agent_mode('nonexistent.action')
        self.assertEqual(mode, 'react')
