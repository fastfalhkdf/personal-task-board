"""OpenAI 兼容模型调用与 Function Calling 工具定义。"""

from __future__ import annotations

import time
from typing import AsyncIterator

from openai import AsyncOpenAI

from .config import Settings


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.require_key(),
            base_url=settings.openai_base_url,
        )

    async def stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
    ) -> AsyncIterator[tuple[str, dict]]:
        started = time.perf_counter()
        first_chunk = True
        stream = await self.client.chat.completions.create(
            model=self.settings.model_chat,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if not delta:
                continue
            if first_chunk:
                first_chunk = False
                yield "ttft", {"ms": int((time.perf_counter() - started) * 1000)}
            yield "delta", {"text": delta}
        yield "done", {"total_ms": int((time.perf_counter() - started) * 1000)}

    async def with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.3,
    ):
        started = time.perf_counter()
        response = await self.client.chat.completions.create(
            model=self.settings.model_chat,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
        )
        usage = getattr(response, "usage", None)
        return response.choices[0].message, {
            "total_ms": int((time.perf_counter() - started) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }


def tool_spec(
    name: str,
    description: str,
    properties: dict,
    required: list[str],
) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
