"""Initial schema: users, patients, calls.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-23

Postgres-only extras (guarded by dialect): regex CHECK constraints for phone/zip/state,
an updated_at trigger, and Row Level Security enabled with no policies so Supabase's
auto-generated REST API cannot read patient data (our direct connection bypasses RLS).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    tz = sa.DateTime(timezone=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", tz, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "patients",
        sa.Column("patient_id", sa.Uuid(), primary_key=True),
        sa.Column("first_name", sa.String(50), nullable=False),
        sa.Column("last_name", sa.String(50), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex", sa.String(20), nullable=False),
        sa.Column("phone_number", sa.String(10), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("address_line_1", sa.String(200), nullable=False),
        sa.Column("address_line_2", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("zip_code", sa.String(10), nullable=False),
        sa.Column("insurance_provider", sa.String(100), nullable=True),
        sa.Column("insurance_member_id", sa.String(50), nullable=True),
        sa.Column("preferred_language", sa.String(50), nullable=False, server_default="English"),
        sa.Column("emergency_contact_name", sa.String(100), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(10), nullable=True),
        sa.Column("created_at", tz, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", tz, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", tz, nullable=True),
        sa.CheckConstraint("sex IN ('" + "', '".join(SEX_VALUES) + "')", name="ck_patients_sex"),
        sa.CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        sa.CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        sa.CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        sa.CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_patients_city_len"),
        sa.CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        sa.CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_len"),
        sa.CheckConstraint(
            "emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
            name="ck_patients_emergency_phone_len",
        ),
    )
    op.create_index("ix_patients_last_name", "patients", ["last_name"])
    op.create_index("ix_patients_date_of_birth", "patients", ["date_of_birth"])
    op.create_index("ix_patients_phone_number", "patients", ["phone_number"])
    op.create_index("ix_patients_deleted_at", "patients", ["deleted_at"])

    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("vapi_call_id", sa.String(64), nullable=False),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.patient_id", ondelete="SET NULL"), nullable=True),
        sa.Column("caller_number", sa.String(32), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="phone"),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("matched_patient_id", sa.Uuid(), nullable=True),
        sa.Column("draft", _json_type(), nullable=False, server_default="{}"),
        sa.Column("captures", _json_type(), nullable=False, server_default="[]"),
        sa.Column("messages", _json_type(), nullable=False, server_default="[]"),
        sa.Column("analysis", _json_type(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.String(1024), nullable=True),
        sa.Column("ended_reason", sa.String(128), nullable=True),
        sa.Column("fields_captured", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("corrections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", tz, nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", tz, nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", tz, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", tz, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('in_progress', 'ended')", name="ck_calls_status"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('registered', 'updated', 'partial', 'failed')", name="ck_calls_outcome"
        ),
    )
    op.create_index("ix_calls_vapi_call_id", "calls", ["vapi_call_id"], unique=True)
    op.create_index("ix_calls_patient_id", "calls", ["patient_id"])
    op.create_index("ix_calls_started_at", "calls", ["started_at"])
    op.create_index("ix_calls_status", "calls", ["status"])

    if is_postgres:
        op.execute(
            "ALTER TABLE patients ADD CONSTRAINT ck_patients_phone_format CHECK (phone_number ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$')"
        )
        op.execute(
            "ALTER TABLE patients ADD CONSTRAINT ck_patients_zip_format CHECK (zip_code ~ '^[0-9]{5}(-[0-9]{4})?$')"
        )
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_state_format CHECK (state ~ '^[A-Z]{2}$')")
        op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_dob_past CHECK (date_of_birth <= CURRENT_DATE)")
        op.execute(
            """
            CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
            BEGIN
                NEW.updated_at = timezone('utc', now());
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table in ("patients", "calls"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
            )
        # Supabase exposes `public` tables through PostgREST; RLS with no policies blocks that path.
        for table in ("users", "patients", "calls"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    op.drop_table("calls")
    op.drop_table("patients")
    op.drop_table("users")
    if is_postgres:
        op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
