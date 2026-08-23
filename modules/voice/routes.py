"""
Vapi-facing endpoints.

POST /api/v1/voice/chat/completions   custom-LLM endpoint: one conversation turn, OpenAI-compatible SSE
POST /api/v1/voice/webhook            server messages: status-update / transcript / end-of-call-report / tool-calls

Both require the shared secret (Authorization: Bearer <secret> or x-vapi-secret header).
"""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from config import get_settings
from core.database import engine
from core.logger.logger import LOG
from core.runtime_state import STATE
from modules.analysis.analysis_service import analyze_call
from modules.calls.calls_service import CallService
from modules.voice import openai_stream as oai
from modules.voice.agent import VoiceAgent, convert_openai_messages
from modules.voice.context import CallContext
from modules.voice.vapi_client import VapiClient
from modules.voice.webhook_service import call_identity, handle_message

voice_router = APIRouter(prefix="/voice", tags=["Voice (Vapi)"])
_agent = VoiceAgent()


def get_agent() -> VoiceAgent:
    return _agent


def verify_vapi_secret(request: Request) -> None:
    settings = get_settings()
    expected = settings.vapi_webhook_secret
    provided = request.headers.get("x-vapi-secret")
    auth = request.headers.get("authorization", "")
    if not provided and auth.lower().startswith("bearer "):
        provided = auth[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing Vapi secret")


def _persist_turn_start(ctx: CallContext, raw_messages: list[dict[str, Any]]) -> None:
    """Keep the live transcript in sync with what Vapi sent (runs in a worker thread)."""
    with Session(engine) as session:
        calls = CallService(session)
        call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
        transcript = [
            {"role": m["role"], "content": m.get("content") or ""}
            for m in raw_messages
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
        ]
        if len(transcript) >= len(call.messages or []):
            calls.sync_messages(call, transcript)


def _persist_turn_end(ctx: CallContext, reply: str) -> None:
    with Session(engine) as session:
        calls = CallService(session)
        call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
        last = (call.messages or [None])[-1]
        if reply.strip() and not (last and last.get("role") == "assistant" and last.get("content") == reply.strip()):
            calls.append_message(call, "assistant", reply.strip(), source="agent")


async def _end_call_fallback(control_url: str | None, spoken_text: str) -> None:
    """If Vapi does not honour the endCall tool call, hang up via the call-control URL after the goodbye."""
    if not control_url:
        return
    delay = min(12.0, 1.5 + 0.075 * len(spoken_text))
    await asyncio.sleep(delay)
    await VapiClient.control(control_url, {"type": "end-call"})


@voice_router.post("/chat/completions", summary="Vapi custom-LLM endpoint (OpenAI-compatible)")
@voice_router.post("/chat/completions/chat/completions", include_in_schema=False)
async def chat_completions(request: Request, background: BackgroundTasks) -> Any:
    verify_vapi_secret(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON") from exc

    settings = get_settings()
    call_obj = body.get("call") or {}
    vapi_call_id, caller, channel = call_identity(call_obj)
    vapi_call_id = vapi_call_id or request.headers.get("x-call-id") or f"adhoc-{abs(hash(json.dumps(body.get('messages', [])[:1], default=str))) % 10**8}"
    raw_messages = body.get("messages") or []
    history = convert_openai_messages(raw_messages)
    ctx = CallContext(vapi_call_id=vapi_call_id, caller_number=caller, channel=channel, turn_index=len(history))
    control_url = (call_obj.get("monitor") or {}).get("controlUrl")
    STATE.touch_llm()
    LOG.info(
        "llm.turn",
        extra={
            "event": "llm.turn",
            "call_id": vapi_call_id,
            "caller": caller,
            "history_len": len(history),
            "body_keys": sorted(k for k in body.keys() if k != "messages"),
            "last_user": next((m.get("content") for m in reversed(raw_messages) if m.get("role") == "user"), None),
        },
    )
    await asyncio.to_thread(_persist_turn_start, ctx, raw_messages)

    agent = get_agent()
    completion_id = oai.new_completion_id()
    model_name = settings.llm_model

    if body.get("stream", True) is False:
        text_parts: list[str] = []
        async for event in agent.run_turn(ctx, history):
            if event.type in ("text", "error"):
                text_parts.append(event.content)
        reply = "".join(text_parts)
        await asyncio.to_thread(_persist_turn_end, ctx, reply)
        if ctx.end_call_requested:
            background.add_task(_end_call_fallback, control_url, reply)
        return JSONResponse(oai.completion(completion_id, model_name, reply, end_call=ctx.end_call_requested))

    async def event_stream() -> AsyncIterator[str]:
        text_parts: list[str] = []
        first = True
        finish = "stop"
        try:
            async for event in agent.run_turn(ctx, history):
                if event.type in ("text", "error"):
                    delta: dict[str, Any] = {"content": event.content}
                    if first:
                        delta["role"] = "assistant"
                        first = False
                    text_parts.append(event.content)
                    yield oai.chunk(completion_id, model_name, delta)
                elif event.type == "end_call":
                    finish = "tool_calls"
                    yield oai.chunk(completion_id, model_name, oai.end_call_tool_delta())
        except Exception as exc:  # last line of defence: the caller must never hear silence
            LOG.exception(f"llm.turn_crashed: {exc}")
            fallback = "I'm sorry, something went wrong on my end. Could you say that again?"
            text_parts.append(fallback)
            yield oai.chunk(completion_id, model_name, {"role": "assistant", "content": fallback})
        yield oai.chunk(completion_id, model_name, {}, finish_reason=finish)
        yield oai.done()
        reply = "".join(text_parts)
        try:
            await asyncio.to_thread(_persist_turn_end, ctx, reply)
        except Exception as exc:  # pragma: no cover
            LOG.warning(f"persist_turn_end failed: {exc}")
        if ctx.end_call_requested:
            asyncio.create_task(_end_call_fallback(control_url, reply))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@voice_router.post("/webhook", summary="Vapi server-message webhook")
async def vapi_webhook(request: Request, background: BackgroundTasks) -> JSONResponse:
    verify_vapi_secret(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON") from exc
    message = body.get("message") or body
    mtype = message.get("type", "unknown")
    STATE.touch_webhook(mtype)
    try:
        result = await asyncio.to_thread(handle_message, message)
    except Exception as exc:
        LOG.exception(f"webhook.{mtype} failed: {exc}", extra={"event": "webhook.failed", "type": mtype})
        return JSONResponse({"ok": False}, status_code=200)  # Vapi retries on 5xx; our failures are not retry-able
    analyze_id = result.pop("analyze_call_id", None)
    if analyze_id:
        background.add_task(analyze_call, analyze_id)
    return JSONResponse(result or {})
