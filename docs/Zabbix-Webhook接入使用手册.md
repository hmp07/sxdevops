# SxDevOps Zabbix Webhook 接入使用手册

## 一、方案概述

SxDevOps 提供三条 Zabbix 告警接入路径，可根据运维场景灵活选择：

| 路径 | 方式 | 实时性 | Zabbix 端配置 | 适用场景 |
|------|------|--------|--------------|---------|
| **路径 A — 平台轮询** | `python manage.py poll_zabbix_alerts` | 分钟级（需 cron） | 无需 | 已有数据源，不想改 Zabbix 配置 |
| **路径 B — Webhook 推送** | Zabbix Action → HTTP POST | 秒级实时 | 需要 | 生产推荐，告警秒级送达 |
| **路径 C — AI 触发** | AI 智能助手查询时静默同步 | 按需 | 无需 | AI 排障场景自动补充 |

**本手册专讲路径 B（Webhook 推送）**，这是推荐的生产方式——Zabbix 触发告警后，通过 Webhook 实时推送到 SxDevOps，经过完整的告警流水线（标准化 → 指纹去重 → 抑制 → 升级 → 通知分发），最终呈现在告警中心。

```
Zabbix Server                        SxDevOps 平台
┌────────────────┐    HTTP POST      ┌─────────────────────────────┐
│ 触发器 → Action │ ───────────────→ │ /api/alerts/webhooks/        │
│   Media Type   │                   │   zabbix/<token>/            │
│   (Webhook)    │                   │                              │
└────────────────┘                   │ → _normalize_zabbix()       │
                                     │ → upsert_alert()            │
                                     │ → apply_alert_suppression() │
                                     │ → dispatch_notifications()  │
                                     │ → 告警中心 / 通知            │
                                     └─────────────────────────────┘
```

---

## 二、平台端配置

### 2.1 创建 Zabbix 告警接入源

1. 登录 SxDevOps，进入 **告警中心**（侧边栏：可观测性 → 告警中心）
2. 点击 **"告警接入源"** Tab
3. 点击 **"新增接入源"**

**表单填写：**

| 字段 | 说明 | 示例 |
|------|------|------|
| 接入源名称 | 自定义名称，用于识别 | `生产环境 Zabbix` |
| 接入类型 | 选择 **Zabbix** | — |
| 标签（可选） | JSON 键值对，所有通过此接入源的告警自动附上 | `{"env":"prod","team":"ops"}` |
| 说明 | 备注信息 | `公司主 Zabbix Server` |

4. 点击 **保存**，系统自动生成唯一接入令牌（Token）
5. 保存后，在接入源列表中找到刚创建的记录，复制 **Webhook URL**，格式为：

```
https://<你的平台地址>/api/alerts/webhooks/zabbix/<token>/
```

> **说明**：`<token>` 是 32 位十六进制字符串（UUID4），由系统自动生成，每条接入源唯一。

### 2.2 接入令牌传递方式（三选一）

Zabbix 发送 Webhook 时，可以通过以下任一方式传递令牌：

| 方式 | 示例 |
|------|------|
| **URL 路径（推荐）** | `POST /api/alerts/webhooks/zabbix/a1b2c3d4e5f6.../` |
| **查询参数** | `POST /api/alerts/webhooks/zabbix/?token=a1b2c3d4e5f6...` |
| **HTTP Header** | `X-Alert-Token: a1b2c3d4e5f6...` 或 `X-Sxdevops-Token: a1b2c3d4e5f6...` |

> **注意**：令牌必须对应一个已启用的 Zabbix 接入源。令牌无效或接入源被禁用时，请求返回 `403 Forbidden`。

### 2.3 验证接入源状态

接入源列表的 **"最近接收时间"** 列显示最后一次成功接收 Webhook 的时间。如果长时间无更新，说明 Zabbix 端未正常推送。

---

## 三、Zabbix 端配置

Zabbix 端需要两步配置：**告警媒介类型（Media Type）** 和 **动作（Action）**。

### 3.1 创建告警媒介类型（Media Type）

在 Zabbix 管理界面：**Alerts → Media types → Create media type**

| 配置项 | 值 |
|--------|-----|
| Name | `SxDevOps Webhook` |
| Type | **Webhook** |
| Parameters | 见下方说明 |
| Script | 粘贴下方 JavaScript 脚本 |
| Timeout | `30s` |

#### Parameters（参数列表）

添加以下参数（Name 列填入，Value 留空由 Zabbix Action 传入）：

| Name | 说明 |
|------|------|
| `alert_subject` | 告警标题 |
| `alert_message` | 告警详情 |
| `alert_severity` | 严重级别（数字 0-5，`{EVENT.NSEVERITY}`） |
| `alert_status` | 告警状态（PROBLEM / OK） |
| `trigger_id` | 触发器 ID |
| `event_id` | 事件 ID |
| `host_name` | 主机名 |
| `host_ip` | 主机 IP |
| `hostid` | 主机 ID（`{HOST.ID}`，用于平台主机关联） |
| `trigger_name` | 触发器名称 |
| `trigger_description` | 触发器描述 |
| `event_time` | 事件时间（点分格式 `YYYY.MM.DD hh:mm:ss`，平台自动解析） |
| `event_recovery_time` | 恢复时间（同上格式） |
| `host_group` | 主机组名称（`{TRIGGER.HOSTGROUP.NAME}`） |
| `event_tags` | 事件标签（`name: value` 冒号格式，逗号分隔） |
| `webhook_url` | SxDevOps Webhook URL |

### 3.2 Webhook JavaScript 脚本

将以下脚本粘贴到 Zabbix Media Type 的 Script 框中：

```javascript
try {
    var params = JSON.parse(value),
        webhook_url = params.webhook_url,
        problem = {},
        data = {};

    if (!webhook_url) {
        throw 'Missing webhook_url parameter.';
    }

    // 构建告警事件
    problem.trigger_name = params.trigger_name || params.alert_subject;
    problem.message = params.alert_message || params.trigger_description;
    problem.severity = params.alert_severity;
    problem.status = params.alert_status;
    problem.triggerid = params.trigger_id;
    problem.eventid = params.event_id;
    problem.host = params.host_name;
    problem.host_ip = params.host_ip;
    problem.hostid = params.hostid;
    problem.hostgroup = params.host_group;
    problem.event_time = params.event_time;
    problem.recovery_time = params.event_recovery_time;
    problem.tags = params.event_tags || '';

    // 包装为标准格式
    data.alerts = [problem];

    // 发送 HTTP POST
    var request = new HttpRequest();
    request.addHeader('Content-Type: application/json');

    var response = request.post(webhook_url, JSON.stringify(data));

    if (request.getStatus() < 200 || request.getStatus() >= 300) {
        throw 'HTTP ' + request.getStatus() + ': ' + response;
    }

    return 'OK: ' + response;
} catch (err) {
    Zabbix.log(4, '[SxDevOps Webhook] ' + err);
    throw 'SxDevOps Webhook Error: ' + err;
}
```

### 3.3 创建动作（Action）

在 Zabbix 管理界面：**Alerts → Actions → Create action**

#### 3.3.1 动作（Actions）Tab

| 配置项 | 值 |
|--------|-----|
| Name | `推送到 SxDevOps` |
| Conditions | 按需添加（如：`Trigger severity >= Warning`） |
| Enabled | 勾选 |

#### 3.3.2 操作（Operations）Tab

点击 **Add** 添加操作：

| 配置项 | 值 |
|--------|-----|
| Send to user groups | 选择接收告警的用户组（通常选全部） |
| Send to users | 选择接收告警的用户（通常选 Admin） |
| Send only to | **SxDevOps Webhook**（刚才创建的媒体类型） |
| Custom message | 勾选 |

**Custom message 配置（按以下方式对应参数）：**

| 参数 | 值 |
|------|-----|
| `alert_subject` | `{ALERT.SUBJECT}` |
| `alert_message` | `{ALERT.MESSAGE}` |
| `alert_severity` | `{EVENT.NSEVERITY}` |
| `alert_status` | `{EVENT.STATUS}` |
| `trigger_id` | `{TRIGGER.ID}` |
| `event_id` | `{EVENT.ID}` |
| `host_name` | `{HOST.NAME}` |
| `host_ip` | `{HOST.IP}` |
| `hostid` | `{HOST.ID}` |
| `trigger_name` | `{TRIGGER.NAME}` |
| `trigger_description` | `{TRIGGER.DESCRIPTION}` |
| `event_time` | `{EVENT.TIME}` |
| `event_recovery_time` | `{EVENT.RECOVERY.TIME}` |
| `host_group` | `{TRIGGER.HOSTGROUP.NAME}` |
| `event_tags` | `{EVENT.TAGS}` |
| `webhook_url` | `https://<你的平台>/api/alerts/webhooks/zabbix/<token>/` |

> **宏选择说明**（对照 Zabbix 官方宏文档）：
> - `{EVENT.NSEVERITY}` 输出**数字** 0-5（平台按数字映射级别）；`{EVENT.SEVERITY}` 输出本地化文本（中文环境如"一般严重"），不推荐。
> - `{EVENT.TIME}`/`{EVENT.RECOVERY.TIME}` 输出点分格式时间（`YYYY.MM.DD hh:mm:ss`），**不是 Unix 时间戳**——平台已支持自动解析，无需转换。
> - `{EVENT.TAGS}` 输出逗号分隔的 `name: value` 冒号格式，平台已兼容。
> - `{TRIGGER.HOSTGROUP.NAME}` 输出主机组**名称**（`{HOSTGROUP.ID}` 是数字 ID，勿用）。
> - webhook 媒体类型参数值需"单个宏填满整个字段"，本表均为单宏，符合要求。

#### 3.3.3 恢复操作（Recovery operations）Tab

点击 **Add**，配置与 Operations 相同，Zabbix 会自动将 `{EVENT.STATUS}` 设为 `OK`，`{EVENT.RECOVERY.TIME}` 填入恢复时间（点分格式）。平台识别 `status="OK"` 后会将告警标记为"已恢复"。

---

## 四、告警字段映射参考

### 4.1 平台支持的 JSON 字段优先级

当 Zabbix Webhook 推送 JSON 数据到 SxDevOps 时，平台按以下优先级解析每个字段：

| 平台字段 | 优先级（从高到低） |
|----------|-------------------|
| `title` | `trigger_name` → `event_name` → `subject` → `name` |
| `message` | `message` → `body` → `trigger_description` |
| `source` | `source` → 默认 `Zabbix` |
| `resource`（主机名）| `host` → `hostname` → `host_name` → `hosts[0].host` → 兜底 `host_ip` |
| `external_id` | `eventid` → `event_id` → `triggerid` |
| `fingerprint` | `triggerid` → `trigger_id` → `eventid` |
| `group_key` | `hostgroup` → `host_group` → `tags.group` |
| `service` | `tags.app` → `tags.job_name` → `tags.service` → `application` |
| `metric_name` | `metric` → `item_name` → `key` |
| `starts_at` | `event_time` → `clock` → `time`（支持 Unix 时间戳 / ISO / 点分格式） |
| `ends_at` | `recovery_time` → `r_clock`（同上） |
| `labels` | `tags`（支持 `key=value` 与 `name: value` 冒号双格式、逗号分隔，或 JSON 对象）；`hostid` 自动写入 `zabbix_hostid` 用于主机关联 |

### 4.2 严重级别映射

| Zabbix 严重级别 | 数字值 | 平台级别 |
|----------------|--------|---------|
| 灾难 / Disaster | 5 | **严重** (critical) |
| 严重 / High | 4 | **严重** (critical) |
| 一般严重 / Average | 3 | **警告** (warning) |
| 警告 / Warning | 2 | **警告** (warning) |
| 信息 / Information | 1 | 信息 (info) |
| 未分类 / Not classified | 0 | 信息 (info) |

> 也支持文本值：`"critical"`, `"high"`, `"disaster"`, `"fatal"` → critical；`"warning"`, `"average"`, `"medium"` → warning

### 4.3 状态映射

| Zabbix 状态 | 平台状态 |
|------------|---------|
| `PROBLEM` / `1` / `"firing"` / `"active"` / `"alert"` | **活跃** (active) |
| `OK` / `0` / `"resolved"` / `"recovered"` / `"closed"` | **已恢复** (resolved) |

### 4.4 Zabbix 宏变量对照表

在 Zabbix Media Type 的 Custom message 中使用的宏变量与 JSON 字段对应关系：

| Zabbix 宏变量 | 对应 JSON 字段 | 说明 |
|--------------|---------------|------|
| `{ALERT.SUBJECT}` | `alert_subject` | 告警标题 |
| `{ALERT.MESSAGE}` | `alert_message` | 告警详情 |
| `{TRIGGER.NAME}` | `trigger_name` | 触发器名称 |
| `{TRIGGER.ID}` | `trigger_id` | 触发器 ID |
| `{TRIGGER.DESCRIPTION}` | `trigger_description` | 触发器描述 |
| `{EVENT.ID}` | `event_id` | 事件 ID |
| `{EVENT.SEVERITY}` | `alert_severity` | 事件严重级别（数字） |
| `{EVENT.STATUS}` | `alert_status` | 事件状态（PROBLEM/OK） |
| `{EVENT.TIME}` | `event_time` | 事件时间 |
| `{EVENT.RECOVERY.TIME}` | `event_recovery_time` | 恢复时间 |
| `{EVENT.TAGS}` | `event_tags` | 事件标签 |
| `{HOST.NAME}` | `host_name` | 主机名 |
| `{HOST.IP}` | `host_ip` | 主机 IP |
| `{HOSTGROUP.ID}` | `host_group` | 主机组 |

---

## 五、完整 Payload 示例

### 5.1 触发告警（PROBLEM）

Zabbix 通过 Webhook 发送的 JSON 负载：

```json
{
  "alerts": [
    {
      "trigger_name": "磁盘使用率过高",
      "message": "/data 分区使用率超过 85%，当前值 92.3%",
      "severity": "4",
      "status": "PROBLEM",
      "source": "Zabbix",
      "triggerid": "28731",
      "eventid": "1058294",
      "host": "db-prod-01",
      "host_ip": "10.10.1.20",
      "hostid": "10107",
      "hostgroup": "database-prod",
      "event_time": "2026.09.18 10:00:00",
      "tags": "app: order-db, env: prod, cluster: prod-cluster, team: dba",
      "trigger_description": "当 /data 分区使用率超过 85% 时触发",
      "url": "https://wiki.example.com/runbooks/disk-full"
    }
  ]
}
```

**平台处理结果：**

| 字段 | 解析值 |
|------|--------|
| 标题 | 磁盘使用率过高 |
| 级别 | **严重** (severity=4 → critical) |
| 状态 | 活跃 |
| 来源 | Zabbix |
| 主机 | db-prod-01 |
| 指纹 | `sha256('zabbix:28731')` 的 64 位十六进制哈希（以 triggerid 为稳定键；轮询兜底路径与推送路径共用同一算法，同一告警双路径不重复） |
| 环境 | prod |
| 集群 | prod-cluster |
| 服务 | order-db |
| 业务线 | dba |
| Runbook | https://wiki.example.com/runbooks/disk-full |

### 5.2 恢复告警（OK）

```json
{
  "alerts": [
    {
      "trigger_name": "磁盘使用率过高",
      "message": "/data 分区使用率已恢复到 72.1%",
      "severity": "0",
      "status": "OK",
      "source": "Zabbix",
      "triggerid": "28731",
      "eventid": "1058456",
      "host": "db-prod-01",
      "hostid": "10107",
      "hostgroup": "database-prod",
      "event_time": "2026.09.18 10:00:00",
      "recovery_time": "2026.09.18 11:00:00",
      "tags": "app: order-db, env: prod"
    }
  ]
}
```

平台收到 `status=OK` → 告警状态变为"已恢复"，`ends_at` 自动填入恢复时间（`recovery_time` 解析），且原 PROBLEM 的 `external_id` 保持不变（不会被恢复事件 ID 覆盖）。

---

## 六、最小可用 Payload

如果只需要最基本的告警推送，Zabbix 端最少只需要提供以下字段：

```json
{
  "trigger_name": "CPU 负载过高",
  "severity": "high",
  "host": "web-server-01"
}
```

其他字段（环境、服务、集群等）可在平台端接入源的 **"默认标签"** 中统一配置，避免了在每个 Zabbix 触发器上重复填写。

---

## 七、验证与排障

### 7.1 测试接入

1. 在平台端：告警中心 → 告警接入源 → 确认接入源状态为**启用**
2. 用 `curl` 模拟 Zabbix 发送测试告警：

```bash
curl -X POST \
  https://<平台地址>/api/alerts/webhooks/zabbix/<token>/ \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "trigger_name": "测试告警-手动触发",
      "message": "这是一条手动测试告警",
      "severity": "warning",
      "status": "PROBLEM",
      "host": "test-host",
      "hostgroup": "test-group",
      "event_time": 1778992200,
      "tags": "env=test"
    }]
  }'
```

成功响应（HTTP 202）：
```json
{
  "success": true,
  "provider": "zabbix",
  "created": 1,
  "updated": 0,
  "alert_ids": [120]
}
```

3. 刷新页面告警中心 → 告警事件 → 来源筛选选择"Zabbix" → 应看到测试告警

### 7.2 常见问题

| 问题 | 可能原因 | 检查方法 |
|------|---------|---------|
| 403 Forbidden | 令牌无效或接入源被禁用 | 检查接入源是否启用，令牌是否匹配 |
| Zabbix 侧报超时 | 网络不通或平台地址错误 | 从 Zabbix 服务器 `curl` 测试连通性 |
| 告警未出现在平台 | Payload 格式不匹配 | 用 curl 发送相同的 JSON 测试 |
| 状态不更新 | `eventid` 或 `triggerid` 不一致 | 确保 PROBLEM 和 OK 使用相同的指纹字段 |
| 平台中文字段显示为乱码 | Content-Type 未设 charset | 确保 `Content-Type: application/json; charset=utf-8` |

### 7.3 查看接入源最近接收时间

告警中心 → 告警接入源 → 表格中的"最近接收时间"列。该字段在每次成功接收 Webhook 后自动更新。

---

## 八、总结

| 对比维度 | 平台轮询（路径 A） | **Webhook 推送（路径 B）** |
|---------|-------------------|--------------------------|
| 实时性 | 取决于 cron 频率（分钟级） | **秒级实时** |
| Zabbix 端配置 | 无需 | 需要配置 Media Type + Action |
| 网络要求 | 平台需能访问 Zabbix API | **Zabbix 需能访问平台** |
| 告警流水线 | 通过桥接函数 | **完整流水线（抑制+升级+通知）** |
| 运维复杂度 | 需要维护 cron 任务 | 一次性配置 Zabbix |

**推荐生产环境使用 Webhook 推送（路径 B）作为主要接入方式**，同时保留平台轮询（路径 A）作为备用兜底方案。

## 九、升级说明（存量 Zabbix 配置迁移）

若此前按旧版手册配置过 Media Type 与 Action，请更新以下参数（平台后端对旧格式保持兼容，新旧配置均可正常工作，但新配置才能获得完整字段）：

| 参数 | 旧值 | 新值 | 原因 |
|------|------|------|------|
| `alert_severity` | `{EVENT.SEVERITY}` | `{EVENT.NSEVERITY}` | 旧宏输出本地化文本，中文环境"一般严重"会被平台误判为 info |
| `host_group` | `{HOSTGROUP.ID}` | `{TRIGGER.HOSTGROUP.NAME}` | 旧宏输出数字 ID，平台按名字使用 |
| `hostid` | 无 | `{HOST.ID}` | 新增：推送路径与轮询路径一致地按主机 ID 精确关联平台主机 |
| `event_time`/`event_recovery_time` | 说明误写为 Unix 时间戳 | 点分格式（宏不变） | 平台已支持自动解析点分格式，无需处理 |

另外：`{EVENT.TAGS}` 为 `name: value` 冒号格式，平台已兼容；`external_id` 在恢复事件到达时保留原 PROBLEM 事件 ID（外部回查 Zabbix 更准确）。
