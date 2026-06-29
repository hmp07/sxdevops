# SxDevOps Zabbix + iTop 集成实施计划（含 AIOps 整合）

## Context

SxDevOps 现有架构主要面向云原生环境。现需转向传统运维场景，接入两个核心系统：

1. **Zabbix**：传统监控系统 → 基础设施监控数据
2. **iTop**：IT 运维管理系统 → CMDB、设备关联关系、工单数据

**关键要求**：新接入的数据不仅要在前端页面展示，更必须融入 AIOps 模块——Agent 可调用为 MCP 工具、Skill 可引用为 SOP 步骤、知识图谱可吸收为关联节点。

---

## AIOps 现有架构速览（关键对接点）

### MCP 工具注册机制
- 工具定义在 `services.py` 的 `PLATFORM_MCP_TOOL_DEFINITIONS` 常量中（当前 7 个工具）
- 格式：`{name, title, description, permission, handler, input_schema}`
- 调度通过 `_invoke_platform_mcp_handler()` 的 if/else 链分发到具体 handler 函数
- RBAC：工具级 `permission` + API 入口 `aiops.mcp.invoke` 双重校验
- Feature gate：`tool_feature_enabled()` 可动态开关工具

### Action 路由注册
- 定义在 `BUILTIN_ACTION_REGISTRY`（当前 7 个 Action）
- 格式：`{code, risk_level, agent_mode, allowed_tools[], skills[], preflight_required, required_context[]}`
- Agent 模式：`direct` / `react` / `plan_react`
- 路由逻辑：关键词匹配 → Action 选择 → 可用工具和 Skill 过滤

### Skill/SOP 模板
- 模型 `AIOpsSkill`：name, slug, category, builtin_tools, recommended_tools, risk_level, output_contract, content
- 内置 13 个 Skill（`BUILTIN_SKILLS` 常量）
- Skill 通过 `applicable_actions` 关联 Action，通过 `builtin_tools` 声明依赖工具

### 知识图谱
- `build_knowledge_graph()` 汇聚 Alert/Log/Trace/Event/Infrastructure/CMDB/Deployment 等多源数据
- 当前 14 种节点关系类型
- 节点 kind：environment, system, service, capability, infrastructure, datasource, event_source, runtime_component
- `AIOpsKnowledgeEnvironment` 模型关联数据源（k8s_cluster_ids, docker_host_ids, log_datasource_ids 等）

---

## Phase 0：前置修复（必须最先完成）

### P0.1 修复 CMDB 路由注册
- **修改**：`backend/sxdevops/urls.py` 增加 `path('api/cmdb/', include('cmdb.urls'))`
- **注意**：cmdb 的 urls.py 中路由不含 `cmdb/` 前缀，而前端 axios baseURL 为 `/api`，API 调用 `/cmdb/ci-types/` → 实际请求 `/api/cmdb/ci-types/`，因此前缀必须是 `api/cmdb/`
- **影响**：所有后续 CMDB/iTop 工作的前提

### P0.2 添加 CMDB 侧边栏菜单
- **修改**：`frontend/src/layout/AppLayout.vue` — 新增 `cmdb` 菜单组
- **内容**：CMDB 总览 → 配置项 → 资源拓扑 → iTop 对接（后续追加）

---

## Phase 1：Zabbix 集成（含 AIOps 整合）

### 1.1 数据模型 — ZabbixDataSource
新建 `backend/ops/models.py`：
```
ZabbixDataSource: name, api_url, auth_type(token/userpass), auth_token/username/password,
  tls_verify, timeout, is_enabled, is_default, config(JSONField)
```
- 遵循 MetricDataSource/TracingDataSource 模式

### 1.2 Zabbix API Client
新建 `backend/ops/zabbix_client.py`：
- JSON-RPC 封装：`host.get`, `hostgroup.get`, `item.get`, `history.get`, `trend.get`, `trigger.get`, `problem.get`, `event.get`
- 自动 token 过期重登录（检测 `-32602`）
- 线程安全 token 缓存

### 1.3 Zabbix 代理 API
新建 `backend/ops/zabbix_views.py`：
- `ZabbixDataSourceViewSet`：标准 CRUD + `test_connection`
- 代理端点：`hosts/`, `items/`, `history/`, `triggers/`, `problems/`
- 所有端点实时查询代理（非预拉取存储）

### 1.4 ⭐ AIOps MCP 工具（Zabbix）
在 `backend/aiops/services.py` 的 `PLATFORM_MCP_TOOL_DEFINITIONS` 中新增：

| 工具名 | 功能 | 权限 |
|--------|------|------|
| `sxdevops.query_zabbix_hosts` | 查询 Zabbix 主机列表和状态 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_problems` | 查询 Zabbix 当前问题/告警 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_items` | 查询主机监控项及最新值 | `ops.zabbix.view` |
| `sxdevops.query_zabbix_history` | 查询监控项历史数据（图表用） | `ops.zabbix.view` |

每个工具需实现对应 handler 函数（如 `query_zabbix_hosts`），在 `_invoke_platform_mcp_handler()` 中注册。

### 1.5 ⭐ AIOps Action（Zabbix）
在 `BUILTIN_ACTION_REGISTRY` 中新增：

```python
{
    'code': 'zabbix.problem_analysis',
    'display_name': 'Zabbix 告警分析',
    'category': '故障排障',
    'risk_level': 'read_only',
    'agent_mode': 'react',
    'allowed_tools': [
        'query_zabbix_problems', 'query_zabbix_hosts', 'query_zabbix_items',
        'query_zabbix_history', 'query_alerts', 'query_logs',
        'query_knowledge_graph', 'query_recent_changes',
    ],
    'skills': ['sx-zabbix-troubleshooting', 'answer-formatter'],
    'required_context': ['environment'],
}
```

### 1.6 ⭐ AIOps Skill（Zabbix）
在 `BUILTIN_SKILLS` 中新增：

```python
{
    'slug': 'sx-zabbix-troubleshooting',
    'name': 'Zabbix 告警排障 SOP',
    'category': '告警排障',
    'risk_level': 'read_only',
    'builtin_tools': ['query_zabbix_problems', 'query_zabbix_hosts', 'query_zabbix_items', 'query_zabbix_history'],
    'output_contract': {
        'sections': ['告警概述', '受影响主机', '监控项异常', '历史趋势', '根因推断', '建议动作'],
    },
    # content 为 SOP 正文
}
```

### 1.7 ⭐ 知识图谱扩展（Zabbix）
在 `backend/aiops/knowledge_graph.py` 的 `build_knowledge_graph()` 中新增节点类型：

| 新 kind | 来源 | 关联关系 |
|---------|------|---------|
| `zabbix_datasource` | ZabbixDataSource | `capability_datasource` ← capability "zabbix_monitoring" |
| `zabbix_host` | Zabbix host.get | `zabbix_monitored` → infrastructure/existing Host |
| `zabbix_problem` | Zabbix problem.get | `zabbix_triggered` → zabbix_host |

新增能力类型：`zabbix_monitoring` 加入 capability 列表。
新增关系类型：`zabbix_monitored`（Zabbix主机 → 基础设施节点）、`zabbix_triggered`（Zabbix告警 → Zabbix主机）。

### 1.8 ⭐ AIOps 知识环境配置扩展
在 `AIOpsKnowledgeEnvironment` 模型中增加字段：
```python
zabbix_datasource_ids = JSONField(default=list)  # 关联的 Zabbix 数据源
```

### 1.9 前端页面 — ZabbixMonitor.vue
- 路由：`/observability/zabbix`
- 数据源选择器 + 主机列表 + 监控项表格 + 触发器列表 + 历史图表
- 用于手动排查，也作为 Agent 工具调用的可视化回显锚点

---

## Phase 2：iTop 集成 — 独立 MCP Server 方案

> **架构决策变更**：原来计划在 Django 内部编写 iTop 客户端（`itop_client.py` + `itop_sync.py` + `itop_views.py`）。
> 现改为：**基于 itop-clinet 的 Go 代码，开发一个独立的 iTop MCP Server**（stdio 类型），
> 作为外部 MCP Server 接入 SxDevOps AIOps 模块。Agent 通过 MCP 协议直接调用 iTop 数据。

### 为什么选择独立 MCP Server

| 维度 | Platform Built-in（原计划） | 独立 MCP Server（新方案） |
|:--|:--|:--|
| 可复用性 | 仅 SxDevOps 可用 | 任何 MCP 客户端都能用 |
| 开发语言 | Python（需重写） | 复用 itop-clinet 已验证的 Go 代码 |
| 部署灵活性 | 绑定在后端 | 独立进程，可本地/远程部署 |
| 测试便利性 | 需启动 Django | 独立测试，stdio 直连验证 |

### 2.1 iTop MCP Server 设计（Go 实现）

**项目结构**（新建 `tools/itop-mcp-server/`）：
```
tools/itop-mcp-server/
  main.go              # MCP Server 入口，JSON-RPC 2.0 协议处理
  itop_client.go        # 从 itop-clinet 复用的 iTop REST API 封装
  go.mod / go.sum
  README.md
  config.example.json   # 示例配置
```

**启动方式**（stdio 模式）：
```bash
itop-mcp-server stdio \
  --url http://itop.example.com/webservices/rest.php \
  --user hmp07 --password Test@123 \
  --version 1.4
```

通过 stdin/stdout 与 SxDevOps 通信，JSON-RPC 2.0 协议。

**实现的 MCP 方法**：

| MCP 方法 | 说明 |
|:--|:--|
| `initialize` | 握手，返回 serverInfo(name=iTop MCP Server, version=1.0.0) |
| `ping` | 健康检查 |
| `tools/list` | 返回所有 iTop 工具的 inputSchema 声明 |
| `tools/call` | 根据 tool name 分发到对应的 iTop API 调用 |

**暴露的 MCP 工具**（只读 + 写入，按风险分级）：

**🟢 查询类工具**（始终启用）：

| 工具名 | iTop API 操作 | 功能 |
|:--|:--|:--|
| `itop_list_operations` | `list_operations` | 列出 iTop 所有可用操作 |
| `itop_check_credentials` | `core/check_credentials` | 验证连接凭据 |
| `itop_get_cis` | `core/get` | 查询 CI 配置项（支持 OQL/ID/条件对象） |
| `itop_get_related` | `core/get_related` | 获取 CI 的关联关系和对象（核心关系 API） |
| `itop_get_tickets` | `core/get` | 查询工单（UserRequest/Incident/NormalChange/Problem） |
| `itop_get_ticket_detail` | `core/get` | 按 ID 查询单个工单详情 |

**🟡 写入类工具**（需 `allow_write: true`，受 SxDevOps Preflight 确认机制保护）：

| 工具名 | iTop API 操作 | 功能 | 风控 |
|:--|:--|:--|:--|
| `itop_update_ci` | `core/update` | 更新 CI 属性字段（如 status/description/serialnumber） | 白名单字段校验 + 写前读 diff |
| `itop_create_ci` | `core/create` | 在 iTop 中创建新的 CI | 必填字段校验 + 写入后返回新 ID |
| `itop_create_ticket` | `core/create` | 创建工单 | 必填字段校验 |
| `itop_update_ticket` | `core/update` | 更新工单 | 字段白名单 |
| `itop_apply_stimulus` | `core/apply_stimulus` | 工单状态转移（指派/解决/关闭） | stimulus 白名单 |

**CI 回写风控机制**：
1. **白名单字段**：`itop_update_ci` 内置安全字段清单，只允许更新 `status`/`description`/`serialnumber`/`asset_number`/`custom_attributes` 等非关键字段，拒绝 `org_id`/关系外键等
2. **写前读**：更新前先 `core/get` 获取当前值，仅对有变化的字段执行更新
3. **审计日志**：每次写入记录时间戳、操作者、CI 对象、变更前后值到 stderr
4. **Agent 侧 Pending Action**：SxDevOps Preflight 在写入前弹出确认框，用户确认后才执行

**工具声明示例**：
```json
{
  "name": "itop_get_cis",
  "description": "查询 iTop CMDB 中的配置项（CI）。支持按 CI 类名（Server/NetworkDevice/StorageSystem 等）和 OQL 条件查询。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "class": {"type": "string", "description": "CI 类名，如 Server、NetworkDevice、VirtualMachine、StorageSystem 等"},
      "key": {"type": "string", "description": "查询条件：数字 ID、OQL 语句（如 SELECT Server WHERE status='production'）、或条件对象"},
      "output_fields": {"type": "string", "description": "返回字段，逗号分隔，默认 id,name,status。* 表示全部"}
    },
    "required": ["class", "key"]
  }
}
```

### 2.2 Go 实现要点

**JSON-RPC 2.0 协议处理**（main.go 核心逻辑）：
```go
// stdin 逐行读取 JSON 请求 → 解析 method → 分发 handler → stdout 写入 JSON 响应
scanner := bufio.NewScanner(os.Stdin)
for scanner.Scan() {
    var req JSONRPCRequest
    json.Unmarshal(scanner.Bytes(), &req)
    switch req.Method {
    case "initialize":
        writeResponse(req.ID, initializeResult{...})
    case "tools/list":
        writeResponse(req.ID, toolsListResult{Tools: getTools()})
    case "tools/call":
        result := dispatchTool(req.Params.Name, req.Params.Arguments)
        writeResponse(req.ID, result)
    case "ping":
        writeResponse(req.ID, map[string]interface{}{})
    }
}
```

**复用 itop-clinet 的函数**：
- `callItopAPI(jsonData)` → 所有 API 调用的底层函数（multipart/form-data POST）
- `GetObjects(class, key, outputFields)` → `itop_get_cis` / `itop_get_tickets` / `itop_get_ticket_detail`
- `GetRelated(class, key, relation, depth, direction)` → `itop_get_related`
- `CheckCredentials(user, password)` → `itop_check_credentials`
- `CreateObject(class, fields, comment)` → `itop_create_ci` / `itop_create_ticket`
- `UpdateObject(class, key, fields, comment)` → `itop_update_ci` / `itop_update_ticket`
- `ApplyStimulus(class, key, stimulus, fields)` → `itop_apply_stimulus`

**CI 更新白名单校验**（itop_update_ci 专用）：
```go
var ciSafeFields = map[string]bool{
    "status": true, "description": true, "serialnumber": true,
    "asset_number": true, "purchase_date": true, "end_of_warranty": true,
    // 自定义属性通过 custom_attributes JSON 字段传递
}
```

### 2.3 部署方案：与 SxDevOps 同机（stdio 模式）

**推荐方案**：iTop MCP Server 与 SxDevOps 部署在同一台服务器，以 stdio 子进程方式运行。

| 维度 | 同机 stdio（推荐） | 独立 HTTP 部署 |
|:--|:--|:--|
| MCP 通信 | stdin/stdout（零网络开销） | HTTP POST JSON-RPC |
| 部署复杂度 | ⭐ 简单（复制二进制 + 一行配置） | ⭐⭐⭐ 需额外实现 HTTP 传输层 |
| 现有模式参考 | N9E MCP、SkyWalking MCP | Grafana MCP |
| iTop 网络延迟 | 取决于 SxDevOps ↔ iTop 网络 | 取决于 MCP Server ↔ iTop 网络 |

**配置示例**（AIOps 配置 → MCP → 新增）：
```
名称: iTop CMDB MCP
类型: STDIO
命令: /opt/sxdevops/tools/itop-mcp-server stdio \
      --url http://192.168.1.248/webservices/rest.php \
      --user itopuser01 --password <password>
鉴权配置: {"timeout_seconds": 20, "allow_write": false}
启用工具: itop_check_credentials, itop_get_cis, itop_get_related,
          itop_get_tickets, itop_get_ticket_detail
```

**如需启用 CI 回写**：
```
鉴权配置: {"timeout_seconds": 20, "allow_write": true}
启用工具: ... itop_update_ci, itop_create_ci
```

### 2.4 iTopDataSource 数据模型（后端保留）

新建 `backend/cmdb/models.py`：
```python
class iTopDataSource(models.Model):
    name = models.CharField("名称", max_length=128)
    api_url = models.CharField("API 地址", max_length=256)  # http://itop.xx/webservices/rest.php
    api_version = models.CharField("API 版本", max_length=8, default="1.4")
    auth_user = models.CharField("用户名", max_length=64)
    auth_password = models.CharField("密码", max_length=256)  # 加密存储
    organization = models.CharField("组织", max_length=128, blank=True)
    is_enabled = models.BooleanField("启用", default=True)
    sync_mode = models.CharField("同步模式", max_length=16, choices=[('full', '全量'), ('incremental', '增量')], default='full')
    sync_interval = models.IntegerField("同步间隔(秒)", default=3600)
    config = models.JSONField("同步配置", default=dict)  # ci_classes, ticket_classes, relation_types
    last_sync_at = models.DateTimeField("上次同步", null=True, blank=True)
    sync_status = models.CharField("同步状态", max_length=16, default='idle')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

修改 `backend/ops/models.py`：
```python
# TransactionTicket 扩展
external_source = CharField("外部来源", max_length=32, null=True, blank=True)   # "itop"
external_id = CharField("外部ID", max_length=64, null=True, blank=True)        # "Server::3742"
external_url = CharField("外部链接", max_length=256, null=True, blank=True)
```

### 2.5 ⭐ 同步引擎 vs MCP Server 职责划分（关键设计）

| 数据流 | 实现 | 访问 iTop 的方式 | 用途 |
|:--|:--|:--|:--|
| **Agent 实时查询** | iTop MCP Server (Go, stdio) | Go → multipart/form-data → iTop REST API | Agent 对话中按需查询 |
| **批量数据同步** | `itop_sync.py` (Python, Django) | Python requests → multipart/form-data → iTop REST API | 定期全量/增量同步到本地 |
| **本地 CI 查询** | `ConfigItemViewSet` (已有) | 本地 SQLite/MySQL | 前端页面 + 拓扑图 |

> **为什么同步引擎不能通过 MCP Server？**
> MCP Server 运行在 stdio 子进程模式，每个 AIOps 会话独立启动一个进程实例。
> 同步引擎是后台批处理任务，需要独立于 Agent 会话运行。因此同步引擎直接在 Python 中调用 iTop REST API。

**同步引擎实现**（`backend/cmdb/itop_sync.py`）：
- 全量同步：逐 CI 类拉取 → CIType 归一化 → ConfigItem upsert → get_related 拉关系 → CIRelation upsert
- 增量同步：全量拉取 → 与本地 diff → 仅更新变更项
- 工单同步：逐 ticket 类拉取 → TransactionTicket upsert（设置 external_source="itop"）
- 复用现有 `cmdb/sync.py` 的 `Host ↔ ConfigItem` 信号

**后端 API 端点**（`backend/cmdb/itop_views.py`）：
- `iTopDataSourceViewSet`：CRUD + `test_connection` + `trigger_full_sync`
- ~~`backend/cmdb/itop_client.py`~~ — **不再需要，iTop API 调用分散到 MCP Server(Go) 和 itop_sync.py(Python) 中各自实现**

### 2.6 ⭐ AIOps 知识图谱扩展（iTop）
`build_knowledge_graph()` 新增节点类型：`itop_datasource`、`itop_ticket`
新增关系类型：`itop_ticket_ci`（iTop工单 → 关联本地 ConfigItem）

### 2.7 前端页面 — iTopCMDB.vue
- 路由：`/cmdb/itop`
- Tabs：数据源配置 / 同步状态 / 同步的 CI 列表 / 同步的工单列表
- **不再需要** iTop API 代理查询页面（由 Agent MCP 工具替代）

### 2.8 AIOps MCP 工具

| 工具名 | 功能 | 来源 |
|:--|:--|:--|
| `mcp__iTop_CMDB_MCP__itop_get_cis` | 查询 iTop CMDB 配置项 | 外部 MCP Server |
| `mcp__iTop_CMDB_MCP__itop_get_related` | 查询 CI 间关联关系 | 外部 MCP Server |
| `mcp__iTop_CMDB_MCP__itop_get_tickets` | 查询 iTop 工单 | 外部 MCP Server |
| `sxdevops.query_cmdb_cis` | 查询本地同步的配置项 | 平台内置（已有） |

---

## Phase 3：深度 AIOps 整合

### 3.1 Zabbix Problem → Alert 桥接
新建 `backend/ops/zabbix_alert_bridge.py`：
- 后台轮询或 Webhook 接收 Zabbix Problem
- 复用 `_normalize_zabbix()` 标准化 → 写入 Alert 模型
- 触发通知/升级/EventWall 链路

### 3.2 ⭐ AIOps Action（iTop 变更影响分析）

在 `BUILTIN_ACTION_REGISTRY` 中新增：

```python
{
    'code': 'itop.change_impact',
    'display_name': '变更影响分析（iTop CMDB）',
    'category': '变更关联',
    'risk_level': 'read_only',
    'agent_mode': 'react',
    'allowed_tools': [
        'mcp__iTop_CMDB_MCP__itop_get_cis',
        'mcp__iTop_CMDB_MCP__itop_get_related',
        'mcp__iTop_CMDB_MCP__itop_get_tickets',
        'query_knowledge_graph', 'query_recent_changes',
    ],
    'skills': ['sx-itop-impact-analysis', 'sx-change-impact-analysis', 'answer-formatter'],
    'required_context': ['environment'],
}
```

### 3.3 ⭐ AIOps Skill（iTop）

在 `BUILTIN_SKILLS` 中新增：

```python
{
    'slug': 'sx-itop-impact-analysis',
    'name': 'iTop 变更影响分析',
    'category': '变更关联',
    'risk_level': 'read_only',
    'builtin_tools': [
        'mcp__iTop_CMDB_MCP__itop_get_cis',
        'mcp__iTop_CMDB_MCP__itop_get_related',
        'mcp__iTop_CMDB_MCP__itop_get_tickets',
    ],
    'output_contract': {
        'sections': ['变更概述', '影响范围', '关联CI', '关联工单', '风险等级', '建议审批策略'],
    },
}
```

### 3.4 联合分析 Action
在 `BUILTIN_ACTION_REGISTRY` 中新增跨系统 Action：

```python
{
    'code': 'cross_system.root_cause',
    'display_name': '跨系统根因分析',
    'category': '故障排障',
    'risk_level': 'read_only',
    'agent_mode': 'plan_react',
    'allowed_tools': [
        # Zabbix（平台内置 MCP 工具）
        'query_zabbix_problems', 'query_zabbix_hosts', 'query_zabbix_items', 'query_zabbix_history',
        # iTop（外部 MCP Server 工具，别名前缀 mcp__iTop_CMDB_MCP__）
        'mcp__iTop_CMDB_MCP__itop_get_cis', 'mcp__iTop_CMDB_MCP__itop_get_related', 'mcp__iTop_CMDB_MCP__itop_get_tickets',
        # 现有
        'query_alerts', 'query_logs', 'query_traces', 'query_knowledge_graph',
        'query_recent_changes', 'query_event_wall',
    ],
    'skills': [
        'sx-zabbix-troubleshooting', 'sx-itop-impact-analysis',
        'sx-alert-evidence-checklist', 'sx-change-impact-analysis',
        'sx-event-timeline-correlation', 'answer-formatter',
    ],
}
```

### 3.5 Dashboard 统计增强
- `dashboard_stats` 扩展：Zabbix 主机可用率、iTop 同步 CI 数、未关闭 iTop 工单数

### 3.6 事件墙集成
- 所有同步/测试连接/Zabbix Problem 导入 → `record_event()` 写入 EventWall

---

## 📊 AIOps 整合全景

```
用户自然语言提问
       ↓
Action Router（关键词匹配 + 上下文路由）
       ↓
┌──────────────────────────────────────────────────────┐
│ 新增 Action:                                          │
│  zabbix.problem_analysis    → Zabbix 告警分析         │
│  itop.change_impact         → iTop 变更影响分析        │
│  cross_system.root_cause    → 跨系统联合根因分析       │
└──────────────────────────────────────────────────────┘
       ↓
Agent Mode: direct / react / plan_react
       ↓
┌──────────────────────────────────────────────────────┐
│ 新增 MCP 工具（Agent 可调用）:                         │
│  [Platform Built-in] query_zabbix_*           (Zabbix) │
│  [External MCP stdio] mcp__iTop_CMDB_MCP__*   (iTop)   │
└──────────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────────┐
│ 新增 Skill（SOP 约束）:                                │
│  sx-zabbix-troubleshooting   → Zabbix 排障 SOP       │
│  sx-itop-impact-analysis     → iTop 影响分析 SOP      │
└──────────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────────┐
│ 知识图谱（关联可视化）:                                 │
│  + zabbix_host → infrastructure 节点                  │
│  + zabbix_problem → zabbix_host 节点                 │
│  + itop_ticket → ConfigItem 节点                     │
│  + CMDB/iTop CI 关系 → depends_on/runs_on/connects_to │
└──────────────────────────────────────────────────────┘
       ↓
Preflight 预检 → Skill 约束输出 → Pending Action 确认 → 执行 → 审计
```

---

## RBAC 权限码新增

```python
# Zabbix（3 个）
('ops.zabbix.view', '查看 Zabbix 监控', 'ops', '查看 Zabbix 主机、监控项、历史数据和问题'),
('ops.zabbix.datasource.view', '查看 Zabbix 数据源', 'ops', '查看 Zabbix Server 连接配置'),
('ops.zabbix.datasource.manage', '管理 Zabbix 数据源', 'ops', '新增、编辑、删除、测试 Zabbix 数据源'),

# iTop / CMDB 扩展（4 个）
('cmdb.itop.view', '查看 iTop 对接', 'cmdb', '查看 iTop 同步状态与结果'),
('cmdb.itop.datasource.view', '查看 iTop 数据源', 'cmdb', '查看 iTop 数据源配置'),
('cmdb.itop.datasource.manage', '管理 iTop 数据源', 'cmdb', '新增、编辑、删除 iTop 数据源并触发同步'),
('cmdb.itop.ticket.view', '查看 iTop 工单', 'cmdb', '查看从 iTop 同步的工单'),
```

---

## 文件变更清单

### 新建文件（9 个）
| 文件 | 说明 |
|:--|:--|
| `backend/ops/zabbix_client.py` | Zabbix JSON-RPC 客户端 |
| `backend/ops/zabbix_views.py` | Zabbix ViewSet + 代理端点 |
| `backend/ops/zabbix_alert_bridge.py` | Zabbix Problem → Alert 桥接 |
| `backend/cmdb/itop_sync.py` | iTop 数据同步引擎（CI/关系/工单 → 本地模型） |
| `backend/cmdb/itop_views.py` | iTop 数据源 ViewSet + 同步触发端点 |
| **`tools/itop-mcp-server/main.go`** | **iTop MCP Server（Go，JSON-RPC 2.0 stdio）** |
| **`tools/itop-mcp-server/itop_client.go`** | **从 itop-clinet 复用的 iTop REST API 封装** |
| `frontend/src/views/ZabbixMonitor.vue` | Zabbix 监控页面 |
| `frontend/src/views/iTopCMDB.vue` | iTop CMDB 对接页面 |

### 修改现有文件（17 个）
| 文件 | 变更点 |
|:--|:--|
| `backend/sxdevops/urls.py` | 注册 CMDB 路由 |
| `backend/sxdevops/settings.py` | 新增 INTEGRATION_CONFIG |
| `backend/ops/models.py` | 新增 ZabbixDataSource + TransactionTicket 扩展(external_source/external_id) |
| `backend/ops/urls.py` | 注册 Zabbix 路由 |
| `backend/ops/views.py` | dashboard_stats 扩展 |
| `backend/cmdb/models.py` | 新增 iTopDataSource |
| `backend/cmdb/urls.py` | 注册 iTop 路由 |
| `backend/rbac/registry.py` | 新增 7 个权限码 + 更新内置角色 |
| **`backend/aiops/services.py`** | **PLATFORM_MCP_TOOL_DEFINITIONS 新增 7 个工具 + handler 实现 + BUILTIN_ACTION_REGISTRY 新增 3 个 Action + BUILTIN_SKILLS 新增 2 个 Skill** |
| **`backend/aiops/knowledge_graph.py`** | **build_knowledge_graph() 增加 Zabbix/iTop 节点和关系** |
| **`backend/aiops/models.py`** | **AIOpsKnowledgeEnvironment 增加 zabbix_datasource_ids / itop_datasource_ids** |
| `frontend/src/router/index.js` | 新增 Zabbix + iTop + CMDB 路由 |
| `frontend/src/layout/AppLayout.vue` | 新增 CMDB + Zabbix + iTop 菜单项 |
| `frontend/src/api/modules/ops.js` | 新增 Zabbix API 函数 |
| `frontend/src/api/modules/cmdb.js` | 新增 iTop API 函数 |
| `frontend/src/views/Dashboard.vue` | 新增统计卡片 |
| `frontend/src/views/AIOpsKnowledgeConfig.vue` | 知识环境配置中可选 Zabbix/iTop 数据源 |

---

## 实施顺序

```
Phase 0 (前置)   → Phase 1 (Zabbix+AI)  → Phase 2 (iTop+AI)      → Phase 3 (深度整合)
      ↓                     ↓                     ↓                       ↓
  P0.1 路由修复        P1.1 模型             P2a iTop MCP Server    P3.1 Alert桥接
  P0.2 菜单            P1.2 Zabbix客户端      P2b iTopDataSource模型  P3.2 联合Action
                       P1.3 Zabbix视图        P2c itop_sync同步引擎  P3.3 Dashboard
                       P1.4 平台MCP工具(4个)  P2d itop_views视图     P3.4 事件墙
                       P1.5 Action(1个)       P2e 前端iTopCMDB页面
                       P1.6 Skill(1个)        P2f 知识图谱扩展
                       P1.7 知识图谱节点      P2g 知识环境配置
                       P1.8 知识环境配置      P2h 注册SxDevOps MCP
                       P1.9 前端页面

每个 Phase 完成后可独立验证，互不阻塞。
```

> **Phase 2 核心区别**：`iTop MCP Server`（Go）独立于 Django 开发，负责 Agent 实时查询；
> `itop_sync.py`（Python）负责批量同步 iTop 数据到本地 CMDB 模型。
> 二者通过不同路径访问 iTop——MCP Server 是 Agent 的查询接口，sync 是后台数据管道。

---

## 验证方式

1. **P0**：`GET /api/cmdb/ci-types/` 返回 200
2. **Zabbix + AI**：配置数据源 → Agent 输入"帮我查 Zabbix 上 order-center 相关主机有没有告警" → Agent 调用 `query_zabbix_hosts`/`query_zabbix_problems` 工具 → Skill 按 SOP 输出结构化回答
3. **iTop + AI**：触发全量同步 → 验证 CI/关系/工单落库 → Agent 输入"这个变更会影响哪些服务器？" → Agent 调用 `query_itop_relations` → 知识图谱可视化展示影响链路
4. **知识图谱**：访问 `/aiops/knowledge-graph/` → Zabbix 主机/告警节点和 iTop CI/工单节点可见
5. **RBAC**：不同角色验证菜单+AIOps 工具可用性
