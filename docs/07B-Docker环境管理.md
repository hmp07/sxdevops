# SxDevOps Docker 环境管理

## 一、概述

SxDevOps 通过 Docker Engine API 接入 Docker 宿主机，在平台内实现容器查看、启停、日志和终端操作。

**前置条件：**
- Docker Engine 20.10+
- Docker API 可网络访问（默认 Unix Socket → 需配置 TCP 暴露）
- 需要 `ops.docker.view` / `ops.docker.manage` 权限

## 二、平台端配置

### 2.1 进入页面

侧边栏：**容器管理 → Docker 环境**

### 2.2 添加 Docker 主机

点击"新增 Docker 主机"，填写配置：

| 字段 | 说明 |
|------|------|
| 主机名称 | 自定义名称 |
| Docker API 地址 | `tcp://host:2375` 或 `unix:///var/run/docker.sock` |
| TLS 验证 | 是否验证 TLS |
| CA 证书 / 客户端证书 / 客户端密钥 | TLS 证书文件（如启用 TLS） |

## 三、Docker 端配置

### 3.1 暴露 Docker API（TCP）

**systemd 方式（推荐）：**

```bash
# 创建 override 配置
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/override.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2375
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

### 3.2 启用 TLS（生产必需）

```bash
# 生成自签证书
openssl req -newkey rsa:4096 -nodes -keyout server-key.pem -x509 -days 365 -out server-cert.pem

# Docker daemon 配置
dockerd --tlsverify --tlscacert=ca.pem --tlscert=server-cert.pem --tlskey=server-key.pem \
  -H=0.0.0.0:2376
```

### 3.3 安全注意

- **不要将 Docker API 暴露在公网！** 仅允许平台服务器 IP 访问
- 使用防火墙限制 2375/2376 端口：
  ```bash
  sudo iptables -A INPUT -p tcp --dport 2375 -s <平台IP> -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport 2375 -j DROP
  ```

## 四、平台功能

| 功能 | 说明 |
|------|------|
| 容器列表 | 所有容器及状态（运行/停止） |
| 容器详情 | Inspect 信息、端口映射、挂载卷、环境变量 |
| 启停操作 | 启动、停止、重启、删除容器 |
| 日志查看 | 实时日志流 |
| Web 终端 | 进入容器执行命令（exec） |
| 镜像列表 | 主机上的 Docker 镜像 |

## 五、验证

1. 添加 Docker 主机 → 确认状态为"已连接"
2. 查看容器列表是否与 `docker ps -a` 一致
3. 点击某个容器 → 查看日志 → 确认日志正常显示
4. 点击 Web 终端 → 执行 `hostname` → 确认返回容器主机名
