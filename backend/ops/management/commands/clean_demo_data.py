"""清理演示种子数据（生产环境使用）。

用于已部署环境移除 seed_data 及各演示种子命令生成的数据，对应关系：

  seed_data                      → ops 演示主机/告警/日志/发布单/任务/Docker 主机/K8s 集群
  seed_marketplace_demo          → ServiceDeployment（change_summary 标记）
  seed_sqlaudit_demo             → SQL 审计演示数据源与工单
  seed_transaction_ticket_demo   → 事务工单 + 「事务工单 · 」前缀审批流
  seed_eventwall_demo            → EventRecord(is_demo=True)
  seed_aiops_demo                → 演示会话/审计/Runbook/Skill/provider/MCP 行
  seed_cmdb_demo                 → CMDB 配置项/关系/成本/资源树/资源申请
  seed_multicloud_demo           → 多云账号/环境/资产/同步任务
  seed_rbac_demo                 → 演示用户与用户组
  Zabbix 演示数据源               → api_url='demo://'

保留：管理员与真实用户、工具市场内置模板、默认知识图谱环境（其演示绑定重置为空）。

安全设计：默认 dry-run 仅打印将要删除的行数，必须显式 --yes 才执行；幂等可重复执行。
适用场景：尚未录入真实业务数据的环境。若环境已有真实数据，请先核对 dry-run 输出。

用法:
  python manage.py clean_demo_data            # dry-run
  python manage.py clean_demo_data --yes      # 执行清理
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from aiops.models import (
    AIOpsChatSession,
    AIOpsKnowledgeEnvironment,
    AIOpsMCPServer,
    AIOpsModelProvider,
    AIOpsRunbook,
    AIOpsSkill,
)
from cmdb.models import CIRelation, ConfigItem, CostRecord, ResourceNode, ResourceRequest
from eventwall.models import EventRecord
from marketplace.models import ServiceDeployment
from multicloud.models import CloudAsset, CloudCredential, CloudEnvironment, CloudSyncTask
from ops.models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    Host,
    HostTask,
    HostTaskExecution,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogDataSource,
    LogEntry,
    MetricDataSource,
    TaskResource,
    TaskResourceGroup,
    TransactionTicket,
    ZabbixDataSource,
)
from rbac.management.commands.seed_rbac_demo import DEMO_GROUPS, DEMO_USERS
from rbac.models import UserGroup
from sqlaudit.models import DataSource, QueryOrder, SqlCheckResult, SqlOrder

# ── 演示数据特征（与各 seed 命令保持一致）──────────────────────────────
DEMO_HOSTNAMES = [
    'order-api-ecs-01',
    'order-api-ecs-02',
    'order-perf-test-ecs',
    'feature-x-dev-ecs',
    'airflow-worker-dev',
    'legacy-data-sync',
    'k8s-node-01',
]
DEMO_DOCKER_HOSTS = ['app-release-test', 'gateway-prod', 'member-prod']
DEMO_FLOW_NAMES = ['生产发布三段审批', '测试快速审批']
TICKET_FLOW_PREFIX = '事务工单 · '
DEMO_TASK_CREATORS = ['ops_demo', 'release_mgr', 'system-scheduler']
DEMO_TASK_NAMES = ['批量刷新主机信息', '批量日志巡检']
DEMO_TASK_TEMPLATE_NAMES = [
    '生产 SSH 巡检',
    '常用服务巡检',
    '批量健康度检查',
    'Ansible 批量基线采集',
    'Nginx 配置一致性 Playbook',
]
DEMO_SQL_DATASOURCES = ['trade-primary', 'member-archive']
DEMO_SQL_SUBMITTERS = ['dev_demo', 'audit_demo']
# 告警/日志按内容特征匹配：种子管线中 CMDB 双向同步信号会重建 Host 行，
# 导致这些表的外键被 SET_NULL（host_id 为空），不能只依赖 host 外键
DEMO_ALERT_TITLES = [
    'CPU 使用率过高',
    '内存使用率过高',
    '磁盘空间不足',
    '服务响应超时',
    'order-center 库存校验超时',
    'order-center 下游依赖重试激增',
    'order-center 发布后健康检查失败',
    'payment-worker Deployment 副本不可用',
    'member-api Deployment 滚动发布卡住',
]
DEMO_LOG_MESSAGES = [
    'Connection refused to database',
    'Timeout while waiting for response',
    'Slow query detected: 2.5s',
    'Connection pool reaching limit',
    'Service started successfully',
    'Health check passed',
    'Cache hit for key: user_123',
    'WebSocket connection established',
    'Inventory service timeout while creating order ORD-20260410-1024',
    'Order center downstream latency increased to 1.8s on /api/orders/create',
    'Order center detected retry storm after inventory timeout in prod',
]
# 与 aiops/management/commands/seed_aiops_demo.py 中的 slug 保持同步
DEMO_AI_SESSION_TITLES = [
    'order-center 库存超时排查',
    'Zabbix 生产监控问题分析',
]
DEMO_AI_SKILL_SLUGS = [
    'evidence-first-answer',
    'fault-correlation-analysis',
    'zabbix-problem-handling',
    'automation-safety-guardrail',
]
DEMO_AI_RUNBOOK_SLUGS = [
    'order-center-inventory-timeout-runbook',
    'zabbix-disk-usage-alert-runbook',
    'post-deploy-healthcheck-rollback-runbook',
]
DEMO_AI_PROVIDER_BASE_URL = 'demo://offline'
DEMO_AI_MCP_NAME = 'iTop CMDB MCP（演示）'


class Command(BaseCommand):
    help = '清理演示种子数据（默认 dry-run，--yes 执行）'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='确认执行清理（默认仅打印 dry-run）')

    def handle(self, *args, **options):
        confirm = options['yes']

        User = get_user_model()
        demo_hosts = Host.objects.filter(hostname__in=DEMO_HOSTNAMES)
        demo_task_templates = HostTaskTemplate.objects.filter(name__in=DEMO_TASK_TEMPLATE_NAMES)
        demo_tasks = HostTask.objects.filter(
            Q(created_by__in=DEMO_TASK_CREATORS) | Q(name__in=DEMO_TASK_NAMES)
        )
        demo_schedules = HostTaskSchedule.objects.filter(created_by='ops_demo')
        demo_flows = DeploymentApprovalFlow.objects.filter(
            Q(name__in=DEMO_FLOW_NAMES) | Q(name__startswith=TICKET_FLOW_PREFIX)
        )

        # 删除顺序与 seed_data 的反向保持一致，满足外键依赖
        steps = [
            ('事件墙演示事件', EventRecord.objects.filter(is_demo=True)),
            ('SQL 审计检查结果', SqlCheckResult.objects.filter(order__submitter__in=DEMO_SQL_SUBMITTERS)),
            ('SQL 审计查询工单', QueryOrder.objects.filter(submitter__in=DEMO_SQL_SUBMITTERS)),
            ('SQL 审计变更工单', SqlOrder.objects.filter(submitter__in=DEMO_SQL_SUBMITTERS)),
            ('SQL 审计演示数据源', DataSource.objects.filter(name__in=DEMO_SQL_DATASOURCES)),
            ('工具市场演示部署', ServiceDeployment.objects.filter(
                Q(deployer__in=['ops-demo', 'dev-demo', 'zhangsan'])
                | Q(deployer='admin', deploy_dir='/opt/sxdevops/mongodb')
            )),
            ('事务工单', TransactionTicket.objects.filter(applicant='ops-demo')),
            ('发布审批步骤', DeploymentApprovalStep.objects.filter(flow__in=demo_flows)),
            ('演示发布单', Deployment.objects.filter(description__contains='典型案例')),
            ('发布审批节点', DeploymentApprovalNode.objects.filter(flow__in=demo_flows)),
            ('演示审批流', demo_flows),
            ('主机任务执行记录', HostTaskExecution.objects.filter(host__in=demo_hosts)),
            ('定时任务执行记录', HostTaskScheduleExecution.objects.filter(schedule__in=demo_schedules)),
            ('定时任务', demo_schedules),
            ('主机任务', demo_tasks),
            ('主机任务模板', demo_task_templates),
            ('演示告警', Alert.objects.filter(
                Q(title__in=DEMO_ALERT_TITLES) | Q(host__in=demo_hosts)
            )),
            ('演示日志', LogEntry.objects.filter(
                Q(message__in=DEMO_LOG_MESSAGES) | Q(host__in=demo_hosts)
            )),
            ('演示主机', Host.objects.filter(
                Q(hostname__in=DEMO_HOSTNAMES) | Q(source='zabbix')
            )),
            ('演示 Docker 主机', DockerHost.objects.filter(name__in=DEMO_DOCKER_HOSTS)),
            ('演示 K8s 集群', K8sCluster.objects.filter(kubeconfig='demo')),
            ('Zabbix 演示数据源', ZabbixDataSource.objects.filter(api_url__startswith='demo://')),
            ('演示指标数据源', MetricDataSource.objects.filter(config__demo_mode=True)),
            ('演示日志数据源', LogDataSource.objects.filter(config__demo_mode=True)),
            ('Zabbix 自动导入资源', TaskResource.objects.filter(external_id__startswith='zabbix:')),
            ('Zabbix 自动导入资源组', TaskResourceGroup.objects.filter(code='zabbix-monitored')),
            ('AIOps 演示会话', AIOpsChatSession.objects.filter(title__in=DEMO_AI_SESSION_TITLES)),
            ('AIOps 演示 Runbook', AIOpsRunbook.objects.filter(slug__in=DEMO_AI_RUNBOOK_SLUGS)),
            ('AIOps 演示 Skill', AIOpsSkill.objects.filter(slug__in=DEMO_AI_SKILL_SLUGS)),
            ('AIOps 演示模型 provider', AIOpsModelProvider.objects.filter(base_url=DEMO_AI_PROVIDER_BASE_URL)),
            ('AIOps 演示 MCP 行', AIOpsMCPServer.objects.filter(name=DEMO_AI_MCP_NAME)),
            ('CMDB 成本记录', CostRecord.objects.all()),
            ('CMDB 配置关系', CIRelation.objects.all()),
            ('CMDB 配置项', ConfigItem.objects.all()),
            ('CMDB 资源申请', ResourceRequest.objects.all()),
            ('CMDB 资源树节点', ResourceNode.objects.all()),
            ('多云同步任务', CloudSyncTask.objects.all()),
            ('多云资产', CloudAsset.objects.all()),
            ('多云环境', CloudEnvironment.objects.filter(created_by='seed')),
            ('多云演示账号', CloudCredential.objects.filter(demo_mode=True)),
            ('RBAC 演示用户', User.objects.filter(username__in=[item['username'] for item in DEMO_USERS])),
            ('RBAC 演示用户组', UserGroup.objects.filter(code__in=[item['code'] for item in DEMO_GROUPS])),
        ]

        total = 0
        for label, qs in steps:
            count = qs.count()
            total += count
            if count:
                self.stdout.write(f'{"[执行]" if confirm else "[预检]"} {label}: {count} 行')
                if confirm:
                    qs.delete()

        # 默认知识图谱环境的演示绑定重置（保留环境本身）
        env = AIOpsKnowledgeEnvironment.objects.filter(is_default=True).first()
        if env is not None:
            has_binding = any([
                env.zabbix_datasource_ids,
                env.k8s_cluster_ids,
                env.docker_host_ids,
                env.metric_datasource_ids,
                env.log_datasource_ids,
                env.tracing_datasource_ids,
                env.observability_link_ids,
                env.event_environments,
                env.alert_environments,
                env.aliases != ['默认', 'default'],
            ])
            if has_binding:
                self.stdout.write(
                    f'{"[执行]" if confirm else "[预检]"} 默认知识图谱环境: 重置演示绑定与别名'
                )
                if confirm:
                    env.aliases = ['默认', 'default']
                    env.event_environments = []
                    env.alert_environments = []
                    env.zabbix_datasource_ids = []
                    env.k8s_cluster_ids = []
                    env.docker_host_ids = []
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

        if total == 0 and not confirm:
            self.stdout.write('没有发现演示数据。')
        elif confirm:
            self.stdout.write(self.style.SUCCESS(
                f'清理完成：共删除 {total} 行演示数据。'
                '（管理员账号、工具市场模板、默认知识图谱环境已保留）'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'\n以上为 dry-run 预览，共 {total} 行将被删除。'
                '确认无误后执行: python manage.py clean_demo_data --yes'
            ))
