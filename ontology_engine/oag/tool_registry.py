"""ToolRegistry — 系统工具与对象函数的可注册分发表。

设计模式：Registry + Strategy
- 系统工具（query_objects / aggregate_objects 等）通过 register_system 注册
- 对象绑定函数（fn_*）通过 register_object_fn 注册
- 新增工具只需一行 register_*()，不改任何已有代码（开闭原则）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _ToolEntry:
    handler: Callable          # (inp: dict) -> dict
    schema_builder: Callable | None = None  # (relevant_types: list[str]) -> dict | None
    category: str = "system"   # "system" | "object_fn"


class ToolRegistry:
    """工具注册表，按 system / object_fn 两类管理 handler 和 schema builder。

    schema_builder 约定：
    - 接受 relevant_types: list[str]，返回工具的 JSON Schema dict
    - 若返回 None，表示当前上下文不需要此工具（如 query_object_set 无相关集合时）
    """

    def __init__(self) -> None:
        # 使用 list 保留注册顺序（Python 3.7+ dict 也有序，但显式更清晰）
        self._entries: dict[str, _ToolEntry] = {}

    # ---- 注册 API ----

    def register_system(
        self,
        name: str,
        handler: Callable,
        schema_builder: Callable | None = None,
    ) -> "ToolRegistry":
        """注册系统工具（query_objects / aggregate_objects 等）。"""
        self._entries[name] = _ToolEntry(handler=handler, schema_builder=schema_builder, category="system")
        return self

    def register_object_fn(
        self,
        name: str,
        handler: Callable,
        schema_builder: Callable | None = None,
    ) -> "ToolRegistry":
        """注册对象绑定函数（fn_* 系列）。"""
        self._entries[name] = _ToolEntry(handler=handler, schema_builder=schema_builder, category="object_fn")
        return self

    # ---- 执行 ----

    def execute(self, tool_name: str, inp: dict) -> dict:
        """按名称分发工具调用，统一捕获异常。"""
        entry = self._entries.get(tool_name)
        if not entry:
            return {"content": f"未知工具: {tool_name}", "summary": "unknown tool"}
        try:
            return entry.handler(inp)
        except Exception as e:  # noqa: BLE001
            return {"content": f"工具执行错误: {e}", "summary": "error", "error": str(e)}

    # ---- Schema 构建 ----

    def get_system_schemas(self, relevant_types: list[str]) -> list[dict]:
        """返回所有系统工具的 JSON Schema，按注册顺序，跳过返回 None 的 builder。"""
        schemas = []
        for entry in self._entries.values():
            if entry.category == "system" and entry.schema_builder:
                schema = entry.schema_builder(relevant_types)
                if schema:
                    schemas.append(schema)
        return schemas

    def get_object_fn_schemas(self, relevant_types: list[str]) -> list[dict]:
        """返回当前 relevant_types 适用的对象函数 JSON Schema。"""
        schemas = []
        for entry in self._entries.values():
            if entry.category == "object_fn" and entry.schema_builder:
                schema = entry.schema_builder(relevant_types)
                if schema:
                    schemas.append(schema)
        return schemas

    def get_all_schemas(self, relevant_types: list[str]) -> list[dict]:
        """系统工具 schema + 对象函数 schema，合并返回。"""
        return self.get_system_schemas(relevant_types) + self.get_object_fn_schemas(relevant_types)

    # ---- 工具名列表（供前端展示） ----

    def get_system_tool_names(self) -> list[str]:
        return [name for name, e in self._entries.items() if e.category == "system"]

    def get_object_fn_names(self, relevant_types: list[str]) -> list[str]:
        """返回在当前 relevant_types 下有效的对象函数名列表。"""
        result = []
        for name, entry in self._entries.items():
            if entry.category != "object_fn":
                continue
            if entry.schema_builder:
                if entry.schema_builder(relevant_types) is not None:
                    result.append(name)
            else:
                result.append(name)
        return result
