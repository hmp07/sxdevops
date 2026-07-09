from django.db import models

class CIType(models.Model):
    name = models.CharField("模型名称", max_length=50, unique=True)
    icon = models.CharField("内置图标", max_length=50, blank=True)
    color = models.CharField("主题色", max_length=20, default="#9c27b0")
    description = models.TextField("描述", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class ConfigItem(models.Model):
    name = models.CharField("配置项名称", max_length=100)
    ci_type = models.ForeignKey(CIType, on_delete=models.PROTECT, related_name='instances')
    business_line = models.CharField("业务线", max_length=50, blank=True)
    environment = models.CharField("环境", max_length=20, choices=[('prod', '生产'), ('test', '测试'), ('dev', '开发')], default='prod')
    admin_user = models.CharField("负责人", max_length=50, blank=True)
    status = models.CharField("状态", max_length=20, choices=[('active', '使用中'), ('idle', '闲置'), ('offline', '已下线')], default='active')
    attributes = models.JSONField("扩展属性", default=dict, blank=True)
    itop_datasource = models.ForeignKey(
        'iTopDataSource', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='config_items', verbose_name='iTop 数据源',
    )
    external_id = models.CharField('外部 ID', max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '配置项'
        verbose_name_plural = '配置项'
        ordering = ['-updated_at', 'name']
        indexes = [
            models.Index(fields=['itop_datasource', 'external_id']),
        ]

    def __str__(self):
        return f"[{self.ci_type.name}] {self.name}"

class CIRelation(models.Model):
    source = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='outgoing_relations')
    target = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='incoming_relations')
    relation_type = models.CharField(
        "关系类型",
        max_length=50,
        choices=[
            ('depends_on', '业务依赖'),
            ('runs_on', '部署在'),
            ('connects_to', '连接到'),
        ],
    )
    description = models.CharField("描述", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'target', 'relation_type'],
                name='cmdb_cirelation_unique_relation',
            )
        ]

class CostRecord(models.Model):
    ci = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='costs')
    month = models.CharField("归属月份", max_length=7) # YYYY-MM
    amount = models.DecimalField("金额(元)", max_digits=10, decimal_places=2)
    provider = models.CharField("云厂商", max_length=50, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['ci', 'month'],
                name='cmdb_costrecord_unique_ci_month',
            )
        ]

class ResourceRequest(models.Model):
    ENV_CHOICES = [('prod', '生产'), ('test', '测试'), ('dev', '开发')]
    PRIORITY_CHOICES = [('low', '低'), ('medium', '中'), ('high', '高')]
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已批准'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]

    title = models.CharField("申请标题", max_length=120, blank=True, default='')
    applicant = models.CharField("申请人", max_length=50)
    approver = models.CharField("审批人", max_length=50, blank=True, default='')
    resource_type = models.CharField("资源类型", max_length=50)
    specification = models.CharField("规格说明", max_length=200, blank=True, default='')
    business_line = models.CharField("业务线", max_length=50, blank=True, default='')
    environment = models.CharField("环境", max_length=20, choices=ENV_CHOICES, blank=True, default='')
    priority = models.CharField("优先级", max_length=16, choices=PRIORITY_CHOICES, default='medium')
    quantity = models.PositiveIntegerField("数量", default=1)
    specs = models.JSONField("规格要求", default=dict, blank=True)
    reason = models.TextField("申请理由")
    approval_comment = models.TextField("审批说明", blank=True, default='')
    fulfillment_note = models.TextField("交付说明", blank=True, default='')
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_at = models.DateTimeField("审批时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ResourceNode(models.Model):
    name = models.CharField("节点名称", max_length=100)
    node_type = models.CharField("节点类型", max_length=20, choices=[('biz', '业务线'), ('env', '环境')])
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    sort_order = models.IntegerField("排序", default=0)

    def __str__(self):
        return self.name


class iTopDataSource(models.Model):
    """iTop 运维管理系统数据源"""
    name = models.CharField("名称", max_length=128, unique=True)
    api_url = models.CharField("API 地址", max_length=256)
    api_version = models.CharField("API 版本", max_length=8, default="1.4")
    auth_user = models.CharField("用户名", max_length=64)
    auth_password = models.CharField("密码", max_length=256)
    organization = models.CharField("组织", max_length=128, blank=True)
    is_enabled = models.BooleanField("启用", default=True)
    sync_mode = models.CharField("同步模式", max_length=16, choices=[('full', '全量'), ('incremental', '增量')], default='full')
    sync_interval = models.PositiveIntegerField("同步间隔(秒)", default=3600)
    config = models.JSONField("同步配置", default=dict, blank=True)
    last_sync_at = models.DateTimeField("上次同步", null=True, blank=True)
    sync_status = models.CharField("同步状态", max_length=16, default='idle')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'iTop 数据源'
        verbose_name_plural = 'iTop 数据源'
        ordering = ['name']

    def __str__(self):
        return self.name
