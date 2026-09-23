"""从环境变量接入真实 DeepSeek 大模型（演示环境/一键部署用）。

环境变量：
  DEEPSEEK_API_KEY      必填（不设置时静默跳过，保持离线模拟模型）
  DEEPSEEK_BASE_URL     可选，默认 https://api.deepseek.com
  DEEPSEEK_MODEL        可选，默认预设 deepseek-v4-flash
  DEEPSEEK_BACKUP_MODEL 可选，默认预设 deepseek-v4-pro
  DEEPSEEK_PROVIDER_NAME 可选，默认 "DeepSeek（演示环境）"

行为：update_or_create DeepSeek provider（API Key Fernet 加密），并设为
AIOpsAgentConfig.default_provider（_ensure_builtin_model_provider 仅在
default_provider 为空时才会覆盖，不会抢占）。幂等：每次启动可安全重跑。
"""
import os

from django.core.management.base import BaseCommand

from aiops.models import AIOpsModelProvider


class Command(BaseCommand):
    help = '从环境变量接入真实 DeepSeek 模型（DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL/DEEPSEEK_MODEL）'

    def handle(self, *args, **options):
        from aiops.services import MODEL_PROVIDER_PRESETS, get_agent_config

        api_key = (os.environ.get('DEEPSEEK_API_KEY') or '').strip()
        if not api_key:
            self.stdout.write('未设置 DEEPSEEK_API_KEY，保持离线模拟模型。')
            return

        preset = next((p for p in MODEL_PROVIDER_PRESETS if p.get('key') == 'deepseek'), {})
        base_url = (os.environ.get('DEEPSEEK_BASE_URL') or '').strip() or preset.get('base_url') or 'https://api.deepseek.com'
        model = (os.environ.get('DEEPSEEK_MODEL') or '').strip() or preset.get('default_model') or 'deepseek-v4-flash'
        backup_model = (os.environ.get('DEEPSEEK_BACKUP_MODEL') or '').strip() or preset.get('backup_model') or ''

        provider, created = AIOpsModelProvider.objects.update_or_create(
            name=(os.environ.get('DEEPSEEK_PROVIDER_NAME') or 'DeepSeek（演示环境）').strip(),
            defaults={
                'provider_type': AIOpsModelProvider.PROVIDER_OPENAI_COMPATIBLE,
                'base_url': base_url,
                'provider_preset': 'deepseek',
                'default_model': model,
                'backup_model': backup_model,
                'temperature': preset.get('temperature', 0.2),
                'max_tokens': preset.get('max_tokens', 10000),
                'timeout_seconds': preset.get('timeout_seconds', 60),
                'price_currency': AIOpsModelProvider.CURRENCY_CNY,
                'is_enabled': True,
                'last_test_status': AIOpsModelProvider.STATUS_UNKNOWN,
                'last_test_message': '由 provision_llm_provider 自动接入',
            },
        )
        provider.set_api_key(api_key)
        provider.save(update_fields=['api_key_encrypted'])

        config = get_agent_config()
        if config.default_provider_id != provider.id:
            config.default_provider = provider
            config.save(update_fields=['default_provider'])

        self.stdout.write(
            self.style.SUCCESS(
                f"DeepSeek 已接入: {provider.name} / {model} (base={base_url}, "
                f"default_provider={'是' if config.default_provider_id == provider.id else '否'})"
            )
        )
