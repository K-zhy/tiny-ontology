# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动 / 常用命令

```bash
python server.py          # 启动 FastAPI 服务 → http://localhost:8000
python seed_data.py       # 重建数据库 + 重新灌入种子数据
```

没有测试套件、没有 build 步骤。Swagger 文档在 http://localhost:8000/docs。

## 架构概览

这是一个 **Ontology 语义层 Demo**，将 SQLite 的原始表（student/teacher/course/score）封装为 Ontology 的 Object/Link/Action/Function，对上暴露业务语义而非 SQL。

```
原始数据表 (SQLite) 
  ↓ 映射
Ontology 语义层 (registry.py 定义 Object/Link/Action/Function)
  ↓ 暴露
REST API (server.py) → 前端图谱 + 自然语言查询 + Python SDK 风格调用
```

核心设计理念来自 [Palantir Ontology](https://www.palantir.com/docs/foundry/ontology/overview/)：**LLM 和上层应用只感知业务对象（Student、Course、Score），不接触底层表结构。**

## 关键文件

| 文件 | 作用 |
|------|------|
| `ontology_engine/schema.py` | 核心 dataclass 定义：`ObjectTypeDef`, `LinkTypeDef`, `ActionTypeDef`, `FunctionDef`, `InterfaceDef` |
| `ontology_engine/registry.py` | **映射配置中心**：4 个 Object Type、3 个 Link Type、4 个 Action、7 个 Function、2 个 Interface、2 个 ObjectSet。新增元素都在这里加定义 |
| `ontology_engine/database.py` | SQLite 连接管理 + 建表（含 audit_log） |
| `ontology_engine/query.py` | 查询引擎：语义操作 → SQL 翻译（`get_object`, `query_objects`, `traverse_link`, `query_objects_v2` 跨 Link JOIN, `query_object_set`） |
| `ontology_engine/action.py` | Action 引擎：校验 → 事务执行 → 审计日志。所有写操作必须走 Action |
| `ontology_engine/functions.py` | Function 引擎：SQL 计算逻辑（`call_function`, `compute_derived_property`）。批量 Function 和标量 Function 分别处理 |
| `ontology_engine/graph.py` | **内存图谱引擎**：邻接表结构，O(1) 遍历。启动时从 SQLite 全量加载并预计算 NodeMetadata。单例 `get_graph()` / `reload_graph()` |
| `server.py` | FastAPI 主入口。REST CRUD + Schema 元数据 API + **三套 NL 查询**（OAG 模式 + 图谱游走 + 批量规划） |
| `static/index.html` | 纯 HTML/JS 单页面：vis.js 力导向图 + 自然语言查询 + Actions/Functions 面板 |

## 三套自然语言查询

**OAG 模式** (`POST /ontology/nl-query-oag`)：**推荐**。LLM 在对象类型层面查询，使用 `query_objects`（支持跨 Link 点号过滤如 `{"student.name":"张三","course.name":"数学"}`）和 `query_object_set`（预定义 ObjectSet 如 TopStudents）。引擎根据 registry.py 的 Link 定义自动编译 SQL JOIN，LLM 不接触实例数据、无 traverse 工具、派生属性自动计算。对应 Palantir AIP 的 OAG（Ontology Augmented Generation）理念。

**批量规划模式** (`POST /ontology/nl-query`)：LLM 一次性输出完整 JSON 操作序列，引擎逐条执行。

**图谱游走模式** (`POST /ontology/nl-query-graph`)：LLM 通过工具在内存实例图谱上逐步探索。保留用于对比学习。DeepSeek API 走 Anthropic 兼容格式的 tool_use。

三套模式共用底层 `OntologyGraph`（内存图谱）、`call_function` 引擎和 `execute_action` 引擎。OAG 模式额外使用 `query_objects_v2`（跨 Link JOIN 编译）和 `query_object_set`（ObjectSet 查询）。

## ObjectSet

预定义的具名对象集合，在 `registry.py` 的 `OBJECT_SETS` 中配置。每个 ObjectSet 只需提供一个返回主键 id 的 SQL 查询，引擎自动 JOIN 基表获取完整对象并填充派生属性。

当前预定义：`TopStudents`（avgScore >= 85）、`PassedCourses`（课程平均分 >= 60）。

## 派生属性策略

- **OAG 模式**：`query_objects` 和 `query_object_set` 自动计算派生属性
- **图谱游走模式**：`search_objects` / `traverse` 自动计算派生属性（从 `_enrich` 获取），`get_node_detail` 也会计算
- `call_function`：独立调用（getTopStudents、getAllCourseAvgScores 等批量函数）

## 新增 Ontology 元素的步骤

1. 在 `database.py:init_db()` 建表（如需要）
2. 在 `registry.py` 添加对应的 `ObjectTypeDef` / `LinkTypeDef` / `FunctionDef` / `ActionTypeDef` / `ObjectSetDef`
3. 如新增 Function：在 `functions.py:call_function()` 添加执行逻辑
4. 如新增 Action：在 `action.py:_run_action()` 添加执行逻辑
5. 如新增 ObjectSet：在 `registry.py` 的 `OBJECT_SETS` 中添加 SQL 定义
6. 内存图谱 `graph.py` 会自动从 registry 读取并构建图结构
7. 如新增数据表：在 `seed_data.py` 添加种子数据
