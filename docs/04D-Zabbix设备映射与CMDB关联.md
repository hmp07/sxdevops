# SxDevOps Zabbix 设备映射与 CMDB 关联

## 一、概述

设备映射将 Zabbix 监控的主机与 CMDB 中的配置项（CI）关联起来，实现"监控→配置"的双向数据打通。映射建立后，在 Zabbix 监控页可看到主机对应的 CI，在 CMDB 配置项列表可看到 CI 是否被 Zabbix 监控。

## 二、自动匹配机制

系统在加载 Zabbix 主机列表时自动执行设备匹配：

1. 提取 Zabbix 主机的**主接口 IP**
2. 在 CMDB `ConfigItem` 表的 `attributes` JSON 字段中搜索 `ip_address` 或 `managementip` 匹配的记录
3. 匹配成功 → 创建 `DeviceMapping` 记录
4. 已有映射的主机直接返回关联结果

### 2.1 匹配方式

| 方式 | 说明 | 触发 |
|------|------|------|
| IP 精确匹配 | Zabbix 主接口 IP == CI 属性中的 ip_address | 自动 |
| 名称模糊匹配 | Zabbix 主机名与 CI 名称相似 | 自动（IP 匹配失败时） |
| 人工指定 | 手动关联 | CMDB 配置项编辑页面 |

### 2.2 匹配置信度

每条映射记录包含 `match_confidence`（0.0~1.0）：
- IP 精确匹配：1.0
- 名称模糊匹配：按相似度
- 人工指定：1.0

## 三、查看映射结果

### 3.1 Zabbix 监控页面

主机列表的"关联 CI"列显示：
- 已关联 → 绿色标签显示 CI 名称
- 未关联 → 灰色"未关联"

### 3.2 CMDB 配置项页面

配置项列表的"Zabbix 监控"列显示：
- 已关联 → 绿色标签显示 Zabbix 主机名
- 未关联 → 灰色"未监控"

## 四、手动管理映射

### 4.1 通过 Zabbix API 查询映射

```
GET /api/observability/zabbix/device-mappings/?host_ids=10084,10085
```

### 4.2 通过 CMDB 关联

编辑配置项时可以手动指定关联的 Zabbix 主机映射。

## 五、反向匹配

从 iTop 同步 CI 后，系统也会执行反向匹配——查找已有 IP 匹配的 Zabbix 主机，自动创建映射。
