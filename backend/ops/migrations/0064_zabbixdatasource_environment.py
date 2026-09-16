from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0063_grafanasetting_api_token_grafanasetting_jwt_secret_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='zabbixdatasource',
            name='environment',
            field=models.CharField(
                blank=True,
                default='',
                help_text='告警入库的 environment 取值；留空则使用数据源名',
                max_length=64,
                verbose_name='所属环境',
            ),
        ),
    ]
