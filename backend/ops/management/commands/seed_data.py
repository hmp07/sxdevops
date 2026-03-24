import random
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from ops.models import Host, Deployment, Alert, LogEntry, K8sCluster
from marketplace.models import ServiceDeployment, ServiceTemplate
from cmdb.demo_seed import seed_cmdb_demo


def seed_marketplace_demo(stdout, hosts):
    stdout.write('正在生成工具市场演示数据...')
    call_command('seed_templates')
    ServiceDeployment.objects.all().delete()

    cluster_main, _ = K8sCluster.objects.update_or_create(
        name='demo-k8s-cluster',
        defaults={
            'api_server': 'https://demo-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '工具市场演示 Kubernetes 集群',
        },
    )
    cluster_dev, _ = K8sCluster.objects.update_or_create(
        name='dev-k8s-cluster',
        defaults={
            'api_server': 'https://dev-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '开发环境演示 Kubernetes 集群',
        },
    )

    template_map = {
        item.name: item
        for item in ServiceTemplate.objects.filter(
            name__in=['Redis', 'MongoDB', 'Nginx', 'Grafana', 'Java', 'Python', 'Node.js']
        )
    }
    host_map = {host.hostname: host for host in hosts}

    demo_deployments = [
        {
            'template': template_map['Redis'],
            'deploy_mode': 'docker_compose',
            'host': host_map['redis-01'],
            'version': '7.0',
            'status': 'running',
            'env_config': {'port': '6379', 'password': 'redis@2024'},
            'deployer': 'ops_demo',
            'deploy_dir': '/opt/agdevops/redis',
            'deploy_log': '[INFO] 部署模式: Docker Compose 单机\n[✓] SSH 连接成功\n[✓] 上传 docker-compose.yml\n[✓] 部署成功',
        },
        {
            'template': template_map['MongoDB'],
            'deploy_mode': 'docker_compose',
            'host': host_map['db-master'],
            'version': '7.0',
            'status': 'stopped',
            'env_config': {'port': '27017', 'root_username': 'admin', 'root_password': 'mongo@2024'},
            'deployer': 'admin',
            'deploy_dir': '/opt/agdevops/mongodb',
            'deploy_log': '[INFO] 部署模式: Docker Compose 单机\n[✓] 首次部署成功\n[✓] 当前实例已停止，等待重新启动',
        },
        {
            'template': template_map['Nginx'],
            'deploy_mode': 'docker_compose',
            'host': host_map['nginx-lb-01'],
            'version': '1.25',
            'status': 'failed',
            'env_config': {'http_port': '80', 'https_port': '443'},
            'deployer': 'zhangsan',
            'deploy_dir': '/opt/agdevops/nginx',
            'deploy_log': '[INFO] 部署模式: Docker Compose 单机\n[✗] 端口 80 已被占用，部署失败',
        },
        {
            'template': template_map['Grafana'],
            'deploy_mode': 'k8s',
            'cluster': cluster_main,
            'namespace': 'monitoring',
            'release_name': 'grafana-demo',
            'replicas': 1,
            'version': '10.3',
            'status': 'running',
            'env_config': {'port': '3000'},
            'deployer': 'ops_demo',
            'deploy_dir': 'k8s://demo-k8s-cluster/monitoring/grafana-demo',
            'deploy_log': '[INFO] 部署模式: Kubernetes\n[✓] 使用现有命名空间: monitoring\n[✓] 已创建 Deployment/grafana-demo\n[✓] 部署成功',
        },
        {
            'template': template_map['Java'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'java-devbox',
            'replicas': 1,
            'version': '3.9.9-eclipse-temurin-21',
            'status': 'running',
            'env_config': {
                'workspace': '/workspace',
                'maven_mirror_url': 'https://maven.aliyun.com/repository/public',
                'maven_opts': '-Xms256m -Xmx512m',
            },
            'deployer': 'dev_demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/java-devbox',
            'deploy_log': '[INFO] 部署模式: Kubernetes\n[✓] 已创建 PVC/java-devbox-workspace\n[✓] 已创建 Deployment/java-devbox\n[✓] 部署成功',
        },
        {
            'template': template_map['Python'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'python-devbox',
            'replicas': 1,
            'version': '3.12',
            'status': 'running',
            'env_config': {
                'workspace': '/workspace',
                'pip_index_url': 'https://pypi.tuna.tsinghua.edu.cn/simple',
                'pip_trusted_host': 'pypi.tuna.tsinghua.edu.cn',
            },
            'deployer': 'dev_demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/python-devbox',
            'deploy_log': '[INFO] 部署模式: Kubernetes\n[✓] 已创建 PVC/python-devbox-workspace\n[✓] 已创建 Deployment/python-devbox\n[✓] 部署成功',
        },
        {
            'template': template_map['Node.js'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'frontend-dev',
            'release_name': 'nodejs-devbox',
            'replicas': 1,
            'version': '20',
            'status': 'deploying',
            'env_config': {
                'workspace': '/workspace',
                'npm_registry': 'https://registry.npmmirror.com',
            },
            'deployer': 'dev_demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/frontend-dev/nodejs-devbox',
            'deploy_log': '[INFO] 部署模式: Kubernetes\n[✓] 已创建命名空间: frontend-dev\n[✓] 正在拉取 node:20 镜像...',
        },
    ]

    for item in demo_deployments:
        ServiceDeployment.objects.create(**item)


class Command(BaseCommand):
    help = '生成 Mock 演示数据'

    def handle(self, *args, **options):
        self.stdout.write('正在清除旧数据...')
        ServiceDeployment.objects.all().delete()
        Host.objects.all().delete()
        Deployment.objects.all().delete()
        Alert.objects.all().delete()
        LogEntry.objects.all().delete()

        self.stdout.write('正在生成主机数据...')
        hosts = []
        host_configs = [
            ('web-server-01', '192.168.1.10', 'CentOS 7.9'),
            ('web-server-02', '192.168.1.11', 'CentOS 7.9'),
            ('app-server-01', '192.168.1.20', 'Ubuntu 22.04'),
            ('app-server-02', '192.168.1.21', 'Ubuntu 22.04'),
            ('db-master', '192.168.1.30', 'CentOS 8'),
            ('db-slave-01', '192.168.1.31', 'CentOS 8'),
            ('redis-01', '192.168.1.40', 'Ubuntu 20.04'),
            ('redis-02', '192.168.1.41', 'Ubuntu 20.04'),
            ('nginx-lb-01', '192.168.1.50', 'Debian 11'),
            ('monitor-01', '192.168.1.60', 'Ubuntu 22.04'),
            ('k8s-master', '10.0.1.10', 'Ubuntu 22.04'),
            ('k8s-worker-01', '10.0.1.11', 'Ubuntu 22.04'),
            ('k8s-worker-02', '10.0.1.12', 'Ubuntu 22.04'),
            ('es-node-01', '192.168.2.10', 'CentOS 7.9'),
            ('mq-broker-01', '192.168.2.20', 'Debian 12'),
        ]
        for hostname, ip, os_type in host_configs:
            host = Host.objects.create(
                hostname=hostname,
                ip_address=ip,
                os_type=os_type,
                status=random.choices(['online', 'offline', 'warning'], weights=[80, 10, 10])[0],
                cpu_usage=round(random.uniform(5, 95), 1),
                memory_usage=round(random.uniform(20, 90), 1),
                disk_usage=round(random.uniform(10, 85), 1),
            )
            hosts.append(host)

        self.stdout.write('正在生成部署记录...')
        apps = [
            ('user-service', 'v2.'),
            ('order-service', 'v3.'),
            ('payment-service', 'v1.'),
            ('gateway', 'v4.'),
            ('admin-panel', 'v1.'),
            ('notification-service', 'v2.'),
        ]
        envs = ['production', 'staging', 'testing', 'development']
        deploy_statuses = ['success', 'success', 'success', 'failed', 'running', 'rollback']
        for i in range(30):
            app_name, version_prefix = random.choice(apps)
            version = f'{version_prefix}{random.randint(0,9)}.{random.randint(0,20)}'
            Deployment.objects.create(
                app_name=app_name,
                version=version,
                environment=random.choice(envs),
                status=random.choice(deploy_statuses),
                deployer=random.choice(['admin', 'devops-bot', 'zhangsan', 'lisi', 'wangwu']),
                description=f'{app_name} {version} 部署',
                host=random.choice(hosts),
            )

        self.stdout.write('正在生成告警数据...')
        alert_templates = [
            ('CPU 使用率超过阈值', 'critical', 'Prometheus', 'CPU 使用率持续 5 分钟超过 90%'),
            ('内存使用率过高', 'warning', 'Prometheus', '内存使用率超过 80%'),
            ('磁盘空间不足', 'critical', 'Zabbix', '磁盘使用率超过 95%，请及时清理'),
            ('服务响应超时', 'warning', 'APM', '服务平均响应时间超过 3 秒'),
            ('数据库连接池满', 'critical', 'MySQL Monitor', '连接池使用率 100%'),
            ('SSL 证书即将过期', 'info', 'CertBot', 'SSL 证书将在 7 天后过期'),
            ('容器重启次数异常', 'warning', 'Kubernetes', 'Pod 在 1 小时内重启超过 5 次'),
            ('网络延迟升高', 'info', 'PingMonitor', '网络延迟超过 200ms'),
        ]
        for i in range(20):
            template = random.choice(alert_templates)
            Alert.objects.create(
                title=template[0],
                level=template[1],
                source=template[2],
                message=template[3],
                is_acknowledged=random.choice([True, False, False]),
                host=random.choice(hosts),
            )

        self.stdout.write('正在生成日志数据...')
        services = ['user-service', 'order-service', 'gateway', 'nginx', 'mysql', 'redis']
        log_messages = {
            'error': [
                'Connection refused to database',
                'NullPointerException at line 42',
                'Out of memory error',
                'Permission denied: /var/log/app.log',
                'Timeout while waiting for response',
            ],
            'warning': [
                'Slow query detected: 2.5s',
                'High memory usage: 85%',
                'Retry attempt 3/5 for API call',
                'Deprecated API version used',
                'Connection pool reaching limit',
            ],
            'info': [
                'Service started successfully',
                'Request processed in 120ms',
                'Configuration reloaded',
                'Health check passed',
                'Scheduled task completed',
            ],
            'debug': [
                'Entering function processOrder()',
                'Cache hit for key: user_123',
                'Query executed: SELECT * FROM users',
                'WebSocket connection established',
            ],
        }
        for i in range(50):
            level = random.choices(['error', 'warning', 'info', 'debug'], weights=[10, 20, 50, 20])[0]
            LogEntry.objects.create(
                level=level,
                service=random.choice(services),
                message=random.choice(log_messages[level]),
                host=random.choice(hosts),
            )

        self.stdout.write(self.style.SUCCESS(
            f'✅ 数据生成完成: '
            f'{Host.objects.count()} 主机, '
            f'{Deployment.objects.count()} 部署记录, '
            f'{Alert.objects.count()} 告警, '
            f'{LogEntry.objects.count()} 日志'
        ))

        self.stdout.write('正在生成 RBAC 演示账号...')
        seed_marketplace_demo(self.stdout, hosts)
        call_command('seed_rbac_demo')

        self.stdout.write('正在生成 CMDB 演示数据...')
        seed_cmdb_demo(self.stdout)
