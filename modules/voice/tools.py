"""
LangChain tools exposed to the voice agent. Each tool is a thin adapter over the same
service layer the REST API uses (PatientService / CallService), so validation and persistence
behave identically whether data arrives by phone or by HTTP.

Contract: tools NEVER raise. They return a JSON string with either
    {"ok": true, ...}                      success
    {"ok": false, "errors": {field: msg}}  validation problems the agent must fix with the caller
    {"ok": false, "error": "..."}          system problem the agent must apologize for
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session

from core.database import engine
from core.logger.logger import LOG
from modules.calls.calls_service import CallService
from modules.patients import validators as v
from modules.patients.patient_model import Patient
from modules.patients.patients_schemas import PatientCreate, PatientUpdate
from modules.patients.patients_service import PatientService
from modules.voice.context import CallContext

# --------------------------------------------------------------------------- schemas


class PatientFieldsArgs(BaseModel):
    """Any subset of patient fields, exactly as the caller said them (the tool normalizes)."""

    first_name: str | None = Field(default=None, description="Caller's first name (spelled if unusual)")
    last_name: str | None = Field(default=None, description="Caller's last name (spelled if unusual)")
    date_of_birth: str | None = Field(default=None, description="Date of birth, e.g. 'March 14 1987' or '03/14/1987'")
    sex: str | None = Field(default=None, description="male | female | other | decline to answer")
    phone_number: str | None = Field(default=None, description="10-digit U.S. phone number")
    email: str | None = Field(default=None, description="Email address, e.g. 'jane dot doe at gmail dot com'")
    address_line_1: str | None = Field(default=None, description="Street address, e.g. '44 Bleecker Street'")
    address_line_2: str | None = Field(default=None, description="Apartment / suite / unit, if any")
    city: str | None = Field(default=None, description="City")
    state: str | None = Field(default=None, description="U.S. state name or 2-letter abbreviation")
    zip_code: str | None = Field(default=None, description="5-digit zip or ZIP+4")
    insurance_provider: str | None = Field(default=None, description="Insurance company name")
    insurance_member_id: str | None = Field(default=None, description="Insurance member / subscriber id")
    preferred_language: str | None = Field(default=None, description="Preferred language (default English)")
    emergency_contact_name: str | None = Field(default=None, description="Emergency contact full name")
    emergency_contact_phone: str | None = Field(default=None, description="Emergency contact 10-digit phone")


class CaptureFieldsArgs(PatientFieldsArgs):
    reset: bool = Field(default=False, description="Set true when the caller wants to start over; clears everything.")


class LookupArgs(BaseModel):
    phone_number: str = Field(description="10-digit U.S. phone number to look up")


class RegisterArgs(PatientFieldsArgs):
    """All confirmed fields. Required: first_name, last_name, date_of_birth, sex, phone_number,
    address_line_1, city, state, zip_code."""


class UpdateArgs(PatientFieldsArgs):
    patient_id: str = Field(description="patient_id of the existing record (from existing_patient / lookup)")


class ScheduleArgs(BaseModel):
    patient_id: str | None = Field(default=None, description="patient_id returned by register/update")
    preferred_day: str = Field(description="Day the caller prefers, e.g. 'next Tuesday' or 'September 3'")
    preferred_time: str = Field(description="Time of day the caller prefers, e.g. 'morning' or '2 pm'")


class EndCallArgs(BaseModel):
    reason: str | None = Field(default=None, description="Why the call is ending: completed | caller_request | failure")


# ------------------------------------------------------------------------- helpers


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


def _spoken(accepted: dict[str, Any]) -> dict[str, Any]:
    """Values in the form the agent should read back (dates as MM/DD/YYYY, formatted phones)."""
    out: dict[str, Any] = {}
    for key, value in accepted.items():
        if isinstance(value, date):
            out[key] = v.format_date_mmddyyyy(value)
        elif key in ("phone_number", "emergency_contact_phone") and value:
            out[key] = v.format_phone(value)
        else:
            out[key] = value
    return out


def _patient_brief(patient: Patient) -> dict[str, Any]:
    return {
        "patient_id": str(patient.patient_id),
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "phone_number": v.format_phone(patient.phone_number),
        "date_of_birth": v.format_date_mmddyyyy(patient.date_of_birth),
        "city": patient.city,
        "state": patient.state,
    }


def _present(args: BaseModel, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        k: val
        for k, val in args.model_dump(exclude_unset=True).items()
        if k not in exclude and val is not None and str(val).strip() != ""
    }


# --------------------------------------------------------------------------- tools


def build_tools(ctx: CallContext) -> list[BaseTool]:
    """Create the tool set bound to one call."""

    def _log_tool(name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        ctx.tool_events.append({"tool": name, "args": args, "ok": result.get("ok")})
        LOG.info(
            f"tool.{name}",
            extra={"event": "tool.call", "tool": name, "call_id": ctx.vapi_call_id, "tool_args": args, "result": result},
        )

    # -- lookup_patient_by_phone ------------------------------------------------
    def lookup_patient_by_phone(phone_number: str) -> str:
        args = {"phone_number": phone_number}
        try:
            with Session(engine) as session:
                patient = PatientService(session).find_by_phone(phone_number)
                result = {"ok": True, "found": patient is not None}
                if patient:
                    result["patient"] = _patient_brief(patient)
                    CallService(session).mark_matched(
                        CallService(session).get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number), patient
                    )
        except ValueError as exc:
            result = {"ok": False, "errors": {"phone_number": str(exc)}}
        except Exception as exc:  # pragma: no cover - DB outage path
            LOG.exception(f"tool.lookup failed: {exc}")
            result = {"ok": False, "error": "The patient database is not reachable right now."}
        _log_tool("lookup_patient_by_phone", args, result)
        return _dump(result)

    # -- capture_fields ---------------------------------------------------------
    def capture_fields(**kwargs: Any) -> str:
        args = CaptureFieldsArgs(**kwargs)
        raw = _present(args, exclude=("reset",))
        accepted, errors = v.validate_fields(raw)
        result: dict[str, Any] = {"ok": not errors, "accepted": _spoken(accepted), "errors": errors}
        try:
            with Session(engine) as session:
                calls = CallService(session)
                call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
                calls.record_capture(call, accepted, errors, reset=args.reset, turn_index=ctx.turn_index or None)
                if "phone_number" in accepted:
                    existing = PatientService(session).find_by_phone(accepted["phone_number"])
                    if existing:
                        result["existing_patient"] = _patient_brief(existing)
                        calls.mark_matched(call, existing)
                draft = call.draft or {}
                result["collected_so_far"] = sorted(k for k, val in draft.items() if val not in (None, ""))
                result["missing_required"] = [f for f in v.REQUIRED_FIELDS if not draft.get(f)]
                if args.reset:
                    result["message"] = "All previously collected information was discarded. Start again from the name."
        except Exception as exc:  # pragma: no cover - DB outage path
            LOG.exception(f"tool.capture_fields failed: {exc}")
            result = {"ok": False, "error": "I could not save that right now, but let's keep going.", "errors": errors}
        _log_tool("capture_fields", raw | ({"reset": True} if args.reset else {}), result)
        return _dump(result)

    # -- register_patient -------------------------------------------------------
    def register_patient(**kwargs: Any) -> str:
        args = RegisterArgs(**kwargs)
        raw = _present(args)
        missing = [f for f in v.REQUIRED_FIELDS if f not in raw]
        if missing:
            result = {"ok": False, "errors": {f: f"{f.replace('_', ' ')} is required" for f in missing}}
            _log_tool("register_patient", raw, result)
            return _dump(result)
        try:
            payload = PatientCreate.model_validate(raw)
        except Exception as exc:
            result = {"ok": False, "errors": _pydantic_errors(exc)}
            _log_tool("register_patient", raw, result)
            return _dump(result)
        try:
            with Session(engine) as session:
                patient = PatientService(session).create(payload)
                calls = CallService(session)
                call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
                calls.complete(call, patient, "registered")
                result = {
                    "ok": True,
                    "patient_id": str(patient.patient_id),
                    "first_name": patient.first_name,
                    "message": f"Registration saved. Tell the caller: You're all set, {patient.first_name}.",
                }
        except Exception as exc:
            LOG.exception(f"tool.register_patient failed: {exc}")
            try:
                with Session(engine) as session:
                    calls = CallService(session)
                    calls.mark_failed(calls.get_or_create(ctx.vapi_call_id), str(exc)[:200])
            except Exception:
                pass
            result = {"ok": False, "error": "The registration could not be saved because of a system problem."}
        _log_tool("register_patient", raw, result)
        return _dump(result)

    # -- update_patient ---------------------------------------------------------
    def update_patient(**kwargs: Any) -> str:
        args = UpdateArgs(**kwargs)
        raw = _present(args, exclude=("patient_id",))
        try:
            patient_id = uuid.UUID(str(args.patient_id))
        except ValueError:
            result = {"ok": False, "errors": {"patient_id": "patient_id is not a valid id"}}
            _log_tool("update_patient", raw, result)
            return _dump(result)
        if not raw:
            result = {"ok": False, "errors": {"fields": "nothing to update - ask what they'd like to change"}}
            _log_tool("update_patient", raw, result)
            return _dump(result)
        try:
            payload = PatientUpdate.model_validate(raw)
        except Exception as exc:
            result = {"ok": False, "errors": _pydantic_errors(exc)}
            _log_tool("update_patient", raw, result)
            return _dump(result)
        try:
            with Session(engine) as session:
                patient = PatientService(session).update(patient_id, payload)
                calls = CallService(session)
                call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
                calls.complete(call, patient, "updated")
                result = {
                    "ok": True,
                    "patient_id": str(patient.patient_id),
                    "first_name": patient.first_name,
                    "updated_fields": sorted(raw.keys()),
                    "message": f"Record updated. Tell the caller: You're all set, {patient.first_name}.",
                }
        except Exception as exc:
            if exc.__class__.__name__ == "NotFoundError":
                result = {"ok": False, "errors": {"patient_id": "No patient with that id"}}
            else:
                LOG.exception(f"tool.update_patient failed: {exc}")
                result = {"ok": False, "error": "The update could not be saved because of a system problem."}
        _log_tool("update_patient", raw | {"patient_id": str(args.patient_id)}, result)
        return _dump(result)

    # -- schedule_appointment (bonus, mock scheduling) --------------------------
    def schedule_appointment(**kwargs: Any) -> str:
        args = ScheduleArgs(**kwargs)
        slot = _mock_slot(args.preferred_day, args.preferred_time)
        result = {
            "ok": True,
            "appointment": slot,
            "message": f"Appointment booked for {slot['spoken']}. Read it back to the caller.",
        }
        try:
            with Session(engine) as session:
                calls = CallService(session)
                call = calls.get_or_create(ctx.vapi_call_id, caller_number=ctx.caller_number, channel=ctx.channel)
                call.analysis = {**(call.analysis or {}), "appointment": slot}
                calls._save(call)
        except Exception as exc:  # pragma: no cover
            LOG.exception(f"tool.schedule_appointment failed: {exc}")
        _log_tool("schedule_appointment", args.model_dump(), result)
        return _dump(result)

    # -- end_call ----------------------------------------------------------------
    def end_call(reason: str | None = None) -> str:
        ctx.end_call_requested = True
        result = {"ok": True, "message": "The call will end after your goodbye is spoken. Do not ask anything else."}
        _log_tool("end_call", {"reason": reason}, result)
        return _dump(result)

    return [
        StructuredTool.from_function(
            func=lookup_patient_by_phone,
            name="lookup_patient_by_phone",
            description="Check whether a patient with this phone number already exists. Use when the caller says "
            "they registered before, or to double-check a phone number.",
            args_schema=LookupArgs,
        ),
        StructuredTool.from_function(
            func=capture_fields,
            name="capture_fields",
            description="Validate and store one or more fields the caller just provided (or corrected). Call it "
            "immediately after every answer. Returns accepted values to read back, field-specific errors to fix, "
            "and existing_patient if the phone number matches a record. Pass reset=true to start over.",
            args_schema=CaptureFieldsArgs,
        ),
        StructuredTool.from_function(
            func=register_patient,
            name="register_patient",
            description="Save the new patient record. Call ONLY after the caller confirmed the read-back. Pass every "
            "collected field. Returns patient_id on success, errors to fix, or error on a system failure.",
            args_schema=RegisterArgs,
        ),
        StructuredTool.from_function(
            func=update_patient,
            name="update_patient",
            description="Update an existing patient (found via existing_patient/lookup). Pass patient_id plus only the "
            "fields that change, after the caller confirmed them.",
            args_schema=UpdateArgs,
        ),
        StructuredTool.from_function(
            func=schedule_appointment,
            name="schedule_appointment",
            description="Book the caller's first appointment after registration (demo scheduler). Returns the "
            "confirmed slot to read back.",
            args_schema=ScheduleArgs,
        ),
        StructuredTool.from_function(
            func=end_call,
            name="end_call",
            description="Hang up after you have said goodbye (registration finished, caller asked to stop, or the "
            "system cannot save). Say the goodbye in the same reply, then call this.",
            args_schema=EndCallArgs,
        ),
    ]


def _pydantic_errors(exc: Exception) -> dict[str, str]:
    errors: dict[str, str] = {}
    for err in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "fields"
        msg = err.get("msg", "invalid value")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        errors[loc] = msg
    return errors or {"fields": str(exc)[:200]}


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _mock_slot(preferred_day: str, preferred_time: str) -> dict[str, Any]:
    """Deterministic fake scheduler: next matching weekday (or +3 days), morning/afternoon slot."""
    today = date.today()
    target = today + timedelta(days=3)
    lowered = (preferred_day or "").lower()
    for idx, name in enumerate(_WEEKDAYS):
        if name in lowered:
            delta = (idx - today.weekday()) % 7 or 7
            target = today + timedelta(days=delta)
            break
    if "tomorrow" in lowered:
        target = today + timedelta(days=1)
    if target.weekday() >= 5:  # clinic closed weekends
        target += timedelta(days=7 - target.weekday())
    time_text = (preferred_time or "").lower()
    hour = 14 if any(word in time_text for word in ("afternoon", "pm", "evening", "late")) else 9
    for token in time_text.replace(":", " ").split():
        if token.isdigit() and 1 <= int(token) <= 12:
            hour = int(token) + (12 if "pm" in time_text and int(token) < 12 else 0)
            break
    start = datetime(target.year, target.month, target.day, hour, 0)
    return {
        "start": start.isoformat(),
        "provider": "Dr. Patel",
        "location": "Main clinic",
        "spoken": start.strftime("%A, %B %d at %I:%M %p").replace(" 0", " "),
        "confirmation_code": f"APT-{start.strftime('%m%d')}-{uuid.uuid4().hex[:4].upper()}",
    }
