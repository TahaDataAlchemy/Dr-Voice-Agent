"""
Post-call analysis with LangChain (structured output) over OpenRouter.

After Vapi's end-of-call report arrives we run the transcript through a structured-output chain that
produces a summary, the fields the caller provided, the corrections they made and whether the
registration completed. The result is stored in calls.analysis and powers the Transcript screen
(corrections count, highlighted turns) and the Overview summary.

If no OPENROUTER_API_KEY is configured the step is skipped and the dashboard falls back to the
capture events recorded live by the tools.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlmodel import Session

from config import get_settings
from core.database import engine
from core.logger.logger import LOG
from modules.calls.call_model import Call


class Correction(BaseModel):
    field: str = Field(description="Patient field that was corrected, e.g. last_name")
    from_value: str | None = Field(default=None, description="Value before the correction")
    to_value: str | None = Field(default=None, description="Value after the correction")
    turn_index: int | None = Field(default=None, description="Index of the transcript turn where it happened")


class CallAnalysis(BaseModel):
    summary: str = Field(description="2-3 sentence summary of the call for the clinic staff")
    completed: bool = Field(description="True if the registration/update was confirmed and saved")
    outcome: str = Field(description="registered | updated | partial | failed | other")
    extracted_fields: dict[str, str] = Field(default_factory=dict, description="Patient fields heard in the call")
    corrections: list[Correction] = Field(default_factory=list)
    validation_reprompts: list[str] = Field(
        default_factory=list, description="Fields the agent had to ask again because the value was invalid"
    )
    sentiment: str = Field(description="positive | neutral | frustrated")
    language: str = Field(default="English")
    notes: str | None = Field(default=None, description="Anything staff should follow up on")


SYSTEM = (
    "You analyze transcripts of phone calls in which a clinic's voice assistant registers a new patient. "
    "Return structured JSON only. Be precise: list a correction only when the caller changed a value they had "
    "already given (including spelling fixes), and list a validation re-prompt when the assistant rejected a value "
    "(future date, bad phone number, unknown state, etc.). Do not invent fields that were not spoken."
)


def build_analysis_llm() -> ChatOpenAI:
    settings = get_settings()
    api_key, base_url, model = settings.analysis_llm
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def transcript_text(messages: list[dict[str, Any]]) -> str:
    lines = []
    for idx, msg in enumerate(messages or []):
        role = "Assistant" if msg.get("role") == "assistant" else "Caller"
        lines.append(f"[{idx}] {role}: {msg.get('content', '')}")
    return "\n".join(lines)


def analyze_transcript(messages: list[dict[str, Any]], llm: BaseChatModel | None = None) -> CallAnalysis:
    llm = llm or build_analysis_llm()
    structured = llm.with_structured_output(CallAnalysis, method="json_schema")
    try:
        result = structured.invoke([SystemMessage(content=SYSTEM), HumanMessage(content=transcript_text(messages))])
    except Exception:
        # Some OpenRouter providers do not support json_schema response_format - fall back to tool-calling mode.
        structured = llm.with_structured_output(CallAnalysis, method="function_calling")
        result = structured.invoke([SystemMessage(content=SYSTEM), HumanMessage(content=transcript_text(messages))])
    if isinstance(result, dict):
        result = CallAnalysis.model_validate(result)
    return result


def analyze_call(call_id: str | uuid.UUID, llm: BaseChatModel | None = None) -> dict[str, Any] | None:
    """Background job: analyze a finished call and persist the result. Never raises."""
    settings = get_settings()
    if llm is None and not settings.analysis_configured:
        LOG.info("analysis.skipped_no_key", extra={"event": "analysis.skipped", "call_id": str(call_id)})
        return None
    try:
        with Session(engine) as session:
            call = session.get(Call, uuid.UUID(str(call_id)))
            if call is None or not call.messages:
                return None
            analysis = analyze_transcript(call.messages, llm=llm)
            data = analysis.model_dump()
            call.analysis = {**(call.analysis or {}), "langchain": data}
            if analysis.summary:
                call.summary = analysis.summary
            if analysis.corrections and len(analysis.corrections) > (call.corrections or 0):
                call.corrections = len(analysis.corrections)
            session.add(call)
            session.commit()
            LOG.info(
                "analysis.completed",
                extra={"event": "analysis.completed", "call_id": call.vapi_call_id, "summary": analysis.summary},
            )
            return data
    except Exception as exc:
        LOG.exception(f"analysis.failed: {exc}", extra={"event": "analysis.failed", "call_id": str(call_id)})
        return None


# ------------------------------------------------------------------ "Ask about this call"

ASK_SYSTEM = (
    "You are an assistant for clinic staff reviewing a recorded patient-registration phone call. Answer the "
    "staff member's question using ONLY the call transcript, the fields the system captured, and the analysis "
    "provided. Be concise (1-4 sentences). Quote the caller's words when it helps. If the transcript does not "
    "contain the answer, say so plainly instead of guessing. Never invent patient details."
)


def _call_context(call: Call) -> str:
    parts = [f"CALL: {call.vapi_call_id} | status={call.status} | outcome={call.outcome} | stage={call.stage}"]
    if call.summary:
        parts.append(f"SUMMARY: {call.summary}")
    if call.draft:
        parts.append("CAPTURED FIELDS: " + ", ".join(f"{k}={v}" for k, v in call.draft.items() if v not in (None, "")))
    captures = call.captures or []
    events = []
    for cap in captures:
        if cap.get("errors"):
            events.append("rejected " + ", ".join(f"{k} ({v})" for k, v in cap["errors"].items()))
        for c in cap.get("corrections") or []:
            events.append(f"corrected {c['field']}: {c['from']} -> {c['to']}")
        if cap.get("reset"):
            events.append("caller started over")
    if events:
        parts.append("VALIDATION/CORRECTION EVENTS: " + "; ".join(events))
    langchain_analysis = (call.analysis or {}).get("langchain")
    if langchain_analysis:
        parts.append("ANALYSIS: " + str({k: langchain_analysis.get(k) for k in ("completed", "sentiment", "notes")}))
    parts.append("TRANSCRIPT:\n" + transcript_text(call.messages or []))
    return "\n".join(parts)


def ask_about_call(call: Call, question: str, history: list[dict[str, str]] | None = None,
                   llm: BaseChatModel | None = None) -> str:
    """Answer a staff question about one call from its stored transcript/captures (LangChain over OpenRouter)."""
    from langchain_core.messages import AIMessage

    llm = llm or build_analysis_llm()
    messages: list = [SystemMessage(content=ASK_SYSTEM), HumanMessage(content=_call_context(call))]
    messages.append(AIMessage(content="Understood. I have the call details. What would you like to know?"))
    for turn in (history or [])[-8:]:
        role, content = turn.get("role"), (turn.get("content") or "").strip()
        if not content:
            continue
        messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    messages.append(HumanMessage(content=question.strip()))
    response = llm.invoke(messages)
    text = getattr(response, "text", None)
    text = text() if callable(text) else text
    return (text or str(response.content)).strip()
