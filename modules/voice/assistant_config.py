"""
Vapi assistant configuration *as code*.

Everything Vapi needs to know about the agent lives here and is pushed by `vapi_setup.sync_assistant()`
(run by scripts/setup_vapi.py or automatically at startup when VAPI_SYNC_ON_STARTUP=true), so the
phone-side configuration is reproducible and versioned with the prompt and tools.

Two placements of the conversation loop (VOICE_LLM_MODE):

  vapi   (default)  Vapi runs the per-turn LLM itself (provider = OpenRouter with the user's key, model =
                    LLM_MODEL) with streaming/TTS pipelining and barge-in on its own infrastructure. Our
                    backend sits only on the *tool path*: Vapi calls /api/v1/voice/webhook (`tool-calls`)
                    for capture_fields / lookup / register / update / schedule. A few hundred ms there is
                    invisible, and a Render cold start costs one tool call instead of every turn.
  custom            Vapi streams every turn to /api/v1/voice/chat/completions where our LangChain agent
                    answers via OpenRouter. Full control, but every turn pays Vapi->Render->OpenRouter.

Either way the prompt, tools, validation and persistence are the same code.
"""

from __future__ import annotations

from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from config import get_settings
from modules.voice.context import CallContext
from modules.voice.prompt import first_message, render_system_prompt_for_vapi
from modules.voice.tools import build_tools

# Phrase the agent always says when it is done; Vapi hangs up after speaking it (belt-and-braces next to the endCall tool).
END_CALL_PHRASES = ["take care, goodbye", "take care. goodbye"]

# Spoken while a slow tool runs (register/lookup hit the database; a cold Render instance may need a moment).
TOOL_WAIT_MESSAGES = {
    "register_patient": "One moment while I save that.",
    "update_patient": "One moment while I update that.",
    "lookup_patient_by_phone": "Let me check that for you.",
}
TOOL_TIMEOUT_SECONDS = 60  # generous: covers a Render free-tier cold start


def custom_llm_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/voice/chat/completions"


def webhook_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/voice/webhook"


def _flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """pydantic -> plain JSON schema Vapi accepts: collapse `anyOf [T, null]` to T, drop titles/defaults."""
    props: dict[str, Any] = {}
    for name, prop in (schema.get("properties") or {}).items():
        prop = dict(prop)
        if "anyOf" in prop:
            options = [o for o in prop.pop("anyOf") if o.get("type") != "null"]
            prop.update(options[0] if options else {"type": "string"})
        prop.pop("title", None)
        prop.pop("default", None)
        prop.setdefault("type", "string")
        props[name] = prop
    out: dict[str, Any] = {"type": "object", "properties": props}
    if schema.get("required"):
        out["required"] = list(schema["required"])
    return out


def function_tool_specs(base_url: str) -> list[dict[str, Any]]:
    """Vapi function tools generated from the same LangChain StructuredTools the agent loop uses."""
    settings = get_settings()
    specs: list[dict[str, Any]] = []
    for tool in build_tools(CallContext(vapi_call_id="spec")):
        if tool.name == "end_call":
            continue  # Vapi-managed mode uses the built-in endCall tool instead
        oai = convert_to_openai_tool(tool)["function"]
        spec: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": oai["name"],
                "description": oai["description"],
                "parameters": _flatten_schema(oai.get("parameters") or {}),
            },
            "server": {
                "url": webhook_url(base_url),
                "secret": settings.vapi_webhook_secret,
                "timeoutSeconds": TOOL_TIMEOUT_SECONDS,
            },
            "messages": [
                {"type": "request-failed", "content": "I'm sorry, I'm having trouble with my system right now."},
            ],
        }
        if tool.name in TOOL_WAIT_MESSAGES:
            spec["messages"].insert(0, {"type": "request-start", "content": TOOL_WAIT_MESSAGES[tool.name]})
        specs.append(spec)
    return specs


def _model_config(base_url: str) -> dict[str, Any]:
    settings = get_settings()
    if settings.custom_llm_mode:
        return {
            "provider": "custom-llm",
            "url": custom_llm_url(base_url),
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "maxTokens": settings.llm_max_tokens,
            # Our server injects the real system prompt on every turn; this placeholder documents that.
            "messages": [
                {
                    "role": "system",
                    "content": "Patient registration agent. The full system prompt is injected server-side "
                    "(modules/voice/prompts/system_prompt.md).",
                }
            ],
            # Built-in tool executed by Vapi when our stream emits a tool call named `endCall`.
            "tools": [{"type": "endCall"}],
        }
    return {
        "provider": settings.vapi_model_provider,
        "model": settings.vapi_side_model,
        "temperature": settings.llm_temperature,
        "maxTokens": settings.llm_max_tokens,
        "messages": [{"role": "system", "content": render_system_prompt_for_vapi()}],
        "tools": [{"type": "endCall"}, *function_tool_specs(base_url)],
    }


def build_assistant_payload(base_url: str) -> dict[str, Any]:
    settings = get_settings()
    return {
        "name": settings.vapi_assistant_name,
        "firstMessage": first_message(),
        "firstMessageMode": "assistant-speaks-first",
        "model": _model_config(base_url),
        "voice": {"provider": settings.vapi_voice_provider, "voiceId": settings.vapi_voice_id},
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        "server": {
            "url": webhook_url(base_url),
            "secret": settings.vapi_webhook_secret,
            "timeoutSeconds": 20,
        },
        "serverMessages": ["status-update", "end-of-call-report", "transcript", "hang"],
        "endCallPhrases": END_CALL_PHRASES,
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 900,
        "backgroundDenoisingEnabled": True,
        "artifactPlan": {"recordingEnabled": True},
        "analysisPlan": {"summaryPlan": {"enabled": True}},
        "startSpeakingPlan": {"waitSeconds": 0.6},
        "stopSpeakingPlan": {"numWords": 2},
        "metadata": {"app": settings.app_name, "version": settings.version, "voice_llm_mode": settings.voice_llm_mode},
    }


def build_custom_llm_credential() -> dict[str, Any]:
    """Sent by Vapi as `Authorization: Bearer <apiKey>` to our custom-LLM endpoint (custom mode only)."""
    settings = get_settings()
    return {"provider": "custom-llm", "apiKey": settings.vapi_webhook_secret, "name": "patient-voice-agent"}
