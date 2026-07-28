# Prometheus 兼容指标数据源接入指南

## 一、架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                    前端 (Vue / Element Plus)                   │
│  指标查询页 / Grafana 面板 / 知识图谱指标选择器                   │
└──────────────────────┬───────────────────────────────────────┘
                       │ REST API
┌──────────────────────┴───────────────────────────────────────┐
│                    后端 API 层 (observability_views.py)        │
│                                                              │
│  POST /metrics/query/         即时查询 / 范围查询               │
│  GET  /metrics/series-names/  指标名自动补全                    │
│  POST /grafana/promql/query/  Grafana 代理查询                 │
│  POST /grafana/panel/query/   Grafana 面板提取查询              │
│  CRUD /metric/datasources/    数据源管理                        │
└──────────────────────┬───────────────────────────────────────┘
                       │ 两条查询路径
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────────┐
│ 路径 A: 直连      │    │ 路径 B: Grafana 代理   │
│ MetricDataSource  │    │ OBSERVABILITY_CONFIG │
│ (DB 配置)         │    │ (settings.py)        │
│                   │    │                      │
│ config.query_url  │    │ Grafana URL           │
│ config.headers    │    │ → /api/datasources/   │
│ config.auth_type  │    │   proxy/{id}/         │
└────────┬──────────┘    └──────────┬───────────┘
         │                          │
         ▼                          ▼
┌──────────────────────────────────────────────────┐
│              Prometheus HTTP API                  │
│  GET /api/v1/query?query={PromQL}                │
│  GET /api/v1/query_range?query={PromQL}&...      │
│  GET /api/v1/label/{name}/values                 │
└──────────────────────────────────────────────────┘
```

## 二、MetricDataSource 模型

**文件**：`backend/ops/models.py`，第 1262-1291 行

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | CharField(128) 唯一 | 指标数据源名称 |
| `provider` | CharField(32) | 仅 `'prometheus'` → `'Prometheus Like'` |
| `description` | CharField(255) | 描述信息 |
| `environment` | CharField(32) | 环境标识，用于知识环境过滤和数据源选择 |
| `cluster_name` | CharField(128) | 集群标识 |
| `tsdb_type` | CharField(32) | 默认 `'prometheus'`；特殊值 `'zabbix'` 为路由标记 |
| `config` | JSONField | 连接配置（URL、认证、headers、timeout） |
| `is_enabled` | BooleanField | 默认 True |
| `is_default` | BooleanField | 默认 False，用于默认数据源选择 |

### config JSON 结构

```json
{
  "query_url": "http://prometheus.example.com:9090",
  "addr": "",
  "internal_addr": "",
  "auth_type": "bearer",
  "bearer_token": "your-token-here",
  "token": "",
  "api_key": "",
  "username": "",
  "password": "",
  "headers": {"X-Scope-OrgID": "tenant1"},
  "tls_skip_verify": false,
  "insecure_skip_verify": false,
  "timeout": 15
}
```

支持的认证方式：
- **Bearer Token**：`auth_type: "bearer"` + `bearer_token`
- **Basic Auth**：`auth_type: "basic"` + `username` + `password`
- **API Key**：通过自定义 `headers` 传递
- **无认证**：`auth_type: "none"` 或不设置

### 数据源选择逻辑

`_select_metric_datasource()` 函数（`observability_views.py` 第 650 行）：

1. 如果提供了 `metric_datasource_id` → 按 ID 精确查找
2. 如果提供了 `environment` → 优先该环境的默认数据源 → 该环境的任意数据源
3. 否则 → 默认数据源（`is_default=True` 且 `environment` 为空）→ 任意已启用数据源

## 三、API 端点

### 3.1 指标数据源 CRUD

**路由**：`/api/observability/metric/datasources/`

| 方法 | URL | 功能 | 权限 |
|------|-----|------|------|
| GET | `/` | 列出所有数据源 | `ops.metric.datasource.view` |
| POST | `/` | 创建数据源 | `ops.metric.datasource.manage` |
| GET | `/{id}/` | 查看详情 | `ops.metric.datasource.view` |
| PUT | `/{id}/` | 更新数据源 | `ops.metric.datasource.manage` |
| PATCH | `/{id}/` | 部分更新 | `ops.metric.datasource.manage` |
| DELETE | `/{id}/` | 删除数据源 | `ops.metric.datasource.manage` |
| POST | `/{id}/test_connection/` | 测试连接 | `ops.metric.datasource.manage` |

**过滤参数**（列表接口）：`provider`, `environment`, `is_enabled`

### 3.2 指标查询端点

**文件**：`backend/ops/observability_views.py`

#### POST `/api/observability/metrics/query/` — PromQL 查询

**权限**：`ops.metric.query`

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` / `promql` | string | PromQL 查询表达式，最大 2000 字符 |
| `range` / `range_query` / `query_type` | string | `"1"` 或 `"true"` 表示范围查询 |
| `start` / `start_time` | datetime/timestamp | 开始时间 |
| `end` / `end_time` | datetime/timestamp | 结束时间 |
| `step` | string | 步长，如 `"60s"`, `"5m"`, `"1h"` |
| `metric_datasource_id` / `datasource_id` | int | 指定数据源 ID |
| `environment` | string | 按环境选择数据源 |

**响应格式**：
```json
{
  "query": "up{job=\"node\"}",
  "range": false,
  "source": "metric_datasource",
  "description": "My Prometheus",
  "metric_datasource": {"id": 1, "name": "My Prometheus", "provider": "prometheus"},
  "resultType": "vector",
  "result": [
    {"metric": {"__name__": "up", "instance": "localhost:9090", "job": "node"}, "value": [1689000000, "1"]}
  ],
  "sample": [{"metric": {"__name__": "up", "instance": "localhost:9090"}, "value": "1"}],
  "series_count": 1
}
```

#### GET `/api/observability/metrics/series-names/` — 指标名自动补全

**权限**：`ops.metric.query`

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` / `keyword` | string | 搜索关键词 |
| `limit` | int | 返回数量，默认 80，最大 200 |
| `metric_datasource_id` | int | 指定数据源 |
| `environment` | string | 按环境选择数据源 |

#### POST `/api/observability/grafana/promql/query/` — Grafana 代理查询

**权限**：`ops.grafana.view`

与 `metrics_promql_query` 参数相同，额外支持：
- `datasource_uid`：Grafana 数据源 UID
- `datasource_id`：Grafana 数据源 ID
- `grafana_url`：Grafana 地址

#### POST `/api/observability/grafana/panel/query/` — Grafana 面板查询

**权限**：`ops.grafana.view`

从 Grafana 面板中提取 PromQL 表达式并执行范围查询。支持模板变量渲染（`$var` 和 `${var}` 语法）。

## 四、查询路径详解

### 路径 A：MetricDataSource 直连

**入口函数**：`_resolve_metric_datasource_client()`（第 677 行）

**流程**：
1. 通过 `_select_metric_datasource()` 从 DB 中选择数据源
2. 从 `config` JSON 中读取 `query_url`（支持多 key 回退：`query_url` → `addr` → `prometheus.addr` → `internal_addr` → `prometheus.internal_addr`）
3. 构建 HTTP headers（Bearer token / Basic auth / 自定义 headers）
4. 设置 TLS 验证和 timeout
5. 返回统一 client dict

**使用的端点**：`metrics_promql_query`、`metrics_series_names`

### 路径 B：Grafana 代理

**入口函数**：`_resolve_prometheus_client()`（第 726 行）

**流程**：
1. 从 `settings.OBSERVABILITY_CONFIG.prometheus` 读取 Grafana 配置
2. 如果没有直接配置 `query_url`，则：
   - 获取 Grafana URL
   - 通过 Grafana API 发现数据源：`GET {grafana_url}/api/datasources/uid/{uid}`
   - 构造代理 URL：`{grafana_url}/api/datasources/proxy/{id}`
3. 使用 Grafana API Token 认证

**使用的端点**：`grafana_promql_query`、`grafana_panel_query`

### 核心 HTTP 查询函数

| 函数 | Prometheus API | 用途 |
|------|---------------|------|
| `_prometheus_query()` | `GET /api/v1/query` | 即时查询 |
| `_prometheus_query_range()` | `GET /api/v1/query_range` | 范围查询 |
| `_prometheus_label_values()` | `GET /api/v1/label/{name}/values` | 标签值查询 |

> **注意**：项目中**没有独立的 PrometheusClient 类**。所有 PromQL 查询通过 `requests.get()` 直接调用 HTTP API。

## 五、认证配置详解

### Bearer Token

```json
{
  "query_url": "http://prometheus:9090",
  "auth_type": "bearer",
  "bearer_token": "my-secret-token"
}
```

→ 生成 HTTP Header：`Authorization: Bearer my-secret-token`

### Basic Auth

```json
{
  "query_url": "http://prometheus:9090",
  "auth_type": "basic",
  "username": "admin",
  "password": "secret"
}
```

→ 使用 `requests` 的 `auth=(username, password)` 参数

### 自定义 Headers

```json
{
  "query_url": "http://prometheus:9090",
  "headers": {
    "X-Scope-OrgID": "tenant-01",
    "X-Custom-Auth": "value"
  }
}
```

→ 直接添加到请求 headers 中

### TLS 跳过验证

```json
{
  "query_url": "https://prometheus:9090",
  "tls_skip_verify": true
}
```

## 六、PromQL 查询基础

### 即时查询 (Instant Query)

查询某个时间点的瞬时值：

```promql
# 查询所有 up 指标
up

# 过滤标签
up{job="node", instance="localhost:9090"}

# 计算 5 分钟内的请求速率
rate(http_requests_total{job="api"}[5m])

# 聚合
sum(rate(http_requests_total[5m])) by (service)
```

API 调用：`GET /api/v1/query?query={PromQL}&time={timestamp}`

### 范围查询 (Range Query)

查询时间范围内的序列数据：

```promql
# 过去 1 小时的 CPU 使用率，每 60 秒一个点
rate(node_cpu_seconds_total{mode!="idle"}[5m])
```

API 调用：`GET /api/v1/query_range?query={PromQL}&start={ts}&end={ts}&step=60s`

### 标签值查询

查询指定标签的所有可能值：

```
GET /api/v1/label/__name__/values          # 所有指标名
GET /api/v1/label/job/values               # job 标签的所有值
GET /api/v1/label/__name__/values?match[]=up  # 匹配 up 的指标
```

## 七、Prometheus 兼容性

SxDevOps 的 `provider='prometheus'` + `PROVIDER_CHOICES = [('prometheus', 'Prometheus Like')]` 明确表达了兼容性定位：**任何实现 Prometheus HTTP API 的时序数据库都可以接入**。

兼容的时序数据库（非详尽列表）：
- **Prometheus** — 原生支持
- **Thanos** — 完全兼容 Prometheus API
- **VictoriaMetrics** — 兼容 Prometheus query API
- **Cortex** — 兼容 Prometheus API
- **Mimir** — Grafana 出品的 Prometheus 兼容存储
- **Grafana Agent** — 通过 Grafana 代理路径支持
- **阿里云 Prometheus** — 兼容 API + 自定义认证

## 八、知识图谱集成

MetricDataSource 在知识图谱中以 `kind='datasource'` 节点形式出现：

```
capability:metrics
    │ (capability_datasource: "接入指标源")
    ▼
metric_ds:{id}  ← MetricDataSource 记录
    │ (environment_observability: "关联指标源")
    ▼
environment:{name}
```

知识环境配置中的 `metric_datasource_ids` 字段决定了哪些指标数据源在知识图谱中可见。

## 九、Zabbix 指标路由标记

当 Zabbix 数据源被保存时（`ops/models.py` 第 1816-1828 行），会自动创建一个特殊的 MetricDataSource：

```python
MetricDataSource.objects.update_or_create(
    name=f'Zabbix - {instance.name}',
    defaults={
        'tsdb_type': 'zabbix',
        'provider': 'prometheus',
        'is_enabled': True,
    },
)
```

- `tsdb_type='zabbix'` 是一个**路由标记**，使其在知识图谱指标选择器中可见
- 它**不提供 PromQL 查询能力**——实际的 Zabbix 数据通过 `zabbix_views.py` 中的独立端点查询
- 目的：让用户知道该环境中存在 Zabbix 监控数据，可以在知识图谱中统一管理

## 十、配置环境变量

**文件**：`backend/sxdevops/settings.py`，第 511-562 行

```bash
# Prometheus 直连
PROMETHEUS_ENABLED=1
PROMETHEUS_QUERY_URL=http://prometheus:9090
PROMETHEUS_QUERY_TIMEOUT=6

# Grafana 代理
PROMETHEUS_GRAFANA_URL=http://grafana:3000
PROMETHEUS_GRAFANA_DATASOURCE_UID=prometheus-infra
PROMETHEUS_GRAFANA_DATASOURCE_ID=
PROMETHEUS_GRAFANA_API_TOKEN=
PROMETHEUS_INFERRED_GRAFANA_PORT=30300

# Grafana 独立配置
GRAFANA_ENABLED=1
GRAFANA_URL=http://grafana:3000
GRAFANA_DEFAULT_PATH=
```

---

> **文档版本**：v2.0
> **生成日期**：2026-07-09
> **覆盖文件**：`backend/ops/models.py`, `backend/ops/observability_views.py`, `backend/ops/serializers.py`, `backend/ops/urls.py`, `backend/sxdevops/settings.py`, `backend/aiops/knowledge_graph.py`
