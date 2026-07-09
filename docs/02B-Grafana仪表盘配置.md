# SxDevOps Grafana 仪表盘配置

## 一、概述

SxDevOps 可以承接已有的 Grafana 仪表盘，在平台内嵌入显示，实现运维统一入口。

**前置条件：**
- Grafana 已部署运行
- 需要 `ops.grafana.view` / `ops.grafana.manage` 权限

## 二、平台端配置

### 2.1 进入页面

侧边栏：**可观测性 → 可视化 → 仪表盘**

### 2.2 配置 Grafana 连接

1. 点击设置按钮，配置 Grafana 基础信息：

| 字段 | 说明 | 示例 |
|------|------|------|
| Grafana URL | Grafana 服务地址 | `https://grafana.example.com` |
| API Key / Token | Grafana Service Account Token | `glsa_...` |

2. 保存后平台自动验证连通性

### 2.3 添加仪表盘

平台预置了 5 个常用仪表盘模板，也可手动添加自定义仪表盘：

| 预置仪表盘 | 用途 |
|-----------|------|
| APM 全链路总览 | 服务吞吐、慢调用、错误率 |
| 基础设施总览 | 节点 CPU、内存、磁盘、Pod |
| 日志钻取看板 | 错误时段与关键日志回放 |
| 入口流量与 SLO | 入口 QPS、延迟分位、可用性 |
| K8s 工作负载资源 | 按 namespace/workload 维度 |

手动添加时填写：
- 仪表盘标题
- slug（Grafana URL 中的仪表盘标识）
- 路径（如 `/d/apm-overview`）
- 面板数量
- 标签和描述

## 三、使用

配置完成后，仪表盘以 iframe 方式嵌入平台页面，用户无需跳转到 Grafana。

## 四、验证

1. 配置 Grafana 连接 → 保存 → 确认连接状态正常
2. 添加一个仪表盘 → 返回列表 → 点击预览 → 确认能正常嵌入显示
