"""生产管理员账号安全初始化（非演示种子）。

用途：生产部署关闭演示种子（SXDEVOPS_SEED_DATA=0）后，post_migrate 会用默认
演示口令兜底创建 admin；本命令把管理员口令切换为 .env 注入的随机口令，
或在账号缺失时用该口令创建。

环境变量：
  SXDEVOPS_ADMIN_USERNAME  管理员用户名（默认 admin）
  SXDEVOPS_ADMIN_PASSWORD  管理员口令（生产环境必须设置）
  SXDEVOPS_ADMIN_EMAIL     管理员邮箱（默认 <用户名>@example.com）

行为（幂等，可每次启动执行）：
  - 口令未配置：输出警告并跳过（账号仍为默认口令时明确提示风险）
  - 账号不存在：用环境变量口令创建超级管理员
  - 账号存在且口令仍是默认演示口令：重置为环境变量口令
  - 账号存在且口令已自定义：不做任何修改
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from rbac.services import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME


class Command(BaseCommand):
    help = '生产管理员账号初始化：按环境变量创建/加固 admin 口令（非演示种子）'

    def handle(self, *args, **options):
        User = get_user_model()
        username = (os.environ.get('SXDEVOPS_ADMIN_USERNAME') or DEFAULT_ADMIN_USERNAME).strip()
        password = (os.environ.get('SXDEVOPS_ADMIN_PASSWORD') or '').strip()
        email = (os.environ.get('SXDEVOPS_ADMIN_EMAIL') or f'{username}@example.com').strip()

        user = User.objects.filter(username=username).first()

        if not password:
            if user is None:
                self.stdout.write(self.style.WARNING(
                    f'未设置 SXDEVOPS_ADMIN_PASSWORD，且账号 {username} 不存在：'
                    '跳过初始化。生产环境请通过 .env 注入随机口令后重启。'
                ))
            elif user.check_password(DEFAULT_ADMIN_PASSWORD):
                self.stdout.write(self.style.WARNING(
                    f'账号 {username} 仍在使用默认演示口令！'
                    '请设置 SXDEVOPS_ADMIN_PASSWORD 后重启容器完成加固。'
                ))
            else:
                self.stdout.write(f'账号 {username} 口令已自定义，无需处理。')
            return

        if user is None:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(
                f'已创建超级管理员: {username}（口令来自 SXDEVOPS_ADMIN_PASSWORD）'
            ))
            return

        if user.check_password(DEFAULT_ADMIN_PASSWORD):
            user.set_password(password)
            user.save(update_fields=['password'])
            self.stdout.write(self.style.SUCCESS(
                f'账号 {username} 的默认演示口令已重置（口令来自 SXDEVOPS_ADMIN_PASSWORD）'
            ))
            return

        self.stdout.write(f'账号 {username} 已存在且口令已自定义，跳过。')
