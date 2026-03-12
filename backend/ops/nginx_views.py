from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import NginxEnvironment, NginxCertificate, NginxDomain, NginxRoute
from .serializers import NginxEnvironmentSerializer, NginxCertificateSerializer, NginxDomainSerializer, NginxRouteSerializer
from .nginx_conf_generator import generate_domain_conf
import paramiko
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from django.utils.timezone import make_aware, is_naive
from rest_framework.exceptions import ValidationError

def _parse_certificate(cert_data):
    if not cert_data:
        return None, None
    try:
        cert = x509.load_pem_x509_certificate(cert_data.encode('utf-8'), default_backend())
        domain = None
        for attribute in cert.subject:
            if attribute.oid == x509.NameOID.COMMON_NAME:
                domain = attribute.value
                break
        
        if not domain:
            try:
                ext = cert.extensions.get_extension_for_oid(x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                sans = ext.value.get_values_for_type(x509.DNSName)
                if sans:
                    domain = sans[0]
            except Exception:
                pass
        
        expires_at = cert.not_valid_after
        if is_naive(expires_at):
            expires_at = make_aware(expires_at)
            
        return domain, expires_at
    except Exception:
        return None, None


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
        _ssh_exec(client, f'mkdir -p {conf_dir} {disabled_dir}')

        if domain_obj.enabled:
            sftp = client.open_sftp()
            with sftp.file(f'{conf_dir}/{filename}', 'w') as f:
                f.write(conf_content)
            sftp.close()
            _ssh_exec(client, f'rm -f {disabled_dir}/{filename}')
        else:
            sftp = client.open_sftp()
            with sftp.file(f'{disabled_dir}/{filename}', 'w') as f:
                f.write(conf_content)
            sftp.close()
            _ssh_exec(client, f'rm -f {conf_dir}/{filename}')

        _ssh_exec(client, 'nginx -t && nginx -s reload')
        client.close()
        return True, '配置已部署'
    except Exception as e:
        return False, str(e)


def _push_cert_to_env(cert, env):
    """将证书推送到指定环境的 ssl 目录"""
    nginx_path = env.nginx_path or '/etc/nginx'
    ssl_dir = f'{nginx_path}/ssl'

    try:
        client = _get_ssh_client(env)
        _ssh_exec(client, f'mkdir -p {ssl_dir}')

        sftp = client.open_sftp()
        with sftp.file(f'{ssl_dir}/{cert.cert_filename}', 'w') as f:
            f.write(cert.cert_content)
        with sftp.file(f'{ssl_dir}/{cert.key_filename}', 'w') as f:
            f.write(cert.key_content)
        _ssh_exec(client, f'chmod 600 {ssl_dir}/{cert.key_filename}')
        sftp.close()
        client.close()
        return True, f'证书已推送到 {env.name} ({ssl_dir}/)'
    except Exception as e:
        return False, str(e)


def _remove_cert_from_env(cert, env):
    """从指定环境删除证书文件"""
    nginx_path = env.nginx_path or '/etc/nginx'
    ssl_dir = f'{nginx_path}/ssl'

    try:
        client = _get_ssh_client(env)
        _ssh_exec(client, f'rm -f {ssl_dir}/{cert.cert_filename} {ssl_dir}/{cert.key_filename}')
        client.close()
        return True, f'证书已从 {env.name} 删除'
    except Exception as e:
        return False, str(e)


class NginxEnvironmentViewSet(viewsets.ModelViewSet):
    """Nginx 环境管理"""
    queryset = NginxEnvironment.objects.all()
    serializer_class = NginxEnvironmentSerializer
    search_fields = ['name', 'ip_address']

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
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


class NginxCertificateViewSet(viewsets.ModelViewSet):
    """Nginx 证书管理"""
    queryset = NginxCertificate.objects.prefetch_related('environments').all()
    serializer_class = NginxCertificateSerializer
    search_fields = ['domain']

    def perform_create(self, serializer):
        cert_content = serializer.validated_data.get('cert_content', '')
        domain, expires_at = _parse_certificate(cert_content)
        if not domain:
            raise ValidationError({'cert_content': '无效的证书内容，无法提取域名信息。'})
        serializer.save(domain=domain, expires_at=expires_at)

    def perform_update(self, serializer):
        cert_content = serializer.validated_data.get('cert_content', '')
        if cert_content:
            domain, expires_at = _parse_certificate(cert_content)
            if not domain:
                raise ValidationError({'cert_content': '无效的证书内容，无法提取域名信息。'})
            serializer.save(domain=domain, expires_at=expires_at)
        else:
            serializer.save()

    @action(detail=True, methods=['post'])
    def link_env(self, request, pk=None):
        """关联环境并推送证书"""
        cert = self.get_object()
        env_id = request.data.get('environment_id')
        if not env_id:
            return Response({'success': False, 'message': '请提供 environment_id'})

        try:
            env = NginxEnvironment.objects.get(id=env_id)
        except NginxEnvironment.DoesNotExist:
            return Response({'success': False, 'message': '环境不存在'})

        if not cert.cert_content or not cert.key_content:
            return Response({'success': False, 'message': '证书内容为空，无法推送'})

        cert.environments.add(env)
        ok, msg = _push_cert_to_env(cert, env)
        return Response({'success': ok, 'message': msg})

    @action(detail=True, methods=['post'])
    def unlink_env(self, request, pk=None):
        """取消关联环境并删除远程证书"""
        cert = self.get_object()
        env_id = request.data.get('environment_id')
        if not env_id:
            return Response({'success': False, 'message': '请提供 environment_id'})

        try:
            env = NginxEnvironment.objects.get(id=env_id)
        except NginxEnvironment.DoesNotExist:
            return Response({'success': False, 'message': '环境不存在'})

        cert.environments.remove(env)
        ok, msg = _remove_cert_from_env(cert, env)
        return Response({'success': ok, 'message': msg})

    @action(detail=True, methods=['post'])
    def push_all(self, request, pk=None):
        """重新推送证书到所有关联环境（更新证书内容后使用）"""
        cert = self.get_object()
        if not cert.cert_content or not cert.key_content:
            return Response({'success': False, 'message': '证书内容为空'})

        results = []
        for env in cert.environments.all():
            ok, msg = _push_cert_to_env(cert, env)
            results.append({'env': env.name, 'success': ok, 'message': msg})
        return Response({'success': True, 'results': results})


class NginxDomainViewSet(viewsets.ModelViewSet):
    """Nginx 域名管理"""
    queryset = NginxDomain.objects.select_related('environment', 'certificate').all()
    serializer_class = NginxDomainSerializer
    search_fields = ['domain']
    filterset_fields = ['environment']

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
