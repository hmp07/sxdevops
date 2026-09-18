"""历史明文凭据加密回填命令（幂等）。

扫描各模型中的凭据字段，将无 `enc:` 前缀的明文值加密回填。
默认 dry-run 预览；--apply 执行写入。已加密值自动跳过，可重复执行。
"""
from django.core.management.base import BaseCommand

from sxdevops.credential_cipher import encrypt_secret, is_encrypted

# (模型路径, 字段名)
CREDENTIAL_FIELDS = [
    ('ops.Host', 'ssh_password'),
    ('ops.TaskResource', 'ssh_password'),
    ('ops.ZabbixDataSource', 'password'),
    ('ops.DockerHost', 'ssh_password'),
    ('ops.NginxEnvironment', 'ssh_password'),
    ('sqlaudit.DataSource', 'password'),
    ('multicloud.CloudCredential', 'access_key_secret'),
]


class Command(BaseCommand):
    help = '将历史明文凭据加密回填（幂等，默认 dry-run，--apply 写入）'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='实际写入加密值（默认仅预览）')

    def handle(self, *args, **options):
        from django.db import connection

        apply = options['apply']
        total_plain = 0
        total_updated = 0
        for model_path, field_name in CREDENTIAL_FIELDS:
            app_label, model_name = model_path.split('.')
            model = __import__(app_label + '.models', fromlist=[model_name])
            model_cls = getattr(model, model_name)
            # ORM 读取会透明解密，检测必须基于库内原始值
            with connection.cursor() as cur:
                cur.execute(f'SELECT id, "{field_name}" FROM "{model_cls._meta.db_table}"')
                raw_by_pk = {row[0]: row[1] for row in cur.fetchall()}
            for instance in model_cls.objects.all():
                raw = raw_by_pk.get(instance.pk)
                value = str(raw) if raw else ''
                if not value or is_encrypted(value):
                    continue
                total_plain += 1
                if apply:
                    setattr(instance, field_name, encrypt_secret(value))
                    field_names = [f.name for f in model_cls._meta.fields]
                    update_fields = [field_name] + (['updated_at'] if 'updated_at' in field_names else [])
                    instance.save(update_fields=update_fields)
                    total_updated += 1
                else:
                    self.stdout.write(f'  [dry-run] {model_name}#{instance.pk} {field_name}: 明文待加密')
        mode = '已回填' if apply else '待回填（dry-run，加 --apply 执行）'
        self.stdout.write(self.style.SUCCESS(f'扫描完成：明文凭据 {total_plain} 处，{mode} {total_updated} 处。'))
