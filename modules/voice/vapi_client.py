"""Minimal async client for the Vapi REST API (assistants, phone numbers, live call control)."""

from __future__ import annotations

from typing import Any

import httpx

from config import get_settings
from core.logger.logger import LOG


class VapiError(RuntimeError):
    pass


class VapiClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.vapi_api_key
        self.base_url = (base_url or settings.vapi_api_base_url).rstrip("/")
        if not self.api_key:
            raise VapiError("VAPI_API_KEY is not configured")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                **kwargs,
            )
        if response.status_code >= 400:
            raise VapiError(f"Vapi {method} {path} -> {response.status_code}: {response.text[:500]}")
        if not response.content:
            return None
        return response.json()

    # ---- assistants -----------------------------------------------------------
    async def list_assistants(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/assistant", params={"limit": 100}) or []

    async def create_assistant(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/assistant", json=payload)

    async def update_assistant(self, assistant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/assistant/{assistant_id}", json=payload)

    # ---- provider credentials -------------------------------------------------
    async def list_credentials(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/credential") or []

    async def create_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/credential", json=payload)

    # ---- phone numbers --------------------------------------------------------
    async def list_phone_numbers(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/phone-number") or []

    async def create_free_number(self, assistant_id: str, area_code: str | None, name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"provider": "vapi", "assistantId": assistant_id, "name": name}
        if area_code:
            payload["numberDesiredAreaCode"] = area_code
        return await self._request("POST", "/phone-number", json=payload)

    async def update_phone_number(self, number_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/phone-number/{number_id}", json=payload)

    # ---- calls ----------------------------------------------------------------
    async def get_call(self, call_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/call/{call_id}")

    @staticmethod
    async def control(control_url: str, payload: dict[str, Any]) -> bool:
        """Live call control (e.g. {"type": "end-call"}) via the call's monitor.controlUrl."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(control_url, json=payload)
            ok = response.status_code < 400
            if not ok:
                LOG.warning(f"vapi.control_failed {response.status_code}: {response.text[:200]}")
            return ok
        except Exception as exc:  # pragma: no cover - network path
            LOG.warning(f"vapi.control_error: {exc}")
            return False
