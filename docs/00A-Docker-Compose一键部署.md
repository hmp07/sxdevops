# SxDevOps Docker Compose 一键部署

## 一、概述

SxDevOps 提供完整的 Docker Compose 编排，包含应用、MySQL 8、Redis 7 三个容器。适合快速体验、演示环境和小规模生产部署。

**前置条件：**
- Docker Engine 20.10+ 和 Docker Compose v2
- 服务器 2C4G 以上，10GB 可用磁盘
- 开放端口 8000（HTTP）

## 二、快速启动

```bash
# 克隆或拷贝项目到服务器
git clone <项目地址> sxdevops
cd sxdevops

# 一键构建并启动（首次约 3-5 分钟）
docker compose up -d --build
```

启动后访问：**`http://<服务器IP>:8000`**

## 三、首次启动流程

容器启动时，`entrypoint.sh` 自动执行以下初始化操作（由环境变量控制）：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SXDEVOPS_WAIT_FOR_DB` | `1` | 等待 MySQL 就绪后再启动 |
| `SXDEVOPS_MIGRATE` | `1` | 自动执行数据库迁移 |
| `SXDEVOPS_SEED_DATA` | `1` | 创建演示数据（用户/主机/任务等） |
| `SXDEVOPS_SEED_TEMPLATES` | `1` | 创建 AI 智能体模板 |

如需纯净安装（无演示数据），在 `docker-compose.yml` 中设置 `SXDEVOPS_SEED_DATA=0` 和 `SXDEVOPS_SEED_TEMPLATES=0`。

## 四、默认账号

初始化数据后，以下账号可用，默认密码均为 `Admin@123456`：

| 账号 | 角色 | 权限范围 |
|------|------|---------|
| `admin` | 平台管理员 | 全部权限 |
| `ops_demo` | 运维工程师 | 运维操作权限 |
| `dev_demo` | 开发工程师 | 开发相关权限 |
| `audit_demo` | 审计员 | 只读审计权限 |
| `viewer_demo` | 观察者 | 最小只读权限 |

> ⚠️ **生产环境务必修改默认密码！**

## 五、容器架构

```
┌──────────────────────────────────────┐
│         sxdevops-app (自构建)          │
│  Daphne ASGI :8000                    │
│  ┌────────────┐  ┌────────────────┐   │
│  │ Django      │  │ Vue 3 前端      │   │
│  │ REST API    │  │ (静态文件)      │   │
│  └────────────┘  └────────────────┘   │
└──────────┬───────────────┬───────────┘
           │               │
    ┌──────▼──────┐  ┌─────▼──────┐
    │  MySQL 8.0  │  │  Redis 7   │
    │  :3306      │  │  :6379     │
    │  utf8mb4    │  │  AOF 持久化 │
    └─────────────┘  └────────────┘
```

## 六、常用运维命令

```bash
# 查看日志
docker compose logs -f sxdevops

# 重启应用
docker compose restart sxdevops

# 停止所有服务
docker compose down

# 停止并删除数据卷（清空数据库和 Redis）
docker compose down -v

# 重新构建镜像（代码更新后）
docker compose up -d --build

# 仅启动/停止数据库
docker compose up -d mysql redis
docker compose stop mysql redis
```

## 七、环境变量参考

所有可配置的环境变量（在 `docker-compose.yml` 的 `environment` 段）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_ENGINE` | `mysql` | 数据库类型 |
| `MYSQL_HOST` | `mysql` | MySQL 主机名（容器名） |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_DATABASE` | `sxdevops` | 数据库名 |
| `MYSQL_USER` | `sxdevops` | 数据库用户名 |
| `MYSQL_PASSWORD` | `sxdevops_password` | 数据库密码 |
| `REDIS_URL` | `redis://redis:6379/0` | 缓存 Redis |
| `CHANNEL_REDIS_URL` | `redis://redis:6379/1` | WebSocket 通道 Redis |
| `SECRET_KEY` | `sxdevops-change-me-in-production` | Django 密钥 |
| `DEBUG` | `0` | 调试模式 |
| `CORS_ALLOW_ALL_ORIGINS` | `1` | 跨域配置 |
| `SXDEVOPS_WAIT_FOR_DB` | `1` | 启动前等待 DB |
| `SXDEVOPS_MIGRATE` | `1` | 自动迁移 |
| `SXDEVOPS_SEED_DATA` | `1` | 种子数据 |
| `SXDEVOPS_SEED_TEMPLATES` | `1` | 种子模板 |

## 八、数据持久化

Docker Compose 创建两个命名卷：

| 卷名 | 挂载路径 | 内容 |
|------|---------|------|
| `mysql_data` | `/var/lib/mysql` | MySQL 数据文件 |
| `redis_data` | `/data` | Redis AOF 文件 |

使用 `docker compose down` 不会删除卷，数据得以保留。使用 `-v` 参数会彻底清空数据。

## 九、生产部署建议

- 修改 `SECRET_KEY` 为随机字符串（`openssl rand -hex 32`）
- 设置 `DEBUG=0`
- 设置 `CORS_ALLOW_ALL_ORIGINS=0`
- 修改数据库和 Redis 密码
- 修改演示账号密码
- 配置反向代理（Nginx）和 HTTPS
- 定期备份 MySQL 数据卷
