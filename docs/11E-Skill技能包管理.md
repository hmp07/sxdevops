# SxDevOps Skill 技能包管理

## 一、概述

Skill（技能包）是领域运维能力的标准化封装，约束 AI 智能体的查询规范、证据清单、输出格式和安全边界。相比于让 AI "自由发挥"，Skill 确保输出的一致性和专业性。

**入口：** AIOps → 智能体配置 → Skill 管理
**权限：** `aiops.config.manage`

## 二、内置 Skill 类型

| Skill | 说明 |
|-------|------|
| `sx-zabbix-troubleshooting` | Zabbix 排障工作流（问题→主机→监控项→趋势交叉验证） |
| `sx-itop-impact-analysis` | iTop 变更影响分析 |
| `sx-alert-evidence-checklist` | 告警证据清单 |
| `sx-change-impact-analysis` | 变更影响分析 |
| `sx-event-timeline-correlation` | 事件时间线关联 |
| `answer-formatter` | 标准答案格式化 |

## 三、Skill 结构

每个 Skill 定义包含：

| 组件 | 说明 |
|------|------|
| 名称 | Skill 唯一标识 |
| 描述 | Skill 用途说明 |
| 证据清单 | 必须收集的数据项 |
| 查询规范 | 推荐的查询步骤和工具 |
| 输出合同 | 输出格式模板（结论/证据/风险/建议） |
| 安全边界 | 允许的操作用范围 |
| 工具依赖 | 依赖的 MCP 工具列表 |
| 包元数据 | 版本、作者、标签 |

## 四、Skill vs Action 的关系

- **Action** 负责"任务入口和流程策略"（这个任务属于什么类型，用什么 Agent Mode，走什么预检）
- **Skill** 负责"能力包和专业约束"（诊断数据库问题应该查什么、怎么查、输出什么格式）

两者配合使用。同一个 Action 可以关联多个 Skill，AI 按场景自动选择。
