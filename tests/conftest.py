"""Test fixtures: in-memory SQLite, TestClient with lifespan, auth helpers, Vapi secret headers."""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["VAPI_WEBHOOK_SECRET"] = "test-vapi-secret"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["VAPI_SYNC_ON_STARTUP"] = "false"
os.environ["VOICE_LLM_MODE"] = "vapi"
os.environ["VAPI_MODEL_PROVIDER"] = "openrouter"
os.environ["VAPI_MODEL"] = ""
os.environ["LLM_MODEL"] = "openai/gpt-oss-120b"
os.environ["CLINIC_NAME"] = "Maple Health Clinic"
os.environ["AGENT_NAME"] = "Sam"
os.environ["PUBLIC_BASE_URL"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["SEED_DEMO_CALLS"] = "false"
os.environ.pop("VAPI_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from core.database import engine  # noqa: E402
from core.server import app  # noqa: E402

VALID_PATIENT = {
    "first_name": "Aisha",
    "last_name": "Khan",
    "date_of_birth": "07/21/1995",
    "sex": "Female",
    "phone_number": "(415) 555-0139",
    "email": "aisha.k@example.com",
    "address_line_1": "900 Market St",
    "address_line_2": "Suite 410",
    "city": "San Francisco",
    "state": "California",
    "zip_code": "94102",
    "insurance_provider": "UnitedHealth",
    "insurance_member_id": "uh 123 456",
    "preferred_language": "english",
    "emergency_contact_name": "Bilal Khan",
    "emergency_contact_phone": "415-555-0140",
}

VAPI_HEADERS = {"x-vapi-secret": "test-vapi-secret"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_tables():
    """Reset patients/calls between tests (keep users so auth tokens stay valid)."""
    yield
    from sqlalchemy import delete

    from modules.calls.call_model import Call
    from modules.patients.patient_model import Patient

    with engine.begin() as conn:
        conn.execute(delete(Call))
        conn.execute(delete(Patient))


@pytest.fixture(scope="session")
def auth_headers(client):
    resp = client.post("/api/v1/auth/login", json={"email": "demo@example.com", "password": "demo12345"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def patient_payload():
    return dict(VALID_PATIENT)


def _ensure_schema():
    SQLModel.metadata.create_all(engine)


_ensure_schema()
