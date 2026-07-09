# SxDevOps Prometheus Alertmanager Webhook 接入

## 一、概述

Prometheus Alertmanager 是云原生监控告警的事实标准。SxDevOps 原生支持 Alertmanager Webhook 格式，可直接接收告警并走完整流水线。

**前置条件：**
- Prometheus + Alertmanager 已部署运行
- 平台对 Alertmanager 网络可达

## 二、平台端配置

1. 告警中心 → **告警接入源** Tab → 新增接入源
2. 接入类型选择 **Prometheus Alertmanager**
3. 保存后获取 Webhook URL：

```
https://<平台地址>/api/alerts/webhooks/prometheus/<token>/
```

> 令牌也可通过 `?token=` 查询参数或 `X-Alert-Token` 请求头传递。

## 三、Alertmanager 端配置

### 3.1 配置 Webhook Receiver

编辑 `alertmanager.yml`：

```yaml
route:
  receiver: 'sxdevops'
  # 可选：按标签分组路由
  routes:
    - match:
        severity: critical
      receiver: 'sxdevops-critical'
      continue: true

receivers:
  - name: 'sxdevops'
    webhook_configs:
      - url: 'https://<平台地址>/api/alerts/webhooks/prometheus/<token>/'
        send_resolved: true  # 恢复通知也发送
```

### 3.2 重载 Alertmanager

```bash
# 检查配置
amtool check-config alertmanager.yml

# 重载（发送 SIGHUP 或调用 API）
curl -X POST http://localhost:9093/-/reload
```

## 四、Payload 格式

Alertmanager 发送的 Webhook 格式由平台 `_normalize_prometheus()` 处理，字段映射：

| 平台字段 | 来源优先级 |
|----------|-----------|
| `title` | `annotations.summary` → `labels.alertname` → `title` |
| `message` | `annotations.description` → `annotations.message` → `title` |
| `level` | `labels.severity`（critical/warning/info） |
| `status` | `status`（firing → active, resolved → resolved） |
| `source` | `labels.job` → `labels.alertname` → `Alertmanager` |
| `external_id` | `fingerprint` → `generatorURL` |
| `resource` | `labels.instance` → `labels.pod` → `labels.node` |
| `service` | `labels.app` → `labels.job_name` → `labels.service` |
| `environment` | `labels.env` → `labels.environment` |
| `runbook_url` | `annotations.runbook_url` → `annotations.runbook` |

### 示例 Payload

```json
{
  "receiver": "sxdevops",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighCPUUsage",
        "severity": "critical",
        "instance": "web-01:9100",
        "job": "node_exporter",
        "app": "web-service",
        "env": "prod",
        "cluster": "prod-cluster"
      },
      "annotations": {
        "summary": "Web-01 CPU 使用率超过 90%",
        "description": "当前 CPU 使用率 94.2%，持续 5 分钟",
        "runbook_url": "https://wiki.example.com/runbooks/high-cpu"
      },
      "startsAt": "2026-07-06T10:30:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph?g0.expr=...",
      "fingerprint": "abc123def456"
    }
  ],
  "commonLabels": {},
  "commonAnnotations": {},
  "groupKey": "{}:{}/{severity=\"critical\"}:{}"
}
```

## 五、验证

```bash
# 发送测试告警
curl -X POST \
  https://<平台>/api/alerts/webhooks/prometheus/<token>/ \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "测试告警",
        "severity": "warning",
        "instance": "test-host",
        "job": "test"
      },
      "annotations": {
        "summary": "测试 Prometheus 告警",
        "description": "这是一条手动测试告警"
      },
      "startsAt": "2026-07-06T10:30:00Z",
      "fingerprint": "test-fingerprint-001"
    }]
  }'
```

成功响应（HTTP 202）：`{"success": true, "provider": "prometheus", "created": 1, "updated": 0, "alert_ids": [123]}`
