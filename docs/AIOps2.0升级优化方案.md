# AIOps 2.0 升级优化方案

本文记录 sxdevops AIOps 2.0 的升级目标、架构调整点、核心能力清单与落地优先级。当前方案面向平台内智能助手能力升级，后续以本文作为研发拆分依据。

## 1. 升级定位

AIOps 2.0 的目标不是增加一个通用聊天入口，而是把 AI 能力做进 sxdevops 的运维控制面：让 assistant 理解用户所在页面、知识图谱关联对象、环境、告警、变更、日志、链路、K8s、发布任务、工单和值班上下文，并通过受控工具完成分析、推荐和待确认操作。

核心定位：

- 从“问答助手”升级为“可配置的运维 Agent 平台”。
- 从“单一大模型回复”升级为“意图路由 + Action 合同 + Skill 知识包 + 受控工具 + 结构化 UI”。
- 从“自然语言建议”升级为“证据链、预检、确认流、审计流闭环”。
- 从“平台内浮窗”升级为“Web assistant + MCP/A2A 互操作能力”。

## 2. 设计原则

1. 平台 API 是唯一执行边界  
   LLM 只负责理解、规划和生成候选参数，所有查询、创建、修改、执行动作都必须通过后端工具层调用平台 API，不能绕过 RBAC、审计和参数校验。

2. Action 负责平台任务合同  
   Action 是稳定的后端协议，负责识别任务类型、选择 agent 模式、声明工具白名单、风险等级、预检 schema、输出 block 和权限边界。

3. Skill 负责领域知识沉淀  
   Skill 是可复用知识包，负责 SOP、证据清单、查询规范、输出要求、安全边界和案例示例。一个 Action 可以加载多个 Skill，一个 Skill 也可以被多个 Action 复用。

4. 结构化响应驱动前端交互  
   assistant 返回 Markdown 之外，还要返回结构化 block，让前端可以渲染事件卡片、证据时间线、查询建议、审批表单、回滚计划、自愈推荐和待确认按钮。

5. 先预检，再确认，再执行  
   创建、修改、执行类动作必须先补齐关联对象、环境、集群、命名空间、服务、时间窗口、审批人等关键参数，再进入 dry-run、人工确认和审计执行。

6. 自愈默认推荐，不默认执行  
   自愈能力先给出候选脚本、风险说明、适用范围、回滚方案和执行 marker。真正执行必须经过用户确认、权限校验和审计记录。

7. 后端权限强制，前端权限镜像  
   后端先做 RBAC 强制控制；前端只负责隐藏入口、按钮和操作列，不能作为安全边界。

## 3. 总体架构调整

```text
页面上下文 / 全局聊天 / 外部 Agent
        |
        v
AIOps API 层
        |
        v
会话与流式状态层
        |
        v
Action Router
        |
        +--> Direct Agent
        +--> ReAct Agent
        +--> Plan + ReAct Agent
        |
        v
Skill Registry + Tool Registry + MCP Registry
        |
        v
平台 API 安全封装层
        |
        v
知识图谱 / 监控告警 / 日志 / 链路 / K8s / CI-CD / Git / 制品库 / 工单 / 值班 / 任务中心 / 自愈
```

关键变化：

- `Action Router` 负责识别任务类型，不直接执行业务动作。
- `Agent Kernel` 支持 Direct、ReAct、Plan + ReAct 三类模式。
- `Skill Registry` 负责加载运维知识、输出约束和场景模板。
- `Tool Registry` 负责暴露平台能力、校验参数、执行权限和记录审计。
- `Structured Block Renderer` 负责把 AI 输出转成可交互 UI。
- `State Store` 负责会话状态、消息流、取消信号、并发锁和恢复能力。

## 4. Action 与 Skill 的边界

Action 和 Skill 不能重复承担同一件事：

- Action 回答“这是什么平台任务、谁能做、按什么流程做、能调用哪些工具、输出什么结构、是否需要预检或确认”。
- Skill 回答“这类任务应该怎么分析、需要哪些证据、查询怎么写、风险怎么判断、回答怎么组织、哪些动作不能直接做”。

示例映射：

| Action | 默认加载 Skill |
| --- | --- |
| `alert.root_cause` | 告警证据清单、K8s 告警排障、日志模式分析、变更影响分析、回答整形 |
| `change.correlation` | 变更影响分析、事件时间线关联、回答整形 |
| `log.query_generate` | 日志查询规范、日志字段字典、回答整形 |
| `k8s.diagnose` | K8s 排障、容器只读取证、安全边界、回答整形 |
| `self_heal.recommend` | 自愈风险护栏、任务模板选择、回滚策略、回答整形 |

## 5. Action Router 设计

P0 先内置以下 Action：

| Action | 目标场景 | 核心工具 |
| --- | --- | --- |
| `alert.root_cause` | 告警根因分析 | 告警、指标、日志、链路、变更、知识图谱 |
| `change.correlation` | 变更关联分析 | 发布记录、工单、Git、CI-CD、事件墙、知识图谱 |
| `log.query_generate` | 日志查询生成 | 日志数据源、字段字典、历史查询 |
| `metric.query_generate` | PromQL/指标查询生成 | 指标数据源、服务标签、指标字典 |
| `k8s.diagnose` | K8s 排障 | 集群、命名空间、Pod、Event、容器日志 |
| `deploy.failure_diagnose` | 发布失败诊断 | 发布任务、构建日志、制品、K8s、告警 |
| `slo.analysis` | SLO/服务健康分析 | 指标、告警、链路、错误率、延迟 |
| `self_heal.recommend` | 自愈推荐 | 告警、历史处置、任务模板、自愈脚本 |
| `notification.policy_suggest` | 通知和升级策略建议 | 告警规则、值班、团队、通知渠道 |
| `runbook.generate` | Runbook 生成 | 历史事件、处置记录、知识库、任务模板 |

每个 Action 至少定义：

- `code`：稳定编码。
- `display_name`：前端展示名称。
- `risk_level`：`read_only` / `draft` / `write` / `execute`。
- `agent_mode`：`direct` / `react` / `plan_react`。
- `required_context`：必须具备的上下文。
- `allowed_tools`：可调用工具白名单。
- `skills`：默认加载 Skill slug。
- `preflight_schema`：缺参时返回的表单 schema。
- `output_schema`：结构化响应 block schema。
- `rbac_permissions`：发起、确认、执行所需权限。

## 6. Skill 库设计

Skill 是 sxdevops assistant 的领域知识包，不直接查数据，不直接执行平台动作。Skill 管理的重点是“让 assistant 在某一类问题上有稳定工作方法”，而不是堆叠零散的一句话提示词。

### Skill 包结构

每个 Skill 至少包含：

- `name`：名称。
- `slug`：稳定标识。
- `category`：问题分类，例如告警排障、日志查询、K8s 诊断、自愈安全。
- `description`：适用场景摘要。
- `applicable_actions`：可复用到哪些 Action。
- `examples`：典型用户问题示例。
- `builtin_tools`：强绑定平台工具。
- `recommended_tools`：建议优先选择的工具。
- `max_iterations`：建议最大推理/工具轮次，0 表示由 Action 决定。
- `risk_level`：Skill 自身风险建议。
- `output_contract`：建议输出结构。
- `content`：完整 SOP、证据清单、查询规范、安全约束和回答格式。

### P0 内置 Skill

- `sx-alert-evidence-checklist`：告警根因分析证据清单，约束必须输出结论、证据、影响范围和下一步动作。
- `sx-k8s-alert-troubleshooting`：K8s 告警排障，约束集群、命名空间、工作负载、Pod、Event、日志和资源状态取证顺序。
- `sx-log-pattern-analysis`：日志模式分析，约束字段、过滤条件、时间范围、聚合方式和样本解释。
- `sx-change-impact-analysis`：变更影响分析，约束时间窗口、发布记录、工单、事件和知识图谱依赖关系。
- `sx-log-query-guide`：日志查询生成规范，约束查询语句、过滤项、字段解释和可复制输出。
- `sx-log-field-dictionary`：日志字段字典，沉淀 service、level、trace_id、span_id、pod、namespace 等字段含义。
- `sx-k8s-troubleshooting`：K8s 排障 SOP，覆盖 Pending、CrashLoopBackOff、ImagePull、探针失败、资源不足等场景。
- `sx-container-readonly-guard`：容器只读取证安全边界，禁止 assistant 直接执行集群或主机写操作。
- `sx-self-heal-risk-guard`：自愈风险护栏，约束推荐、dry-run、确认、执行、审计和回滚。
- `sx-task-template-selection`：任务模板选择，约束如何匹配任务中心模板与目标资源。
- `sx-rollback-strategy`：回滚策略，约束回滚前置条件、影响范围、验证项和失败处理。
- `answer-formatter`：回答整形器，负责把工具事实整理成稳定的最终回答。

### 自定义 Skill

团队可在平台内创建自定义 Skill，用于沉淀团队自己的 Runbook、排障 SOP、日志字段规范、发布回滚策略、K8s 常见故障处理、数据库故障处理和自愈脚本规范。

自定义 Skill 必须遵守：

- 必须声明适用 Action，不允许成为无边界的通用提示词。
- 必须声明风险等级和推荐工具。
- 写入或执行类 Skill 必须包含预检、确认、dry-run、审计和回滚要求。
- 不允许把密钥、token、kubeconfig、证书等敏感信息写入内容。

## 7. 工具层升级

工具层是 AIOps 2.0 的安全边界。所有工具必须是平台 API 的后端封装，不允许模型直接拼接数据库查询或绕过服务层。

工具统一规范：

- `name`：工具名。
- `description`：模型可见说明。
- `input_schema`：参数 schema。
- `output_schema`：返回 schema。
- `permission`：所需权限。
- `risk_level`：风险等级。
- `timeout`：超时时间。
- `rate_limit`：限流策略。
- `audit_event`：审计事件类型。
- `dry_run_supported`：是否支持 dry-run。
- `preflight_required`：是否必须预检。
- `idempotency_key`：写入或执行类动作的幂等键。

建议工具分组：

- 知识图谱：服务、环境关联、负责人、依赖关系、上下游拓扑。
- 监控告警：当前告警、历史告警、告警规则、订阅、屏蔽、通知策略。
- 指标查询：指标数据源、PromQL 生成、指标曲线、服务健康。
- 日志查询：日志数据源、字段字典、查询生成、错误日志聚合。
- 链路追踪：Trace 查询、Span 错误、慢调用、上下游依赖。
- K8s：集群、命名空间、Workload、Pod、Event、容器日志、资源用量。
- CI-CD：发布任务、构建日志、部署记录、回滚候选。
- Git 与制品：提交、分支、Tag、制品版本、镜像信息。
- 工单和值班：工单、审批人、值班表、升级策略。
- 任务中心：任务模板、巡检任务、执行历史、脚本 dry-run。
- 自愈：候选脚本、适用条件、风险评估、执行 marker。
- SQL 审计：数据源、查询申请、审批、执行审计。

## 8. 结构化响应协议

AIOps 2.0 需要把“回答内容”和“前端可交互对象”分开。建议每次回复包含：

```json
{
  "answer": "面向用户的自然语言总结",
  "blocks": [],
  "actions": [],
  "trace": [],
  "citations": []
}
```

建议内置 block：

| Block | 用途 |
| --- | --- |
| `incident_card` | 故障或异常摘要卡片 |
| `evidence_timeline` | 告警、日志、链路、变更证据时间线 |
| `query_suggestion` | PromQL、SQL、LogQL 等查询建议 |
| `chart_query` | 可直接跳转或渲染的指标查询 |
| `alert_rule_draft` | 告警规则草稿 |
| `dashboard_draft` | 仪表盘草稿 |
| `change_candidate` | 可能相关的变更记录 |
| `rollback_plan` | 发布回滚计划 |
| `k8s_action` | K8s 操作建议或待确认动作 |
| `self_heal_recommendation` | 自愈推荐卡片 |
| `approval_form` | 待补参或待确认表单 |
| `tool_trace` | 工具调用追踪 |
| `risk_notice` | 风险提示 |

## 9. Preflight 与确认流

创建、修改、执行类 Action 必须走统一流程：

1. 用户提出目标。
2. Action Router 识别 Action。
3. Agent 检查缺失参数。
4. 返回 `approval_form` 或 `preflight_form`。
5. 用户补齐关联对象、环境、集群、命名空间、服务、时间窗口、审批人等信息。
6. 后端校验 RBAC、参数 schema、资源范围和风险等级。
7. 生成 dry-run 或草稿。
8. 用户二次确认。
9. 后端执行平台 API。
10. 记录审计、工具调用、执行结果和可回溯链路。

## 10. MCP/A2A 互操作

sxdevops 不只服务 Web 页面，也要服务外部 Agent 编排平台。

sxdevops 作为 MCP Server：

- 暴露知识图谱、告警、日志、链路、K8s、发布、工单、任务中心等只读工具。
- 写入和执行类工具默认要求 preflight 和用户确认。
- 统一鉴权、权限过滤、审计和限流。

sxdevops 接入外部 MCP：

- 管理外部 MCP Server 配置。
- 做健康检查、工具发现、权限绑定和超时控制。
- 外部工具输出必须进入事实集，不能直接变成最终回答。

A2A 方向：

- 支持外部 Agent 创建 AIOps 任务。
- 支持任务状态查询、取消、结果回调。
- 支持跨系统编排时保留用户身份、权限和审计链路。

## 11. 落地优先级

### P0：AIOps assistant 基座

- LLM 配置中心升级为 Provider + Model Profile。
- 会话流式响应、取消、恢复和 ChatLock。
- Action registry 初版。
- RBAC 工具层和工具 schema 规范。
- 页面上下文注入。
- 结构化响应 block 协议。
- Skill 库初版：告警根因、变更关联、日志查询生成、K8s 诊断、自愈推荐。
- 工具调用追踪和基础审计。

### P1：能力增强

- Skill 市场和团队自定义 Skill。
- MCP 接入与对外暴露。
- preflight 表单。
- AI 执行审计。
- 工具调用追踪详情。
- 模型连接测试、成本统计、工具调用成本统计。

### P2：深度编排

- A2A。
- 多 Agent 编排。
- Plan + ReAct 深度排障。
- 自动生成 Runbook。
- 自动沉淀复盘知识。

## 12. 结论

AIOps 2.0 的价值在于把 AI 做进 sxdevops 的运维控制面，而不是外接一个通用 Bot。研发应围绕“Action 合同 + Skill 知识包 + 权限工具层 + 结构化 UI + 安全执行闭环”推进。
