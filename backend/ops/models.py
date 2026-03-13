from django.db import models


class Host(models.Model):
    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
        ('warning', '告警'),
    ]

    hostname = models.CharField('主机名', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    os_type = models.CharField('操作系统', max_length=64, default='Linux')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='online')
    cpu_usage = models.FloatField('CPU 使用率 (%)', default=0)
    memory_usage = models.FloatField('内存使用率 (%)', default=0)
    disk_usage = models.FloatField('磁盘使用率 (%)', default=0)
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主机'
        verbose_name_plural = '主机'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.hostname} ({self.ip_address})'


class Deployment(models.Model):
    STATUS_CHOICES = [
        ('success', '成功'),
        ('failed', '失败'),
        ('running', '部署中'),
        ('pending', '待部署'),
        ('rollback', '已回滚'),
    ]
    ENV_CHOICES = [
        ('production', '生产'),
        ('staging', '预发布'),
        ('testing', '测试'),
        ('development', '开发'),
    ]

    app_name = models.CharField('应用名称', max_length=128)
    version = models.CharField('版本号', max_length=64)
    environment = models.CharField('环境', max_length=32, choices=ENV_CHOICES, default='testing')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    deployer = models.CharField('部署人', max_length=64, default='admin')
    description = models.TextField('描述', blank=True, default='')
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='部署主机')
    deployed_at = models.DateTimeField('部署时间', auto_now_add=True)

    class Meta:
        verbose_name = '部署记录'
        verbose_name_plural = '部署记录'
        ordering = ['-deployed_at']

    def __str__(self):
        return f'{self.app_name} v{self.version} -> {self.environment}'


class Alert(models.Model):
    LEVEL_CHOICES = [
        ('critical', '严重'),
        ('warning', '警告'),
        ('info', '信息'),
    ]

    title = models.CharField('告警标题', max_length=256)
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    source = models.CharField('来源', max_length=128)
    message = models.TextField('详情')
    is_acknowledged = models.BooleanField('已确认', default=False)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联主机')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警'
        verbose_name_plural = '告警'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.level}] {self.title}'


class LogEntry(models.Model):
    LEVEL_CHOICES = [
        ('error', 'ERROR'),
        ('warning', 'WARNING'),
        ('info', 'INFO'),
        ('debug', 'DEBUG'),
    ]

    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    service = models.CharField('服务名', max_length=128)
    message = models.TextField('日志内容')
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='来源主机')
    timestamp = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '日志'
        verbose_name_plural = '日志'
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.level}] {self.service}: {self.message[:50]}'


class K8sCluster(models.Model):
    """Kubernetes 集群连接"""
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('集群名称', max_length=128, unique=True)
    api_server = models.CharField('API Server', max_length=256, blank=True, default='')
    kubeconfig = models.TextField('KubeConfig', help_text='YAML 格式的 kubeconfig 内容')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'K8s 集群'
        verbose_name_plural = 'K8s 集群'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class DockerHost(models.Model):
    """Docker 环境主机（手工录入，独立于通用 Host）"""
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    docker_api_version = models.CharField('Docker API 版本', max_length=16, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Docker 环境'
        verbose_name_plural = 'Docker 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'

class NginxEnvironment(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    nginx_path = models.CharField('Nginx 路径', max_length=256, default='/etc/nginx')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 环境'
        verbose_name_plural = 'Nginx 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NginxCertificate(models.Model):
    """独立证书管理 — 证书可关联多个环境，推送到对应环境的 ssl 目录"""
    domain = models.CharField('证书域名', max_length=256, help_text='证书对应的域名')
    cert_content = models.TextField('证书内容 (PEM)', blank=True, default='')
    key_content = models.TextField('私钥内容 (KEY)', blank=True, default='')
    environments = models.ManyToManyField(NginxEnvironment, blank=True, verbose_name='关联环境', related_name='certificates')
    expires_at = models.DateTimeField('过期时间', null=True, blank=True)
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 证书'
        verbose_name_plural = 'Nginx 证书'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.domain}'

    @property
    def cert_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.pem'

    @property
    def key_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.key'


class NginxDomain(models.Model):
    """域名管理 — 一个域名对应一个 server block，可选关联证书"""
    environment = models.ForeignKey(NginxEnvironment, on_delete=models.CASCADE, verbose_name='所属环境', related_name='domains')
    domain = models.CharField('域名/IP', max_length=256, help_text='填写域名或 IP 地址')
    listen_port = models.IntegerField('监听端口', default=80)
    ssl_port = models.IntegerField('SSL 端口', default=443)
    certificate = models.ForeignKey(NginxCertificate, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联证书', related_name='linked_domains')
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 域名'
        verbose_name_plural = 'Nginx 域名'
        ordering = ['-created_at']
        unique_together = ('environment', 'domain', 'listen_port')

    def __str__(self):
        return f'{self.domain}:{self.listen_port} ({self.environment.name})'

    @property
    def ssl_enabled(self):
        return self.certificate is not None and self.certificate_id is not None

    @property
    def conf_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}_{self.listen_port}.conf'


class NginxRoute(models.Model):
    nginx_domain = models.ForeignKey(NginxDomain, on_delete=models.CASCADE, verbose_name='所属域名', related_name='routes')
    location = models.CharField('Location 路径', max_length=256, default='/')
    upstream_servers = models.TextField('后端地址', blank=True, default='', help_text='每行一个后端地址，如 http://127.0.0.1:8080')
    redirect_url = models.CharField('重定向地址', max_length=512, blank=True, default='')
    redirect_code = models.IntegerField('重定向状态码', default=301)
    custom_headers = models.TextField('自定义 Header (JSON)', blank=True, default='', help_text='[{"name":"X-Custom","value":"val"}]')
    proxy_set_headers = models.TextField('proxy_set_header (JSON)', blank=True, default='', help_text='[{"name":"Host","value":"$host"}]')
    client_max_body_size = models.CharField('上传大小限制', max_length=32, blank=True, default='10m')
    extra_directives = models.TextField('额外指令', blank=True, default='', help_text='原始 Nginx 指令，每行一条')
    enabled = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 路由'
        verbose_name_plural = 'Nginx 路由'
        ordering = ['-created_at']
        unique_together = ('nginx_domain', 'location')

    def __str__(self):
        return f'{self.nginx_domain.domain}{self.location}'

