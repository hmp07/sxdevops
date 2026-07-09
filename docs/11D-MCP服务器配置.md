# SxDevOps MCP 服务器配置

## 一、概述

MCP（Model Context Protocol）是 AI 智能体与外部工具/服务的标准协议。SxDevOps 支持注册外部 MCP 服务器，使 AI 助手能够调用第三方工具（如数据库查询、API 调用等）。平台也内置了多个 MCP 工具（如 Zabbix 查询、iTop CMDB 查询等）。

**前置条件：**
- MCP 服务器已部署并运行（或使用平台内置工具）
- 需要 `aiops.config.manage` 权限

## 二、平台端配置

### 2.1 进入配置页面

侧边栏：**AIOps → 智能体配置 → MCP 服务器** Tab

### 2.2 平台内置 MCP 工具

平台已内置以下 MCP 工具（无需额外配置）：

| 工具名称 | 功能 | 权限要求 |
|---------|------|---------|
| `sxdevops.query_zabbix_hosts` | 查询 Zabbix 主机列表 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_problems` | 查询 Zabbix 活跃问题 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_items` | 查询主机监控项 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_history` | 查询监控项历史数据 | `ops.zabbix.view` |
| `sxdevops.query_alerts` | 查询平台告警中心数据 | `ops.alert.view` |
| `sxdevops.query_logs` | 查询日志数据 | `ops.log.query` |
| `sxdevops.query_knowledge_graph` | 查询知识图谱 | `aiops.knowledge.view` |
| `sxdevops.query_recent_changes` | 查询近期变更记录 | `cmdb.ci.view` |
| `mcp__iTop_CMDB_MCP__*` | iTop CMDB 查询工具 | `cmdb.itop.view` |

### 2.3 新增外部 MCP 服务器

点击"新增 MCP 服务器"，填写配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| 服务器名称 | 自定义名称 | `生产 MySQL 查询` |
| 传输协议 | 通信方式 | `stdio` / `HTTP` / `WebSocket` |
| 命令 / URL | 服务器连接地址 | `python mysql-mcp-server.py` 或 `https://mcp.example.com` |
| 环境变量 | 传递给服务器的环境变量 | `DB_HOST=mysql.example.com` |
| 启用 / 停用 | 控制服务器是否可用 | 启用 |

### 2.4 工具白名单

可为每个 MCP 服务器配置工具白名单——只允许 AI 调用指定的工具子集：

- `enabled_tool_names`：指定可用的工具名称列表
- 不配置则允许所有工具

## 三、MCP 服务器开发

### 3.1 内置 MCP 示例：iTop MCP Server

项目 `tools/itop-mcp-server/` 目录包含一个 Go 语言开发的 MCP 服务器示例，实现 iTop CMDB 的 MCP 工具接口。

```
tools/itop-mcp-server/
├── main.go          # MCP 服务入口，注册工具
├── itop_client.go   # iTop REST API 客户端
└── go.mod
```

### 3.2 工具调用权限模型

AI 智能体实际可使用的工具由四层交集决定：

```
可用工具 = Skill工具依赖 ∩ MCP可用性 ∩ 用户RBAC权限 ∩ Action安全策略
```

这意味着即使 MCP 服务器注册了一个工具，如果用户没有对应权限或当前 Action 不允许，AI 也无法调用。

### 3.3 MCP 工具描述规范

注册的 MCP 工具应提供清晰的描述，帮助 AI 正确选择和使用。工具描述包含：
- 功能说明
- 参数定义（名称、类型、是否必填）
- 返回值结构
- 使用场景提示

## 四、验证

1. 注册新的 MCP 服务器并启用
2. 打开 AI 智能助手
3. 输入相关查询 → 确认 AI 能发现并调用新工具
4. 在智能体审计页面 → 工具调用记录 → 查看新工具的调用日志

## 五、安全建议

- MCP 服务器运行在受控环境中（Docker 容器或隔离进程）
- 敏感凭证（数据库密码、API Key）通过环境变量注入，不写在配置中
- 工具白名单限制 AI 只能调用预授权的方法
- 所有工具调用记录在审计日志中
