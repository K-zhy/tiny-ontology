"""系统工具的 handler 实现和 schema builder，以及统一注册入口。

每个系统工具包含两个函数：
  _handle_<name>(inp: dict) -> dict          — 执行逻辑（从原 execute_tool 提取）
  _schema_<name>(relevant_types: list) -> dict|None  — LLM 工具 Schema（从原 build_tool_schemas 提取）

register_all_system_tools(registry) 按原有顺序注册全部系统工具。
"""
from __future__ import annotations
import json
from typing import TYPE_CHECKING

from ontology_engine.registry import OBJECT_TYPES, ACTION_TYPES, OBJECT_SETS
from ontology_engine.query import (
    query_objects_v2, query_object_set as _engine_query_object_set,
    get_object, fill_derived_batch, aggregate_objects, exclude_objects,
)
from ontology_engine.action import execute_action as _engine_execute_action
from ontology_engine.graph import reload_graph

from .capabilities import infer_relevant_types, build_object_capability_data, get_relevant_object_sets
from .config import OntologyConfig, DEFAULT_CONFIG
from .utils import normalize_filters

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry


# ============================================================
# 工具 1: infer_relevant_types
# ============================================================

def _make_infer_relevant_types(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        query_text = inp.get("query", "")
        types = infer_relevant_types(
            query_text,
            type_aliases=config.type_aliases or None,
            extra_type_keywords=config.extra_type_keywords or None,
            type_expansion_rules=config.type_expansion_rules or None,
        )
        return {
            "content": "推断相关对象类型：" + "、".join(types),
            "summary": f"relevant types: {', '.join(types)}",
            "data": {"relevant_types": types},
        }
    return handler


def _schema_infer_relevant_types(relevant_types: list[str]) -> dict:  # noqa: ARG001
    return {
        "name": "infer_relevant_types",
        "description": "推断当前问题涉及哪些对象类型。首次分析问题时调用。返回 relevant_types 列表。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "用户原始问题"}},
            "required": ["query"],
        },
    }


# ============================================================
# 工具 2: describe_object_capabilities
# ============================================================

def _make_describe_object_capabilities(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        object_types = inp.get("object_types", []) or list(OBJECT_TYPES.keys())
        capability = build_object_capability_data(object_types, type_aliases=config.type_aliases or None)
        return {
            "content": capability["summary_text"],
            "summary": f"described {len(capability['object_types'])} object types",
            "data": capability,
        }
    return handler


def _schema_describe_object_capabilities(relevant_types: list[str]) -> dict:
    return {
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
    }


# ============================================================
# 工具 3: query_objects
# ============================================================

def _make_query_objects(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        raw_type = inp.get("object_type", "")
        obj_type = (config.type_aliases or {}).get(raw_type, raw_type)
        filters = inp.get("filters", {})
        if filters:
            filters = normalize_filters(filters, config.value_aliases or None)
        fuzzy = inp.get("fuzzy", False)
        limit = min(inp.get("limit", 20), 100)
        order_by = inp.get("order_by")
        order_dir = inp.get("order_dir", "asc")

        results = query_objects_v2(obj_type, filters=filters, fuzzy=fuzzy, limit=limit,
                                   order_by=order_by, order_dir=order_dir)
        if not results:
            return {"content": f"未找到匹配的 {obj_type} 对象", "summary": f"empty {obj_type}", "data": []}

        if config.result_enricher:
            config.result_enricher(results)
        lines = [f"找到 {len(results)} 个 {obj_type} 对象："]
        for obj in results[:15]:
            obj_name = obj.get("name", "")
            parts = [f"{k}={v}" for k, v in obj.items() if not k.startswith("_") and k != "name"]
            obj_key = obj.get("_id") or obj.get("Sno") or obj.get("Tno") or obj.get("Cno") or obj.get("id", "?")
            label = obj_name if obj_name else f"{obj_type}#{obj_key}"
            lines.append(f"  {obj_type}#{obj_key} '{label}': {', '.join(parts[:8])}")
        if len(results) > 15:
            lines.append(f"  ...及其他 {len(results) - 15} 个结果")
        return {"content": "\n".join(lines), "summary": f"found {len(results)} {obj_type}", "data": results}
    return handler


def _schema_query_objects(relevant_types: list[str]) -> dict:
    return {
        "name": "query_objects",
        "description": (
            "在类型层面查询对象。filters、order_by 中涉及的字段必须使用 describe_object_capabilities 返回的"
            "对象属性名或 Link 路径。结果自动含派生属性（avgScore、passRate）。"
            "对 Score 结果会补充 studentName、courseName 和 teacherName；对 TeachingAssignment 结果会补充 courseName 和 teacherName。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string", "enum": relevant_types, "description": "要查询的对象类型"},
                "filters": {
                    "type": "object",
                    "description": (
                        "过滤条件，字段必须使用对象业务属性名或合法跨 Link 路径。支持格式（可混用）：\n"
                        '- 等值: {"name": "张三"}\n'
                        '- 运算符: {"scoreValue": {"op": "gte", "value": 85}}\n'
                        "  可用 op: eq ne gt gte lt lte like between in not_in is_null is_not_null\n"
                        '- between: {"scoreValue": {"op": "between", "value": [80, 90]}}\n'
                        '- in: {"name": {"op": "in", "value": ["张三", "李四"]}}\n'
                        '- 跨 Link: {"student.name": "张三", "course.name": "高等数学"}\n'
                        '- OR: {"$or": [{"name": "张三"}, {"className": "理学院"}]}'
                    ),
                },
                "fuzzy": {"type": "boolean", "description": "是否模糊匹配文本属性"},
                "limit": {"type": "integer", "description": "返回上限（默认 20）"},
                "order_by": {"type": "string", "description": "排序字段，支持点号跨 Link"},
                "order_dir": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向"},
            },
            "required": ["object_type"],
        },
    }


# ============================================================
# 工具 4: query_object_set（有相关集合时才注入）
# ============================================================

def _handle_query_object_set(inp: dict) -> dict:
    set_name = inp.get("set_name", "")
    filters = inp.get("filters", {})
    if filters:
        filters = normalize_filters(filters)
    limit = min(inp.get("limit", 20), 100)

    result = _engine_query_object_set(set_name, filters=filters, limit=limit)
    if not result.get("success"):
        return {"content": f"ObjectSet 错误: {result.get('error')}", "summary": "error", "error": result.get("error")}

    results = result["data"]
    set_def = OBJECT_SETS.get(set_name)
    obj_type = set_def.object_type if set_def else "unknown"
    label = set_def.display_name if set_def else set_name
    lines = [f"{label} 包含 {len(results)} 个 {obj_type}："]
    for obj in results[:15]:
        obj_name = obj.get("name", "")
        parts = [f"{k}={v}" for k, v in obj.items() if not k.startswith("_") and k != "name"]
        pk = obj.get("_id") or obj.get("Sno") or obj.get("Tno") or obj.get("Cno") or obj.get("id", "?")
        lbl = obj_name if obj_name else f"{obj_type}#{pk}"
        lines.append(f"  {lbl}: {', '.join(parts[:8])}")
    return {"content": "\n".join(lines), "summary": f"set {set_name}: {len(results)} results", "data": results}


def _schema_query_object_set(relevant_types: list[str]) -> dict | None:
    relevant_sets = get_relevant_object_sets(relevant_types)
    names = [s.api_name for sets in relevant_sets.values() for s in sets]
    if not names:
        return None
    return {
        "name": "query_object_set",
        "description": "查询预定义的 ObjectSet（具名对象集合）。可用: " + "、".join(
            f"{OBJECT_SETS[n].api_name}({OBJECT_SETS[n].display_name})" for n in names
        ) + "。",
        "input_schema": {
            "type": "object",
            "properties": {
                "set_name": {"type": "string", "enum": names, "description": "ObjectSet 名称"},
                "filters": {"type": "object", "description": "在集合结果上额外过滤"},
                "limit": {"type": "integer"},
            },
            "required": ["set_name"],
        },
    }


# ============================================================
# 工具 5: get_object_detail
# ============================================================

def _make_get_object_detail(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        raw_type = inp.get("object_type", "")
        obj_type = (config.type_aliases or {}).get(raw_type, raw_type)
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
    return handler


def _schema_get_object_detail(relevant_types: list[str]) -> dict:
    return {
        "name": "get_object_detail",
        "description": "获取单个对象的完整详情（含派生属性）。参数是对象类型+主键，不是节点标识。",
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string", "enum": relevant_types},
                "object_id": {"type": "string", "description": "对象主键，使用业务编号字符串"},
            },
            "required": ["object_type", "object_id"],
        },
    }


# ============================================================
# 工具 6: execute_action
# ============================================================

def _make_execute_action(config: OntologyConfig):  # noqa: ARG001
    def handler(inp: dict) -> dict:
        action_name = inp.get("action_name", "")
        params = inp.get("params", {})
        result = _engine_execute_action(action_name, params)
        if result.get("success"):
            reload_graph()
        return {
            "content": json.dumps(result, ensure_ascii=False),
            "summary": f"executed {action_name}",
            "data": result,
            "error": result.get("error"),
        }
    return handler


def _schema_execute_action(relevant_types: list[str]) -> dict:  # noqa: ARG001
    return {
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
    }


# ============================================================
# 工具 7: aggregate_objects
# ============================================================

def _make_aggregate_objects(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        raw_type = inp.get("object_type", "")
        obj_type = (config.type_aliases or {}).get(raw_type, raw_type)
        aggregations = inp.get("aggregations", [])
        filters = inp.get("filters", {})
        if filters:
            filters = normalize_filters(filters, config.value_aliases or None)
        group_by = inp.get("group_by")
        having = inp.get("having")
        order_by = inp.get("order_by")
        order_dir = inp.get("order_dir", "desc")
        limit = min(inp.get("limit", 50), 200)

        result = aggregate_objects(
            obj_type, aggregations=aggregations, filters=filters,
            group_by=group_by, having=having,
            order_by=order_by, order_dir=order_dir, limit=limit,
        )
        if not result.get("success"):
            return {"content": f"聚合错误: {result.get('error')}", "summary": "agg error", "error": result.get("error")}

        data = result["data"]
        lines = [f"聚合结果（{len(data)} 行）："]
        for row in data[:20]:
            lines.append("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
        if len(data) > 20:
            lines.append(f"  ...及其他 {len(data) - 20} 行")
        return {"content": "\n".join(lines), "summary": f"agg {obj_type}: {len(data)} rows", "data": data}
    return handler


def _schema_aggregate_objects(relevant_types: list[str]) -> dict:
    return {
        "name": "aggregate_objects",
        "description": (
            "通用聚合查询，支持对任意对象类型按维度分组统计。"
            "适用于：计数、求和、平均、最大/最小值、分组统计等。"
            "支持跨 Link 点号分组（如按 teacher.name 分组统计 Score）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string", "enum": relevant_types, "description": "聚合的基础对象类型"},
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
                            "field": {"type": "string", "description": "聚合字段，支持点号跨 Link。count 可不传。"},
                            "name": {"type": "string", "description": "结果别名（可选）"},
                        },
                        "required": ["type"],
                    },
                    "description": "聚合定义列表",
                },
                "filters": {"type": "object", "description": "过滤条件（格式同 query_objects）"},
                "group_by": {
                    "type": "array", "items": {"type": "string"},
                    "description": "分组字段，支持点号（如 [\"student.name\", \"course.name\"]）",
                },
                "order_by": {"type": "string", "description": "排序字段（可以是聚合别名或 group_by 字段别名）"},
                "order_dir": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向（默认 desc）"},
                "limit": {"type": "integer", "description": "返回上限（默认 50）"},
                "having": {
                    "type": "object",
                    "description": (
                        "HAVING 过滤：对聚合结果过滤。键为聚合别名，值为运算符格式。\n"
                        '示例: {"cnt": {"op": "gte", "value": 3}, "avg_score": {"op": "gt", "value": 80}}'
                    ),
                },
            },
            "required": ["object_type", "aggregations"],
        },
    }


# ============================================================
# 工具 8: exclude_objects
# ============================================================

def _make_exclude_objects(config: OntologyConfig):
    def handler(inp: dict) -> dict:
        aliases = config.type_aliases or {}
        obj_type = aliases.get(inp.get("object_type", ""), inp.get("object_type", ""))
        exclude_link = inp.get("exclude_link", "")
        raw_target = inp.get("exclude_target_type", "")
        exclude_target_type = aliases.get(raw_target, raw_target)
        exclude_target_filters = inp.get("exclude_target_filters")
        if exclude_target_filters:
            exclude_target_filters = normalize_filters(exclude_target_filters, config.value_aliases or None)
        base_filters = inp.get("base_filters")
        if base_filters:
            base_filters = normalize_filters(base_filters, config.value_aliases or None)
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

        if config.result_enricher:
            config.result_enricher(results)
        lines = [f"排除后找到 {len(results)} 个 {obj_type} 对象："]
        for obj in results[:15]:
            obj_name = obj.get("name", "")
            parts = [f"{k}={v}" for k, v in obj.items() if not k.startswith("_") and k != "name"]
            pk = obj.get("_id") or obj.get("Sno") or obj.get("Tno") or obj.get("Cno") or obj.get("id", "?")
            lbl = obj_name if obj_name else f"{obj_type}#{pk}"
            lines.append(f"  {obj_type}#{pk} '{lbl}': {', '.join(parts[:8])}")
        return {"content": "\n".join(lines), "summary": f"exclude {obj_type}: {len(results)} results", "data": results}
    return handler


def _schema_exclude_objects(relevant_types: list[str]) -> dict:
    return {
        "name": "exclude_objects",
        "description": (
            "否定查询：找出「不存在」某种关联的对象。用于回答'哪些学生没有选过X课/X老师的课'等否定型问题。\n"
            "原理：对主对象做 NOT EXISTS 子查询，排除通过 Link 关联到满足条件的目标对象。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string", "enum": relevant_types, "description": "主查询对象类型"},
                "exclude_link": {
                    "type": "string",
                    "description": "关联路径名（Link 的 api_name 或 reverse_name），如 'scores'",
                },
                "exclude_target_type": {"type": "string", "enum": relevant_types, "description": "关联目标类型"},
                "exclude_target_filters": {
                    "type": "object",
                    "description": (
                        "对关联目标的过滤条件（格式同 query_objects 的 filters）。\n"
                        "支持跨 Link 点号。为空表示「没有任何关联对象」。\n"
                        '示例: {"course.teacher.name": "李教授"} 或 {"scoreValue": {"op": "lt", "value": 60}}'
                    ),
                },
                "base_filters": {"type": "object", "description": "对主对象的基础过滤"},
                "limit": {"type": "integer", "description": "返回上限（默认 50）"},
            },
            "required": ["object_type", "exclude_link", "exclude_target_type"],
        },
    }


# ============================================================
# 统一注册入口
# ============================================================

def register_all_system_tools(registry: "ToolRegistry", config: OntologyConfig = DEFAULT_CONFIG) -> None:
    """按原有顺序注册全部系统工具。config 传入领域专属配置，框架不包含领域知识。"""
    registry.register_system("infer_relevant_types",        _make_infer_relevant_types(config),        _schema_infer_relevant_types)
    registry.register_system("describe_object_capabilities", _make_describe_object_capabilities(config), _schema_describe_object_capabilities)
    registry.register_system("query_objects",               _make_query_objects(config),               _schema_query_objects)
    registry.register_system("query_object_set",            _handle_query_object_set,                  _schema_query_object_set)
    registry.register_system("get_object_detail",           _make_get_object_detail(config),           _schema_get_object_detail)
    registry.register_system("execute_action",              _make_execute_action(config),              _schema_execute_action)
    registry.register_system("aggregate_objects",           _make_aggregate_objects(config),           _schema_aggregate_objects)
    registry.register_system("exclude_objects",             _make_exclude_objects(config),             _schema_exclude_objects)
