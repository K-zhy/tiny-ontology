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
| `ontology_engine/registry.py` | **映射配置中心**：4 个 Object Type、3 个 Link Type、4 个 Action、7 个 Function、2 个 Interface。新增 Object/Function/Action 都在这里加定义 |
| `ontology_engine/database.py` | SQLite 连接管理 + 建表（含 audit_log） |
| `ontology_engine/query.py` | 查询引擎：Ontology 语义操作 → SQL 翻译（`get_object`, `query_objects`, `traverse_link`）。支持正向/反向 Link 遍历 |
| `ontology_engine/action.py` | Action 引擎：校验 → 事务执行 → 审计日志。所有写操作必须走 Action |
| `ontology_engine/functions.py` | Function 引擎：SQL 计算逻辑（`call_function`, `compute_derived_property`）。批量 Function 和标量 Function 分别处理 |
| `ontology_engine/graph.py` | **内存图谱引擎**：邻接表结构，O(1) 遍历。启动时从 SQLite 全量加载并预计算 NodeMetadata。单例 `get_graph()` / `reload_graph()` |
| `server.py` | FastAPI 主入口。REST CRUD + Schema 元数据 API + **两套 NL 查询**（批量规划 + 图谱游走） |
| `static/index.html` | 纯 HTML/JS 单页面：vis.js 力导向图 + 自然语言查询 + Actions/Functions 面板 |

## 两套自然语言查询

**批量规划模式** (`POST /ontology/nl-query`)：旧模式，把所有 Schema dump 进 prompt，LLM 一次性输出完整 JSON 操作序列，引擎逐条执行。

**图谱游走模式** (`POST /ontology/nl-query-graph`)：新模式，LLM 通过 5 个图原生工具 (search_objects / traverse / get_node_detail / call_function / execute_action) 在内存图谱上逐步探索，每次工具返回包含节点元数据（可用遍历方向 + 绑定函数），LLM 根据元数据动态决定下一步。DeepSeek API 走 Anthropic 兼容格式的 tool_use。

两套模式共用底层 `OntologyGraph`（内存图谱）、`call_function` 引擎和 `execute_action` 引擎。

## 派生属性策略

- `search_objects` / `traverse`：不计算派生属性（只返回 regular props + 元数据）
- `get_node_detail`：计算所有派生属性（调 `compute_derived_property`）
- `call_function`：独立调用（getTopStudents、getAllCourseAvgScores 等批量函数）

## 新增 Ontology 元素的步骤

1. 在 `database.py:init_db()` 建表（如需要）
2. 在 `registry.py` 添加对应的 `ObjectTypeDef` / `LinkTypeDef` / `FunctionDef` / `ActionTypeDef`
3. 如新增 Function：在 `functions.py:call_function()` 添加执行逻辑
4. 如新增 Action：在 `action.py:_run_action()` 添加执行逻辑
5. 内存图谱 `graph.py` 会自动从 registry 读取并构建图结构
6. 如新增数据表：在 `seed_data.py` 添加种子数据
