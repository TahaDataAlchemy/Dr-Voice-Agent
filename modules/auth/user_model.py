"""`users` table - dashboard accounts (custom JWT auth)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(max_length=254, unique=True, index=True, nullable=False)
    hashed_password: str = Field(max_length=255, nullable=False)
    full_name: str | None = Field(default=None, max_length=100)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False, default=utcnow)
    )
