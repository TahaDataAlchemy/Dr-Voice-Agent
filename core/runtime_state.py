"""Tiny in-process state used by the dashboard status row (last webhook / LLM turn timestamps)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RuntimeState:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_webhook_at: datetime | None = None
    last_webhook_type: str | None = None
    last_llm_turn_at: datetime | None = None
    last_llm_latency_ms: int | None = None
    vapi_assistant_id: str | None = None
    vapi_phone_number: str | None = None

    def touch_webhook(self, message_type: str) -> None:
        self.last_webhook_at = datetime.now(timezone.utc)
        self.last_webhook_type = message_type

    def touch_llm(self, latency_ms: int | None = None) -> None:
        self.last_llm_turn_at = datetime.now(timezone.utc)
        if latency_ms is not None:
            self.last_llm_latency_ms = latency_ms


STATE = RuntimeState()
