# SxDevOps 指标查询 (Prometheus)

## 一、概述

指标查询模块用于查询 Prometheus 兼容的指标数据，支持即时查询和范围查询。

**前置条件：**
- Prometheus 数据源已在平台配置
- 需要 `ops.metric.query` 权限

## 二、平台端配置

### 2.1 数据源配置

侧边栏：**可观测性 → 数据源 → 指标数据源** Tab

| 字段 | 说明 |
|------|------|
| 数据源名称 | 自定义名称 |
| Prometheus URL | `http://prometheus:9090` |
| 启用 / 停用 | 控制数据源可用性 |

### 2.2 指标查询

侧边栏：**可观测性 → 指标查询**

- 选择数据源和目标
- 输入 PromQL 查询表达式
- 支持即时查询（Instant）和范围查询（Range）
- 结果以表格和折线图展示

## 三、使用示例

```promql
# 查询 CPU 使用率
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# 查询内存使用率
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

## 四、验证

1. 配置 Prometheus 数据源
2. 切换到指标查询页面 → 输入简单 PromQL（如 `up`）
3. 确认返回数据并正确渲染图表
