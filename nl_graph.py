"""
Graph Walk 模式 NL 查询
LLM 通过工具在内存实例图谱上逐步游走探索。
路由: POST /ontology/nl-query-graph
"""

from __future__ import annotations
import httpx
import json
import os
import re

from ontology_engine.registry import OBJECT_TYPES, FUNCTIONS, INTERFACES
from ontology_engine.graph import get_graph, reload_graph


# ---- 中文容错映射 ----

TYPE_ALIASES = {
    "学生": "Student", "教师": "Teacher", "课程": "Course", "成绩": "Score", "分数": "Score",
}
PROP_ALIASES = {
    "姓名": "name", "名称": "name", "名字": "name",
    "年龄": "age", "性别": "gender", "班级": "className",
    "科目": "subject", "院系": "department", "部门": "department",
    "学分": "credit", "学期": "semester",
    "分数值": "scoreValue", "成绩": "scoreValue",
    "考试日期": "examDate",
}


# ---- LLM 调用 ----

async def call_llm(system: str, tools: list[dict], messages: list[dict]) -> dict:
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
                    "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-flash"),
                    "max_tokens": 2048,
                    "system": system,
                    "tools": tools,
                    "messages": messages,
                    "thinking": {"type": "disabled"},
                },
            )
            data = resp.json()
            if resp.status_code >= 400:
                return {"content": [{"type": "text", "text": f"API error {resp.status_code}: {data}"}], "stop_reason": "error"}
            return data
    except Exception as e:
        return {"content": [{"type": "text", "text": str(e)}], "stop_reason": "error"}


# ---- System Prompt ----

def build_system_prompt() -> str:
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

## 工具
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


def build_tool_schemas() -> list[dict]:
    return [
        {
            "name": "list_object_types",
            "description": "列出系统中所有可用的对象类型（Object Type）及其属性、遍历路径、绑定函数、可用操作和实例数量。",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "search_by_semantic",
            "description": "跨对象类型模糊搜索。在全部（或指定）对象类型的所有文本属性中做子串匹配。",
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
                    "object_type": {"type": "string", "enum": ["Student", "Teacher", "Course", "Score"]},
                    "filters": {"type": "object", "description": "属性过滤条件，如 {\"name\": \"张三\"}"},
                    "fuzzy": {"type": "boolean", "description": "是否模糊匹配（默认 false）"},
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


# ---- 节点格式化 ----

def format_node(graph, node: dict, detail: bool = False) -> str:
    obj_type = node.get("_objectType", "")
    node_key = node.get("_node_key", "")
    name = node.get("name", node_key)
    lines = [f"[{node_key}] {obj_type} \"{name}\""]
    ctx = node.get("_context", "")
    if ctx:
        lines.append(f"  ({ctx})")
    skip = {"name", "_node_key", "_objectType", "_traversals", "_functions", "_actions", "_available_traversals", "_context"}
    prop_parts = [f"{k}={v}" for k, v in node.items() if not k.startswith("_") and k not in skip]
    if prop_parts:
        lines.append("  " + ", ".join(prop_parts[:8]))
    functions = node.get("_functions", [])
    if functions:
        lines.append("  [函数] " + ", ".join(f['name'] for f in functions[:5]))
    traversals = node.get("_traversals", [])
    available = set(node.get("_available_traversals", []))
    if traversals:
        trav_names = [f"{t['name']}→{t['target_type']}" for t in traversals if t['name'] in available]
        if trav_names:
            lines.append("  [遍历] " + ", ".join(trav_names[:5]))
    return "\n".join(lines)


# ---- 工具执行 ----

def execute_tool(graph, tool_name: str, inp: dict) -> dict:
    empty = {"visited_node_keys": [], "visited_edges": []}
    try:
        if tool_name == "list_object_types":
            types = graph.list_object_types()
            if not types:
                return {"content": "系统中没有注册任何对象类型", "summary": "no types", **empty}
            parts = [f"系统共有 {len(types)} 种对象类型：\n"]
            for t in types:
                props_str = ", ".join(f"{p['name']}({p['data_type']})" for p in t["properties"])
                parts.append(f"- **{t['object_type']}**（{t['display_name']}）: {props_str}  [共 {t['count']} 个实例]")
                if t.get("traversals"):
                    parts.append("  [可遍历] " + ", ".join(f"{tr['name']}→{tr['target_type']}" for tr in t["traversals"]))
                if t.get("functions"):
                    parts.append("  [可调用函数] " + ", ".join(f"{f['name']}({f['display_name']})" for f in t["functions"]))
                if t.get("actions"):
                    parts.append("  [可执行操作] " + ", ".join(f"{a['name']}({a['display_name']})" for a in t["actions"]))
            return {"content": "\n".join(parts), "summary": f"listed {len(types)} object types", **empty}

        elif tool_name == "search_by_semantic":
            keyword = inp.get("keyword", "")
            obj_types = inp.get("object_types")
            if obj_types:
                obj_types = [TYPE_ALIASES.get(t, t) for t in obj_types]
            if not keyword:
                return {"content": "错误：需要提供 keyword 参数", "summary": "error", **empty}
            nodes = graph.search_by_semantic(keyword, obj_types)
            if not nodes:
                scope = "、".join(obj_types) if obj_types else "全部类型"
                return {"content": f"在 {scope} 中未找到匹配 \"{keyword}\" 的对象", "summary": "empty semantic search", **empty}
            visited = [n["_node_key"] for n in nodes]
            parts = [f"模糊搜索 \"{keyword}\" 找到 {len(nodes)} 个结果：\n"]
            for node in nodes[:15]:
                parts.append(format_node(graph, node, detail=True))
            if len(nodes) > 15:
                parts.append(f"...及其他 {len(nodes) - 15} 个结果")
            return {"content": "\n---\n".join(parts), "summary": f"semantic search '{keyword}' → {len(nodes)} results", "visited_node_keys": visited, "visited_edges": []}

        elif tool_name == "search_objects":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            filters = inp.get("filters")
            fuzzy = inp.get("fuzzy", False)
            if filters:
                filters = {PROP_ALIASES.get(k, k): v for k, v in filters.items()}
            if not obj_type:
                return {"content": "错误：未指定 object_type", "summary": "error", **empty}
            nodes = graph.search_objects(obj_type, filters, fuzzy=fuzzy)
            if not nodes:
                return {"content": f"未找到匹配的 {obj_type} 对象（{'模糊' if fuzzy else '精确'}匹配）", "summary": f"empty ({obj_type})", **empty}
            visited = [n["_node_key"] for n in nodes]
            parts = [f"找到 {len(nodes)} 个 {obj_type} 对象：\n"]
            for node in nodes[:10]:
                parts.append(format_node(graph, node, detail=True))
            if len(nodes) > 10:
                parts.append(f"...及其他 {len(nodes) - 10} 个结果")
            return {"content": "\n---\n".join(parts), "summary": f"found {len(nodes)} {obj_type}", "visited_node_keys": visited, "visited_edges": []}

        elif tool_name == "traverse":
            node_key = inp.get("node_key", "")
            trav_name = inp.get("traversal_name", "")
            if not node_key or not trav_name:
                return {"content": "错误：需要 node_key 和 traversal_name", "summary": "error", **empty}
            source_node = graph.get_node(node_key)
            if source_node is None:
                return {"content": f"节点 {node_key} 不存在", "summary": "node not found", "visited_node_keys": [node_key], "visited_edges": []}
            neighbors = graph.traverse(node_key, trav_name)
            if not neighbors:
                available = graph.get_available_traversals(node_key)
                hint = f"当前可用的遍历: {', '.join(available)}" if available else "该节点没有可用的遍历路径"
                return {"content": f"从 {source_node.get('name', node_key)} 沿 '{trav_name}' 遍历无结果。{hint}", "summary": "empty traversal", "visited_node_keys": [node_key], "visited_edges": []}
            visited = [node_key] + [n["_node_key"] for n in neighbors]
            edges = [{"from": node_key, "to": n["_node_key"], "label": trav_name} for n in neighbors[:8]]
            parts = [f"从 {source_node.get('name', node_key)} 沿 '{trav_name}' 找到 {len(neighbors)} 个对象：\n"]
            for n in neighbors[:8]:
                parts.append(format_node(graph, n))
            if len(neighbors) > 8:
                parts.append(f"...及其他 {len(neighbors) - 8} 个结果")
            return {"content": "\n---\n".join(parts), "summary": f"traversed {node_key} → {len(neighbors)} nodes", "visited_node_keys": visited, "visited_edges": edges}

        elif tool_name == "get_node_detail":
            node_key = inp.get("node_key", "")
            node = graph.get_node(node_key) if node_key else None
            if node is None:
                return {"content": f"节点 {node_key} 不存在", "summary": "node not found", **empty}
            from ontology_engine.functions import compute_derived_property
            obj_type = node["_objectType"]
            obj_id = node.get("id")
            for func_def in FUNCTIONS.values():
                if func_def.is_derived_property and func_def.bound_object == obj_type:
                    node[func_def.is_derived_property] = compute_derived_property(obj_type, obj_id, func_def.is_derived_property)
            return {"content": format_node(graph, node, detail=True), "summary": f"detail for {node_key}", "visited_node_keys": [node_key], "visited_edges": []}

        elif tool_name == "call_function":
            from ontology_engine.functions import call_function
            result = call_function(inp.get("function_name", ""), inp.get("params", {}))
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"called {inp.get('function_name', '')}", **empty}

        elif tool_name == "execute_action":
            from ontology_engine.action import execute_action
            result = execute_action(inp.get("action_name", ""), inp.get("params", {}))
            if result.get("success"):
                reload_graph()
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"executed {inp.get('action_name', '')}", **empty}

        return {"content": f"未知工具: {tool_name}", "summary": "unknown tool", **empty}
    except Exception as e:
        return {"content": f"工具执行错误: {e}", "summary": "error", **empty}


def _parse_tool_call(text_parts: list[str]) -> dict | None:
    full_text = "".join(text_parts).strip()
    try:
        obj = json.loads(full_text)
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+"\s*[,}][^{}]*\}', full_text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if "tool" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ---- 主入口函数（由 server.py 调用）----

async def handle_graph_query(query_text: str, max_iterations: int = 20) -> dict:
    graph = get_graph()
    system_prompt = build_system_prompt()
    tool_schemas = build_tool_schemas()

    # 可用工具摘要（供前端展示）
    available_tools = [{"name": t["name"], "description": t["description"]} for t in tool_schemas]

    exploration_path = []
    messages = [{"role": "user", "content": query_text}]
    final_answer = None

    for iteration in range(max_iterations):
        resp = await call_llm(system_prompt, tool_schemas, messages)
        content_blocks = resp.get("content", [])
        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        reasoning = " ".join(text_parts).strip() if text_parts and tool_use_blocks else ""

        if tool_use_blocks:
            messages.append({"role": "assistant", "content": content_blocks})
            tool_results_content = []
            first = True
            for tool in tool_use_blocks:
                tool_name = tool["name"]
                tool_input = tool.get("input", {})
                tool_id = tool.get("id", "")
                tool_result = execute_tool(graph, tool_name, tool_input)
                entry = {
                    "step": iteration + 1,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_result_summary": tool_result["summary"],
                    "visited_node_keys": tool_result.get("visited_node_keys", []),
                    "visited_edges": tool_result.get("visited_edges", []),
                }
                if first:
                    if reasoning:
                        entry["reasoning"] = reasoning
                    entry["available_tools"] = available_tools
                    first = False
                exploration_path.append(entry)
                content = tool_result["content"]
                if iteration + 1 >= 2:
                    content += f"\n\n[已执行 {iteration + 1} 步。请直接用中文给出答案，不要再调工具。]"
                tool_results_content.append({"type": "tool_result", "tool_use_id": tool_id, "content": content})
            messages.append({"role": "user", "content": tool_results_content})
            continue

        tool_call = _parse_tool_call(text_parts)
        if tool_call:
            tool_result = execute_tool(graph, tool_call["tool"], tool_call.get("input", {}))
            exploration_path.append({
                "step": iteration + 1,
                "tool_name": tool_call["tool"],
                "tool_input": tool_call.get("input", {}),
                "tool_result_summary": tool_result["summary"],
                "visited_node_keys": tool_result.get("visited_node_keys", []),
                "visited_edges": tool_result.get("visited_edges", []),
            })
            messages.append({"role": "assistant", "content": json.dumps(tool_call, ensure_ascii=False)})
            remaining = max_iterations - iteration - 1
            hint = f"如果数据足够请直接回答。还剩 {remaining} 步。" if remaining <= 3 else ""
            messages.append({"role": "user", "content": f"[工具返回]\n{tool_result['content']}\n\n{hint}"})
            continue

        if text_parts:
            final_answer = "".join(text_parts)
        elif exploration_path:
            steps_desc = "; ".join(f"步骤{s['step']}: {s['tool_name']} → {s['tool_result_summary']}" for s in exploration_path)
            final_answer = f"图谱探索完成（{len(exploration_path)} 步）：{steps_desc}"
        else:
            final_answer = "无法生成回答"
        break

    if final_answer is None:
        if exploration_path:
            last = exploration_path[-1]
            final_answer = f"探索了 {len(exploration_path)} 步，最后一步: {last['tool_name']} → {last['tool_result_summary']}"
        else:
            final_answer = "未找到相关信息"

    return {"success": True, "answer": final_answer, "exploration_path": exploration_path, "available_tools": available_tools}
