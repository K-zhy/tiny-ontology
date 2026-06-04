# Ontology 语义层 Demo

一个基于 **Palantir Ontology** 设计理念的学生成绩管理系统 Demo。将 SQLite 的原始数据表（student/teacher/course/score）封装为 Ontology 语义层的 Object/Link/Action/Function，对上暴露业务语义而非 SQL。

**核心设计理念**：LLM 和上层应用只感知业务对象（Student、Course、Score），不接触底层表结构。

![前端界面截图](assets/image.png)

## 快速启动

```bash
# 1. 安装依赖
pip install fastapi uvicorn httpx

# 2. 初始化数据库并灌入种子数据
python seed_data.py

# 3. 启动服务
python server.py
```

访问 http://localhost:8000 查看前端图谱页面，http://localhost:8000/docs 查看 Swagger API 文档。

## 架构概览

```
SQLite 原始表 (student / teacher / course / score)
        │
        ▼  映射配置 (registry.py)
Ontology 语义层
  ├── Object Types:  Student, Teacher, Course, Score
  ├── Link Types:     earnedBy, forCourse, taughtBy
  ├── Action Types:   createScore, updateScore, deleteScore, assignTeacher
  ├── Functions:      getAvgScore, getTopStudents, getPassRate ...
  ├── Interfaces:     Nameable, Scoreable
  └── Object Sets:    TopStudents, PassedCourses
        │
        ▼  暴露 (server.py)
┌──────────────────────────────────────────────────────────┐
│  REST API    │  前端图谱    │      自然语言查询            │
│  CRUD 端点   │  vis.js     │  AIP Logic 模式 (推荐)       │
│  /docs       │  力导向图   │  + 图谱游走模式 + 批量规划    │
└──────────────────────────────────────────────────────────┘
```

## 核心概念

### 五元模型

| 概念 | 角色 | 示例 |
|------|------|------|
| **Object Type** | 业务实体（名词） | Student（学生）、Course（课程） |
| **Link Type** | 实体间关系（动词） | earnedBy（成绩属于谁）、taughtBy（谁教） |
| **Action Type** | 写操作（祈使句） | createScore（录入成绩） |
| **Function** | 计算推理 | getAvgScore（计算平均分） |
| **Interface** | 跨对象抽象契约 | Nameable（可被按名称搜索） |
| **Object Set** | 具名对象集合（业务规则预定义） | TopStudents（平均分>=85 的学生） |

### 三种属性

| 类型 | 说明 | 示例 |
|------|------|------|
| 主键（primary_key） | 唯一标识 | `id` |
| 普通属性（regular） | 存储的业务字段 | `name`, `age`, `credit` |
| 派生属性（derived） | 由 Function 动态计算 | `avgScore`（平均分）, `passRate`（通过率） |

### Action 执行流程

```
参数校验 → 业务校验(validateScore) → 事务执行 → 审计日志(audit_log) → commit/rollback
```

所有写操作必须通过 Action，不可直接操作数据库表。

## 自然语言查询

系统提供 **三套** NL 查询模式，从不同架构层次展示 Ontology 查询的演进。

### AIP Logic 模式 `POST /ontology/nl-query-oag`（推荐）

本模式忠实复现了 Palantir [AIP Logic](https://www.palantir.com/docs/foundry/logic/overview/) 的核心架构：**LLM + Ontology 工具调用**。

#### 官方对应关系

AIP Logic 的 "Use LLM" Block 向 LLM 暴露三类 Ontology 驱动工具（[官方文档](https://www.palantir.com/docs/foundry/logic/blocks/#tools)），本项目完整实现了这三类：

> *AIP Logic leverages three categories of Ontology-driven tools — **data, logic, and action** — to effectively query data, execute logical operations, and safely take actions.*
> — Palantir AIP Logic Blocks 文档

| Palantir 官方工具 | 官方说明 | 本项目对应工具 | 实现说明 |
|---|---|---|---|
| **Query objects** (Data) | LLM 可访问的 Object Types，支持属性过滤、Link 遍历、聚合 | `query_objects` | 跨 Link 点号过滤（如 `{"student.name":"张三"}`），引擎自动编译 SQL JOIN；结果自动附带派生属性 |
| **Query objects** (Data) | — | `query_object_set` | 查询预定义 ObjectSet（TopStudents、PassedCourses），业务规则封装在引擎内，LLM 只传名称 |
| **Call function** (Logic) | 调用 Foundry Functions 或已发布的 Logic Functions | `call_function` | 调用 `getAvgScore`、`getTopStudents` 等预定义计算函数 |
| **Apply actions** (Action) | LLM 通过 Action 写入 Ontology，在调用用户权限下执行 | `execute_action` | 执行 `createScore`、`updateScore` 等 Action，校验 → 事务 → 审计日志 |

额外暴露的辅助工具（官方通过 UI Schema 配置，本项目作为运行时工具）：

| 工具 | 用途 |
|---|---|
| `list_object_types` | LLM 动态发现 Schema（Object Types、Links、ObjectSets） |
| `get_object_detail` | 按 `(type, id)` 获取单对象完整详情含派生属性 |

#### 关键设计原则（与官方一致）

1. **LLM 不直接访问数据**：官方文档明确 *"LLMs do not have direct access to tools; LLMs can only ask to use tools, and these tool calls are then executed by AIP Logic"*。本项目中 LLM 调用工具 → 引擎翻译为 SQL 执行，路径完全一致。
2. **Link 遍历下沉到引擎**：LLM 不需要知道"要先查 student 再 JOIN score"，只需声明 `{"student.name":"张三", "course.name":"数学"}`，引擎自动编译跨表 JOIN。对应官方 Object Query 工具的 Link traversal 能力。
3. **派生属性自动计算**：`query_objects` 和 `query_object_set` 返回结果自动含 `avgScore`、`passRate`，LLM 无需额外调用 Function。对应 AIP Logic 中 Function 计算结果透明注入对象的设计。
4. **Native Tool Calling**：本项目使用 Anthropic 原生 `tool_use` 协议，对应官方"Native tool calling"模式（*improved speed and performance, ability to call multiple tools in parallel*）。

### 图谱游走模式 `POST /ontology/nl-query-graph`

LLM 通过 7 个图原生工具在**实例图**上逐步探索，每次工具返回节点元数据（可用遍历方向 + 绑定函数），LLM 动态决定下一步。适合理解「LLM agent 如何在图上导航」的对比学习。

### 批量规划模式 `POST /ontology/nl-query`

LLM 一次性输出完整 JSON 操作序列，引擎逐条执行后生成自然语言回答。不涉及实例图游走。

### 典型查询对比

| 查询 | AIP Logic 模式（推荐） | 图谱游走模式 |
|------|-----------------|-------------|
| 「张三高等数学多少分」 | **1 步**：`query_objects(Score, {student.name, course.name})` | 8 步：search → traverse scores → 逐个 traverse forCourse |
| 「优秀学生有哪些」 | **1 步**：`query_object_set("TopStudents")` | 不支持（无 ObjectSet 概念） |
| 「张三的平均分」 | **1 步**：`query_objects(Student, {name})`，结果自带 avgScore | 2 步：search_objects → call_function getAvgScore |
| 「有哪些对象类型」 | 1 步：`list_object_types` | 1 步：`list_object_types` |
| 「录入张三的高等数学成绩85分」 | 1 步：`execute_action createScore` | 1 步：`execute_action createScore` |

## API 端点

### Schema 元数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/schema` | 完整 Schema 定义（前端图谱渲染 + LLM 工具定义） |
| GET | `/ontology/graph/schema` | Object Type + Link Type 的类型层图谱 |
| GET | `/ontology/graph` | 全量实例数据图谱（节点 + 边） |
| GET | `/ontology/interfaces` | 所有 Interface 定义 |

### 对象查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/objects/{type}` | 查询对象列表（支持 name 模糊匹配、排序、分页） |
| GET | `/ontology/objects/{type}/{id}` | 获取单个对象（含派生属性） |
| GET | `/ontology/objects/{type}/{id}/links/{link}` | 沿 Link 遍历获取关联对象 |

### 计算与操作

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/functions/{funcName}` | 调用 Function |
| POST | `/ontology/actions/{actionName}` | 执行 Action |

### ObjectSet

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/object-sets` | 列出所有 ObjectSet 定义 |
| GET | `/ontology/object-sets/{name}` | 查询某个 ObjectSet 的对象 |

### 自然语言查询

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ontology/nl-query-oag` | **AIP Logic 模式（推荐）** — LLM 工具调用，引擎编译 JOIN |
| POST | `/ontology/nl-query-graph` | 图谱游走模式 — 实例图 agent 探索 |
| POST | `/ontology/nl-query` | 批量规划模式 — LLM 输出 JSON 操作序列 |

## 项目结构

```
ontology/
├── server.py                       # FastAPI 主入口
├── seed_data.py                    # 种子数据（3 教师、5 课程、5 学生、20 条成绩）
├── static/
│   └── index.html                  # 前端单页面（vis.js 力导向图 + NL 查询）
├── ontology_engine/
│   ├── schema.py                   # 核心 dataclass 定义
│   ├── registry.py                 # 映射配置中心（Object/Link/Action/Function/ObjectSet）
│   ├── database.py                 # SQLite 连接管理 + 建表
│   ├── graph.py                    # 内存图谱引擎（邻接表，O(1) 遍历）
│   ├── query.py                    # 查询引擎（语义操作 → SQL 翻译）
│   ├── action.py                   # Action 引擎（校验 → 事务 → 审计）
│   └── functions.py                # Function 引擎（SQL 计算逻辑）
└── Palantir_Ontology_详解.md       # Palantir Ontology 设计理念参考文档
```

## 新增 Ontology 元素

1. 在 `database.py:init_db()` 建表（如需要）
2. 在 `registry.py` 添加 `ObjectTypeDef` / `LinkTypeDef` / `FunctionDef` / `ActionTypeDef` / `ObjectSetDef`
3. 新增 Function → 在 `functions.py:call_function()` 添加逻辑
4. 新增 Action → 在 `action.py:_run_action()` 添加逻辑
5. 新增 ObjectSet → 在 `registry.py` 的 `OBJECT_SETS` 中添加定义（只需提供 SELECT id 的 SQL）
6. 图谱引擎自动从 registry 读取并构建图结构
7. 在 `seed_data.py` 添加种子数据

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_BASE_URL` | LLM API 地址 | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_AUTH_TOKEN` | LLM API 密钥 | — |
| `ANTHROPIC_MODEL` | 模型名称 | `deepseek-v4-flash` |

## 欢迎贡献

本项目是一个开放的社区项目，欢迎任何感兴趣的人参与贡献！无论你是：

- **学习者**：对 Ontology 语义层概念感兴趣，想通过实际代码理解
- **开发者**：想增加新的 Object/Link/Action/Function，或改进现有实现
- **研究者**：对 Palantir Ontology 设计理念有深入理解，想分享你的见解
- **使用者**：发现了 bug 或有功能建议

### 贡献方式

- **Issue 讨论**：对 Ontology 设计理念的理解、架构改进建议、功能需求
- **Pull Request**：代码改进、新功能、文档优化、bug 修复
- **想法分享**：欢迎在 Discussions 中分享你对 Ontology 语义层、OAG（Ontology Augmented Generation）、AI Agent 与知识图谱融合的思考和理解

所有贡献者都会在项目的贡献者列表中列名致谢。

## 设计参考

- [Palantir Foundry - Ontology Overview](https://www.palantir.com/docs/foundry/ontology/overview/)
- [Building with Palantir AIP: Data Tools for RAG/OAG](https://blog.palantir.com/building-with-palantir-aip-data-tools-for-rag-oag-b3b509c8b0f3)
- [Building with Palantir AIP: Logic Tools for RAG/OAG](https://blog.palantir.com/building-with-palantir-aip-logic-tools-for-rag-oag-fdaf8938d02e)

## 免责声明

本项目是对 [Palantir Ontology](https://www.palantir.com/docs/foundry/ontology/overview/) 设计理念的独立开源学习和实现，所有代码均为独立编写。本项目与 Palantir Technologies Inc. 无任何关联、赞助或认可关系。"Palantir" 和 "Foundry" 是 Palantir Technologies Inc. 的商标。
