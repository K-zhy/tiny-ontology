# Palantir Foundry Ontology（本体）详解

---

## 一、先说人话：Ontology 到底是个什么东西？

想象你是一家航空公司，你的数据库里有几千张表：

- `flight_schedule_2024` — 航班时刻表
- `aircraft_maintenance_log` — 飞机维修记录
- `crew_roster` — 机组排班表
- `passenger_booking_v3` — 乘客订票记录
- `airport_info` — 机场信息表

每张表都有几十个列，列名都是 `ac_id`、`dept_stn_cd`、`pax_cnt` 这种缩写。技术人员写 SQL 要 JOIN 五六张表才能回答「这架飞机的下一个航班是什么？」；业务人员完全看不懂，只能等 IT 部门出报表。

**Ontology 做的事情，就是在这些原始数据表之上，构建一个用「业务语言」描述的世界模型。**

你不再看到表和列，而是看到：
- **对象**：`航班`、`飞机`、`机场`、`机组`、`乘客`
- **关系**：航班 `由...执飞` 飞机、机组 `被分配到` 航班、乘客 `预订了` 航班
- **操作**：`取消航班`、`更换飞机`、`重新分配机组`
- **计算**：`航班准点率`、`飞机累计飞行小时`、`航线盈利分析`

**一句话总结：Ontology 是企业的数字孪生（Digital Twin），它把冷冰冰的数据表变成了有业务含义的「知识图谱」。**

---

## 二、Ontology 在整个 Foundry 平台中的位置

```
┌──────────────────────────────────────────────────┐
│                  应用层 (Apps)                     │
│    Workshop · OSDK · REST API · AIP Agent         │
├──────────────────────────────────────────────────┤
│              ★ Ontology (本体层) ★                │
│    Object Types · Link Types · Action Types       │
│    Functions · Interfaces                         │
├──────────────────────────────────────────────────┤
│              数据集成层 (Data Integration)          │
│    Pipeline Builder · Transforms · Data Lineage   │
├──────────────────────────────────────────────────┤
│              存储层 (Storage)                      │
│    Datasets · Files · Streaming                   │
└──────────────────────────────────────────────────┘
```

**关键认知**：Ontology 是平台中间层，它在原始数据集之上把数据"翻译"成业务对象，然后上层的所有应用（Workshop 低代码应用、自定义 TypeScript 应用、AI Agent）都通过 Ontology 来访问和修改数据，而不是直接去读数据表。

---

## 三、Ontology 的五大核心组件

Ontology 有**五个"一等公民"（First-Class Citizens）**：

### 3.1 Object Type（对象类型）— 知识图谱的「细胞」

**定义**：Object Type 是真实世界中某个实体或事件的数据模式定义。一个 Object（对象）是 Object Type 的一个具体实例。

**类比**：如果 Object Type = **类（Class）**，Object = **实例（Instance）**

**举例**：
| Object Type（对象类型） | Object（具体对象） |
|---|---|
| `Airport`（机场） | JFK、LHR、PEK、NRT |
| `Flight`（航班） | CA1234 (2024-03-15 PEK→SHA) |
| `Employee`（员工） | 张三、李四、王五 |
| `Aircraft`（飞机） | B-1234（注册号）、B-5678 |
| `WorkOrder`（工单） | WO-2024-001234、WO-2024-001235 |

每个 Object Type 有四个层面：

```
┌─────────────────────────────────────┐
│         元数据层 (Metadata)          │
│  API名称 · 显示名 · 描述 · 图标      │
├─────────────────────────────────────┤
│         属性层 (Properties)          │
│  主键 · 普通属性 · 派生属性          │
├─────────────────────────────────────┤
│        数据源层 (Data Sources)       │
│  主数据集 + 补充数据集（≤3个）        │
├─────────────────────────────────────┤
│         安全层 (Security)            │
│  对象级 · 列级 · 行级权限管控         │
└─────────────────────────────────────┘
```

**三种属性类型**：

| 类型 | 说明 | 示例 |
|------|------|------|
| **主键（Primary Key）** | 唯一标识，不可为空，建议用 UUID | `flight_id = "uuid-1234"` |
| **普通属性（Regular）** | 业务字段，有明确数据类型和描述 | `departure_time`、`status`、`capacity` |
| **派生属性（Derived）** | 由 Function 动态计算，可设缓存 TTL | `on_time_rate`（准点率）、`total_fly_hours` |

**数据源映射**：一个 Object Type 通常由一个**主数据集**（Backing Dataset）提供，最多可以关联 3 个**补充数据集**来丰富属性。这意味着一张或多张原始数据表被"封装"成了一个语义对象。

**设计最佳实践**：
- API 名用 **snake_case**，创建后**永不变更**（不可逆操作）
- 主键优先使用**无意义的 UUID**（而非业务字段如身份证号），避免业务规则变化时大规模迁移
- 描述字段写清楚，**这是 AI Agent 理解业务语义的关键入口**
- 高频访问的派生属性要**开启缓存**

---

### 3.2 Link Type（链接类型）— 知识图谱的「骨架」

**定义**：Link Type 是两个 Object Type 之间**带语义的关系**的模式定义。一个 Link 是两个具体 Object 之间该关系的一个实例。

**核心区别——它不只是外键**：
```
传统数据库外键：        flight.aircraft_id → aircraft.id （只是一个字段引用）
Ontology Link Type：    Flight ──[operated_by]──▶ Aircraft （有名称、有方向、有基数、有安全权限、有属性）
```

**举例**：

| Link Type | 源对象 | 目标对象 | 语义 |
|---|---|---|---|
| `operated_by`（执飞） | Flight | Aircraft | 航班由哪架飞机执飞 |
| `assigned_to`（分配到） | Crew | Flight | 机组被分配到哪个航班 |
| `supervised_by`（汇报给） | Employee | Employee | 自引用——下属汇报给经理 |
| `part_of`（属于） | Part | Assembly | 零件属于哪个装配件 |
| `booked_on`（预订了） | Passenger | Flight | 乘客预订了哪个航班 |

**八个核心配置维度**：

| 维度 | 说明 |
|------|------|
| **基数（Cardinality）** | 一对一、一对多、多对多。既是校验规则，也是图遍历的优化提示 |
| **方向性（Directionality）** | 单向（员工→经理）、无向、双向对称 |
| **源和目标类型** | 两端必须都是已注册的 Object Type；同一对 Object Type 之间可以有多个不同的 Link Type |
| **数据源映射** | 80% 的情况用外键映射；多对多或带属性的 Link 用关联表（Join Table）；少量跨数据集推断 |
| **独立安全（ACL）** | Link 有自己的权限控制——可以做到"能看到 Flight 对象和 Aircraft 对象，但看不到它们之间的 operated_by 关系" |
| **链接属性（Link Properties）** | Link 可以携带自己的属性（见下文） |
| **两端显示名** | Link 在两端可以有不同的显示名：Flight 端叫"飞机"，Aircraft 端叫"航班列表" |
| **API Name** | 编程名，如 `Flight.aircraft.get()` |

**链接属性（Link Properties）**——这是一个核心差异化能力：

传统的中间表只在 JOIN 时出现，但在 Ontology 中，关系的属性是一等公民。例如：
```
Employee ──[assigned_to]──▶ Project
              ├─ role: "后端开发"
              ├─ hours_per_week: 20
              └─ start_date: "2024-01-15"
```
`role`、`hours_per_week`、`start_date` 属于这个 **关系本身**，而不是 Employee 或 Project 的属性。这些属性支持筛选、排序和聚合。

**设计最佳实践**：
- **语义优先命名**：用 `supervised_by`、`part_of`、`assigned_to`，而不是 `emp_mgr_fk`
- **不要复用一个 Link 表达多重含义**：如果需要表达"行政汇报"和"专业指导"两种关系，应该创建两个不同的 Link Type
- **多对多要审慎**：多对多遍历开销最大，如果数据量很大，需要提前考虑分页和缓存策略
- **善用链接属性**：把关系级别的元数据放在 Link 上，而不是额外创建中间 Object Type（除非中间对象本身有独立存在的业务意义）

---

### 3.3 Action Type（操作类型）— 知识图谱的「肌肉」

**定义**：Action Type 让 Ontology 从"只读"变为"可写"，它是修改对象和关系的执行单元，实现**数据回写（Write-back）**。

**一句话：如果 Object Type 是名词、Link Type 是动词，那 Action Type 就是「祈使句」——"取消这个航班"、"更换飞机"、"创建工单"。**

**七步执行流程**：

```
用户点击「取消航班」
  │
  ▼
① 表单渲染 —— 展示确认界面，含预填数据和可选参数
  │
  ▼
② 前端校验 —— 即时检查必填项、格式、跨字段规则
  │
  ▼
③ 请求提交 —— 加密传输，携带用户身份信息
  │
  ▼
④ 服务端权限校验 —— 双重验证：操作权限 + 目标对象修改权限
  │
  ▼
⑤ 后端业务校验 —— 通过 TypeScript Function 实现复杂校验
  │   例如：航班已起飞 → 不能取消
  │
  ▼
⑥ 事务性执行 —— 修改对象、修改链接、触发 Webhook（原子化：全成或全败）
  │
  ▼
⑦ 审计日志 —— 自动记录：谁、什么时间、做了什么操作、参数、结果（不可篡改）
```

**六大 Action 分类**：

| 类型 | 用途 | 示例 |
|------|------|------|
| **Object Actions** | 创建/修改/删除对象 | `创建工单`、`修改航班状态` |
| **Link Actions** | 建立/移除对象间关系 | `分配机组到航班`、`更换飞机` |
| **Function Actions** | 由 Function 提供复杂逻辑 | `批量审批`、`风险评估` |
| **Webhook Actions** | 触发外部系统集成 | `同步到 SAP`、`通知第三方物流` |
| **Interface Actions** | 基于 Interface 的多态操作 | `审核`（适用于所有实现了 "Auditable" 接口的对象） |
| **Notification Actions** | 触发通知 | `发送邮件/短信提醒` |

**两种 Webhook 执行模式**：

| | 回写 Webhook | 副作用 Webhook |
|---|---|---|
| **执行时机** | 本体变更**之前** | 本体变更**之后** |
| **失败影响** | 失败则回滚所有更改 | 失败不影响已完成的本体变更 |
| **适用场景** | 跨系统事务一致性 | 通知、日志、非关键同步 |

---

### 3.4 Function（函数）— 知识图谱的「大脑」

**定义**：Function 是 Ontology 的原生计算层，将"推理能力"嵌入知识图谱，让数据从被动查询变为**主动计算、推理和预警**。

**四大函数类型**：

| 类型 | 触发方式 | 用途 | 示例 |
|------|----------|------|------|
| **Object Function** | 对单个对象调用 | 计算派生属性、调用 AI 模型 | 计算航班准点率、生成客户评分 |
| **Object Set Function** | 对对象集合调用 | 批量计算、聚合分析（自动下沉 Spark） | 统计航线盈利能力、批量风险评分 |
| **Action Validation Function** | Action 提交前触发 | 校验复杂业务规则 | 「航班已起飞则禁止取消」 |
| **Query Function** | 前端/API 显式调用 | 复杂计算、自定义 API | 路线规划、推荐引擎 |

**关键能力**：
- Functions 运行在**托管沙盒**中，安全隔离
- Object Function 的结果可作为**虚拟属性**（派生属性）在全平台复用
- Object Set Function 大规模计算自动下沉 **Spark 集群**
- 支持配置**缓存策略**，高频查询的结果可以缓存减少重复计算

---

### 3.5 Interface（接口）— 知识图谱的「抽象契约」

**定义**：Interface 定义一个**跨对象的共享能力契约**。它不是具体的实体，而是规定"必须有什么属性、能做什么操作"。

**核心价值——解决什么问题**：

假设你有三种对象：`卡车`、`飞机`、`叉车`，它们来自不同的部门、不同的数据源，但你需要在统一的"资产盘点"页面查看所有可折旧资产，并执行统一的"报废"操作。

传统做法：为每种对象各写一套页面和操作。新增一种资产类型（如 `船舶`）就要重新开发。

Interface 做法：

```
Interface: DepreciableAsset（可折旧资产）
  ├─ 共享属性: purchase_date, purchase_price, useful_life, current_value
  ├─ 共享 Action: 开始折旧, 报废
  │
  ├─ 实现者: 卡车, 飞机, 叉车, 船舶（新增）
  │
  └─ 通用界面: 「所有可折旧资产」自动聚合四类对象的数据
```

**Interface vs 传统的继承**：

| | 继承（Inheritance） | Interface（接口） |
|---|---|---|
| 关系本质 | 「是什么」的层级（猫→动物） | 「能做什么」的资格（猫、机器人、桌子都可以「有主人」） |
| 实现方式 | 单继承 | 多实现 |
| 耦合度 | 紧耦合 | 解耦 |
| 扩展性 | 改父类影响所有子类 | 新增实现者不影响已有代码 |

**设计原则**：
- 聚焦**能力**而非数据——描述"能做什么"，不是"是什么"
- 单一职责——每个 Interface 只定义一组相关能力
- **真正出现共性之前不强行抽象**

---

## 四、Ontology 的三层架构

Palantir 的 Ontology 架构分为三个逻辑层：

```
┌─────────────────────────────────────────────────┐
│              动态层 (Dynamic Layer)               │
│  决策引擎 · AI 模型绑定 · 多步模拟 · 审计追踪       │
│  回答："我们应该采取什么行动？"                      │
├─────────────────────────────────────────────────┤
│              动力层 (Kinetic Layer)               │
│  Action Types · Functions · 校验规则 · Webhooks    │
│  回答："我们能对数据做什么操作？"                     │
├─────────────────────────────────────────────────┤
│              语义层 (Semantic Layer)              │
│  Object Types · Link Types · Properties            │
│  Interfaces · 共享合约                             │
│  回答："企业里存在什么？它们之间什么关系？"            │
└─────────────────────────────────────────────────┘
```

这对应了 Palantir 的哲学三阶段——**本体论 → 认识论 → 实践论**：

| 层 | 哲学对应 | 核心问题 | Palantir 实现 |
|---|---|---|---|
| 语义层 | **本体论**（Ontology） | 什么存在？ | Object Types + Link Types |
| 动力层 | **认识论**（Epistemology） | 我们如何知道/判断？ | Functions + Action Types |
| 动态层 | **实践论**（Praxis） | 我们如何行动？ | AIP 决策循环 → 提案 → 人工审核 → 执行 → 审计 |

---

## 五、与传统架构的关键区别

| 维度 | 传统企业架构（数据库 + 应用） | Palantir Ontology |
|---|---|---|
| **数据建模** | 表和列（Table/Column） | 对象和属性（Object/Property） |
| **数据关系** | 外键（Foreign Key）— 无业务语义 | Link Type — 有名称、方向、基数、权限、属性 |
| **业务逻辑** | 散落在各应用的 Service 层 | 集中在 Ontology 的 Action + Function |
| **权限控制** | 在应用层实现，各系统不一致 | 在 Ontology 层统一执行，每次都检查 |
| **数据写入** | 各自写数据库，难以追溯 | 通过 Action 统一入口，全审计 |
| **跨系统语义** | 每个系统有自己的理解（"客户"在 CRM 和 ERP 含义不同） | 统一语义层，所有系统共享同一套定义 |
| **AI 接入** | AI 需要理解每张表、每个列的含义 | AI 直接感知 Ontology 的对象、关系和操作 |
| **编程模型** | `SELECT * FROM table WHERE ...` | `Flight.where(status='active').aircraft.get()` |

---

## 六、Ontology 与 AI（AIP Agent）的关系

这是 Palantir 近期最重要的演进方向——**Ontology Augmented Generation (OAG)**：

```
用户：「帮我查一下这架飞机接下来还有几个航班？」

传统 LLM 方式：
  LLM → 猜 SQL → SELECT * FROM flight WHERE aircraft_id=... → 拼结果回复

OAG 方式：
  LLM → 感知 Ontology：
    - 存在 Aircraft 对象，有 operated_by → Flight 的关系
    - Flight 有 status, departure_time 属性
    - 可以调用 getUpcomingFlights() Function
  → 生成 Proposal：「查询 B-1234 的 upcoming flights」
  → 人工审核 → 执行 → 返回结果
```

**关键差异**：
- LLM 不是在猜表结构和 SQL，而是在理解**业务世界模型**
- 所有操作受 Ontology **权限管控**，不会出现数据泄露
- 生成的结果是可审计的——谁、何时、做了什么
- **Proposal → Human Review → Action → Audit** 形成了一个安全的闭环

---

## 七、数据如何变成 Ontology？—— 一个端到端的例子

假设你要在 Foundry 里搭建航空公司的 Ontology：

### 第 1 步：接入原始数据
```
Source System → Data Connection → Dataset

SAP    → Connector → raw_flight_schedule  (CSV/Parquet)
MRO    → Connector → raw_aircraft_info    (JSON)
HR     → Connector → raw_crew_data        (Database)
```

### 第 2 步：数据清洗和转换
```
Pipeline Builder / Python Transforms

raw_flight_schedule → cleaned_flight_schedule
  (清洗、标准化、去重、合并)
```

### 第 3 步：映射为 Ontology Object
```
Ontology Manager:

cleaned_flight_schedule → Object Type: Flight
  - flight_id   → Primary Key
  - flight_no   → Property: 航班号
  - dept_time   → Property: 出发时间
  - status      → Property: 状态
  - aircraft_id → 通过 Link Type [operated_by] 关联到 Aircraft

raw_aircraft_info → Object Type: Aircraft
  - tail_number  → Primary Key
  - model        → Property: 机型
  - total_hours  → Derived Property (由 Function 计算)
```

### 第 4 步：定义关系和操作
```
Link Types:
  Flight ──[operated_by]──▶ Aircraft         (一对多)
  Crew   ──[assigned_to]──▶ Flight           (多对多，带 link property: role)
  Flight ──[departs_from]─▶ Airport          (一对多)

Action Types:
  CancelFlight     → 修改 Flight.status = 'CANCELLED', 释放 Crew 分配
  ReassignAircraft → 修改 Flight→Aircraft 链接

Functions:
  getOnTimeRate(flight: Flight) → 计算单个航班准点率
  getTopRoutes(year: Integer)   → 批量计算最盈利航线
```

### 第 5 步：构建应用
```
Workshop App / TypeScript App

用户在界面上看到：
  ┌──────────────────────────────────┐
  │  航班 CA1234                    │
  │  状态: 准点  出发: 14:30        │
  │  执飞飞机: B-1234 (Boeing 787)  │
  │  机组: [张三(机长), 李四(副驾)]  │
  │  [取消航班] [更换飞机]           │  ← Action 按钮
  │  准点率: 92.3%                  │  ← Derived Property
  └──────────────────────────────────┘
```

---

## 八、五种组件的协同全景图

```
                      ┌─────────┐
                      │  AIP Agent  │  AI 驱动的自主决策
                      └─────┬───────┘
                            │ 感知、推理、提案
                            ▼
    ┌───────────────────────────────────────────────┐
    │              动态层：决策与执行                   │
    │  提案 → 人工审核 → Action 执行 → 审计日志         │
    └───────────────────────┬───────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │              动力层：计算与操作                   │
    │                                                  │
    │   ┌──────────┐   调用   ┌─────────┐             │
    │   │  Action   │◄───────►│ Function │             │
    │   │  操作封装  │         │  计算推理  │             │
    │   │  回写执行  │         │  派生属性  │             │
    │   │  Webhook  │         │  校验规则  │             │
    │   └─────┬─────┘         └────┬──────┘             │
    │         │                    │                     │
    └─────────┼────────────────────┼─────────────────────┘
              │                    │
    ┌─────────┼────────────────────┼─────────────────────┐
    │              语义层：实体与关系                     │
    │         │                    │                     │
    │   ┌─────┴──────┐  Link  ┌───┴────────┐            │
    │   │  Object Type  │◄─────►│  Object Type  │            │
    │   │  Flight       │       │  Aircraft     │            │
    │   │  · flight_no  │       │  · tail_no    │            │
    │   │  · dept_time  │       │  · model      │            │
    │   │  · status     │       │  · total_hrs  │            │
    │   └──────┬───────┘       └──────┬───────┘            │
    │          │                      │                     │
    │          └────── Interface ─────┘                     │
    │              (例如: Trackable)                        │
    └──────────────────────────────────────────────────────┘
                            │
                            ▼
    ┌──────────────────────────────────────────────────────┐
    │              数据层：原始存储                          │
    │   Datasets · Files · Streaming · External Systems    │
    └──────────────────────────────────────────────────────┘
```

---

## 九、通过 SDK/API 访问 Ontology

这一节能让你直观感受「用 Ontology 编程」和「写 SQL」的差异：

```typescript
// ========== 传统方式：写 SQL ==========
const query = `
  SELECT f.flight_no, f.dept_time, a.tail_number, a.model,
         c.name as crew_name, ca.role
  FROM flight f
  JOIN aircraft a ON f.aircraft_id = a.id
  JOIN crew_assignment ca ON f.id = ca.flight_id
  JOIN crew c ON ca.crew_id = c.id
  WHERE f.status = 'ACTIVE'
    AND f.dept_time > NOW()
  ORDER BY f.dept_time ASC
`;
// 问题：表名/列名难记、JOIN 逻辑容易出错、语义不清晰、无权限控制

// ========== Ontology 方式 ==========
import { createClient } from "@osdk/client";

const client = createClient("https://your-stack.palantir.com", "ri.ontology.main", auth);

// 语义化查询：获取所有活跃航班及其执飞飞机
const activeFlights = await client
  .ontology("Flight")
  .where({ status: "ACTIVE" })
  .orderBy("departureTime", "asc")
  .fetchPage({ pageSize: 50 });

// 直接通过 Link 获取关联对象，不需要写 JOIN
for (const flight of activeFlights) {
  const aircraft = await flight.operatedBy.get();      // 获取执飞飞机
  const crew = await flight.assignedTo.get();          // 获取分配机组

  console.log(`${flight.flightNo}: ${aircraft.model}`);

  // 触发 Action
  if (needsReroute) {
    await flight.actions.reroute({ newRoute: "JFK-LAX" });
  }
}
```

**核心体验差异**：
- 不需要知道底层是几张表、怎么 JOIN
- 属性名和类型都有 IDE 补全
- Link 是语言层面的，`flight.operatedBy.get()` 比 JOIN 直观
- Action 执行自带权限校验和审计日志

---

## 十、总结

| 问题 | 答案 |
|------|------|
| **Ontology 是什么？** | 位于数据层之上的企业数字孪生，用业务语言描述现实世界 |
| **它解决什么问题？** | 打破数据孤岛，统一语义，让数据可读、可写、可解释、可审计 |
| **Object Type 是什么？** | 业务实体（航班、飞机、员工）——"名词" |
| **Link Type 是什么？** | 实体间关系（执飞、分配到、属于）——"动词" |
| **Action Type 是什么？** | 修改操作（取消、分配、创建）——"祈使句" |
| **Function 是什么？** | 计算逻辑（准点率、风险评估）——"推理" |
| **Interface 是什么？** | 跨对象的能力契约（可折旧、可审核）——"抽象" |
| **和数据库有什么区别？** | 数据库存储数据，Ontology 赋予数据**业务语义**和**操作能力** |
| **为什么 AI 时代重要？** | AI 通过 Ontology 理解业务世界，而非猜测表结构 |

**一图总结 Ontology 的全貌**：

```
数据表 ──封装──▶ Object Types ──关联──▶ Link Types ──构成──▶ 知识图谱
                                         │
                   Interfaces (抽象契约)  │
                                         │
                   Functions  (计算推理)  │
                   Actions    (执行操作)  │──套──▶ 权限 & 审计
                                         │
                                         ▼
                                   Workshop / OSDK / AIP
                                  (统一的业务应用和 AI 入口)
```
