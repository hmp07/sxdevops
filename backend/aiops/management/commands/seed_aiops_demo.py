"""AIOps 演示数据种子 — 补齐智能体域的演示数据。

覆盖：
1. 知识环境绑定（Zabbix 演示数据源 / K8s / Docker / 告警与事件环境）
2. 离线演示模型 provider 行（demo 模式下引擎不真正调用，仅用于配置页展示）
3. 2 个演示会话 + 消息 + 工具/模型调用审计（智能体审计页展示）
4. 3 个 Runbook（应急手册）
5. 4 个内置 Skill（演示 SOP）
6. 1 个停用的外部 MCP Server 行（MCP 列表页展示）

幂等：按 slug/name update_or_create；演示会话按固定标题清理重建。
可单独运行：python manage.py seed_aiops_demo
也可由 seed_data 统一调用。
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone


DEMO_SESSION_TITLES = [
    'order-center 库存超时排查',
    'Zabbix 生产监控问题分析',
]


class Command(BaseCommand):
    help = '生成 AIOps 演示数据（知识环境绑定/演示会话/审计/Runbook/Skill）'

    def handle(self, *args, **options):
        stdout = self.stdout
        user = self._demo_user(stdout)

        self._bind_knowledge_environment(stdout)
        self._seed_demo_provider(stdout)
        self._seed_skills(stdout)
        self._seed_runbooks(stdout, user)
        self._seed_mcp_row(stdout)
        self._seed_sessions(stdout, user)

        stdout.write(self.style.SUCCESS('AIOps 演示数据完成'))

    # ── 用户 ─────────────────────────────────────────────────────────

    def _demo_user(self, stdout):
        User = get_user_model()
        user = User.objects.filter(username='admin').first()
        if not user:
            # 演示管理员口令：默认使用项目文档化的演示口令（README 体验账号），
            # 可通过环境变量覆盖。非演示环境建议执行前设置 SXDEVOPS_DEMO_ADMIN_PASSWORD。
            import os
            password = os.environ.get('SXDEVOPS_DEMO_ADMIN_PASSWORD') or 'Admin@123456'
            user = User.objects.create_superuser(
                username='admin', email='admin@example.com', password=password
            )
            if not os.environ.get('SXDEVOPS_DEMO_ADMIN_PASSWORD'):
                stdout.write(self.style.WARNING(
                    '已创建演示管理员 admin（默认演示口令，仅限演示环境；'
                    '生产部署请勿使用演示种子）'
                ))
            else:
                stdout.write('已创建演示管理员 admin（口令来自 SXDEVOPS_DEMO_ADMIN_PASSWORD）')
        return user

    # ── 知识环境绑定 ─────────────────────────────────────────────────

    def _bind_knowledge_environment(self, stdout):
        from aiops.models import AIOpsKnowledgeEnvironment
        from ops.models import (
            DockerHost,
            K8sCluster,
            LogDataSource,
            MetricDataSource,
            TracingDataSource,
            ZabbixDataSource,
        )

        env = AIOpsKnowledgeEnvironment.objects.filter(is_default=True).first()
        if env is None:
            from aiops.models import AIOpsKnowledgeEnvironment as _E
            env = _E.objects.create(
                name='默认环境', is_default=True, is_enabled=True,
                description='离线演示知识环境',
            )

        def _ids(qs, limit=10):
            return list(qs.values_list('id', flat=True)[:limit])

        env.aliases = ['生产环境', '生产', 'prod', '默认']
        env.event_environments = ['prod', 'staging', 'shared']
        env.alert_environments = ['prod', 'staging']
        env.zabbix_datasource_ids = _ids(ZabbixDataSource.objects.filter(is_enabled=True))
        env.k8s_cluster_ids = _ids(K8sCluster.objects.all())
        env.docker_host_ids = _ids(DockerHost.objects.filter(status='connected'))
        # 演示环境不绑定外部日志/指标/链路数据源：
        # 日志查询回落到平台 LogEntry（种子故事日志），避免离线环境查询空数据源
        env.metric_datasource_ids = []
        env.log_datasource_ids = []
        env.tracing_datasource_ids = []
        env.observability_link_ids = []
        env.save(update_fields=[
            'aliases', 'event_environments', 'alert_environments',
            'zabbix_datasource_ids', 'k8s_cluster_ids', 'docker_host_ids',
            'metric_datasource_ids', 'log_datasource_ids', 'tracing_datasource_ids',
            'observability_link_ids',
        ])
        # 停用外部日志/指标/链路数据源（离线演示无法连接真实系统）：
        # 停用后 AI 查询自动回落平台 LogEntry / 本地数据
        LogDataSource.objects.filter(is_enabled=True).update(is_enabled=False)
        MetricDataSource.objects.filter(is_enabled=True).update(is_enabled=False)
        TracingDataSource.objects.filter(is_enabled=True).update(is_enabled=False)
        stdout.write(
            f'知识环境绑定完成: zabbix={len(env.zabbix_datasource_ids or [])}, '
            f'k8s={len(env.k8s_cluster_ids or [])}, docker={len(env.docker_host_ids or [])}'
        )

    # ── 演示模型 provider ────────────────────────────────────────────

    def _seed_demo_provider(self, stdout):
        from aiops.models import AIOpsModelProvider

        provider, created = AIOpsModelProvider.objects.update_or_create(
            name='离线演示模型',
            defaults={
                'provider_type': AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
                'base_url': 'demo://offline',
                'provider_preset': 'custom_openai_compatible',
                'default_model': 'sxdevops-demo-mock',
                'temperature': 0.3,
                'max_tokens': 2048,
                'is_enabled': True,
                'last_test_status': 'success',
                'last_test_message': '离线演示模式无需真实 API Key',
            },
        )
        # 演示模式下 api_key 只是占位（引擎不真实调用）
        provider.set_api_key('demo-offline-key')
        provider.save(update_fields=['api_key_encrypted'])
        stdout.write(f'演示模型 provider: {"created" if created else "updated"}')

    # ── 内置 Skill ───────────────────────────────────────────────────

    def _seed_skills(self, stdout):
        from aiops.models import AIOpsSkill

        skills = [
            {
                'name': '证据优先应答',
                'slug': 'evidence-first-answer',
                'description': '所有结论必须基于工具查询到的平台事实，禁止编造数据。',
                'category': '应答规范',
                'applicable_actions': ['alert.root_cause', 'zabbix.problem_analysis', 'cmdb.query'],
                'examples': ['分析 order-center 库存校验超时的根因'],
                'recommended_tools': ['query_alerts_tool', 'query_logs_tool'],
                'risk_level': AIOpsSkill.RISK_READ_ONLY,
                'output_contract': '结论/关键证据/风险评估/建议操作 四段式',
                'content': (
                    'SOP：\n'
                    '1. 先用 query_alerts_tool 获取告警事实\n'
                    '2. 再用 query_logs_tool 获取日志证据\n'
                    '3. 结论必须引用具体告警/日志内容\n'
                    '4. 数据不足时明确说明，不得猜测'
                ),
            },
            {
                'name': '故障关联分析',
                'slug': 'fault-correlation-analysis',
                'description': '故障排查时联动告警、日志、变更与依赖拓扑，定位根因。',
                'category': '排障方法',
                'applicable_actions': ['alert.root_cause', 'change.correlation'],
                'examples': ['分析这个故障的根因', '这个变更会影响哪些系统'],
                'recommended_tools': ['query_alerts_tool', 'query_recent_changes_tool', 'query_cmdb_topology_tool'],
                'risk_level': AIOpsSkill.RISK_READ_ONLY,
                'output_contract': '根因结论 + 证据链 + 影响范围',
                'content': (
                    'SOP：\n'
                    '1. 收集告警与事件时间线\n'
                    '2. 对照最近变更记录\n'
                    '3. 用 CMDB 拓扑评估影响范围\n'
                    '4. 输出根因结论与证据链'
                ),
            },
            {
                'name': 'Zabbix 问题处置',
                'slug': 'zabbix-problem-handling',
                'description': 'Zabbix 告警问题的查询、分级与处置建议。',
                'category': '监控处置',
                'applicable_actions': ['zabbix.problem_analysis'],
                'examples': ['Zabbix 上有哪些严重级别的磁盘问题'],
                'recommended_tools': ['query_zabbix_problems_tool', 'query_zabbix_host_metrics_tool'],
                'risk_level': AIOpsSkill.RISK_READ_ONLY,
                'output_contract': '问题列表（按严重度）+ 处置建议',
                'content': (
                    'SOP：\n'
                    '1. query_zabbix_problems_tool 获取活跃问题\n'
                    '2. 按严重度排序，灾难/严重优先\n'
                    '3. 对主机问题补充主机指标佐证\n'
                    '4. 给出清理/扩容/重启等处置建议'
                ),
            },
            {
                'name': '自动化安全护栏',
                'slug': 'automation-safety-guardrail',
                'description': '写入/执行类动作必须先预检、生成待确认草稿，用户确认后才执行。',
                'category': '安全边界',
                'applicable_actions': ['host_task.generate'],
                'examples': ['帮我生成一个对订单相关主机的巡检任务'],
                'recommended_tools': ['query_zabbix_hosts_tool'],
                'risk_level': AIOpsSkill.RISK_WRITE,
                'output_contract': '任务草稿 + 待确认动作',
                'content': (
                    'SOP：\n'
                    '1. 先查询目标主机清单\n'
                    '2. 生成任务草稿（标题/目标/命令）\n'
                    '3. 输出待确认动作，等待用户确认\n'
                    '4. 确认后由平台 API 执行并审计'
                ),
            },
        ]

        for spec in skills:
            _, created = AIOpsSkill.objects.update_or_create(
                slug=spec['slug'],
                defaults={
                    'source_type': 'builtin',
                    'is_builtin': True,
                    'is_enabled': True,
                    **{k: v for k, v in spec.items() if k != 'slug'},
                },
            )
        stdout.write(f'内置 Skill: {len(skills)} 个')

    # ── Runbook ──────────────────────────────────────────────────────

    def _seed_runbooks(self, stdout, user):
        from aiops.models import AIOpsRunbook, AIOpsRunbookVersion

        runbooks = [
            {
                'title': 'order-center 库存校验超时应急手册',
                'slug': 'order-center-inventory-timeout-runbook',
                'environment': 'prod',
                'service': 'order-center',
                'content': (
                    '# 应急目标\n快速恢复订单服务库存校验功能，避免业务中断。\n\n'
                    '# 排查步骤\n1. 确认告警时间线与影响范围（告警中心）\n'
                    '2. 检索库存服务错误日志（日志中心）\n'
                    '3. 检查最近发布与灰度批次（应用发布）\n'
                    '4. 对照库存依赖拓扑（CMDB 拓扑）\n\n'
                    '# 处置步骤\n1. 优先回滚问题版本\n2. 无效则扩容库存服务实例\n'
                    '3. 处置后观察 30 分钟确认告警不再复现\n\n'
                    '# 收尾\n更新事件墙记录，沉淀结论。'
                ),
                'tags': ['库存', '超时', '应急'],
                'source_refs': [
                    {'type': 'alert', 'name': 'order-center 库存校验超时'},
                    {'type': 'deployment', 'name': '订单中心生产发布'},
                ],
            },
            {
                'title': 'Zabbix 磁盘使用率告警处理手册',
                'slug': 'zabbix-disk-usage-alert-runbook',
                'environment': 'prod',
                'service': 'order-api-ecs-01',
                'content': (
                    '# 应急目标\n释放主机磁盘空间，消除 >90% 使用率告警。\n\n'
                    '# 排查步骤\n1. 查询 Zabbix 活跃问题确认主机\n'
                    '2. 查询主机指标确认磁盘趋势\n\n'
                    '# 处置步骤\n1. 清理过期日志与临时文件\n'
                    '2. 无法释放则提交扩容工单\n'
                    '3. 观察告警是否恢复\n\n# 预防措施\n'
                    '配置磁盘容量趋势告警阈值 80%。'
                ),
                'tags': ['磁盘', 'Zabbix', '告警'],
                'source_refs': [
                    {'type': 'zabbix', 'name': 'order-api-ecs-01 磁盘问题'},
                ],
            },
            {
                'title': '发布后健康检查失败回滚手册',
                'slug': 'post-deploy-healthcheck-rollback-runbook',
                'environment': 'prod',
                'service': 'member-center',
                'content': (
                    '# 应急目标\n发布后健康检查失败时快速回滚到上一稳定版本。\n\n'
                    '# 排查步骤\n1. 查看发布单状态与失败阶段\n'
                    '2. 检索服务启动错误日志\n'
                    '3. 确认失败影响范围\n\n'
                    '# 处置步骤\n1. 触发一键回滚\n2. 回滚后验证健康检查\n'
                    '3. 复盘失败原因后重新规划发布窗口\n\n# 收尾\n更新发布记录与事件墙。'
                ),
                'tags': ['发布', '回滚', '健康检查'],
                'source_refs': [
                    {'type': 'deployment', 'name': '会员中心发布失败'},
                ],
            },
        ]

        for spec in runbooks:
            runbook, created = AIOpsRunbook.objects.update_or_create(
                slug=spec['slug'],
                defaults={
                    'title': spec['title'],
                    'environment': spec['environment'],
                    'service': spec['service'],
                    'status': AIOpsRunbook.STATUS_PUBLISHED,
                    'version': 1,
                    'content': spec['content'],
                    'tags': spec['tags'],
                    'source_refs': spec['source_refs'],
                    'created_by': user.username,
                    'updated_by': user.username,
                    'published_at': timezone.now(),
                },
            )
            AIOpsRunbookVersion.objects.update_or_create(
                runbook=runbook, version=1,
                defaults={
                    'status': AIOpsRunbook.STATUS_PUBLISHED,
                    'title': spec['title'],
                    'content': spec['content'],
                    'tags': spec['tags'],
                    'source_refs': spec['source_refs'],
                    'change_note': '演示数据初始化',
                    'created_by': user.username,
                },
            )
        stdout.write(f'Runbook: {len(runbooks)} 个')

    # ── MCP Server 行 ────────────────────────────────────────────────

    def _seed_mcp_row(self, stdout):
        from aiops.models import AIOpsMCPServer

        _, created = AIOpsMCPServer.objects.update_or_create(
            name='iTop CMDB MCP（演示）',
            defaults={
                'server_type': 'stdio',
                'endpoint_or_command': 'demo://itop-mcp',
                'description': '外部 iTop CMDB MCP 服务（演示环境停用，展示列表用途）',
                'is_builtin': False,
                'is_enabled': False,
            },
        )
        stdout.write(f'演示 MCP 行: {"created" if created else "updated"}')

    # ── 演示会话与审计记录 ───────────────────────────────────────────

    def _seed_sessions(self, stdout, user):
        from aiops.models import (
            AIOpsChatMessage,
            AIOpsChatSession,
            AIOpsModelInvocation,
            AIOpsModelProvider,
            AIOpsToolInvocation,
        )

        # 清理旧演示会话（幂等重建）
        AIOpsChatSession.objects.filter(title__in=DEMO_SESSION_TITLES).delete()

        now = timezone.now()
        specs = [
            {
                'title': DEMO_SESSION_TITLES[0],
                'question': '分析 order-center 库存校验超时的根因',
                'answer': (
                    '## 结论\n已定位为订单中心 v2.6.3 灰度发布后库存服务响应超时。\n\n'
                    '## 关键证据\n1. 告警：order-center 库存校验超时（严重，持续 2 小时）\n'
                    '2. 日志：Inventory service timeout while creating order ORD-20260410-1024\n'
                    '3. 变更：订单中心生产发布（第二批灰度）\n\n'
                    '## 建议操作\n- 回滚问题批次或扩容库存服务\n- 处置后观察 30 分钟确认恢复'
                ),
                'tool_name': 'query_alert_root_cause_tool',
                'action_code': 'alert.root_cause',
            },
            {
                'title': DEMO_SESSION_TITLES[1],
                'question': 'Zabbix 上有哪些严重级别的磁盘问题',
                'answer': (
                    '## 结论\nZabbix 当前存在 1 个严重级磁盘问题。\n\n'
                    '## 关键证据\n1. [严重] 磁盘空间使用率超过 90%（order-api-ecs-01）\n\n'
                    '## 建议操作\n- 对 order-api-ecs-01 执行磁盘清理或扩容'
                ),
                'tool_name': 'query_zabbix_problems_tool',
                'action_code': 'zabbix.problem_analysis',
            },
        ]

        for idx, spec in enumerate(specs):
            session = AIOpsChatSession.objects.create(
                user=user,
                title=spec['title'],
                status=AIOpsChatSession.STATUS_ACTIVE,
                last_message_at=now - timedelta(days=idx + 1),
            )
            session.created_at = now - timedelta(days=idx + 1)
            session.updated_at = now - timedelta(days=idx + 1)
            session.save(update_fields=['created_at', 'updated_at'])

            user_msg = AIOpsChatMessage.objects.create(
                session=session,
                role=AIOpsChatMessage.ROLE_USER,
                message_type=AIOpsChatMessage.TYPE_TEXT,
                content=spec['question'],
                metadata={},
            )
            user_msg.created_at = session.created_at
            user_msg.save(update_fields=['created_at'])

            assistant = AIOpsChatMessage.objects.create(
                session=session,
                role=AIOpsChatMessage.ROLE_ASSISTANT,
                message_type=AIOpsChatMessage.TYPE_ANALYSIS,
                content=spec['answer'],
                tool_calls=[{'name': spec['tool_name'], 'content': '演示工具调用'}],
                metadata={
                    'processing_status': 'completed',
                    'engine': 'deepagents',
                    'action_code': spec['action_code'],
                    'agent_mode': 'react',
                    'processing_steps': [
                        {'title': '初始化', 'detail': 'DeepAgents 引擎已启动', 'status': 'completed'},
                        {'title': '分析完成', 'detail': '调用 1 个工具', 'status': 'completed'},
                    ],
                },
            )
            assistant.created_at = session.created_at
            assistant.save(update_fields=['created_at'])

            AIOpsToolInvocation.objects.create(
                session=session,
                message=assistant,
                tool_name=spec['tool_name'],
                status=AIOpsToolInvocation.STATUS_SUCCESS,
                latency_ms=120 + idx * 45,
                request_payload={'query': spec['question']},
                response_summary={'summary': '演示数据'},
            )
            demo_provider = AIOpsModelProvider.objects.filter(
                default_model='sxdevops-demo-mock'
            ).first()
            AIOpsModelInvocation.objects.create(
                session=session,
                message=assistant,
                provider=demo_provider,
                username=user.username,
                purpose='agent_llm_call',
                requested_model='sxdevops-demo-mock',
                resolved_model='sxdevops-demo-mock',
                status='success',
                latency_ms=180 + idx * 50,
                prompt_tokens=350,
                completion_tokens=220,
                total_tokens=570,
            )
        stdout.write(f'演示会话: {len(specs)} 个（含审计记录）')
