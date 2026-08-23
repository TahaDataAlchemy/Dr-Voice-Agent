"""
CallService - lifecycle of a Vapi call as seen by our backend.

    get_or_create()  first request for a call (custom-LLM turn or webhook)
    record_capture() agent captured/validated a group of fields -> draft, stage, corrections
    sync_messages()  keep the live transcript for the dashboard
    complete()       patient registered/updated
    finalize()       end-of-call report: transcript, recording, duration, outcome
    stats()          numbers for the Overview screen
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from core.logger.logger import LOG
from core.responses import NotFoundError
from modules.calls.call_model import Call
from modules.patients import validators as v
from modules.patients.patient_model import Patient

# Groups of fields in the order the agent collects them -> drives the live "stage" label.
STAGE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Collecting name", ("first_name", "last_name")),
    ("Collecting phone number", ("phone_number",)),
    ("Collecting date of birth", ("date_of_birth",)),
    ("Collecting sex", ("sex",)),
    ("Collecting address", ("address_line_1", "city", "state", "zip_code")),
]
STALE_AFTER = timedelta(minutes=20)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def derive_stage(draft: dict[str, Any]) -> str:
    for label, fields in STAGE_GROUPS:
        if any(not draft.get(f) for f in fields):
            return label
    return "Confirming details"


class CallService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ lookup
    def get(self, call_id: uuid.UUID) -> Call:
        call = self.session.get(Call, call_id)
        if call is None:
            raise NotFoundError(f"Call {call_id} not found")
        return call

    def get_by_vapi_id(self, vapi_call_id: str) -> Call | None:
        return self.session.exec(select(Call).where(Call.vapi_call_id == vapi_call_id)).first()

    def get_or_create(
        self,
        vapi_call_id: str,
        *,
        caller_number: str | None = None,
        channel: str | None = None,
        started_at: datetime | None = None,
    ) -> Call:
        call = self.get_by_vapi_id(vapi_call_id)
        if call is None:
            call = Call(
                vapi_call_id=vapi_call_id,
                caller_number=caller_number,
                channel=channel or "phone",
                started_at=started_at or utcnow(),
                stage=STAGE_GROUPS[0][0],
            )
            self.session.add(call)
            self.session.commit()
            self.session.refresh(call)
            LOG.info(
                "call.started",
                extra={"event": "call.started", "call_id": vapi_call_id, "caller": caller_number, "channel": call.channel},
            )
        else:
            changed = False
            if caller_number and not call.caller_number:
                call.caller_number, changed = caller_number, True
            if channel and call.channel != channel:
                call.channel, changed = channel, True
            if changed:
                self._save(call)
        return call

    def list(self, *, limit: int = 50, patient_id: uuid.UUID | None = None, status: str | None = None) -> list[Call]:
        stmt = select(Call)
        if patient_id:
            stmt = stmt.where(Call.patient_id == patient_id)
        if status:
            stmt = stmt.where(Call.status == status)
        stmt = stmt.order_by(Call.started_at.desc()).limit(limit)
        return list(self.session.exec(stmt).all())

    def active_call(self) -> Call | None:
        cutoff = utcnow() - STALE_AFTER
        stmt = (
            select(Call)
            .where(Call.status == "in_progress")
            .order_by(Call.started_at.desc())
        )
        for call in self.session.exec(stmt).all():
            started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=timezone.utc)
            if started >= cutoff:
                return call
            # Stale in-progress call (we never got an end-of-call report) -> close it as partial.
            self.finalize(call, ended_reason="stale-timeout")
        return None

    # --------------------------------------------------------------- mutations
    def record_capture(
        self,
        call: Call,
        accepted: dict[str, Any],
        errors: dict[str, str],
        *,
        reset: bool = False,
        turn_index: int | None = None,
    ) -> dict[str, Any]:
        draft = {} if reset else dict(call.draft or {})
        corrections: list[dict[str, Any]] = []
        for field, value in accepted.items():
            new_value = _json_value(value)
            old_value = draft.get(field)
            if old_value not in (None, "") and old_value != new_value:
                corrections.append({"field": field, "from": old_value, "to": new_value})
            draft[field] = new_value
        event = {
            "at": utcnow().isoformat(),
            "turn_index": turn_index if turn_index is not None else len(call.messages or []),
            "fields": {k: _json_value(val) for k, val in accepted.items()},
            "errors": errors,
            "corrections": corrections,
            "reset": reset,
        }
        call.draft = draft
        call.captures = [*(call.captures or []), event]
        call.corrections = (call.corrections or 0) + len(corrections)
        call.fields_captured = len([k for k, val in draft.items() if val not in (None, "")])
        call.stage = derive_stage(draft)
        self._save(call)
        LOG.info(
            "call.capture",
            extra={
                "event": "call.capture",
                "call_id": call.vapi_call_id,
                "fields": event["fields"],
                "errors": errors,
                "corrections": corrections,
                "stage": call.stage,
            },
        )
        return event

    def set_stage(self, call: Call, stage: str) -> None:
        if call.stage != stage:
            call.stage = stage
            self._save(call)

    def mark_matched(self, call: Call, patient: Patient) -> None:
        call.matched_patient_id = patient.patient_id
        call.stage = "Existing record found"
        self._save(call)

    def sync_messages(self, call: Call, messages: list[dict[str, Any]]) -> None:
        """Replace the live transcript with the latest (Vapi sends the full history each turn)."""
        if messages and messages != (call.messages or []):
            call.messages = messages
            self._save(call)

    def append_message(self, call: Call, role: str, content: str, **extra: Any) -> None:
        if not content:
            return
        entry = {"role": role, "content": content, "at": utcnow().isoformat(), **extra}
        call.messages = [*(call.messages or []), entry]
        self._save(call)

    def complete(self, call: Call, patient: Patient, outcome: str) -> None:
        call.patient_id = patient.patient_id
        call.outcome = outcome
        call.stage = "Saved" if outcome == "registered" else "Updated"
        call.draft = {**(call.draft or {}), **{k: _json_value(getattr(patient, k)) for k in v.ALL_FIELDS}}
        call.fields_captured = len([k for k in v.ALL_FIELDS if getattr(patient, k) not in (None, "")])
        self._save(call)
        LOG.info(
            "call.completed",
            extra={
                "event": "call.completed",
                "call_id": call.vapi_call_id,
                "patient_id": str(patient.patient_id),
                "outcome": outcome,
                "final_payload": {k: _json_value(getattr(patient, k)) for k in v.ALL_FIELDS},
            },
        )

    def mark_failed(self, call: Call, reason: str) -> None:
        call.outcome = "failed"
        call.stage = "Save failed"
        call.analysis = {**(call.analysis or {}), "failure_reason": reason}
        self._save(call)

    def finalize(
        self,
        call: Call,
        *,
        ended_reason: str | None = None,
        ended_at: datetime | None = None,
        duration_seconds: float | None = None,
        recording_url: str | None = None,
        summary: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        analysis: dict[str, Any] | None = None,
    ) -> Call:
        call.status = "ended"
        call.ended_reason = ended_reason or call.ended_reason
        call.ended_at = ended_at or call.ended_at or utcnow()
        if duration_seconds is not None:
            call.duration_seconds = int(round(duration_seconds))
        elif call.duration_seconds is None and call.started_at:
            started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=timezone.utc)
            call.duration_seconds = max(0, int((call.ended_at - started).total_seconds()))
        if recording_url:
            call.recording_url = recording_url
        if summary:
            call.summary = summary
        if messages:
            call.messages = messages
        if analysis:
            call.analysis = {**(call.analysis or {}), **analysis}
        if call.outcome is None:
            call.outcome = "partial" if (call.draft or call.messages) else "failed"
            call.stage = "Caller hung up" if call.outcome == "partial" else call.stage
        self._save(call)
        LOG.info(
            "call.ended",
            extra={
                "event": "call.ended",
                "call_id": call.vapi_call_id,
                "outcome": call.outcome,
                "ended_reason": call.ended_reason,
                "duration_seconds": call.duration_seconds,
                "summary": call.summary,
            },
        )
        return call

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        patients_registered = self.session.exec(
            select(func.count()).select_from(Patient).where(Patient.deleted_at.is_(None))
        ).one()
        calls_today = self.session.exec(
            select(func.count()).select_from(Call).where(Call.started_at >= today_start)
        ).one()
        ended = self.session.exec(select(Call).where(Call.status == "ended")).all()
        finished = [c for c in ended if c.outcome in ("registered", "updated")]
        completion_rate = round(100 * len(finished) / len(ended)) if ended else None
        durations = [c.duration_seconds for c in ended if c.duration_seconds]
        avg_seconds = int(sum(durations) / len(durations)) if durations else None
        return {
            "patients_registered": patients_registered,
            "calls_today": calls_today,
            "completion_rate": completion_rate,
            "avg_call_seconds": avg_seconds,
            "calls_total": len(ended),
        }

    # ----------------------------------------------------------------- helpers
    def _save(self, call: Call) -> None:
        call.updated_at = utcnow()
        self.session.add(call)
        self.session.commit()
        self.session.refresh(call)
