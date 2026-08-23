"""Per-turn context shared between the agent loop and its tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallContext:
    vapi_call_id: str
    caller_number: str | None = None
    channel: str = "phone"
    turn_index: int = 0
    end_call_requested: bool = False
    tool_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def caller_digits(self) -> str | None:
        if not self.caller_number:
            return None
        digits = "".join(ch for ch in self.caller_number if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits if len(digits) == 10 else None
