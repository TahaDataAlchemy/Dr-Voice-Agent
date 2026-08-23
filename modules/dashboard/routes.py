"""Overview screen data: status row (public, also the keep-alive target) and stat tiles (JWT)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from config import get_settings
from core.database import SessionDep
from core.responses import envelope
from core.runtime_state import STATE
from core.security import get_current_user
from modules.calls.calls_schemas import CallSummary
from modules.calls.calls_service import CallService
from modules.calls.routes import _with_patient
from modules.patients.validators import format_phone

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _elapsed(call) -> int:
    started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))


@dashboard_router.get("/status", summary="Liveness: API, database, last webhook, active call")
def status(session: SessionDep) -> JSONResponse:
    settings = get_settings()
    db_ok, db_error = True, None
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - only when the DB is down
        db_ok, db_error = False, str(exc)[:200]

    active = None
    if db_ok:
        call = CallService(session).active_call()
        if call:
            caller = call.caller_number or ""
            digits = "".join(ch for ch in caller if ch.isdigit())
            pretty = format_phone(digits[-10:]) if len(digits) >= 10 else (caller or "web call")
            active = {
                "id": str(call.id),
                "vapi_call_id": call.vapi_call_id,
                "caller": pretty,
                "stage": call.stage,
                "elapsed_seconds": _elapsed(call),
                "channel": call.channel,
            }

    return envelope(
        {
            "api": "up",
            "version": settings.version,
            "environment": settings.environment,
            "database": {"connected": db_ok, "engine": "sqlite" if settings.is_sqlite else "postgres", "error": db_error},
            "webhook": {"last_at": STATE.last_webhook_at, "last_type": STATE.last_webhook_type},
            "llm": {
                "model": settings.analysis_llm[2],
                "provider": "groq" if settings.groq_api_key else ("openrouter" if settings.openrouter_api_key else None),
                "configured": settings.analysis_configured,
                "last_turn_at": STATE.last_llm_turn_at,
                "last_latency_ms": STATE.last_llm_latency_ms,
            },
            "vapi": {
                "configured": bool(settings.vapi_api_key),
                "assistant_id": STATE.vapi_assistant_id or settings.vapi_assistant_id,
                "phone_number": STATE.vapi_phone_number,
            },
            "active_call": active,
            "server_time": datetime.now(timezone.utc),
        }
    )


@dashboard_router.get("/stats", summary="Stat tiles + recent registrations", dependencies=[Depends(get_current_user)])
def stats(session: SessionDep) -> JSONResponse:
    service = CallService(session)
    recent = [_with_patient(session, c, CallSummary) for c in service.list(limit=8)]
    return envelope({**service.stats(), "recent": recent})
