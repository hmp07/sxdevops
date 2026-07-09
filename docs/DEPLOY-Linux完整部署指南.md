# SxDevOps Linux 完整部署指南

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| 操作系统 | CentOS 7+ / Ubuntu 20.04+ / Debian 11+ | x86_64 |
| Docker | 20.10+ | 含 docker-compose 或 docker compose 插件 |
| CPU | 2 核+ | 推荐 4 核 |
| 内存 | 4 GB+ | 推荐 8 GB |
| 磁盘 | 20 GB+ | 推荐 50 GB |

## 一、服务器初始化

```bash
# 1. 设置时区
timedatectl set-timezone Asia/Shanghai

# 2. 关闭 SELinux（CentOS/RedHat）
setenforce 0
sed -i 's/SELINUX=enforcing/SELINUX=disabled/' /etc/selinux/config

# 3. 关闭防火墙或在防火墙开放端口
# firewalld:
firewall-cmd --add-port=8000/tcp --permanent && firewall-cmd --reload
# ufw (Ubuntu):
ufw allow 8000/tcp

# 4. 安装 Docker（如未安装）
curl -fsSL https://get.docker.com | bash
systemctl enable docker && systemctl start docker
docker --version

# 5. 安装 Docker Compose（如未安装）
curl -SL "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
docker-compose --version
```

## 二、获取代码

```bash
# 方式一：Git 克隆
cd /opt
git clone https://gitee.com/heimp/sxdevops.git
cd sxdevops

# 方式二：手动上传
# 将项目目录打包上传至 /opt/sxdevops，解压后进入
```

## 三、配置说明

### 3.1 Docker Compose 环境变量

编辑 `docker-compose.yml` 中 `sxdevops` 服务的 `environment` 段：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_ENGINE` | `mysql` | 数据库引擎：`mysql` 或 `sqlite` |
| `MYSQL_HOST` | `mysql` | MySQL 主机名（容器名） |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_DATABASE` | `sxdevops` | 数据库名 |
| `MYSQL_USER` | `sxdevops` | 数据库用户 |
| `MYSQL_PASSWORD` | `sxdevops_password` | **务必修改！** 数据库密码 |
| `SECRET_KEY` | 默认值 | **务必修改！** Django 密钥 |
| `DEBUG` | `0` | 生产环境必须为 `0` |
| `SXDEVOPS_SEED_DATA` | `1` | 首次部署设为 1，后续启动设为 0 |
| `SXDEVOPS_SEED_TEMPLATES` | `1` | 首次部署设为 1，后续启动设为 0 |
| `SXDEVOPS_MIGRATE` | `1` | 自动执行数据库迁移 |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 连接地址 |
| `CHANNEL_REDIS_URL` | `redis://redis:6379/1` | WebSocket 通道层 |

### 3.2 MySQL 密码

修改两处密码（必须一致）：
```yaml
# docker-compose.yml
sxdevops:
  environment:
    MYSQL_PASSWORD: 你的密码

mysql:
  environment:
    MYSQL_PASSWORD: 你的密码          # 同 sxdevops 的 MYSQL_PASSWORD
    MYSQL_ROOT_PASSWORD: 你的root密码  # 更强的密码
```

### 3.3 Django SECRET_KEY

```bash
# 生成随机密钥
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

将输出替换 `SECRET_KEY` 值。

## 四、一键部署

```bash
cd /opt/sxdevops

# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f sxdevops

# 等待看到类似输出：
# Listening on TCP address 0.0.0.0:8000
```

首次启动会自动：
1. 等待 MySQL 和 Redis 就绪（最多 120 秒）
2. 执行数据库迁移
3. 导入种子数据（用户、模板）
4. 启动 Daphne ASGI 服务器

## 五、访问与初始登录

```
地址：http://<服务器IP>:8000
账号：admin
密码：Admin@123456
```

## 六、初始配置（按顺序操作）

### 6.1 修改默认密码
登录后 → 用户管理 → 编辑 admin → 修改密码

### 6.2 配置模型提供商
智能助手 → 模型供应商 → 新增

```
名称：DeepSeek 体验版
提供商类型：OpenAI 兼容
Base URL：https://api.deepseek.com/v1
API Key：（你的 DeepSeek API Key）
默认模型：deepseek-chat
```

### 6.3 配置 Zabbix 数据源
监控中心 → Zabbix 数据源 → 新增

```
名称：公司测试开发系统
API URL：http://<Zabbix服务器IP>/api_jsonrpc.php
认证方式：userpass
用户名：Admin
密码：（Zabbix 密码）
```

保存后自动触发：主机导入 → 设备映射 → 告警轮询

### 6.4 配置 iTop 数据源
CMDB → CMDB 数据源 → iTop → 新增

```
名称：iTop
API URL：http://<iTop服务器IP>/itop/webservices/rest.php
版本：1.3
用户名：admin
密码：（iTop 密码）
组织：你的组织名
```

保存后点击"触发同步"，自动导入 CI 类型、配置项、拓扑关系。

### 6.5 配置知识图谱环境
智能助手 → 知识图谱 → 编辑"公司测试开发系统"环境

勾选对应的：
- Zabbix 数据源
- iTop 数据源
- 任务中心资源底座环境
- 告警环境

保存后知识图谱即可展示完整数据。

## 七、验证部署

```bash
# 1. 登录接口
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@123456"}'
# 应返回 token

# 2. Bootstrap
curl -H "Authorization: Token <token>" \
  http://localhost:8000/api/aiops/bootstrap/
# 应返回 HTTP 200

# 3. 知识图谱
curl -H "Authorization: Token <token>" \
  "http://localhost:8000/api/aiops/knowledge-graph/?environment=公司测试开发系统"
# 应返回 nodes 和 edges

# 4. CMDB 仪表盘
curl -H "Authorization: Token <token>" \
  http://localhost:8000/api/cmdb/dashboard/stats/
# 应返回 total_ci, relation_count 等

# 5. 告警列表
curl -H "Authorization: Token <token>" \
  "http://localhost:8000/api/ops/observability/alerts/?limit=3"
# 应返回告警数据
```

## 八、常用运维命令

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down

# 重启
docker-compose restart sxdevops

# 查看日志
docker-compose logs -f sxdevops
docker-compose logs --tail=100 sxdevops

# 进入容器
docker exec -it sxdevops-app /bin/bash

# 重建镜像（代码更新后）
docker-compose up -d --build

# 完全清理（含数据卷）
docker-compose down -v
```

## 九、手动触发数据同步

### Zabbix 主机导入
```bash
docker exec sxdevops-app python manage.py shell -c "
from ops.models import ZabbixDataSource
ds = ZabbixDataSource.objects.filter(is_enabled=True).first()
ds.save()  # 触发信号导入
print('Done')
"
```

### iTop 全量同步
```bash
docker exec sxdevops-app python manage.py shell -c "
from cmdb.models import iTopDataSource
from cmdb.itop_sync import run_full_sync
ds = iTopDataSource.objects.filter(is_enabled=True).first()
run_full_sync(ds)
print('Done')
"
```

### 设备映射修复
```bash
docker exec sxdevops-app python manage.py shell -c "
from ops.device_matcher import reconcile_device_mappings
stats = reconcile_device_mappings()
print(stats)
"
```

## 十、数据备份

```bash
# 备份 MySQL 数据库
docker exec sxdevops-mysql mysqldump -u sxdevops -psxdevops_password sxdevops \
  > /opt/backup/sxdevops_$(date +%Y%m%d_%H%M%S).sql

# 恢复
docker exec -i sxdevops-mysql mysql -u sxdevops -psxdevops_password sxdevops \
  < /opt/backup/sxdevops_20260709_120000.sql

# 备份整个项目
tar czf /opt/backup/sxdevops_$(date +%Y%m%d).tar.gz -C /opt sxdevops
```

## 十一、故障排除

### 容器启动失败
```bash
docker-compose logs sxdevops   # 查看应用日志
docker-compose logs mysql      # 查看数据库日志
docker-compose ps              # 查看容器状态
```

### 数据库连接失败
检查 MySQL 健康检查是否通过：
```bash
docker exec sxdevops-mysql mysqladmin ping -h 127.0.0.1 -uroot -psxdevops_root_password --silent
```

### Daphne 启动但无法访问
```bash
# 确认端口监听
docker exec sxdevops-app netstat -tlnp | grep 8000

# 确认防火墙
iptables -L -n | grep 8000
```

### 知识图谱无数据
1. 确认知识图谱环境已配置 Zabbix/iTop 数据源 ID
2. 确认 Zabbix/iTop 数据同步已完成
3. 确认 TaskResourceGroup ID 与环境配置匹配

### 智能助手无法回答问题
1. 确认模型提供商配置正确（API Key、Base URL）
2. 确认模型名与提供商支持的一致
3. 检查后端日志：`docker-compose logs sxdevops | grep -i error`
