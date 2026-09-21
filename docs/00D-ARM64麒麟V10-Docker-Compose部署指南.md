# SxDevOps ARM64 麒麟 V10 Docker Compose 部署指南

本文档面向 **ARM64（aarch64）架构 + Kylin Linux Advanced Server V10** 环境的完整部署测试，覆盖环境准备、Docker 安装（在线/离线）、镜像清单与版本、构建步骤、Compose 配置、启动验证与排障。

---

## 一、环境要求

| 项目 | 要求 |
| ---- | ---- |
| 操作系统 | Kylin Linux Advanced Server V10（SP1/SP2/SP3 均可，CentOS 8 兼容系） |
| CPU 架构 | **aarch64 / ARM64**（`uname -m` 输出 `aarch64`） |
| 内存 | ≥ 4GB（推荐 8GB） |
| 磁盘 | ≥ 20GB 可用（MySQL + Redis + 应用镜像与数据） |
| Docker | Docker Engine 20.10+，Docker Compose v2 插件 |
| 网络 | 开放 8000 端口；首次构建需能访问 npm 与 PyPI 镜像源（离线交付可豁免） |

### 1.1 环境确认

```bash
# 架构确认（必须输出 aarch64）
uname -m

# 系统版本确认
cat /etc/kylin-release
cat /etc/os-release | grep -E "^(NAME|VERSION)="

# 资源确认
free -h
df -h /
```

---

## 二、Docker 安装

### 2.1 方式一：在线安装（可访问互联网时）

Kylin V10 兼容 CentOS 8 软件源，直接使用 Docker CE 官方源：

```bash
# 1. 安装依赖
sudo yum install -y yum-utils device-mapper-persistent-data lvm2

# 2. 添加 Docker CE 源（CentOS 8 兼容源）
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# 3. 安装 Docker Engine + Compose 插件
sudo yum install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# 4. 启动并设置开机自启
sudo systemctl enable --now docker

# 5. 验证（Compose 插件版本需为 v2）
docker version
docker compose version
```

> 若官方源不可达，可改用国内镜像源（如阿里云/清华的 docker-ce 源），或走 2.2 离线安装。

### 2.2 方式二：离线安装（内网环境）

在一台**同架构（aarch64）+ 可联网**的机器上下载 RPM 包：

```bash
# 联网机：下载 docker-ce 全家桶及其依赖
mkdir -p /tmp/docker-rpms && cd /tmp/docker-rpms
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
yumdownloader --resolve docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

将 `/tmp/docker-rpms` 拷贝到麒麟服务器后安装：

```bash
cd /path/to/docker-rpms
sudo yum localinstall -y *.rpm
sudo systemctl enable --now docker
docker compose version   # 验证
```

### 2.3 配置 daemon.json（推荐）

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "data-root": "/var/lib/docker",
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" },
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live"
  ]
}
EOF
sudo systemctl restart docker
docker info | grep -A3 "Registry Mirrors"   # 确认镜像源生效
```

---

## 三、镜像清单与版本

### 3.1 基础镜像（官方多架构镜像，均含 linux/arm64）

| 镜像 | 推荐固定版本 | 用途 | ARM64 说明 |
| ---- | ---- | ---- | ---- |
| `node` | `node:20-alpine` | 前端构建（Dockerfile 第一阶段） | ✅ 官方多架构 |
| `python` | `python:3.12-slim` | 后端运行（Dockerfile 第二阶段） | ✅ 官方多架构 |
| `mysql` | `mysql:8.0.36` | 业务数据库 | ✅ 官方多架构（8.0 全系支持 arm64） |
| `redis` | `redis:7.2.5-alpine` | 缓存 + Channels 通道层 | ✅ 官方多架构 |

### 3.2 自建镜像

| 镜像 | 说明 |
| ---- | ---- |
| `sxdevops:latest-arm64` | 项目多阶段构建产物：前端 dist + Django 后端 + Daphne，ENTRYPOINT 自动迁移、模板初始化与管理员账号初始化 |

### 3.3 架构一致性原则

⚠ **必须保证所有镜像架构一致（全 arm64）**。混用 x86 镜像会报 `exec format error`。验证方法：

```bash
docker inspect mysql:8.0.36 | grep -i architecture   # 应输出 "Architecture": "arm64"
docker inspect sxdevops:latest-arm64 | grep -i architecture
```

---

## 四、构建与镜像准备

### 4.1 方式一：目标机上直接构建（可联网）

```bash
# 1. 获取源码
cd /opt
git clone <项目地址> sxdevops
cd sxdevops

# 2. （可选）配置前端 npm 国内源，加速构建
#    在 Dockerfile 的 `RUN npm ci` 前加:
#    RUN npm config set registry https://registry.npmmirror.com
#    或构建时直接使用默认官方源（可访问即可）

# 3. 构建并启动（pip 默认走阿里云 PyPI 镜像，见 Dockerfile ARG PIP_INDEX_URL）
docker compose -f docker-compose.arm64.yml up -d --build
```

构建时间参考：首次构建 3-8 分钟（依赖网络），依赖缓存后 1-2 分钟。

### 4.2 方式二：离线镜像包交付（目标机无外网）

**① 在联网构建机（同架构 arm64，或使用 buildx 交叉构建）上：**

```bash
# 构建应用镜像
docker compose -f docker-compose.arm64.yml build

# 拉取并固定基础镜像
docker pull mysql:8.0.36
docker pull redis:7.2.5-alpine

# 导出全部镜像
docker save sxdevops:latest-arm64 mysql:8.0.36 redis:7.2.5-alpine \
  -o sxdevops-arm64-images.tar
```

若构建机是 x86 架构（如 Windows/Mac 开发机），使用 buildx 交叉构建：

```bash
docker buildx create --name sxarm --use
docker buildx build --platform linux/arm64 \
  -t sxdevops:latest-arm64 --load .
docker save sxdevops:latest-arm64 mysql:8.0.36 redis:7.2.5-alpine \
  -o sxdevops-arm64-images.tar
```

**② 拷贝到麒麟服务器并导入：**

```bash
docker load -i sxdevops-arm64-images.tar
docker images    # 确认三个镜像均存在且为 arm64
```

---

## 五、Compose 配置文件说明

使用仓库 `docker-compose.arm64.yml`（与 `docker-compose.yml` 等价，基础镜像固定版本）。三个服务：

| 服务 | 端口 | 数据卷 | 说明 |
| ---- | ---- | ---- | ---- |
| `sxdevops` | 8000 | — | 自建应用（Daphne ASGI，前端静态文件内嵌） |
| `mysql` | 内部 3306 | `mysql_data` | MySQL 8，utf8mb4，默认认证插件 caching_sha2_password，健康检查 `mysqladmin ping` |
| `redis` | 内部 6379 | `redis_data` | Redis 7，AOF 持久化，健康检查 `redis-cli ping` |

应用环境变量（`environment` 段）：

| 变量 | 来源 | 说明 |
| ---- | ---- | ---- |
| `DATABASE_ENGINE` | 固定值 `mysql` | 数据库引擎 |
| `MYSQL_HOST/PORT/DATABASE/USER` | 固定值 | 与 mysql 服务环境一致 |
| `MYSQL_PASSWORD` | **.env 注入**（`${MYSQL_PASSWORD:?...}`，未配置启动即报错） | 业务库口令，与 mysql 服务共用同一变量 |
| `MYSQL_ROOT_PASSWORD` | **.env 注入** | MySQL root 口令（仅 mysql 服务使用） |
| `REDIS_URL` / `CHANNEL_REDIS_URL` | 固定值 | 缓存与 WebSocket 通道层 |
| `SECRET_KEY` | **.env 注入**（`${SECRET_KEY:?...}`） | Django 密钥，部署时生成随机值（`openssl rand -hex 32`） |
| `SXDEVOPS_WAIT_FOR_DB` | 1 | 启动前等待 MySQL 就绪 |
| `SXDEVOPS_MIGRATE` | 1 | 自动执行数据库迁移 |
| `SXDEVOPS_SEED_DATA` | 0 | **生产默认关闭演示种子数据**（seed_data 生成的全部为演示数据）；需要演示数据时改 1 |
| `SXDEVOPS_SEED_TEMPLATES` | 1 | 工具市场内置模板 + 默认知识图谱环境（产品基础数据，建议保留） |
| `SXDEVOPS_ADMIN_PASSWORD` | **.env 注入**（`${SXDEVOPS_ADMIN_PASSWORD:?...}`） | 管理员账号口令；每次启动由 `ensure_admin` 创建/加固 admin 账号（默认演示口令自动重置为该值） |

---

## 六、部署启动步骤

```bash
# 1. 进入项目目录（含 docker-compose.arm64.yml）
cd /opt/sxdevops

# 2. 准备 .env 环境变量文件（敏感配置注入，未配置启动会直接报错）
cp .env.arm64.example .env
sed -i "s/change-me-please-run-openssl-rand-hex-32/$(openssl rand -hex 32)/" .env
sed -i "s/change-me-please-run-openssl-rand-hex-16/$(openssl rand -hex 16)/g" .env
sed -i "s/change-me-please-run-openssl-rand-hex-16-admin/$(openssl rand -hex 16)/" .env
# 确认替换成功（不应再包含 change-me）
grep -c change-me .env || echo "OK: .env 口令已随机化"

# 3. 启动全部服务（compose 自动读取项目目录 .env）
docker compose -f docker-compose.arm64.yml up -d

# 4. 查看启动进度（等待迁移 + 模板初始化完成，约 1-2 分钟）
docker compose -f docker-compose.arm64.yml logs -f sxdevops
# 看到 "Listening on TCP address 0.0.0.0:8000" 即启动完成

# 5. 查看容器状态（三个容器均 Up/healthy）
docker compose -f docker-compose.arm64.yml ps
```

### 6.1 防火墙放行

```bash
# Kylin V10 默认启用 firewalld，放行 8000 端口
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

> 若环境使用 SELinux（默认 enforcing），Docker 数据卷一般不受影响；如遇权限问题参考第八节排障。

---

## 七、验证清单

```bash
# 1. HTTP 可达（登录页 200）
curl -I http://<服务器IP>:8000/login

# 2. API 登录冒烟（口令来自 .env 的 SXDEVOPS_ADMIN_PASSWORD）
ADMIN_PASSWORD=$(grep '^SXDEVOPS_ADMIN_PASSWORD=' .env | cut -d= -f2-)
curl -s -X POST http://<服务器IP>:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PASSWORD\"}" | head -c 200
# 返回 {"token":"..."} 即成功

# 3. 浏览器验证
#    访问 http://<服务器IP>:8000 → 以 admin / .env 口令登录
#    核对：平台正常登录；告警/主机/事件墙等页面为空（生产默认不加载演示数据）；
#          工具市场模板存在；AIOps 无演示会话

# 4. 数据持久化验证
docker compose -f docker-compose.arm64.yml restart
# 重启后数据完整（初始化不会重复执行）

# 5. 架构一致性复查
for img in sxdevops:latest-arm64 mysql:8.0.36 redis:7.2.5-alpine; do
  docker inspect $img --format "{{.Id}}: {{.Architecture}}"
done
```

---

## 八、常见问题排障

| 现象 | 原因与处理 |
| ---- | ---- |
| `exec format error` | 镜像架构与主机不匹配（x86 镜像跑在 arm64）。按 3.3 节逐镜像确认 Architecture=arm64，重新拉取/构建 |
| `docker compose: command not found` | Compose 插件未安装。安装 `docker-compose-plugin`（见 2.1/2.2）；老式独立二进制可改用 `docker-compose` 命令 |
| MySQL 容器反复重启 | ① 数据卷残留旧版本数据：`docker compose down -v` 清卷重建（会清数据）② 查看日志 `docker logs sxdevops-mysql` |
| 登录提示「用户名或密码错误」 | 账号缺失或 .env 口令未生效（旧版 compose 未接线 `SXDEVOPS_ADMIN_PASSWORD`），按 9.3 节排查处理 |
| MySQL 日志 MY-013360 告警（mysql_native_password 弃用） | 旧版 compose 指定了已弃用的认证插件。升级新代码重建镜像后，按 9.2 节迁移存量账号即可消除 |
| 应用容器在"等待 MySQL"后超时退出 | MySQL 未在 120s 内通过健康检查；确认资源充足（arm64 低配机首次初始化较慢，可提高内存） |
| `docker pull` 超时 | Docker Hub 不可达。配置 2.3 节 registry-mirrors，或使用离线导入（4.2 节） |
| 构建时 `npm ci` 失败 | npm 源不可达。在 Dockerfile `npm ci` 前加 `RUN npm config set registry https://registry.npmmirror.com` |
| 构建时 pip 安装失败 | PyPI 源不可达。构建时覆盖 `--build-arg PIP_INDEX_URL=http://内网PyPI源/simple/` |
| SELinux 导致卷挂载权限问题 | `sudo chcon -Rt svirt_sandbox_file_t` 或临时 `setenforce 0`（不推荐长期） |
| 麒麟系统 yum 源报错 | 使用系统自带麒麟源或内网 yum 源；Docker 安装走 2.2 离线 RPM 方式最稳 |

---

## 九、常用运维命令

```bash
# 查看日志
docker compose -f docker-compose.arm64.yml logs -f sxdevops

# 停止 / 启动（数据保留）
docker compose -f docker-compose.arm64.yml down
docker compose -f docker-compose.arm64.yml up -d

# 清空数据（慎用，删除数据库与 Redis 数据）
docker compose -f docker-compose.arm64.yml down -v

# 升级：更新源码后重新构建
docker compose -f docker-compose.arm64.yml up -d --build

# 备份 MySQL
docker exec sxdevops-mysql sh -c \
  'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" sxdevops' > sxdevops-backup-$(date +%F).sql
```

### 9.1 清理演示种子数据（旧环境升级）

若环境是按旧版指南部署的（首次启动自动加载了演示数据），升级新代码后按以下步骤清理：

```bash
# 1. 更新源码并重建镜像（含新的 clean_demo_data / ensure_admin 命令）
git pull
docker compose -f docker-compose.arm64.yml up -d --build

# 2. 预览将要删除的演示数据（dry-run，仅打印不执行）
docker compose -f docker-compose.arm64.yml exec sxdevops python manage.py clean_demo_data

# 3. 确认无误后执行清理
docker compose -f docker-compose.arm64.yml exec sxdevops python manage.py clean_demo_data --yes

# 4. 管理员口令加固：.env 设置 SXDEVOPS_ADMIN_PASSWORD 后重建容器
docker compose -f docker-compose.arm64.yml up -d --force-recreate
```

清理保留：管理员账号、工具市场内置模板、默认知识图谱环境（其演示绑定重置为空）。
注意：清理命令按演示数据特征匹配删除，仅应在尚未录入真实业务数据的环境执行；
已有真实数据时请先核对第 2 步 dry-run 输出，确认无误再执行。

### 9.2 MySQL 认证插件迁移（消除 mysql_native_password 弃用告警）

新版 compose 已移除 `--default-authentication-plugin=mysql_native_password`（MySQL 8.0 默认
caching_sha2_password，应用侧 PyMySQL + cryptography 已兼容）。已部署环境按以下步骤迁移存量账号：

```bash
# 1. 更新代码并重建镜像（应用镜像内含 cryptography，支持 caching_sha2_password）
git pull
docker compose -f docker-compose.arm64.yml up -d --build

# 2. 确认应用侧依赖就绪
docker exec sxdevops python -c "import pymysql, cryptography; print(pymysql.__version__, cryptography.__version__)"

# 3. 迁移存量账号（口令来自容器内环境变量，不落盘不暴露）
#    注意：compose 参数只影响新建账号，已部署环境的存量账号必须显式 ALTER USER
docker exec sxdevops-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
ALTER USER IF EXISTS "sxdevops"@"%" IDENTIFIED WITH caching_sha2_password BY "$MYSQL_PASSWORD";
ALTER USER IF EXISTS "root"@"%" IDENTIFIED WITH caching_sha2_password BY "$MYSQL_ROOT_PASSWORD";
ALTER USER IF EXISTS "root"@"localhost" IDENTIFIED WITH caching_sha2_password BY "$MYSQL_ROOT_PASSWORD";
SQL'

# 4. 重启应用容器并验证
docker compose -f docker-compose.arm64.yml restart sxdevops
docker compose -f docker-compose.arm64.yml logs --tail 20 sxdevops-mysql
# MY-013360 告警消失；按第七节登录冒烟确认平台正常

# 5. 可随时复核账号插件状态（预期均为 caching_sha2_password）
docker exec sxdevops-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT user, host, plugin FROM mysql.user;"'
```

> 说明：`docker exec sh -c '...'` 单引号内变量由容器内 shell 展开，口令不会出现在宿主机命令历史中。
> 若迁移后应用无法连接，先核对第 2 步依赖是否就绪；可随时回退：
> `ALTER USER 'sxdevops'@'%' IDENTIFIED WITH mysql_native_password BY '<MYSQL_PASSWORD>';`

### 9.3 管理员账号缺失 / 口令重置（登录提示「用户名或密码错误」）

旧版 compose 未把 `SXDEVOPS_ADMIN_PASSWORD` 注入容器：生产模式（DEBUG=0）下平台不会自动建号，
.env 口令也不生效，登录会统一提示「用户名或密码错误」（实为账号不存在）。新版 compose 已接线该
变量（缺失则启动报错），每次启动由 `ensure_admin` 自动建号/加固，正常部署无需本节。

旧环境升级、或忘记/丢失管理员口令时，按以下步骤处理（命令幂等，可重复执行）：

```bash
# 1. 确认 admin 账号是否存在（EXISTS=存在 / MISSING=缺失）
docker compose -f docker-compose.arm64.yml exec sxdevops python manage.py shell -c \
  "from django.contrib.auth import get_user_model; u=get_user_model().objects.filter(username='admin').first(); print('EXISTS' if u else 'MISSING')"

# 2. 建号或重置为 .env 中的口令（MISSING/EXISTS 均适用，口令来自 SXDEVOPS_ADMIN_PASSWORD）
ADMIN_PW=$(grep '^SXDEVOPS_ADMIN_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
docker compose -f docker-compose.arm64.yml exec sxdevops python manage.py shell -c \
  "from django.contrib.auth import get_user_model; u, created = get_user_model().objects.get_or_create(username='admin', defaults={'email': 'admin@example.com'}); u.is_superuser = True; u.is_staff = True; u.set_password('$ADMIN_PW'); u.save(); print('created' if created else 'reset', 'admin')"

# 3. 浏览器以 admin / 上述口令登录（口令查询：grep '^SXDEVOPS_ADMIN_PASSWORD=' .env）
```

> 说明：`Admin@123456` 是开发模式（DEBUG=1）的兜底口令，生产部署一律使用 .env 中的随机口令。
> 升级新版 compose 后（`docker compose ... up -d --force-recreate`），`ensure_admin` 会在每次启动
> 时自动执行本节第 2 步的等效逻辑，后续无需再手动干预。

---

## 十、部署自检表

- [ ] `uname -m` 输出 `aarch64`
- [ ] Docker ≥ 20.10 且 `docker compose version` 为 v2
- [ ] `.env` 已按模板生成，SECRET_KEY / MYSQL / SXDEVOPS_ADMIN_PASSWORD 口令均已随机化（无 change-me 残留）
- [ ] 三个镜像 `docker inspect ... .Architecture` 均为 `arm64`
- [ ] `docker compose ps` 三容器 Up（healthy）
- [ ] 8000 端口防火墙放行
- [ ] 登录页可访问，admin 以 .env 口令登录成功
- [ ] 生产环境无演示数据（告警/主机/事件墙为空；工具市场模板存在）
- [ ] 重启后数据持久
