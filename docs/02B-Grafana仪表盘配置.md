# SxDevOps Grafana 仪表盘配置

## 一、概述

SxDevOps 可以承接已有的 Grafana 仪表盘，在平台内以 iframe 嵌入显示，实现运维统一入口。

**前置条件：**
- Grafana 已部署运行（版本 **9.1+**，推荐 10.x LTS / 11.x）
- 需要 `ops.grafana.view`（查看）/ `ops.grafana.manage`（配置）权限（`ops-admin` 角色已内置）

## 二、平台端配置

### 2.1 进入页面

侧边栏：**可观测性 → 可视化 → 仪表盘**

### 2.2 配置 Grafana 连接（设置对话框）

点击页面右上角 **设置** 按钮：

| 字段 | 说明 | 示例 |
|------|------|------|
| Grafana URL | Grafana 服务地址 | `https://grafana.example.com` |
| API Token | Grafana Service Account Token（可选，服务端 API 调用用） | `glsa_...` |
| 默认看板路径 | 未指定看板时的默认嵌入路径（可选） | `/d/apm-overview` |
| Org ID | Grafana 组织 ID | `1` |
| TLS 验证 | 是否校验证书（自签名内网可关闭） | 开启（推荐） |
| 请求超时 | 平台调用 Grafana API 的超时（秒） | `10` |

保存前可点击 **测试连接**：平台会返回 Grafana 版本与组织信息，并通过匿名请求 `/api/org` 探测 iframe 嵌入就绪状态（匿名访问未开启时提示"匿名访问未开启"，请按 [Grafana嵌入配置指南](Grafana嵌入配置指南.md) 配置 Grafana 侧开关；Grafana 12 的 `/login` 恒 200，已不再作为判定依据）。测试使用弹窗中当前的 **TLS 验证** 与 **请求超时** 值，无需先保存即可生效。

> Token 留空保存表示保留已配置值；Token 与 JWT Secret 均加密存储且永不回传前端。
> URL 留空保存同样保留已配置值，不会清空已有连接信息。

### 2.3 添加仪表盘（两种方式）

**方式一：从 Grafana 同步（推荐）**

点击 **从 Grafana 同步** → 获取看板列表 → 勾选要导入的看板 → 选择目标目录 → 导入。
平台通过 Grafana `api/search` 自动发现目录与看板（需 Service Account Token 具备 Viewer 权限），按 UID 去重，不会覆盖手动配置的条目。

> **列表不全提示（两个常见原因）**：
> 1. Service Account 创建时选择了 **No basic role**（无基础角色）——此时只能看到被逐个共享/授权的看板。处理：Service accounts 中点开该账号，Role 改为 **Viewer**。
> 2. Grafana 10+ 新建的文件夹默认权限不含 Viewer——看板在文件夹中时同步列表缺失。处理：Dashboards → 目标文件夹 → Settings → Permissions 为 Service Account 显式添加 **Viewer** 权限。

**方式二：手动添加**

点击目录菜单的 **新增看板**，填写：

| 字段 | 说明 |
|------|------|
| 看板名称 | 展示标题 |
| 目录 | 所属目录（支持 `基础设施/节点` 层级） |
| 标签 | 用于列表筛选 |
| 完整 Grafana URL | 可直接打开的看板地址，如 `https://grafana.example.com/d/apm-overview` |
| 展示参数 | 自动追加 `kiosk=true&theme=light`（隐藏 Grafana 菜单 + 浅色主题） |
| 嵌入面板 | 可选：选择单个面板做 `/d-solo` 面板级嵌入，留空嵌入整个看板 |

平台预置 5 个常用仪表盘模板（未配置外部 Grafana 时展示）：

| 预置仪表盘 | 用途 |
|-----------|------|
| APM 全链路总览 | 服务吞吐、慢调用、错误率 |
| 基础设施总览 | 节点 CPU、内存、磁盘、Pod |
| 日志钻取看板 | 错误时段与关键日志回放 |
| 入口流量与 SLO | 入口 QPS、延迟分位、可用性 |
| K8s 工作负载资源 | 按 namespace/workload 维度 |

## 三、使用

- 点击看板 **打开看板** 进入沉浸式嵌入视图：工具栏支持 **自动刷新**（15s/30s/1m/5m，Grafana 原生 `refresh` 参数，不重载 iframe）、手动重载、查链路/查日志跳转（需配置数据源关联）、全屏打开。
- 已配置 JWT Secret 时，平台打开看板自动签发 60 秒短时 Token，通过 `?auth_token=` 完成 Grafana 自动登录；未配置时回退匿名 Viewer 模式（详见 [Grafana嵌入配置指南](Grafana嵌入配置指南.md)）。

## 四、验证

1. 设置对话框填写 Grafana URL → 测试连接 → 显示版本与组织信息
2. 从 Grafana 同步导入看板 → 点击打开看板 → 确认 iframe 正常渲染（无登录页跳转）
3. 选择自动刷新 → 确认面板数据按间隔更新

### 4.1 故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| 测试连接报证书错误 | Grafana 使用自签名证书 | 设置中关闭 **TLS 验证**（仅内网），或配置受信证书 |
| 测试连接报重定向错误 | 前置反代强制 HTTP→HTTPS 且证书未受信 | 直接使用 Grafana 服务地址（如 `http://192.168.x.x:3000`），或关闭 TLS 验证后使用 HTTPS 地址 |
| 测试连接报 401/403 | Token 无效或 Service Account 权限不足 | 重新生成 Token，确认角色为 Viewer 且对目标看板有读权限 |
| 同步列表不全 | 看板所在文件夹未授权给 Service Account | 为文件夹添加 Service Account 的 Viewer 权限（见 2.3 提示） |
| 导入后看板打开 404 | 看板 URL 路径不正确 | 重新同步导入（平台已按 Grafana 返回的标准路径 `/d/{uid}/{slug}` 生成地址） |
| 打开看板停留在 Grafana 登录页 | ① 匿名访问未开启 ② 匿名组织名配置错误（容器环境变量列表写法 `KEY="value"` 引号陷阱，Grafana 报 `organization not found`）③ 平台 URL 为 HTTP 而 Grafana 配置了 `cookie_secure=true` | ① 启用 `[auth.anonymous]` ② compose 改映射写法或去掉引号并重建容器 ③ 平台改 https 地址并关闭 TLS 验证，或将 Grafana `cookie_secure` 设为 false；详见 [Grafana嵌入配置指南](Grafana嵌入配置指南.md) 常见问题表 |
