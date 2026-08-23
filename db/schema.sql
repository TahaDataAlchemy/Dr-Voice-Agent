-- Reference DDL for the Supabase Postgres schema (generated from alembic/versions/0001_initial.py).
-- The app applies this automatically on startup via `alembic upgrade head`; paste it in the Supabase
-- SQL editor only if you prefer to create the tables by hand.
--
-- Tables: users (dashboard logins), patients (spec data model + soft delete), calls (Vapi call state,
-- transcript, captures, analysis). Row Level Security is enabled with no policies so Supabase's
-- auto-generated REST API cannot read patient data; the app connects as the postgres role.

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR(254) NOT NULL, 
    hashed_password VARCHAR(255) NOT NULL, 
    full_name VARCHAR(100), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE patients (
    patient_id UUID NOT NULL, 
    first_name VARCHAR(50) NOT NULL, 
    last_name VARCHAR(50) NOT NULL, 
    date_of_birth DATE NOT NULL, 
    sex VARCHAR(20) NOT NULL, 
    phone_number VARCHAR(10) NOT NULL, 
    email VARCHAR(254), 
    address_line_1 VARCHAR(200) NOT NULL, 
    address_line_2 VARCHAR(100), 
    city VARCHAR(100) NOT NULL, 
    state VARCHAR(2) NOT NULL, 
    zip_code VARCHAR(10) NOT NULL, 
    insurance_provider VARCHAR(100), 
    insurance_member_id VARCHAR(50), 
    preferred_language VARCHAR(50) DEFAULT 'English' NOT NULL, 
    emergency_contact_name VARCHAR(100), 
    emergency_contact_phone VARCHAR(10), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (patient_id), 
    CONSTRAINT ck_patients_sex CHECK (sex IN ('Male', 'Female', 'Other', 'Decline to Answer')), 
    CONSTRAINT ck_patients_first_name_len CHECK (length(first_name) BETWEEN 1 AND 50), 
    CONSTRAINT ck_patients_last_name_len CHECK (length(last_name) BETWEEN 1 AND 50), 
    CONSTRAINT ck_patients_phone_len CHECK (length(phone_number) = 10), 
    CONSTRAINT ck_patients_city_len CHECK (length(city) BETWEEN 1 AND 100), 
    CONSTRAINT ck_patients_state_len CHECK (length(state) = 2), 
    CONSTRAINT ck_patients_zip_len CHECK (length(zip_code) IN (5, 10)), 
    CONSTRAINT ck_patients_emergency_phone_len CHECK (emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10)
);

CREATE INDEX ix_patients_last_name ON patients (last_name);

CREATE INDEX ix_patients_date_of_birth ON patients (date_of_birth);

CREATE INDEX ix_patients_phone_number ON patients (phone_number);

CREATE INDEX ix_patients_deleted_at ON patients (deleted_at);

CREATE TABLE calls (
    id UUID NOT NULL, 
    vapi_call_id VARCHAR(64) NOT NULL, 
    patient_id UUID, 
    caller_number VARCHAR(32), 
    channel VARCHAR(16) DEFAULT 'phone' NOT NULL, 
    status VARCHAR(16) DEFAULT 'in_progress' NOT NULL, 
    outcome VARCHAR(16), 
    stage VARCHAR(64), 
    matched_patient_id UUID, 
    draft JSONB DEFAULT '{}' NOT NULL, 
    captures JSONB DEFAULT '[]' NOT NULL, 
    messages JSONB DEFAULT '[]' NOT NULL, 
    analysis JSONB, 
    summary TEXT, 
    recording_url VARCHAR(1024), 
    ended_reason VARCHAR(128), 
    fields_captured INTEGER DEFAULT '0' NOT NULL, 
    corrections INTEGER DEFAULT '0' NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    ended_at TIMESTAMP WITH TIME ZONE, 
    duration_seconds INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_calls_status CHECK (status IN ('in_progress', 'ended')), 
    CONSTRAINT ck_calls_outcome CHECK (outcome IS NULL OR outcome IN ('registered', 'updated', 'partial', 'failed')), 
    FOREIGN KEY(patient_id) REFERENCES patients (patient_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_calls_vapi_call_id ON calls (vapi_call_id);

CREATE INDEX ix_calls_patient_id ON calls (patient_id);

CREATE INDEX ix_calls_started_at ON calls (started_at);

CREATE INDEX ix_calls_status ON calls (status);

ALTER TABLE patients ADD CONSTRAINT ck_patients_phone_format CHECK (phone_number ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$');

ALTER TABLE patients ADD CONSTRAINT ck_patients_zip_format CHECK (zip_code ~ '^[0-9]{5}(-[0-9]{4})?$');

ALTER TABLE patients ADD CONSTRAINT ck_patients_state_format CHECK (state ~ '^[A-Z]{2}$');

ALTER TABLE patients ADD CONSTRAINT ck_patients_dob_past CHECK (date_of_birth <= CURRENT_DATE);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
            BEGIN
                NEW.updated_at = timezone('utc', now());
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;;

CREATE TRIGGER trg_patients_updated_at BEFORE UPDATE ON patients FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_calls_updated_at BEFORE UPDATE ON calls FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;

ALTER TABLE calls ENABLE ROW LEVEL SECURITY;

INSERT INTO alembic_version (version_num) VALUES ('0001_initial') RETURNING alembic_version.version_num;

COMMIT;

