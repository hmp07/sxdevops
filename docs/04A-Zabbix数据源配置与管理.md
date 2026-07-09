# SxDevOps Zabbix 数据源配置与管理

## 一、概述

Zabbix 数据源是 SxDevOps 对接 Zabbix Server 的桥梁。配置后即可：
- 在 **Zabbix 监控** 页面实时查看主机、触发器、当前问题
- 通过 **告警中心** 接收 Zabbix 告警（Webhook 或轮询）
- 让 **AIOps 智能助手** 查询 Zabbix 数据进行排障分析
- 将 Zabbix 主机与 CMDB 配置项建立 **设备关联映射**

**前置条件：**
- Zabbix Server 5.x / 6.x / 7.x（支持 JSON-RPC API）
- 平台能访问 Zabbix Server 的 `api_jsonrpc.php` 端点
- 需要 `ops.zabbix.datasource.manage` 权限

## 二、平台端配置

### 2.1 进入配置页面

侧边栏：**可观测性 → 数据源 → Zabbix 数据源** Tab

### 2.2 新增数据源

点击"新增数据源"，填写以下配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| **数据源名称** | 自定义名称，用于识别 | `公司生产 Zabbix` |
| **API 地址** | Zabbix JSON-RPC 端点 | `https://zabbix.example.com/api_jsonrpc.php` |
| **认证方式** | 选择认证方式 | `API Token (推荐)` 或 `用户名 / 密码` |
| **API Token** | 认证方式为 Token 时填写 | Zabbix 7.x: 用户 → API Tokens 生成 |
| **用户名** | 认证方式为用户密码时填写 | `Admin` |
| **密码** | 认证方式为用户密码时填写 | Zabbix 登录密码 |
| **启用 / 停用** | 控制数据源是否可用 | 启用 |
| **设为默认** | 设为默认数据源（下拉框自动选中） | 根据需要 |
| **TLS 验证** | 是否验证 HTTPS 证书 | 生产环境建议开启 |
| **超时 (秒)** | API 调用超时，范围 5-60 | `15` |

### 2.3 测试连接

保存后，在数据源列表点击 **"测试连接"**，确认返回 `Zabbix API 连接正常，版本：7.x`。

### 2.4 管理数据源

- **编辑**：修改配置信息，密码/Token 字段留空则保持不变
- **删除**：删除数据源，关联的设备映射将失效
- **设为默认**：在编辑时切换

## 三、Zabbix 端要求

### 3.1 网络要求

Zabbix Server 的 `api_jsonrpc.php` 端点必须对平台服务器可达（通常不需要额外配置，因为这是 Zabbix 前端同一端口）。

### 3.2 API 认证

**方式一：API Token（推荐，Zabbix 5.4+）**
1. Zabbix 管理界面 → Users → 选择一个用户 → **API tokens** Tab
2. 点击 **Create API token**，填写名称，保存
3. 复制生成的 Token（仅显示一次）

**方式二：用户名/密码**
使用 Zabbix 登录用户名和密码。平台通过 `user.login` 获取临时 session token，1 小时缓存。

### 3.3 权限要求

关联的 Zabbix 用户至少需要以下权限：
- 对需要监控的主机组有**读**权限
- 用户类型：Zabbix Super Admin / Admin / User

## 四、验证配置

### 4.1 查看主机列表

数据源保存后，切换到 **Zabbix 监控** 页面（侧边栏：可观测性 → Zabbix 监控）：

- 顶部下拉框选择刚创建的数据源
- 主机列表 Tab 应显示 Zabbix 中的主机
- 统计卡片显示：主机总数、可用主机数
- 触发器 Tab 和当前问题 Tab 显示对应数据

### 4.2 查看设备映射

主机列表的 **"关联 CI"** 列显示该主机是否已与 CMDB 中的配置项关联。系统会自动通过 IP 匹配尝试关联。

### 4.3 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 连接测试失败 | API 地址错误或网络不通 | 从平台服务器 `curl` 测试 API 地址 |
| 主机列表为空 | Zabbix 用户权限不足 | 检查 Zabbix 用户的主机组权限 |
| 认证失败 | Token 过期或密码错误 | 重新生成 Token，确认密码正确 |
| 超时 | 网络延迟或主机过多 | 增大超时值 |

## 五、后续配置

数据源配置完成后，建议继续配置：
- [Zabbix 监控页面使用](04B-Zabbix监控页面使用.md) — 日常监控操作
- [Zabbix Webhook 告警接入](03G-Zabbix-Webhook接入.md) — 告警实时推送
- [Zabbix 告警轮询配置](04C-Zabbix告警轮询配置.md) — 定时拉取告警
