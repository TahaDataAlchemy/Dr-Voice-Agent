"""Loads and renders the documented system prompt (modules/voice/prompts/system_prompt.md)."""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from config import get_settings

PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@lru_cache
def _raw_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = _COMMENT_RE.sub("", text)  # strip reviewer annotations
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fill(text: str, *, today: str, caller: str) -> str:
    settings = get_settings()
    return (
        text.replace("{{agent_name}}", settings.agent_name)
        .replace("{{clinic_name}}", settings.clinic_name)
        .replace("{{today}}", today)
        .replace("{{caller_number}}", caller)
    )


def render_system_prompt(caller_number: str | None = None, today: date | None = None) -> str:
    """Prompt for our own LangChain loop (custom-LLM mode / terminal chat): values filled server-side."""
    today = today or date.today()
    return _fill(_raw_prompt(), today=today.strftime("%A, %B %d, %Y"), caller=caller_number or "not available")


def render_system_prompt_for_vapi() -> str:
    """Prompt stored on the Vapi assistant (Vapi-managed mode).

    Vapi fills its own template variables at call time: `{{customer.number}}` is the caller id and the
    Liquid `date` filter gives today's date. The end-call tool is Vapi's built-in `endCall`.
    """
    text = _fill(
        _raw_prompt(),
        today='{{"now" | date: "%A, %B %d, %Y"}}',
        caller="{{customer.number}}",
    )
    return text.replace("`end_call`", "`endCall`")


def first_message() -> str:
    settings = get_settings()
    return (
        f"Thanks for calling {settings.clinic_name}, this is {settings.agent_name}. "
        "I can get you registered as a new patient in just a few minutes. "
        "Could I start with your first and last name?"
    )
