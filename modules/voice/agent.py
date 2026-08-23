"""
VoiceAgent - the LangChain conversation loop behind Vapi's custom-LLM endpoint.

One call to `run_turn()` == one conversation turn:

    Vapi (OpenAI-format history) -> our system prompt + history
        -> ChatOpenAI(OpenRouter, tools bound)  streams tokens
        -> tool calls executed in-process (validation / DB)  -> model called again
        -> final text streamed to Vapi, which speaks it

Yields `AgentEvent`s so the HTTP layer can emit OpenAI-compatible SSE chunks as tokens arrive.
The LLM is injectable (tests use a fake chat model).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from config import get_settings
from core.logger.logger import LOG
from core.runtime_state import STATE
from modules.voice.context import CallContext
from modules.voice.prompt import render_system_prompt
from modules.voice.tools import build_tools

MAX_TOOL_ROUNDS = 6


@dataclass
class AgentEvent:
    type: str  # "text" | "tool_call" | "tool_result" | "end_call" | "error"
    content: str = ""
    name: str | None = None
    data: dict[str, Any] | None = None


def _chunk_text(chunk: BaseMessage) -> str:
    text = getattr(chunk, "text", None)
    if callable(text):
        text = text()
    if text:
        return text
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            (block.get("text", "") if isinstance(block, dict) else str(block)) for block in content if block
        )
    return ""


def build_llm() -> ChatOpenAI:
    """OpenRouter is OpenAI-compatible, so LangChain's ChatOpenAI works with a custom base_url."""
    settings = get_settings()
    extra_body: dict[str, Any] = {}
    if settings.llm_reasoning_effort and "gpt-oss" in settings.llm_model:
        extra_body["reasoning"] = {"effort": settings.llm_reasoning_effort, "exclude": True}
    providers = [p.strip() for p in settings.llm_provider_order.split(",") if p.strip()]
    if providers:
        extra_body["provider"] = {"order": providers, "allow_fallbacks": True}
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openrouter_api_key or "missing-openrouter-key",
        base_url=settings.openrouter_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        streaming=True,
        timeout=30,
        max_retries=1,
        default_headers={
            "HTTP-Referer": settings.base_url or "http://localhost:8000",
            "X-Title": "Patient Voice Agent",
        },
        extra_body=extra_body or None,
    )


def convert_openai_messages(raw_messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """OpenAI chat dicts (from Vapi) -> LangChain messages. System messages are dropped (ours is authoritative)."""
    converted: list[BaseMessage] = []
    for msg in raw_messages or []:
        role = msg.get("role")
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content if b
            )
        if role == "system":
            continue
        if role == "user":
            converted.append(HumanMessage(content=content))
        elif role == "assistant":
            tool_calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"id": tc.get("id") or "call_0", "name": fn.get("name", ""), "args": args})
            if content or tool_calls:
                converted.append(AIMessage(content=content, tool_calls=tool_calls))
        elif role == "tool":
            converted.append(ToolMessage(content=content, tool_call_id=msg.get("tool_call_id") or "call_0"))
    return converted


class VoiceAgent:
    def __init__(self, llm: BaseChatModel | None = None):
        self._llm = llm

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            self._llm = build_llm()
        return self._llm

    async def run_turn(self, ctx: CallContext, history: list[BaseMessage]) -> AsyncIterator[AgentEvent]:
        tools = build_tools(ctx)
        tools_by_name = {t.name: t for t in tools}
        llm = self.llm.bind_tools(tools)
        messages: list[BaseMessage] = [
            SystemMessage(content=render_system_prompt(ctx.caller_number)),
            *history,
        ]
        started = time.perf_counter()
        spoke = False

        for _round in range(MAX_TOOL_ROUNDS + 1):
            gathered: AIMessageChunk | None = None
            try:
                async for chunk in llm.astream(messages):
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    text = _chunk_text(chunk)
                    if text:
                        spoke = True
                        yield AgentEvent("text", text)
                    gathered = chunk if gathered is None else gathered + chunk
            except Exception as exc:
                LOG.exception(f"llm.stream_failed: {exc}", extra={"event": "llm.failed", "call_id": ctx.vapi_call_id})
                yield AgentEvent("error", _fallback_line(spoke))
                return

            tool_calls = list(getattr(gathered, "tool_calls", None) or []) if gathered is not None else []
            messages.append(
                AIMessage(content=_chunk_text(gathered) if gathered is not None else "", tool_calls=tool_calls)
            )
            if not tool_calls:
                break

            for tc in tool_calls:
                name, args, call_id = tc.get("name"), tc.get("args") or {}, tc.get("id") or "call_0"
                yield AgentEvent("tool_call", name=name, data=args)
                tool = tools_by_name.get(name)
                if tool is None:
                    result = json.dumps({"ok": False, "error": f"unknown tool {name}"})
                else:
                    try:
                        result = await tool.ainvoke(args)
                    except Exception as exc:  # tools never raise, but be safe
                        LOG.exception(f"tool.crashed {name}: {exc}")
                        result = json.dumps({"ok": False, "error": "tool failed"})
                messages.append(ToolMessage(content=str(result), tool_call_id=call_id))
                yield AgentEvent("tool_result", content=str(result), name=name)

            if ctx.end_call_requested:
                break
        else:
            LOG.warning("agent.max_tool_rounds", extra={"event": "agent.max_tool_rounds", "call_id": ctx.vapi_call_id})

        if ctx.end_call_requested:
            if not spoke:
                yield AgentEvent("text", "Take care, goodbye.")
            yield AgentEvent("end_call")

        STATE.touch_llm(int((time.perf_counter() - started) * 1000))


def _fallback_line(already_spoke: bool) -> str:
    if already_spoke:
        return " Sorry, I lost my train of thought for a second. Could you repeat that?"
    return "I'm sorry, I'm having a little trouble on my end. Could you say that again?"
