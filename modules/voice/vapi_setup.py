"""
Idempotent sync of our assistant + phone number to Vapi.

    credential : vapi mode   -> OpenRouter provider key so Vapi can run LLM_MODEL itself
                 custom mode -> custom-llm bearer secret for our /chat/completions endpoint
    assistant  : upsert by name (VAPI_ASSISTANT_NAME) with build_assistant_payload(PUBLIC_BASE_URL)
    number     : attach VAPI_PHONE_NUMBER_ID, else the first free Vapi number, else create one
"""

from __future__ import annotations

import re
from typing import Any

from config import get_settings
from core.logger.logger import LOG
from core.runtime_state import STATE
from modules.voice.assistant_config import build_assistant_payload, build_custom_llm_credential
from modules.voice.vapi_client import VapiClient, VapiError


async def sync_assistant(base_url: str | None = None, *, ensure_number: bool = True) -> dict[str, Any]:
    settings = get_settings()
    base_url = (base_url or settings.base_url or "").rstrip("/")
    if not base_url:
        raise VapiError("PUBLIC_BASE_URL (or RENDER_EXTERNAL_URL) must be set so Vapi can reach this server")
    client = VapiClient()
    payload = build_assistant_payload(base_url)

    if not settings.custom_llm_mode:
        await _ensure_provider_credential(client)

    assistant = await _upsert_assistant(client, payload)
    assistant_id = assistant["id"]
    STATE.vapi_assistant_id = assistant_id
    result: dict[str, Any] = {
        "assistant_id": assistant_id,
        "mode": settings.voice_llm_mode,
        "model": payload["model"].get("model"),
        "webhook_url": payload["server"]["url"],
    }
    if settings.custom_llm_mode:
        result["custom_llm_url"] = payload["model"]["url"]

    if ensure_number:
        number = await _ensure_number(client, assistant_id)
        if number:
            STATE.vapi_phone_number = number.get("number")
            result["phone_number"] = number.get("number")
            result["phone_number_id"] = number.get("id")
    return result


async def _ensure_provider_credential(client: VapiClient) -> None:
    """Vapi needs the OpenRouter key on file to run the model on our behalf (vapi mode)."""
    settings = get_settings()
    provider = settings.vapi_model_provider
    if provider != "openrouter" or not settings.openrouter_api_key:
        return
    try:
        existing = await client.list_credentials()
        if any(c.get("provider") == provider for c in existing):
            return
        await client.create_credential({"provider": provider, "apiKey": settings.openrouter_api_key, "name": "openrouter"})
        LOG.info("vapi.credential_created", extra={"event": "vapi.credential_created", "provider": provider})
    except VapiError as exc:
        LOG.warning(
            f"vapi.credential_sync_failed: {exc} - add your OpenRouter key under Vapi dashboard -> "
            "Provider Keys -> OpenRouter if calls fail with a model/credential error."
        )


async def _upsert_assistant(client: VapiClient, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    existing_id = settings.vapi_assistant_id
    if not existing_id:
        for assistant in await client.list_assistants():
            if assistant.get("name") == payload["name"]:
                existing_id = assistant["id"]
                break

    body = payload
    if settings.custom_llm_mode:
        body = {**payload, "credentials": [build_custom_llm_credential()]}
    try:
        return await _write_assistant(client, existing_id, body)
    except VapiError as exc:
        if not settings.custom_llm_mode or "credential" not in str(exc).lower():
            raise
        LOG.warning(
            f"vapi.inline_credential_rejected: {exc} - retrying without; configure the Custom LLM "
            "credential (bearer = VAPI_WEBHOOK_SECRET) in the Vapi dashboard."
        )
        return await _write_assistant(client, existing_id, payload)


async def _write_assistant(client: VapiClient, existing_id: str | None, body: dict[str, Any]) -> dict[str, Any]:
    if existing_id:
        assistant = await client.update_assistant(existing_id, body)
        LOG.info("vapi.assistant_updated", extra={"event": "vapi.assistant_updated", "assistant_id": existing_id})
    else:
        assistant = await client.create_assistant(body)
        LOG.info("vapi.assistant_created", extra={"event": "vapi.assistant_created", "assistant_id": assistant["id"]})
    return assistant


async def _create_free_number(client: VapiClient, assistant_id: str, area_code: str | None) -> dict[str, Any] | None:
    """Create a free Vapi number; if the requested area code is unavailable, retry with Vapi's suggestions."""
    settings = get_settings()
    tried: list[str | None] = []
    candidates: list[str | None] = [area_code, None]
    while candidates:
        code = candidates.pop(0)
        if code in tried:
            continue
        tried.append(code)
        try:
            number = await client.create_free_number(assistant_id, code, settings.vapi_assistant_name)
            LOG.info("vapi.number_created", extra={"event": "vapi.number_created", "number": number.get("number")})
            return number
        except VapiError as exc:
            hint = re.search(r"Try one of ([0-9, ]+)", str(exc))
            if hint:
                suggested = [c.strip() for c in hint.group(1).split(",") if c.strip()]
                LOG.warning(f"vapi.area_code_unavailable: {code} - trying {suggested}")
                candidates = [c for c in suggested if c not in tried] + candidates
                continue
            LOG.error(
                f"vapi.number_create_failed: {exc}. Create a free number in the Vapi dashboard "
                "(Phone Numbers -> Create -> Free Vapi number) and set VAPI_PHONE_NUMBER_ID."
            )
            return None
    return None


async def _ensure_number(client: VapiClient, assistant_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    numbers = await client.list_phone_numbers()
    chosen: dict[str, Any] | None = None
    if settings.vapi_phone_number_id:
        chosen = next((n for n in numbers if n.get("id") == settings.vapi_phone_number_id), None)
    if chosen is None:
        chosen = next((n for n in numbers if n.get("assistantId") == assistant_id), None)
    if chosen is None:
        chosen = next((n for n in numbers if n.get("provider") == "vapi"), None) or (numbers[0] if numbers else None)

    if chosen is None:
        chosen = await _create_free_number(client, assistant_id, settings.vapi_area_code)
        if chosen is None:
            return None

    if chosen.get("assistantId") != assistant_id:
        chosen = await client.update_phone_number(chosen["id"], {"assistantId": assistant_id})
        LOG.info("vapi.number_attached", extra={"event": "vapi.number_attached", "number": chosen.get("number")})
    return chosen
