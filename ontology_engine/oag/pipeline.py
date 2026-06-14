"""OAGPipeline — 问答流程骨架（Template Method 模式）。

流程固定为四个阶段：
  1. infer_types         — 对象推断（引擎直接执行，不过 LLM）
  2. discover_capabilities — 能力发现（引擎直接执行，不过 LLM）
  3. build_bootstrap     — 构建首条消息 + tool_schemas
  4. execute_loop        — LLM 工具调用迭代循环（async）

子类可覆盖任意阶段（如用 LLM 做对象推断、从缓存读取能力信息等）。
"""
from __future__ import annotations
import re
from typing import Callable

from .context import QueryContext
from .tool_registry import ToolRegistry
from .capabilities import infer_relevant_types, build_object_capability_data, build_system_prompt
from .config import OntologyConfig, DEFAULT_CONFIG


# ---- 答案格式化 ----

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
        return f'结论：{_truncate_text(conclusion, 90)}\n分析：{_truncate_text(analysis.strip(), 120)}'

    fragments = [f.strip(' -•*\t') for f in re.split(r'\n+|(?<=[。！？])\s*', text) if f.strip()]
    if not fragments:
        return '结论：未找到相关信息。\n分析：未获得足够数据。'

    conclusion = fragments[0]
    analysis_start = 1
    if conclusion.endswith(('：', ':')) and len(fragments) > 1:
        conclusion += fragments[1]
        analysis_start = 2

    analysis_parts = fragments[analysis_start: analysis_start + 2]
    analysis = '；'.join(p.rstrip('。') for p in analysis_parts if p) or '依据当前查询结果给出判断。'
    return f'结论：{_truncate_text(conclusion, 90)}\n分析：{_truncate_text(analysis, 120)}'


# ---- Pipeline ----

class OAGPipeline:
    """OAG 问答流程骨架。

    Args:
        registry:  已注册好系统工具 + 对象函数的 ToolRegistry。
        llm_fn:    异步 LLM 调用函数，签名 async (system, messages, tool_schemas, max_tokens) -> dict。
        max_tokens: LLM 单次输出上限。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm_fn: Callable,
        max_tokens: int = 2048,
        config: OntologyConfig = DEFAULT_CONFIG,
    ) -> None:
        self.registry = registry
        self.llm_fn = llm_fn
        self.max_tokens = max_tokens
        self.config = config

    # ---- 可覆盖的阶段方法（Template Method） ----

    def infer_types(self, ctx: QueryContext) -> None:
        """阶段 1：对象推断。默认使用关键词匹配；子类可覆盖为 LLM 推断。"""
        ctx.relevant_types = infer_relevant_types(
            ctx.query_text,
            type_aliases=self.config.type_aliases or None,
            extra_type_keywords=self.config.extra_type_keywords or None,
            type_expansion_rules=self.config.type_expansion_rules or None,
        )
        ctx.exploration_log.append({
            "step": 0,
            "tool": "infer_relevant_types",
            "input": {"query": ctx.query_text},
            "summary": f"relevant types: {', '.join(ctx.relevant_types)}",
            "result_data": {"relevant_types": ctx.relevant_types},
            "result_content": "推断相关对象类型：" + "、".join(ctx.relevant_types),
        })

    def discover_capabilities(self, ctx: QueryContext) -> None:
        """阶段 2：能力发现。默认从 registry 同步构建；子类可覆盖为缓存或远程加载。"""
        cap = build_object_capability_data(ctx.relevant_types, type_aliases=self.config.type_aliases or None)
        ctx.capability = cap
        ctx.exploration_log.append({
            "step": 0,
            "tool": "describe_object_capabilities",
            "input": {"object_types": ctx.relevant_types},
            "summary": f"described {len(cap.get('object_types', []))} object types",
            "result_data": cap,
            "result_content": cap.get("summary_text", ""),
        })

    def build_bootstrap(self, ctx: QueryContext) -> None:
        """阶段 3：构建首条消息和 tool_schemas。子类可覆盖以定制 Prompt 或工具集。"""
        ctx.system_prompt = build_system_prompt(
            ctx.relevant_types,
            system_prompt_addendum=self.config.system_prompt_addendum,
        )
        ctx.tool_schemas = self.registry.get_all_schemas(ctx.relevant_types)

        capability_text = ctx.capability.get("summary_text", "")
        bootstrap = (
            "系统已完成对象推断和对象能力发现。后续只能使用当前对象能力中列出的业务字段、Link 路径和工具。\n\n"
            + capability_text
            + f"\n\n用户问题：{ctx.query_text}"
        )
        ctx.messages = [{"role": "user", "content": bootstrap}]

    async def execute_loop(self, ctx: QueryContext, max_iterations: int = 20) -> None:
        """阶段 4：LLM 工具调用迭代循环（核心，一般不覆盖）。"""
        available_tools = [{"name": s["name"], "description": s.get("description", "")} for s in ctx.tool_schemas]

        for iteration in range(max_iterations):
            resp = await self.llm_fn(
                ctx.system_prompt, ctx.messages,
                tool_schemas=ctx.tool_schemas, max_tokens=self.max_tokens,
            )
            content_blocks = resp.get("content", [])
            tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
            text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
            reasoning = " ".join(text_parts).strip() if text_parts and tool_use_blocks else ""

            if tool_use_blocks:
                ctx.messages.append({"role": "assistant", "content": content_blocks})
                tool_results_content = []
                first = True
                for tool in tool_use_blocks:
                    tool_name = tool["name"]
                    tool_input = tool.get("input", {})
                    tool_id = tool.get("id", "")
                    tool_result = self.registry.execute(tool_name, tool_input)

                    entry: dict = {
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
                    ctx.exploration_log.append(entry)
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": tool_result["content"],
                    })

                # 第 2 次起附加催促语，引导 LLM 直接给出结论
                if iteration + 1 >= 2 and tool_results_content:
                    tool_results_content[-1]["content"] += (
                        "\n\n[数据应该足够了。请严格按两行格式回答：第一行 `结论：...`，"
                        "第二行 `分析：...`。必须先给结论，再简要分析，不要复述过程，不要再调工具。]"
                    )

                ctx.messages.append({"role": "user", "content": tool_results_content})
                continue

            # 没有工具调用 → 得到最终答案
            if text_parts:
                ctx.final_answer = "".join(text_parts)
            elif ctx.exploration_log:
                steps_desc = "; ".join(
                    f"步骤{s['step']}: {s['tool']} → {s['summary']}"
                    for s in ctx.exploration_log
                )
                ctx.final_answer = f"查询完成（{len(ctx.exploration_log)} 步）：{steps_desc}"
            else:
                ctx.final_answer = "无法生成回答"
            break

        if ctx.final_answer is None:
            ctx.final_answer = "未找到相关信息"

        ctx.final_answer = format_final_answer(ctx.final_answer)
        ctx.messages.append({"role": "assistant", "content": ctx.final_answer})

    # ---- 主入口 ----

    async def run(self, query_text: str, max_iterations: int = 20) -> dict:
        """执行完整 OAG 问答流程，返回供 server.py 使用的结果字典。"""
        ctx = QueryContext(query_text=query_text)
        self.infer_types(ctx)
        self.discover_capabilities(ctx)
        self.build_bootstrap(ctx)
        await self.execute_loop(ctx, max_iterations=max_iterations)

        available_tools = [{"name": s["name"], "description": s.get("description", "")} for s in ctx.tool_schemas]
        return {
            "success": True,
            "answer": ctx.final_answer,
            "exploration_log": ctx.exploration_log,
            "available_tools": available_tools,
            "_ctx": ctx,  # 供调用方（nl_oag.py）访问完整上下文（如持久化对话）
        }
