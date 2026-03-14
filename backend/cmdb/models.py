from django.db import models

class CIType(models.Model):
    name = models.CharField("模型名称", max_length=50, unique=True)
    icon = models.CharField("内置图标", max_length=50, blank=True)
    color = models.CharField("主题色", max_length=20, default="#9c27b0")
    description = models.CharField("描述", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.ci_type.name}] {self.name}"

class CIRelation(models.Model):
    source = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='outgoing_relations')
    target = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='incoming_relations')
    relation_type = models.CharField("关系类型", max_length=50, choices=[('depends_on', '依赖'), ('runs_on', '运行在'), ('connects_to', '连接')])
    description = models.CharField("描述", max_length=200, blank=True)

class CostRecord(models.Model):
    ci = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='costs')
    month = models.CharField("归属月份", max_length=7) # YYYY-MM
    amount = models.DecimalField("金额(元)", max_digits=10, decimal_places=2)
    provider = models.CharField("云厂商", max_length=50, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)

class ResourceRequest(models.Model):
    applicant = models.CharField("申请人", max_length=50)
    resource_type = models.CharField("资源类型", max_length=50)
    specs = models.JSONField("规格要求", default=dict)
    reason = models.TextField("申请理由")
    status = models.CharField("状态", max_length=20, choices=[('pending', '待审批'), ('approved', '已批准'), ('rejected', '已拒绝'), ('provisioned', '已交付')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

class ResourceNode(models.Model):
    name = models.CharField("节点名称", max_length=100)
    node_type = models.CharField("节点类型", max_length=20, choices=[('biz', '业务线'), ('env', '环境')])
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    sort_order = models.IntegerField("排序", default=0)

    def __str__(self):
        return self.name
