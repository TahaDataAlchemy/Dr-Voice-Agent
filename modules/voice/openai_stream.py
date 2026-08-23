"""Helpers that shape our agent output like OpenAI chat completions (what Vapi's custom-LLM mode expects)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

END_CALL_TOOL_NAME = "endCall"  # Vapi built-in tool name


def new_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def chunk(completion_id: str, model: str, delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def done() -> str:
    return "data: [DONE]\n\n"


def end_call_tool_delta(index: int = 0) -> dict[str, Any]:
    return {
        "tool_calls": [
            {
                "index": index,
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": END_CALL_TOOL_NAME, "arguments": "{}"},
            }
        ]
    }


def completion(completion_id: str, model: str, text: str, end_call: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    finish = "stop"
    if end_call:
        message["tool_calls"] = end_call_tool_delta()["tool_calls"]
        for tc in message["tool_calls"]:
            tc.pop("index", None)
        finish = "tool_calls"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
