"""
REST endpoints for patients (assessment spec):

  GET    /patients            list (filters: last_name, date_of_birth, phone_number; extra: q, include_deleted)
  GET    /patients/{id}       single patient
  POST   /patients            create -> 201
  PUT    /patients/{id}       partial update
  DELETE /patients/{id}       soft delete (sets deleted_at)

Every response uses the {"data": ..., "error": ...} envelope (see core/responses.py).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse

from core.database import SessionDep
from core.responses import AppError, envelope
from modules.patients import validators as v
from modules.patients.patients_schemas import PatientCreate, PatientDeleted, PatientRead, PatientUpdate
from modules.patients.patients_service import PatientService

patients_router = APIRouter(prefix="/patients", tags=["Patients"])

_ENVELOPE_EXAMPLE = {"data": {"patient_id": "a3f9c2e1-7b04-4d8a-9e15-2c6f8b0d4471", "first_name": "Jane"}, "error": None}


def _validate_filters(last_name: str | None, date_of_birth: str | None, phone_number: str | None) -> None:
    details = []
    if date_of_birth:
        try:
            v.parse_date_of_birth(date_of_birth)
        except ValueError as exc:
            details.append({"field": "date_of_birth", "message": str(exc)})
    if phone_number:
        try:
            v.normalize_phone(phone_number)
        except ValueError as exc:
            details.append({"field": "phone_number", "message": str(exc)})
    if details:
        raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", "Invalid query parameters", details)


@patients_router.get(
    "",
    summary="List patients",
    responses={200: {"content": {"application/json": {"example": {"data": [], "error": None}}}}},
)
def list_patients(
    session: SessionDep,
    last_name: Annotated[str | None, Query(description="Exact match, case-insensitive")] = None,
    date_of_birth: Annotated[str | None, Query(description="MM/DD/YYYY or YYYY-MM-DD")] = None,
    phone_number: Annotated[str | None, Query(description="10-digit U.S. number, any formatting")] = None,
    q: Annotated[str | None, Query(description="Free-text search over name, phone, email, DOB")] = None,
    include_deleted: Annotated[bool, Query(description="Include soft-deleted records")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    _validate_filters(last_name, date_of_birth, phone_number)
    patients = PatientService(session).list(
        last_name=last_name,
        date_of_birth=date_of_birth,
        phone_number=phone_number,
        q=q,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return envelope([PatientRead.model_validate(p) for p in patients])


@patients_router.get("/{patient_id}", summary="Get a patient by id")
def get_patient(patient_id: uuid.UUID, session: SessionDep, include_deleted: bool = False) -> JSONResponse:
    patient = PatientService(session).get(patient_id, include_deleted=include_deleted)
    return envelope(PatientRead.model_validate(patient))


@patients_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a patient",
    responses={201: {"content": {"application/json": {"example": _ENVELOPE_EXAMPLE}}}},
)
def create_patient(payload: Annotated[PatientCreate, Body()], session: SessionDep) -> JSONResponse:
    patient = PatientService(session).create(payload)
    return envelope(PatientRead.model_validate(patient), status.HTTP_201_CREATED)


@patients_router.put("/{patient_id}", summary="Update a patient (partial updates allowed)")
def update_patient(
    patient_id: uuid.UUID, payload: Annotated[PatientUpdate, Body()], session: SessionDep
) -> JSONResponse:
    patient = PatientService(session).update(patient_id, payload)
    return envelope(PatientRead.model_validate(patient))


@patients_router.patch("/{patient_id}", include_in_schema=False)
def patch_patient(
    patient_id: uuid.UUID, payload: Annotated[PatientUpdate, Body()], session: SessionDep
) -> JSONResponse:
    return update_patient(patient_id, payload, session)


@patients_router.delete("/{patient_id}", summary="Soft-delete a patient (sets deleted_at)")
def delete_patient(patient_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    patient = PatientService(session).soft_delete(patient_id)
    return envelope(PatientDeleted(patient_id=patient.patient_id, deleted_at=patient.deleted_at))
