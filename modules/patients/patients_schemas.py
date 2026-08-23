"""
Pydantic I/O schemas for the patients API. All server-side validation goes through
`modules.patients.validators` so the API never relies on the voice agent's validation.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.patients import validators as v

SexLiteral = Literal["Male", "Female", "Other", "Decline to Answer"]


class _PatientFieldsMixin(BaseModel):
    """Normalizers shared by create/update. Each validator delegates to validators.py."""

    @field_validator("first_name", mode="before", check_fields=False)
    @classmethod
    def _first_name(cls, value):
        return v.normalize_name(value, "first name") if value is not None else value

    @field_validator("last_name", mode="before", check_fields=False)
    @classmethod
    def _last_name(cls, value):
        return v.normalize_name(value, "last name") if value is not None else value

    @field_validator("date_of_birth", mode="before", check_fields=False)
    @classmethod
    def _dob(cls, value):
        return v.parse_date_of_birth(value) if value not in (None, "") else None

    @field_validator("sex", mode="before", check_fields=False)
    @classmethod
    def _sex(cls, value):
        return v.normalize_sex(value) if value not in (None, "") else None

    @field_validator("phone_number", mode="before", check_fields=False)
    @classmethod
    def _phone(cls, value):
        return v.normalize_phone(value) if value is not None else value

    @field_validator("email", mode="before", check_fields=False)
    @classmethod
    def _email(cls, value):
        return v.normalize_email(value)

    @field_validator("address_line_1", mode="before", check_fields=False)
    @classmethod
    def _address1(cls, value):
        return v.normalize_text(value, "street address", 200, required=False)

    @field_validator("address_line_2", mode="before", check_fields=False)
    @classmethod
    def _address2(cls, value):
        return v.normalize_text(value, "apartment/suite", 100, required=False)

    @field_validator("city", mode="before", check_fields=False)
    @classmethod
    def _city(cls, value):
        return v.normalize_text(value, "city", 100) if value is not None else value

    @field_validator("state", mode="before", check_fields=False)
    @classmethod
    def _state(cls, value):
        return v.normalize_state(value) if value not in (None, "") else None

    @field_validator("zip_code", mode="before", check_fields=False)
    @classmethod
    def _zip(cls, value):
        return v.normalize_zip(value) if value not in (None, "") else None

    @field_validator("insurance_provider", mode="before", check_fields=False)
    @classmethod
    def _insurance_provider(cls, value):
        return v.normalize_text(value, "insurance provider", 100, required=False)

    @field_validator("insurance_member_id", mode="before", check_fields=False)
    @classmethod
    def _member_id(cls, value):
        return v.normalize_member_id(value)

    @field_validator("preferred_language", mode="before", check_fields=False)
    @classmethod
    def _language(cls, value):
        return v.normalize_language(value) if value is not None else value

    @field_validator("emergency_contact_name", mode="before", check_fields=False)
    @classmethod
    def _ec_name(cls, value):
        text = (value or "").strip() if isinstance(value, str) else value
        return v.normalize_full_name(text, "emergency contact name") if text else None

    @field_validator("emergency_contact_phone", mode="before", check_fields=False)
    @classmethod
    def _ec_phone(cls, value):
        text = (value or "").strip() if isinstance(value, str) else value
        return v.normalize_phone(text, "emergency contact phone") if text else None


class PatientCreate(_PatientFieldsMixin):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str = Field(..., examples=["Jane"])
    last_name: str = Field(..., examples=["Doe"])
    date_of_birth: date | None = Field(default=None, description="MM/DD/YYYY or YYYY-MM-DD", examples=["03/14/1987"])
    sex: SexLiteral | None = None
    phone_number: str = Field(..., description="10-digit U.S. number (formatting ignored)", examples=["2125550188"])
    email: str | None = Field(default=None, examples=["jane.d@mail.com"])
    address_line_1: str | None = Field(default=None, examples=["44 Bleecker St"])
    address_line_2: str | None = Field(default=None, examples=["Apt 3B"])
    city: str = Field(..., examples=["New York"])
    state: str | None = Field(default=None, description="2-letter abbreviation (full names accepted)", examples=["NY"])
    zip_code: str | None = Field(default=None, examples=["10012"])
    insurance_provider: str | None = Field(default=None, examples=["Aetna"])
    insurance_member_id: str | None = Field(default=None, examples=["W8842710X"])
    preferred_language: str = Field(default="English")
    emergency_contact_name: str | None = Field(default=None, examples=["Robert Doe"])
    emergency_contact_phone: str | None = Field(default=None, examples=["2125550190"])

    @model_validator(mode="after")
    def _emergency_contact_pair(self):
        # A phone without a name (or vice-versa) is allowed but we keep both optional; nothing to do.
        return self


class PatientUpdate(_PatientFieldsMixin):
    """Partial update: every field optional; only provided keys change."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: SexLiteral | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    def changed_fields(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date | None
    sex: str | None
    phone_number: str
    email: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str
    state: str | None
    zip_code: str | None
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    status: str = "active"

    @field_validator("created_at", "updated_at", "deleted_at", mode="before")
    @classmethod
    def _utc(cls, value):
        return _as_utc(value)

    @model_validator(mode="after")
    def _status(self):
        self.status = "deleted" if self.deleted_at else "active"
        return self


class PatientDeleted(BaseModel):
    patient_id: uuid.UUID
    deleted_at: datetime
