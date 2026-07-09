# SxDevOps iTop CMDB 查询与拓扑

## 一、概述

配置 iTop 数据源后，可以在平台内直接查询 iTop 的配置项和关联关系，并触发全量数据同步。

**前置条件：** 已配置至少一个 [iTop 数据源](05A-iTop数据源配置.md)
**权限：** `cmdb.itop.view`

## 二、CI 查询

### 2.1 查询 iTop CI

在 **CMDB → 配置项** 页面，选择 iTop 数据源后：
- 按 CI 类型筛选（Server、VirtualMachine、Application 等）
- 按名称搜索
- 查看 CI 属性（IP、状态、组织等）

### 2.2 CI 类型映射

iTop 的 CI 类自动映射到平台的 CI 类型：

| iTop 类 | 平台 CI 类型 |
|---------|------------|
| Server | 服务器 |
| VirtualMachine | 云主机 (ECS) |
| NetworkDevice | 网络设备 |
| StorageSystem | 存储系统 |
| Application | 应用 |
| Database | 数据库 |

## 三、数据同步

### 3.1 触发同步

在 **CMDB → iTop 对接** 页面，点击数据源的"同步"按钮触发全量同步。

同步内容：
1. CI 类型同步（从 `ci_class_map` 配置）
2. CI 实例同步（含自动 Zabbix 设备关联匹配）
3. 关联关系同步
4. 工单同步（UserRequest、Incident、Change、Problem）

### 3.2 同步状态

数据源列表的"同步状态"列显示：
- `idle`：空闲
- `running`：正在同步
- `ok`：上次同步成功
- `error: ...`：同步失败（含错误信息）

### 3.3 同步模式

| 模式 | 说明 |
|------|------|
| 全量 (full) | 每次重新拉取所有数据 |
| 增量 (incremental) | 仅拉取自上次同步以来的变更 |

## 四、关联关系

iTop 中的 CI 关联关系同步到平台后，可在**资源拓扑**页面中可视化查看。关系类型自动转换：
- `impacts` / `depends on` → 依赖关系
- `provides` / `connected to` → 连接关系

## 五、工单同步

iTop 中的工单（UserRequest、Incident、NormalChange、Problem）同步到平台的**事务工单**模块，`external_source='itop'` 标记来源。
