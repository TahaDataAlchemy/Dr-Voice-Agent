"""
Demo data: 8 fictional patients (one soft-deleted), 3 scripted demo calls + the demo dashboard login.
Runs on startup when SEED_DEMO_DATA=true and only inserts records that are missing. All data is fictional.
"""

from __future__ import annotations

from sqlmodel import Session, select

from config import get_settings
from core.logger.logger import LOG
from datetime import datetime, timedelta, timezone

from modules.auth.auth_service import AuthService
from modules.calls.calls_service import CallService
from modules.patients import validators
from modules.patients.patient_model import Patient
from modules.patients.patients_service import PatientService

SEED_PATIENTS = [
    {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "03/14/1987",
        "sex": "Female",
        "phone_number": "2125550188",
        "email": "jane.d@mail.com",
        "address_line_1": "44 Bleecker St",
        "address_line_2": "Apt 3B",
        "city": "New York",
        "state": "NY",
        "zip_code": "10012",
        "insurance_provider": "Aetna",
        "insurance_member_id": "W8842710X",
        "preferred_language": "English",
        "emergency_contact_name": "Robert Doe",
        "emergency_contact_phone": "2125550190",
    },
    {
        "first_name": "Marcus",
        "last_name": "Reyes",
        "date_of_birth": "11/02/1974",
        "sex": "Male",
        "phone_number": "7185550102",
        "email": None,
        "address_line_1": "1210 Grand Concourse",
        "address_line_2": None,
        "city": "Bronx",
        "state": "NY",
        "zip_code": "10456",
        "insurance_provider": "Cigna",
        "insurance_member_id": "CG5521908",
        "preferred_language": "Spanish",
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
    },
    {
        "first_name": "Aisha",
        "last_name": "Khan",
        "date_of_birth": "07/21/1995",
        "sex": "Female",
        "phone_number": "4155550139",
        "email": "aisha.khan@example.com",
        "address_line_1": "900 Market St",
        "address_line_2": "Suite 410",
        "city": "San Francisco",
        "state": "CA",
        "zip_code": "94102",
        "insurance_provider": "UnitedHealth",
        "insurance_member_id": "UH5589021",
        "preferred_language": "English",
        "emergency_contact_name": "Bilal Khan",
        "emergency_contact_phone": "4155550140",
    },
    {
        "first_name": "Tom",
        "last_name": "Nguyen",
        "date_of_birth": "01/09/1968",
        "sex": "Male",
        "phone_number": "6465550164",
        "email": None,
        "address_line_1": "31-15 Broadway",
        "address_line_2": None,
        "city": "Astoria",
        "state": "NY",
        "zip_code": "11106",
        "insurance_provider": None,
        "insurance_member_id": None,
        "preferred_language": "Vietnamese",
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
    },
    {
        "first_name": "Lena",
        "last_name": "Silva",
        "date_of_birth": "05/30/2001",
        "sex": "Female",
        "phone_number": "3055550121",
        "email": "lena.silva@example.com",
        "address_line_1": "1200 Brickell Ave",
        "address_line_2": "Apt 18C",
        "city": "Miami",
        "state": "FL",
        "zip_code": "33131-2847",
        "insurance_provider": "Humana",
        "insurance_member_id": "HM20481177",
        "preferred_language": "Portuguese",
        "emergency_contact_name": "Paulo Silva",
        "emergency_contact_phone": "3055550122",
        "_deleted": True,  # demonstrates soft delete in the Patients list
    },
    {
        "first_name": "Daniel",
        "last_name": "O'Brien",
        "date_of_birth": "09/12/1959",
        "sex": "Male",
        "phone_number": "3125550177",
        "email": "dobrien@example.com",
        "address_line_1": "4500 N Lincoln Ave",
        "address_line_2": None,
        "city": "Chicago",
        "state": "IL",
        "zip_code": "60625",
        "insurance_provider": "Blue Cross Blue Shield",
        "insurance_member_id": "BCB77412093",
        "preferred_language": "English",
        "emergency_contact_name": "Maureen O'Brien",
        "emergency_contact_phone": "3125550178",
    },
    {
        "first_name": "Priya",
        "last_name": "Ramaswamy",
        "date_of_birth": "12/03/1988",
        "sex": "Female",
        "phone_number": "5125550199",
        "email": "priya.r@example.com",
        "address_line_1": "2100 Barton Springs Rd",
        "address_line_2": "Unit 7",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78704",
        "insurance_provider": "Aetna",
        "insurance_member_id": "AE3391007",
        "preferred_language": "English",
        "emergency_contact_name": "Karthik Ramaswamy",
        "emergency_contact_phone": "5125550200",
    },
    {
        "first_name": "Carlos",
        "last_name": "Mendoza",
        "date_of_birth": "04/17/1979",
        "sex": "Male",
        "phone_number": "6025550158",
        "email": None,
        "address_line_1": "7800 W Thomas Rd",
        "address_line_2": None,
        "city": "Phoenix",
        "state": "AZ",
        "zip_code": "85033",
        "insurance_provider": "Kaiser Permanente",
        "insurance_member_id": "KP11840362",
        "preferred_language": "Spanish",
        "emergency_contact_name": "Lucia Mendoza",
        "emergency_contact_phone": "6025550159",
    },
]


def seed_if_empty(session: Session) -> None:
    """Idempotent: inserts any seed patient not present yet (matched by phone + last name)."""
    settings = get_settings()
    if not settings.seed_demo_data:
        return
    AuthService(session).ensure_demo_user()
    service = PatientService(session)
    created = 0
    for record in SEED_PATIENTS:
        record = dict(record)
        deleted = record.pop("_deleted", False)
        exists = session.exec(
            select(Patient).where(Patient.phone_number == record["phone_number"], Patient.last_name == record["last_name"])
        ).first()
        if exists is not None:
            continue
        patient = service.create(record)
        if deleted:
            service.soft_delete(patient.patient_id)
        created += 1
    if created:
        LOG.info("seed.patients_created", extra={"event": "seed.patients_created", "count": created})
    if settings.seed_demo_calls:
        seed_demo_calls(session)


# --------------------------------------------------------------------------- demo calls
# Scripted conversations that exercise the Transcript screen: a rejected future DOB, a spelling
# correction, a duplicate-phone "update instead" flow and a caller who hung up. Steps:
#   ("assistant"|"user", text)  -> transcript turn
#   ("capture", {...})          -> capture_fields result (validated through the real validators)
A, U = "assistant", "user"
SEED_CALLS = [
    {
        "vapi_call_id": "demo-4c81a2f0-jane-doe",
        "caller_number": "+12125550188",
        "link": {"phone_number": "2125550188", "last_name": "Doe"},
        "outcome": "registered",
        "minutes_ago": 95,
        "duration_seconds": 258,
        "ended_reason": "assistant-ended-call",
        "summary": "Jane Doe registered as a new patient. The caller corrected the spelling of her last name "
        "(Davies -> Doe) and a mistyped birth year (2087 -> 1987); insurance and emergency contact were provided.",
        "analysis": {"completed": True, "outcome": "registered", "sentiment": "positive", "language": "English",
                     "corrections": [{"field": "last_name", "from_value": "Davies", "to_value": "Doe", "turn_index": 7}],
                     "validation_reprompts": ["date_of_birth"], "notes": None},
        "script": [
            (A, "Thanks for calling Maple Health Clinic, this is Sam. I can get you registered as a new patient in just a few minutes. Could I start with your first and last name?"),
            (U, "Jane Davies."),
            ("capture", {"first_name": "Jane", "last_name": "Davies"}),
            (A, "Nice to meet you, Jane. Is the number you're calling from the best one to reach you?"),
            (U, "Yes, that's my cell."),
            ("capture", {"phone_number": "212 555 0188"}),
            (A, "Great, two one two, five five five, zero one eight eight. And your date of birth?"),
            (U, "March 14th, 2087."),
            ("capture", {"date_of_birth": "March 14th, 2087"}),
            (A, "That one's in the future - did you mean 1987?"),
            (U, "Yes, 1987. Oh, and it's D-O-E, not Davies."),
            ("capture", {"date_of_birth": "03/14/1987", "last_name": "Doe"}),
            (A, "Fixed - Jane Doe, born March 14th, 1987. Is that female, male, other, or would you rather not say?"),
            (U, "Female."),
            ("capture", {"sex": "female"}),
            (A, "Thanks. What's your street address, including apartment, city, state and zip?"),
            (U, "44 Bleecker Street, apartment 3B, New York, New York, 10012."),
            ("capture", {"address_line_1": "44 Bleecker St", "address_line_2": "Apt 3B", "city": "New York", "state": "New York", "zip_code": "10012"}),
            (A, "Got it. Do you have an email address you'd like on file? It's fine to skip."),
            (U, "jane dot d at mail dot com."),
            ("capture", {"email": "jane dot d at mail dot com"}),
            (A, "Perfect. I can also collect your insurance information, emergency contact, and preferred language. Would you like to provide any of those?"),
            (U, "Sure. Insurance is Aetna, member ID W 8 8 4 2 7 1 0 X. Emergency contact is Robert Doe, two one two, five five five, zero one nine zero."),
            ("capture", {"insurance_provider": "Aetna", "insurance_member_id": "W8842710X", "emergency_contact_name": "Robert Doe", "emergency_contact_phone": "212 555 0190"}),
            (A, "Let me read that back: Jane Doe, born March 14th, 1987, phone two one two, five five five, zero one eight eight, email jane dot d at mail dot com, 44 Bleecker Street apartment 3B, New York, New York 10012, Aetna member W8842710X, emergency contact Robert Doe. Is everything correct?"),
            (U, "Yes, that's all correct."),
            (A, "One moment while I save that. You're all set, Jane. We look forward to seeing you. Take care, goodbye."),
        ],
    },
    {
        "vapi_call_id": "demo-9e21b7c4-marcus-reyes",
        "caller_number": "+17185550102",
        "link": {"phone_number": "7185550102", "last_name": "Reyes"},
        "outcome": "updated",
        "minutes_ago": 50,
        "duration_seconds": 97,
        "ended_reason": "assistant-ended-call",
        "summary": "Returning patient Marcus Reyes was recognized by his phone number and chose to update his record "
        "instead of registering again; his address was updated.",
        "analysis": {"completed": True, "outcome": "updated", "sentiment": "neutral", "language": "English",
                     "corrections": [], "validation_reprompts": [], "notes": "Caller mentioned he may switch insurance next month."},
        "script": [
            (A, "Thanks for calling Maple Health Clinic, this is Sam. I can get you registered as a new patient in just a few minutes. Could I start with your first and last name?"),
            (U, "Marcus Reyes. I think I might already be in your system."),
            ("capture", {"first_name": "Marcus", "last_name": "Reyes"}),
            (A, "Let me check that for you. Is the number you're calling from the best one to reach you?"),
            (U, "Yes."),
            ("capture", {"phone_number": "718 555 0102"}),
            (A, "It looks like we already have a record for Marcus Reyes. Would you like to update your information instead?"),
            (U, "Yes please, I moved. New address is 1210 Grand Concourse, Bronx, New York, 10456."),
            ("capture", {"address_line_1": "1210 Grand Concourse", "city": "Bronx", "state": "NY", "zip_code": "10456"}),
            (A, "So that's 1210 Grand Concourse, Bronx, New York 10456. Shall I update your record with that?"),
            (U, "Yes, that's right."),
            (A, "One moment while I update that. Done - you're all set, Marcus. Take care, goodbye."),
        ],
    },
    {
        "vapi_call_id": "demo-7f2ad913-maria-lopez",
        "caller_number": "+13055550187",
        "link": None,
        "outcome": "partial",
        "minutes_ago": 22,
        "duration_seconds": 71,
        "ended_reason": "customer-ended-call",
        "summary": "Caller Maria Lopez gave her name, phone number and date of birth, then hung up before the "
        "address could be collected. No patient record was created.",
        "analysis": {"completed": False, "outcome": "partial", "sentiment": "neutral", "language": "English",
                     "corrections": [], "validation_reprompts": [], "notes": "Follow up: call back to finish registration."},
        "script": [
            (A, "Thanks for calling Maple Health Clinic, this is Sam. I can get you registered as a new patient in just a few minutes. Could I start with your first and last name?"),
            (U, "Maria Lopez."),
            ("capture", {"first_name": "Maria", "last_name": "Lopez"}),
            (A, "Thanks, Maria. Is the number you're calling from the best one to reach you?"),
            (U, "Yes, three oh five, five five five, zero one eight seven."),
            ("capture", {"phone_number": "305 555 0187"}),
            (A, "Got it. And your date of birth?"),
            (U, "June 2nd, 1990. Sorry, I have to go, I'll call back."),
            ("capture", {"date_of_birth": "06/02/1990"}),
        ],
    },
]


def seed_demo_calls(session: Session) -> int:
    """Insert the scripted demo calls once (matched by vapi_call_id). Returns how many were created."""
    calls = CallService(session)
    patients = PatientService(session)
    created = 0
    for spec in SEED_CALLS:
        if calls.get_by_vapi_id(spec["vapi_call_id"]) is not None:
            continue
        started = datetime.now(timezone.utc) - timedelta(minutes=spec["minutes_ago"])
        call = calls.get_or_create(spec["vapi_call_id"], caller_number=spec["caller_number"], started_at=started)
        messages: list[dict] = []
        for kind, payload in spec["script"]:
            if kind == "capture":
                accepted, errors = validators.validate_fields(payload)
                calls.record_capture(call, accepted, errors, turn_index=len(messages))
            else:
                messages.append({"role": kind, "content": payload})
                calls.sync_messages(call, list(messages))
        if spec["link"]:
            patient = next(
                (
                    p
                    for p in patients.list(phone_number=spec["link"]["phone_number"], include_deleted=True)
                    if p.last_name == spec["link"]["last_name"]
                ),
                None,
            )
            if patient is not None:
                calls.complete(call, patient, spec["outcome"])
        calls.finalize(
            call,
            ended_reason=spec["ended_reason"],
            ended_at=started + timedelta(seconds=spec["duration_seconds"]),
            duration_seconds=spec["duration_seconds"],
            summary=spec["summary"],
            analysis={"langchain": {"summary": spec["summary"], **spec["analysis"]}},
        )
        created += 1
    if created:
        LOG.info("seed.calls_created", extra={"event": "seed.calls_created", "count": created})
    return created
