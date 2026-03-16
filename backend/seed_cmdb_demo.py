import os
import sys
from decimal import Decimal

import django
from django.utils import timezone

sys.path.append('d:/code/agdevops/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agdevops.settings')
django.setup()

from cmdb.models import CIType, CIRelation, ConfigItem, CostRecord, ResourceNode, ResourceRequest


BIZ_COMMERCE = '电商线'
BIZ_INFRA = '基础架构'
BIZ_EXTERNAL = '外部服务'


def ensure_ci_type(name, color, icon='Monitor', description=''):
    ci_type, _ = CIType.objects.get_or_create(
        name=name,
        defaults={'icon': icon, 'color': color, 'description': description},
    )
    ci_type.icon = ci_type.icon or icon
    ci_type.color = color
    if description and not ci_type.description:
        ci_type.description = description
    ci_type.save()
    return ci_type


def create_ci(ci_type, name, business_line, environment, admin_user, status, attributes=None):
    return ConfigItem.objects.create(
        name=name,
        ci_type=ci_type,
        business_line=business_line,
        environment=environment,
        admin_user=admin_user,
        status=status,
        attributes=attributes or {},
    )


def create_relation(source, target, relation_type, description):
    return CIRelation.objects.create(
        source=source,
        target=target,
        relation_type=relation_type,
        description=description,
    )


def seed_demo_data():
    print('Clearing existing CMDB demo data...')
    CostRecord.objects.all().delete()
    CIRelation.objects.all().delete()
    ConfigItem.objects.all().delete()
    ResourceRequest.objects.all().delete()
    ResourceNode.objects.all().delete()

    print('Preparing CI types...')
    type_app = ensure_ci_type('应用服务', '#3b82f6', 'Grid', '对外或对内提供能力的应用服务')
    type_host = ensure_ci_type('云主机(ECS)', '#64748b', 'Monitor', '云上主机资源')
    type_db = ensure_ci_type('MySQL', '#f97316', 'Coin', '关系型数据库')
    type_cache = ensure_ci_type('Redis', '#ef4444', 'Lightning', '缓存与队列类能力')
    type_lb = ensure_ci_type('Nginx', '#10b981', 'Connection', '网关与反向代理')
    type_third_party = ensure_ci_type('第三方服务', '#0f766e', 'Link', '外部SaaS或开放平台')

    print('Creating resource tree...')
    biz_ecommerce = ResourceNode.objects.create(name=BIZ_COMMERCE, node_type='biz')
    ResourceNode.objects.create(name='prod', node_type='env', parent=biz_ecommerce)
    ResourceNode.objects.create(name='test', node_type='env', parent=biz_ecommerce)
    biz_infra = ResourceNode.objects.create(name=BIZ_INFRA, node_type='biz')
    ResourceNode.objects.create(name='prod', node_type='env', parent=biz_infra)

    print('Creating config items...')
    host_trade = create_ci(
        type_host, 'host-trade-01-prod', BIZ_COMMERCE, 'prod', 'admin', 'active',
        {
            'ip_address': '10.0.1.10',
            'cpu': 8,
            'memory_gb': 16,
            'disk_gb': 100,
            'instance_type': 'ecs.g6.2xlarge',
            'cloud_provider': '阿里云',
            'region': 'cn-hangzhou',
            'monthly_cost': 350.0,
        },
    )
    host_user = create_ci(
        type_host, 'host-user-01-prod', BIZ_COMMERCE, 'prod', 'admin', 'active',
        {
            'ip_address': '10.0.1.11',
            'cpu': 4,
            'memory_gb': 8,
            'disk_gb': 100,
            'instance_type': 'ecs.g6.xlarge',
            'cloud_provider': '阿里云',
            'region': 'cn-hangzhou',
            'monthly_cost': 200.0,
        },
    )
    db_prod = create_ci(
        type_db, 'mysql-master-prod', BIZ_COMMERCE, 'prod', 'DBA', 'active',
        {
            'version': 'MySQL 8.0',
            'storage': '500GB',
            'ip_address': '10.0.1.100',
            'cpu': 16,
            'memory_gb': 32,
            'monthly_cost': 1500.0,
            'cloud_provider': '阿里云 RDS',
        },
    )
    redis_prod = create_ci(
        type_cache, 'redis-cluster-prod', BIZ_COMMERCE, 'prod', 'DBA', 'active',
        {
            'version': 'Redis 6.2',
            'ip_address': '10.0.1.101',
            'cpu': 8,
            'memory_gb': 16,
            'monthly_cost': 800.0,
            'cloud_provider': '阿里云 KVStore',
        },
    )
    nginx_gateway = create_ci(
        type_lb, 'nginx-gateway-01', BIZ_COMMERCE, 'prod', 'Network', 'active',
        {
            'ip_address': '115.190.230.15',
            'bandwidth': '100Mbps',
            'cpu': 4,
            'memory_gb': 8,
            'monthly_cost': 150.0,
            'cloud_provider': '腾讯云',
        },
    )
    trade_service = create_ci(
        type_app, 'trade-service', BIZ_COMMERCE, 'prod', '开发-张三', 'active',
        {'language': 'Java', 'framework': 'Spring Boot', 'repo': 'git@gitlab.com:shop/trade.git'},
    )
    user_center = create_ci(
        type_app, 'user-center', BIZ_COMMERCE, 'prod', '开发-李四', 'active',
        {'language': 'Go', 'framework': 'Gin', 'repo': 'git@gitlab.com:shop/user.git'},
    )
    db_test = create_ci(
        type_db, 'mysql-test', BIZ_COMMERCE, 'test', 'QA', 'active',
        {'version': 'MySQL 8.0', 'storage': '50GB', 'ip_address': '10.0.2.100', 'cpu': 4, 'memory_gb': 8, 'monthly_cost': 200.0},
    )
    trade_service_test = create_ci(
        type_app, 'trade-service-test', BIZ_COMMERCE, 'test', '开发-张三', 'active',
        {'language': 'Java'},
    )
    k8s_master = create_ci(
        type_host, 'k8s-master-01', BIZ_INFRA, 'prod', 'SRE', 'active',
        {'ip_address': '192.168.1.10', 'cpu': 4, 'memory_gb': 16, 'monthly_cost': 300.0},
    )
    k8s_node = create_ci(
        type_host, 'k8s-node-01', BIZ_INFRA, 'prod', 'SRE', 'active',
        {'ip_address': '192.168.1.11', 'cpu': 16, 'memory_gb': 64, 'monthly_cost': 1200.0},
    )
    harbor_registry = create_ci(
        type_app, 'harbor-registry', BIZ_INFRA, 'prod', 'SRE', 'active',
        {'version': 'v2.5.0', 'storage': '1TB'},
    )

    anxinqian = create_ci(
        type_third_party, 'anxinqian-api', BIZ_COMMERCE, 'prod', '外部供应商', 'active',
        {
            'provider': '安心签',
            'endpoint': 'https://open.anxinqian.example',
            'description': '电子签约与合同回传能力',
        },
    )
    ocr_platform = create_ci(
        type_third_party, 'ocr-platform', BIZ_COMMERCE, 'prod', '外部供应商', 'active',
        {
            'provider': 'OCR',
            'endpoint': 'https://ocr.example.com',
            'description': '证件识别与票据解析能力',
        },
    )
    qichacha = create_ci(
        type_third_party, 'qichacha-openapi', BIZ_COMMERCE, 'prod', '外部供应商', 'active',
        {
            'provider': '企查查',
            'endpoint': 'https://openapi.qcc.com',
            'description': '企业信息查询与风险核验',
        },
    )
    kingdee = create_ci(
        type_third_party, 'kingdee-cloud', BIZ_COMMERCE, 'prod', '外部供应商', 'active',
        {
            'provider': '金蝶',
            'endpoint': 'https://api.kingdee.com',
            'description': '财务单据与结算单同步',
        },
    )

    print('Creating relations...')
    create_relation(nginx_gateway, trade_service, 'connects_to', 'Gateway routes order traffic')
    create_relation(nginx_gateway, user_center, 'connects_to', 'Gateway routes user traffic')
    create_relation(trade_service, db_prod, 'connects_to', 'Reads and writes order data')
    create_relation(trade_service, redis_prod, 'connects_to', 'Caches order sessions and hot data')
    create_relation(user_center, db_prod, 'connects_to', 'Reads and writes account data')
    create_relation(trade_service, host_trade, 'runs_on', 'Application is deployed on the trade host')
    create_relation(user_center, host_user, 'runs_on', 'Application is deployed on the user host')
    create_relation(trade_service_test, db_test, 'connects_to', 'Test environment database access')
    create_relation(k8s_node, k8s_master, 'connects_to', 'Worker node joins the cluster')
    create_relation(k8s_master, harbor_registry, 'depends_on', 'Control plane depends on image registry availability')

    create_relation(trade_service, anxinqian, 'depends_on', 'Order signing and contract callback rely on Anxinqian')
    create_relation(trade_service, kingdee, 'depends_on', 'Financial vouchers and settlement sync to Kingdee')
    create_relation(user_center, qichacha, 'depends_on', 'Enterprise profile verification relies on Qichacha')
    create_relation(user_center, ocr_platform, 'depends_on', 'Identity OCR verification relies on external OCR service')
    create_relation(trade_service, ocr_platform, 'depends_on', 'Invoice and attachment parsing relies on OCR service')

    print('Creating cost records...')
    current_month = timezone.now().strftime('%Y-%m')
    last_month = (timezone.now() - timezone.timedelta(days=30)).strftime('%Y-%m')
    for month in [last_month, current_month]:
        CostRecord.objects.create(ci=host_trade, month=month, amount=Decimal('350.00'), provider='Aliyun')
        CostRecord.objects.create(ci=host_user, month=month, amount=Decimal('200.00'), provider='Aliyun')
        CostRecord.objects.create(ci=db_prod, month=month, amount=Decimal('1500.00'), provider='Aliyun RDS')
        CostRecord.objects.create(ci=redis_prod, month=month, amount=Decimal('800.00'), provider='Aliyun KVStore')
        CostRecord.objects.create(ci=nginx_gateway, month=month, amount=Decimal('150.00'), provider='Tencent Cloud')
        CostRecord.objects.create(ci=k8s_node, month=month, amount=Decimal('1200.00'), provider='Physical')

    print('Demo data seeded successfully.')


if __name__ == '__main__':
    seed_demo_data()
