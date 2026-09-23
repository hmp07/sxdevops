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

    def test_all_18_tools_registered(self):
        """验证全部 18 个平台工具已注册。"""
        self.assertEqual(
            len(SXDEVOPS_TOOLS), 18,
            f"期望 18 个工具，实际 {len(SXDEVOPS_TOOLS)} 个"
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

    def test_get_tool_names_returns_18(self):
        """验证 get_tool_names() 返回完整的 18 个名称。"""
        names = get_tool_names()
        self.assertEqual(len(names), 18)

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
        self.assertEqual(len(tools), 18)

    def test_new_metric_tools_registered_in_registry(self):
        """TOOL_REGISTRY 包含智能问数与资源预测两个新工具。"""
        from aiops.tools.registry import TOOL_REGISTRY
        self.assertEqual(len(TOOL_REGISTRY), 18)
        handlers = {t['handler'] for t in TOOL_REGISTRY}
        self.assertIn('query_metrics_promql', handlers)
        self.assertIn('query_resource_forecast', handlers)
        by_name = {t['deepagents_name'] for t in TOOL_REGISTRY}
        self.assertIn('query_metrics_promql_tool', by_name)
        self.assertIn('query_resource_forecast_tool', by_name)

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


class NewMetricToolsTests(TestCase):
    """智能问数与资源预测两个新工具的端到端行为（演示数据源 fixture）。"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.core.cache import cache
        from aiops.models import AIOpsChatSession
        from ops.models import MetricDataSource, ZabbixDataSource

        cache.clear()
        self.admin = get_user_model().objects.create_superuser('tool-admin', 'a@example.com', 'Admin@123456')
        self.limited = get_user_model().objects.create_user('tool-limited', 'b@example.com', 'User@123456')
        self.session = AIOpsChatSession.objects.create(user=self.admin, title='工具测试会话')
        MetricDataSource.objects.create(
            name='Prometheus 演示数据源', provider='prometheus', tsdb_type='prometheus',
            config={'demo_mode': True}, is_enabled=True, is_default=True)
        ZabbixDataSource.objects.create(
            name='Zabbix 演示数据源', api_url='demo://', auth_type='token',
            auth_token='demo-token', tls_verify=False, timeout=10,
            is_enabled=True, is_default=True)

    def test_query_metrics_promql_demo_returns_series(self):
        from aiops.tools import query_metrics_promql
        result = query_metrics_promql(
            self.session, None, self.admin,
            promql='rate(http_requests_total{service="order-service",code="200"}[5m])',
            range_query=True, duration_minutes=60, step=60, limit=6)
        self.assertIn('summary', result)
        self.assertEqual(result['summary'].get('series_count'), 1)
        self.assertIn('promql', result)
        self.assertEqual(result['promql']['source'], 'prometheus_demo')

    def test_query_resource_forecast_disk_demo(self):
        from aiops.tools import query_resource_forecast
        result = query_resource_forecast(
            self.session, None, self.admin,
            hostname='order-api-ecs-01', metric='disk', lookback_hours=24, horizon_hours=6)
        summary = result['summary']
        self.assertEqual(summary['hostname'], 'order-api-ecs-01')
        self.assertGreater(summary['current'], 80, msg='故事线磁盘使用率应已超过 80%')
        self.assertIn('threshold_eta_text', summary)
        self.assertIn('chart', result)
        self.assertEqual(result['chart']['type'], 'line')
        self.assertTrue(result['chart']['categories'])
        self.assertEqual(len(result['chart']['categories']),
                         len(result['chart']['values']) + len(result['chart']['forecast']))

    def test_query_resource_forecast_unknown_hostname(self):
        from aiops.tools import query_resource_forecast
        result = query_resource_forecast(
            self.session, None, self.admin, hostname='no-such-host', metric='disk')
        self.assertIn('未找到主机', result['summary'].get('error', ''))

    def test_new_tools_denied_without_metric_permission(self):
        from aiops.tools import query_metrics_promql, query_resource_forecast
        promql_result = query_metrics_promql(
            self.session, None, self.limited, promql='node_cpu_usage_percent')
        self.assertEqual(promql_result, {'sections': [], 'citations': []})
        forecast_result = query_resource_forecast(
            self.session, None, self.limited, hostname='order-api-ecs-01', metric='disk')
        self.assertEqual(forecast_result, {'sections': [], 'citations': []})
