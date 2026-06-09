"""
OAG（Ontology Augmented Generation）模式 NL 查询
LLM 在对象类型层面操作，引擎负责 Link JOIN 编译和派生属性自动计算。
路由: POST /ontology/nl-query-oag
"""

from __future__ import annotations
import httpx
import json
import os
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

# 共用的中文容错映射（与 nl_graph.py 保持一致）
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
        mapped_key = PROP_ALIASES.get(key, key)
        if mapped_key == "$or" and isinstance(value, list):
            normalized[mapped_key] = [normalize_filters(item) if isinstance(item, dict) else item for item in value]
            continue
        prop_name = mapped_key.split(".")[-1]
        normalized[mapped_key] = normalize_filter_value(prop_name, value)
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


# ---- Schema 上下文 ----

def build_llm_context() -> str:
    """构建给 LLM 的 Schema 上下文（与 nl_batch.py 同内容，供 OAG system prompt 使用）"""
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


def build_tool_schemas(relevant_types: list[str] | None = None) -> list[dict]:
    if relevant_types is None:
        relevant_types = list(OBJECT_TYPES.keys())
    return [
        {
            "name": "list_object_types",
            "description": "列出系统中所有可用的对象类型、ObjectSet、属性、Link 关系、绑定函数。",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "query_objects",
            "description": "在类型层面查询对象，支持跨 Link 点号过滤和多种运算符。结果自动含派生属性（avgScore、passRate）。对 Score 结果会补充 studentName 和 courseName。",
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
                            "过滤条件，支持以下格式（可混用）：\n"
                            "- 等值: {\"name\": \"张三\"}\n"
                            "- 运算符: {\"scoreValue\": {\"op\": \"gte\", \"value\": 85}}\n"
                            "  可用 op: eq ne gt gte lt lte like between in not_in is_null is_not_null\n"
                            "- between: {\"scoreValue\": {\"op\": \"between\", \"value\": [80, 90]}}\n"
                            "- in: {\"name\": {\"op\": \"in\", \"value\": [\"张三\", \"李四\"]}}\n"
                            "- 跨 Link: {\"student.name\": \"张三\", \"course.name\": \"数学\"}\n"
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
            "name": "query_object_set",
            "description": "查询预定义的 ObjectSet（具名对象集合）。可用: TopStudents(优秀学生)、PassedCourses(及格课程)。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "set_name": {
                        "type": "string",
                        "enum": ["TopStudents", "PassedCourses"],
                        "description": "ObjectSet 名称",
                    },
                    "filters": {"type": "object", "description": "在集合结果上额外过滤"},
                    "limit": {"type": "integer"},
                },
                "required": ["set_name"],
            },
        },
        {
            "name": "get_object_detail",
            "description": "获取单个对象的完整详情（含派生属性）。参数是对象类型+ID，不是节点标识。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "object_type": {"type": "string", "enum": relevant_types},
                    "object_id": {"type": "integer", "description": "对象的数字 ID"},
                },
                "required": ["object_type", "object_id"],
            },
        },
        {
            "name": "execute_action",
            "description": "执行数据写入操作: createScore、updateScore、deleteScore、assignTeacher。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action_name": {"type": "string", "enum": ["createScore", "updateScore", "deleteScore", "assignTeacher"]},
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


def build_system_prompt(relevant_types: list[str] | None = None) -> str:
    if relevant_types is None:
        relevant_types = list(OBJECT_TYPES.keys())
    schema = build_llm_context()

    # 生成本次可用的对象绑定函数描述
    relevant_set = set(relevant_types)
    fn_lines = []
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
        params_str = ", ".join(f"{p.name}:{p.param_type}" + ("" if p.required else "?") for p in func_def.params)
        fn_lines.append(f"- fn_{func_name}({params_str}) → [{type_label}] {func_def.display_name}")

    types_str = "、".join(relevant_types)
    fn_section = "\n".join(fn_lines) if fn_lines else "（无）"

    return f"""你是一个 Ontology 对象查询助手。系统使用 Ontology Augmented Generation（OAG）模式：所有数据建模为业务对象（Student、Course、Score、Teacher），Ontology 提供 Data（对象+Link）、Logic（函数）、Action（写操作）三类能力来增强你的回答。

## 本次查询推断的对象类型
{types_str}

## 本次可用的对象绑定函数
{fn_section}

## 核心原则
1. 你通过 **query_objects** 在类型层面声明查询意图，用属性过滤条件返回结果。不要遍历实例图。
2. 对象属性支持**跨 Link 点号过滤**（如 filters={{"student.name":"张三","course.name":"数学"}}），系统自动处理跨表 JOIN。
3. 过滤条件支持**多种运算符**，value 可以是标量（等值）或 {{"op":"运算符","value":值}} 格式：
   - 比较: gt / gte / lt / lte / ne（大于/大于等于/小于/小于等于/不等于）
   - 范围: between（需 value=[下限,上限]）
   - 集合: in / not_in（需 value=[...]）
   - 空值: is_null / is_not_null（无需 value）
   - 模糊: like（value 中直接写 %...%）
4. 支持 **$or 条件**：filters={{"$or":[{{"name":"张三"}},{{"className":"理学院"}}]}}，括号内支持运算符。
5. **order_by 支持点号跨 Link**，如 order_by="course.name" 按关联课程名排序。
6. 查询结果**自动包含派生属性**（avgScore、passRate）。Score 查询结果**自动附带 studentName、courseName、teacherName**。
7. 预定义的 ObjectSet 通过 **query_object_set** 引用，如 TopStudents、PassedCourses。
8. **对象绑定函数通过 `fn_{{funcName}}` 工具直接调用**（如 fn_getAvgScore、fn_getPassRate），无需经过 call_function 包装。需要先用 query_objects 拿到对象 id，再传给函数。
9. 获取足够信息后立即用中文简短回答，不要暴露内部 ID 给用户。
10. **再次强调：Score 结果已经包含 studentName、courseName、teacherName，你不需要再单独查 Student 或 Course 表！**
11. **Student.gender 在底层数据中使用 `M`/`F` 编码；当用户说“男/女”时，你应分别按 `M`/`F` 过滤。**

## 输出要求
- 严格按以下格式输出：第一行 `结论：...`，第二行 `分析：...`
- 必须先给结论，再给简要分析过程
- `结论` 只写最终答案，不铺垫，不解释工具调用
- `分析` 只保留最关键的 1 到 2 个依据，简短说明即可
- 如果结果并列，直接在 `结论` 中点名并列对象；如果没找到，直接写没找到

## Schema

{schema}

## ObjectSets（预定义集合）
- **TopStudents**: 平均分 >= 85 的优秀学生
- **PassedCourses**: 课程平均分 >= 60 的及格课程

## 常用查询模式
- "张三的数学成绩" → query_objects(type="Score", filters={{"student.name": "张三", "course.name": "数学"}})
- "优秀学生有哪些" → query_object_set(set_name="TopStudents")
- "张三的平均分" → query_objects(type="Student", filters={{"name": "张三"}})，结果含 avgScore
- "谁的成绩最差" → query_objects(type="Score", order_by="scoreValue", order_dir="asc", limit=1)
- "高等数学谁最高分" → query_objects(type="Score", filters={{"course.name": "高等数学"}}, order_by="scoreValue", order_dir="desc", limit=1)
- "有哪些类型的对象" → list_object_types
- "成绩在80到90之间的" → query_objects(type="Score", filters={{"scoreValue": {{"op":"between","value":[80,90]}}}})
- "成绩大于85分的学生" → query_objects(type="Score", filters={{"scoreValue": {{"op":"gt","value":85}}}})
- "高等数学低于80分的学生" → query_objects(type="Score", filters={{"course.name":"高等数学","scoreValue":{{"op":"lt","value":80}}}})
- "数据结构不及格（<60）的" → query_objects(type="Score", filters={{"course.name":"数据结构","scoreValue":{{"op":"lt","value":60}}}})
- "高等数学低于80 **或** 数据结构低于80" → 分两次 query_objects 分别查，合并 studentName 列表（$or 不支持跨 Link 条件，须拆开查）
- "张三或李四的成绩" → query_objects(type="Score", filters={{"student.name": {{"op":"in","value":["张三","李四"]}}}})
- "还没有老师的课程" → query_objects(type="Course", filters={{"teacherId": {{"op":"is_null"}}}})
- "按课程名排序所有成绩" → query_objects(type="Score", order_by="course.name")
- "有哪些女学生" → query_objects(type="Student", filters={{"gender": "F"}})
- "哪些学生没有选修过李教授的课" → exclude_objects(object_type="Student", exclude_link="earnedBy", exclude_target_type="Score", exclude_target_filters={{"course.teacher.name":"李教授"}})
- "哪些课程没被英语2201学生修读" → exclude_objects(object_type="Course", exclude_link="forCourse", exclude_target_type="Score", exclude_target_filters={{"student.className":"英语2201"}})
- "每门课选课人数大于3的" → aggregate_objects(type="Score", aggregations=[{{"type":"count","name":"cnt"}}], group_by=["course.name"], having={{"cnt":{{"op":"gt","value":3}}}})

## 规则
- **Score 结果已经包含 studentName、courseName、teacherName，不要再单独查 Student/Course！**
- "低于/小于/不超过 N" 必须用 {{"op":"lt","value":N}} 或 {{"op":"lte","value":N}}，**禁止用等值 N 代替**
- "高于/大于/超过 N" 必须用 {{"op":"gt","value":N}} 或 {{"op":"gte","value":N}}
- **"超过X"=严格大于(gt)，"不低于X"=大于等于(gte)，"达到X"=大于等于(gte)** — 注意区分边界
- 找最好/最差/最高/最低时用 order_by + order_dir + limit=1
- **跨不同 Link 路径的 OR（如 高等数学低于80 OR 数据结构低于80）须拆成两次 query_objects，合并结果**
- $or 仅支持同一对象的直接属性条件，不支持跨 Link
- **否定查询（"没有"、"不存在"、"未修读"）务必使用 exclude_objects 工具**，不要尝试手动做集合差
- **模糊匹配提示**：当用户口语表达可能与数据库精确值不同时（如"英语2201班" vs "英语2201"），使用 fuzzy=true 或 like 操作符（{{"op":"like","value":"%英语2201%"}}）
- 知道某属性值但不知道具体类型时，先查对应类型，再用跨 Link 过滤
- 找不到就说没找到，不编造数据
- 跨 Link 过滤优先用点号语法，而非多步查询"""


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
        f"SELECT id, student_id, course_id FROM score WHERE id IN ({placeholders})",
        tuple(obj_ids)
    ).fetchall()
    conn.close()
    id_to_fk = {r["id"]: (r["student_id"], r["course_id"]) for r in fk_rows}
    sids, cids = set(), set()
    for obj in results:
        fk = id_to_fk.get(obj["id"])
        if fk:
            sid, cid = fk
            obj["studentId"] = sid
            obj["courseId"] = cid
            if sid:
                sids.add(sid)
            if cid:
                cids.add(cid)
    s_names, c_names, c_teachers = {}, {}, {}
    if sids:
        conn = get_connection()
        rows = conn.execute(f"SELECT id, name FROM student WHERE id IN ({','.join('?'*len(sids))})", tuple(sids)).fetchall()
        s_names = {r["id"]: r["name"] for r in rows}
        conn.close()
    if cids:
        conn = get_connection()
        rows = conn.execute(f"SELECT id, name, teacher_id FROM course WHERE id IN ({','.join('?'*len(cids))})", tuple(cids)).fetchall()
        tids = set()
        for r in rows:
            c_names[r["id"]] = r["name"]
            if r["teacher_id"]:
                tids.add(r["teacher_id"])
                c_teachers[r["id"]] = r["teacher_id"]
        if tids:
            t_rows = conn.execute(f"SELECT id, name FROM teacher WHERE id IN ({','.join('?'*len(tids))})", tuple(tids)).fetchall()
            t_names = {r["id"]: r["name"] for r in t_rows}
            for cid, tid in c_teachers.items():
                c_teachers[cid] = t_names.get(tid, f"Teacher#{tid}")
        conn.close()
    for obj in results:
        sid = obj.get("studentId") or obj.get("student_id")
        cid = obj.get("courseId") or obj.get("course_id")
        if sid and sid in s_names:
            obj["studentName"] = s_names[sid]
        if cid and cid in c_names:
            obj["courseName"] = c_names[cid]
            if cid in c_teachers:
                obj["teacherName"] = c_teachers[cid]


# ---- 工具执行 ----

def execute_tool(tool_name: str, inp: dict) -> dict:
    """执行 OAG 工具，返回 {content, summary}。"""
    try:
        if tool_name == "list_object_types":
            types_info = []
            for type_name, obj_def in OBJECT_TYPES.items():
                props = [{"name": p.name, "type": p.prop_type, "dataType": p.data_type} for p in obj_def.properties]
                out_links = [{"name": l.api_name, "target": l.target_type, "display": l.display_name} for l in LINK_TYPES.values() if l.source_type == type_name]
                in_links = [{"name": l.reverse_name, "target": l.source_type, "display": f"反向{l.display_name}"} for l in LINK_TYPES.values() if l.target_type == type_name]
                bound_funcs = [f.api_name for f in FUNCTIONS.values() if f.bound_object == type_name]
                types_info.append({"type": type_name, "display": obj_def.display_name, "properties": props, "links": out_links + in_links, "functions": bound_funcs})
            set_info = [{"name": s.api_name, "display": s.display_name, "type": s.object_type, "description": s.description} for s in OBJECT_SETS.values()]
            content = json.dumps({"object_types": types_info, "object_sets": set_info}, ensure_ascii=False)
            return {"content": content, "summary": f"listed {len(types_info)} types, {len(set_info)} sets", "data": {"object_types": types_info, "object_sets": set_info}}

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
                label = obj_name if obj_name else f"{obj_type}#{obj.get('id', '?')}"
                lines.append(f"  {obj_type}#{obj.get('id', '?')} '{label}': {', '.join(parts[:8])}")
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
                label = obj_name if obj_name else f"{obj_type}#{obj.get('id', '?')}"
                lines.append(f"  {label}: {', '.join(parts[:8])}")
            return {"content": "\n".join(lines), "summary": f"set {set_name}: {len(results)} results", "data": results}

        elif tool_name == "get_object_detail":
            obj_type = TYPE_ALIASES.get(inp.get("object_type", ""), inp.get("object_type", ""))
            obj_id = inp.get("object_id", 0)
            obj = get_object(obj_type, obj_id)
            if obj is None:
                return {"content": f"{obj_type} id={obj_id} 不存在", "summary": "not found", "error": "not found"}
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
    relevant_types = infer_relevant_types(query_text)
    system_prompt = build_system_prompt(relevant_types)
    tool_schemas = build_tool_schemas(relevant_types) + build_object_bound_tool_schemas(relevant_types)

    # 可用工具摘要（供前端展示）
    available_tools = [{"name": t["name"], "description": t["description"]} for t in tool_schemas]

    messages = [{"role": "user", "content": query_text}]
    exploration_log = [{"step": 0, "tool": "type_inference", "input": {"query": query_text}, "summary": f"推断相关对象类型: {', '.join(relevant_types)}"}]
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
