"""Make DOB, sex, address_line_1, state, zip_code optional (only name + phone + city required).

Revision ID: 0002_optional_demographics
Revises: 0001_initial
Create Date: 2026-08-23

The existing CHECK constraints (sex enum, zip/state/phone formats) stay in place; SQL CHECKs pass on
NULL, so they simply no longer apply when a value is absent.
"""

from __future__ import annotations

from alembic import op

revision = "0002_optional_demographics"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

NOW_OPTIONAL = ("date_of_birth", "sex", "address_line_1", "state", "zip_code")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite (tests) builds the schema from the model via create_all
    for col in NOW_OPTIONAL:
        op.alter_column("patients", col, nullable=True)
    # DOB-in-the-past check must tolerate NULL (it already does, but re-assert intent).
    op.execute("ALTER TABLE patients DROP CONSTRAINT IF EXISTS ck_patients_dob_past")
    op.execute("ALTER TABLE patients ADD CONSTRAINT ck_patients_dob_past CHECK (date_of_birth IS NULL OR date_of_birth <= CURRENT_DATE)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for col in NOW_OPTIONAL:
        op.alter_column("patients", col, nullable=False)
