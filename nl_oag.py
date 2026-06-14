"""
OAG 问答入口 — Demo 项目的自然语言查询实现
============================================
此文件是 server.py 调用的 OAG 入口，属于 demo 项目的一部分。

职责：
    1. 引用 demo/config.py 中的领域配置
    2. 组装 ToolRegistry + OAGPipeline
    3. 暴露 handle_oag_query() / list_conversations() / get_conversation()
    4. 持久化对话历史
"""

from __future__ import annotations
import json
import os
import uuid
from datetime import datetime

from llm_client import chat_completion

from demo.config import DEMO_OAG_CONFIG
from ontology_engine.oag.tool_registry import ToolRegistry
from ontology_engine.oag.system_tools import register_all_system_tools
from ontology_engine.oag.object_tools import register_all_object_tools
from ontology_engine.oag.pipeline import OAGPipeline


# ---- Pipeline 工厂 ----

def _create_pipeline() -> OAGPipeline:
    """按 demo 领域配置组装 Pipeline。"""
    registry = ToolRegistry()
    register_all_system_tools(registry, config=DEMO_OAG_CONFIG)
    register_all_object_tools(registry)
    return OAGPipeline(registry, chat_completion, config=DEMO_OAG_CONFIG)


# ---- 主入口函数（由 server.py 调用）----

async def handle_oag_query(query_text: str, max_iterations: int = 20) -> dict:
    """OAG 模式问答入口：组装 Pipeline，执行查询，持久化对话。"""
    pipeline = _create_pipeline()
    result = await pipeline.run(query_text, max_iterations=max_iterations)

    # 持久化对话历史
    ctx = result.pop("_ctx", None)
    if ctx is not None:
        _save_conversation(
            query_text=query_text,
            answer=result["answer"],
            relevant_types=ctx.relevant_types,
            system_prompt=ctx.system_prompt,
            messages=ctx.messages,
            tool_schemas_names=[t["name"] for t in ctx.tool_schemas],
        )

    return result


# ---- 对话历史持久化 ----

_CONV_DIR = os.path.join(os.path.dirname(__file__), "conversation_logs")


def _save_conversation(
    query_text: str,
    answer: str,
    relevant_types: list[str],
    system_prompt: str,
    messages: list[dict],
    tool_schemas_names: list[str],
) -> None:
    """将完整对话保存为 conversation_logs/{id}.json"""
    os.makedirs(_CONV_DIR, exist_ok=True)
    conv_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    record = {
        "id": conv_id,
        "timestamp": datetime.now().isoformat(),
        "query": query_text,
        "answer": answer,
        "relevant_types": relevant_types,
        "system_prompt": system_prompt,
        "tool_schemas": tool_schemas_names,
        "messages": messages,
    }
    path = os.path.join(_CONV_DIR, f"{conv_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def list_conversations(limit: int = 50) -> list[dict]:
    """返回最近 N 条对话的摘要列表（倒序）"""
    if not os.path.isdir(_CONV_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(_CONV_DIR) if f.endswith(".json")],
        reverse=True,
    )[:limit]
    result = []
    for fname in files:
        path = os.path.join(_CONV_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "id": data.get("id", fname[:-5]),
                "timestamp": data.get("timestamp", ""),
                "query": data.get("query", ""),
                "answer": data.get("answer", ""),
                "relevant_types": data.get("relevant_types", []),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    return result


def get_conversation(conv_id: str) -> dict | None:
    """按 id 读取完整对话记录"""
    path = os.path.join(_CONV_DIR, f"{conv_id}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
