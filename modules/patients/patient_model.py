"""
`patients` table - the standard minimum U.S. demographic dataset from the assessment spec.

Column types/constraints enforce the data model at the database level (NOT NULL, lengths,
CHECK constraints). Postgres-only CHECKs (regex on phone/zip) and the `updated_at` trigger
are added by the Alembic migration so the model stays portable to SQLite for tests.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Index
from sqlmodel import Field, SQLModel

from modules.patients.validators import SEX_VALUES


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tz_datetime(*, nullable: bool, onupdate: bool = False) -> Column:
    kwargs = {"nullable": nullable}
    if not nullable:
        kwargs["default"] = utcnow
    if onupdate:
        kwargs["onupdate"] = utcnow
    return Column(DateTime(timezone=True), **kwargs)


class Patient(SQLModel, table=True):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint(
            "sex IN ('" + "', '".join(SEX_VALUES) + "')",
            name="ck_patients_sex",
        ),
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_patients_city_len"),
        CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_len"),
        CheckConstraint(
            "emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
            name="ck_patients_emergency_phone_len",
        ),
        Index("ix_patients_last_name", "last_name"),
        Index("ix_patients_date_of_birth", "date_of_birth"),
        Index("ix_patients_phone_number", "phone_number"),
        Index("ix_patients_deleted_at", "deleted_at"),
    )

    patient_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Required demographics
    first_name: str = Field(max_length=50, nullable=False)
    last_name: str = Field(max_length=50, nullable=False)
    date_of_birth: date = Field(nullable=False)
    sex: str = Field(max_length=20, nullable=False)
    phone_number: str = Field(max_length=10, nullable=False, description="10 digits, no formatting")

    # Optional contact
    email: str | None = Field(default=None, max_length=254)

    # Address
    address_line_1: str = Field(max_length=200, nullable=False)
    address_line_2: str | None = Field(default=None, max_length=100)
    city: str = Field(max_length=100, nullable=False)
    state: str = Field(max_length=2, nullable=False)
    zip_code: str = Field(max_length=10, nullable=False)

    # Optional extras (opt-in during the call)
    insurance_provider: str | None = Field(default=None, max_length=100)
    insurance_member_id: str | None = Field(default=None, max_length=50)
    preferred_language: str = Field(default="English", max_length=50, nullable=False)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None, max_length=10)

    # Audit
    created_at: datetime = Field(default_factory=utcnow, sa_column=_tz_datetime(nullable=False))
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=_tz_datetime(nullable=False, onupdate=True)
    )
    deleted_at: datetime | None = Field(default=None, sa_column=_tz_datetime(nullable=True))

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
