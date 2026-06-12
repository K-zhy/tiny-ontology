"""对象绑定函数（fn_*）的 handler 工厂和注册入口。

每个 fn_* 工具对应 registry.py 中的一个 FunctionDef（func_type != "validation"）。
schema_builder 在 relevant_types 不包含该函数所属对象时返回 None（自动过滤）。
"""
from __future__ import annotations
import json
from typing import Callable

from ontology_engine.registry import FUNCTIONS, INTERFACES
from ontology_engine.functions import call_function

if TYPE_CHECKING := False:
    from .tool_registry import ToolRegistry


def _param_type_to_json_schema(param_type: str) -> str:
    return {"integer": "integer", "int": "integer", "float": "number", "number": "number"}.get(param_type, "string")


def _make_fn_handler(func_name: str) -> Callable:
    """工厂：生成 fn_<func_name> 的 handler 闭包。"""
    def handler(inp: dict) -> dict:
        result = call_function(func_name, inp)
        return {
            "content": json.dumps(result, ensure_ascii=False),
            "summary": f"fn:{func_name} → {result.get('data', result.get('error', '?'))}",
            "data": result.get("data", result),
            "error": result.get("error"),
        }
    handler.__name__ = f"_handle_fn_{func_name}"
    return handler


def _make_fn_schema_builder(func_name: str, func_def) -> Callable:
    """工厂：生成 fn_<func_name> 的 schema builder 闭包。

    当 relevant_types 不包含该函数绑定的对象时返回 None（工具不注入给 LLM）。
    """
    def schema_builder(relevant_types: list[str]) -> dict | None:
        relevant_set = set(relevant_types)
        if func_def.bound_object in relevant_set:
            type_label = func_def.bound_object
        elif func_def.bound_object in INTERFACES:
            iface = INTERFACES[func_def.bound_object]
            applicable = [t for t in iface.implementors if t in relevant_set]
            if not applicable:
                return None
            type_label = "、".join(applicable)
        else:
            return None

        props = {}
        required_params: list[str] = []
        for p in func_def.params:
            props[p.name] = {"type": _param_type_to_json_schema(p.param_type), "description": p.name}
            if p.required:
                required_params.append(p.name)

        return {
            "name": f"fn_{func_name}",
            "description": f"[{type_label}] {func_def.display_name} → 返回 {func_def.return_type}",
            "input_schema": {"type": "object", "properties": props, "required": required_params},
        }

    schema_builder.__name__ = f"_schema_fn_{func_name}"
    return schema_builder


def register_all_object_tools(registry: "ToolRegistry") -> None:
    """遍历 FUNCTIONS，为所有非 validation 函数注册 fn_* 工具。"""
    for func_name, func_def in FUNCTIONS.items():
        if func_def.func_type == "validation":
            continue
        registry.register_object_fn(
            f"fn_{func_name}",
            _make_fn_handler(func_name),
            _make_fn_schema_builder(func_name, func_def),
        )
