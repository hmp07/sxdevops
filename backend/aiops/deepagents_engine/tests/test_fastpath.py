"""Fastpath 路由器测试。"""
from django.test import TestCase
from aiops.deepagents_engine.fastpath import (
    fastpath_router,
    FASTPATH_PATTERNS,
    _strip_noise,
    _extract_hostname,
)


class FastpathPatternTest(TestCase):
    """验证快速路由模式匹配。"""

    def test_seven_patterns_defined(self):
        self.assertEqual(len(FASTPATH_PATTERNS), 7)

    def test_alert_list_matches(self):
        tool, params = fastpath_router('查询今天的告警')
        self.assertEqual(tool, 'query_alerts_tool')
        self.assertEqual(params.get('date_filter'), 'today')

    def test_cmdb_query_matches(self):
        tool, params = fastpath_router('电商平台有哪些服务器')
        self.assertEqual(tool, 'query_cmdb_items_tool')

    def test_zabbix_problems_matches(self):
        tool, _ = fastpath_router('查询Zabbix当前的严重问题')
        self.assertEqual(tool, 'query_zabbix_problems_tool')

    def test_k8s_lookup_matches(self):
        tool, _ = fastpath_router('Pod异常重启怎么办')
        self.assertEqual(tool, 'query_k8s_cluster_summary_tool')

    def test_irrelevant_query_no_match(self):
        tool, params = fastpath_router('帮我写首诗')
        self.assertIsNone(tool)

    def test_host_metrics_defers_to_llm(self):
        tool, _ = fastpath_router('Dataease1的CPU使用率')
        self.assertIsNone(tool)  # needs multi-step, defers to LLM

    def test_strip_noise(self):
        result = _strip_noise('请帮我查询今天的告警统计')
        self.assertNotIn('请帮我', result)
        self.assertNotIn('统计', result)

    def test_extract_hostname(self):
        self.assertEqual(_extract_hostname('Dataease1的CPU使用率'), 'Dataease1')
        self.assertEqual(_extract_hostname('192.168.1.1的状态'), '192.168.1.1')
