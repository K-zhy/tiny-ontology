"""OAG 查询流程的运行时状态容器。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class QueryContext:
    """每次查询创建一个实例，各 Pipeline 阶段共享同一个 ctx，通过字段传递状态。"""
    query_text: str
    relevant_types: list[str] = field(default_factory=list)
    capability: dict = field(default_factory=dict)
    system_prompt: str = ""
    tool_schemas: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    exploration_log: list[dict] = field(default_factory=list)
    final_answer: str | None = None
