"""
`calls` table - one row per Vapi call (phone or web test call).

Holds the live conversation state the dashboard needs (stage, draft fields captured so far),
the final transcript, the post-call analysis and the link to the patient that was created/updated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


CALL_STATUS = ("in_progress", "ended")
CALL_OUTCOME = ("registered", "updated", "partial", "failed")


class Call(SQLModel, table=True):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_started_at", "started_at"),
        Index("ix_calls_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    vapi_call_id: str = Field(max_length=64, unique=True, index=True, nullable=False)
    patient_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("patients.patient_id", ondelete="SET NULL"), nullable=True, index=True),
    )
    caller_number: str | None = Field(default=None, max_length=32, description="E.164 caller id from Vapi")
    channel: str = Field(default="phone", max_length=16, description="phone | web")

    status: str = Field(default="in_progress", max_length=16)
    outcome: str | None = Field(default=None, max_length=16)
    stage: str | None = Field(default=None, max_length=64, description="Live label, e.g. 'Collecting address'")
    matched_patient_id: uuid.UUID | None = Field(default=None, description="Existing patient detected by phone")

    draft: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False, default=dict))
    captures: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONType, nullable=False, default=list)
    )
    messages: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONType, nullable=False, default=list)
    )
    analysis: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONType, nullable=True))

    summary: str | None = Field(default=None)
    recording_url: str | None = Field(default=None, max_length=1024)
    ended_reason: str | None = Field(default=None, max_length=128)
    fields_captured: int = Field(default=0)
    corrections: int = Field(default=0)

    started_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow)
    )
    ended_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    duration_seconds: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow)
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow),
    )
