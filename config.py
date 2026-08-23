"""
Application settings.

Reads name/version/description from pyproject.toml,
and adds a pydantic-settings `Settings` object for everything that comes from the
environment (.env locally, Render environment variables in production).

Nothing secret is hard-coded here: every credential is read from the environment.
"""

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent

with open(ROOT_DIR / "pyproject.toml", "rb") as f:
    _project: dict = tomllib.load(f).get("project", {})


class Settings(BaseSettings):
    """All runtime configuration. Field names map 1:1 to UPPER_CASE env vars."""

    # Skip the .env file when running tests so the suite is hermetic regardless of local secrets.
    model_config = SettingsConfigDict(
        env_file=None if os.getenv("ENVIRONMENT") == "test" else ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App metadata (from pyproject.toml) ---------------------------------
    app_name: str = _project.get("name", "patient-voice-agent")
    description: str = _project.get("description", "")
    version: str = _project.get("version", "0.0.0")

    # --- Runtime ---------------------------------------------------------------
    environment: str = Field(default="development", description="development | production | test")
    public_base_url: Optional[str] = Field(
        default=None,
        description="Public HTTPS origin of this server (tunnel URL locally, Render URL in prod). "
        "Falls back to RENDER_EXTERNAL_URL which Render injects automatically.",
    )
    render_external_url: Optional[str] = None
    log_level: str = "INFO"

    # --- Database --------------------------------------------------------------
    database_url: str = Field(
        default="sqlite:///./data/dev.db",
        description="Supabase Postgres session-pooler URI in prod; SQLite for local/offline dev and tests.",
    )
    seed_demo_data: bool = Field(default=True, description="Insert fake patients + demo login when tables are empty.")
    seed_demo_calls: bool = Field(default=True, description="Insert scripted demo call transcripts (disabled in tests).")

    # --- Auth (dashboard login) ------------------------------------------------
    secret_key: str = Field(default="dev-only-change-me", description="JWT signing key.")
    access_token_expire_minutes: int = 60 * 24
    demo_user_email: str = "demo@example.com"
    demo_user_password: str = "demo12345"
    allow_signup: bool = True

    # --- LLM (LangChain -> OpenRouter) ----------------------------------------
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = Field(default="openai/gpt-oss-120b", description="Conversation model (OpenRouter id).")
    llm_reasoning_effort: str = Field(default="low", description="Reasoning effort for gpt-oss models: low|medium|high")
    llm_temperature: float = 0.3
    llm_max_tokens: int = 350
    llm_provider_order: str = Field(
        default="Cerebras,Groq",
        description="Comma-separated OpenRouter provider preference (fast providers first). Empty = OpenRouter default.",
    )
    analysis_model: Optional[str] = Field(default=None, description="Post-call analysis / chat model; defaults to LLM_MODEL.")

    # Analysis + "ask about this call" can run on Groq (fast, generous free tier) instead of OpenRouter.
    groq_api_key: Optional[str] = None
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- Voice loop placement ------------------------------------------------------
    voice_llm_mode: str = Field(
        default="vapi",
        description="vapi   = Vapi runs the per-turn LLM (OpenRouter provider) and calls our tools via webhook "
        "(lowest latency, survives cold starts).  custom = Vapi streams every turn to our LangChain agent.",
    )
    vapi_model_provider: str = Field(default="openrouter", description="Model provider Vapi uses in 'vapi' mode.")
    vapi_model: Optional[str] = Field(default=None, description="Model id for Vapi mode; defaults to LLM_MODEL.")

    # --- Vapi (telephony / STT / TTS) -----------------------------------------
    vapi_api_key: Optional[str] = None
    vapi_api_base_url: str = "https://api.vapi.ai"
    vapi_webhook_secret: str = Field(
        default="dev-only-vapi-secret",
        description="Shared secret Vapi sends in the x-vapi-secret header / bearer token for our endpoints.",
    )
    vapi_assistant_name: str = "Patient Registration Agent"
    vapi_assistant_id: Optional[str] = Field(default=None, description="Set automatically after first sync.")
    vapi_phone_number_id: Optional[str] = Field(default=None, description="Existing Vapi phone number id to attach.")
    vapi_area_code: Optional[str] = Field(default=None, description="Desired US area code when creating a free number.")
    vapi_sync_on_startup: bool = Field(default=False, description="Push assistant config to Vapi when the app boots.")
    vapi_voice_provider: str = "vapi"
    vapi_voice_id: str = "Elliot"

    # --- Agent persona -----------------------------------------------------------
    clinic_name: str = "Maple Health Clinic"
    agent_name: str = "Sam"

    # --- Misc -----------------------------------------------------------------------
    api_key: Optional[str] = None

    # --- Derived helpers -----------------------------------------------------------
    @property
    def base_url(self) -> Optional[str]:
        url = self.public_base_url or self.render_external_url
        return url.rstrip("/") if url else None

    @property
    def analysis_llm(self) -> tuple[str, str, str]:
        """(api_key, base_url, model) for the post-call analysis + chat. Prefers Groq when GROQ_API_KEY is set."""
        model = self.analysis_model or self.llm_model
        if self.groq_api_key:
            return self.groq_api_key, self.groq_base_url, model
        return self.openrouter_api_key or "missing-key", self.openrouter_base_url, model

    @property
    def analysis_configured(self) -> bool:
        return bool(self.groq_api_key or self.openrouter_api_key)

    @property
    def vapi_side_model(self) -> str:
        return self.vapi_model or self.llm_model

    @property
    def custom_llm_mode(self) -> bool:
        return self.voice_llm_mode.lower() == "custom"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Shared settings singleton used by the core modules (logger, server).
CONFIG = get_settings()
