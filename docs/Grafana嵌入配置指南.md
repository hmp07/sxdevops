# Grafana 嵌入配置指南

SxDevOps 平台以 iframe 方式嵌入 Grafana 看板。本文给出外部 Grafana 的完整配置要求，包括版本、grafana.ini 配置、Service Account Token 创建、嵌入 URL 格式与安全加固。

---

## 一、版本要求

| 能力 | 最低版本 | 说明 |
|------|---------|------|
| iframe 嵌入 | 6.x | `allow_embedding` 开关 |
| Service Account + Token | **9.1** | 替代旧 API Key，平台服务端 API 调用认证 |
| JWT auth_token 自动登录 | **9.1** | `[auth.jwt] url_login` 免密嵌入 |
| 看板原生自动刷新参数 | 6.4 | `?refresh=30s` 面板级刷新 |

**推荐：Grafana 10.x LTS 或 11.x**（`api/search`、`api/dashboards/uid/{uid}` 均稳定支持）。

---

## 二、grafana.ini 必需配置

```ini
[security]
# 必须显式开启，默认 false 会阻止 iframe 嵌入
allow_embedding = true

[auth.anonymous]
# JWT auth_token 未配置时的兜底方案（只读 Viewer）
enabled = true
org_name = Main Org.
org_role = Viewer
```

**JWT auth_token 自动登录（推荐，替代匿名访问）**：

```ini
[auth.jwt]
enabled = true
# 允许通过 ?auth_token=<JWT> 查询参数自动登录（iframe 嵌入的关键）
url_login = true
# 平台签发的 JWT 放在自定义头中
header_name = X-JWT-Assertion
# 与平台 GrafanaSetting.jwt_secret 相同的 HS256 secret 文件
key_file = /etc/grafana/jwt-secret
username_claim = sub
email_claim = email
auto_sign_up = true
# 可选：按 JWT claim 映射角色；不配置则新用户默认 Viewer
# role_attribute_path = role
```

> `key_file` 同时支持 HMAC secret（HS256）与 RSA/ECDSA 公钥（PEM）。

Docker 环境变量等价写法（见 [docker-compose.monitoring.yml](../docker-compose.monitoring.yml)）：

```yaml
environment:
  GF_SECURITY_ALLOW_EMBEDDING: "true"
  GF_AUTH_ANONYMOUS_ENABLED: "true"
  GF_AUTH_ANONYMOUS_ORG_NAME: "Main Org."
  GF_AUTH_ANONYMOUS_ORG_ROLE: "Viewer"
  GF_AUTH_JWT_ENABLED: "true"
  GF_AUTH_JWT_URL_LOGIN: "true"
  GF_AUTH_JWT_HEADER_NAME: "X-JWT-Assertion"
  GF_AUTH_JWT_USERNAME_CLAIM: "sub"
  GF_AUTH_JWT_EMAIL_CLAIM: "email"
  GF_AUTH_JWT_AUTO_SIGN_UP: "true"
```

修改配置后需重启 Grafana 生效。

---

## 三、Service Account Token（平台服务端 API 用）

平台的服务端调用（连接测试 / 看板发现 / PromQL 代理 / 面板分析）通过 Grafana HTTP API，需 Service Account Token 认证：

1. Grafana UI → **Administration → Users and access → Service accounts** → **Add service account**
2. 角色设为 **Viewer**（`api/search` 只返回该账号有权限的看板，最小权限原则）
3. 添加 Token（`glsa_...`），复制后填入平台「仪表盘 → 设置 → API Token」

> **必须选择基础角色 Viewer，不要选 "No basic role"**：Grafana 11+ 支持创建无基础角色的账号，此时账号只能看到被**逐个共享/显式授权**的看板，`api/search` 返回列表会严重不全（即使看板都在 General 目录）。已创建的无角色 SA 可在 Service accounts 列表中点开该账号，把 Role 改为 Viewer 即可。

**文件夹权限（同步列表不全的另一个常见原因）**：Grafana 10+ 新建的文件夹默认权限只含 Admin/Editor，**不含 Viewer**。看板放入文件夹后，Service Account 将无法通过 `api/search` 看到它们。处理：Dashboards → 目标文件夹 → **Settings → Permissions** → Add permission → 选择该 Service Account → 角色 **Viewer**（或把看板放在 General 目录）。

请求认证方式（平台自动附加）：

```http
Authorization: Bearer <SERVICE_ACCOUNT_TOKEN>
```

---

## 四、嵌入 URL 格式

| 场景 | URL 格式 |
|------|---------|
| 整个看板 | `/d/{uid}/{slug}?orgId=1&kiosk&theme=light` |
| 单个面板 | `/d-solo/{uid}/{slug}?panelId={panelId}&kiosk&theme=light` |
| 自动刷新 | 追加 `&refresh=30s`（15s / 30s / 1m / 5m） |
| JWT 免密 | 追加 `&auth_token={60s短时JWT}`（平台自动注入） |

- `kiosk`：隐藏 Grafana 顶部导航，适合嵌入
- `theme=light`：浅色主题与平台风格一致
- `orgId`：与平台设置中的 Org ID 一致

---

## 五、安全加固

1. **匿名访问风险**：`[auth.anonymous]` 开启后任何人可只读查看看板。生产环境建议：
   - 仅启用 JWT auth_token 方案并关闭匿名（`enabled = false`）
   - 或通过反向代理做 IP 白名单限制
2. **CSP frame-ancestors**：平台与 Grafana 同源反代或同域部署时无跨域问题；跨域嵌入需确保 Grafana 未通过 `X-Frame-Options`/`Content-Security-Policy` 阻止（`allow_embedding = true` 已处理）
3. **Service Account Token 最小化**：仅 Viewer 角色、单独账号、定期轮换；Token 加密存储于平台数据库
4. **JWT secret 轮换**：平台 GrafanaSetting.jwt_secret 与 Grafana `key_file` 需同步轮换，两端不一致会拒绝登录
5. **TLS**：生产环境 Grafana 必须 HTTPS；平台默认校验 TLS 证书，自签名内网可显式关闭（不推荐）
6. **反向代理**：若 nginx 等反代将 HTTP 强制 301/302 跳转到 HTTPS 且证书自签，平台测试连接会报证书或重定向错误。建议平台直接配置 Grafana 服务地址（如 `http://<host>:3000`）并在设置中关闭 TLS 验证，或为反代域名配置受信证书

---

## 六、同源反向代理（可选）

当平台以 HTTPS 部署且需要同源嵌入时，平台前端会把 Grafana 地址改写为同源 `/grafana/` 路径。可参考 nginx 配置：

```nginx
location /grafana/ {
    proxy_pass http://grafana:3000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## 七、常见问题

| 现象 | 处理 |
|------|------|
| iframe 一片空白 | ① `allow_embedding = true` 是否生效（改后重启 Grafana）② 浏览器控制台 CSP 报错 |
| iframe 跳转登录页 | 匿名访问未开启或 JWT secret 不一致；用平台「测试连接」的嵌入就绪探测确认 |
| 从 Grafana 同步为空列表 | Service Account Token 角色权限不足（需 Viewer）或所属 Org 不对 |
| 同步列表看板不全 | 看板所在文件夹未授权给 Service Account（Grafana 10+ 新文件夹默认不含 Viewer）；在文件夹 Permissions 中为 Service Account 添加 Viewer |
| 同步列表看板不全（仅部分可见） | **General 目录权限被清空**：目录内无显式权限的看板继承该限制、仅管理员可见，而带显式看板级授权的看板仍可见，造成"部分可见"现象；在 General 目录 Settings → Permissions 中加回 **Viewer** 角色 |
| 测试连接报证书/重定向错误 | 反代强制 HTTP→HTTPS 且证书自签；平台配置直连 Grafana 地址并关闭 TLS 验证（见五.6） |
| 面板列表获取失败 | Token 无该看板读权限，或看板 UID 拼写错误 |
| JWT 登录 401 | 两端 secret 不一致 / JWT 已过期（平台签发 60 秒短时 Token，打开看板时实时签发） |
