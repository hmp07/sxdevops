"""Agent 创建与模型解析测试。"""
from django.test import TestCase
from aiops.deepagents_engine.agent import (
    create_sxdevops_agent,
    resolve_model_from_provider,
    _default_model,
)


class ModelResolutionTest(TestCase):
    """验证模型解析逻辑。"""

    def test_default_model_returns_string(self):
        model = _default_model()
        self.assertIsInstance(model, str)
        self.assertIn(':', model)  # provider:model format

    def test_resolve_model_from_provider(self):
        model = resolve_model_from_provider()
        self.assertIsInstance(model, str)
        self.assertGreater(len(model), 5)


class AgentCreationTest(TestCase):
    """验证 Agent 创建。"""

    def test_create_agent_without_subagents(self):
        agent = create_sxdevops_agent(
            model="anthropic:claude-sonnet-4-5-20250929",
            knowledge_environment={'name': 'test'},
            analysis_scope={'summary': {}},
            enable_subagents=False,
            enable_audit=False,
            enable_rbac=False,
            enable_persistence=False,
        )
        self.assertIsNotNone(agent)

    def test_create_agent_with_action_code(self):
        agent = create_sxdevops_agent(
            model="anthropic:claude-sonnet-4-5-20250929",
            action_code='alert.root_cause',
            enable_subagents=False,
            enable_audit=False,
            enable_rbac=False,
            enable_persistence=False,
        )
        self.assertIsNotNone(agent)
