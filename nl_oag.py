"""
OAG（Ontology Augmented Generation）模式 NL 查询
LLM 在对象类型层面操作，引擎负责 Link JOIN 编译和派生属性自动计算。
路由: POST /ontology/nl-query-oag
"""

from __future__ import annotations
import json
import re

from ontology_engine.registry import (
    OBJECT_TYPES, LINK_TYPES, ACTION_TYPES, FUNCTIONS, INTERFACES, OBJECT_SETS,
)
from ontology_engine.query import (
    get_object, query_objects_v2, query_object_set, fill_derived_batch,
    aggregate_objects, exclude_objects,
)
from ontology_engine.action import execute_action
from ontology_engine.functions import call_function, compute_derived_property
from ontology_engine.database import get_connection
from ontology_engine.graph import reload_graph
from llm_client import chat_completion

# 共用的中文容错映射（与 nl_graph.py 保持一致）
TYPE_ALIASES = {
    "学生": "Student", "教师": "Teacher", "课程": "Course", "成绩": "Score", "分数": "Score",
}
VALUE_ALIASES = {
    "gender": {
        "男": "M", "男性": "M", "male": "M", "m": "M",
        "女": "F", "女性": "F", "female": "F", "f": "F",
    }
}


def normalize_filter_value(prop_name: str, value):
    if isinstance(value, str):
        alias_map = VALUE_ALIASES.get(prop_name)
        if alias_map:
            return alias_map.get(value.lower(), alias_map.get(value, value))
        return value
    if isinstance(value, list):
        return [normalize_filter_value(prop_name, item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            normalized[key] = normalize_filter_value(prop_name, item) if key == "value" else item
        return normalized
    return value


def normalize_filters(filters: dict) -> dict:
    normalized = {}
    for key, value in filters.items():
        if key == "$or" and isinstance(value, list):
            normalized[key] = [normalize_filters(item) if isinstance(item, dict) else item for item in value]
            continue
        prop_name = key.split(".")[-1]
        normalized[key] = normalize_filter_value(prop_name, value)
    return normalized


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

async def call_llm(system: str, tools: list[dict], messages: list[dict]) -> dict:
    return await chat_completion(system, messages, tool_schemas=tools, max_tokens=2048)


# ---- 对象类型推断 ----
# 后续可升级，当前结构过于简单
def infer_relevant_types(query_text: str) -> list[str]:
    """从查询文本推断涉及的对象类型（关键词匹配，无需额外 LLM 调用）"""
    type_keywords = {
        "Student": ["学生", "同学", "student", "平均分", "avgscore", "学号"],
        "Teacher": ["老师", "教师", "teacher", "讲师", "教授", "任课"],
        "Course": ["课程", "科目", "course", "学分", "通过率", "passrate"],
        "Score": ["成绩", "分数", "score", "考试", "不及格", "挂科", "高分", "低分"],
    }
    q = query_text.lower()
    matched = set(t for t, kws in type_keywords.items() if any(kw in q for kw in kws))
    # Score 查询通常需要 Student 和 Course 上下文（studentName/courseName 富化）
    if "Score" in matched:
        matched.update(["Student", "Course"])
    if re.search(r'[\u4e00-\u9fff]{2,3}(?:的|同学|学生)', query_text):
        matched.add("Student")
    result = [t for t in OBJECT_TYPES.keys() if t in matched]
    return result if result else list(OBJECT_TYPES.keys())



# ---- 工具 Schema 构建 ----

def _param_type_to_json_schema(param_type: str) -> str:
    return {"integer": "integer", "int": "integer", "float": "number", "number": "number"}.get(param_type, "string")


def build_object_bound_tool_schemas(relevant_types: list[str]) -> list[dict]:
    """按 relevant_types 动态生成对象绑定函数工具（工具名: fn_{funcName}）"""
    tools = []
    relevant_set = set(relevant_types)
    for func_name, func_def in FUNCTIONS.items():
        if func_def.func_type == "validation":
            continue
        if func_def.bound_object in relevant_set:
            type_label = func_def.bound_object
        elif func_def.bound_object in INTERFACES:
            iface = INTERFACES[func_def.bound_object]
            applicable = [t for t in iface.implementors if t in relevant_set]
            if not applicable:
                continue
            type_label = "、".join(applicable)
        else:
            continue
        props = {}
        required_params = []
        for p in func_def.params:
            props[p.name] = {"type": _param_type_to_json_schema(p.param_type), "description": p.name}
            if p.required:
                required_params.append(p.name)
        tools.append({
            "name": f"fn_{func_name}",
            "description": f"[{type_label}] {func_def.display_name} → 返回 {func_def.return_type}",
            "input_schema": {"type": "object", "properties": props, "required": required_params},
        })
    return tools


def get_relevant_object_sets(object_types: list[str]) -> dict[str, list]:
    """返回当前对象类型上定义的 ObjectSet，避免把无关集合暴露给上下文。"""
    normalized_types = []
    for type_name in object_types:
        mapped = TYPE_ALIASES.get(type_name, type_name)
        if mapped in OBJECT_TYPES and mapped not in normalized_types:
            normalized_types.append(mapped)

    relevant_sets: dict[str, list] = {type_name: [] for type_name in normalized_types}
    for obj_set in OBJECT_SETS.values():
        if obj_set.object_type in relevant_sets:
            relevant_sets[obj_set.object_type].append(obj_set)
    return relevant_sets


def build_object_capability_data(object_types: list[str]) -> dict:
    """构建当前推断对象的属性、Link、ObjectSet、函数能力描述。"""
    normalized_types = []
    for type_name in object_types:
        mapped = TYPE_ALIASES.get(type_name, type_name)
        if mapped in OBJECT_TYPES and mapped not in normalized_types:
            normalized_types.append(mapped)
    relevant_object_sets = get_relevant_object_sets(normalized_types)

    object_caps = []
    for type_name in normalized_types:
        obj_def = OBJECT_TYPES[type_name]
        properties = [
            {
                "name": p.name,
                "dataType": p.data_type,
                "kind": p.prop_type,
            }
            for p in obj_def.properties
        ]

        links = []
        for link in LINK_TYPES.values():
            if link.source_type == type_name:
                links.append({
                    "path": link.target_type.lower(),
                    "direction": "forward",
                    "targetType": link.target_type,
                    "display": link.display_name,
                })
            if link.target_type == type_name:
                links.append({
                    "path": link.reverse_name,
                    "direction": "reverse",
                    "targetType": link.source_type,
                    "display": f"反向{link.display_name}",
                })

        object_sets = [
            {
                "name": obj_set.api_name,
                "display": obj_set.display_name,
                "description": obj_set.description,
            }
            for obj_set in relevant_object_sets.get(type_name, [])
        ]

        seen_functions = set()
        functions = []
        for func_name, func_def in FUNCTIONS.items():
            if func_def.func_type == "validation":
                continue
            applies = False
            if func_def.bound_object == type_name:
                applies = True
            elif func_def.bound_object in INTERFACES and type_name in INTERFACES[func_def.bound_object].implementors:
                applies = True
            if not applies or func_name in seen_functions:
                continue
            seen_functions.add(func_name)
            functions.append({
                "tool": f"fn_{func_name}",
                "display": func_def.display_name,
                "returnType": func_def.return_type,
                "params": [
                    {
                        "name": param.name,
                        "type": param.param_type,
                        "required": param.required,
                    }
                    for param in func_def.params
                ],
            })

        object_caps.append({
            "type": type_name,
            "display": obj_def.display_name,
            "properties": properties,
            "links": links,
            "objectSets": object_sets,
            "functions": functions,
        })

    system_tools = [
        {
            "name": "infer_relevant_types",
            "purpose": "推断当前问题涉及哪些对象类型",
        },
        {
            "name": "describe_object_capabilities",
            "purpose": "列出当前对象的属性、Link、ObjectSet 和绑定函数",
        },
        {
            "name": "query_objects",
            "purpose": "按对象属性和跨 Link 路径查询对象",
        },
        {
            "name": "get_object_detail",
            "purpose": "根据对象主键获取单个对象详情",
        },
        {
            "name": "aggregate_objects",
            "purpose": "按对象属性或跨 Link 路径做分组聚合",
        },
        {
            "name": "exclude_objects",
            "purpose": "执行不存在类排除查询（NOT EXISTS）",
        },
        {
            "name": "execute_action",
            "purpose": "执行写操作 Action",
        },
    ]
    if any(relevant_object_sets.values()):
        system_tools.insert(3, {
            "name": "query_object_set",
            "purpose": "查询当前对象相关的预定义语义集合",
        })

    lines = ["## 当前对象能力"]
    for item in object_caps:
        lines.append(f"- {item['type']}({item['display']})")
        prop_parts = []
        for prop in item["properties"]:
            suffix = "[pk]" if prop["kind"] == "primary_key" else ("[derived]" if prop["kind"] == "derived" else "")
            prop_parts.append(f"{prop['name']}({prop['dataType']}){suffix}")
        lines.append("  属性: " + ("、".join(prop_parts) if prop_parts else "无"))
        link_parts = [f"{link['path']} -> {link['targetType']}({link['display']})" for link in item["links"]]
        lines.append("  Link: " + ("、".join(link_parts) if link_parts else "无"))
        set_parts = [f"{obj_set['name']}({obj_set['display']})" for obj_set in item["objectSets"]]
        lines.append("  ObjectSet: " + ("、".join(set_parts) if set_parts else "无"))
        function_parts = []
        for fn in item["functions"]:
            params_str = ", ".join(
                f"{param['name']}:{param['type']}" + ("" if param["required"] else "?")
                for param in fn["params"]
            )
            function_parts.append(f"{fn['tool']}({params_str})")
        lines.append("  对象工具: " + ("、".join(function_parts) if function_parts else "无"))

    lines.append("## 当前系统工具")
    for tool in system_tools:
        lines.append(f"- {tool['name']}: {tool['purpose']}")

    return {
        "object_types": object_caps,
        "system_tools": system_tools,
        "summary_text": "\n".join(lines),
    }


def build_tool_schemas(relevant_types: list[str] | None = None) -> list[dict]:
    if relevant_types is None:
        relevant_types = list(OBJECT_TYPES.keys())
    relevant_object_sets = get_relevant_object_sets(relevant_types)
    relevant_object_set_names = [
        obj_set.api_name
        for type_name in relevant_types
        for obj_set in relevant_object_sets.get(type_name, [])
    ]
    schemas = [
        {
            "name": "infer_relevant_types",
            "description": "推断当前用户问题涉及哪些对象类型。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户原始问题"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "describe_object_capabilities",
            "description": "列出当前对象的业务属性、可用 Link 路径、ObjectSet 和对象绑定函数。后续系统工具的字段都必须使用这里返回的业务属性名。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": relevant_types},
                        "description": "当前问题涉及的对象类型列表",
                    },
                },
                "required": ["object_types"],
            },
        },
        {
            "name": "query_objects",
            "description": "在类型层面查询对象。filters、order_by 中涉及的字段必须使用 describe_object_capabilities 返回的对象属性名或 Link 路径。结果自动含派生属性（avgScore、passRate）。对 Score 结果会补充 studentName、courseName 和 teacherName。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "enum": relevant_types,
                        "description": "要查询的对象类型",
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "过滤条件，字段必须使用对象业务属性名（如 name、className、scoreValue）或合法跨 Link 路径（如 student.name、course.name）。支持以下格式（可混用）：\n"
                            "- 等值: {\"name\": \"张三\"}\n"
                            "- 运算符: {\"scoreValue\": {\"op\": \"gte\", \"value\": 85}}\n"
                            "  可用 op: eq ne gt gte lt lte like between in not_in is_null is_not_null\n"
                            "- between: {\"scoreValue\": {\"op\": \"between\", \"value\": [80, 90]}}\n"
                            "- in: {\"name\": {\"op\": \"in\", \"value\": [\"张三\", \"李四\"]}}\n"
                            "- 跨 Link: {\"student.name\": \"张三\", \"course.name\": \"高等数学\"}\n"
                            "- 跨 Link 运算符: {\"score.scoreValue\": {\"op\": \"gt\", \"value\": 60}}\n"
                            "- OR: {\"$or\": [{\"name\": \"张三\"}, {\"className\": \"理学院\"}]}"
                        ),
                    },
                    "fuzzy": {"type": "boolean", "description": "是否模糊匹配文本属性（标量值时有效）"},
                    "limit": {"type": "integer", "description": "返回上限（默认 20）"},
                    "order_by": {
                        "type": "string",
                        "description": "排序字段名，支持点号跨 Link，如 'scoreValue' 或 'course.name'",
                    },
                    "order_dir": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向"},
                },
                "required": ["object_type"],
            },
        },
        {
            "name": "get_object_detail",
            "description": "获取单个对象的完整详情（含派生属性）。参数是对象类型+ID，不是节点标识。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {"type": "string", "enum": relevant_types},
                    "object_id": {"type": "string", "description": "对象主键，使用业务编号字符串"},
                },
                "required": ["object_type", "object_id"],
            },
        },
        {
            "name": "execute_action",
            "description": "执行数据写入操作: " + "、".join(ACTION_TYPES.keys()) + "。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action_name": {"type": "string", "enum": list(ACTION_TYPES.keys())},
                    "params": {"type": "object", "description": "操作参数"},
                },
                "required": ["action_name"],
            },
        },
        {
            "name": "aggregate_objects",
            "description": (
                "通用聚合查询，支持对任意对象类型按维度分组统计。"
                "适用于：计数、求和、平均、最大/最小值、分组统计等。"
                "支持跨 Link 点号分组（如按 teacher.name 分组统计 Score）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "enum": relevant_types,
                        "description": "聚合的基础对象类型",
                    },
                    "aggregations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["count", "count_distinct", "sum", "avg", "min", "max"],
                                    "description": "聚合函数类型",
                                },
                                "field": {
                                    "type": "string",
                                    "description": "聚合字段（支持跨Link点号如 student.age）。count 可不传 field。",
                                },
                                "name": {
                                    "type": "string",
                                    "description": "结果别名（可选）",
                                },
                            },
                            "required": ["type"],
                        },
                        "description": "聚合定义列表",
                    },
                    "filters": {
                        "type": "object",
                        "description": "过滤条件（格式同 query_objects 的 filters，支持跨 Link 点号和运算符）",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "分组字段列表，支持跨 Link 点号（如 [\"student.name\", \"course.name\"]）",
                    },
                    "order_by": {
                        "type": "string",
                        "description": "排序字段（可以是 aggregation 的 name 或 group_by 字段别名如 student_name）",
                    },
                    "order_dir": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向（默认 desc）"},
                    "limit": {"type": "integer", "description": "返回上限（默认 50）"},
                    "having": {
                        "type": "object",
                        "description": (
                            "HAVING 过滤：对聚合结果进行过滤。键为聚合别名(name)，值为运算符格式。\n"
                            "示例: {\"cnt\": {\"op\": \"gte\", \"value\": 3}, \"avg_score\": {\"op\": \"gt\", \"value\": 80}}"
                        ),
                    },
                },
                "required": ["object_type", "aggregations"],
            },
        },
        {
            "name": "exclude_objects",
            "description": (
                "否定查询：找出「不存在」某种关联的对象。用于回答'哪些学生没有选过X课/X老师的课'、'哪些课没被Y班学生修读'等否定型问题。\n"
                "原理：对主对象做 NOT EXISTS 子查询，排除掉通过 Link 关联到满足条件的目标对象。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "enum": relevant_types,
                        "description": "主查询对象类型（要返回的对象类型）",
                    },
                    "exclude_link": {
                        "type": "string",
                        "description": (
                            "关联路径名（Link 的 api_name 或 reverse_name）。\n"
                            "如 Student 的反向关联名为 'scores'(Score->Student)，Course 的反向名为 'scores'(Score->Course)。"
                        ),
                    },
                    "exclude_target_type": {
                        "type": "string",
                        "enum": relevant_types,
                        "description": "关联目标类型（被排除的关联对象类型）",
                    },
                    "exclude_target_filters": {
                        "type": "object",
                        "description": (
                            "对关联目标的过滤条件（格式同 query_objects 的 filters）。\n"
                            "支持跨 Link 点号。为空表示'没有任何关联对象'。\n"
                            "示例: {\"course.teacher.name\": \"李教授\"} 或 {\"scoreValue\": {\"op\": \"lt\", \"value\": 60}}"
                        ),
                    },
                    "base_filters": {
                        "type": "object",
                        "description": "对主对象的基础过滤（如只看某个班的学生）",
                    },
                    "limit": {"type": "integer", "description": "返回上限（默认 50）"},
                },
                "required": ["object_type", "exclude_link", "exclude_target_type"],
            },
        },
    ]
    if relevant_object_set_names:
        schemas.insert(3, {
            "name": "query_object_set",
            "description": "查询预定义的 ObjectSet（具名对象集合）。可用: " + "、".join(
                f"{OBJECT_SETS[name].api_name}({OBJECT_SETS[name].display_name})" for name in relevant_object_set_names
            ) + "。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "set_name": {
                        "type": "string",
                        "enum": relevant_object_set_names,
                        "description": "ObjectSet 名称",
                    },
                    "filters": {"type": "object", "description": "在集合结果上额外过滤"},
                    "limit": {"type": "integer"},
                },
                "required": ["set_name"],
            },
        })
    return schemas


def build_system_prompt(relevant_types: list[str] | None = None) -> str:
    if relevant_types is None:
        relevant_types = list(OBJECT_TYPES.keys())

    return """你是一个 Ontology 对象查询助手。系统采用“对象推断 -> 对象能力发现 -> 查询执行”的流程。

## 工作流程
1. 如果需要确认问题涉及哪些对象，先调用 infer_relevant_types。
2. 在使用任何字段前，优先依据当前上下文中的对象能力信息；如果仍不确定，再调用 describe_object_capabilities。
3. 完成对象能力确认后，再调用 query_objects、query_object_set、get_object_detail、aggregate_objects、exclude_objects 或 execute_action。
4. 对象绑定函数通过 fn_* 工具直接调用，只对当前问题涉及的对象开放。

## 核心约束
1. 系统工具中的业务字段必须使用对象属性名，不要使用数据库列名，也不要使用中文属性别名。
2. 跨 Link 查询只使用对象能力信息中列出的 path token，例如 student.name、course.name、scores.scoreValue。
3. Score 查询结果会自动补充 studentName、courseName、teacherName，不要再重复查询 Student 或 Course 只为拿名称。
4. get_object_detail 需要对象主键；如果只有对象名称，先用 query_objects 找到对象，再取主键。
5. 如果字段或路径不确定，先重新查看当前对象能力，不要猜测不存在的属性。

## 输出要求
- 严格按以下格式输出：第一行 `结论：...`，第二行 `分析：...`
- 必须先给结论，再给简要分析过程
- `结论` 只写最终答案，不铺垫，不解释工具调用
- `分析` 只保留最关键的 1 到 2 个依据，简短说明即可
- 如果结果并列，直接在 `结论` 中点名并列对象；如果没找到，直接写没找到

## 规则
- “低于/小于/不超过 N” 用 {"op":"lt","value":N} 或 {"op":"lte","value":N}
- “高于/大于/超过 N” 用 {"op":"gt","value":N} 或 {"op":"gte","value":N}
- “超过X”=严格大于(gt)；“不低于X”=大于等于(gte)；“达到X”=大于等于(gte)
- 找最好/最差/最高/最低时优先使用 order_by + order_dir + limit=1
- $or 仅用于同一对象的直接属性条件；跨不同 Link 路径的 OR 需要拆成多次 query_objects
- 否定查询（没有 / 不存在 / 未修读）优先用 exclude_objects
- 找不到就说没找到，不编造数据"""


# ---- Score 上下文富化 ----

def enrich_score_context(results: list[dict]):
    """为 Score 对象批量补充 studentName、courseName、teacherName"""
    if not results or results[0].get("_objectType") != "Score":
        return
    obj_ids = [obj["id"] for obj in results if obj.get("id")]
    if not obj_ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(obj_ids))
    fk_rows = conn.execute(
        f"SELECT id, Sno, Cno FROM score WHERE id IN ({placeholders})",
        tuple(obj_ids)
    ).fetchall()
    conn.close()
    id_to_fk = {r["id"]: (r["Sno"], r["Cno"]) for r in fk_rows}
    sids, cids = set(), set()
    for obj in results:
        fk = id_to_fk.get(obj["id"])
        if fk:
            sid, cid = fk
            obj["studentSno"] = sid
            obj["courseCno"] = cid
            if sid:
                sids.add(sid)
            if cid:
                cids.add(cid)
    s_names, c_names, c_teachers = {}, {}, {}
    if sids:
        conn = get_connection()
        rows = conn.execute(f"SELECT Sno, name FROM student WHERE Sno IN ({','.join('?'*len(sids))})", tuple(sids)).fetchall()
        s_names = {r["Sno"]: r["name"] for r in rows}
        conn.close()
    if cids:
        conn = get_connection()
        rows = conn.execute(f"SELECT Cno, name FROM course WHERE Cno IN ({','.join('?'*len(cids))})", tuple(cids)).fetchall()
        for r in rows:
            c_names[r["Cno"]] = r["name"]
        tc_rows = conn.execute(
            f"SELECT tc.Cno, t.Tno, t.name FROM tc JOIN teacher t ON tc.Tno = t.Tno WHERE tc.Cno IN ({','.join('?'*len(cids))})",
            tuple(cids)
        ).fetchall()
        for row in tc_rows:
            c_teachers.setdefault(row["Cno"], []).append(row["name"])
        conn.close()
    for obj in results:
        sid = obj.get("studentSno") or obj.get("Sno")
        cid = obj.get("courseCno") or obj.get("Cno")
        if sid and sid in s_names:
            obj["studentName"] = s_names[sid]
        if cid and cid in c_names:
            obj["courseName"] = c_names[cid]
            if cid in c_teachers:
                obj["teacherName"] = "、".join(c_teachers[cid])


# ---- 工具执行 ----

def execute_tool(tool_name: str, inp: dict) -> dict:
    """执行 OAG 工具，返回 {content, summary}。"""
    try:
        if tool_name == "infer_relevant_types":
            query_text = inp.get("query", "")
            relevant_types = infer_relevant_types(query_text)
            content = "推断相关对象类型：" + "、".join(relevant_types)
            return {
                "content": content,
                "summary": f"relevant types: {', '.join(relevant_types)}",
                "data": {"relevant_types": relevant_types},
            }

        if tool_name == "describe_object_capabilities":
            object_types = inp.get("object_types", []) or list(OBJECT_TYPES.keys())
            capability = build_object_capability_data(object_types)
            return {
                "content": capability["summary_text"],
                "summary": f"described {len(capability['object_types'])} object types",
                "data": capability,
            }

        elif tool_name == "query_objects":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            filters = inp.get("filters", {})
            if filters:
                filters = normalize_filters(filters)
            fuzzy = inp.get("fuzzy", False)
            limit = min(inp.get("limit", 20), 100)
            order_by = inp.get("order_by")
            order_dir = inp.get("order_dir", "asc")

            results = query_objects_v2(obj_type, filters=filters, fuzzy=fuzzy, limit=limit, order_by=order_by, order_dir=order_dir)
            if not results:
                return {"content": f"未找到匹配的 {obj_type} 对象", "summary": f"empty {obj_type}", "data": []}
            enrich_score_context(results)

            lines = [f"找到 {len(results)} 个 {obj_type} 对象："]
            for obj in results[:15]:
                parts = []
                obj_name = obj.get("name", "")
                for k, v in obj.items():
                    if k.startswith("_") or k == "name":
                        continue
                    parts.append(f"{k}={v}")
                obj_key = obj.get("_id") or obj.get("Sno") or obj.get("Tno") or obj.get("Cno") or obj.get("id", "?")
                label = obj_name if obj_name else f"{obj_type}#{obj_key}"
                lines.append(f"  {obj_type}#{obj_key} '{label}': {', '.join(parts[:8])}")
            if len(results) > 15:
                lines.append(f"  ...及其他 {len(results) - 15} 个结果")
            return {"content": "\n".join(lines), "summary": f"found {len(results)} {obj_type}", "data": results}

        elif tool_name == "query_object_set":
            set_name = inp.get("set_name", "")
            filters = inp.get("filters", {})
            if filters:
                filters = normalize_filters(filters)
            limit = min(inp.get("limit", 20), 100)

            result = query_object_set(set_name, filters=filters, limit=limit)
            if not result.get("success"):
                return {"content": f"ObjectSet 错误: {result.get('error')}", "summary": "error", "error": result.get('error')}
            results = result["data"]
            set_def = OBJECT_SETS.get(set_name)
            obj_type = set_def.object_type if set_def else "unknown"
            lines = [f"{set_def.display_name if set_def else set_name} 包含 {len(results)} 个 {obj_type}："]
            for obj in results[:15]:
                parts = []
                obj_name = obj.get("name", "")
                for k, v in obj.items():
                    if k.startswith("_") or k == "name":
                        continue
                    parts.append(f"{k}={v}")
                label = obj_name if obj_name else f"{obj_type}#{obj.get('_id') or obj.get('Sno') or obj.get('Tno') or obj.get('Cno') or obj.get('id', '?')}"
                lines.append(f"  {label}: {', '.join(parts[:8])}")
            return {"content": "\n".join(lines), "summary": f"set {set_name}: {len(results)} results", "data": results}

        elif tool_name == "get_object_detail":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            obj_id = inp.get("object_id", "")
            obj = get_object(obj_type, obj_id)
            if obj is None:
                return {"content": f"{obj_type} object_id={obj_id} 不存在", "summary": "not found", "error": "not found"}
            fill_derived_batch([obj], obj_type)
            lines = [f"{obj_type}#{obj_id} '{obj.get('name', '')}'"]
            for k, v in obj.items():
                if not k.startswith("_"):
                    lines.append(f"  {k}: {v}")
            return {"content": "\n".join(lines), "summary": f"detail {obj_type}#{obj_id}", "data": obj}

        elif tool_name == "execute_action":
            action_name = inp.get("action_name", "")
            params = inp.get("params", {})
            result = execute_action(action_name, params)
            if result.get("success"):
                reload_graph()
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"executed {action_name}", "data": result, "error": result.get("error")}

        elif tool_name == "aggregate_objects":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            aggregations = inp.get("aggregations", [])
            filters = inp.get("filters", {})
            if filters:
                filters = normalize_filters(filters)
            group_by = inp.get("group_by")
            having = inp.get("having")
            order_by = inp.get("order_by")
            order_dir = inp.get("order_dir", "desc")
            limit = min(inp.get("limit", 50), 200)

            result = aggregate_objects(
                obj_type, aggregations=aggregations, filters=filters,
                group_by=group_by, having=having, order_by=order_by, order_dir=order_dir, limit=limit,
            )
            if not result.get("success"):
                return {"content": f"聚合错误: {result.get('error')}", "summary": "agg error", "error": result.get("error")}
            data = result["data"]
            lines = [f"聚合结果（{len(data)} 行）："]
            for row in data[:20]:
                parts = [f"{k}={v}" for k, v in row.items()]
                lines.append(f"  {', '.join(parts)}")
            if len(data) > 20:
                lines.append(f"  ...及其他 {len(data) - 20} 行")
            return {"content": "\n".join(lines), "summary": f"agg {obj_type}: {len(data)} rows", "data": data}

        elif tool_name == "exclude_objects":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            exclude_link = inp.get("exclude_link", "")
            exclude_target_type = TYPE_ALIASES.get(inp.get("exclude_target_type", ""), inp.get("exclude_target_type", ""))
            exclude_target_filters = inp.get("exclude_target_filters")
            if exclude_target_filters:
                exclude_target_filters = normalize_filters(exclude_target_filters)
            base_filters = inp.get("base_filters")
            if base_filters:
                base_filters = normalize_filters(base_filters)
            limit = min(inp.get("limit", 50), 100)

            results = exclude_objects(
                obj_type,
                exclude_link=exclude_link,
                exclude_target_type=exclude_target_type,
                exclude_target_filters=exclude_target_filters,
                base_filters=base_filters,
                limit=limit,
            )
            if not results:
                return {"content": f"没有找到满足排除条件的 {obj_type} 对象", "summary": f"exclude empty {obj_type}", "data": []}
            enrich_score_context(results)
            lines = [f"排除后找到 {len(results)} 个 {obj_type} 对象："]
            for obj in results[:15]:
                parts = []
                obj_name = obj.get("name", "")
                for k, v in obj.items():
                    if k.startswith("_") or k == "name":
                        continue
                    parts.append(f"{k}={v}")
                label = obj_name if obj_name else f"{obj_type}#{obj.get('id', '?')}"
                lines.append(f"  {obj_type}#{obj.get('id', '?')} '{label}': {', '.join(parts[:8])}")
            return {"content": "\n".join(lines), "summary": f"exclude {obj_type}: {len(results)} results", "data": results}

        elif tool_name.startswith("fn_"):
            func_name = tool_name[3:]
            result = call_function(func_name, inp)
            return {"content": json.dumps(result, ensure_ascii=False), "summary": f"fn:{func_name} → {result.get('data', result.get('error', '?'))}", "data": result.get("data", result), "error": result.get("error")}

        return {"content": f"未知工具: {tool_name}", "summary": "unknown tool"}
    except Exception as e:
        return {"content": f"工具执行错误: {e}", "summary": "error"}


# ---- 主入口函数（由 server.py 调用）----

async def handle_oag_query(query_text: str, max_iterations: int = 20) -> dict:
    """OAG 模式：LLM 在对象类型层操作，引擎负责 Link JOIN 编译。"""
    infer_result = execute_tool("infer_relevant_types", {"query": query_text})
    relevant_types = infer_result.get("data", {}).get("relevant_types", [])
    capability_result = execute_tool("describe_object_capabilities", {"object_types": relevant_types})

    system_prompt = build_system_prompt(relevant_types)
    tool_schemas = build_tool_schemas(relevant_types) + build_object_bound_tool_schemas(relevant_types)

    # 可用工具摘要（供前端展示）
    available_tools = [{"name": t["name"], "description": t["description"]} for t in tool_schemas]

    bootstrap_context = (
        "系统已完成对象推断和对象能力发现。后续只能使用当前对象能力中列出的业务字段、Link 路径和工具。\n\n"
        + capability_result.get("content", "")
        + f"\n\n用户问题：{query_text}"
    )

    messages = [{"role": "user", "content": bootstrap_context}]
    exploration_log = [
        {
            "step": 0,
            "tool": "infer_relevant_types",
            "input": {"query": query_text},
            "summary": infer_result["summary"],
            "result_data": infer_result.get("data"),
            "result_content": infer_result.get("content"),
        },
        {
            "step": 0,
            "tool": "describe_object_capabilities",
            "input": {"object_types": relevant_types},
            "summary": capability_result["summary"],
            "result_data": capability_result.get("data"),
            "result_content": capability_result.get("content"),
        },
    ]
    final_answer = None

    for iteration in range(max_iterations):
        resp = await call_llm(system_prompt, tool_schemas, messages)
        content_blocks = resp.get("content", [])
        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        # 本轮 LLM 在调工具前输出的推断文本
        reasoning = " ".join(text_parts).strip() if text_parts and tool_use_blocks else ""

        if tool_use_blocks:
            messages.append({"role": "assistant", "content": content_blocks})
            tool_results_content = []
            first = True
            for tool in tool_use_blocks:
                tool_name = tool["name"]
                tool_input = tool.get("input", {})
                tool_id = tool.get("id", "")
                tool_result = execute_tool(tool_name, tool_input)
                entry = {
                    "step": iteration + 1,
                    "tool": tool_name,
                    "input": tool_input,
                    "summary": tool_result["summary"],
                    "result_data": tool_result.get("data"),
                    "result_content": tool_result.get("content"),
                    "result_error": tool_result.get("error"),
                }
                if first:
                    if reasoning:
                        entry["reasoning"] = reasoning
                    entry["available_tools"] = available_tools
                    first = False
                exploration_log.append(entry)
                tool_results_content.append({"type": "tool_result", "tool_use_id": tool_id, "content": tool_result["content"]})

            if iteration + 1 >= 2 and tool_results_content:
                tool_results_content[-1]["content"] += "\n\n[数据应该足够了。请严格按两行格式回答：第一行 `结论：...`，第二行 `分析：...`。必须先给结论，再简要分析，不要复述过程，不要再调工具。]"

            messages.append({"role": "user", "content": tool_results_content})
            continue

        if text_parts:
            final_answer = "".join(text_parts)
        elif exploration_log:
            steps_desc = "; ".join(f"步骤{s['step']}: {s['tool']} → {s['summary']}" for s in exploration_log)
            final_answer = f"查询完成（{len(exploration_log)} 步）：{steps_desc}"
        else:
            final_answer = "无法生成回答"
        break

    if final_answer is None:
        final_answer = "未找到相关信息"

    final_answer = format_final_answer(final_answer)

    return {"success": True, "answer": final_answer, "exploration_log": exploration_log, "available_tools": available_tools}




if __name__ == "__main__":
    import asyncio
    result = asyncio.run(handle_oag_query("王教授教授哪些课程？"))
    print(result["answer"])