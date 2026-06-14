"""
Batch Plan 模式 NL 查询
LLM 一次性输出完整 JSON 操作序列，引擎逐条执行。
路由: POST /ontology/nl-query
"""

from __future__ import annotations
import json
import re
import copy

from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, ACTION_TYPES, FUNCTIONS, INTERFACES
from ontology_engine.query import get_object, query_objects, traverse_link
from ontology_engine.action import execute_action
from ontology_engine.functions import call_function, compute_derived_property
from llm_client import chat_completion_text


def _truncate_text(text: str, max_len: int) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + '…'


def format_final_answer(answer: str) -> str:
    text = (answer or '').strip()
    if not text:
        return '结论：未找到相关信息。\n分析：未获得足够数据。'

    if '结论：' in text and '分析：' in text:
        conclusion, analysis = text.split('分析：', 1)
        conclusion = conclusion.split('结论：', 1)[-1].strip()
        analysis = analysis.strip()
        return f'结论：{_truncate_text(conclusion, 90)}\n分析：{_truncate_text(analysis, 120)}'

    fragments = [frag.strip(' -•*\t') for frag in re.split(r'\n+|(?<=[。！？])\s*', text) if frag.strip()]
    if not fragments:
        return '结论：未找到相关信息。\n分析：未获得足够数据。'

    conclusion = fragments[0]
    analysis_start = 1
    if conclusion.endswith(('：', ':')) and len(fragments) > 1:
        conclusion = conclusion + fragments[1]
        analysis_start = 2

    analysis_parts = fragments[analysis_start:analysis_start + 2]
    analysis = '；'.join(part.rstrip('。') for part in analysis_parts if part) if analysis_parts else '依据当前查询结果给出判断。'
    return f'结论：{_truncate_text(conclusion, 90)}\n分析：{_truncate_text(analysis, 120)}'


# ---- LLM 调用 ----

async def call_llm_simple(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
    """单轮无工具 LLM 调用，返回文本"""
    return await chat_completion_text(system_prompt, user_content, max_tokens=max_tokens)


# ---- Schema 上下文 ----

def build_llm_context() -> str:
    """构建给 LLM 的 Schema 上下文"""
    lines = ["## Object Types"]
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


def build_batch_system_prompt() -> str:
    schema_context = build_llm_context()
    return f"""你是一个 Ontology 查询引擎。以下是系统的 Ontology Schema：

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
6. 对于学期、授课安排、共同授课问题，优先查询 TeachingAssignment；仅在不涉及学期时才直接用 Course → taughtBy
7. 跨步骤引用格式：后续步骤需要前面步骤的返回值时，用 <RESULT[N].field>。N是步骤的数组索引（从0开始），field是字段名。
8. 如果用户想跨类型搜索名字，用 searchByName(keyword)。如果用户想看某对象的成绩汇总，先 query_objects 再 call_function getScoreSummary(objectType, objectId)。
9. TeachingAssignment 表示“某门课在某学期由某位老师授课”的业务事实，字段包括 semester、courseCno、teacherTno，可通过 course.name、teacher.name 跨 Link 过滤。"""


# ---- 操作解析与执行 ----

def parse_llm_ops(text: str) -> list[dict]:
    try:
        ops = json.loads(text)
        if isinstance(ops, list):
            return ops
    except json.JSONDecodeError:
        pass
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def resolve_params(op: dict, results: list) -> dict:
    """解析参数中的上下文引用，如 <RESULT[0].id>"""
    op = copy.deepcopy(op)

    def _resolve_value(val):
        if not isinstance(val, str):
            return val
        m = re.match(r'^<RESULT\[(\d+)\]\.(\w+)>$', val)
        if m:
            idx, field = int(m.group(1)), m.group(2)
            if idx < len(results) and results[idx].get("data") is not None:
                data = results[idx]["data"]
                if isinstance(data, list) and data:
                    return data[0].get(field, val)
                elif isinstance(data, dict):
                    return data.get(field, val)
            return val
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
    return op


def _fill_derived(object_type: str, obj: dict):
    obj_id = obj.get("id")
    if obj_id is None:
        return
    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        return
    for p in obj_def.properties:
        if p.prop_type == "derived":
            obj[p.name] = compute_derived_property(object_type, obj_id, p.name)


def execute_op(op: dict) -> dict:
    op_type = op.get("op")
    try:
        if op_type == "get_object":
            obj = get_object(op["objectType"], op["objectId"])
            if obj:
                _fill_derived(op["objectType"], obj)
            return {"op": op_type, "data": obj}
        elif op_type == "query_objects":
            results = query_objects(op["objectType"], where=op.get("where"), limit=op.get("limit", 5))
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


# ---- 主入口函数（由 server.py 调用）----

async def handle_batch_query(query_text: str) -> dict:
    system_prompt = build_batch_system_prompt()
    try:
        llm_text = await call_llm_simple(system_prompt, query_text)
        with open("/tmp/nl_debug.log", "a") as f:
            f.write(f"=== BATCH QUERY: {query_text} ===\nTEXT: {llm_text[:500]}\n\n")

        ops = parse_llm_ops(llm_text)
        results = []
        for op in ops:
            op = resolve_params(op, results)
            results.append(execute_op(op))

        # 生成自然语言回答
        answer_text = await call_llm_simple(
            "",
            f"用户问题：{query_text}\n\n查询结果：{json.dumps(results, ensure_ascii=False)}\n\n请严格按两行格式回答：第一行 `结论：...`，第二行 `分析：...`。必须先给结论，再简要分析过程。不要复述查询过程，不要说“根据结果”或“查询显示”。",
            max_tokens=120,
        )
        answer_text = format_final_answer(answer_text)
        return {"success": True, "operations": ops, "results": results, "answer": answer_text}
    except Exception as e:
        return {"success": False, "error": str(e), "operations": [], "results": []}
