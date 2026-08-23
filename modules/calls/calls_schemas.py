from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CallSummary(BaseModel):
    """Row for lists (Overview 'recent registrations', Patients 'partial' rows)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vapi_call_id: str
    patient_id: uuid.UUID | None
    matched_patient_id: uuid.UUID | None
    caller_number: str | None
    channel: str
    status: str
    outcome: str | None
    stage: str | None
    draft: dict[str, Any]
    fields_captured: int
    corrections: int
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    summary: str | None
    recording_url: str | None
    patient_name: str | None = None
    insurance_provider: str | None = None

    @field_validator("started_at", "ended_at", mode="before")
    @classmethod
    def _utc(cls, value):
        return _as_utc(value)


class CallDetail(CallSummary):
    messages: list[dict[str, Any]]
    captures: list[dict[str, Any]]
    analysis: dict[str, Any] | None
    ended_reason: str | None
