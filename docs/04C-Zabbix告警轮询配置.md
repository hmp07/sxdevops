# SxDevOps Zabbix 告警轮询配置

## 一、概述

Zabbix 告警轮询是**无需修改 Zabbix Server 配置**的告警接入方式。平台通过 Django management command 定时从 Zabbix API 拉取活跃问题，导入告警中心并走完整告警流水线。

**与 Webhook 方式对比：**

| 维度 | 轮询（本文档） | Webhook |
|------|--------------|---------|
| 实时性 | 分钟级（取决于 cron 频率） | 秒级实时 |
| Zabbix 端配置 | 无需 | 需配置 Action + Media Type |
| 网络要求 | 平台需能访问 Zabbix API | Zabbix 需能访问平台 |
| 推荐场景 | 快速接入、备份兜底 | 生产推荐 |

**前置条件：**
- 已配置至少一个启用的 [Zabbix 数据源](04A-Zabbix数据源配置与管理.md)

## 二、手动执行

```bash
cd backend

# 从所有启用的数据源拉取告警
python manage.py poll_zabbix_alerts

# 仅拉取指定数据源
python manage.py poll_zabbix_alerts --datasource-id 1

# 预览模式（不写入数据库）
python manage.py poll_zabbix_alerts --dry-run
```

**输出示例：**
```
正在从 "公司生产Zabbix" (http://192.168.1.45/api_jsonrpc.php) 拉取告警...
  获取到 39 个活跃问题
    新建 5 条，更新 34 条
轮询完成: 共 39 条告警 (新建 5，更新 34)
```

## 三、定时执行

### 3.1 内置调度（推荐）

平台内置调度器已随后端进程自动运行，**默认每 5 分钟**轮询一次所有启用的 Zabbix 数据源，无需再配置外部 cron / Task Scheduler。

| 环境变量 | 默认值 | 说明 |
| ---- | ---- | ---- |
| `SXDEVOPS_ZABBIX_POLL_INTERVAL` | 300 | 轮询间隔（秒） |
| `SXDEVOPS_DISABLE_ZABBIX_POLL` | 未设置 | 设为 `1` 关闭内置调度 |

调度器为 daemon 线程：单轮失败仅记日志、下一轮自动重试；随后端进程退出。管理命令 `python manage.py poll_zabbix_alerts` 仍可用于手动触发。

### 3.2 外部调度（可选，内置调度关闭时使用）

#### Linux Cron

```bash
# 编辑 crontab
crontab -e

# 每 5 分钟执行一次
*/5 * * * * cd /app/backend && python manage.py poll_zabbix_alerts >> /var/log/zabbix_poll.log 2>&1
```

#### Docker 环境

容器内已包含所有依赖，可直接执行：

```bash
docker exec sxdevops-app python manage.py poll_zabbix_alerts
```

在宿主机设置 cron：

```bash
*/5 * * * * docker exec sxdevops-app python manage.py poll_zabbix_alerts >> /var/log/zabbix_poll.log 2>&1
```

#### Windows Task Scheduler

1. 创建基本任务 → 触发器：每天，重复间隔 5 分钟
2. 操作：启动程序 → `python` → 参数 `manage.py poll_zabbix_alerts` → 起始于 `C:\path\to\backend`

## 四、告警导入流程

```
cron 触发
  │
  ▼
poll_zabbix_alerts 命令
  │
  ├── 遍历所有启用的 ZabbixDataSource
  ├── 调用 ZabbixClient.get_problems()
  │
  ▼
zabbix_alert_bridge.upsert_alert_from_zabbix_problem()
  │
  ├── _build_normalized()       # 构建统一格式
  ├── alerting.upsert_alert()   # 指纹去重 + 创建/更新
  ├── apply_alert_suppression() # 应用静默/抑制规则
  ├── dispatch_alert_notifications() # 通知分发
  └── _record_event()           # 写入事件墙
  │
  ▼
告警中心可查看、认领、静默、关闭
```

## 五、数据源同步时间

每次轮询完成后，数据源的 `last_sync_at` 字段自动更新。在 Zabbix 数据源列表中可以看到"最近同步"时间。

## 六、AI 智能助手补充

AIOps 智能助手在使用 Zabbix 排障工具时，会**静默同步**查询到的问题到告警中心，作为轮询的补充。这意味着即使没有配置 cron，只要有人使用 AI 助手分析 Zabbix 告警，告警中心也会逐渐积累数据。

## 七、验证

1. 执行 `python manage.py poll_zabbix_alerts`
2. 打开告警中心 → 来源筛选选择 **Zabbix** → 确认出现导入的告警
3. 确认告警标题、级别、状态与实际 Zabbix 问题一致
4. 设置 cron 定时任务后，观察数据源"最近同步"时间是否定期更新
