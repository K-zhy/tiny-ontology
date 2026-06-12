"""
OAG（Ontology Augmented Generation）模式 NL 查询 — 入口层
======================================================
职责：
  1. 创建默认 ToolRegistry（系统工具 + 对象函数）并组装 OAGPipeline
  2. 暴露 handle_oag_query() 给 server.py 调用
  3. 持久化对话历史（conversation_logs/）
  4. 提供 list_conversations / get_conversation 给 REST 路由

业务逻辑、工具分发、流程骨架均已迁移至 ontology_engine/oag/ 子包。
"""

from __future__ import annotations
import json
import os
import uuid
from datetime import datetime

from llm_client import chat_completion
from ontology_engine.oag.tool_registry import ToolRegistry
from ontology_engine.oag.system_tools import register_all_system_tools
from ontology_engine.oag.object_tools import register_all_object_tools
from ontology_engine.oag.pipeline import OAGPipeline

# ---- 默认 Pipeline 工厂 ----

def _create_default_pipeline() -> OAGPipeline:
    """创建并返回注册好所有工具的默认 OAGPipeline。"""
    registry = ToolRegistry()
    register_all_system_tools(registry)
    register_all_object_tools(registry)
    return OAGPipeline(registry, chat_completion)


# ---- 主入口函数（由 server.py 调用）----

async def handle_oag_query(query_text: str, max_iterations: int = 20) -> dict:
    """OAG 模式问答入口：组装 Pipeline，执行查询，持久化对话。"""
    pipeline = _create_default_pipeline()
    result = await pipeline.run(query_text, max_iterations=max_iterations)

    # 从 ctx 提取完整对话信息后持久化
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




if __name__ == "__main__":
    import asyncio
    result = asyncio.run(handle_oag_query("王教授教授哪些课程？"))
    print(result["answer"])