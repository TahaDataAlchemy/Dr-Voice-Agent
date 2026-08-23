"""
PatientService - the single data-access layer for patients.

Both the REST API and the voice agent tools go through this class, so behaviour
(soft delete, filtering, timestamps, duplicate lookup) is identical regardless of entry point.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from core.logger.logger import LOG
from core.responses import NotFoundError
from modules.patients import validators as v
from modules.patients.patient_model import Patient
from modules.patients.patients_schemas import PatientCreate, PatientUpdate


class PatientService:
    def __init__(self, session: Session):
        self.session = session

    # ----------------------------------------------------------------- queries
    def list(
        self,
        *,
        last_name: str | None = None,
        date_of_birth: date | str | None = None,
        phone_number: str | None = None,
        q: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Patient]:
        stmt = select(Patient)
        if not include_deleted:
            stmt = stmt.where(Patient.deleted_at.is_(None))
        if last_name:
            stmt = stmt.where(func.lower(Patient.last_name) == last_name.strip().lower())
        if date_of_birth:
            dob = date_of_birth if isinstance(date_of_birth, date) else v.parse_date_of_birth(date_of_birth)
            stmt = stmt.where(Patient.date_of_birth == dob)
        if phone_number:
            stmt = stmt.where(Patient.phone_number == v.normalize_phone(phone_number))
        if q:
            term = q.strip()
            digits = "".join(ch for ch in term if ch.isdigit())
            like = f"%{term.lower()}%"
            conditions = [
                func.lower(Patient.first_name).like(like),
                func.lower(Patient.last_name).like(like),
                func.lower(Patient.first_name + " " + Patient.last_name).like(like),
                func.lower(Patient.email).like(like),
            ]
            if digits:
                conditions.append(Patient.phone_number.like(f"%{digits}%"))
            try:
                conditions.append(Patient.date_of_birth == v.parse_date_of_birth(term))
            except ValueError:
                pass
            stmt = stmt.where(or_(*conditions))
        stmt = stmt.order_by(Patient.created_at.desc()).offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def get(self, patient_id: uuid.UUID, *, include_deleted: bool = False) -> Patient:
        patient = self.session.get(Patient, patient_id)
        if patient is None or (patient.deleted_at is not None and not include_deleted):
            raise NotFoundError(f"Patient {patient_id} not found")
        return patient

    def find_by_phone(self, phone_number: str) -> Patient | None:
        """Most recently created active patient with this phone (used for duplicate detection)."""
        digits = v.normalize_phone(phone_number)
        stmt = (
            select(Patient)
            .where(Patient.phone_number == digits, Patient.deleted_at.is_(None))
            .order_by(Patient.created_at.desc())
        )
        return self.session.exec(stmt).first()

    def count_active(self) -> int:
        return self.session.exec(select(func.count()).select_from(Patient).where(Patient.deleted_at.is_(None))).one()

    # ---------------------------------------------------------------- mutations
    def create(self, data: PatientCreate | dict[str, Any]) -> Patient:
        payload = data if isinstance(data, PatientCreate) else PatientCreate.model_validate(data)
        patient = Patient(**payload.model_dump())
        self.session.add(patient)
        self.session.commit()
        self.session.refresh(patient)
        LOG.info(
            "patient.created",
            extra={"event": "patient.created", "patient_id": str(patient.patient_id), "payload": _loggable(patient)},
        )
        return patient

    def update(self, patient_id: uuid.UUID, data: PatientUpdate | dict[str, Any]) -> Patient:
        payload = data if isinstance(data, PatientUpdate) else PatientUpdate.model_validate(data)
        patient = self.get(patient_id)
        changes = payload.changed_fields()
        for key, value in changes.items():
            setattr(patient, key, value)
        patient.updated_at = datetime.now(timezone.utc)
        self.session.add(patient)
        self.session.commit()
        self.session.refresh(patient)
        LOG.info(
            "patient.updated",
            extra={"event": "patient.updated", "patient_id": str(patient.patient_id), "changes": _json_safe(changes)},
        )
        return patient

    def soft_delete(self, patient_id: uuid.UUID) -> Patient:
        patient = self.get(patient_id)
        patient.deleted_at = datetime.now(timezone.utc)
        patient.updated_at = patient.deleted_at
        self.session.add(patient)
        self.session.commit()
        self.session.refresh(patient)
        LOG.info("patient.soft_deleted", extra={"event": "patient.soft_deleted", "patient_id": str(patient_id)})
        return patient

    def restore(self, patient_id: uuid.UUID) -> Patient:
        patient = self.get(patient_id, include_deleted=True)
        patient.deleted_at = None
        patient.updated_at = datetime.now(timezone.utc)
        self.session.add(patient)
        self.session.commit()
        self.session.refresh(patient)
        return patient


def _json_safe(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (v_.isoformat() if isinstance(v_, (date, datetime)) else v_) for k, v_ in data.items()}


def _loggable(patient: Patient) -> dict[str, Any]:
    return _json_safe(
        {k: getattr(patient, k) for k in v.ALL_FIELDS} | {"patient_id": str(patient.patient_id)}
    )
