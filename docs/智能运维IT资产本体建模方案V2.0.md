# 智能运维IT资产本体建模方案（V2.0 修订版）

> 文档版本：V2.0（依据《三方专家评审报告》修订，替代 V1.0）
> 适用场景：企业IT全域运维（基础设施/网络/服务器/中间件/数据库/应用），支撑告警收敛、根因分析、变更风险评估，对接多智能体与Harness安全约束模块
> 落地策略：**统一顶层本体框架，分阶段实例灌入，试点从Oracle数据库域切入，逐步扩展至全IT域**
> 核心架构决策（V2.0新增）：**设计期用 OWL+SWRL 建模与一致性校验；运行期由规则引擎/图遍历承载因果推理**（SWRL 规则作为语义规范，转写后执行）

---

## 变更说明（V1.0 → V2.0）

| 评审问题 | 修订内容 | 位置 |
| --- | --- | --- |
| P0-1 SWRL 规则含析取、规则头新生个体不可执行 | 全部规则改写为纯合取、一规则一告警码；新增"运行期执行说明"，SWRL 退居设计期规范 | §2、§4.3、§4.4 |
| P0-2 11 个类/属性未定义（含 DatabaseHost） | 补全 `DatabaseHost`、`HarnessAction` 及全部缺失属性；统一 `dependsOn` 命名 | §3、§4.1、§4.2 |
| P0-3 用例 01/02/03/07 推理链断裂 | 所有 L1 规则头显式赋 `alertCode`；新增 D3c/D3d/D3e 桥接规则；修正全部用例规则链 | §4.3、§6 |
| P0-4 OWL 全量推理无法承载实时收敛 | 新增运行期架构：图数据库 + 增量规则引擎 + 推理编排（深度上限/环路检测/熔断/降级） | §7 |
| P0-5 收敛缺时间窗/去重/维护窗/抖动 | 新增告警预处理流水线（时间窗关联、去重、维护窗抑制、flapping、风暴阈值） | §4.5、§7.3 |
| 告警码语义错配 | ORA-03137 降为 L2 概率性；ORA-12514 独立为服务注册异常（B4）；B3 仅保留 ORA-12541 | §4.3、附录A |
| Harness P0 一刀切拦截 | F1 增加白名单 runbook 例外（F1b）、置信度阈值（F3）、紧急破例（F4） | §4.3 组F |
| 类归属错误/公理残缺 | 新增 `DatabaseComponent` 分支；补顶层互斥公理；`derivedFrom` 取消传递性 | §3、§4.1 |
| 业务标签维度不足 | 拆 `PriorityTag`/`BusinessLine`，新增 SLA/变更窗口/责任人/runbook 属性 | §3、§4.2 |
| ETL 与集成契约缺失 | 新增数据同步架构（CI_ID 对齐、CDC+消息队列、CQRS、对账）与接口契约 Schema | §5.2、§7.4 |
| WBS 缺关键活动 | 新增 Phase 0（CMDB 数据治理）及各阶段压测/契约/灰度/培训/回滚活动 | §8 |

---

## 1. 方案概述

### 1.1 建设目标

构建**三层本体模型（概念层-语义层-实例层）**，作为IT资源语义知识库底座，实现：

1. 资产语义建模：统一描述基础设施、网络、服务器、中间件、数据库、业务应用之间的依赖关系；
2. 告警风暴收敛：通过因果推理区分**根因告警 / 衍生告警**，结合时间窗、去重、维护窗抑制压缩告警数量；
3. 全链路根因推理：底层硬件故障向上传导至业务应用，自动输出故障影响链路与**证据链**；
4. 变更风险评估：结合业务资产标签（P0/P1/P2）与置信度阈值，在AI自动执行操作前做风险判定；
5. 安全联动：对接Harness安全约束模块，高危操作拦截、限制AI操作域，支持白名单runbook例外与紧急破例。

### 1.2 双模运行架构（V2.0 核心决策）

| 模式 | 技术栈 | 职责 |
| --- | --- | --- |
| **设计期** | Protégé + OWL 2 + SWRL + HermiT + SHACL | 概念建模、本体一致性校验、规则语义规范存档、实例数据形状校验 |
| **运行期** | Neo4j（拓扑依赖图）+ 增量规则引擎（Drools / Jena Rules，RETE 算法） | 毫秒级依赖遍历、L1 实时告警收敛、L2/L3 异步深度推理 |

> 决策依据：SWRL 为闭世界全量物化推理，且不允许规则头生成新个体（违反 DL-safety），无法承载秒级告警收敛。SWRL 规则在本方案中作为**语义规范**存在，部署时转写为规则引擎等价规则或 SPARQL CONSTRUCT 执行（§4.4）。

### 1.3 适用范围

- 资产范围：物理服务器、虚拟机、K8s Pod、存储、ASM磁盘组、交换机、负载均衡、网卡、Oracle/MySQL/openGauss数据库、Nginx/Tomcat中间件、连接池、微服务、业务应用；
- 事件范围：监控指标、告警事件、变更事件、运维工单；
- 业务标签：业务线、资产优先级（P0/P1/P2）、SLA、变更窗口、责任人、处置预案。

### 1.4 落地路径

> 小切口试点，逐步扩展，避免一次性全量建模带来的模型爆炸、推理性能问题

- Phase 0（前置）：CMDB 数据治理——资产唯一 ID 清洗、依赖关系补全、数据质量基线
- Phase 1（试点）：服务器+存储+Oracle数据库域，验证告警收敛、数据库故障根因推理
- Phase 2（一期扩展）：新增网络资源、Web/App中间件，支持网络类数据库故障（如ORA-03113）
- Phase 3（二期全域）：接入微服务、业务应用、K8s，实现端到端业务影响分析

---

## 2. 本体建模总体设计原则

1. **分层继承原则**：区分父类、子类，避免层级混排；基础设施为硬件父类，软件资源为平行大类，数据库组件（监听/表空间/数据文件/归档日志）独立为 `DatabaseComponent` 分支，事件为独立分支。
2. **最小本体原则**：只建模会独立产生告警、独立作为故障点的实体；普通属性作为DataProperty，不新建Class。
3. **因果确定性分级**：
   - L1：确定性硬因果（主机宕机→实例不可用），实时推理，用于告警收敛
   - L2：高概率因果（网络丢包→ORA-03113），异步深度推理
   - L3：候选提示规则，**不参与告警收敛**，仅作为根因智能体候选假设
4. **形式化约束原则（V2.0新增）**：
   - SWRL 规则前件与后件**仅允许合取**，禁止 `∨` 析取——多取值场景拆分为多条规则；
   - **一条规则只断言一个 alertCode**，禁止规则头出现告警码枚举；
   - 规则头不得出现未在前件绑定的变量；运行期"生成新告警个体"由规则引擎完成，SWRL 仅作语义规范；
   - 所有 L1 规则头**必须显式断言 alertCode**，保证下游规则可链式匹配。
5. **属性全局复用**：`dependsOn` / `hostedOn` / `generatedBy` 等关系全局统一，不按业务域重复定义；命名统一为 `dependsOn`（禁止 `dependOn` 变体）。
6. **推理流水线分离**：实时流水线（仅L1，低延迟告警收敛）；异步流水线（L1+L2+L3，深度根因分析）。推理**跳数上限默认≤5**，环路检测，超限熔断降级。
7. **收敛动态维度原则（V2.0新增）**：因果收敛必须叠加时间窗（默认±5min）、重复告警去重、维护窗口抑制、flapping 抖动抑制、风暴阈值——由告警预处理流水线实现，不依赖 SWRL 表达。
8. **可解释性原则（V2.0新增）**：每条 `derivedFrom` 必须携带证据链（命中规则ID + 输入事实），供运维追责与规则复盘。
9. **安全联动优先**：推理输出的资产依赖、业务标签、根因置信度直接供给Harness安全模块；P0 拦截支持白名单 runbook 例外、置信度阈值与紧急破例。

---

## 3. 概念层（Class类体系）

> 命名规范：类 PascalCase、属性 lowerCamelCase；base IRI `http://ontology.itops.local/itasset#`；按 `infra / network / database / middleware / application / event / safety` 模块拆分，通过 `owl:imports` 组合。

```
Thing
├─ IT_Resource 【IT资源：顶层总父类】
│  ├─ InfraResource 基础设施资源（硬件/底层平台）
│  │  ├─ ComputeResource 计算资源
│  │  │   ├─ PhysicalServer 物理服务器（IBM X3650 M4等）
│  │  │   │   └─ DatabaseHost 数据库主机【V2.0新增：V1.0属性表Domain大量引用但未定义】
│  │  │   ├─ VirtualMachine 虚拟机
│  │  │   └─ ContainerResource 容器资源【V2.0新增】
│  │  │       └─ K8sPod K8s Pod
│  │  ├─ NetworkResource 网络资源
│  │  │   ├─ Switch 交换机
│  │  │   ├─ Router 路由器
│  │  │   ├─ LoadBalancer 负载均衡【V2.0新增】
│  │  │   └─ NetworkInterface 网卡/端口
│  │  └─ StorageResource 存储资源
│  │      ├─ LocalDisk 本地磁盘
│  │      ├─ StorageVolume 存储LUN
│  │      └─ AsmDiskGroup ASM磁盘组
│  └─ SoftwareResource 软件资源
│     ├─ Middleware 中间件
│     │   ├─ WebServer Nginx/Apache
│     │   ├─ AppServer Tomcat/WebLogic
│     │   ├─ MessageQueue 消息队列
│     │   └─ ConnectionPool 连接池【V2.0新增】
│     ├─ DatabaseSystem 数据库系统
│     │   ├─ OracleInstance Oracle实例
│     │   ├─ MysqlInstance MySQL实例
│     │   ├─ OpenGaussInstance openGauss实例
│     │   └─ OracleRacCluster Oracle RAC集群【V2.0新增】
│     ├─ DatabaseComponent 数据库组件【V2.0新增分支：V1.0误挂为DatabaseSystem子类】
│     │   ├─ OracleListener Oracle监听
│     │   ├─ Tablespace 表空间
│     │   ├─ Datafile 数据文件
│     │   └─ ArchiveLog 归档日志
│     └─ ApplicationSystem 应用系统
│         ├─ MicroService 微服务
│         └─ BusinessApplication 业务应用
├─ Event 事件类（独立分支，动态事件）
│  ├─ Metric 监控指标
│  ├─ AlertEvent 告警事件
│  ├─ ChangeEvent 变更事件
│  └─ TroubleTicket 工单事件
├─ BusinessTag 业务标签
│  ├─ PriorityTag 优先级标签（枚举个体：P0/P1/P2）【V2.0拆分】
│  └─ BusinessLine 业务线
└─ HarnessAction 安全约束动作【V2.0新增：F组规则头引用】
```

**互斥与约束公理（V2.0补全）**：

- `DisjointClasses(IT_Resource, Event, BusinessTag, HarnessAction)` —— 顶层四分支互斥
- `DisjointClasses(ComputeResource, NetworkResource, StorageResource)`
- `DatabaseSystem ⊑ ¬DatabaseComponent` —— 数据库系统与数据库组件互斥
- `DisjointClasses(PhysicalServer, VirtualMachine, ContainerResource)`
- `hasKey(DatabaseHost, hostIp)`、`hasKey(OracleInstance, instanceName)` —— 标识唯一性约束

---

## 4. 语义层（对象属性、数据属性、SWRL全局推理规则库）

### 4.1 全局对象属性（带反向、传递特性）

| 属性名 | 定义域 | 值域 | 特征 | 中文含义 |
| --- | --- | --- | --- | --- |
| hosts | ComputeResource | SoftwareResource | 反向：hostedOn | 主机/平台承载软件实例 |
| hostedOn | SoftwareResource | ComputeResource | 反向：hosts | 软件实例运行于主机/Pod |
| contains | OracleInstance | Tablespace | 反向：belongsToInstance | 实例包含表空间 |
| belongsToInstance | Tablespace | OracleInstance | 反向：contains | 表空间隶属于实例 |
| consistOf | Tablespace | Datafile | 反向：belongsToTablespace | 表空间由数据文件组成 |
| belongsToTablespace | Datafile | Tablespace | 反向：consistOf | 数据文件隶属于表空间 |
| storedOn | Datafile/ArchiveLog | StorageVolume | - | 文件存储在存储卷 |
| dependsOn | IT_Resource | IT_Resource | **传递Transitive**；反向：supports | 资源依赖上游资源 |
| supports | IT_Resource | IT_Resource | 反向：dependsOn | 资源支撑下游资源 |
| generatedBy | AlertEvent/Metric | IT_Resource | - | 事件由IT资源产生 |
| derivedFrom | AlertEvent | AlertEvent | **非传递**【V2.0修正：防链式爆炸】 | 衍生告警源自根因告警 |
| derivedFromMetric | AlertEvent | Metric | -【V2.0新增：修复A3值域违反】 | 衍生告警源自指标 |
| derivedFromCode | —（见4.2数据属性） | - | - | 衍生告警源自状态码 |
| hasBusinessTag | IT_Resource | BusinessTag | - | 资产绑定业务标签 |
| hasPort | Switch | NetworkInterface | - | 交换机拥有网口 |
| connectedTo | NetworkInterface | NetworkInterface | 对称Symmetric | 网口互连 |
| hasNic | DatabaseHost | NetworkInterface | - | 主机拥有网卡 |
| containsArchive | OracleInstance | ArchiveLog | - | 实例包含归档日志 |
| hasComponent | DatabaseSystem | DatabaseComponent | 反向：componentOf【V2.0新增】 | 数据库系统拥有组件 |
| monitoredBy | IT_Resource | Metric | 反向：monitors【V2.0新增：A3引用】 | 资源被指标监控 |
| rootCauseOf | AlertEvent | IT_Resource | -【V2.0新增：F2引用】 | 告警的根因资源 |
| targetResource | ChangeEvent | IT_Resource | -【V2.0新增：F1引用】 | 变更目标资源 |
| memberOfCluster | OracleInstance | OracleRacCluster | -【V2.0新增】 | 实例隶属于RAC集群 |
| usesPool | MicroService | ConnectionPool | -【V2.0新增】 | 微服务使用连接池 |

> 说明：`dependsOn` 已声明传递性，其逆 `supports` 自动传递，**不再单独定义 `dependsOnTransitive`**（V1.0 F1 中该未定义属性已删除）。

### 4.2 全局数据属性

| 属性名称 | 定义域 | 数据类型 | 说明 |
| --- | --- | --- | --- |
| hostIp | DatabaseHost | xsd:string | 主机IP（hasKey） |
| hostOs | DatabaseHost | xsd:string | 操作系统版本 |
| hostCpuTotal | DatabaseHost | xsd:decimal | CPU总核数 |
| instanceName | OracleInstance | xsd:string | Oracle实例名（hasKey） |
| oracleVersion | OracleInstance | xsd:string | Oracle版本 |
| listenerPort | OracleListener | xsd:int | 监听端口 |
| tablespaceUsedPct | Tablespace | xsd:decimal | 表空间使用率（SHACL约束 0~100） |
| volumeUtilPct | StorageVolume | xsd:decimal | 存储卷使用率 |
| alertCode | AlertEvent | xsd:string | 告警编码（字典见附录A） |
| alertLevel | AlertEvent | xsd:string | 紧急/严重/警告 |
| escalatedLevel | AlertEvent | xsd:string | **升级后级别**【V2.0新增：替代非法的 setAlertLevel】 |
| alertTimestamp | AlertEvent | xsd:dateTime | 告警发生时间 |
| derivedFromCode | AlertEvent | xsd:string | 衍生来源状态码（如 TABLESPACE_FULL） |
| evidenceChain | AlertEvent | xsd:string | **证据链**（命中规则ID+输入事实，JSON）【V2.0新增】 |
| metricName | Metric | xsd:string | 指标名【V2.0新增：A3引用】 |
| metricValue | Metric | xsd:decimal | 指标当前值 |
| metricThreshold | Metric | xsd:decimal | 指标阈值 |
| tagValue | BusinessTag | xsd:string | 标签值 P0/P1/P2 |
| slaLevel | IT_Resource | xsd:string | SLA等级/RTO/RPO【V2.0新增】 |
| changeWindow | IT_Resource | xsd:string | 允许变更的维护窗口【V2.0新增】 |
| owner | IT_Resource | xsd:string | 责任人/on-call【V2.0新增】 |
| runbookRef | IT_Resource | xsd:string | 处置预案链接【V2.0新增】 |
| compliance | IT_Resource | xsd:string | 合规要求（如等保级别）【V2.0新增】 |
| action | HarnessAction | xsd:string | 安全动作【V2.0新增】 |
| reason | HarnessAction | xsd:string | 拦截/放行理由【V2.0新增】 |
| allowedScope | HarnessAction | xsd:string | 允许操作范围【V2.0新增】 |
| confidence | AlertEvent | xsd:decimal | 根因置信度 0~1【V2.0新增：F3引用】 |
| whitelistRunbook | ChangeEvent | xsd:string | 命中的白名单预案ID【V2.0新增：F1b引用】 |
| overrideApproved | ChangeEvent | xsd:boolean | 紧急破例审批标志【V2.0新增：F4引用】 |

### 4.3 SWRL全局推理规则库（语义规范）

> **语法说明**：Protégé SWRLTab 插件使用；`?` 代表变量；`swrlb` 内置函数。
> **V2.0 形式化约束**：全部为纯合取；一条规则一个 alertCode；所有 L1 规则头显式断言 alertCode；规则头新个体的**物化由运行期规则引擎完成**（§4.4）。
> 规则分为 A-F 六组，按因果域划分。

#### 组A：基础设施层规则（Compute / Storage）

**A1 L1 主机宕机 → 其上所有软件实例不可达**（V2.0：以 SoftwareResource 统一前件，消除析取；补充 alertCode）

```
DatabaseHost(?h) ∧ AlertEvent(?a) ∧ generatedBy(?a,?h) ∧ alertCode(?a,"HOST_DOWN")
∧ SoftwareResource(?i) ∧ hostedOn(?i,?h)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"INSTANCE_UNREACHABLE")
∧ derivedFrom(?a2,?a)
```

**A2a L1 存储卷IO超时 → 数据库IO性能劣化**（V2.0拆分；补充 alertCode 桥接 D3c）

```
StorageVolume(?v) ∧ AlertEvent(?a) ∧ generatedBy(?a,?v) ∧ alertCode(?a,"STORAGE_IO_TIMEOUT")
∧ Datafile(?df) ∧ storedOn(?df,?v) ∧ Tablespace(?ts) ∧ consistOf(?ts,?df)
∧ OracleInstance(?i) ∧ contains(?i,?ts)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"DB_IO_DEGRADED")
∧ derivedFrom(?a2,?a)
```

**A2b L1 存储卷写满 → 数据库写入阻塞**

```
StorageVolume(?v) ∧ AlertEvent(?a) ∧ generatedBy(?a,?v) ∧ alertCode(?a,"STORAGE_FULL")
∧ Datafile(?df) ∧ storedOn(?df,?v) ∧ Tablespace(?ts) ∧ consistOf(?ts,?df)
∧ OracleInstance(?i) ∧ contains(?i,?ts)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"DB_WRITE_BLOCKED")
∧ derivedFrom(?a2,?a)
```

**A3 L3 主机CPU资源耗尽 → 数据库性能候选提示**（V2.0：改用 derivedFromMetric 修复值域违反；仅候选不收敛）

```
DatabaseHost(?h) ∧ Metric(?m) ∧ monitoredBy(?h,?m)
∧ metricName(?m,"CPU_USAGE") ∧ metricValue(?m,?v) ∧ swrlb:greaterThan(?v,95)
∧ OracleInstance(?i) ∧ hostedOn(?i,?h)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"DB_PERF_RISK")
∧ alertLevel(?a2,"WARNING") ∧ derivedFromMetric(?a2,?m)
```

#### 组B：网络层规则（Network）

**B1a L1 交换机端口Down → 主机网络异常**（V2.0拆分）

```
Switch(?sw) ∧ NetworkInterface(?port) ∧ hasPort(?sw,?port)
∧ AlertEvent(?a) ∧ generatedBy(?a,?port) ∧ alertCode(?a,"PORT_DOWN")
∧ NetworkInterface(?nic) ∧ connectedTo(?nic,?port)
∧ DatabaseHost(?h) ∧ hasNic(?h,?nic)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?h) ∧ alertCode(?a2,"NETWORK_ABNORMAL")
∧ derivedFrom(?a2,?a)
```

**B1b L1 端口丢包率过高 → 主机网络异常**

```
Switch(?sw) ∧ NetworkInterface(?port) ∧ hasPort(?sw,?port)
∧ AlertEvent(?a) ∧ generatedBy(?a,?port) ∧ alertCode(?a,"PACKET_LOSS_HIGH")
∧ NetworkInterface(?nic) ∧ connectedTo(?nic,?port)
∧ DatabaseHost(?h) ∧ hasNic(?h,?nic)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?h) ∧ alertCode(?a2,"NETWORK_ABNORMAL")
∧ derivedFrom(?a2,?a)
```

**B2a L2 主机网络异常 → ORA-03113（通信通道EOF，断连类）**

```
DatabaseHost(?h) ∧ AlertEvent(?a) ∧ generatedBy(?a,?h) ∧ alertCode(?a,"NETWORK_ABNORMAL")
∧ OracleInstance(?i) ∧ hostedOn(?i,?h)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"ORA-03113")
∧ derivedFrom(?a2,?a)
```

**B2b L2 主机网络异常 → ORA-12535（TNS操作超时，断连类）**

```
DatabaseHost(?h) ∧ AlertEvent(?a) ∧ generatedBy(?a,?h) ∧ alertCode(?a,"NETWORK_ABNORMAL")
∧ OracleInstance(?i) ∧ hostedOn(?i,?h)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"ORA-12535")
∧ derivedFrom(?a2,?a)
```

**B2c L2 主机网络异常 → ORA-03137（TTC协议内部错误）**

> V2.0修订：03137 本质是 TTC 协议层内部错误，**常伴随网络闪断、空闲连接被中段设备（防火墙/LB）切断出现**，属概率性因果，定为 L2 而非 L1，仅参与异步深度推理。

```
DatabaseHost(?h) ∧ AlertEvent(?a) ∧ generatedBy(?a,?h) ∧ alertCode(?a,"NETWORK_ABNORMAL")
∧ OracleInstance(?i) ∧ hostedOn(?i,?h)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"ORA-03137")
∧ confidence(?a2,0.7) ∧ derivedFrom(?a2,?a)
```

**B3 L1 监听进程宕机 → ORA-12541（TNS:no listener）**（V2.0：移除 12514）

```
OracleListener(?l) ∧ AlertEvent(?a) ∧ generatedBy(?a,?l) ∧ alertCode(?a,"LISTENER_DOWN")
∧ OracleInstance(?i) ∧ dependsOn(?i,?l)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"ORA-12541")
∧ derivedFrom(?a2,?a)
```

**B4 L2 服务未注册/服务名错误 → ORA-12514**（V2.0新增：12514 为"监听存活但不认识该service"，与监听宕机无关）

```
OracleListener(?l) ∧ AlertEvent(?a) ∧ generatedBy(?a,?l) ∧ alertCode(?a,"SERVICE_UNREGISTERED")
∧ OracleInstance(?i) ∧ dependsOn(?i,?l)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"ORA-12514")
∧ derivedFrom(?a2,?a)
```

#### 组C：中间件层规则（Middleware）

**C1 L1 WebServer宕机 → 前端业务访问失败**

```
WebServer(?ws) ∧ AlertEvent(?a) ∧ generatedBy(?a,?ws) ∧ alertCode(?a,"PROCESS_DOWN")
∧ BusinessApplication(?app) ∧ dependsOn(?app,?ws)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?app) ∧ alertCode(?a2,"ACCESS_FAILURE")
∧ derivedFrom(?a2,?a)
```

**C2 L2 AppServer线程池耗尽 → 微服务API超时**

```
AppServer(?s) ∧ AlertEvent(?a) ∧ generatedBy(?a,?s) ∧ alertCode(?a,"THREAD_POOL_EXHAUSTED")
∧ MicroService(?ms) ∧ hostedOn(?ms,?s)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"API_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

**C3 L2 连接池耗尽 → 微服务API超时**（V2.0新增）

```
ConnectionPool(?p) ∧ AlertEvent(?a) ∧ generatedBy(?a,?p) ∧ alertCode(?a,"CONN_POOL_EXHAUSTED")
∧ MicroService(?ms) ∧ usesPool(?ms,?p)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"API_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

#### 组D：数据库层规则（Database）

**D1 L1 表空间使用率>99% → ORA-01653**（V2.0：修复 derivedFrom 指向字符串的类型错误，改用数据属性 derivedFromCode）

```
Tablespace(?ts) ∧ tablespaceUsedPct(?ts,?p) ∧ swrlb:greaterThan(?p,99)
∧ OracleInstance(?i) ∧ contains(?i,?ts)
→ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"ORA-01653")
∧ derivedFromCode(?a,"TABLESPACE_FULL")
```

**D2 L1 归档目的地满 → Oracle数据库挂起**

```
ArchiveLog(?ar) ∧ AlertEvent(?a) ∧ generatedBy(?a,?ar) ∧ alertCode(?a,"ARCHIVE_DEST_FULL")
∧ OracleInstance(?i) ∧ containsArchive(?i,?ar)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?i) ∧ alertCode(?a2,"DB_HANG")
∧ derivedFrom(?a2,?a)
```

**D3a L1 实例宕机 → 依赖的微服务业务报错**（V2.0拆分，桥接 A1/B 组到业务层）

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"INSTANCE_DOWN")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"BUSINESS_ERROR")
∧ derivedFrom(?a2,?a)
```

**D3b L1 数据库挂起 → 依赖的微服务业务报错**

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"DB_HANG")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"BUSINESS_ERROR")
∧ derivedFrom(?a2,?a)
```

**D3c L2 数据库IO劣化 → 依赖的微服务API超时**（V2.0新增：桥接 A2a → 业务层，修复用例02断链）

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"DB_IO_DEGRADED")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"API_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

**D3d L1 实例不可达 → 依赖的微服务业务报错**（V2.0新增：桥接 A1 → 业务层，修复用例03断链）

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"INSTANCE_UNREACHABLE")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"BUSINESS_ERROR")
∧ derivedFrom(?a2,?a)
```

**D3e L2 数据库连接断（ORA-03113）→ 依赖的微服务API超时**（V2.0新增：桥接 B2a → 业务层，修复用例01断链）

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"ORA-03113")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"API_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

**D4 L2 阻塞锁/锁等待 → 依赖的微服务锁超时**（V2.0新增：高频场景 enq:TX）

```
OracleInstance(?i) ∧ AlertEvent(?a) ∧ generatedBy(?a,?i) ∧ alertCode(?a,"BLOCKING_LOCK")
∧ MicroService(?ms) ∧ dependsOn(?ms,?i)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?ms) ∧ alertCode(?a2,"DB_LOCK_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

#### 组E：应用层规则（Application）

**E1a L1 微服务业务错误 → 上层业务应用交易失败**（V2.0拆分）

```
MicroService(?ms) ∧ AlertEvent(?a) ∧ generatedBy(?a,?ms) ∧ alertCode(?a,"BUSINESS_ERROR")
∧ BusinessApplication(?app) ∧ dependsOn(?app,?ms)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?app) ∧ alertCode(?a2,"TRANSACTION_FAILURE")
∧ derivedFrom(?a2,?a)
```

**E1b L1 微服务API超时 → 上层业务应用交易超时**

```
MicroService(?ms) ∧ AlertEvent(?a) ∧ generatedBy(?a,?ms) ∧ alertCode(?a,"API_TIMEOUT")
∧ BusinessApplication(?app) ∧ dependsOn(?app,?ms)
→ AlertEvent(?a2) ∧ generatedBy(?a2,?app) ∧ alertCode(?a2,"TRANSACTION_TIMEOUT")
∧ derivedFrom(?a2,?a)
```

**E2a L1 P0业务交易失败，告警升级为CRITICAL**（V2.0：SWRL无更新语义，改为断言 escalatedLevel；运行期由引擎/SPARQL UPDATE 回写 alertLevel）

```
BusinessApplication(?app) ∧ AlertEvent(?a) ∧ generatedBy(?a,?app) ∧ alertCode(?a,"TRANSACTION_FAILURE")
∧ hasBusinessTag(?app,?tag) ∧ tagValue(?tag,"P0")
→ escalatedLevel(?a,"CRITICAL")
```

**E2b L1 P0业务交易超时，告警升级为CRITICAL**

```
BusinessApplication(?app) ∧ AlertEvent(?a) ∧ generatedBy(?a,?app) ∧ alertCode(?a,"TRANSACTION_TIMEOUT")
∧ hasBusinessTag(?app,?tag) ∧ tagValue(?tag,"P0")
→ escalatedLevel(?a,"CRITICAL")
```

#### 组F：变更与安全联动规则（对接Harness）

**F1 L1 变更操作影响P0资产（非白名单）→ 拦截AI自动执行**（V2.0：dependsOn 方向修正为 ?app→?r；使用已定义的传递属性）

```
ChangeEvent(?c) ∧ targetResource(?c,?r)
∧ BusinessApplication(?app) ∧ dependsOn(?app,?r)
∧ hasBusinessTag(?app,?tag) ∧ tagValue(?tag,"P0")
→ HarnessAction(?h) ∧ action(?h,"BLOCK_AUTO_EXECUTE")
∧ reason(?h,"变更影响P0核心业务，需人工审批")
```

**F1b L1 变更影响P0但命中白名单runbook → 转人工审批通道**（V2.0新增：修复"P0一刀切拦截"）

```
ChangeEvent(?c) ∧ targetResource(?c,?r) ∧ whitelistRunbook(?c,?rb)
∧ BusinessApplication(?app) ∧ dependsOn(?app,?r)
∧ hasBusinessTag(?app,?tag) ∧ tagValue(?tag,"P0")
→ HarnessAction(?h) ∧ action(?h,"REQUIRE_APPROVAL")
∧ reason(?h,"命中白名单预案，一键人审后可自动执行")
```

**F2a L1 根因定位到存储层 → 限制AI仅可操作基础设施**（V2.0拆分析取）

```
AlertEvent(?a) ∧ rootCauseOf(?a,?rc) ∧ StorageVolume(?rc)
→ HarnessAction(?h) ∧ action(?h,"RESTRICT_SCOPE") ∧ allowedScope(?h,"INFRASTRUCTURE_ONLY")
```

**F2b L1 根因定位到网络层 → 限制AI仅可操作基础设施**

```
AlertEvent(?a) ∧ rootCauseOf(?a,?rc) ∧ NetworkResource(?rc)
→ HarnessAction(?h) ∧ action(?h,"RESTRICT_SCOPE") ∧ allowedScope(?h,"INFRASTRUCTURE_ONLY")
```

**F3 L1 根因置信度不足 → 转人工确认而非硬禁**（V2.0新增：防止误收敛锁死有效处置）

```
AlertEvent(?a) ∧ rootCauseOf(?a,?rc) ∧ confidence(?a,?cf) ∧ swrlb:lessThan(?cf,0.8)
→ HarnessAction(?h) ∧ action(?h,"REQUIRE_MANUAL_CONFIRM")
∧ reason(?h,"根因置信度低于0.8，转人工确认")
```

**F4 L1 紧急破例：on-call审批通过 → 放行并审计留痕**（V2.0新增：紧急降级开关）

```
ChangeEvent(?c) ∧ targetResource(?c,?r) ∧ overrideApproved(?c,true)
→ HarnessAction(?h) ∧ action(?h,"ALLOW_WITH_AUDIT")
∧ reason(?h,"on-call紧急破例，全程审计留痕")
```

### 4.4 运行期执行说明（V2.0新增）

SWRL 规则在本方案中是**设计期语义规范**，部署时按以下方式转写执行：

| SWRL 语义 | 运行期实现 |
| --- | --- |
| 规则头生成新告警个体 | 规则引擎（Drools/Jena Rules）物化新 AlertEvent 实例；或 SPARQL CONSTRUCT 生成三元组 |
| `∨` 已拆分多规则 | 规则引擎天然支持多规则并行匹配（RETE 网络） |
| `escalatedLevel` 断言 | 引擎断言后由 SPARQL UPDATE / 应用层回写 `alertLevel` |
| 数值比较 built-in | 引擎内置比较器或流处理窗口函数 |
| 传递闭包（dependsOn） | Neo4j 图遍历 `MATCH path=(a)-[:dependsOn*1..5]->(b)`，深度上限 5 |

**推理编排约束**：推理跳数上限 ≤5；`derivedFrom` 写入幂等去重；已标记根因的实例禁止再被派生（环路检测）；单事件派生告警数 >50 触发熔断，降级为"仅标记不派生"。

### 4.5 告警预处理流水线（V2.0新增：收敛动态维度）

因果推理**之前**，告警流先经预处理（流处理层实现，非 SWRL 职责）：

1. **去重**：同资源 + 同 alertCode + 5min 内重复 → 合并计数；
2. **时间窗关联**：衍生判定要求根因与衍生告警时间差 ≤5min（可配置）；
3. **维护窗抑制**：`changeWindow` 内的资源告警降级为维护通知，不参与收敛与升级；
4. **flapping 抑制**：同一告警 10min 内震荡 ≥3 次 → 聚合为一条"抖动"告警；
5. **风暴阈值**：单根因派生 >20 条时，仅展示根因 + 派生计数，链路详情折叠可查。

---

## 5. 实例层说明 & Oracle试点实例样例

> 实例层：从CMDB、监控平台采集资产、指标、告警，转化为RDF三元组灌入知识库。
> **V2.0补充 Metric 与 BusinessTag 实例**（V1.0 缺失导致 A3/E2/F1 无法复现）。

### 实例1 DatabaseHost

- ID：Host_X3650M4_01
- rdf:type: DatabaseHost（PhysicalServer 子类）
- hostIp: `192.168.10.10`（hasKey）
- hostOs: RockyLinux 8.6
- hostCpuTotal: 16

### 实例2 OracleInstance

- ID：ORCL_01
- rdf:type: OracleInstance
- instanceName: ORCL（hasKey）
- oracleVersion: 11g
- `hostedOn`: Host_X3650M4_01

### 实例3 OracleListener

- ID：LISTENER_ORCL01
- rdf:type: OracleListener
- listenerPort: 1521
- `componentOf`: ORCL_01（反向 hasComponent）
- ORCL_01 `dependsOn` LISTENER_ORCL01

### 实例4 Tablespace

- ID：TS_USERS
- rdf:type: Tablespace
- tablespaceUsedPct: 99.5
- `belongsToInstance`: ORCL_01

### 实例5 Datafile

- ID：df_users01.dbf
- rdf:type: Datafile
- `belongsToTablespace`: TS_USERS
- `storedOn`: LUN_01

### 实例6 StorageVolume

- ID：LUN_01
- rdf:type: StorageVolume
- volumeUtilPct: 85

### 实例7 Metric（V2.0新增：A3 必需）

- ID：Metric_CPU_H01
- rdf:type: Metric
- metricName: CPU_USAGE
- metricValue: 97
- metricThreshold: 95
- Host_X3650M4_01 `monitoredBy` Metric_CPU_H01

### 实例8 BusinessTag（V2.0新增：E2/F1 必需）

- ID：Tag_P0
- rdf:type: PriorityTag
- tagValue: P0
- PayApp `hasBusinessTag` Tag_P0（PayApp slaLevel=RTO 15min，owner=支付运维组，runbookRef=RB-PAY-001）

### 实例9 根因告警

- ID：Alert_Storage_IO
- rdf:type: AlertEvent
- alertCode: STORAGE_IO_TIMEOUT
- alertLevel: 严重
- alertTimestamp: 2026-09-24T08:30:00
- `generatedBy`: LUN_01

### 实例10 衍生告警（推理自动生成，V2.0修正 alertCode 与证据链）

- ID：Alert_Oracle_IO
- rdf:type: AlertEvent
- alertCode: **DB_IO_DEGRADED**（V2.0：与 A2a 规则头一致）
- alertTimestamp: 2026-09-24T08:30:12
- `generatedBy`: ORCL_01
- `derivedFrom`: Alert_Storage_IO
- evidenceChain: `[{"ruleId":"A2a","facts":["LUN_01","df_users01.dbf","TS_USERS","ORCL_01"]}]`

### 5.2 数据同步架构（V2.0新增）

```
CMDB/iTop ──CDC──▶ Kafka(资产变更) ──▶ ETL对齐服务 ──▶ Neo4j(拓扑读模型)
Zabbix/监控 ─────▶ Kafka(指标/告警) ──▶ 告警预处理流水线 ──▶ 规则引擎
                                          │
                                    定时对账任务(每日) ◀── CMDB快照
```

1. **对齐键**：资产唯一 ID（CI_ID）为全局主键，CMDB 为唯一写源，本体库为读模型（CQRS）；
2. **增量同步**：CDC 捕获变更 → Kafka → ETL 服务幂等消费（幂等键=CI_ID+版本号），断链可重放；
3. **脏数据兜底**：入湖前 SHACL 形状校验（如 tablespaceUsedPct∈[0,100]、OracleInstance 必有 hostedOn），不合格拦截并告警；
4. **一致性**：每日对账任务比对 CMDB 快照与图库，差异 >0.1% 触发治理工单。

---

## 6. 跨域测试用例集（12套验收用例）

> 用于本体模型验收、推理引擎验证、平台联调测试。L1/L2自动化回归（CI固化）；L3人工验证。
> **V2.0：修正用例01/02/03/07断链，新增用例11/12验证 B4 与 F1b。**

### 用例01：交换机端口Down，触发ORA-03113，P0支付业务交易超时

- 场景：接入交换机上联端口故障，主机网卡断连，Oracle数据库报ORA-03113，上层支付业务超时。资产标签：支付业务P0
- 注入初始实例&告警：
  1. Switch:S01，Port:Port01，AlertEvent:A01，alertCode=PORT_DOWN，generatedBy=Port01
  2. Host:H01（X3650M4）网卡HostNic01 connectedTo Port01
  3. OracleInstance:ORCL01 hostedOn H01；微服务PayMS dependsOn ORCL01；业务系统PayApp dependsOn PayMS，hasBusinessTag P0
- 触发规则链：**B1a → B2a → D3e → E1b → E2b**；F1、F2b
- 预期推理结果：
  1. 根因告警：A01（交换机端口DOWN）
  2. 衍生告警依次生成：NETWORK_ABNORMAL → ORA-03113 → PayMS API_TIMEOUT → PayApp TRANSACTION_TIMEOUT
  3. PayApp 告警 escalatedLevel=CRITICAL（运行期回写 alertLevel）
- Harness输出：
  - 任何针对ORCL01、PayMS、PayApp的自动变更操作拦截，提示【影响P0业务，需人工审批】
  - 根因判定属于网络层，限制AI仅可操作网络基础设施，禁止执行数据库类自动处置
- 验收标准：告警收敛后只展示根因告警；完整影响链路+证据链可查询；P0自动升级；Harness拦截生效

### 用例02：存储卷LUN IO超时，Oracle IO劣化，业务查询超时

- 场景：存储LUN性能异常IO超时，数据库读写缓慢，上层业务查询超时
- 注入初始：StorageVolume:LUN01，Alert:A02 alertCode=STORAGE_IO_TIMEOUT；Datafile:df01 storedOn LUN01；Tablespace TS01 consistOf df01；ORCL01包含TS01；ReportMS依赖ORCL01（P1业务）
- 触发规则：**A2a → D3c → E1b**
- 预期：根因A02存储IO超时；衍生：DB_IO_DEGRADED → ReportMS API_TIMEOUT → 报表应用 TRANSACTION_TIMEOUT；P1不自动升级
- Harness输出：根因在存储层，禁止AI执行数据库变更，仅允许存储侧操作（F2a）
- 验收：链路完整，告警收敛，无自动阻断（P1业务）

### 用例03：物理服务器主机宕机，主机上Oracle+Tomcat全部不可达

- 场景：数据库物理机硬件故障主机离线，主机上Oracle实例和Tomcat中间件全部停止
- 注入初始：Host:H02，Alert:A03 alertCode=HOST_DOWN；ORCL02、Tomcat01 hostedOn H02；OrderMS依赖ORCL02
- 触发规则：**A1 → D3d → E1a**
- 预期：根因A03主机宕机；衍生：ORCL02 INSTANCE_UNREACHABLE、Tomcat01 INSTANCE_UNREACHABLE、OrderMS BUSINESS_ERROR、订单应用 TRANSACTION_FAILURE
- Harness：所有依赖该主机资产自动变更拦截
- 验收：主机为唯一根因，多个上层资源告警全部标记衍生

### 用例04：Oracle监听进程DOWN，产生ORA-12541连接报错

- 场景：Oracle监听异常停止，应用连接数据库报ORA-12541
- 注入初始：Listener:Lsnr01，Alert:A04 alertCode=LISTENER_DOWN；ORCL03 dependsOn Lsnr01
- 触发规则：**B3**
- 预期：根因监听DOWN；衍生告警 ORA-12541
- Harness：无P0业务则不拦截；提示根因在数据库监听层
- 验收：正确识别监听为根因，数据库连接告警标记衍生

### 用例05：表空间使用率99.5%，触发ORA-01653报错

- 场景：业务表空间持续写满，新数据插入报ORA-01653
- 注入初始：Tablespace TS_USER，tablespaceUsedPct=99.5，属于ORCL04
- 触发规则：**D1**
- 预期：根因表空间满（derivedFromCode=TABLESPACE_FULL）；衍生告警 ORA-01653
- Harness：无跨业务阻断，提示可执行表空间扩容（需人工确认）
- 验收：识别表空间资源超限作为根因

### 用例06：归档日志目的地满，Oracle实例挂起，P0库存业务中断

- 场景：归档磁盘耗尽，数据库挂起，业务请求全部卡住
- 注入初始：ArchiveLog ARC01，Alert:A06 alertCode=ARCHIVE_DEST_FULL；ORCL05 containsArchive ARC01；StockMS依赖ORCL05（P0）
- 触发规则：**D2 → D3b → E1a → E2a**；F1
- 预期：根因归档满；衍生：DB_HANG、StockMS BUSINESS_ERROR、库存应用 TRANSACTION_FAILURE；升级CRITICAL
- Harness：拦截自动操作（F1），P0业务禁止AI自动清理归档
- 验收：P0业务自动升级，Harness拦截生效

### 用例07：WebServer Nginx进程宕机，前端业务访问失败

- 场景：Nginx服务异常退出，外部用户无法访问业务页面
- 注入初始：WebServer Nginx01，Alert:A07 alertCode=PROCESS_DOWN；App01 dependsOn Nginx01
- 触发规则：**C1**（V2.0修正：V1.0标注"C1→E1"不实——C1直接作用于业务应用，不经微服务层）
- 预期：根因Nginx进程DOWN；衍生 App01 ACCESS_FAILURE
- Harness：根因在Web中间件，仅允许中间件操作
- 验收：中间件故障传导至业务层

### 用例08：AppServer Tomcat线程池耗尽，微服务API超时

- 场景：Tomcat线程池耗尽，接口响应超时
- 注入初始：AppServer Tomcat01，Alert:A08 alertCode=THREAD_POOL_EXHAUSTED；UserMS hostedOn Tomcat01；UserApp dependsOn UserMS
- 触发规则：**C2 → E1b**
- 预期：根因Tomcat线程池耗尽；衍生：UserMS API_TIMEOUT → UserApp TRANSACTION_TIMEOUT
- Harness：允许AI尝试重启Tomcat（非P0）
- 验收：识别中间件资源耗尽为根因

### 用例09：主机CPU使用率97%，L3候选规则，提示数据库性能风险

- 场景：主机CPU持续97%，数据库响应变慢，**L3候选规则，不做告警收敛**
- 注入初始：Host:H03，Metric CPU_USAGE metricValue=97（实例7）；ORCL06 hostedOn H03
- 触发规则：**A3**（L3，仅候选假设）
- 预期：**不自动收敛告警**；根因智能体仅将【主机CPU高】放入候选根因列表，由大模型结合时序指标综合判断
- Harness：不触发自动拦截
- 验收：L3规则仅作为候选提示，不参与告警收敛

### 用例10：微服务内部异常，上层业务交易失败（应用层故障）

- 场景：微服务代码异常，抛出业务错误，上层应用交易失败
- 注入初始：MicroService MsgMS，Alert:A10 alertCode=BUSINESS_ERROR；TradeApp dependsOn MsgMS，P1业务
- 触发规则：**E1a**
- 预期：根因是微服务本身；衍生 TradeApp TRANSACTION_FAILURE；不升级CRITICAL
- Harness：根因在应用层，仅限制应用相关操作
- 验收：故障停留在应用域，不会错误向下推导到底层硬件

### 用例11：实例未注册到监听，应用报ORA-12514（V2.0新增）

- 场景：Oracle实例重启后未自动注册到监听，应用连接报 ORA-12514（监听存活但不知道该service）
- 注入初始：Listener:Lsnr02，Alert:A11 alertCode=SERVICE_UNREGISTERED；ORCL07 dependsOn Lsnr02
- 触发规则：**B4**
- 预期：根因服务未注册；衍生 ORA-12514；**不触发 B3**（区分监听宕机与服务未注册）
- Harness：提示处置动作——实例注册（`alter system register`），非P0可自动执行
- 验收：正确区分 12541（监听宕机）与 12514（服务未注册）

### 用例12：归档满+P0业务，命中白名单runbook，转人工审批而非硬拦截（V2.0新增）

- 场景：同用例06归档满导致P0业务挂起，但"清理归档"为标准安全预案 RB-ARCH-001（白名单）
- 注入初始：同用例06 + ChangeEvent:C01，targetResource=ORCL05，whitelistRunbook=RB-ARCH-001
- 触发规则：**D2 → D3b → E1a → E2a**；**F1b**（而非 F1）
- 预期：Harness 输出 REQUIRE_APPROVAL——【命中白名单预案RB-ARCH-001，一键人审后自动执行】，而非硬拦截
- 验收：白名单例外通道生效，P0故障恢复不被一刀切拦截拖慢

> 测试执行建议：试点优先跑用例1、2、4、5、6；每轮测试输出推理链路JSON（含evidenceChain），归档至测试报告；12套用例全部固化为CI回归。

---

## 7. 本体与智能体、Harness安全约束集成架构

### 7.1 整体架构（V2.0重构：设计期/运行期分离）

```
【设计期】                          【运行期】
Protégé + OWL/SWRL                  Kafka ─▶ 告警预处理流水线(去重/时间窗/维护窗/flapping/风暴阈值)
  │  HermiT一致性校验                          │
  │  SHACL形状校验                             ▼
  ▼                              ┌──────────────────────────────┐
OWL语义规范 ──转写──▶ 规则包      │  增量规则引擎(Drools/Jena)    │
（Drools DRL / SPARQL CONSTRUCT） │  L1实时收敛 / L2+L3异步推理   │
                                 └──────┬───────────────┬──────┘
              Neo4j(拓扑依赖图) ◀────────┘               │
              ▲ dependsOn*1..5 遍历                      ▼
              │                              ┌──────────────────────┐
     ETL对齐服务(CDC+Kafka,CQRS)              │ 推理编排服务          │
              ▲                              │ 深度≤5/环路检测/熔断/降级│
         CMDB(iTop)                          └──────┬────────┬───────┘
                                                    ▼        ▼
                                       告警监控智能体  根因专家智能体  Harness安全约束
```

### 7.2 智能体 ↔ 规则映射表（V2.0更新）

| 智能体/模块 | 订阅规则组 | 规则级别 | 核心消费目的 | 输出物 |
| --- | --- | --- | --- | --- |
| 告警监控智能体 | A1,A2a,A2b,B1a,B1b,B3,C1,D1,D2,D3a,D3b,D3d,E1a,E1b,E2a,E2b | L1 | 实时告警收敛，标记衍生告警，抑制风暴 | 清洗后的告警流，标记根因/衍生 |
| 根因专家智能体 | 全部L1 + B2a/B2b/B2c,B4,C2,C3,D3c,D3e,D4 + A3(L3候选) | L1+L2+L3候选 | 全链路根因推理，生成故障传导路径与证据链 | 根因结论、上下游影响链路、候选根因清单、置信度 |
| Harness安全约束模块 | F1,F1b,F2a,F2b,F3,F4 | L1 | 变更/AI自动处置风险评估，拦截/例外/破例 | 风险判定、阻断指令、操作范围限制、审计记录 |

### 7.3 故障发生调用时序（V2.0更新）

1. 监控采集指标、原始告警，写入 Kafka；
2. **告警预处理流水线**：去重 → 时间窗关联 → 维护窗抑制 → flapping聚合 → 风暴阈值（§4.5）；
3. **告警监控智能体**：触发L1实时推理（增量规则引擎），标记衍生告警，抑制告警风暴；
4. **根因专家智能体**：异步执行L1/L2/L3深度推理 + Neo4j 依赖遍历，生成故障传导链路、证据链与置信度；
5. **Harness安全约束**：读取推理结果与置信度，执行F组规则（含白名单例外/破例），输出AI操作权限策略；
6. 运维前端展示：根因、影响范围、证据链、安全操作边界，供运维人员处置。

> 降级策略：推理引擎超时/异常时，**透传原始告警 + 标注"推理不可用"**，绝不阻塞监控主链路。

### 7.4 集成接口契约（V2.0新增）

**推理结果 Schema（JSON-LD）**：

```json
{
  "rootCause": { "id": "Port01", "type": "NetworkInterface", "alertCode": "PORT_DOWN" },
  "derivedChain": [
    { "ruleId": "B1a", "alertId": "A11", "alertCode": "NETWORK_ABNORMAL", "resource": "H01" },
    { "ruleId": "B2a", "alertId": "A12", "alertCode": "ORA-03113", "resource": "ORCL01" },
    { "ruleId": "D3e", "alertId": "A13", "alertCode": "API_TIMEOUT", "resource": "PayMS" }
  ],
  "confidence": 0.95,
  "evidence": ["Port01.PORT_DOWN@T0", "HostNic01.connectedTo.Port01"],
  "escalated": ["PayApp:CRITICAL"]
}
```

- 本体查询 API：GraphQL / gRPC，返回 JSON-LD；幂等键 = 事件ID + 规则版本号；
- 事件订阅：Kafka topic 按规则组划分，携带规则包版本号，支持灰度比对；
- Harness 策略查询：输入变更目标 + 操作类型，输出 action/reason/allowedScope/审计ID。

---

## 8. 落地实施WBS与分阶段上线计划（V2.0重构）

### Phase 0：CMDB数据治理（前置，2周）【V2.0新增】

1. 资产唯一 ID（CI_ID）清洗与去重
2. 依赖关系补全（主机-实例-表空间-存储链路）
3. 数据质量基线评估与SHACL校验规则落地
4. 输出：数据质量报告、可灌入资产清单

### Phase 1：试点阶段（Oracle数据库域，6周）

1. 环境准备：Protégé建模环境 + HermiT校验 + 规则引擎/Neo4j 选型验证与压测基线
2. 本体建模：导入顶层Class、对象/数据属性、A/B/D组规则，HermiT一致性校验通过
3. **ETL与增量同步开发**（CDC+Kafka+对账）【V2.0新增】
4. **集成契约定义与评审**（API Schema、事件Schema、幂等约定）【V2.0新增】
5. 隔离试点环境搭建（影子库并行，不接生产告警）【V2.0新增】
6. 资产实例灌入：X3650M4服务器、存储LUN、Oracle实例、表空间等样本实例
7. 测试验证：执行用例1,2,4,5,6，验证推理正确性与证据链完整性
8. 联调：对接告警监控智能体，验证告警收敛效果与降级策略
9. 输出：试点本体OWL文件、规则包、压测报告、测试报告

### Phase 2：一期扩展（网络+中间件，6周）

1. 扩充Class：交换机、网卡、负载均衡、Nginx/Tomcat/连接池
2. 新增B、C组SWRL规则并转写规则包
3. **推理可观测与降级上线**（Prometheus指标：推理耗时/规则命中率/收敛率）【V2.0新增】
4. **规则热更新与灰度**（影子推理双版本比对后切流）【V2.0新增】
5. 全量回归测试（CI固化），新增网络故障类用例
6. 联调根因智能体，打通网络→数据库故障链路（ORA-03113场景）

### Phase 3：二期全域（应用层+K8s，8周）

1. 新增微服务、业务应用、K8sPod Class，E组规则完善
2. 全量CMDB资产批量灌入本体
3. Harness安全模块全量对接，F组安全规则上线（含白名单/破例通道）
4. 全量12个用例回归验收
5. **运维培训与SOP交付**（规则维护、知识沉淀手册）【V2.0新增】
6. **回滚与应急预案演练**（推理库异常回退CMDB直读）【V2.0新增】
7. 上线业务影响分析能力

---

## 9. 模型治理与运维规范

1. **规则入库评审**：新增SWRL规则，运维专家+知识工程师双签，标注级别、上下游、服务智能体；强制满足形式化约束（纯合取、一规则一码、L1必赋alertCode）。
2. **一致性校验**：HermiT 定时执行本体一致性检查；**SHACL 形状校验**拦截脏实例（示例：tablespaceUsedPct∈[0,100]，OracleInstance 必有 hostedOn）。
3. **规则分级隔离**：L3候选规则不参与实时告警收敛，仅异步查询。
4. **版本管理与灰度**：本体OWL模型、SWRL规则、规则包三件套版本化；故障复盘沉淀新规则走版本发布；影子推理比对后切流；旧规则标记deprecated保留历史追溯。
5. **规则单元测试**：每条规则配正例+负例（示例：B3 注入 LISTENER_DOWN 期望推出 ORA-12541；负例注入 SERVICE_UNREGISTERED 期望**不**推出 12541）；12套用例CI固化，规则变更自动回归。
6. **数据质量巡检**：定时校验CMDB灌入实例，缺失依赖关系、属性异常告警，每日对账。
7. **性能管控**：在线推理只启用L1；推理跳数≤5；L2/L3异步计算；监控推理耗时/命中率/收敛率指标。

---

## 10. 风险与约束说明（V2.0补全）

1. **本体只做确定性因果推理**：随机偶发故障（瞬时网络抖动）本体无法直接判定，需结合时序异常检测+大模型综合研判。
2. **实例数据质量强依赖CMDB**：CMDB资产依赖关系缺失、错误会直接导致推理链路错误——**Phase 0 数据治理是硬前置**，治理不达标不得进入Phase 1。
3. **推理性能约束**：类与规则持续膨胀降低推理速度；严格执行最小本体原则、跳数上限与熔断；每Phase做压测。
4. **规则边界**：SWRL适合静态因果传导；复杂概率性故障诊断交给大模型，本体不承担全部诊断工作。
5. **组织协同成本【新增】**：规则维护需要运维专家+知识工程师长期投入，需明确规则治理的R&R。
6. **CMDB治理长期成本【新增】**：依赖关系补全不是一次性工作，需纳入日常CMDB运营KPI。
7. **厂商/技术锁定【新增】**：本体层保持标准OWL，运行期规则引擎可替换（Drools/Jena/自研RETE），避免与单一推理机绑定。
8. **知识沉淀【新增】**：故障复盘→新规则的转化流程需制度化，防止规则库停滞腐化。

---

## 附录A　告警码字典（V2.0新增）

| 告警码 | 含义 | 因果级别 | 典型根因 |
| --- | --- | --- | --- |
| HOST_DOWN | 主机宕机/离线 | 根因 | 硬件故障、断电、OS崩溃 |
| STORAGE_IO_TIMEOUT | 存储卷IO超时 | 根因 | 存储性能劣化、链路异常 |
| STORAGE_FULL | 存储卷写满 | 根因 | 容量耗尽 |
| PORT_DOWN | 交换机端口Down | 根因 | 链路/光模块/对端故障 |
| PACKET_LOSS_HIGH | 端口丢包率过高 | 根因 | 链路质量、拥塞 |
| NETWORK_ABNORMAL | 主机网络异常 | 衍生(L1) | 交换机端口故障 |
| ORA-03113 | 通信通道EOF（连接中断） | 衍生(L2) | 网络闪断、会话被切断 |
| ORA-12535 | TNS操作超时 | 衍生(L2) | 网络不通、防火墙拦截 |
| ORA-03137 | TTC协议内部错误 | 衍生(L2，概率性) | 常伴网络闪断/空闲连接被中段设备切断 |
| ORA-12541 | TNS:no listener | 衍生(L1) | 监听进程宕机 |
| ORA-12514 | 监听不认识该service | 衍生(L2) | 实例未注册/服务名错误 |
| ORA-01653 | 表空间无法扩展 | 衍生(L1) | 表空间使用率>99% |
| DB_HANG | 数据库挂起 | 衍生(L1) | 归档目的地满 |
| DB_IO_DEGRADED | 数据库IO性能劣化 | 衍生(L1) | 存储IO超时 |
| DB_WRITE_BLOCKED | 数据库写入阻塞 | 衍生(L1) | 存储卷写满 |
| INSTANCE_DOWN | 数据库实例宕机 | 根因/衍生 | 实例崩溃或主机宕机 |
| INSTANCE_UNREACHABLE | 实例不可达 | 衍生(L1) | 主机宕机 |
| BLOCKING_LOCK | 阻塞锁/锁等待 | 根因 | 长事务、死锁 |
| DB_LOCK_TIMEOUT | 锁等待超时 | 衍生(L2) | 阻塞锁传导 |
| LISTENER_DOWN | 监听进程宕机 | 根因 | 监听进程异常退出 |
| SERVICE_UNREGISTERED | 服务未注册到监听 | 根因 | 实例未注册/动态注册失败 |
| ARCHIVE_DEST_FULL | 归档目的地满 | 根因 | 归档磁盘耗尽 |
| PROCESS_DOWN | 进程宕机 | 根因 | 进程异常退出 |
| THREAD_POOL_EXHAUSTED | 线程池耗尽 | 根因 | 流量突增、慢请求堆积 |
| CONN_POOL_EXHAUSTED | 连接池耗尽 | 根因 | 连接泄漏、慢SQL |
| API_TIMEOUT | 接口超时 | 衍生 | 中间件/数据库资源耗尽 |
| ACCESS_FAILURE | 业务访问失败 | 衍生(L1) | WebServer宕机 |
| BUSINESS_ERROR | 微服务业务错误 | 衍生/根因 | 数据库不可用或代码异常 |
| TRANSACTION_FAILURE | 业务交易失败 | 衍生(L1) | 微服务业务错误 |
| TRANSACTION_TIMEOUT | 业务交易超时 | 衍生(L1) | 微服务API超时 |
| DB_PERF_RISK | 数据库性能风险（候选） | L3候选 | 主机资源耗尽嫌疑 |

---

*V2.0 修订依据：《智能运维IT资产本体建模方案_三方专家评审报告》（2026-09-23），覆盖全部 P0 项（8/8）、P1 项（6/6）、P2 项（3/3）。*

---

## 平台落地对照（轻量化实施 V1）

> 2026-09 实施记录。V2.0 本体思想在 SxDevOps 的轻量化落地：不引入 Neo4j/Kafka/Drools/OWL 工具链，保持单容器轻部署（MySQL/SQLite + Redis）。

### 概念层对照

| 本体（V2.0） | 平台落点 |
| --- | --- |
| Class 类体系 | CMDB `CIType` 增加 parent 层级 / layer / is_abstract；存储域与数据库组件（存储卷/表空间/数据文件/归档日志/Oracle监听/Oracle实例）为平台自定义 CI 类型（iTop 无标准类） |
| 对象属性注册 | `RelationType` 关系类型注册表：code/display_name/color/line_style/direction（forward=source impacts target）/allowed 类型约束/ontology_property |
| 互斥/唯一性公理 | 关系类型 allowed_source_types/allowed_target_types 校验；(source, target, relation_type) 唯一约束 |

### 语义层对照

| 本体属性 | RelationType code | iTop 来源（3.0.4 盘点） |
| --- | --- | --- |
| dependsOn（传递） | depends_on | lnkApplicationSolutionToFunctionalCI / lnkApplicationSolutionToBusinessProcess / impacts / depends on / WebServer.webapp_list |
| hostedOn | hosted_on / runs_on | VirtualizationSystem.virtualmachines_list / Middleware.middlewareinstance_list |
| contains | contains | DBServer.dbschema_list（LinkedSet，映射常量已备，拉取路径后续版本接入） |
| connectedTo（对称） | connects_to | lnkConnectableCIToNetworkDevice / lnkSubnetToVLAN / lnkPhysicalInterfaceToVLAN |
| owner（数据属性） | ConfigItem.attributes.owner_group/owner_contact | lnkGroupToCI / lnkContactToFunctionalCI |
| runbookRef（数据属性） | ConfigItem.attributes.document_refs | lnkDocumentTo* |

iTop 同步：`cmdb/itop_sync.py` ITOP_RELATION_MAP（13 个 lnk 类全量映射 + 数据属性模式 + 可选清理 relation_cleanup）。

### 运行期对照

| V2.0 §4.3/4.4 | 平台实现 |
| --- | --- |
| L1 确定性收敛（实时） | `ops/alert_causality.py` 规则引擎：AlertCausalRule 数据规则（B3/D1/D2/D2b/D3/B1/B2 默认种入）、webhook 与 Zabbix 轮询双路径同步挂载、时间窗 ±5min、图上溯 ≤5 跳、环检测、>20 节点熔断 |
| L2/L3 概率诊断 | 现有 LLM 根因分析流（query_alert_root_cause）：`_infer_alert_root_cause` 新增 causal_chain（L1 结论）与 hypotheses（受影响范围）键，提示词约定"L1 不可推翻、L2 假设标注置信度" |
| 传递闭包遍历 | `aiops/knowledge_graph/_impl.py` find_graph_paths：≤5 跳 DFS + 环剪枝 + 路径数熔断 + Redis 缓存；服务 query_knowledge_graph_closure（工具 sxdevops.query_knowledge_graph_closure） |
| evidenceChain | Alert.evidence_chain JSON（rule_code/relation_code/path/root_code/at），根因/派生标记 causal_level + derived_from |
| §4.5 预处理流水线 | 复用 03B 管道（去重/维护窗静默/升级）；flapping 由 occurrence_count 阈值跳过 |
| 告警码字典 | `ops/alert_causality.py` ALERT_CODE_DICTIONARY（附录 A 31 条 + TABLESPACE_FULL），`backfill_alert_codes` 命令回填存量告警 |

### 边界（本期）

- F 组安全联动：仅落数据+文档（AlertCausalRule 预留 notes/priority 字段），不接自动执行拦截
- iTop 侧不改动；LinkedSet 拉取路径后续版本接入；真实生产数据治理不在本期
- 演示：Oracle 域故事线（seed_oracle_domain + Zabbix 演示问题 5 条，对应用例 04/05）
