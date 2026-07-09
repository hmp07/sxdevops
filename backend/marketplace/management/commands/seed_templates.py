"""
初始化工具市场内置模板 + 默认知识图谱环境
用法: python manage.py seed_templates
"""

from django.core.management.base import BaseCommand

from marketplace.models import ServiceTemplate
from marketplace.template_catalog import TEMPLATES
from marketplace.template_presets import K8S_MANIFESTS


class Command(BaseCommand):
    help = '初始化工具市场模板数据 + 默认知识图谱环境'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for tpl_data in TEMPLATES:
            defaults = dict(tpl_data)
            defaults['k8s_manifest_template'] = K8S_MANIFESTS.get(tpl_data['name'], '')
            _, created = ServiceTemplate.objects.update_or_create(
                name=tpl_data['name'],
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'完成! 新增 {created_count} 个, 更新 {updated_count} 个模板'
        ))

        # 创建默认知识图谱环境（如果没有任何环境）
        self._seed_default_knowledge_environment()

    def _seed_default_knowledge_environment(self):
        try:
            from aiops.models import AIOpsKnowledgeEnvironment
        except ImportError:
            return

        if AIOpsKnowledgeEnvironment.objects.exists():
            self.stdout.write('  知识图谱环境已存在，跳过默认环境创建')
            return

        env = AIOpsKnowledgeEnvironment.objects.create(
            name='默认环境',
            aliases=['默认', 'default'],
            description='系统自动创建的默认知识图谱环境。请根据实际数据源配置修改或创建新环境。',
            event_environments=['默认'],
            is_enabled=True,
            is_default=True,
        )
        self.stdout.write(self.style.SUCCESS(
            f'  已创建默认知识图谱环境: {env.name}'
        ))
