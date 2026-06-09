from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


_DOTENV_LOADED = False


def load_dotenv() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        _DOTENV_LOADED = True
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)

    _DOTENV_LOADED = True


def get_llm_config() -> dict[str, str]:
    load_dotenv()

    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    if not base_url:
        legacy_base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
        if legacy_base_url.endswith("/anthropic"):
            base_url = legacy_base_url[: -len("/anthropic")]
        else:
            base_url = legacy_base_url
    if not base_url:
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or ""
    ).strip()
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or "qwen3.7-plus"
    ).strip()

    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
    }


def build_chat_completions_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url.rstrip("/") + "/chat/completions"


def build_openai_tools(tool_schemas: list[dict] | None) -> list[dict] | None:
    if not tool_schemas:
        return None

    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get(
                    "input_schema",
                    {"type": "object", "properties": {}, "required": []},
                ),
            },
        }
        for schema in tool_schemas
    ]


def convert_messages_to_openai(system: str, messages: list[dict]) -> list[dict]:
    openai_messages: list[dict] = []
    if system:
        openai_messages.append({"role": "system", "content": system})

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            openai_messages.append({"role": role, "content": json.dumps(content, ensure_ascii=False)})
            continue

        if role == "assistant":
            text_parts = []
            tool_calls = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        }
                    )

            assistant_message = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            openai_messages.append(assistant_message)
            continue

        text_parts = []
        for block in content:
            if block.get("type") == "tool_result":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    }
                )
            elif block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        if text_parts:
            openai_messages.append({"role": role, "content": "".join(text_parts)})

    return openai_messages


def normalize_openai_response(data: dict) -> dict:
    try:
        choice = data.get("choices", [])[0]
        message = choice.get("message", {})
    except (AttributeError, IndexError):
        return {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "stop_reason": "error",
        }

    content_blocks = []
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        content_blocks.append({"type": "text", "text": content})
    elif isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if text_parts:
            content_blocks.append({"type": "text", "text": "".join(text_parts)})

    for tool_call in message.get("tool_calls", []) or []:
        arguments = tool_call.get("function", {}).get("arguments", "{}")
        try:
            tool_input = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            tool_input = {}
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id", ""),
                "name": tool_call.get("function", {}).get("name", ""),
                "input": tool_input,
            }
        )

    return {
        "content": content_blocks,
        "stop_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
    }


async def chat_completion(
    system: str,
    messages: list[dict],
    tool_schemas: list[dict] | None = None,
    max_tokens: int = 2048,
) -> dict:
    config = get_llm_config()
    payload = {
        "model": config["model"],
        "messages": convert_messages_to_openai(system, messages),
        "max_tokens": max_tokens,
    }
    tools = build_openai_tools(tool_schemas)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = True

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                build_chat_completions_url(config["base_url"]),
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        data = response.json()
    except Exception as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "stop_reason": "error"}

    if response.status_code >= 400:
        return {
            "content": [{"type": "text", "text": f"API error {response.status_code}: {data}"}],
            "stop_reason": "error",
        }
    return normalize_openai_response(data)


async def chat_completion_text(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
    response = await chat_completion(
        system_prompt,
        [{"role": "user", "content": user_content}],
        tool_schemas=None,
        max_tokens=max_tokens,
    )
    text_blocks = [
        block.get("text", "")
        for block in response.get("content", [])
        if block.get("type") == "text"
    ]
    return text_blocks[0] if text_blocks else ""