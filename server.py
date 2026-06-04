"""
Ontology Demo — FastAPI 主入口

启动: python server.py
然后访问 http://localhost:8000 查看前端页面
Swagger 文档: http://localhost:8000/docs
"""

from __future__ import annotations
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from ontology_engine.database import init_db
from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, ACTION_TYPES, FUNCTIONS, INTERFACES
from ontology_engine.query import get_object, query_objects, traverse_link
from ontology_engine.action import execute_action
from ontology_engine.functions import call_function, compute_derived_property
from ontology_engine.graph import get_graph, reload_graph

app = FastAPI(title="Ontology Demo", description="学生成绩管理系统 — Ontology 语义层 Demo")

# ---- 启动时初始化 ----

@app.on_event("startup")
def startup():
    init_db()


# ============================================================
# Schema 元数据 API（供前端和 AI Agent 使用）
# ============================================================

@app.get("/ontology/schema")
def get_schema():
    """返回完整 Ontology Schema，供前端图谱渲染和 LLM Tool Definition 使用"""
    objects = {}
    for name, o in OBJECT_TYPES.items():
        objects[name] = {
            "apiName": o.api_name,
            "displayName": o.display_name,
            "table": o.table,
            "properties": [
                {"name": p.name, "type": p.prop_type, "dataType": p.data_type}
                for p in o.properties
            ],
        }

    links = {}
    for name, l in LINK_TYPES.items():
        links[name] = {
            "apiName": l.api_name,
            "displayName": l.display_name,
            "sourceType": l.source_type,
            "targetType": l.target_type,
            "cardinality": l.cardinality,
            "reverseName": l.reverse_name,
        }

    actions = {}
    for name, a in ACTION_TYPES.items():
        actions[name] = {
            "apiName": a.api_name,
            "displayName": a.display_name,
            "actionType": a.action_type,
            "boundObject": a.bound_object,
            "params": [{"name": p.name, "type": p.param_type, "required": p.required} for p in a.params],
        }

    functions = {}
    for name, f in FUNCTIONS.items():
        functions[name] = {
            "apiName": f.api_name,
            "displayName": f.display_name,
            "funcType": f.func_type,
            "boundObject": f.bound_object,
            "returnType": f.return_type,
            "params": [{"name": p.name, "type": p.param_type, "required": p.required} for p in f.params],
        }

    return {"objects": objects, "links": links, "actions": actions, "functions": functions}


# ============================================================
# Object 查询 API
# ============================================================

@app.get("/ontology/objects/{object_type}")
def api_query_objects(
    object_type: str,
    name: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    order_dir: str = Query("asc"),
    limit: int = Query(50),
    offset: int = Query(0),
):
    """查询对象列表，支持 name 模糊匹配"""
    where = {"name": name} if name else None
    results = query_objects(object_type, where=where, order_by=order_by,
                            order_dir=order_dir, limit=limit, offset=offset)
    # 计算派生属性
    for obj in results:
        _fill_derived(object_type, obj)
    return {"data": results, "count": len(results)}


@app.get("/ontology/objects/{object_type}/{object_id}")
def api_get_object(object_type: str, object_id: int):
    """获取单个对象（含派生属性）"""
    obj = get_object(object_type, object_id)
    if obj is None:
        raise HTTPException(404, f"{object_type} id={object_id} not found")
    _fill_derived(object_type, obj)
    return obj


@app.get("/ontology/objects/{object_type}/{object_id}/links/{link_name}")
def api_traverse_link(object_type: str, object_id: int, link_name: str):
    """沿 Link 遍历获取关联对象"""
    results = traverse_link(object_type, object_id, link_name)
    return {"data": results, "count": len(results)}


# ============================================================
# Function API
# ============================================================

@app.get("/ontology/functions/{func_name}")
def api_call_function(func_name: str, request: Request):
    """调用 Function——动态接收所有 query 参数"""
    params = {}
    for key, val in request.query_params.items():
        # 自动转换数值类型
        if val.isdigit():
            params[key] = int(val)
        elif val.replace('.', '', 1).replace('-', '', 1).isdigit():
            params[key] = float(val)
        else:
            params[key] = val
    return call_function(func_name, params)


# ============================================================
# Action API
# ============================================================

class ActionRequest(BaseModel):
    params: dict


@app.post("/ontology/actions/{action_name}")
def api_execute_action(action_name: str, req: ActionRequest):
    """执行 Action"""
    result = execute_action(action_name, req.params)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Action failed"))
    return result


# ============================================================
# 自然语言查询 API
# ============================================================

import httpx
import json
import os


@app.post("/ontology/nl-query")
async def api_nl_query(req: dict):
    """自然语言查询：LLM 理解意图 → Ontology 操作 → 返回结果"""
    query_text = req.get("query", "")

    # 构建 Schema Context（精简版，给 LLM 理解 Ontology）
    schema_context = _build_llm_context()

    system_prompt = f"""你是一个 Ontology 查询引擎。以下是系统的 Ontology Schema：

{schema_context}

用户会用自然语言提问。你的任务是输出一个 JSON 数组，描述需要执行的 Ontology 操作序列。

可用的操作类型：
- {{"op": "get_object", "objectType": "...", "objectId": ...}}
- {{"op": "query_objects", "objectType": "...", "where": {{"name": "..."}}}}
- {{"op": "traverse_link", "objectType": "...", "objectId": ..., "linkName": "..."}}
- {{"op": "call_function", "funcName": "...", "params": {{...}}}}
- {{"op": "execute_action", "actionName": "...", "params": {{...}}}}

重要规则：
1. 如果用户想查某个学生的成绩，先 query_objects Student where name，再 traverse_link scores（反向 Link）
2. 如果用户想查某门课的排名，先 query_objects Course where name，再 call_function getTopStudents
3. 如果用户想查平均分/通过率，query_objects 找到对象后 call_function
4. 如果用户想录入/修改成绩，用 execute_action
5. 只输出 JSON 数组，不要其他内容
6. 对于 Course 要找 teacher，用正向 Link: traverse_link Course → taughtBy
7. 跨步骤引用格式：后续步骤需要前面步骤的返回值时，用 <RESULT[N].field>。N是步骤的数组索引（从0开始），field是字段名。例如第一步查到学生(id=1)后，第二步要调用getAvgScore：{{"op": "call_function", "funcName": "getAvgScore", "params": {{"studentId": "<RESULT[0].id>"}}}}。不要用其他格式如「上一结果.id」
8. 如果用户想跨类型搜索名字（如「搜索张三」「查一下张三是什么」），用 searchByName(keyword)。如果用户想看某对象的成绩汇总（如「张三的成绩汇总」），先 query_objects 再 call_function getScoreSummary(objectType, objectId)。"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic") + "/messages",
                headers={
                    "x-api-key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]"),
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": query_text}],
                },
            )
            data = resp.json()
            text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            llm_text = text_blocks[0] if text_blocks else ""
            with open("/tmp/nl_debug.log", "a") as f:
                f.write(f"=== QUERY: {query_text} ===\n")
                for i, b in enumerate(data.get("content", [])):
                    f.write(f"  BLOCK[{i}] type={b.get('type')}: {str(b)[:300]}\n")
                f.write(f"TEXT: {llm_text[:500]}\n\n")

        # 解析 LLM 输出的操作序列
        ops = _parse_llm_ops(llm_text)
        with open("/tmp/nl_debug.log", "a") as f:
            f.write(f"OPS: {ops}\n\n")

        # 执行操作序列
        results = []
        for op in ops:
            op = _resolve_params(op, results)  # 解析上一步结果引用
            step_result = _execute_op(op)
            results.append(step_result)

        # 用 LLM 生成自然语言回答
        answer = await _generate_answer(query_text, results, system_prompt)

        return {"success": True, "operations": ops, "results": results, "answer": answer}

    except Exception as e:
        return {"success": False, "error": str(e), "operations": [], "results": []}


def _build_llm_context() -> str:
    """构建给 LLM 的 Schema 上下文"""
    lines = []
    lines.append("## Object Types")
    for name, o in OBJECT_TYPES.items():
        props = ", ".join(f"{p.name}({p.data_type})" for p in o.properties)
        lines.append(f"- {name}({o.display_name}): {props}")

    lines.append("\n## Link Types")
    for name, l in LINK_TYPES.items():
        lines.append(f"- {name}: {l.source_type} → {l.target_type} ({l.display_name}), 反向: {l.reverse_name}")

    lines.append("\n## Functions")
    for name, f in FUNCTIONS.items():
        params = ", ".join(f"{p.name}:{p.param_type}" for p in f.params)
        lines.append(f"- {name}({f.bound_object}.{f.display_name}): ({params}) → {f.return_type}")

    lines.append("\n## Interfaces (跨对象抽象契约)")
    for name, i in INTERFACES.items():
        lines.append(f"- {name}({i.display_name}): {i.description}, 实现者: {', '.join(i.implementors)}, 共享Function: {', '.join(i.shared_functions)}")

    lines.append("\n## Actions")
    for name, a in ACTION_TYPES.items():
        params = ", ".join(f"{p.name}:{p.param_type}" for p in a.params)
        lines.append(f"- {name}({a.display_name}): ({params})")
    return "\n".join(lines)


def _parse_llm_ops(text: str) -> list[dict]:
    """解析 LLM 输出的操作序列 JSON"""
    try:
        # 尝试直接解析
        ops = json.loads(text)
        if isinstance(ops, list):
            return ops
    except json.JSONDecodeError:
        pass
    # 尝试提取 JSON 数组
    import re
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def _resolve_params(op: dict, results: list) -> dict:
    """解析参数中的上下文引用，如 <RESULT[0].id> —— 对所有字段递归生效"""
    import re
    import copy
    op = copy.deepcopy(op)

    def _resolve_value(val):
        """递归解析单个值中的 <RESULT[N].field> 引用"""
        if not isinstance(val, str):
            return val
        # <RESULT[N].field> 引用
        m = re.match(r'^<RESULT\[(\d+)\]\.(\w+)>$', val)
        if m:
            idx = int(m.group(1))
            field = m.group(2)
            if idx < len(results) and results[idx].get("data") is not None:
                data = results[idx]["data"]
                if isinstance(data, list) and len(data) > 0:
                    return data[0].get(field, val)
                elif isinstance(data, dict):
                    return data.get(field, val)
            return val
        # <RESULT[N]> 整结果引用
        m = re.match(r'^<RESULT\[(\d+)\]>$', val)
        if m:
            idx = int(m.group(1))
            if idx < len(results) and results[idx].get("data") is not None:
                return results[idx]["data"]
            return val
        return val

    for key, val in op.items():
        if key == "op":
            continue
        if key == "params" and isinstance(val, dict):
            for pk, pv in val.items():
                op[key][pk] = _resolve_value(pv)
        elif isinstance(val, str):
            op[key] = _resolve_value(val)
        elif isinstance(val, (int, float)):
            pass  # 已经是数值，不处理

    return op


def _execute_op(op: dict) -> dict:
    """执行单个 Ontology 操作"""
    op_type = op.get("op")
    try:
        if op_type == "get_object":
            obj = get_object(op["objectType"], op["objectId"])
            _fill_derived(op["objectType"], obj) if obj else None
            return {"op": op_type, "data": obj}

        elif op_type == "query_objects":
            results = query_objects(op["objectType"], where=op.get("where"),
                                    limit=op.get("limit", 5))
            for obj in results:
                _fill_derived(op["objectType"], obj)
            return {"op": op_type, "data": results}

        elif op_type == "traverse_link":
            results = traverse_link(op["objectType"], op["objectId"], op["linkName"])
            return {"op": op_type, "data": results}

        elif op_type == "call_function":
            return {"op": op_type, **call_function(op["funcName"], op.get("params", {}))}

        elif op_type == "execute_action":
            return {"op": op_type, **execute_action(op["actionName"], op.get("params", {}))}

        return {"op": op_type, "error": f"Unknown op: {op_type}"}
    except Exception as e:
        return {"op": op_type, "error": str(e)}


async def _generate_answer(query: str, results: list, schema_context: str) -> str:
    """用 LLM 根据查询结果生成自然语言回答"""
    import os, httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic") + "/messages",
                headers={
                    "x-api-key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]"),
                    "max_tokens": 300,
                    "messages": [
                        {"role": "user", "content": f"用户问题：{query}\n\n查询结果：{json.dumps(results, ensure_ascii=False)}\n\n请用简洁的中文回答用户问题，直接给出答案即可。"}
                    ],
                },
            )
            data = resp.json()
            text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            return text_blocks[0] if text_blocks else str(results)
    except Exception:
        return str(results)


# ============================================================
# 图谱原生 NL 查询（LLM 通过工具在图上游走）
# ============================================================

@app.post("/ontology/nl-query-graph")
async def api_nl_query_graph(req: dict):
    """图谱原生 NL 查询：LLM 通过工具调用在图上游走探索"""
    query_text = req.get("query", "")
    max_iterations = req.get("max_iterations", 20)

    graph = get_graph()

    system_prompt = _build_graph_system_prompt()
    tool_schemas = _build_graph_tool_schemas()

    exploration_path = []
    messages = [{"role": "user", "content": query_text}]
    final_answer = None

    for iteration in range(max_iterations):
        resp = await _call_llm_graph(system_prompt, tool_schemas, messages)
        content_blocks = resp.get("content", [])
        stop_reason = resp.get("stop_reason", "")

        # 提取 tool_use 块（原生格式）
        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
        # 提取文本块
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]

        # 处理所有 tool_use（一次 LLM 响应可能并行调多个工具）
        if tool_use_blocks:
            # 传回完整 assistant content（含 thinking 块，DeepSeek 要求）
            messages.append({"role": "assistant", "content": content_blocks})

            tool_results_content = []
            for tool in tool_use_blocks:
                tool_name = tool["name"]
                tool_input = tool.get("input", {})
                tool_id = tool.get("id", "")
                tool_result = _execute_graph_tool(graph, tool_name, tool_input)

                exploration_path.append({
                    "step": iteration + 1,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_result_summary": tool_result["summary"],
                    "visited_node_keys": tool_result.get("visited_node_keys", []),
                    "visited_edges": tool_result.get("visited_edges", []),
                })

                tool_results_content.append(
                    {"type": "tool_result", "tool_use_id": tool_id,
                     "content": tool_result["content"]}
                )

            # 超过2步后强提醒只需回答
            steps_done = iteration + 1
            if steps_done >= 2:
                hint = f"\n\n[已执行 {steps_done} 步。现在你应该已经有足够数据回答用户问题了。请直接用中文给出答案，不要再调工具。]"
                if tool_results_content:
                    tool_results_content[-1]["content"] += hint

            messages.append({"role": "user", "content": tool_results_content})
            continue

        # 尝试 JSON 文本格式工具调用（fallback）
        tool_call = _parse_tool_call(text_parts)
        if tool_call:
            tool_name = tool_call["tool"]
            tool_input = tool_call.get("input", {})
            tool_result = _execute_graph_tool(graph, tool_name, tool_input)

            exploration_path.append({
                "step": iteration + 1,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_result_summary": tool_result["summary"],
                "visited_node_keys": tool_result.get("visited_node_keys", []),
                "visited_edges": tool_result.get("visited_edges", []),
            })

            assistant_text = json.dumps(tool_call, ensure_ascii=False)
            tool_result_text = tool_result["content"]
            remaining = max_iterations - iteration - 1
            hint = f"如果数据足够请直接回答。还剩 {remaining} 步。" if remaining <= 3 else ""
            messages.append({"role": "assistant", "content": assistant_text})
            messages.append({"role": "user", "content": f"[工具返回]\n{tool_result_text}\n\n{hint}"})
            continue

        # 不是工具调用 → 当最终回答
        if text_parts:
            final_answer = "".join(text_parts)
        elif exploration_path:
            # 有探索结果但无文本回答 → 直接返回执行摘要
            steps_desc = "; ".join(
                f"步骤{s['step']}: {s['tool_name']} → {s['tool_result_summary']}"
                for s in exploration_path
            )
            final_answer = f"图谱探索完成（{len(exploration_path)} 步）：{steps_desc}"
        else:
            final_answer = "无法生成回答"
        break

    if final_answer is None:
        # 用最后一次工具结果生成简单总结
        if exploration_path:
            last_step = exploration_path[-1]
            final_answer = f"探索了 {len(exploration_path)} 步，最后一步: {last_step['tool_name']} → {last_step['tool_result_summary']}"
        else:
            final_answer = "未找到相关信息"

    return {
        "success": True,
        "answer": final_answer,
        "exploration_path": exploration_path,
    }


def _build_graph_system_prompt() -> str:
    return """你是一个 Ontology 知识图谱查询助手。你面前是一个业务知识图谱，你需要通过工具来逐步探索。

## 核心原则：工具驱动的逐步发现
1. 如果用户问题涉及不明确的实体，先用 search_by_semantic 模糊搜索
2. 如果知道具体要找什么类型的对象，用 search_objects 精确查找
3. 如果不确定有哪些对象类型可用，调用 list_object_types 查询
4. 获取足够信息后立即用中文简短回答，不要继续深挖
5. 找不到就说没找到，不编造数据

## 典型查询
- "查XXX的成绩" → search_objects 找到学生 → traverse scores 或 call_function getAvgScore
- "XXXX谁教" → search_objects 找到课程 → traverse taughtBy
- "搜索叫张三的" → search_objects(Student, filters={"name":"张三"}) 或 search_by_semantic("张三")
- "有哪些类型的对象" → list_object_types

""" + _build_graph_tool_descriptions()


def _build_graph_tool_descriptions() -> str:
    return """## 工具
list_object_types: 列出所有可用的对象类型及其属性、能做什么遍历、有什么函数和操作
search_by_semantic: 跨类型模糊搜索。输入keyword在所有对象的属性值中模糊匹配
search_objects: 在指定类型中搜索。object_type 用英文 API 名, filters 的 key 用英文属性名。设 fuzzy=true 模糊匹配
traverse: 沿路径找邻居。node_key如"Student-1", traversal_name从搜索结果[遍历]行获取
get_node_detail: 获取节点完整信息含派生属性(avgScore, passRate)
call_function: 调用函数。function_name+params从搜索结果[函数]行获取
execute_action: 执行写入操作

## 规则
- 得到足够信息后立即用中文简短回答，不要继续深挖
- 只回答用户问题，不要主动展示无关信息
- 找不到就说没找到"""


def _build_graph_tool_schemas() -> list[dict]:
    """给 LLM API 的 tools 参数（可选，部分 LLM 不支持则忽略）"""
    return [
        {
            "name": "list_object_types",
            "description": "列出系统中所有可用的对象类型（Object Type）及其属性、遍历路径、绑定函数、可用操作和实例数量。当你需要了解'有哪些类型的数据'时调用此工具。",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "search_by_semantic",
            "description": "跨对象类型模糊搜索。在全部（或指定）对象类型的所有文本属性中做子串匹配（大小写不敏感）。适合用户用口语化关键词搜索而不确定具体类型时使用，如'搜一下张三'、'找计算机相关的内容'。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "object_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["Student", "Teacher", "Course", "Score"]},
                        "description": "限定搜索的对象类型列表，不传则搜索全部类型",
                    },
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "search_objects",
            "description": "在指定对象类型中搜索，支持精确或模糊属性过滤",
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {"type": "string", "enum": ["Student", "Teacher", "Course", "Score"], "description": "对象类型: Student/Teacher/Course/Score"},
                    "filters": {"type": "object", "description": "属性过滤条件，如 {\"name\": \"张三\"}"},
                    "fuzzy": {"type": "boolean", "description": "是否模糊匹配（默认 false 精确匹配）"},
                },
                "required": ["object_type"],
            },
        },
        {
            "name": "traverse",
            "description": "沿遍历路径到邻居节点",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_key": {"type": "string", "description": "节点标识，格式: 类型-ID，如 Student-1"},
                    "traversal_name": {"type": "string", "description": "遍历路径名，来自上一结果的可用遍历列表"},
                },
                "required": ["node_key", "traversal_name"],
            },
        },
        {
            "name": "get_node_detail",
            "description": "获取节点完整信息，含派生属性",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_key": {"type": "string", "description": "节点标识，如 Student-1"},
                },
                "required": ["node_key"],
            },
        },
        {
            "name": "call_function",
            "description": "调用对象绑定的计算函数",
            "input_schema": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string", "description": "函数名称"},
                    "params": {"type": "object", "description": "函数参数"},
                },
                "required": ["function_name"],
            },
        },
        {
            "name": "execute_action",
            "description": "执行数据写入操作",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action_name": {"type": "string", "description": "操作名称"},
                    "params": {"type": "object", "description": "操作参数"},
                },
                "required": ["action_name"],
            },
        },
    ]


async def _call_llm_graph(system: str, tools: list[dict], messages: list[dict]) -> dict:
    """单轮 LLM 调用"""
    import os, httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic") + "/messages",
                headers={
                    "x-api-key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]"),
                    "max_tokens": 2048,
                    "system": system,
                    "tools": tools,
                    "messages": messages,
                },
            )
            return resp.json()
    except Exception as e:
        return {"content": [{"type": "text", "text": str(e)}], "stop_reason": "error"}


def _parse_tool_call(text_parts: list[str]) -> dict | None:
    """从 LLM 输出文本中解析 JSON 工具调用"""
    import re
    full_text = "".join(text_parts).strip()
    # 尝试直接解析 JSON
    try:
        obj = json.loads(full_text)
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 尝试提取 JSON 对象
    match = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+"\s*[,}][^{}]*\}', full_text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if "tool" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# 中文→英文类型名容错映射
_TYPE_ALIASES = {
    "学生": "Student", "教师": "Teacher", "课程": "Course", "成绩": "Score",
    "分数": "Score",
}
_PROP_ALIASES = {
    "姓名": "name", "名称": "name", "名字": "name",
    "年龄": "age", "性别": "gender", "班级": "className",
    "科目": "subject", "院系": "department", "部门": "department",
    "学分": "credit", "学期": "semester",
    "分数值": "scoreValue", "成绩": "scoreValue",
    "考试日期": "examDate",
}


def _execute_graph_tool(graph, tool_name: str, inp: dict) -> dict:
    """执行图原生工具，返回 {content, summary, visited_node_keys, visited_edges}"""
    try:
        if tool_name == "list_object_types":
            types = graph.list_object_types()
            if not types:
                return {"content": "系统中没有注册任何对象类型", "summary": "no types", "visited_node_keys": [], "visited_edges": []}
            parts = [f"系统共有 {len(types)} 种对象类型：\n"]
            for t in types:
                props_str = ", ".join(
                    f"{p['name']}({p['data_type']})" for p in t["properties"]
                )
                parts.append(f"- **{t['object_type']}**（{t['display_name']}）: {props_str}  [共 {t['count']} 个实例]")
                if t.get("traversals"):
                    travs = ", ".join(f"{tr['name']}→{tr['target_type']}" for tr in t["traversals"])
                    parts.append(f"  [可遍历] {travs}")
                if t.get("functions"):
                    funcs = ", ".join(f"{f['name']}({f['display_name']})" for f in t["functions"])
                    parts.append(f"  [可调用函数] {funcs}")
                if t.get("actions"):
                    acts = ", ".join(f"{a['name']}({a['display_name']})" for a in t["actions"])
                    parts.append(f"  [可执行操作] {acts}")
            return {"content": "\n".join(parts), "summary": f"listed {len(types)} object types", "visited_node_keys": [], "visited_edges": []}

        elif tool_name == "search_by_semantic":
            keyword = inp.get("keyword", "")
            obj_types = inp.get("object_types")
            # 翻译中文类型名
            if obj_types:
                obj_types = [_TYPE_ALIASES.get(t, t) for t in obj_types]
            if not keyword:
                return {"content": "错误：需要提供 keyword 参数", "summary": "error", "visited_node_keys": [], "visited_edges": []}
            nodes = graph.search_by_semantic(keyword, obj_types)
            if not nodes:
                scope = "、".join(obj_types) if obj_types else "全部类型"
                return {"content": f"在 {scope} 中未找到匹配 \"{keyword}\" 的对象", "summary": f"empty semantic search", "visited_node_keys": [], "visited_edges": []}
            parts = [f"模糊搜索 \"{keyword}\" 找到 {len(nodes)} 个结果：\n"]
            visited = []
            show_detail = min(len(nodes), 15)
            for node in nodes[:show_detail]:
                parts.append(_format_node_for_llm(graph, node, detail=True))
                visited.append(node["_node_key"])
            if len(nodes) > show_detail:
                parts.append(f"...及其他 {len(nodes) - show_detail} 个结果")
                for node in nodes[show_detail:]:
                    visited.append(node["_node_key"])
            return {"content": "\n---\n".join(parts), "summary": f"semantic search '{keyword}' → {len(nodes)} results", "visited_node_keys": visited, "visited_edges": []}

        elif tool_name == "search_objects":
            obj_type = inp.get("object_type", "")
            obj_type = _TYPE_ALIASES.get(obj_type, obj_type)
            filters = inp.get("filters")
            fuzzy = inp.get("fuzzy", False)
            # 翻译中文属性名
            if filters:
                filters = {_PROP_ALIASES.get(k, k): v for k, v in filters.items()}
            if not obj_type:
                return {"content": "错误：未指定 object_type。可用的类型请调用 list_object_types 查看。", "summary": "error", "visited_node_keys": [], "visited_edges": []}
            nodes = graph.search_objects(obj_type, filters, fuzzy=fuzzy)
            if not nodes:
                match_mode = "模糊" if fuzzy else "精确"
                return {"content": f"未找到匹配的 {obj_type} 对象（{match_mode}匹配）", "summary": f"empty ({obj_type})", "visited_node_keys": [], "visited_edges": []}
            match_mode = "模糊" if fuzzy else ""
            parts = [f"找到 {len(nodes)} 个 {obj_type} 对象{match_mode}：\n"]
            visited = []
            # 最多展示前 10 个节点的详情，其余仅列出 node_key
            show_detail = min(len(nodes), 10)
            for node in nodes[:show_detail]:
                parts.append(_format_node_for_llm(graph, node, detail=True))  # search 时显示遍历路径
                visited.append(node["_node_key"])
            if len(nodes) > show_detail:
                parts.append(f"...及其他 {len(nodes) - show_detail} 个结果")
                for node in nodes[show_detail:]:
                    visited.append(node["_node_key"])
            return {"content": "\n---\n".join(parts), "summary": f"found {len(nodes)} {obj_type}", "visited_node_keys": visited, "visited_edges": []}

        elif tool_name == "traverse":
            node_key = inp.get("node_key", "")
            trav_name = inp.get("traversal_name", "")
            if not node_key or not trav_name:
                return {"content": "错误：需要 node_key 和 traversal_name", "summary": "error", "visited_node_keys": [], "visited_edges": []}
            source_node = graph.get_node(node_key)
            if source_node is None:
                return {"content": f"节点 {node_key} 不存在", "summary": "node not found", "visited_node_keys": [], "visited_edges": []}
            neighbors = graph.traverse(node_key, trav_name)
            if not neighbors:
                available = graph.get_available_traversals(node_key)
                hint = f"当前可用的遍历: {', '.join(available)}" if available else "该节点没有可用的遍历路径"
                return {"content": f"从 {source_node.get('name', node_key)} 沿 '{trav_name}' 遍历无结果。{hint}", "summary": "empty traversal", "visited_node_keys": [node_key], "visited_edges": []}

            parts = [f"从 {source_node.get('name', node_key)} 沿 '{trav_name}' 找到 {len(neighbors)} 个对象：\n"]
            visited = [node_key]
            edges = []
            show_detail = min(len(neighbors), 8)
            for n in neighbors[:show_detail]:
                parts.append(_format_node_for_llm(graph, n))
                visited.append(n["_node_key"])
                edges.append({"from": node_key, "to": n["_node_key"], "label": trav_name})
            if len(neighbors) > show_detail:
                parts.append(f"...及其他 {len(neighbors) - show_detail} 个结果（可用 get_node_detail 查看详情）")
                for n in neighbors[show_detail:]:
                    visited.append(n["_node_key"])
            return {"content": "\n---\n".join(parts), "summary": f"traversed {node_key} → {len(neighbors)} nodes", "visited_node_keys": visited, "visited_edges": edges}

        elif tool_name == "get_node_detail":
            node_key = inp.get("node_key", "")
            node = graph.get_node(node_key) if node_key else None
            if node is None:
                return {"content": f"节点 {node_key} 不存在", "summary": "node not found", "visited_node_keys": [], "visited_edges": []}
            # 计算派生属性
            obj_type = node["_objectType"]
            obj_id = node.get("id")
            from ontology_engine.functions import compute_derived_property
            for func_def in FUNCTIONS.values():
                if func_def.is_derived_property and func_def.bound_object == obj_type:
                    val = compute_derived_property(obj_type, obj_id, func_def.is_derived_property)
                    node[func_def.is_derived_property] = val
            parts = [_format_node_for_llm(graph, node, detail=True)]
            return {"content": "\n".join(parts), "summary": f"detail for {node_key}", "visited_node_keys": [node_key], "visited_edges": []}

        elif tool_name == "call_function":
            func_name = inp.get("function_name", "")
            params = inp.get("params", {})
            from ontology_engine.functions import call_function
            result = call_function(func_name, params)
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"called {func_name}", "visited_node_keys": [], "visited_edges": []}

        elif tool_name == "execute_action":
            action_name = inp.get("action_name", "")
            params = inp.get("params", {})
            from ontology_engine.action import execute_action
            result = execute_action(action_name, params)
            if result.get("success"):
                reload_graph()
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"executed {action_name}", "visited_node_keys": [], "visited_edges": []}

        return {"content": f"未知工具: {tool_name}", "summary": "unknown tool", "visited_node_keys": [], "visited_edges": []}

    except Exception as e:
        return {"content": f"工具执行错误: {e}", "summary": "error", "visited_node_keys": [], "visited_edges": []}


def _format_node_for_llm(graph, node: dict, detail: bool = False) -> str:
    """紧凑格式化节点，包含属性、可用遍历、可用函数"""
    obj_type = node.get("_objectType", "")
    node_key = node.get("_node_key", "")
    name = node.get("name", node_key)

    lines = [f"[{node_key}] {obj_type} \"{name}\""]

    # 上下文（如 Score 节点显示关联的学生名和课程名）
    ctx = node.get("_context", "")
    if ctx:
        lines.append(f"  ({ctx})")

    # 紧凑属性行
    skip = {"name", "_node_key", "_objectType", "_traversals", "_functions", "_actions", "_available_traversals", "_context"}
    prop_parts = []
    for k, v in node.items():
        if k.startswith("_") or k in skip:
            continue
        prop_parts.append(f"{k}={v}")
    if prop_parts:
        lines.append("  " + ", ".join(prop_parts[:8]))

    # 可用函数
    functions = node.get("_functions", [])
    if functions:
        func_names = [f['name'] for f in functions[:5]]
        lines.append("  [函数] " + ", ".join(func_names))

    # 遍历路径（总是显示，LLM 需要知道如何进一步探索）
    traversals = node.get("_traversals", [])
    available = set(node.get("_available_traversals", []))
    if traversals:
        trav_names = [f"{t['name']}→{t['target_type']}" for t in traversals if t['name'] in available]
        if trav_names:
            lines.append("  [遍历] " + ", ".join(trav_names[:5]))

    return "\n".join(lines)


# ============================================================
# 图谱数据 API（全量对象+关系，供前端渲染）
# ============================================================

@app.get("/ontology/graph")
def api_graph_data():
    """返回全量图谱数据：节点（所有 Object）+ 边（所有 Link）"""
    nodes = []
    edges = []

    for obj_name, obj_def in OBJECT_TYPES.items():
        # 获取所有对象
        conn = __import__("ontology_engine.database", fromlist=["get_connection"]).get_connection()
        rows = conn.execute(f"SELECT * FROM {obj_def.table}").fetchall()
        conn.close()

        for row in rows:
            nodes.append({
                "id": f"{obj_name}-{row['id']}",
                "objectType": obj_name,
                "objectId": row["id"],
                "label": row["name"] if "name" in row.keys() else f"{obj_name}#{row['id']}",
                "group": obj_name,
            })

    for link_def in LINK_TYPES.values():
        source_def = OBJECT_TYPES[link_def.source_type]
        conn = __import__("ontology_engine.database", fromlist=["get_connection"]).get_connection()
        rows = conn.execute(f"SELECT id, {link_def.source_fk} FROM {source_def.table}").fetchall()
        conn.close()

        for row in rows:
            source_id = row["id"]
            target_id = row[link_def.source_fk]
            if target_id:
                edges.append({
                    "from": f"{link_def.source_type}-{source_id}",
                    "to": f"{link_def.target_type}-{target_id}",
                    "label": link_def.api_name,
                    "displayLabel": link_def.display_name,
                })

    return {"nodes": nodes, "edges": edges}


@app.get("/ontology/graph/schema")
def api_schema_graph():
    """返回 Ontology 类型层图谱：Object Type 为节点，Link Type 为边"""
    nodes = []
    edges = []

    # 每个 Object Type 是一个节点
    for name, obj_def in OBJECT_TYPES.items():
        props_summary = ", ".join(
            f"{p.name}({p.data_type})" for p in obj_def.properties[:4]
        )
        nodes.append({
            "id": f"Type-{name}",
            "label": f"{obj_def.display_name}\n{name}",
            "group": name,
            "title": f"<b>{obj_def.display_name} ({name})</b><br>"
                     f"表: {obj_def.table}<br>"
                     f"属性: {props_summary}",
            "shape": "box",
            "size": 35,
            "font": {"size": 14, "color": "#333", "multi": True},
            "borderWidth": 2,
            "level": 0,
        })

    # 每个 Link Type 是一条边
    for name, link_def in LINK_TYPES.items():
        edges.append({
            "from": f"Type-{link_def.source_type}",
            "to": f"Type-{link_def.target_type}",
            "label": f"{link_def.display_name}\n({link_def.api_name})",
            "arrows": "to",
            "font": {"size": 11, "color": "#555", "background": "white", "multi": True},
            "width": 2,
            "color": {"color": "#888", "opacity": 0.8},
        })

    # Interface 节点（菱形，紫色，level=1 便于分层布局）
    if INTERFACES:
        for name, iface_def in INTERFACES.items():
            nodes.append({
                "id": f"Interface-{name}",
                "label": f"◆ {iface_def.display_name}\n{name}",
                "group": "Interface",
                "title": f"<b>{iface_def.display_name} ({name})</b><br>"
                         f"{iface_def.description}<br>"
                         f"共享属性: {', '.join(iface_def.shared_properties) if iface_def.shared_properties else '无'}<br>"
                         f"共享Function: {', '.join(iface_def.shared_functions)}<br>"
                         f"实现者: {', '.join(iface_def.implementors)}",
                "shape": "diamond",
                "size": 30,
                "color": {"background": "#f9f0ff", "border": "#722ed1"},
                "font": {"size": 12, "color": "#531dab", "multi": True},
                "borderWidth": 2,
                "level": 1,
            })
            # implements 边（虚线）
            for impl in iface_def.implementors:
                edges.append({
                    "from": f"Interface-{name}",
                    "to": f"Type-{impl}",
                    "label": "implements",
                    "arrows": "to",
                    "dashes": [8, 4],
                    "font": {"size": 9, "color": "#999", "background": "white"},
                    "width": 1,
                    "color": {"color": "#b37feb", "opacity": 0.6},
                })

    return {"nodes": nodes, "edges": edges}


@app.get("/ontology/interfaces")
def api_interfaces():
    """返回所有 Interface 定义"""
    result = {}
    for name, iface_def in INTERFACES.items():
        result[name] = {
            "apiName": iface_def.api_name,
            "displayName": iface_def.display_name,
            "description": iface_def.description,
            "sharedProperties": iface_def.shared_properties,
            "sharedFunctions": iface_def.shared_functions,
            "implementors": iface_def.implementors,
        }
    return result


def _fill_derived(object_type: str, obj: dict):
    """为对象填充派生属性"""
    obj_id = obj.get("id")
    if obj_id is None:
        return
    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        return
    for p in obj_def.properties:
        if p.prop_type == "derived":
            val = compute_derived_property(object_type, obj_id, p.name)
            obj[p.name] = val


# ============================================================
# 静态页面
# ============================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
