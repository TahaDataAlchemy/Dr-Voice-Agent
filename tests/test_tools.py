"""Direct tests of the agent tools (no LLM): contracts, validation, duplicate detection, failure paths."""

from __future__ import annotations

import json

import pytest

from modules.voice.context import CallContext
from modules.voice.tools import build_tools
from tests.conftest import VALID_PATIENT


@pytest.fixture
def tools():
    ctx = CallContext(vapi_call_id="tool-test-1", caller_number="+14155550139")
    return ctx, {t.name: t for t in build_tools(ctx)}


def run(tool, **kwargs):
    return json.loads(tool.invoke(kwargs))


def test_capture_fields_accepts_normalizes_and_reports_progress(tools):
    _, t = tools
    out = run(t["capture_fields"], first_name="jane", last_name="Davies", date_of_birth="March 14th, 1987")
    assert out["ok"] is True and out["errors"] == {}
    assert out["accepted"]["date_of_birth"] == "03/14/1987"
    assert "phone_number" in out["missing_required"]
    assert out["collected_so_far"] == ["date_of_birth", "first_name", "last_name"]


def test_capture_fields_field_specific_errors(tools):
    _, t = tools
    out = run(t["capture_fields"], date_of_birth="03/14/2087", phone_number="555", state="ZZ")
    assert out["ok"] is False
    assert set(out["errors"]) == {"date_of_birth", "phone_number", "state"}
    assert "future" in out["errors"]["date_of_birth"]


def test_capture_fields_reset(tools):
    _, t = tools
    run(t["capture_fields"], first_name="Jane")
    out = run(t["capture_fields"], reset=True)
    assert out["ok"] is True and out["collected_so_far"] == [] and "discarded" in out["message"]


def test_capture_detects_existing_patient(client, tools, patient_payload):
    client.post("/patients", json=patient_payload)
    _, t = tools
    out = run(t["capture_fields"], phone_number="(415) 555-0139")
    assert out["existing_patient"]["first_name"] == "Aisha"
    found = run(t["lookup_patient_by_phone"], phone_number="4155550139")
    assert found["found"] is True and found["patient"]["last_name"] == "Khan"
    assert run(t["lookup_patient_by_phone"], phone_number="2125550000")["found"] is False
    assert run(t["lookup_patient_by_phone"], phone_number="12")["ok"] is False


def test_register_requires_all_required_fields(tools):
    _, t = tools
    out = run(t["register_patient"], first_name="Jane")
    assert out["ok"] is False and "zip_code" in out["errors"] and "last_name" in out["errors"]


def test_register_then_update_and_schedule(client, tools):
    ctx, t = tools
    out = run(t["register_patient"], **VALID_PATIENT)
    assert out["ok"] is True and out["first_name"] == "Aisha"
    pid = out["patient_id"]
    assert client.get(f"/patients/{pid}").status_code == 200

    upd = run(t["update_patient"], patient_id=pid, city="Oakland", zip_code="94612")
    assert upd["ok"] is True and upd["updated_fields"] == ["city", "zip_code"]
    assert client.get(f"/patients/{pid}").json()["data"]["city"] == "Oakland"
    assert run(t["update_patient"], patient_id=pid, phone_number="12")["ok"] is False
    assert run(t["update_patient"], patient_id="not-a-uuid", city="X")["ok"] is False
    assert run(t["update_patient"], patient_id=pid)["ok"] is False

    appt = run(t["schedule_appointment"], patient_id=pid, preferred_day="next tuesday", preferred_time="2 pm")
    assert appt["ok"] is True and "Tuesday" in appt["appointment"]["spoken"] and "2:00 PM" in appt["appointment"]["spoken"]

    assert ctx.end_call_requested is False
    assert run(t["end_call"], reason="completed")["ok"] is True
    assert ctx.end_call_requested is True
    assert all(e["ok"] for e in ctx.tool_events if e["tool"] not in ("update_patient",) or e["args"].get("city") == "Oakland")


def test_register_failure_path_reports_system_error(tools, monkeypatch):
    _, t = tools
    from modules.patients import patients_service

    def boom(self, data):
        raise RuntimeError("db down")

    monkeypatch.setattr(patients_service.PatientService, "create", boom)
    out = run(t["register_patient"], **VALID_PATIENT)
    assert out["ok"] is False and "system problem" in out["error"]
