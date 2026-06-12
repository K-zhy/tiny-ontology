"""OAG 元能力：对象推断、能力描述、System Prompt 构建。

这里的函数是 Pipeline 的前两个阶段（infer_types / discover_capabilities），
以及构建 LLM 上下文所需的格式化工具。
"""
from __future__ import annotations
import re

from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, FUNCTIONS, INTERFACES, OBJECT_SETS
from .utils import TYPE_ALIASES

# ---- 可扩展的推断关键词 ----
# 默认从 registry 的 display_name/api_name 派生，也可注入领域专用词。
# 更换 OBJECT_TYPES 后只需更新此字典（或清空让 registry 自动派生）。
EXTRA_TYPE_KEYWORDS: dict[str, list[str]] = {
    "Student": ["学生", "同学", "平均分", "avgscore", "学号"],
    "Teacher": ["老师", "教师", "讲师", "教授", "任课"],
    "Course":  ["课程", "科目", "学分", "通过率", "passrate"],
    "Score":   ["成绩", "分数", "考试", "不及格", "挂科", "高分", "低分"],
}


def infer_relevant_types(query_text: str) -> list[str]:
    """从查询文本推断涉及的对象类型。

    关键词来源：
    1. registry 中每个 ObjectType 的 display_name + api_name（自动适应新对象定义）
    2. EXTRA_TYPE_KEYWORDS 中可配置的额外关键词
    """
    q = query_text.lower()
    matched: set[str] = set()

    for type_name, obj_def in OBJECT_TYPES.items():
        registry_kws = [type_name.lower(), obj_def.display_name.lower()]
        extra_kws = EXTRA_TYPE_KEYWORDS.get(type_name, [])
        if any(kw in q for kw in registry_kws + extra_kws):
            matched.add(type_name)

    # Score 查询通常需要 Student 和 Course 的名称富化
    if "Score" in matched:
        matched.update(["Student", "Course"])
    if re.search(r'[\u4e00-\u9fff]{2,3}(?:的|同学|学生)', query_text):
        matched.add("Student")

    result = [t for t in OBJECT_TYPES.keys() if t in matched]
    return result if result else list(OBJECT_TYPES.keys())


def get_relevant_object_sets(object_types: list[str]) -> dict[str, list]:
    """返回当前对象类型上定义的 ObjectSet，按对象类型分组。"""
    normalized = _normalize_types(object_types)
    relevant: dict[str, list] = {t: [] for t in normalized}
    for obj_set in OBJECT_SETS.values():
        if obj_set.object_type in relevant:
            relevant[obj_set.object_type].append(obj_set)
    return relevant


def _normalize_types(object_types: list[str]) -> list[str]:
    result: list[str] = []
    for t in object_types:
        mapped = TYPE_ALIASES.get(t, t)
        if mapped in OBJECT_TYPES and mapped not in result:
            result.append(mapped)
    return result


def build_object_capability_data(object_types: list[str]) -> dict:
    """构建对象的属性、Link、ObjectSet、函数能力描述，供 bootstrap 消息和前端展示使用。"""
    normalized = _normalize_types(object_types)
    relevant_object_sets = get_relevant_object_sets(normalized)

    object_caps = []
    for type_name in normalized:
        obj_def = OBJECT_TYPES[type_name]

        properties = [
            {"name": p.name, "dataType": p.data_type, "kind": p.prop_type}
            for p in obj_def.properties
        ]

        links = []
        for link in LINK_TYPES.values():
            if link.source_type == type_name:
                links.append({
                    "path": link.target_type.lower(), "direction": "forward",
                    "targetType": link.target_type, "display": link.display_name,
                })
            if link.target_type == type_name:
                links.append({
                    "path": link.reverse_name, "direction": "reverse",
                    "targetType": link.source_type, "display": f"反向{link.display_name}",
                })

        object_sets = [
            {"name": s.api_name, "display": s.display_name, "description": s.description}
            for s in relevant_object_sets.get(type_name, [])
        ]

        seen: set[str] = set()
        functions = []
        for func_name, func_def in FUNCTIONS.items():
            if func_def.func_type == "validation":
                continue
            if func_def.bound_object == type_name:
                pass
            elif func_def.bound_object in INTERFACES and type_name in INTERFACES[func_def.bound_object].implementors:
                pass
            else:
                continue
            if func_name in seen:
                continue
            seen.add(func_name)
            functions.append({
                "tool": f"fn_{func_name}",
                "display": func_def.display_name,
                "returnType": func_def.return_type,
                "params": [
                    {"name": p.name, "type": p.param_type, "required": p.required}
                    for p in func_def.params
                ],
            })

        object_caps.append({
            "type": type_name, "display": obj_def.display_name,
            "properties": properties, "links": links,
            "objectSets": object_sets, "functions": functions,
        })

    # 系统工具列表（用于 bootstrap 消息中的 "## 当前系统工具" 块）
    system_tools = [
        {"name": "infer_relevant_types",        "purpose": "推断当前问题涉及哪些对象类型"},
        {"name": "describe_object_capabilities", "purpose": "列出当前对象的属性、Link、ObjectSet 和绑定函数"},
        {"name": "query_objects",               "purpose": "按对象属性和跨 Link 路径查询对象"},
        {"name": "get_object_detail",           "purpose": "根据对象主键获取单个对象详情"},
        {"name": "aggregate_objects",           "purpose": "按对象属性或跨 Link 路径做分组聚合"},
        {"name": "exclude_objects",             "purpose": "执行不存在类排除查询（NOT EXISTS）"},
        {"name": "execute_action",              "purpose": "执行写操作 Action"},
    ]
    if any(relevant_object_sets.values()):
        system_tools.insert(3, {"name": "query_object_set", "purpose": "查询当前对象相关的预定义语义集合"})

    # 生成 summary_text（注入 bootstrap 消息）
    lines = ["## 当前对象能力"]
    for item in object_caps:
        lines.append(f"- {item['type']}({item['display']})")
        prop_parts = []
        for p in item["properties"]:
            suffix = "[pk]" if p["kind"] == "primary_key" else ("[derived]" if p["kind"] == "derived" else "")
            prop_parts.append(f"{p['name']}({p['dataType']}){suffix}")
        lines.append("  属性: " + ("、".join(prop_parts) if prop_parts else "无"))
        link_parts = [f"{l['path']} -> {l['targetType']}({l['display']})" for l in item["links"]]
        lines.append("  Link: " + ("、".join(link_parts) if link_parts else "无"))
        set_parts = [f"{s['name']}({s['display']})" for s in item["objectSets"]]
        lines.append("  ObjectSet: " + ("、".join(set_parts) if set_parts else "无"))
        fn_parts = []
        for fn in item["functions"]:
            params_str = ", ".join(
                f"{p['name']}:{p['type']}" + ("" if p["required"] else "?")
                for p in fn["params"]
            )
            fn_parts.append(f"{fn['tool']}({params_str})")
        lines.append("  对象工具: " + ("、".join(fn_parts) if fn_parts else "无"))

    lines.append("## 当前系统工具")
    for tool in system_tools:
        lines.append(f"- {tool['name']}: {tool['purpose']}")

    return {
        "object_types": object_caps,
        "system_tools": system_tools,
        "summary_text": "\n".join(lines),
    }


def build_system_prompt(relevant_types: list[str] | None = None) -> str:  # noqa: ARG001
    """构建 OAG 模式的 System Prompt。当前为固定模板，可在子类中覆盖实现个性化提示词。"""
    return (
        '你是一个 Ontology 对象查询助手。系统采用"对象推断 -> 对象能力发现 -> 查询执行"的流程。\n\n'
        "## 工作流程\n"
        "1. 如果需要确认问题涉及哪些对象，先调用 infer_relevant_types。\n"
        "2. 在使用任何字段前，优先依据当前上下文中的对象能力信息；如果仍不确定，再调用 describe_object_capabilities。\n"
        "3. 完成对象能力确认后，再调用 query_objects、query_object_set、get_object_detail、aggregate_objects、exclude_objects 或 execute_action。\n"
        "4. 对象绑定函数通过 fn_* 工具直接调用，只对当前问题涉及的对象开放。\n\n"
        "## 核心约束\n"
        "1. 系统工具中的业务字段必须使用对象属性名，不要使用数据库列名，也不要使用中文属性别名。\n"
        "2. 跨 Link 查询只使用对象能力信息中列出的 path token，例如 student.name、course.name、scores.scoreValue。\n"
        "3. Score 查询结果会自动补充 studentName、courseName、teacherName，不要再重复查询 Student 或 Course 只为拿名称。\n"
        "4. get_object_detail 需要对象主键；如果只有对象名称，先用 query_objects 找到对象，再取主键。\n"
        "5. 如果字段或路径不确定，先重新查看当前对象能力，不要猜测不存在的属性。\n\n"
        "## 输出要求\n"
        "- 严格按以下格式输出：第一行 `结论：...`，第二行 `分析：...`\n"
        "- 必须先给结论，再给简要分析过程\n"
        "- `结论` 只写最终答案，不铺垫，不解释工具调用\n"
        "- `分析` 只保留最关键的 1 到 2 个依据，简短说明即可\n"
        "- 如果结果并列，直接在 `结论` 中点名并列对象；如果没找到，直接写没找到\n\n"
        "## 规则\n"
        '- "低于/小于/不超过 N" 用 {"op":"lt","value":N} 或 {"op":"lte","value":N}\n'
        '- "高于/大于/超过 N" 用 {"op":"gt","value":N} 或 {"op":"gte","value":N}\n'
        '- "超过X"=严格大于(gt)；"不低于X"=大于等于(gte)；"达到X"=大于等于(gte)\n'
        "- 找最好/最差/最高/最低时优先使用 order_by + order_dir + limit=1\n"
        "- $or 仅用于同一对象的直接属性条件；跨不同 Link 路径的 OR 需要拆成多次 query_objects\n"
        "- 否定查询（没有 / 不存在 / 未修读）优先用 exclude_objects\n"
        "- 找不到就说没找到，不编造数据"
    )
