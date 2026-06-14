"""OAG 元能力：对象推断、能力描述、System Prompt 构建。

所有函数均不包含领域知识，领域专属配置通过 OntologyConfig 传入。
"""
from __future__ import annotations

from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, FUNCTIONS, INTERFACES, OBJECT_SETS


def infer_relevant_types(
    query_text: str,
    type_aliases: dict[str, str] | None = None,
    extra_type_keywords: dict[str, list[str]] | None = None,
    type_expansion_rules: dict[str, list[str]] | None = None,
) -> list[str]:
    """从查询文本推断涉及的对象类型。

    关键词来源（按优先级）：
    1. registry 中每个 ObjectType 的 api_name + display_name（平台自动派生）
    2. extra_type_keywords 中可配置的额外关键词

    type_expansion_rules: 类型关联规则，如 {"Score": ["Student", "Course"]}
    type_aliases: 中文别称 -> api_name，如 {"学生": "Student"}
    """
    q = query_text.lower()
    aliases = type_aliases or {}
    extras = extra_type_keywords or {}
    expansion = type_expansion_rules or {}
    matched: set[str] = set()

    for type_name, obj_def in OBJECT_TYPES.items():
        registry_kws = [type_name.lower(), obj_def.display_name.lower()]
        extra_kws = [kw.lower() for kw in extras.get(type_name, [])]
        if any(kw in q for kw in registry_kws + extra_kws):
            matched.add(type_name)

    # 中文别名匹配
    for alias, canonical in aliases.items():
        if alias.lower() in q and canonical in OBJECT_TYPES:
            matched.add(canonical)

    # 类型关联扩展（领域专属的隐式依赖）
    for src, targets in expansion.items():
        if src in matched:
            matched.update(targets)

    result = [t for t in OBJECT_TYPES.keys() if t in matched]
    return result if result else list(OBJECT_TYPES.keys())


def get_relevant_object_sets(object_types: list[str]) -> dict[str, list]:
    """返回当前对象类型上定义的 ObjectSet，按对象类型分组。"""
    relevant: dict[str, list] = {t: [] for t in object_types}
    for obj_set in OBJECT_SETS.values():
        if obj_set.object_type in relevant:
            relevant[obj_set.object_type].append(obj_set)
    return relevant


def _normalize_types(object_types: list[str], type_aliases: dict[str, str] | None = None) -> list[str]:
    aliases = type_aliases or {}
    result: list[str] = []
    for t in object_types:
        mapped = aliases.get(t, t)
        if mapped in OBJECT_TYPES and mapped not in result:
            result.append(mapped)
    return result


def build_object_capability_data(
    object_types: list[str],
    type_aliases: dict[str, str] | None = None,
) -> dict:
    """构建对象的属性、Link、ObjectSet、函数能力描述。完全通用，不包含领域知识。"""
    normalized = _normalize_types(object_types, type_aliases)
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

    # 系统工具列表
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


# ---- System Prompt ----
# 框架只提供通用骨架，具体的输出格式和查询规则由 OntologyConfig.system_prompt_addendum 注入。

_BASE_SYSTEM_PROMPT = """\
你是一个 Ontology 对象查询助手。系统采用"对象推断 -> 对象能力发现 -> 查询执行"的流程。

## 工作流程
1. 如果需要确认问题涉及哪些对象，先调用 infer_relevant_types。
2. 在使用任何字段前，优先依据当前上下文中的对象能力信息；如果仍不确定，再调用 describe_object_capabilities。
3. 完成对象能力确认后，再调用 query_objects、query_object_set、get_object_detail、aggregate_objects、exclude_objects 或 execute_action。
4. 对象绑定函数通过 fn_* 工具直接调用，只对当前问题涉及的对象开放。

## 核心约束
1. 系统工具中的业务字段必须使用对象属性名，不要使用数据库列名，也不要使用中文属性别名。
2. 跨 Link 查询只使用对象能力信息中列出的 path token。
3. get_object_detail 需要对象主键；如果只有对象名称，先用 query_objects 找到对象，再取主键。
4. 如果字段或路径不确定，先重新查看当前对象能力，不要猜测不存在的属性。

## 输出要求
- 严格按以下格式输出：第一行 `结论：...`，第二行 `分析：...`
- 必须先给结论，再给简要分析过程
- `结论` 只写最终答案，不铺垫，不解释工具调用
- `分析` 只保留最关键的 1 到 2 个依据，简短说明即可
- 如果结果并列，直接在 `结论` 中点名并列对象；如果没找到，直接写没找到

## 规则
- "低于/小于/不超过 N" 用 {"op":"lt","value":N} 或 {"op":"lte","value":N}
- "高于/大于/超过 N" 用 {"op":"gt","value":N} 或 {"op":"gte","value":N}
- "超过X"=严格大于(gt)；"不低于X"=大于等于(gte)；"达到X"=大于等于(gte)
- 找最好/最差/最高/最低时优先使用 order_by + order_dir + limit=1
- $or 仅用于同一对象的直接属性条件；跨不同 Link 路径的 OR 需要拆成多次 query_objects
- 否定查询（没有 / 不存在 / 未修读）优先用 exclude_objects
- 找不到就说没找到，不编造数据"""


def build_system_prompt(
    relevant_types: list[str] | None = None,
    system_prompt_addendum: str = "",
) -> str:
    """构建 System Prompt = 通用骨架 + 领域补充说明。

    system_prompt_addendum 由 OntologyConfig 提供，用于注入领域专属约束。
    不传则只有通用规则。
    """
    prompt = _BASE_SYSTEM_PROMPT
    if system_prompt_addendum:
        prompt += "\n\n" + system_prompt_addendum
    return prompt
