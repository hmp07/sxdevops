# SxDevOps 数据模式设计

## 文档目的

本文档完整梳理了 SxDevOps 平台中**全部 12 类数据源**的接入方式、数据结构、流转逻辑、关联映射关系，以及知识图谱中的数据模型。以此为基础，给出了 Zabbix 和 iTop 数据融入后的**统一数据模型设计方案**。

---

# 第一部分：全平台数据源梳理

## 一、数据源全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                      SxDevOps 数据源全景                          │
├───────────────────┬──────────────┬──────────────┬────────────────┤
│   监控与可观测性   │   CMDB/配置   │  任务与部署   │  事件与告警    │
├───────────────────┼──────────────┼──────────────┼────────────────┤
│ Zabbix (监控)     │ iTop (CMDB)  │ 任务中心      │ 告警中心       │
│ Prometheus/Grafana│ ConfigItem   │ TaskResource  │ Alert          │
│ Loki/ELK/SLS (日志)│ CIRelation  │ Host          │ 事件墙          │
│ SkyWalking/Tempo  │ DeviceMapping│ Deployment    │ EventRecord    │
│ (链路追踪)        │              │ Transaction   │ EventSource    │
│ K8s (容器编排)    │              │ Ticket        │                │
│ Docker (容器)     │              │               │                │
└───────────────────┴──────────────┴──────────────┴────────────────┘
```

---

## 二、逐一数据源分析

### 2.1 K8s 集群数据

**数据模型**：
```
K8sCluster (ops_k8scluster)
  ├── name (唯一), api_server, kubeconfig, status
  ├── 运行时资源（无 DB 存储，全部实时）
  │     ├── Nodes, Namespaces, Pods
  │     ├── Deployments, StatefulSets, DaemonSets
  │     ├── Services, Ingresses, ConfigMaps, Secrets
  │     ├── PVs, PVCs, StorageClasses
  │     └── Jobs, CronJobs
  └── K8sConfigRevision (配置变更历史)
```

**接入方式**：手动配置 K8sCluster → 实时调用 Kubernetes API（kubernetes Python SDK）→ Django Cache 缓存（8-15s TTL）→ API 响应

**关键特点**：
- 无持久化运行时数据存储，纯实时 + 缓存
- 支持 kubeconfig='demo' 返回硬编码演示数据
- ConfigMap/Secret 支持在线编辑，有修订历史

---

### 2.2 Docker 环境数据

**数据模型**：
```
DockerHost (ops_dockerhost)
  ├── name (唯一), ip_address, ssh_port/ssh_user/ssh_password
  ├── docker_api_version, status
  └── 运行时容器/镜像（无 DB 存储）
```

**接入方式**：手动配置 DockerHost → SSH 远程执行 `docker ps -a`/`docker images` → JSON 解析 → 实时响应

---

### 2.3 指标数据源 (Prometheus/Grafana)

**数据模型**：
```
MetricDataSource (ops_metricdatasource)
  ├── name (唯一), provider ('prometheus')
  ├── tsdb_type ('prometheus'/'zabbix') ← 路由标记
  ├── config (query_url, auth_type, headers, bearer_token)
  └── environment, cluster_name, is_default

GrafanaSetting (ops_grafanasetting)
  ├── name, url, enabled
  ├── folders, dashboards (JSONField)
  └── dashboard panel data (实时查询)
```

**接入方式**：
- Prometheus：手动配置 MetricDataSource → 实时 PromQL HTTP API 查询
- Grafana：手动配置 GrafanaSetting → 实时 Grafana HTTP API 查询面板/数据源代理
- Zabbix 路由标记：`ZabbixDataSource.save()` 信号自动创建 `MetricDataSource(tsdb_type='zabbix')`

---

### 2.4 日志数据源 (Loki/ELK/SLS)

**数据模型**：
```
LogDataSource (ops_logdatasource)
  ├── name (唯一), provider ('loki'/'elk'/'sls')
  ├── config (endpoint, auth, index_patterns)
  └── is_default

LogEntry (ops_logentry)  ← 平台自身应用日志
  ├── level, service, message
  ├── host → FK(Host, SET_NULL)
  └── timestamp
```

**接入方式**：
- Loki：LogQL HTTP API 实时查询
- ELK：Elasticsearch `_search` API 实时查询
- SLS：阿里云 SLS REST API（HMAC-SHA1 签名）
- LogEntry：平台自身日志，CRUD API

---

### 2.5 链路追踪数据源

**数据模型**：
```
TracingDataSource (ops_tracingdatasource)
  ├── name (唯一), provider ('skywalking'/'tempo'/'jaeger'/'zipkin')
  ├── config (provider-specific: oap_url, query_url, ui_url, authorization)
  └── is_default

运行时数据（无 DB 存储）：
  ├── 服务目录 (Services)
  ├── Trace 列表 / Trace 详情
  ├── Spans 详情
  └── 拓扑关系 (SkyWalking)
```

**接入方式**：手动配置 TracingDataSource → 实时调用各 Provider 特定 API（GraphQL/HTTP）→ 无持久化

---

### 2.6 告警数据

**数据模型**：
```
Alert (ops_alert)
  ├── 核心：title, level (critical/warning/info), status (active/resolved/closed/muted)
  ├── 来源：source ('zabbix_api'), source_type ('zabbix'/'prometheus'/...)
  ├── 去重：fingerprint ('zabbix:{eventid}' 或 SHA256), group_key
  ├── 关联：host → FK(Host, SET_NULL), service, environment
  ├── 标签：labels (JSONField), annotations (JSONField)
  ├── 生命周期：starts_at, ends_at, acknowledged_at, claimed_at, closed_at
  ├── 抑制：is_suppressed, suppressed_by, mute_until
  ├── 升级：escalation_level, escalated_at
  ├── 原始数据：raw_payload (JSONField)
  └── 关联模型（丰富告警管理）：
        ├── AlertIntegration (Webhook 入口)
        ├── AlertClaim, AlertAction (审计)
        ├── AlertRecipient/Group (通知对象)
        ├── AlertNotificationChannel/Rule/Log (通知渠道与日志)
        ├── AlertAggregationRule (聚合)
        ├── AlertInhibitionRule (抑制)
        ├── AlertMuteRule (静默)
        └── AlertEscalationPolicy (升级策略)
```

**接入方式**（3 条路径）：
1. **Zabbix 轮询**：`_sync_zabbix_hosts` 信号 → `client.get_problems()` → `upsert_alert_from_zabbix_problem()` → `alerting.upsert_alert()`
2. **Webhook 接入**：外部系统 POST 到 `/api/alerting/webhook/` → `alerting.ingest_webhook()` → 归一化 → `upsert_alert()`
3. **手动创建**：AlertViewSet CRUD

---

### 2.7 事件墙数据

**数据模型**：
```
EventRecord (eventwall_eventrecord)
  ├── 核心：occurred_at, module, category, action, result, severity, title
  ├── 来源：source_type (http/async/scheduler/system/seed/external)
  ├── 触发者：actor_type, actor_username
  ├── 关联（松散字符字段）：resource_module, resource_type, resource_id, resource_name
  ├── 上下文：business_line, environment, application
  ├── 数据：detail, changes (JSONField), related_resources (JSONField)
  ├── 父事件：parent_event → FK(self, nullable)
  └── 外部源：correlation_id, ip_address

EventSource (eventwall_eventsource)
  ├── code (唯一 slug), name, source_kind (builtin/external)
  ├── 外部源：endpoint_url, auth_type, token_hash
  ├── 映射：field_mapping (JSONField), config (JSONField)
  └── 状态：enabled, status, last_sync_at, last_event_at, last_error
```

**接入方式**（4 条路径）：
1. **平台操作自动记录**：EventWallModelViewSetMixin → CRUD 操作自动写入 EventRecord
2. **代码显式调用**：`record_event()` / `record_model_event()` 遍布各模块
3. **Zabbix 告警导入**：`zabbix_alert_bridge._record_event()` 记录告警事件
4. **外部 Webhook**：`/api/event-sources/{code}/ingest/` 接受 Jira/Jenkins/ArgoCD/GitLab 等事件

---

### 2.8 任务中心数据

**数据模型**：
```
Host (ops_host)
  ├── hostname (唯一), ip_address, status (online/offline/warning)
  ├── business_line, environment, os_type
  ├── cpu_usage, memory_usage, disk_usage
  ├── ssh_port, ssh_user, ssh_password
  ├── source ('manual'/'zabbix'), external_id ('zabbix:{hostid}')
  └── 关联：Alert.host, TaskResource.host, LogEntry.host

TaskResourceGroup (ops_taskresourcegroup)
  ├── name, code (slug), group_type (environment/system)
  └── parent → FK(self), 层次结构

TaskResource (ops_taskresource)
  ├── name, resource_type (host/k8s), status
  ├── environment → FK(TaskResourceGroup), system → FK(TaskResourceGroup)
  ├── host → FK(Host), cluster → FK(K8sCluster)
  ├── ip_address, ssh_*, namespace
  └── external_id ('zabbix:{hostid}'), metadata (JSONField)

HostTask (ops_hosttask) + HostTaskTemplate + HostTaskSchedule + HostTaskExecution
  └── 完整的任务创建、模板、调度、执行系统
```

**接入方式**：
- Host：手动 CRUD + Zabbix 信号自动创建
- TaskResource：手动 CRUD + Zabbix 信号自动创建（归入 'Zabbix 监控主机' 分组）
- HostTask：API 创建 + AIOps 智能助手生成

---

### 2.9 部署与工单数据

**数据模型**：
```
Deployment (ops_deployment)
  ├── app_name, version, image, environment
  ├── deploy_mode (docker_compose/k8s)
  ├── status, approval_status, action_type
  ├── 关联：host, docker_host, cluster, approval_flow
  ├── 版本链：previous_success, rollback_source, rerun_source → FK(self)
  └── 审批流：DeploymentApprovalFlow → DeploymentApprovalNode → DeploymentApprovalStep

TransactionTicket (ops_transactionticket)
  ├── title, ticket_type (change/inspection/access/incident)
  ├── priority, status (pending/approved/processing/done/rejected)
  ├── 外部源：external_source ('itop'), external_id, external_url
  └── approval_flow → FK(DeploymentApprovalFlow)

### 2.10 iTop CMDB 数据

**数据模型**：
```
iTopDataSource (cmdb_itopdatasource)
  ├── name, api_url, api_version, auth_user, auth_password, organization
  ├── sync_mode (full/incremental), sync_interval
  ├── config (JSONField): ci_class_map, ci_classes, relation_types, ticket_classes
  └── last_sync_at, sync_status

ConfigItem (cmdb_configitem)
  ├── name, ci_type → FK(CIType)
  ├── business_line, environment (prod/test/dev), admin_user, status
  ├── attributes (JSONField) ← iTop 全部自定义字段
  ├── itop_datasource → FK(iTopDataSource), external_id ('itop:ClassName:id')
  └── 关联：zabbix_mapping → OneToOneField(DeviceMapping)

CIType (cmdb_citype)
  ├── name (唯一), icon, color, description

CIRelation (cmdb_cirelation)
  ├── source → FK(ConfigItem), target → FK(ConfigItem)
  ├── relation_type (depends_on/runs_on/connects_to)
  └── unique(source, target, relation_type)
```

**接入方式**：
- iTopDataSource 手动创建 → 点击"触发同步" → `run_full_sync()` 全量同步
- 同步流程：sync_ci_classes → sync_cis → sync_relations → sync_tickets → reconcile_device_mappings()
- CI 按需补齐：relation sync 遇到未同步的 CI 时，自动从 iTop API 拉取并创建

**iTop CI 类映射**：
```
Server           → 云主机(ECS)
VirtualMachine   → 虚拟机
NetworkDevice    → 网络设备
StorageSystem    → 存储系统
ApplicationSolution → 应用方案
WebApplication   → Web应用
WebServer        → Web服务器
DBServer         → 数据库服务器
Hypervisor       → 虚拟化平台
BusinessProcess  → 业务流程
```

**iTop Ticket 映射**：
```
UserRequest      → TransactionTicket (change)
Incident         → TransactionTicket (incident)
NormalChange     → TransactionTicket (change)
Problem          → TransactionTicket (incident)
```

---

### 2.11 Zabbix 监控数据

**数据模型**：
```
ZabbixDataSource (ops_zabbixdatasource)
  ├── name, api_url, auth_type (token/userpass)
  ├── auth_token / username+password
  ├── tls_verify, timeout, is_default
  └── last_sync_at, config (JSONField)

DeviceMapping (ops_devicemapping)
  ├── zabbix_hostid (唯一), zabbix_hostname, zabbix_ip
  ├── config_item → OneToOneField(ConfigItem, nullable)
  ├── match_method (ip_exact/name_fuzzy/manual)
  ├── match_confidence (1.0/0.7), is_verified
  └── 索引: zabbix_ip, config_item
```

**接入方式**：
- 手动配置 ZabbixDataSource → `post_save` 信号触发完整级联：
  1. `ZabbixClient.get_hosts()` → 拉取全部主机
  2. `Host.objects.update_or_create()` → 创建/更新 Host 记录
  3. `TaskResource.objects.update_or_create()` → 创建 TaskResource
  4. `match_all_zabbix_hosts()` → 创建 DeviceMapping
  5. `reconcile_device_mappings()` → 双向修复
  6. `MetricDataSource.update_or_create()` → 创建路由标记
  7. `client.get_problems()` → 轮询告警 → `upsert_alert_from_zabbix_problem()`

**Zabbix API 调用方式**（`ZabbixClient`）：
- JSON-RPC 2.0 协议
- 认证：Token（Bearer header）/ UserPass（`user.login` 获取 session token）
- 主要方法：`host.get`, `hostgroup.get`, `problem.get`, `trigger.get`, `item.get`, `history.get`, `trend.get`

---

### 2.12 跨数据源桥接 (ObservabilityDataSourceLink)

**数据模型**：
```
ObservabilityDataSourceLink
  ├── log_datasource → FK(LogDataSource)
  ├── tracing_datasource → FK(TracingDataSource)
  ├── trace_id_fields (JSONField), trace_id_regex
  ├── log_query_template (LogQL), log_label_mappings (JSONField)
  ├── grafana_dashboard_key, grafana_variable_mappings (JSONField)
  └── unique(log_datasource, tracing_datasource)
```

**功能**：实现日志 → 链路、链路 → 日志、日志 → Grafana、链路 → Grafana 的跨源跳转。

---

# 第二部分：数据源关联映射关系

## 三、核心关联链

### 3.1 Zabbix ↔ iTop 双向桥接

```
Zabbix API                          iTop API
    │                                    │
    ▼                                    ▼
ZabbixDataSource.save()            iTopDataSource 同步
    │                                    │
    ├── get_hosts()                     ├── sync_cis()
    │     └── {hostid, host,             │     └── ConfigItem
    │         ip, status,                │         (external_id='itop:{class}:{id}')
    │         groups}                    │
    │                                    │
    ├── Host                             │
    │   (external_id='zabbix:{hostid}')  │
    │                                    │
    ├── TaskResource                     │
    │   (external_id='zabbix:{hostid}')  │
    │                                    │
    └── DeviceMapping ◄──────────────► ConfigItem
        (zabbix_hostid)      (一对一)    (zabbix_mapping)
        match_method: ip_exact           │
        match_method: name_fuzzy         │
        match_method: manual             │
                                         │
    ┌──── reconcile_device_mappings() ◄──┘
    │  (双向修复：Zabbix→CI, CI→Zabbix)
    │
    ▼
知识图谱数据统一展示
```

### 3.2 Host ↔ ConfigItem 双向同步

```
Host (ops)                    ConfigItem (cmdb)
  post_save ─────────────────→ sync_host_to_config_item()
                                (创建/更新 host-like ConfigItem)
  
  post_delete ────────────────→ delete_config_item_for_host()
  
                               ConfigItem post_save ─→ sync_config_item_to_host()
                               (创建/更新 Host)
                               
                               ConfigItem post_delete
                               ├── delete_host_for_config_item()
                               └── DeviceMapping.config_item = NULL
```

### 3.3 告警关联链

```
Zabbix problem (API)
    │
    ▼
upsert_alert_from_zabbix_problem()
    │
    ├── fingerprint = 'zabbix:{eventid}'
    ├── host → Host (via _host_for: hostname/ip match)
    │         └── Host.external_id = 'zabbix:{hostid}'
    │               └── DeviceMapping.config_item → ConfigItem
    ├── environment = ZabbixDataSource.name
    │
    ▼
alerting.upsert_alert()
    ├── apply_alert_suppression()
    ├── dispatch_alert_notifications()
    └── _record_event() → EventWall
```

### 3.4 知识环境数据源选择

```
AIOpsKnowledgeEnvironment
    │
    ├── zabbix_datasource_ids ────→ ZabbixDataSource
    ├── itop_datasource_ids ───────→ iTopDataSource
    ├── metric_datasource_ids ─────→ MetricDataSource
    ├── log_datasource_ids ────────→ LogDataSource
    ├── tracing_datasource_ids ────→ TracingDataSource
    ├── k8s_cluster_ids ───────────→ K8sCluster (+ namespaces)
    ├── docker_host_ids ───────────→ DockerHost
    ├── task_resource_environment_ids → TaskResourceGroup
    ├── alert_environments ────────→ Alert.environment
    ├── event_environments ────────→ EventRecord.environment
    └── observability_link_ids ────→ ObservabilityDataSourceLink

    ↓ (传递给 build_knowledge_graph)

selected_* 过滤集 → 各数据源加载 → 知识图谱节点/边
```

---

# 第三部分：知识图谱数据模型

## 四、知识图谱节点类型目录

| kind | category 示例 | 数据源 | 生命周期 | 节点 key 格式 |
|------|-------------|--------|---------|-------------|
| **environment** | 环境 | AIOpsKnowledgeEnvironment | 配置持久 | `environment:{name}` |
| **system** | 系统 | ① K8s/Tracing 上下文<br>② CMDB ApplicationSolution | 运行时发现 | ① `system:{name}`<br>② `cmdb_system:{name}` |
| **service** | 服务 | ① K8s/Docker/Deploy/Tracing<br>② CMDB BusinessProcess | 运行时发现 | ① `service:{name}`<br>② `cmdb_service:{ci.id}` |
| **capability** | 数据来源 | 静态定义 (CAPABILITY_DEFS) | 常量 | `capability:{code}` |
| **infrastructure** | K8s集群/主机/Docker/资源底座/CMDB主机 | ① K8sCluster (实时API)<br>② DockerHost (实时SSH)<br>③ TaskResource<br>④ ConfigItem (iTop) | 混合 | `infrastructure:k8s:{id}`<br>`infrastructure:task_resource:{id}`<br>`cmdb_infra:{ci.id}` |
| **runtime_component** | DB/中间件/服务 | ① K8s 自动发现<br>② Docker 自动发现<br>③ Tracing spans<br>④ ConfigMaps<br>⑤ ServiceDeployment<br>⑥ CMDB DBServer/WebServer | 运行时发现 | `runtime_component:{name}`<br>`cmdb_component:{ci.id}` |
| **datasource** | 指标/日志/链路/Zabbix/iTop源 | 各 DataSource 模型 | 配置持久 | `metric_ds:{id}` / `log_ds:{id}` / `trace_ds:{id}` / `zabbix_ds:{id}` / `itop_ds:{id}` |
| **dashboard** | Grafana看板目录 | GrafanaSetting | 配置持久 | `dashboard_folder:{folder}` |
| **event_source** | 事件源 | EventSource | 配置持久 | `event_source:{id}` |

## 五、知识图谱边关系目录

| relation | label 示例 | 连接 | 方向性 |
|----------|-----------|------|--------|
| `environment_system` | 包含系统 | environment → system | 层次 |
| `system_service` | 承载服务 / 包含流程 | system → service | 层次 |
| `environment_service` | 业务流程 | environment → service | 回退 |
| `service_capability` | 产生数据 | service → capability | 数据流 |
| `environment_infrastructure` | 运行于 / 孤立主机 | environment → infrastructure | 部署 |
| `infrastructure_member` | 包含主机 / 包含资源 | infra → infra | 成员 |
| `environment_resource_base` | 关联资源底座 | environment → infra | 任务 |
| `service_deployment` | 部署在 | service/component → infra | 部署 |
| `service_runtime` | 服务依赖 | service → runtime_component | 依赖 |
| `system_runtime_component` | 依赖组件 | system → runtime_component | CMDB |
| `system_infrastructure` | 包含主机 | system → infrastructure | CMDB |
| `capability_datasource` | 接入指标源/日志源/链路源/Zabbix/iTop | capability → datasource | 数据流 |
| `capability_event_source` | 接入事件源 | capability → event_source | 数据流 |
| `capability_dashboard` | 展示看板 | capability → dashboard | 展示 |
| `environment_observability` | 关联指标源/可观测性/事件源 | environment → ds/dashboard/event_source | 关联 |
| `observability_link` | Trace ID关联/看板跳转 | datasource ↔ datasource/dashboard | 跨源 |
| `cmdb_relation` | depends_on/runs_on/connects_to | CI节点 → CI节点 | CMDB拓扑 |

## 六、知识图谱构建流程

```
build_knowledge_graph(params)
    │
    ├─ [1] 环境解析
    │     selected_knowledge_configs = resolve(params.environment)
    │     selected_* 过滤集 = union(configs[*].datasource_ids)
    │
    ├─ [2] 预加载 (CMDB)
    │     全部 ConfigItem → _cmdb_ci_lookup
    │     DeviceMapping → _cmdb_mapping_by_ip / _cmdb_mapping_by_name
    │     BFS 传播 business_line (ApplicationSolution → 下游 CI)
    │     构建 iTop IP/名称 → business_line 索引
    │
    ├─ [3] 基础设施加载
    │     K8s 集群/节点 → infrastructure 节点
    │     Docker 环境 → infrastructure 节点
    │     TaskResource (含 Zabbix) → infrastructure 节点
    │       └─ CMDB 富化: DeviceMapping → cmdb_ci → business_line
    │
    ├─ [4] 运行时组件发现
    │     K8s/Docker/Tracing/ConfigMap → runtime_component 节点
    │     Marketplace 部署 → runtime_component 节点
    │
    ├─ [5] 数据源接入
    │     Metric/Log/Tracing/Zabbix/iTop → datasource 节点
    │     Grafana → dashboard 节点
    │
    ├─ [6] CMDB 系统/服务/组件节点 (新增)
    │     ApplicationSolution → system 节点
    │     BusinessProcess → service 节点
    │     DBServer/WebServer/WebApplication → runtime_component 节点
    │     Server/VirtualMachine (无Zabbix) → infrastructure 节点
    │     CIRelation → cmdb_relation 边
    │
    ├─ [7] 服务上下文
    │     Alert/Event 关联 → environment/system/service 节点
    │     Tracing 服务目录 → 服务上下文
    │
    ├─ [8] 跨源关联
    │     ObservabilityDataSourceLink → observability_link 边
    │     Zabbix infra → CMDB system → system_infrastructure 边
    │
    ├─ [9] 图过滤
    │     仅保留从选定 environment 可达的节点和边
    │
    ├─ [10] 快照持久化
    │     association_snapshot / child_node_snapshot → DB
    │
    └─ [11] 缓存 (20s TTL) → API 响应
```

---

# 第四部分：数据融合问题分析

## 七、当前数据融合的断点与不足

### 7.1 基础设施节点的多重身份

**问题**：同一台物理服务器在知识图谱中有多个表示：
- Zabbix 角度：`infrastructure:task_resource:{id}` ← 来自 TaskResource
- CMDB 角度：`cmdb_infra:{ci.id}` ← 来自 ConfigItem (iTop)
- 如果还有 K8s 节点：`infrastructure:k8s_host:{cid}:{name}`

**当前方案（部分解决）**：通过 DeviceMapping 将 TaskResource 富化 CMDB 元数据，并为有 Zabbix 映射的 CI 跳过 `cmdb_infra` 节点创建。但仍有 12 个无法匹配 IP/名称的 CI 创建了独立的 `cmdb_infra` 节点。

**改进方向**：增强名称模糊匹配（如 "mysql57" vs "vm-mysql57"），将更多 CI 对接到已有 TaskResource 节点。

### 7.2 业务线的断裂

**问题**：
- iTop ApplicationSolution 有 `business_line='电商平台'`
- 但其他 CI (DBServer, WebServer 等) 的 `business_line` 字段为空
- 当前通过 BFS 沿 CIRelation 传播解决，但依赖拓扑完整性
- Zabbix 创建的 Host 完全无 business_line

**当前方案（部分解决）**：BFS 传播 + iTop IP 索引补充 Zabbix CI 的 business_line。

### 7.3 服务发现的碎片化

**问题**：平台有 5 条独立服务发现路径：
1. K8s workload 名称 → 推测服务名
2. Docker 容器名/镜像名 → 推测服务名
3. Tracing 服务目录 → 精确服务名
4. 部署记录 (Deployment.app_name) → 精确服务名
5. CMDB BusinessProcess → 业务流程名

这些路径之间没有关联键。同一个服务（如 "订单服务"）在不同系统中可能有不同名称。

**改进方向**：建立服务名称映射表 / 别名系统，统一服务标识。

### 7.4 运行时组件与 CMDB 组件的割裂

**问题**：
- K8s/Docker/Tracing 自动发现的 `runtime_component`（如 "db-mysql57"）
- CMDB 中的 DBServer（如 "vm-mysql57"）
- 可能是同一个 MySQL 实例，但在知识图谱中是两个独立节点

**当前方案**：无关联。两个节点通过不同的 relation 分别连接到服务和系统。

**改进方向**：通过 IP 或名称匹配合并运行时发现的组件与 CMDB 组件。

### 7.5 告警与拓扑的弱关联

**问题**：
- Alert 有 `host` FK 指向 Host 表
- Host 通过 DeviceMapping 关联 ConfigItem
- ConfigItem 通过 CIRelation 关联拓扑
- 但 Alert 不直接关联知识图谱节点 - 只能通过 hostname/ip 间接匹配服务

**改进方向**：在告警创建时，自动解析其影响的 CI/服务/系统，写入 Alert 的 service/business_line 字段。

### 7.6 数据源配置散落

**问题**：一个"知识环境"需要手动填写 18 个 JSON 字段来选择数据源。字段之间没有一致性校验 —— 比如选择了 ZabbixDS ID=1 但 TaskResourceGroup ID=3（而实际 Zabbix 在组 ID=4 中）。

**改进方向**：自动发现环境关联的数据源 ID，减少手动配置。

---

# 第五部分：统一数据模型设计

## 八、统一实体分层模型

```
                          ┌─────────────────────┐
                          │   知识环境 (Environment)│
                          │   公司测试开发系统      │
                          └──────────┬──────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
     ┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐
     │   业务系统 (System)│    │   业务系统 (System)│    │   业务系统 (System)│
     │   电商平台 (CMDB)  │    │   (K8s上下文)     │    │   (告警上下文)    │
     └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
              │                      │                      │
    ┌─────────┼──────────┐          │                      │
    │         │          │          │                      │
┌───▼───┐ ┌──▼───┐ ┌───▼────┐  ┌──▼──────┐          ┌────▼─────┐
│ 服务   │ │ 服务  │ │运行时组件│  │运行时组件│          │ 服务      │
│订单业务│ │支付业务│ │MySQL57  │  │Oracle19C│  ...     │(Tracing) │
│(CMDB) │ │(CMDB) │ │(CMDB)  │  │(CMDB)   │          │          │
└───┬───┘ └──┬───┘ └───┬────┘  └──┬──────┘          └──────────┘
    │        │         │          │
    └────────┼─────────┼──────────┼──────────────────────────────┐
             │         │          │                              │
      ┌──────▼─────────▼──────────▼──────────┐    ┌──────────────▼──────────┐
      │        基础设施 (Infrastructure)       │    │   可观测性能力 (Capability)│
      │                                      │    │                          │
      │  ┌────────────────────────────┐      │    │  指标 ─→ MetricDataSource │
      │  │ Zabbix TaskResource (18)   │      │    │  日志 ─→ LogDataSource    │
      │  │  └─ cmdb_business_line     │      │    │  链路 ─→ TracingDataSource │
      │  │  └─ cmdb_ci_type          │      │    │  告警 ─→ Alert            │
      │  │  └─ Zabbix 实时状态        │      │    │  事件 ─→ EventRecord      │
      │  │  └─ DeviceMapping ←→ CI   │      │    │  Zabbix监控                │
      │  └────────────────────────────┘      │    │  CMDB                      │
      │                                      │    └───────────────────────────┘
      │  ┌────────────────────────────┐      │
      │  │ CMDB ConfigItem (主机类)    │      │
      │  │  └─ 无 Zabbix 映射 (12)    │      │    ┌──────────────────────────┐
      │  │  └─ business_line (传播)   │      │    │    数据源 (Datasource)     │
      │  └────────────────────────────┘      │    │                          │
      │                                      │    │  ZabbixDataSource         │
      │  ┌────────────────────────────┐      │    │  iTopDataSource           │
      │  │ K8s 节点 / Docker 环境     │      │    │  ...                     │
      │  └────────────────────────────┘      │    └──────────────────────────┘
      └─────────────────────────────────────┘
```

## 九、统一桥接策略

### 9.1 DeviceMapping：Zabbix ↔ CMDB 主桥

```
DeviceMapping (主桥)
  ├── zabbix_hostid ←→ Host.external_id ('zabbix:{hostid}')
  ├── zabbix_hostname ←→ Host.hostname / TaskResource.name
  ├── zabbix_ip       ←→ Host.ip_address
  └── config_item     ←→ ConfigItem (OneToOne)
```

**桥接能力**：
- IP 精确匹配 (match_method='ip_exact', confidence=1.0)
- 名称模糊匹配 (match_method='name_fuzzy', confidence=0.7)
- 人工确认保护 (is_verified=True 跳过自动修复)

### 9.2 业务线传播：CMDB 拓扑 → Zabbix

```
ApplicationSolution (business_line='电商平台')
  │
  ▼ (BFS 沿 CIRelation 双向)
  ├── DBServer (business_line='电商平台' [传播])
  ├── WebServer (business_line='电商平台' [传播])
  ├── Server (business_line='电商平台' [传播])
  │     │
  │     ▼ (IP 匹配 iTop CI)
  │     DeviceMapping → Zabbix TaskResource → cmdb_business_line='电商平台'
  │
  └── BusinessProcess (business_line='电商平台' [传播])
```

### 9.3 知识图谱统一节点命名规范

| 统一实体 | 当前多源节点 | 规范方案 |
|---------|-------------|---------|
| 业务系统 | system (上下文) + cmdb_system (CMDB) | 按名称去重：同名 system 合并 | 
| 服务 | service + cmdb_service | 按名称去重 |
| 运行时组件 | runtime_component + cmdb_component | 按 IP/名称合并 |
| 基础设施 | infratask_resource + cmdb_infra + infrak8s_host | DeviceMapping 去重，K8s 暂时独立 |

---

## 十、数据库 Schema 关联全景

```
ZabbixDataSource ────────────────────────────────────────────┐
  │ (post_save 信号级联)                                      │
  ├── Host (external_id='zabbix:{hostid}')                    │
  │     ├── TaskResource.host                                 │
  │     ├── Alert.host                                        │
  │     └── (post_save 信号) → ConfigItem (via cmdb/sync)     │
  │                                                           │
  ├── TaskResource (external_id='zabbix:{hostid}')            │
  │     └── TaskResourceGroup (code='zabbix-monitored')       │
  │                                                           │
  ├── MetricDataSource (tsdb_type='zabbix')                   │
  │                                                           │
  └── Alert (via upsert_alert_from_zabbix_problem)            │

iTopDataSource ─────────────────────────────────────────────┐
  │ (run_full_sync 同步)                                      │
  ├── CIType (ci_class_map)                                   │
  ├── ConfigItem (external_id='itop:{class}:{id}')            │
  │     ├── (post_save 信号) → Host (via cmdb/sync)           │
  │     └── zabbix_mapping ← OneToOne → DeviceMapping         │
  │                                                           │
  ├── CIRelation (source → target, relation_type)             │
  │                                                           │
  └── TransactionTicket (external_source='itop')              │

DeviceMapping ───────────────────────────────────────────────┐
  │ (双向桥接)                                                 │
  ├── zabbix_hostid ←→ Host.external_id                       │
  └── config_item  ←→ ConfigItem                              │
```

---

> **文档版本**：v1.0  
> **生成日期**：2026-07-09  
> **覆盖文件**：`backend/ops/models.py`, `backend/cmdb/models.py`, `backend/aiops/models.py`, `backend/aiops/knowledge_graph.py`, `backend/ops/zabbix_client.py`, `backend/ops/zabbix_alert_bridge.py`, `backend/ops/device_matcher.py`, `backend/cmdb/itop_sync.py`, `backend/eventwall/models.py`
