# SxDevOps 阿里云监控 Webhook 接入

## 一、概述

接入阿里云云监控（CloudMonitor）告警，支持将 ECS、RDS、SLB 等云资源告警推送到 SxDevOps 统一管理。

**前置条件：**
- 阿里云账号，已开通云监控服务
- 平台对阿里云回调地址网络可达（HTTPS 公网可达）

## 二、平台端配置

1. 告警中心 → **告警接入源** Tab → 新增接入源
2. 接入类型选择 **阿里云监控**
3. 保存后获取 Webhook URL：

```
https://<平台地址>/api/alerts/webhooks/aliyun/<token>/
```

## 三、阿里云端配置

### 3.1 创建报警回调

阿里云控制台：**云监控 → 报警服务 → 报警规则**

1. 创建或编辑报警规则
2. 在 **通知方式** 中，选择 **回调 URL**
3. 填入 Webhook URL：
   ```
   https://<平台地址>/api/alerts/webhooks/aliyun/<token>/
   ```

### 3.2 多规则共享

可以在**报警联系组**中统一配置回调 URL，所有规则共享同一接入源。

## 四、Payload 格式

阿里云云监控发送的 JSON 由平台 `_normalize_aliyun()` 处理。

字段映射：

| 平台字段 | 来源优先级 |
|----------|-----------|
| `title` | `alertName` → `ruleName` → `name` |
| `level` | `level` → `severity` → `warnLevel` |
| `status` | `alertState` → `state` → `status` |
| `source` | `namespace` → `product` → `Aliyun CloudMonitor` |
| `external_id` | `alertId` → `ruleId` → `eventId` |
| `fingerprint` | 自动组合：`ruleId:instanceId:metricName` |
| `resource` | `instanceName` → `instanceId` → `dimensions.instanceId` |
| `service` | `labels.app` → `product` → `namespace` |
| `region` | `regionId` → `region` → `dimensions.regionId` |

### 示例 Payload

```json
{
  "alertName": "ECS CPU 使用率过高",
  "level": "CRITICAL",
  "alertState": "ALARM",
  "namespace": "acs_ecs_dashboard",
  "instanceName": "prod-web-01",
  "instanceId": "i-bp1xxxxxxxxxx",
  "regionId": "cn-hangzhou",
  "ruleId": "rule-xxxxx",
  "metricName": "CPUUtilization",
  "curValue": "95.2",
  "timestamp": 1779000000000,
  "userId": "1234567890",
  "dimensions": {
    "instanceId": "i-bp1xxxxxxxxxx",
    "regionId": "cn-hangzhou"
  }
}
```

## 五、验证

```bash
curl -X POST \
  https://<平台>/api/alerts/webhooks/aliyun/<token>/ \
  -H "Content-Type: application/json" \
  -d '{
    "alertName": "测试阿里云告警",
    "level": "WARN",
    "alertState": "ALARM",
    "namespace": "acs_ecs_dashboard",
    "instanceName": "test-instance",
    "instanceId": "i-test00001",
    "regionId": "cn-hangzhou",
    "ruleId": "rule-test01",
    "metricName": "CPUUtilization",
    "curValue": "85.0",
    "timestamp": 1779000000000,
    "userId": "1234567890"
  }'
```
