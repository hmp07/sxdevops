# SxDevOps SQL 审计

## 一、概述

SQL 审计模块为数据库变更提供安全管控——DBA/开发提交 SQL 工单，经审核后由平台代理执行，全程留痕。

**入口：** 侧边栏 → 工单系统 → SQL 审计
**权限：** `sqlaudit.order.view` / `sqlaudit.order.submit` / `sqlaudit.order.review` / `sqlaudit.order.execute`

## 二、数据源配置

### 2.1 添加数据库

在 SQL 审计页面的"数据源"Tab 中添加目标数据库：

| 字段 | 说明 |
|------|------|
| 数据源名称 | 如 `trade-primary` |
| 数据库类型 | MySQL / PolarDB / MongoDB |
| 主机地址 | 数据库 IP 或域名 |
| 端口 | 默认 3306 |
| 用户名 / 密码 | 数据库连接凭证 |
| 字符集 | 默认 utf8mb4 |

### 2.2 支持的数据库类型

- MySQL 5.7+
- PolarDB（MySQL 兼容）
- MongoDB

## 三、SQL 工单

### 3.1 提交工单

1. 点击"新建 SQL 工单"
2. 选择目标数据源和数据库
3. 选择 SQL 类型（DDL / DML / DQL）
4. 输入 SQL 内容
5. 提交审核

### 3.2 工单审核

- 审核人查看 SQL 内容和预检结果
- 自动检测：SELECT *、缺少 WHERE 的 DELETE/UPDATE、TRUNCATE 风险操作
- 通过 / 驳回 / 修改建议

### 3.3 执行

- 审核通过后由平台代理执行
- 执行结果实时展示
- 失败的 SQL 记录错误详情

## 四、SQL 查询

"查询"Tab 提供只读 SQL 查询功能，用于数据分析和问题排查，不产生变更记录。提交的查询也记录在工单历史中。
