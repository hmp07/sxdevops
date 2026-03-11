from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import NginxEnvironment, NginxDomain, NginxRoute
from .serializers import NginxEnvironmentSerializer, NginxDomainSerializer, NginxRouteSerializer
from .nginx_conf_generator import generate_domain_conf
import paramiko
import os


def _get_ssh_client(env):
    """创建 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=env.ip_address,
        port=env.ssh_port or 22,
        username=env.ssh_user or 'root',
        password=env.ssh_password or None,
        timeout=10,
    )
    return client


def _ssh_exec(client, cmd):
    """执行远程命令并返回 stdout"""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=15)
    return stdout.read().decode('utf-8', errors='replace').strip()


def _deploy_domain_conf(domain_obj):
    """通过 SSH 部署域名配置文件到远程 Nginx"""
    env = domain_obj.environment
    nginx_path = env.nginx_path or '/etc/nginx'
    conf_dir = f'{nginx_path}/conf.d'
    disabled_dir = f'{conf_dir}/disabled'
    filename = domain_obj.conf_filename
    conf_content = generate_domain_conf(domain_obj)

    try:
        client = _get_ssh_client(env)

        # 确保目录存在
        _ssh_exec(client, f'mkdir -p {conf_dir} {disabled_dir}')

        if domain_obj.enabled:
            # 写入到 conf.d/
            sftp = client.open_sftp()
            with sftp.file(f'{conf_dir}/{filename}', 'w') as f:
                f.write(conf_content)
            sftp.close()
            # 删除 disabled 下的同名文件 (如果有)
            _ssh_exec(client, f'rm -f {disabled_dir}/{filename}')
        else:
            # 移到 disabled/
            sftp = client.open_sftp()
            with sftp.file(f'{disabled_dir}/{filename}', 'w') as f:
                f.write(conf_content)
            sftp.close()
            # 删除 conf.d 下的同名文件
            _ssh_exec(client, f'rm -f {conf_dir}/{filename}')

        # 重载 nginx
        _ssh_exec(client, 'nginx -t && nginx -s reload')
        client.close()
        return True, '配置已部署'
    except Exception as e:
        return False, str(e)


def _deploy_cert_files(domain_obj):
    """通过 SSH 写入证书文件到远程"""
    env = domain_obj.environment
    nginx_path = env.nginx_path or '/etc/nginx'
    ssl_dir = f'{nginx_path}/ssl'
    safe_domain = domain_obj.domain.replace('*', '_wc_').replace('.', '_')

    cert_path = f'{ssl_dir}/{safe_domain}.pem'
    key_path = f'{ssl_dir}/{safe_domain}.key'

    try:
        client = _get_ssh_client(env)
        _ssh_exec(client, f'mkdir -p {ssl_dir}')

        sftp = client.open_sftp()
        with sftp.file(cert_path, 'w') as f:
            f.write(domain_obj.cert_content)
        with sftp.file(key_path, 'w') as f:
            f.write(domain_obj.key_content)
        # 设置权限
        _ssh_exec(client, f'chmod 600 {key_path}')
        sftp.close()
        client.close()

        # 更新模型中的路径
        domain_obj.cert_path = cert_path
        domain_obj.key_path = key_path
        domain_obj.save(update_fields=['cert_path', 'key_path'])

        return True, f'证书已部署到 {ssl_dir}/'
    except Exception as e:
        return False, str(e)


class NginxEnvironmentViewSet(viewsets.ModelViewSet):
    """Nginx 环境管理"""
    queryset = NginxEnvironment.objects.all()
    serializer_class = NginxEnvironmentSerializer
    search_fields = ['name', 'ip_address']

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试 SSH 连接"""
        env = self.get_object()
        try:
            client = _get_ssh_client(env)
            stdin, stdout, stderr = client.exec_command('nginx -v', timeout=5)
            err_output = stderr.read().decode('utf-8', errors='replace').strip()
            out_output = stdout.read().decode('utf-8', errors='replace').strip()
            output = err_output if err_output else out_output
            client.close()

            if 'nginx version' in output.lower():
                env.status = 'connected'
                env.save(update_fields=['status'])
                return Response({'success': True, 'message': f'连接成功: {output}'})
            else:
                env.status = 'error'
                env.save(update_fields=['status'])
                return Response({'success': False, 'message': f'连接成功但未检测到 Nginx: {output}'})
        except Exception as e:
            env.status = 'disconnected'
            env.save(update_fields=['status'])
            return Response({'success': False, 'message': f'连接失败: {str(e)}'})


class NginxDomainViewSet(viewsets.ModelViewSet):
    """Nginx 域名管理"""
    queryset = NginxDomain.objects.select_related('environment').all()
    serializer_class = NginxDomainSerializer
    search_fields = ['domain']
    filterset_fields = ['environment']

    def perform_create(self, serializer):
        domain = serializer.save()
        # 如果有证书内容, 自动部署
        if domain.cert_content and domain.key_content:
            _deploy_cert_files(domain)

    def perform_update(self, serializer):
        domain = serializer.save()
        if domain.cert_content and domain.key_content:
            _deploy_cert_files(domain)

    @action(detail=True, methods=['post'])
    def toggle_ssl(self, request, pk=None):
        """切换 SSL 启用/禁用并重新部署配置"""
        domain = self.get_object()
        enable = request.data.get('enable', not domain.ssl_enabled)

        if enable and (not domain.cert_path or not domain.key_path):
            return Response({'success': False, 'message': '请先上传证书后再启用 SSL'})

        domain.ssl_enabled = enable
        domain.save(update_fields=['ssl_enabled'])

        ok, msg = _deploy_domain_conf(domain)
        return Response({
            'success': ok,
            'message': f'SSL {"已启用" if enable else "已禁用"}: {msg}',
            'ssl_enabled': domain.ssl_enabled,
        })

    @action(detail=True, methods=['post'])
    def deploy_cert(self, request, pk=None):
        """部署证书文件到远程"""
        domain = self.get_object()
        cert = request.data.get('cert_content', domain.cert_content)
        key = request.data.get('key_content', domain.key_content)

        if not cert or not key:
            return Response({'success': False, 'message': '请提供证书和私钥内容'})

        domain.cert_content = cert
        domain.key_content = key
        domain.save(update_fields=['cert_content', 'key_content'])

        ok, msg = _deploy_cert_files(domain)
        return Response({'success': ok, 'message': msg})

    @action(detail=True, methods=['post'])
    def deploy_conf(self, request, pk=None):
        """部署域名配置到远程"""
        domain = self.get_object()
        ok, msg = _deploy_domain_conf(domain)
        return Response({'success': ok, 'message': msg})

    @action(detail=True, methods=['get'])
    def preview_conf(self, request, pk=None):
        """预览生成的配置文件内容"""
        domain = self.get_object()
        conf = generate_domain_conf(domain)
        return Response({'conf': conf, 'filename': domain.conf_filename})


class NginxRouteViewSet(viewsets.ModelViewSet):
    """Nginx 路由管理"""
    queryset = NginxRoute.objects.select_related('nginx_domain', 'nginx_domain__environment').all()
    serializer_class = NginxRouteSerializer
    search_fields = ['location', 'upstream_servers']
    filterset_fields = ['nginx_domain']
