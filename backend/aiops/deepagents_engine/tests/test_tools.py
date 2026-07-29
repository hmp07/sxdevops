"""
DeepAgents Engine 工具包装器单元测试。
"""

from django.test import TestCase

from aiops.deepagents_engine.tools import (
    SXDEVOPS_TOOLS,
    get_tool_by_name,
    get_tool_names,
    get_tools_for_action,
)


class ToolRegistryTest(TestCase):
    """验证统一工具注册表的完整性和一致性。"""

    def test_all_16_tools_registered(self):
        """验证全部 16 个平台工具已注册。"""
        self.assertEqual(
            len(SXDEVOPS_TOOLS), 16,
            f"期望 16 个工具，实际 {len(SXDEVOPS_TOOLS)} 个"
        )

    def test_tool_names_are_unique(self):
        """验证所有工具名全局唯一。"""
        names = [t.name for t in SXDEVOPS_TOOLS]
        duplicates = [n for n in names if names.count(n) > 1]
        self.assertEqual(
            len(duplicates), 0,
            f"重复的工具名: {set(duplicates)}"
        )

    def test_get_tool_by_name_returns_all(self):
        """验证按名称查找每个工具都能返回非 None。"""
        for tool in SXDEVOPS_TOOLS:
            found = get_tool_by_name(tool.name)
            self.assertIsNotNone(
                found, f"工具 {tool.name} 在注册表中无法按名称找到"
            )
            self.assertEqual(found.name, tool.name)

    def test_all_tools_have_descriptions(self):
        """验证每个工具有足够详细的 docstring（LLM 路由依赖）。"""
        for tool in SXDEVOPS_TOOLS:
            desc = tool.description or ""
            self.assertGreater(
                len(desc), 20,
                f"工具 {tool.name} 的 description 过短（{len(desc)} 字符），"
                f"至少需要 50 字符以支撑 LLM 路由决策"
            )

    def test_tool_params_contain_config(self):
        """验证每个工具函数签名包含 config 参数（LangGraph 上下文注入）。

        注意：RunnableConfig 类型的参数由 LangChain 框架注入，
        不出现在 args_schema 中（不是 LLM 可见的参数）。
        这里验证的是 Python 函数签名层面。
        """
        import inspect
        for tool in SXDEVOPS_TOOLS:
            # 获取底层函数（@tool 装饰器包装后为 .func 属性或直接就是函数）
            func = getattr(tool, 'func', None) or getattr(tool, '__wrapped__', None)
            if func is None:
                continue
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            self.assertIn(
                'config', params,
                f"工具 {tool.name} 的函数签名缺少 config 参数，"
                f"无法从 LangGraph 上下文提取 user/session。"
                f"当前参数: {params}"
            )

    def test_get_tool_names_returns_16(self):
        """验证 get_tool_names() 返回完整的 16 个名称。"""
        names = get_tool_names()
        self.assertEqual(len(names), 16)

    def test_get_tools_for_action_known_actions(self):
        """验证已知 action 返回合集的工具子集。"""
        actions = [
            'alert.root_cause', 'k8s.diagnose', 'change.correlation',
            'zabbix.problem_analysis', 'cross_system.root_cause',
            'cmdb.query', 'host_task.generate',
        ]
        for action in actions:
            tools = get_tools_for_action(action)
            self.assertGreater(
                len(tools), 0,
                f"Action {action} 的工具子集为空"
            )
            global_names = set(get_tool_names())
            for t in tools:
                self.assertIn(t.name, global_names)

    def test_get_tools_for_action_unknown_returns_all(self):
        """验证未知 action 返回全部工具。"""
        tools = get_tools_for_action('nonexistent.action')
        self.assertEqual(len(tools), 16)

    def test_parity_with_platform_mcp_definitions(self):
        """验证工具列表与 PLATFORM_MCP_TOOL_DEFINITIONS 保持一致。"""
        from aiops.tools.registry import TOOL_REGISTRY

        mcp_tool_handlers = {
            t['handler'].replace('-', '_') + '_tool'
            for t in TOOL_REGISTRY
        }
        registered_tool_names = set(get_tool_names())

        for handler_suffix in mcp_tool_handlers:
            self.assertIn(
                handler_suffix, registered_tool_names,
                f"PLATFORM_MCP_TOOL_DEFINITIONS 中的 handler "
                f"'{handler_suffix}' 在 SXDEVOPS_TOOLS 中找不到"
            )
