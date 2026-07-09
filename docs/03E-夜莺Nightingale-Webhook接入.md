# SxDevOps 夜莺 Nightingale Webhook 接入

## 一、概述

夜莺（Nightingale）是国产开源监控系统。SxDevOps 原生支持夜莺告警事件 Webhook 格式。

**前置条件：**
- 夜莺监控系统已部署
- 平台对夜莺服务器网络可达

## 二、平台端配置

1. 告警中心 → **告警接入源** Tab → 新增接入源
2. 接入类型选择 **夜莺**
3. 保存后获取 Webhook URL：

```
https://<平台地址>/api/alerts/webhooks/nightingale/<token>/
```

## 三、夜莺端配置

### 3.1 配置通知渠道

在夜莺管理界面：**告警管理 → 通知渠道 → 新增**

| 配置项 | 值 |
|--------|-----|
| 名称 | `SxDevOps` |
| 渠道类型 | **Webhook** |
| URL | `https://<平台地址>/api/alerts/webhooks/nightingale/<token>/` |
| 请求头 | `Content-Type: application/json` |
| 是否启用 | 是 |

### 3.2 配置告警规则的通知

在夜莺告警规则中，将通知渠道设置为刚创建的 `SxDevOps`。

## 四、Payload 格式

夜莺发送的 JSON 由平台 `_normalize_nightingale()` 处理。支持两种格式：
- 单事件：`{"events": [...]}` 或 `{"alerts": [...]}`
- 嵌套事件：`events` 包含 `events` 子数组

字段映射：

| 平台字段 | 来源优先级 |
|----------|-----------|
| `title` | `rule_name` → `title` → `annotations.summary` |
| `level` | `severity`（1=critical, 2=warning, 3=info） |
| `status` | `is_recovered` 为 true → resolved，否则 `status` → `event_status` |
| `source` | `cluster` → `datasource_name` → `cate` |
| `external_id` | `id` → `event_id` → `hash` |
| `fingerprint` | `hash` |
| `resource` | `target_ident` → `target` → `labels.ident` |
| `service` | `labels.app` → `rule_prod` |
| `labels` | `tags_map`（JSON）→ `tags`（逗号分隔 key=value） |

### 示例 Payload

```json
{
  "events": [
    {
      "id": 18573,
      "rule_name": "CPU 使用率过高",
      "severity": 2,
      "status": "active",
      "cluster": "prod-cluster",
      "target_ident": "10.0.1.15",
      "tags_map": {
        "app": "api-gateway",
        "env": "prod"
      },
      "trigger_time": 1779000000,
      "rule_note": "CPU 使用率超过 80% 持续 5 分钟",
      "is_recovered": false
    }
  ]
}
```

## 五、严重级别映射

| 夜莺 severity | 平台级别 |
|--------------|---------|
| 1 | **严重** (critical) |
| 2 | **警告** (warning) |
| 3 | 信息 (info) |

## 六、验证

```bash
curl -X POST \
  https://<平台>/api/alerts/webhooks/nightingale/<token>/ \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "id": 99999,
      "rule_name": "测试夜莺告警",
      "severity": 2,
      "status": "active",
      "target_ident": "test-host",
      "trigger_time": 1779000000,
      "is_recovered": false
    }]
  }'
```
