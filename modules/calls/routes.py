"""Call transcripts + analysis for the dashboard (JWT protected)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from config import get_settings
from core.database import SessionDep
from core.logger.logger import LOG
from core.responses import envelope
from core.security import get_current_user
from modules.calls.call_model import Call
from modules.calls.calls_schemas import CallDetail, CallSummary
from modules.calls.calls_service import CallService
from modules.patients.patient_model import Patient

calls_router = APIRouter(prefix="/calls", tags=["Calls"], dependencies=[Depends(get_current_user)])
patient_calls_router = APIRouter(prefix="/patients", tags=["Calls"], dependencies=[Depends(get_current_user)])


def _with_patient(session, call: Call, schema=CallSummary):
    data = schema.model_validate(call)
    pid = call.patient_id or call.matched_patient_id
    if pid:
        patient = session.get(Patient, pid)
        if patient:
            data.patient_name = f"{patient.first_name} {patient.last_name}"
            data.insurance_provider = patient.insurance_provider
    if not data.patient_name:
        draft = call.draft or {}
        name = " ".join(p for p in (draft.get("first_name"), draft.get("last_name")) if p)
        data.patient_name = name or None
        data.insurance_provider = data.insurance_provider or draft.get("insurance_provider")
    return data


@calls_router.get("", summary="List calls (newest first)")
def list_calls(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status: Annotated[str | None, Query(description="in_progress | ended")] = None,
) -> JSONResponse:
    calls = CallService(session).list(limit=limit, status=status)
    return envelope([_with_patient(session, c) for c in calls])


@calls_router.get("/{call_id}", summary="Call detail: transcript, captures, analysis")
def get_call(call_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    call = CallService(session).get(call_id)
    return envelope(_with_patient(session, call, CallDetail))


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


@calls_router.post("/{call_id}/ask", summary="Ask a question about this call (LangChain over the stored transcript)")
def ask_call(call_id: uuid.UUID, payload: Annotated[AskRequest, Body()], session: SessionDep) -> JSONResponse:
    from modules.analysis.analysis_service import ask_about_call

    settings = get_settings()
    if not settings.analysis_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No analysis LLM configured (set GROQ_API_KEY or OPENROUTER_API_KEY)")
    call = CallService(session).get(call_id)
    try:
        answer = ask_about_call(call, payload.question, payload.history)
    except Exception as exc:
        LOG.exception(f"ask_call failed: {exc}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model did not answer; try again") from exc
    LOG.info("call.ask", extra={"event": "call.ask", "call_id": call.vapi_call_id, "question": payload.question})
    return envelope({"answer": answer, "model": settings.analysis_llm[2]})


@calls_router.get("/{call_id}/recording-url", summary="Short-lived signed URL for the call recording")
def recording_url(call_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    """Vapi stores recordings in a private bucket. This resolves the authenticated
    `GET /call/{id}/{type}-recording` endpoint (302 → signed URL) using our Vapi key, server-side,
    so the browser can play it without ever seeing the key."""
    import httpx

    call = CallService(session).get(call_id)
    if not call.recording_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This call has no recording")
    settings = get_settings()
    if settings.vapi_api_key:
        for kind in ("mono", "stereo"):
            try:
                r = httpx.get(
                    f"{settings.vapi_api_base_url}/call/{call.vapi_call_id}/{kind}-recording",
                    headers={"Authorization": f"Bearer {settings.vapi_api_key}"},
                    follow_redirects=False,
                    timeout=20,
                )
            except Exception as exc:  # pragma: no cover - network path
                LOG.warning(f"recording fetch failed: {exc}")
                break
            if r.status_code in (301, 302, 307) and r.headers.get("location"):
                return envelope({"url": r.headers["location"]})
            if r.status_code == 200:
                return envelope({"url": str(r.url)})
    # Fallback: maybe the stored URL is already publicly playable (non-access-controlled orgs).
    return envelope({"url": call.recording_url})


@patient_calls_router.get("/{patient_id}/calls", summary="Calls linked to a patient")
def patient_calls(patient_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    calls = CallService(session).list(patient_id=patient_id, limit=50)
    return envelope([_with_patient(session, c) for c in calls])
