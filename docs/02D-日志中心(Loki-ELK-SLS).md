# SxDevOps 日志中心 (Loki / ELK / SLS)

## 一、概述

日志中心统一管理多种日志后端，支持 Loki、ELK (Elasticsearch)、阿里云 SLS 三种数据源。

**前置条件：**
- 至少一个日志数据源已部署
- 需要 `ops.log.query` 权限

## 二、数据源配置

侧边栏：**可观测性 → 数据源 → 日志数据源** Tab

### 2.1 Loki

| 字段 | 说明 |
|------|------|
| 数据源名称 | 如 `生产 Loki` |
| 日志类型 | Loki |
| Loki 地址 | `http://loki:3100` |

### 2.2 ELK / Elasticsearch

| 字段 | 说明 |
|------|------|
| 数据源名称 | 如 `生产 ELK` |
| 日志类型 | ELK / Elasticsearch |
| ES 地址 | `https://es.example.com:9200` |
| 认证方式 | 无认证 / Basic Auth / API Key / Bearer Token |
| 索引模式 | `logs-*` |
| 时间字段 | `@timestamp` |
| 消息字段 | `message,log,msg` |

### 2.3 阿里云 SLS

| 字段 | 说明 |
|------|------|
| 数据源名称 | 如 `生产 SLS` |
| 日志类型 | 阿里云 SLS |
| Endpoint | `cn-hangzhou.log.aliyuncs.com` |
| Project | SLS Project 名称 |
| Logstore | Logstore 名称 |
| AccessKey ID / Secret | 阿里云 RAM 用户凭证 |

## 三、日志查询

侧边栏：**可观测性 → 日志中心**

- 选择数据源
- 输入查询语句（LogQL / Lucene / SLS 查询语法）
- 选择时间范围
- 结果以列表和时序图展示

## 四、日志与链路关联

配置**关联配置**（可观测性 → 数据源 → 关联配置）后，日志中可一键跳转到对应的链路追踪详情。
