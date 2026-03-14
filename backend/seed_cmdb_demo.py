import os
import sys
import django
from decimal import Decimal
import random

sys.path.append('d:\\code\\agdevops\\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agdevops.settings')
django.setup()

from cmdb.models import CIType, ConfigItem, CIRelation, CostRecord, ResourceRequest, ResourceNode
from django.utils import timezone

def seed_demo_data():
    print("Clearing existing CMDB items...")
    ConfigItem.objects.all().delete()
    ResourceRequest.objects.all().delete()
    ResourceNode.objects.all().delete()

    print("Fetching and updating CI Types colors...")
    type_app = CIType.objects.get(name='应用服务')
    type_app.color = '#3b82f6' # Blue
    type_app.save()

    type_host = CIType.objects.get(name='云主机(ECS)')
    type_host.color = '#64748b' # Gray
    type_host.save()

    type_db = CIType.objects.get(name='MySQL')
    type_db.color = '#f97316' # Orange
    type_db.save()

    type_cache = CIType.objects.get(name='Redis')
    type_cache.color = '#ef4444' # Red
    type_cache.save()

    type_lb = CIType.objects.get(name='Nginx')
    type_lb.color = '#10b981' # Green
    type_lb.save()

    print("Creating Resource Nodes...")
    biz_ecommerce = ResourceNode.objects.create(name='电商线', node_type='biz')
    env_ecommerce_prod = ResourceNode.objects.create(name='prod', node_type='env', parent=biz_ecommerce)
    env_ecommerce_test = ResourceNode.objects.create(name='test', node_type='env', parent=biz_ecommerce)

    biz_infra = ResourceNode.objects.create(name='基础架构', node_type='biz')
    env_infra_prod = ResourceNode.objects.create(name='prod', node_type='env', parent=biz_infra)

    print("Creating Config Items...")
    # ------- Ecommerce Prod -------
    # Hosts
    host1 = ConfigItem.objects.create(
        name="host-trade-01-prod", ci_type=type_host, business_line="电商线", environment="prod", admin_user="admin", status="active",
        attributes={"ip_address": "10.0.1.10", "cpu": 8, "memory_gb": 16, "disk_gb": 100, "instance_type": "ecs.g6.2xlarge", "cloud_provider": "阿里云", "region": "cn-hangzhou", "monthly_cost": 350.0}
    )
    host2 = ConfigItem.objects.create(
        name="host-user-01-prod", ci_type=type_host, business_line="电商线", environment="prod", admin_user="admin", status="active",
        attributes={"ip_address": "10.0.1.11", "cpu": 4, "memory_gb": 8, "disk_gb": 100, "instance_type": "ecs.g6.xlarge", "cloud_provider": "阿里云", "region": "cn-hangzhou", "monthly_cost": 200.0}
    )

    # DB & Cache
    db_prod = ConfigItem.objects.create(
        name="mysql-master-prod", ci_type=type_db, business_line="电商线", environment="prod", admin_user="DBA", status="active",
        attributes={"version": "MySQL 8.0", "storage": "500GB", "ip_address": "10.0.1.100", "cpu": 16, "memory_gb": 32, "monthly_cost": 1500.0, "cloud_provider": "阿里云 RDS"}
    )
    redis_prod = ConfigItem.objects.create(
        name="redis-cluster-prod", ci_type=type_cache, business_line="电商线", environment="prod", admin_user="DBA", status="active",
        attributes={"version": "Redis 6.2", "ip_address": "10.0.1.101", "cpu": 8, "memory_gb": 16, "monthly_cost": 800.0, "cloud_provider": "阿里云 KVStore"}
    )

    # LB
    lb_1 = ConfigItem.objects.create(
        name="nginx-gateway-01", ci_type=type_lb, business_line="电商线", environment="prod", admin_user="Network", status="active",
        attributes={"ip_address": "115.190.230.15", "bandwidth": "100Mbps", "cpu": 4, "memory_gb": 8, "monthly_cost": 150.0, "cloud_provider": "腾讯云"}
    )

    # Apps
    app_trade = ConfigItem.objects.create(
        name="trade-service", ci_type=type_app, business_line="电商线", environment="prod", admin_user="开发-张三", status="active",
        attributes={"language": "Java", "framework": "Spring Boot", "repo": "git@gitlab.com:shop/trade.git"}
    )
    app_user = ConfigItem.objects.create(
        name="user-center", ci_type=type_app, business_line="电商线", environment="prod", admin_user="开发-李四", status="active",
        attributes={"language": "Go", "framework": "Gin", "repo": "git@gitlab.com:shop/user.git"}
    )

    # ------- Ecommerce Test & Dev -------
    db_test = ConfigItem.objects.create(
        name="mysql-test", ci_type=type_db, business_line="电商线", environment="test", admin_user="QA", status="active",
        attributes={"version": "MySQL 8.0", "storage": "50GB", "ip_address": "10.0.2.100", "cpu": 4, "memory_gb": 8, "monthly_cost": 200.0}
    )
    app_trade_test = ConfigItem.objects.create(
        name="trade-service-test", ci_type=type_app, business_line="电商线", environment="test", admin_user="开发-张三", status="active",
        attributes={"language": "Java"}
    )
    
    # ------- Infrastructure Prod -------
    k8s_master = ConfigItem.objects.create(
        name="k8s-master-01", ci_type=type_host, business_line="基础架构", environment="prod", admin_user="SRE", status="active",
        attributes={"ip_address": "192.168.1.10", "cpu": 4, "memory_gb": 16, "monthly_cost": 300.0}
    )
    k8s_node1 = ConfigItem.objects.create(
        name="k8s-node-01", ci_type=type_host, business_line="基础架构", environment="prod", admin_user="SRE", status="active",
        attributes={"ip_address": "192.168.1.11", "cpu": 16, "memory_gb": 64, "monthly_cost": 1200.0}
    )
    harbor_repo = ConfigItem.objects.create(
        name="harbor-registry", ci_type=type_app, business_line="基础架构", environment="prod", admin_user="SRE", status="active",
        attributes={"version": "v2.5.0", "storage": "1TB"}
    )


    print("Creating Relations...")
    # Ecommerce Prod
    CIRelation.objects.create(source=lb_1, target=app_trade, relation_type='depends_on', description='Routes traffic')
    CIRelation.objects.create(source=lb_1, target=app_user, relation_type='depends_on', description='Routes traffic')
    CIRelation.objects.create(source=app_trade, target=db_prod, relation_type='connects_to', description='Reads/Writes orders')
    CIRelation.objects.create(source=app_user, target=db_prod, relation_type='connects_to', description='Reads/Writes user data')
    CIRelation.objects.create(source=app_trade, target=redis_prod, relation_type='connects_to', description='Caches orders')
    CIRelation.objects.create(source=app_trade, target=host1, relation_type='runs_on', description='Pod deployed here')
    CIRelation.objects.create(source=app_user, target=host2, relation_type='runs_on', description='Pod deployed here')
    
    # Ecommerce Test
    CIRelation.objects.create(source=app_trade_test, target=db_test, relation_type='connects_to', description='Test DB')

    # Infra Prod
    CIRelation.objects.create(source=k8s_node1, target=k8s_master, relation_type='connects_to', description='Joins cluster')
    CIRelation.objects.create(source=k8s_master, target=harbor_repo, relation_type='depends_on', description='Pulls images')

    print("Creating Cost Records...")
    current_month = timezone.now().strftime('%Y-%m')
    last_month = (timezone.now() - timezone.timedelta(days=30)).strftime('%Y-%m')
    
    for month in [last_month, current_month]:
        CostRecord.objects.create(ci=host1, month=month, amount=Decimal('350.00'), provider='Aliyun')
        CostRecord.objects.create(ci=host2, month=month, amount=Decimal('200.00'), provider='Aliyun')
        CostRecord.objects.create(ci=db_prod, month=month, amount=Decimal('1500.00'), provider='AWS')
        CostRecord.objects.create(ci=redis_prod, month=month, amount=Decimal('800.00'), provider='AWS')
        CostRecord.objects.create(ci=lb_1, month=month, amount=Decimal('150.00'), provider='Tencent')
        CostRecord.objects.create(ci=k8s_node1, month=month, amount=Decimal('1200.00'), provider='Physical')

    print("Demo data seeded successfully with new colorful topology!")

if __name__ == '__main__':
    seed_demo_data()
