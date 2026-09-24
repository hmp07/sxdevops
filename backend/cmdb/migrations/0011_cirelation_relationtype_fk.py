"""CIRelation.relation_type 由 CharField(choices) 升级为 FK(RelationType, to_field='code')。

SQLite 安全四步：加新列 → 回填 → 删旧列（先摘唯一约束）→ 改名并复原名列 → 重建约束。
"""

from django.db import migrations, models
import django.db.models.deletion


def backfill_relation_fk(apps, schema_editor):
    CIRelation = apps.get_model('cmdb', 'CIRelation')
    RelationType = apps.get_model('cmdb', 'RelationType')
    # 兜底：历史数据中的未知关系码也建注册表行，保证 FK 回填不丢数据
    known = set(RelationType.objects.values_list('code', flat=True))
    old_codes = set(CIRelation.objects.exclude(relation_type='').values_list('relation_type', flat=True))
    for code in old_codes - known:
        RelationType.objects.get_or_create(
            code=code,
            defaults={
                'name': code, 'display_name': code, 'description': '历史数据迁移生成',
                'is_system': False,
            },
        )
    for rel in CIRelation.objects.all().iterator():
        if rel.relation_type:
            rel.relation_fk_id = rel.relation_type
            rel.save(update_fields=['relation_fk'])


class Migration(migrations.Migration):

    dependencies = [
        ('cmdb', '0010_relationtype'),
    ]

    operations = [
        migrations.AddField(
            model_name='cirelation',
            name='relation_fk',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                to='cmdb.relationtype', to_field='code',
            ),
        ),
        migrations.RunPython(backfill_relation_fk, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='cirelation',
            name='cmdb_cirelation_unique_relation',
        ),
        migrations.RemoveField(
            model_name='cirelation',
            name='relation_type',
        ),
        migrations.RenameField(
            model_name='cirelation',
            old_name='relation_fk',
            new_name='relation_type',
        ),
        migrations.AlterField(
            model_name='cirelation',
            name='relation_type',
            field=models.ForeignKey(
                db_column='relation_type', on_delete=django.db.models.deletion.PROTECT,
                related_name='relations', to='cmdb.relationtype', to_field='code',
                verbose_name='关系类型',
            ),
        ),
        migrations.AddField(
            model_name='cirelation',
            name='attributes',
            field=models.JSONField(blank=True, default=dict, verbose_name='扩展属性'),
        ),
        migrations.AddConstraint(
            model_name='cirelation',
            constraint=models.UniqueConstraint(
                fields=('source', 'target', 'relation_type'),
                name='cmdb_cirelation_unique_relation',
            ),
        ),
    ]
