"""
Handlers for Vapi server messages (POST /api/v1/voice/webhook).

    status-update        call started / ended            -> calls.status, live banner on the dashboard
    transcript           final utterances in real time    -> live transcript
    end-of-call-report   transcript, recording, duration  -> finalize call, then post-call analysis
    hang                 caller silent / agent slow       -> logged
    tool-calls           only used in VOICE_LLM_MODE=vapi fallback (same tools as the LangChain agent)

All handlers are synchronous (DB access) and are called from the route in a worker thread.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from core.database import engine
from core.logger.logger import LOG
from modules.calls.call_model import Call
from modules.calls.calls_service import CallService
from modules.voice.context import CallContext
from modules.voice.tools import build_tools

CHANNEL_BY_CALL_TYPE = {"webCall": "web", "inboundPhoneCall": "phone", "outboundPhoneCall": "phone"}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def call_identity(call: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
    """(vapi_call_id, caller_number, channel) from a Vapi call object."""
    call = call or {}
    customer = call.get("customer") or {}
    number = customer.get("number") or (call.get("phoneCallProviderDetails") or {}).get("from")
    channel = CHANNEL_BY_CALL_TYPE.get(call.get("type", ""), "phone")
    return call.get("id"), number, channel


def transcript_from_artifact(artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Vapi artifact.messages -> our transcript format [{role, content, seconds_from_start}]."""
    out: list[dict[str, Any]] = []
    for msg in (artifact or {}).get("messages") or []:
        role = msg.get("role")
        if role in ("bot", "assistant"):
            role = "assistant"
        elif role != "user":
            continue
        text = (msg.get("message") or msg.get("content") or "").strip()
        if not text:
            continue
        out.append(
            {
                "role": role,
                "content": text,
                "seconds_from_start": msg.get("secondsFromStart"),
                "at": datetime.fromtimestamp(msg["time"] / 1000, tz=timezone.utc).isoformat()
                if isinstance(msg.get("time"), (int, float))
                else None,
            }
        )
    return out


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one Vapi server message. Returns the JSON body to send back."""
    mtype = message.get("type")
    call_obj = message.get("call") or {}
    vapi_call_id, caller, channel = call_identity(call_obj)
    if mtype == "status-update":
        return _handle_status_update(message, vapi_call_id, caller, channel)
    if mtype == "transcript":
        return _handle_transcript(message, vapi_call_id, caller, channel)
    if mtype == "end-of-call-report":
        return _handle_end_of_call(message, vapi_call_id, caller, channel)
    if mtype == "tool-calls":
        return _handle_tool_calls(message, vapi_call_id, caller, channel)
    if mtype == "hang":
        LOG.warning("vapi.hang", extra={"event": "vapi.hang", "call_id": vapi_call_id})
        return {}
    LOG.info(f"vapi.{mtype}", extra={"event": "vapi.message", "type": mtype, "call_id": vapi_call_id})
    return {}


def _handle_status_update(message, vapi_call_id, caller, channel) -> dict[str, Any]:
    status = message.get("status")
    LOG.info("vapi.status", extra={"event": "vapi.status", "call_id": vapi_call_id, "status": status, "caller": caller})
    if not vapi_call_id:
        return {}
    with Session(engine) as session:
        calls = CallService(session)
        if status in ("in-progress", "ringing", "queued"):
            started = _parse_ts((message.get("call") or {}).get("startedAt"))
            calls.get_or_create(vapi_call_id, caller_number=caller, channel=channel, started_at=started)
        elif status == "ended":
            call = calls.get_by_vapi_id(vapi_call_id)
            if call and call.status != "ended":
                calls.finalize(call, ended_reason=message.get("endedReason"))
    return {}


def _handle_transcript(message, vapi_call_id, caller, channel) -> dict[str, Any]:
    if message.get("transcriptType") != "final" or not vapi_call_id:
        return {}
    role = "assistant" if message.get("role") in ("assistant", "bot") else "user"
    text = (message.get("transcript") or "").strip()
    if not text:
        return {}
    with Session(engine) as session:
        calls = CallService(session)
        call = calls.get_or_create(vapi_call_id, caller_number=caller, channel=channel)
        last = (call.messages or [None])[-1]
        if not (last and last.get("role") == role and last.get("content") == text):
            calls.append_message(call, role, text, source="vapi")
    return {}


def _handle_end_of_call(message, vapi_call_id, caller, channel) -> dict[str, Any]:
    if not vapi_call_id:
        return {}
    artifact = message.get("artifact") or {}
    analysis = message.get("analysis") or {}
    recording = (
        message.get("recordingUrl")
        or artifact.get("recordingUrl")
        or (artifact.get("recording") or {}).get("stereoUrl")
        or (artifact.get("recording") or {}).get("mono", {}).get("combinedUrl")
    )
    transcript = transcript_from_artifact(artifact)
    with Session(engine) as session:
        calls = CallService(session)
        call = calls.get_or_create(vapi_call_id, caller_number=caller, channel=channel)
        calls.finalize(
            call,
            ended_reason=message.get("endedReason"),
            ended_at=_parse_ts(message.get("endedAt")) or _parse_ts((message.get("call") or {}).get("endedAt")),
            duration_seconds=message.get("durationSeconds"),
            recording_url=recording,
            summary=analysis.get("summary"),
            messages=transcript or None,
            analysis={"vapi": {k: v for k, v in analysis.items() if k != "summary"}} if analysis else None,
        )
        call_id = str(call.id)
    return {"analyze_call_id": call_id}


def _handle_tool_calls(message, vapi_call_id, caller, channel) -> dict[str, Any]:
    """Vapi-managed LLM mode: Vapi calls our tools here (same tools the LangChain loop uses)."""
    ctx = CallContext(vapi_call_id=vapi_call_id or "unknown", caller_number=caller, channel=channel)
    artifact_messages = [
        m for m in ((message.get("artifact") or {}).get("messages") or []) if m.get("role") in ("user", "bot", "assistant")
    ]
    ctx.turn_index = len(artifact_messages)
    if vapi_call_id:
        with Session(engine) as session:
            calls = CallService(session)
            call = calls.get_or_create(vapi_call_id, caller_number=caller, channel=channel)
            live = transcript_from_artifact(message.get("artifact"))
            if live and len(live) >= len(call.messages or []):
                calls.sync_messages(call, live)
    tools = {t.name: t for t in build_tools(ctx)}
    results = []
    for item in message.get("toolWithToolCallList") or message.get("toolCallList") or []:
        tool_call = item.get("toolCall") or item
        fn = tool_call.get("function") or {}
        name = fn.get("name") or item.get("name")
        args = fn.get("arguments") or tool_call.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool = tools.get(name)
        try:
            result = tool.invoke(args) if tool else json.dumps({"ok": False, "error": f"unknown tool {name}"})
        except Exception as exc:  # pragma: no cover
            LOG.exception(f"webhook tool {name} failed: {exc}")
            result = json.dumps({"ok": False, "error": "tool failed"})
        results.append({"name": name, "toolCallId": tool_call.get("id"), "result": result})
    return {"results": results}


def get_call_for_analysis(call_id: str) -> Call | None:
    with Session(engine) as session:
        return session.get(Call, call_id)
