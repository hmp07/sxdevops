# SxDevOps iTop CMDB 数据源配置

## 一、概述

iTop 是开源的 IT 运维管理（ITSM/CMDB）平台。SxDevOps 通过 iTop REST API 接入其配置管理数据，实现：
- 在平台内直接查询 iTop 的 CI（配置项）和关联关系
- 将 iTop CI 与 Zabbix 监控主机建立设备映射
- 基于 CI 关联关系进行变更影响分析

**前置条件：**
- iTop 2.7+ 已部署运行
- iTop 开启了 REST API（默认启用）
- 需要 `cmdb.itop.view` / `cmdb.itop.datasource.manage` 权限

## 二、平台端配置

### 2.1 进入配置页面

侧边栏：**CMDB → iTop 对接**

### 2.2 新增 iTop 数据源

| 字段 | 说明 | 示例 |
|------|------|------|
| 名称 | 数据源名称 | `公司 iTop CMDB` |
| API 地址 | iTop REST API 端点 | `https://itop.example.com/webservices/rest.php` |
| 用户名 | iTop 登录用户 | `admin` |
| 密码 | iTop 登录密码 | — |
| 启用 / 停用 | 控制数据源可用性 | 启用 |

### 2.3 测试连接

保存后，平台会自动验证 iTop API 连通性。

## 三、iTop 端要求

### 3.1 REST API 验证

确认 iTop 的 REST API 可访问：

```bash
curl -X POST \
  https://itop.example.com/webservices/rest.php \
  -d "version=1.3" \
  -d "auth_user=admin" \
  -d "auth_pwd=your-password" \
  -d "json_data={\"operation\":\"core/get\",\"class\":\"Server\",\"key\":\"SELECT Server WHERE name LIKE '%' LIMIT 1\",\"output_fields\":\"name\"}"
```

### 3.2 用户权限

iTop 用户需要：
- REST API 访问权限（Profile: Administrator 或自定义 REST 角色）
- 对目标 CI 类有读权限

### 3.3 版本兼容

支持 iTop 2.7+/3.0+/3.1+。不同版本的数据模型（CI 类名）可能有差异，平台自动适配。

## 四、数据同步

### 4.1 CI 查询

数据源配置后，可在 **CMDB → 配置项** 页面选择 iTop 数据源，查询 iTop 中的 CI 列表。支持按 CI 类型、名称、组织过滤。

### 4.2 设备关联映射

平台通过 IP 匹配自动将 iTop CI 与 Zabbix 监控主机关联：
- 匹配条件：CI 的 `ip_address` 或 `managementip` 与 Zabbix 主机的接口 IP 一致
- 匹配结果在 Zabbix 监控页面"关联 CI"列显示
- 也可在 CMDB 配置项页面手动关联

### 4.3 变更影响分析（AIOps）

配置 iTop 数据源后，AIOps 智能助手的**跨系统根因分析**能力可以利用 iTop 的 CI 关联关系追溯变更影响范围。

## 五、验证

1. 保存 iTop 数据源
2. 切换至 CMDB → 配置项 → 切换数据源为刚创建的 iTop 数据源
3. 确认能看到 iTop 中的 CI 列表
4. 切换至 CMDB → 资源拓扑 → 查看 CI 关联关系图

## 六、配套文档

- [Zabbix 设备映射与 CMDB 关联](04D-Zabbix设备映射与CMDB关联.md)
- [CMDB 配置项管理](06B-配置项管理.md)
