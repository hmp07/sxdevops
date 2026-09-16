from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0064_zabbixdatasource_environment'),
    ]

    operations = [
        migrations.AddField(
            model_name='zabbixdatasource',
            name='business_line',
            field=models.CharField(
                blank=True,
                default='',
                help_text='同步主机时写入 Host.business_line 的默认值（权威覆盖）',
                max_length=64,
                verbose_name='默认业务线',
            ),
        ),
        migrations.AddField(
            model_name='zabbixdatasource',
            name='host_environment',
            field=models.CharField(
                blank=True,
                choices=[('prod', '生产'), ('test', '测试'), ('dev', '开发')],
                default='',
                help_text='同步主机时写入 Host.environment 的默认值（仅主机环境为空时写入）',
                max_length=20,
                verbose_name='默认主机环境',
            ),
        ),
    ]
