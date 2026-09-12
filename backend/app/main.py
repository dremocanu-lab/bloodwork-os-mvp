import os
import re
import json
import secrets
import tempfile
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

# Loads backend/.env for local development (documented in .env.example).
# No-op if the file doesn't exist — production (Render etc.) sets real
# environment variables directly, so this never overrides those.
load_dotenv()


def generate_public_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import models
from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_password_timing_safe,
)
from app.db import SessionLocal, engine
from app.services.document_pipeline import process_uploaded_document
from app.services.lab_catalog import find_lab_definition
from app.services.discharge_summary_pipeline import process_uploaded_discharge_summary
from app.services.medication_lookup import lookup_medication
from app.services.document_taxonomy import (
    AUTO_CLASSIFY_SECTION,
    DOCUMENT_TYPE_LABELS,
    document_type_choices,
    is_valid_document_type,
    legacy_section_for,
)
from app.services.extraction_provider import REDUCTO, ProcessingMetadata, get_extraction_provider
from app.services.reducto_client import ReductoError
from app.services import reducto_extraction
from app.services.ocr_service import extract_text as ocr_extract_text
from app.services.file_hash import compute_sha256
from app.services.security_scan import run_security_scan
from app.services.ask_bragi.context import (
    AskBragiAccessDenied,
    AskBragiContext,
    recheck_access,
    resolve_document_scope,
    resolve_patient_id_for_new_conversation,
)
from app.services.ask_bragi.service import ASK_BRAGI_ENABLED, AskBragiError, run_turn, run_turn_streaming
from app.rate_limit import RateLimiter
from app.services.patient_identity import (
    MISMATCH,
    NEEDS_CONFIRMATION,
    IdentityCheckResult,
    check_patient_identity,
)
from app.services.structured_reader_service import (
    SECTION_KEYS as READER_SECTION_KEYS,
    extract_structured_sections,
)
from app.services.interop.flags import INTEROP_FHIR_ENABLED, IS_PRODUCTION
from app.services.interop import (
    auth_providers as interop_auth_providers,
    capability as interop_capability,
    fhir_connector,
    identity as interop_identity,
    jwks as interop_jwks,
    reports as interop_reports,
    templates as interop_templates,
)
from app.services.interop.crypto import encrypt_secret as interop_encrypt_secret
from app.services.interop.mapping import MappingError, parse_mapping_rule

app = FastAPI()

# --- Schema provisioning: RETIRED as an import-time side effect ------------
#
# Until this point, every app.main import unconditionally ran
# `models.Base.metadata.create_all(bind=engine)` followed by
# `run_migrations()` (a ~570-line function of hand-written idempotent
# `CREATE TABLE`/`ALTER TABLE`/`CREATE INDEX`/`DO $$` blocks) — acceptable
# during early MVP development, no longer acceptable now that real
# production data exists, multiple environments exist, and schema
# complexity is growing (see BRAGI_INTEROP_PLAN.md's migration-framework
# section). Schema is now managed by Alembic — see `alembic/` and
# `docs/database/MIGRATIONS.md`:
#
#   - A brand-new database: `alembic upgrade head` (see
#     backend/scripts/run_migrations.py for the advisory-lock-guarded
#     runner used in deployment).
#   - An existing database that already has schema from the OLD
#     create_all()/run_migrations() startup code: a one-time, explicit
#     operator action — `python scripts/bootstrap_alembic.py` — verifies
#     the live schema and stamps it to the matching revision. This is
#     NEVER automatic; ordinary application startup does not create,
#     alter, or stamp anything.
#   - Tests: tests/conftest.py runs `alembic upgrade head` once per
#     session (only when DATABASE_URL is set), so a fresh CI/ephemeral
#     Postgres is provisioned the same way a real deployment would be.
#
# `run_migrations()`'s function body is kept below, UNCALLED, as a
# historical reference for exactly what the old startup path used to do
# (its content is now represented, revision-for-revision, by
# alembic/versions/0001_legacy_baseline.py and
# alembic/versions/0002_interop_phase1.py) — it is dead code, never
# invoked, and must not be resurrected as an automatic startup step.


def run_migrations():
    with engine.connect() as conn:
        # CRITICAL, found via a real production failure: documents.is_verified
        # is declared Boolean in the model (models.py), but on at least one
        # real deployment the live column is still INTEGER — every single
        # Document insert (any provider, not Reducto-specific) fails with
        # `psycopg.errors.DatatypeMismatch: column "is_verified" is of type
        # integer but expression is of type boolean`. A prior phase's
        # commit changed the Python declaration to Boolean after checking
        # ITS OWN dev DB, but never added a migration to convert the column
        # itself — meaning any environment whose column predates that
        # change silently breaks every upload. Idempotent: only runs the
        # actual ALTER when the column isn't boolean yet.
        conn.execute(text("""
            DO $$
            BEGIN
                IF (
                    SELECT data_type FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'is_verified'
                ) IS DISTINCT FROM 'boolean' THEN
                    ALTER TABLE documents ALTER COLUMN is_verified DROP DEFAULT;
                    ALTER TABLE documents ALTER COLUMN is_verified TYPE BOOLEAN USING (is_verified::int <> 0);
                    ALTER TABLE documents ALTER COLUMN is_verified SET DEFAULT false;
                END IF;
            END $$;
        """))
        conn.execute(text("ALTER TABLE doctor_patient_access ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1"))
        conn.execute(text("ALTER TABLE doctor_patient_access ADD COLUMN IF NOT EXISTS ended_at VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS source_section VARCHAR"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS patient_medications (
                id SERIAL PRIMARY KEY,
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                created_by_user_id INTEGER NOT NULL REFERENCES users(id),
                updated_by_user_id INTEGER REFERENCES users(id),
                name VARCHAR NOT NULL,
                dose_strength VARCHAR,
                frequency VARCHAR,
                reason TEXT,
                status VARCHAR NOT NULL DEFAULT 'active',
                route_form VARCHAR,
                start_date VARCHAR,
                stop_date VARCHAR,
                prescriber VARCHAR,
                extra_info TEXT,
                is_uncertain INTEGER NOT NULL DEFAULT 0,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR,
                official_match_status VARCHAR,
                official_source_name VARCHAR,
                official_source_url VARCHAR,
                rxnorm_rxcui VARCHAR,
                dailymed_setid VARCHAR,
                official_info_json TEXT,
                official_retrieved_at VARCHAR,
                official_label_date VARCHAR
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_patient_medications_patient_id ON patient_medications(patient_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_patient_medications_status ON patient_medications(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_patient_medications_name ON patient_medications(name)"))
        # Emergency access portal tables
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS emergency_access_sessions (
                id SERIAL PRIMARY KEY,
                emergency_user_id INTEGER NOT NULL REFERENCES users(id),
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                reason VARCHAR NOT NULL,
                reason_note TEXT,
                started_at VARCHAR NOT NULL,
                expires_at VARCHAR NOT NULL,
                closed_at VARCHAR,
                ip_address VARCHAR,
                user_agent VARCHAR,
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eas_user ON emergency_access_sessions(emergency_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eas_patient ON emergency_access_sessions(patient_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS emergency_audit_logs (
                id SERIAL PRIMARY KEY,
                emergency_user_id INTEGER REFERENCES users(id),
                patient_id INTEGER REFERENCES patients(id),
                session_id INTEGER REFERENCES emergency_access_sessions(id),
                action VARCHAR NOT NULL,
                ip_address VARCHAR,
                user_agent VARCHAR,
                details TEXT,
                timestamp VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eal_user ON emergency_audit_logs(emergency_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eal_patient ON emergency_audit_logs(patient_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eal_session ON emergency_audit_logs(session_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eal_action ON emergency_audit_logs(action)"))
        # Emergency discoverability setting on patients
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS emergency_search_enabled INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS emergency_search_updated_at VARCHAR"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS emergency_search_consent_text_version VARCHAR"))
        # Revocation fields on emergency sessions
        conn.execute(text("ALTER TABLE emergency_access_sessions ADD COLUMN IF NOT EXISTS revoked_at VARCHAR"))
        conn.execute(text("ALTER TABLE emergency_access_sessions ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR"))
        # Emergency contacts table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS emergency_contacts (
                id SERIAL PRIMARY KEY,
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                name VARCHAR NOT NULL,
                relationship VARCHAR,
                phone VARCHAR,
                notes VARCHAR,
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ec_patient ON emergency_contacts(patient_id)"))
        # Doctor type field for PCP/specialist distinction
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS doctor_type VARCHAR"))
        # Normalize existing doctors: default to specialist, then upgrade PCP matches
        conn.execute(text("""
            UPDATE users SET doctor_type = 'specialist'
            WHERE role = 'doctor' AND doctor_type IS NULL
        """))
        conn.execute(text("""
            UPDATE users SET doctor_type = 'pcp'
            WHERE role = 'doctor' AND doctor_type = 'specialist' AND (
                LOWER(department) LIKE '%pcp%' OR
                LOWER(department) LIKE '%primary care%' OR
                LOWER(department) LIKE '%family medicine%' OR
                LOWER(department) LIKE '%family physician%' OR
                LOWER(department) LIKE '%general practice%' OR
                LOWER(department) = 'gp' OR
                LOWER(department) LIKE '%doctor de familie%' OR
                LOWER(department) LIKE '%medic de familie%' OR
                LOWER(department) LIKE '%medicina de familie%' OR
                LOWER(department) LIKE '%medicin%familie%'
            )
        """))
        # Bragi document taxonomy / classification metadata (Phase 1 —
        # see BRAGI_REDUCTO_PLAN.md). Additive to `section`.
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS classification_status VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS classification_confidence FLOAT"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS classification_source VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_document_type ON documents(document_type)"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS document_type VARCHAR"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS classification_status VARCHAR"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS classification_confidence FLOAT"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS classification_source VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_upload_jobs_document_type ON upload_jobs(document_type)"))
        # Public ID columns for pretty URLs
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS public_id VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS public_id VARCHAR"))
        conn.execute(text("ALTER TABLE emergency_access_sessions ADD COLUMN IF NOT EXISTS public_id VARCHAR"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_patients_public_id ON patients(public_id) WHERE public_id IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_public_id ON documents(public_id) WHERE public_id IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_eas_public_id ON emergency_access_sessions(public_id) WHERE public_id IS NOT NULL"))
        conn.commit()
        # Backfill public_ids for existing rows (done in Python for cross-DB compatibility)
        patients_no_pub = conn.execute(text("SELECT id FROM patients WHERE public_id IS NULL")).fetchall()
        for row in patients_no_pub:
            conn.execute(
                text("UPDATE patients SET public_id = :pid WHERE id = :id AND public_id IS NULL"),
                {"pid": generate_public_id("brg-pt"), "id": row[0]},
            )
        docs_no_pub = conn.execute(text("SELECT id FROM documents WHERE public_id IS NULL")).fetchall()
        for row in docs_no_pub:
            conn.execute(
                text("UPDATE documents SET public_id = :pid WHERE id = :id AND public_id IS NULL"),
                {"pid": generate_public_id("brg-doc"), "id": row[0]},
            )
        sessions_no_pub = conn.execute(text("SELECT id FROM emergency_access_sessions WHERE public_id IS NULL")).fetchall()
        for row in sessions_no_pub:
            conn.execute(
                text("UPDATE emergency_access_sessions SET public_id = :pid WHERE id = :id AND public_id IS NULL"),
                {"pid": generate_public_id("brg-em"), "id": row[0]},
            )
        conn.commit()

        # Phase 2 — identity/duplicate safety + provenance groundwork
        # (see BRAGI_REDUCTO_PLAN.md Phase 2).
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_sha256 VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS identity_status VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_status VARCHAR"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS intended_patient_id INTEGER REFERENCES patients(id)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS structured_sections TEXT"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS parsed_content TEXT"))
        # Real Reducto Split integration — mixed-PDF parent/child documents.
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS parent_document_id INTEGER REFERENCES documents(id)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_range_start INTEGER"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_range_end INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_parent_document_id ON documents(parent_document_id)"))
        # Self-referential FKs must not block deleting either side, in
        # whichever order a caller happens to delete rows — found via a
        # real 500 on DELETE /my/account for a patient with a split
        # document (parent_document_id) or a linked duplicate lab row
        # (duplicate_of_lab_result_id, a pre-existing Phase 2 FK with the
        # same gap). ON DELETE SET NULL fixes this for every current and
        # future deletion path, not just one endpoint. Guarded so the
        # ALTER only actually runs once, not on every app start.
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'documents_parent_document_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_parent_document_id_fkey;
                    ALTER TABLE documents ADD CONSTRAINT documents_parent_document_id_fkey
                        FOREIGN KEY (parent_document_id) REFERENCES documents(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'lab_results_duplicate_of_lab_result_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE lab_results DROP CONSTRAINT IF EXISTS lab_results_duplicate_of_lab_result_id_fkey;
                    ALTER TABLE lab_results ADD CONSTRAINT lab_results_duplicate_of_lab_result_id_fkey
                        FOREIGN KEY (duplicate_of_lab_result_id) REFERENCES lab_results(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_file_sha256 ON documents(file_sha256)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_review_status ON documents(review_status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_intended_patient_id ON documents(intended_patient_id)"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS file_sha256 VARCHAR"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS identity_status VARCHAR"))
        conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN IF NOT EXISTS identity_override INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS observation_datetime VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS institution VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS specimen VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS accession_id VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS verification_state VARCHAR DEFAULT 'unverified'"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS extraction_confidence FLOAT"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS normalization_confidence FLOAT"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS normalization_method VARCHAR"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS duplicate_of_lab_result_id INTEGER REFERENCES lab_results(id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lab_results_observation_datetime ON lab_results(observation_datetime)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS source_evidence (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                lab_result_id INTEGER REFERENCES lab_results(id),
                page_number INTEGER,
                bbox_x FLOAT,
                bbox_y FLOAT,
                bbox_width FLOAT,
                bbox_height FLOAT,
                source_block_id VARCHAR,
                source_text TEXT,
                extraction_confidence FLOAT,
                provider VARCHAR,
                parser_version VARCHAR,
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_source_evidence_document_id ON source_evidence(document_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_source_evidence_lab_result_id ON source_evidence(lab_result_id)"))
        # Presentation-only "whole row" geometry for lab evidence — derived
        # from the real per-field bboxes above, see models.py's docstring.
        conn.execute(text("ALTER TABLE source_evidence ADD COLUMN IF NOT EXISTS row_bbox_x FLOAT"))
        conn.execute(text("ALTER TABLE source_evidence ADD COLUMN IF NOT EXISTS row_bbox_y FLOAT"))
        conn.execute(text("ALTER TABLE source_evidence ADD COLUMN IF NOT EXISTS row_bbox_width FLOAT"))
        conn.execute(text("ALTER TABLE source_evidence ADD COLUMN IF NOT EXISTS row_bbox_height FLOAT"))

        # Same FK-cascade class of bug as parent_document_id/duplicate_of_
        # lab_result_id above, found by a security audit rather than a live
        # 500 this time: DELETE /my/account would fail for any patient who
        # ever had an emergency-access session opened on them, or who
        # appears (as subject or context) in an admin-action-log row —
        # both are audit-relevant records that must survive the patient's
        # own account deletion (see docs/privacy/RETENTION_POLICY.md), so
        # the fix is to detach the reference (SET NULL), not delete the
        # audit row. emergency_access_sessions.patient_id is also made
        # nullable here (was NOT NULL) to allow that — see models.py's
        # comment on the column; any session still ACTIVE at the moment of
        # deletion is immediately unusable once nulled (every access check
        # compares patient_id by equality, so None never matches a real
        # patient id — fails closed, not open).
        conn.execute(text("ALTER TABLE emergency_access_sessions ALTER COLUMN patient_id DROP NOT NULL"))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'emergency_access_sessions_patient_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE emergency_access_sessions DROP CONSTRAINT IF EXISTS emergency_access_sessions_patient_id_fkey;
                    ALTER TABLE emergency_access_sessions ADD CONSTRAINT emergency_access_sessions_patient_id_fkey
                        FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'emergency_audit_logs_patient_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE emergency_audit_logs DROP CONSTRAINT IF EXISTS emergency_audit_logs_patient_id_fkey;
                    ALTER TABLE emergency_audit_logs ADD CONSTRAINT emergency_audit_logs_patient_id_fkey
                        FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        # Found by an actual reproduction, not just reading the schema: a
        # PATIENT who ever changed their own emergency-access settings gets
        # an emergency_audit_logs row with emergency_user_id set to THEIR
        # OWN user id (the actor of that settings change, not necessarily
        # an emergency_worker role) — so this FK can block deleting an
        # ordinary patient's user row too, not just an emergency worker's.
        # emergency_user_id is already nullable; only the constraint's
        # delete rule needed fixing. Same for session_id (nullable, no
        # session is ever hard-deleted today, but fixed for consistency/
        # defense-in-depth rather than assuming that stays true).
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'emergency_audit_logs_emergency_user_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE emergency_audit_logs DROP CONSTRAINT IF EXISTS emergency_audit_logs_emergency_user_id_fkey;
                    ALTER TABLE emergency_audit_logs ADD CONSTRAINT emergency_audit_logs_emergency_user_id_fkey
                        FOREIGN KEY (emergency_user_id) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'emergency_audit_logs_session_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE emergency_audit_logs DROP CONSTRAINT IF EXISTS emergency_audit_logs_session_id_fkey;
                    ALTER TABLE emergency_audit_logs ADD CONSTRAINT emergency_audit_logs_session_id_fkey
                        FOREIGN KEY (session_id) REFERENCES emergency_access_sessions(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.referential_constraints
                    WHERE constraint_name = 'admin_action_logs_patient_id_fkey' AND delete_rule = 'SET NULL'
                ) THEN
                    ALTER TABLE admin_action_logs DROP CONSTRAINT IF EXISTS admin_action_logs_patient_id_fkey;
                    ALTER TABLE admin_action_logs ADD CONSTRAINT admin_action_logs_patient_id_fkey
                        FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))

        # Priority 8 (role deletion completeness, BRAGI_SECURITY_GDPR_PLAN.md
        # §19): doctor/admin self-deletion is a soft-delete (row persists,
        # deleted_at is set) rather than a hard row delete — a real hard
        # delete would need ON DELETE SET NULL/CASCADE across ~8 tables
        # (doctor_patient_access, doctor_patient_access_requests,
        # patient_events, documents.uploaded_by_user_id,
        # doctor_document_reviews, patient_medications, admin_action_logs,
        # upload_jobs) that hold NOT NULL clinical/audit references to a
        # doctor or admin's user id — several of those rows are part of a
        # PATIENT's own clinical record (who treated them, who uploaded a
        # document), which must not disappear or go anonymous just because
        # the clinician later deletes their own account. See
        # get_current_user()/login() for where deleted_at is enforced.
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at VARCHAR"))

        # Ask Bragi (see BRAGI_ASK_BRAGI_PLAN.md, models.py's docstrings on
        # both tables). Additive, brand-new tables — no data migration
        # concern. Feature-flagged off by default (ASK_BRAGI_ENABLED) so
        # these tables existing has zero effect until explicitly enabled.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ask_bragi_conversations (
                id SERIAL PRIMARY KEY,
                public_id VARCHAR UNIQUE,
                owner_user_id INTEGER NOT NULL REFERENCES users(id),
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                scope VARCHAR NOT NULL DEFAULT 'patient_record',
                document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                owner_role VARCHAR NOT NULL,
                title VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR,
                archived_at VARCHAR
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ask_bragi_conversations_owner_user_id ON ask_bragi_conversations (owner_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ask_bragi_conversations_patient_id ON ask_bragi_conversations (patient_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ask_bragi_messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES ask_bragi_conversations(id) ON DELETE CASCADE,
                role VARCHAR NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT,
                chart_json TEXT,
                follow_ups_json TEXT,
                status VARCHAR,
                tool_categories_json TEXT,
                prompt_version VARCHAR,
                tool_schema_version VARCHAR,
                model VARCHAR,
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ask_bragi_messages_conversation_id ON ask_bragi_messages (conversation_id)"))
        # Visible scope-broadening (see app/services/ask_bragi/context.py's
        # turn_scope/broadened_this_turn) — added after the two tables
        # above, additive.
        conn.execute(text("ALTER TABLE ask_bragi_messages ADD COLUMN IF NOT EXISTS scope_used VARCHAR"))
        # Conversation creation is now lazy (see POST /ask-bragi/conversations
        # and ask-bragi-chat.tsx's `start()` effect): a row is only ever
        # created once a first real user message is submitted, so a
        # zero-message conversation should no longer occur in normal use.
        # This DELETE is (a) a one-time cleanup of rows persisted by the
        # PREVIOUS, eager-creation behavior (every "New conversation"
        # opened-but-never-used before this fix), and (b) an ongoing,
        # idempotent self-healing backstop that runs on every startup in
        # case some other path ever creates an empty conversation again —
        # it only ever matches rows with zero messages, so it can never
        # touch a real conversation.
        conn.execute(text("""
            DELETE FROM ask_bragi_conversations
            WHERE NOT EXISTS (
                SELECT 1 FROM ask_bragi_messages
                WHERE ask_bragi_messages.conversation_id = ask_bragi_conversations.id
            )
        """))

        # Interoperability (BRAGI_INTEROP_PLAN.md — Phase 1: FHIR connector).
        # Additive: nothing above this point changes. See app/models.py's
        # "Interoperability" section for what each table is for.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_secrets (
                id SERIAL PRIMARY KEY,
                ref VARCHAR NOT NULL UNIQUE,
                ciphertext TEXT NOT NULL,
                created_at VARCHAR NOT NULL,
                created_by_user_id INTEGER REFERENCES users(id),
                rotated_at VARCHAR
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_connections (
                id SERIAL PRIMARY KEY,
                public_id VARCHAR UNIQUE,
                name VARCHAR NOT NULL,
                connector_type VARCHAR NOT NULL DEFAULT 'fhir',
                status VARCHAR NOT NULL DEFAULT 'draft',
                base_url VARCHAR NOT NULL,
                fhir_version VARCHAR,
                allow_private_network BOOLEAN NOT NULL DEFAULT false,
                auth_type VARCHAR NOT NULL DEFAULT 'none',
                auth_config_json TEXT,
                secret_ref VARCHAR REFERENCES interop_secrets(ref),
                patient_identity_json TEXT,
                capabilities_json TEXT,
                capabilities_discovered_at VARCHAR,
                terminology_overrides_json TEXT,
                sync_config_json TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_by_user_id INTEGER REFERENCES users(id),
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL,
                change_reason VARCHAR
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_interop_connections_status ON interop_connections(status)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_sync_runs (
                id SERIAL PRIMARY KEY,
                connection_id INTEGER NOT NULL REFERENCES interop_connections(id) ON DELETE CASCADE,
                run_type VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'running',
                summary_json TEXT,
                error_message TEXT,
                started_at VARCHAR NOT NULL,
                finished_at VARCHAR,
                started_by_user_id INTEGER REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_interop_sync_runs_connection_id ON interop_sync_runs(connection_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_patient_identity_links (
                id SERIAL PRIMARY KEY,
                connection_id INTEGER NOT NULL REFERENCES interop_connections(id) ON DELETE CASCADE,
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                identifier_system VARCHAR NOT NULL,
                identifier_value VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'verified',
                verification_method VARCHAR,
                verified_at VARCHAR,
                verified_by_user_id INTEGER REFERENCES users(id),
                created_at VARCHAR NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_epil_connection_id ON interop_patient_identity_links(connection_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_epil_patient_id ON interop_patient_identity_links(patient_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_epil_identifier_system ON interop_patient_identity_links(identifier_system)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_epil_identifier_value ON interop_patient_identity_links(identifier_value)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_identity_conflicts (
                id SERIAL PRIMARY KEY,
                connection_id INTEGER NOT NULL REFERENCES interop_connections(id) ON DELETE CASCADE,
                identifier_system VARCHAR NOT NULL,
                identifier_value VARCHAR NOT NULL,
                existing_link_id INTEGER REFERENCES interop_patient_identity_links(id),
                attempted_patient_id INTEGER REFERENCES patients(id),
                detected_at VARCHAR NOT NULL,
                resolved BOOLEAN NOT NULL DEFAULT false,
                resolved_at VARCHAR,
                resolved_by_user_id INTEGER REFERENCES users(id),
                resolution_note TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_iic_connection_id ON interop_identity_conflicts(connection_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_iic_resolved ON interop_identity_conflicts(resolved)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS interop_terminology_mappings (
                id SERIAL PRIMARY KEY,
                connection_id INTEGER NOT NULL REFERENCES interop_connections(id) ON DELETE CASCADE,
                source_system VARCHAR,
                source_code VARCHAR,
                source_display VARCHAR,
                target_canonical_name VARCHAR,
                target_display_name VARCHAR,
                target_category VARCHAR,
                target_unit VARCHAR,
                mapping_type VARCHAR NOT NULL DEFAULT 'pending_review',
                status VARCHAR NOT NULL DEFAULT 'pending',
                frequency_seen INTEGER NOT NULL DEFAULT 1,
                example_json TEXT,
                created_at VARCHAR NOT NULL,
                approved_at VARCHAR,
                approved_by_user_id INTEGER REFERENCES users(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_itm_connection_id ON interop_terminology_mappings(connection_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_itm_source_code ON interop_terminology_mappings(source_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_itm_status ON interop_terminology_mappings(status)"))
        # Additive columns on the pre-existing documents/lab_results tables —
        # both null for every upload; only interop's own sync path sets them.
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_connection_id INTEGER REFERENCES interop_connections(id) ON DELETE SET NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_source_connection_id ON documents(source_connection_id)"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS source_connection_id INTEGER REFERENCES interop_connections(id) ON DELETE SET NULL"))
        conn.execute(text("ALTER TABLE lab_results ADD COLUMN IF NOT EXISTS external_observation_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lab_results_source_connection_id ON lab_results(source_connection_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lab_results_external_observation_id ON lab_results(external_observation_id)"))

        conn.commit()

# run_migrations() is intentionally NOT called here anymore — see this
# function's own module-level comment above (schema is now Alembic-
# managed). Kept as a defined-but-uncalled function for historical
# reference only.

# These origins are always allowed regardless of any env var setting.
# FRONTEND_ORIGINS (comma-separated) is additive — it can add staging/preview
# URLs on top, but it cannot remove the production URL.
_ALWAYS_ALLOWED_ORIGINS = [
    "https://app.bragi.health",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
]
_extra_origins = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if o.strip()
]
# dict.fromkeys preserves insertion order and deduplicates.
frontend_origins = list(dict.fromkeys(_ALWAYS_ALLOWED_ORIGINS + _extra_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Explicit header list avoids wildcard edge-cases with allow_credentials=True.
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Baseline response headers — see docs/security/THREAT_MODEL.md.

    This is a JSON API (the browser-rendered surface is the separate
    Next.js frontend, which sets its own CSP/frame-ancestors in
    next.config.ts), so the headers here are the ones that matter
    regardless of content type: no MIME-sniffing, no referrer leakage
    to third parties, HSTS on the real production host, and a defensive
    frame-ancestors/CSP in case any endpoint ever returns HTML (an error
    page, FastAPI's own /docs, etc.) rather than JSON.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
    )
    # Defense-in-depth only — this API never intentionally serves HTML for
    # a browser to render (uploaded documents are served with their own
    # content_type via FileResponse, not text/html), so a restrictive
    # default-src here costs nothing for the real JSON responses and only
    # matters if something unexpected (an error page, /docs) is loaded
    # directly.
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    # Render terminates TLS in front of this app; HSTS is safe to set
    # unconditionally since there is no legitimate plain-HTTP use of this
    # API (frontend_origins above are all HTTPS in production).
    if os.getenv("ENVIRONMENT", "production").lower() != "development":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# File-upload hardening — see docs/security/THREAT_MODEL.md "malicious
# upload." Every format the product actually offers today (the frontend's
# getFileBadge()/accept list): PDF, common raster images, and
# doc/docx (accepted even though no current extraction path reads them,
# to avoid narrowing an already-advertised upload capability). Nothing
# else — in particular, no executable/script/archive extension is ever
# accepted, regardless of what Content-Type a client claims.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".doc", ".docx",
}
# Real byte-signature ("magic number") prefixes for the formats above that
# have one — a client-supplied filename/Content-Type can lie, but the
# actual first bytes of the file are real. doc/docx aren't included: doc
# is an OLE/CFB container and docx is a zip, both crossing into "worth a
# real parsing library, not a hand-rolled prefix check" territory — their
# risk is already bounded by the extension allowlist above plus the
# separate size cap, so this is intentionally scoped to formats a simple,
# unambiguous prefix genuinely identifies.
UPLOAD_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),  # full container check (RIFF....WEBP) below
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024


def _validate_upload_extension(original_filename: str) -> str:
    """Returns the lowercased, validated extension or raises 400. Extension
    is what decides ACCEPT/REJECT — Content-Type is client-supplied and
    only used later for the response's Content-Type header (unchanged
    behavior), never for this decision."""
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or '(none)'}'. Allowed: {allowed}.",
        )
    return suffix


async def _read_and_validate_upload(file: UploadFile, suffix: str) -> bytes:
    """Reads the whole upload into memory, enforcing the size cap while
    reading (never trusts a Content-Length header, which a client can
    misstate) and, where a real signature exists for this extension,
    verifying the first bytes actually match it — a spoofed extension on
    an unrelated file type is rejected before ever touching disk."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB upload limit.",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    signatures = UPLOAD_MAGIC_BYTES.get(suffix)
    if signatures:
        if suffix == ".webp":
            valid = data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        else:
            valid = any(data.startswith(sig) for sig in signatures)
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"File content doesn't match its '{suffix}' extension.",
            )
    return data

# Bounded concurrency for multi-file batch uploads (POST /upload/batch): a
# batch's files are dispatched to this pool instead of FastAPI's
# BackgroundTasks, which runs tasks strictly one-at-a-time in-process — a
# fast file (e.g. a 1-page prescription) had to wait for every earlier file
# in the batch to fully finish (each making several real Reducto HTTP
# calls) before it even started. A small fixed pool gives real, bounded
# parallelism — not unbounded concurrent Reducto requests — while
# process_upload_job stays exactly as safe to call from a worker thread as
# it already was from BackgroundTasks (it opens its own SessionLocal()
# per call; no shared mutable state between jobs).
UPLOAD_JOB_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("UPLOAD_JOB_CONCURRENCY", "3")), thread_name_prefix="upload-job")

ALLOWED_SECTIONS = {
    "notes",
    "bloodwork",
    "discharge_summary",
    "medications",
    "scans",
    "hospitalizations",
    "other",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        user_id_int = int(user_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(models.User).filter(models.User.id == user_id_int).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.deleted_at:
        # Soft-deleted (doctor/admin self-deletion — see
        # BRAGI_SECURITY_GDPR_PLAN.md §19/Priority 8): the row still
        # exists (clinical/audit records reference it) but the account
        # itself must behave as gone for every authorization purpose —
        # including a JWT issued before the deletion that hasn't expired
        # yet, which is exactly what this check catches.
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_role(*allowed_roles):
    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return dependency


def serialize_user(user):
    if not user:
        return None

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "department": user.department,
        "hospital_name": user.hospital_name,
        "doctor_type": user.doctor_type,
    }


def add_audit_log(
    db: Session,
    document_id: int,
    action: str,
    actor: str | None = None,
    details: str | None = None,
) -> None:
    log = models.AuditLog(
        document_id=document_id,
        action=action,
        actor=actor,
        timestamp=now_iso(),
        details=details,
    )
    db.add(log)


def get_patient_for_user(db: Session, user_id: int):
    return db.query(models.Patient).filter(models.Patient.linked_user_id == user_id).first()


def ensure_patient_for_user(db: Session, user):
    patient = get_patient_for_user(db, user.id)

    if patient:
        _ensure_patient_code(db, patient.id)
        return patient

    patient = models.Patient(
        linked_user_id=user.id,
        full_name=user.full_name,
        date_of_birth=None,
        age=None,
        sex=None,
        cnp=None,
        patient_identifier=None,
        public_id=generate_public_id("brg-pt"),
    )

    db.add(patient)
    db.commit()
    db.refresh(patient)
    _ensure_patient_code(db, patient.id)
    return patient


def _ensure_patient_code(db: Session, patient_id: int) -> str:
    existing = db.query(models.PatientCarePartnerCode).filter(
        models.PatientCarePartnerCode.patient_id == patient_id
    ).first()
    if existing:
        return existing.code
    code = _generate_unique_care_partner_code(db)
    record = models.PatientCarePartnerCode(patient_id=patient_id, code=code, created_at=now_iso())
    db.add(record)
    db.commit()
    return code

    return patient


def doctor_has_patient_access(db: Session, doctor_user_id: int, patient_id: int) -> bool:
    return (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
            models.DoctorPatientAccess.patient_id == patient_id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .first()
        is not None
    )


def can_access_patient(db: Session, current_user, patient_id: int) -> bool:
    if current_user.role == "admin":
        return True

    if current_user.role == "doctor":
        return doctor_has_patient_access(db, current_user.id, patient_id)

    if current_user.role == "patient":
        patient = get_patient_for_user(db, current_user.id)
        return patient is not None and patient.id == patient_id

    # care_partners have no general patient record access; document-level access
    # is checked separately via care_partner_can_access_document
    return False


def care_partner_can_access_document(db: Session, care_partner_user_id: int, document_id: int) -> bool:
    return (
        db.query(models.SharedStructuredPage)
        .filter(
            models.SharedStructuredPage.care_partner_user_id == care_partner_user_id,
            models.SharedStructuredPage.document_id == document_id,
        )
        .first()
        is not None
    )


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_unique_care_partner_code(db: Session) -> str:
    for _ in range(20):
        code = (
            "BW-"
            + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
            + "-"
            + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        )
        exists = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.code == code)
            .first()
        )
        if not exists:
            return code
    raise HTTPException(status_code=500, detail="Could not generate unique code.")


def lab_flag_is_abnormal(flag: str | None) -> bool:
    if not flag:
        return False

    normalized = str(flag).strip().lower()

    return normalized not in {
        "",
        "normal",
        "none",
        "n",
        "ok",
        "within range",
    }


def document_has_abnormal_labs(db: Session, document_id: int) -> bool:
    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document_id).all()
    return any(lab_flag_is_abnormal(lab.flag) for lab in labs)


def doctor_reviewed_document(db: Session, doctor_user_id: int | None, document_id: int) -> bool:
    if not doctor_user_id:
        return False

    return (
        db.query(models.DoctorDocumentReview)
        .filter(
            models.DoctorDocumentReview.doctor_user_id == doctor_user_id,
            models.DoctorDocumentReview.document_id == document_id,
        )
        .first()
        is not None
    )


def mark_doctor_reviewed_document(db: Session, doctor_user_id: int, document_id: int) -> None:
    existing = (
        db.query(models.DoctorDocumentReview)
        .filter(
            models.DoctorDocumentReview.doctor_user_id == doctor_user_id,
            models.DoctorDocumentReview.document_id == document_id,
        )
        .first()
    )

    if existing:
        return

    review = models.DoctorDocumentReview(
        doctor_user_id=doctor_user_id,
        document_id=document_id,
        reviewed_at=now_iso(),
    )
    db.add(review)


def get_best_document_date(document) -> str | None:
    return (
        document.test_date
        or document.collected_on
        or document.reported_on
        or document.generated_on
        or document.registered_on
        or document.created_at
    )


def lab_value_to_float(value) -> float | None:
    if value is None:
        return None

    cleaned = str(value).strip().lower()
    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("−", "-")
    cleaned = cleaned.replace("—", "-").replace("–", "-")

    if cleaned in {"", "-", "--", "---", "nil", "n/a", "na", "null", "none"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


def serialize_lab_result(lab):
    return {
        "id": lab.id,
        "raw_test_name": lab.raw_test_name,
        "canonical_name": lab.canonical_name,
        "display_name": lab.display_name,
        "category": lab.category,
        "source_section": lab.source_section,
        "value": lab.value,
        "flag": lab.flag,
        "reference_range": lab.reference_range,
        "unit": lab.unit,
        # Provenance: how raw_test_name -> canonical/display_name was
        # resolved (see app/services/lab_resolver.py). Never displayed
        # prominently in Analize itself — for provenance/debugging surfaces.
        "normalization_confidence": lab.normalization_confidence,
        "normalization_method": lab.normalization_method,
    }


def serialize_document_card(db: Session, document, current_user=None) -> dict:
    uploaded_by = serialize_user(document.uploaded_by_user) if document.uploaded_by_user else None
    has_abnormal = document_has_abnormal_labs(db, document.id)

    reviewed_by_current_doctor = False
    if current_user and current_user.role == "doctor":
        reviewed_by_current_doctor = doctor_reviewed_document(db, current_user.id, document.id)

    note_preview = None
    if document.note_body:
        note_preview = document.note_body[:180] + ("..." if len(document.note_body) > 180 else "")

    return {
        "id": document.id,
        "public_id": document.public_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "report_name": document.report_name,
        "report_type": document.report_type,
        "lab_name": document.lab_name,
        "sample_type": document.sample_type,
        "referring_doctor": document.referring_doctor,
        "test_date": document.test_date,
        "collected_on": document.collected_on,
        "reported_on": document.reported_on,
        "registered_on": document.registered_on,
        "generated_on": document.generated_on,
        "created_at": document.created_at,
        "section": document.section,
        "document_type": document.document_type,
        "parent_document_id": document.parent_document_id,
        "page_range_start": document.page_range_start,
        "page_range_end": document.page_range_end,
        "is_verified": bool(document.is_verified),
        "has_abnormal": has_abnormal,
        "has_abnormal_labs": has_abnormal,
        "reviewed_by_current_doctor": reviewed_by_current_doctor,
        "uploaded_by": uploaded_by,
        "note_preview": note_preview,
        "can_edit_note": (
            document.section == "notes"
            and current_user is not None
            and document.uploaded_by_user_id == current_user.id
        ),
    }


def serialize_patient_event(event) -> dict:
    doctor = event.doctor_user

    return {
        "id": event.id,
        "patient_id": event.patient_id,
        "doctor_user_id": event.doctor_user_id,
        "event_type": event.event_type,
        "status": event.status,
        "title": event.title,
        "description": event.description,
        "hospital_name": event.hospital_name,
        "department": event.department,
        "admitted_at": event.admitted_at,
        "discharged_at": event.discharged_at,
        "doctor_name": doctor.full_name if doctor else None,
    }


def serialize_doctor_access(link) -> dict:
    doctor = link.doctor_user

    return {
        "doctor_user_id": link.doctor_user_id,
        "doctor_name": doctor.full_name if doctor else "",
        "doctor_email": doctor.email if doctor else "",
        "department": doctor.department if doctor else None,
        "hospital_name": doctor.hospital_name if doctor else None,
        "granted_at": link.granted_at,
    }


def build_patient_profile_response(db: Session, patient, current_user) -> dict:
    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient.id)
        .order_by(models.Document.id.desc())
        .all()
    )

    grouped_documents = {
        "notes": [],
        "bloodwork": [],
        "discharge_summary": [],
        "medications": [],
        "scans": [],
        "hospitalizations": [],
        "other": [],
    }

    for document in documents:
        section = document.section if document.section in grouped_documents else "other"
        grouped_documents[section].append(serialize_document_card(db, document, current_user))

    events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient.id)
        .order_by(models.PatientEvent.admitted_at.desc())
        .all()
    )

    doctor_access = [serialize_doctor_access(link) for link in patient.doctor_access_links]

    code_record = db.query(models.PatientCarePartnerCode).filter(
        models.PatientCarePartnerCode.patient_id == patient.id
    ).first()

    # Full CNP is only returned to the patient viewing their own profile.
    # A doctor/admin viewing someone else's profile through this same
    # response shape (GET /patients/{id}/profile) gets a masked value —
    # the frontend doesn't need the real value merely because the model
    # has it, and no identity-matching logic depends on this response
    # (that comparison happens server-side against the uploaded
    # document's own extracted CNP, not the frontend-supplied value).
    is_self = bool(current_user) and current_user.role == "patient" and patient.linked_user_id == current_user.id
    cnp_out = patient.cnp if is_self else _mask_cnp(patient.cnp)

    return {
        "patient": {
            "id": patient.id,
            "public_id": patient.public_id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            "cnp": cnp_out,
            "patient_identifier": patient.patient_identifier,
            "care_partner_code": code_record.code if code_record else None,
        },
        "sections": grouped_documents,
        "doctor_access": doctor_access,
        "events": [serialize_patient_event(event) for event in events],
    }

def get_document_payload(db: Session, document, labs, audit_logs, current_user=None):
    uploaded_by = serialize_user(document.uploaded_by_user) if document.uploaded_by_user else None

    original_layout = {}
    original_layout_json = getattr(document, "original_layout_json", None)

    if original_layout_json:
        try:
            original_layout = json.loads(original_layout_json or "{}")
        except Exception:
            original_layout = {}

    has_abnormal = document_has_abnormal_labs(db, document.id)

    reviewed_by_current_doctor = False
    if current_user and current_user.role == "doctor":
        reviewed_by_current_doctor = doctor_reviewed_document(db, current_user.id, document.id)

    structured_sections = {}
    if document.structured_sections:
        try:
            structured_sections = json.loads(document.structured_sections).get("sections") or {}
        except Exception:
            structured_sections = {}

    parsed_content = None
    if document.parsed_content:
        try:
            parsed_content = json.loads(document.parsed_content)
        except Exception:
            parsed_content = None

    return {
        "document_id": document.id,
        "id": document.id,
        "patient_id": document.patient_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "saved_to": document.saved_to,
        "section": document.section,
        "document_type": document.document_type,
        "parent_document_id": document.parent_document_id,
        "page_range_start": document.page_range_start,
        "page_range_end": document.page_range_end,
        "classification_status": document.classification_status,
        "identity_status": document.identity_status,
        "structured_sections": structured_sections,
        "parsed_content": parsed_content,
        "uploaded_by_user_id": document.uploaded_by_user_id,
        "uploaded_by": uploaded_by,
        "extracted_text": document.extracted_text or "",
        "original_layout": original_layout,
        "parsed_data": {
            "patient_name": document.patient_name,
            "date_of_birth": document.date_of_birth,
            "age": document.age,
            "sex": document.sex,
            # Full value only for roles that can act on identity
            # review/correction (patient/doctor/admin); a care_partner
            # only ever has read access to a specific shared document and
            # has no identity-matching workflow that needs it.
            "cnp": document.cnp if not (current_user and current_user.role == "care_partner") else _mask_cnp(document.cnp),
            "patient_identifier": document.patient_identifier,
            "lab_name": document.lab_name,
            "sample_type": document.sample_type,
            "referring_doctor": document.referring_doctor,
            "report_name": document.report_name,
            "report_type": document.report_type,
            "source_language": document.source_language,
            "test_date": document.test_date,
            "collected_on": document.collected_on,
            "reported_on": document.reported_on,
            "registered_on": document.registered_on,
            "generated_on": document.generated_on,
            "note_body": document.note_body,
            "is_verified": bool(document.is_verified),
            "verified_by": document.verified_by,
            "verified_at": document.verified_at,
            "last_edited_at": document.last_edited_at,
            "created_at": document.created_at,
            "has_abnormal": has_abnormal,
            "has_abnormal_labs": has_abnormal,
            "reviewed_by_current_doctor": reviewed_by_current_doctor,
            "labs": [serialize_lab_result(lab) for lab in labs],
            "audit_logs": [
                {
                    "action": log.action,
                    "actor": log.actor,
                    "timestamp": log.timestamp,
                    "details": log.details,
                }
                for log in audit_logs
            ],
        },
    }

def serialize_upload_job(job) -> dict:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "patient_id": job.patient_id,
        "section": job.section if job.section != AUTO_CLASSIFY_SECTION else None,
        "filename": job.filename,
        "content_type": job.content_type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "document_id": job.document_id,
        "document_type": job.document_type,
        "classification_status": job.classification_status,
        "classification_confidence": job.classification_confidence,
        "identity_status": job.identity_status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _finish_mixed_reducto_upload(
    db,
    job: "models.UploadJob",
    user: "models.User",
    patient: "models.Patient",
    file_path: Path,
    split_result,
) -> None:
    """A single upload that real Reducto Split found to contain multiple
    logically separate documents (see BRAGI_REDUCTO_PLAN.md §5). The
    ORIGINAL file is preserved untouched as a parent Document; each
    section becomes its own child Document, sliced from the parent's
    pages purely to give Reducto a clean single-section input (see
    app.services.pdf_split) — every child's `saved_to` still points at the
    parent's real file, and evidence page numbers are remapped back to the
    parent's original page numbers, so "View original" always opens the
    real source at the real page.

    Identity is checked exactly once for the whole physical document
    (it's one piece of paper/one file, one patient) — never bypassed just
    because Reducto found multiple sections in it.
    """
    from app.services import pdf_split

    try:
        identity_fields = reducto_extraction.extract_identity(split_result.file_id)
    except ReductoError as error:
        identity_fields = {}
        print(f"UPLOAD JOB {job.id}: Reducto identity extract failed for split document: {error}")

    if job.identity_override:
        identity_result = IdentityCheckResult(
            status="matched_override",
            reasons=["Manually confirmed by the uploader after a mismatch/uncertainty review."],
        )
    else:
        identity_result = check_patient_identity(
            patient_full_name=patient.full_name,
            patient_dob=patient.date_of_birth,
            patient_cnp=patient.cnp,
            patient_identifier=patient.patient_identifier,
            extracted_full_name=identity_fields.get("patient_name"),
            extracted_dob=identity_fields.get("date_of_birth"),
            extracted_cnp=identity_fields.get("cnp"),
            extracted_patient_identifier=identity_fields.get("patient_identifier"),
        )

    job.identity_status = identity_result.status

    if identity_result.status == NEEDS_CONFIRMATION and not job.identity_override:
        job.status = "needs_identity_confirmation"
        job.progress = 60
        job.message = "; ".join(identity_result.reasons) or "Please confirm this document belongs to you."
        db.commit()
        return

    section_summary = ", ".join(
        DOCUMENT_TYPE_LABELS.get(s.document_type, {}).get("en", s.name) if s.document_type else s.name
        for s in split_result.sections
        if s.pages
    )

    if identity_result.status == MISMATCH:
        quarantined_document = models.Document(
            patient_id=None,
            intended_patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section="other",
            filename=job.filename,
            content_type=job.content_type,
            saved_to=job.saved_to,
            extracted_text=f"[Split into {len(split_result.sections)} sections: {section_summary}]",
            file_sha256=job.file_sha256,
            report_name=f"Mixed upload ({section_summary})",
            report_type="mixed_batch_source",
            identity_status=MISMATCH,
            review_status="quarantined",
            is_verified=False,
            created_at=now_iso(),
            public_id=generate_public_id("brg-doc"),
        )
        db.add(quarantined_document)
        db.flush()
        add_audit_log(
            db=db, document_id=quarantined_document.id, action="quarantined", actor="system",
            details=f"Identity mismatch for split upload {job.filename}: {'; '.join(identity_result.reasons)}",
        )
        job.status = "quarantined"
        job.document_id = quarantined_document.id
        job.progress = 100
        job.message = "This document appears to belong to a different patient and has been set aside for review."
        job.finished_at = now_iso()
        db.commit()
        return

    if identity_fields.get("patient_name") and not patient.full_name:
        patient.full_name = identity_fields["patient_name"]
    if identity_fields.get("date_of_birth") and not patient.date_of_birth:
        patient.date_of_birth = identity_fields["date_of_birth"]
    if identity_fields.get("cnp") and not patient.cnp:
        patient.cnp = identity_fields["cnp"]
    if identity_fields.get("patient_identifier") and not patient.patient_identifier:
        patient.patient_identifier = identity_fields["patient_identifier"]

    parent_document = models.Document(
        patient_id=patient.id,
        uploaded_by_user_id=user.id,
        section="other",
        filename=job.filename,
        content_type=job.content_type,
        saved_to=job.saved_to,
        extracted_text=f"Original upload, split by Reducto into {len(split_result.sections)} document(s): {section_summary}.",
        file_sha256=job.file_sha256,
        identity_status=identity_result.status,
        patient_name=identity_fields.get("patient_name") or patient.full_name,
        date_of_birth=identity_fields.get("date_of_birth") or patient.date_of_birth,
        cnp=identity_fields.get("cnp") or patient.cnp,
        patient_identifier=identity_fields.get("patient_identifier") or patient.patient_identifier,
        report_name=f"Original upload ({section_summary})",
        report_type="mixed_batch_source",
        classification_source="reducto",
        is_verified=False,
        created_at=now_iso(),
        public_id=generate_public_id("brg-doc"),
    )
    db.add(parent_document)
    db.flush()

    add_audit_log(
        db=db, document_id=parent_document.id, action="split_detected", actor="reducto",
        details=f"Reducto Split found {len(split_result.sections)} section(s): {section_summary}.",
    )

    child_ids: list[int] = []

    for section in split_result.sections:
        if not section.pages or section.document_type is None:
            continue

        # Maps a 1-indexed page within the slice back to the ORIGINAL
        # document's real page number — a plain offset would be wrong for
        # a non-contiguous section (e.g. pages [1, 2, 5]).
        original_pages = sorted(section.pages)
        slice_path = None

        try:
            slice_path = pdf_split.slice_pdf_pages(
                file_path, section.pages, UPLOAD_DIR / "_split_tmp", suffix=section.name
            )
            slice_file_id = reducto_extraction.ReductoClient().upload(str(slice_path), filename=slice_path.name)

            document_type = section.document_type.value
            if document_type == "laboratory_results":
                child_pipeline_result = reducto_extraction.build_pipeline_result_labs(slice_file_id)
            elif document_type in READER_SECTION_KEYS:
                child_pipeline_result = reducto_extraction.build_pipeline_result_reader(slice_file_id, document_type)
            else:
                child_pipeline_result = {"extracted_text": "", "parsed_data": {"labs": []}, "warnings": []}
        except ReductoError as error:
            print(f"UPLOAD JOB {job.id}: split child extraction failed for section {section.name}: {error}")
            continue
        finally:
            if slice_path is not None:
                try:
                    slice_path.unlink(missing_ok=True)
                except OSError:
                    pass

        def _original_page(slice_local_page: int | None) -> int | None:
            if not slice_local_page or slice_local_page < 1 or slice_local_page > len(original_pages):
                return None
            return original_pages[slice_local_page - 1]

        # parsed_content blocks were parsed from the slice — remap their
        # page numbers back to the original document too, same as evidence
        # below, so they stay consistent with each other.
        if child_pipeline_result.get("parsed_content"):
            for block in child_pipeline_result["parsed_content"].get("blocks", []):
                block["page"] = _original_page(block.get("page"))

        child_parsed_data = child_pipeline_result.get("parsed_data") or {}

        child_document = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            parent_document_id=parent_document.id,
            page_range_start=min(section.pages),
            page_range_end=max(section.pages),
            section=legacy_section_for(section.document_type),
            filename=job.filename,
            content_type=job.content_type,
            saved_to=job.saved_to,  # the PARENT file — a child is a page-range view, not a copy
            extracted_text=child_pipeline_result.get("extracted_text") or "",
            note_body=child_pipeline_result.get("note_body"),
            identity_status=identity_result.status,
            patient_name=parent_document.patient_name,
            date_of_birth=parent_document.date_of_birth,
            cnp=parent_document.cnp,
            patient_identifier=parent_document.patient_identifier,
            report_name=child_parsed_data.get("report_name") or document_type.replace("_", " ").title(),
            report_type=child_parsed_data.get("report_type") or document_type,
            document_type=document_type,
            classification_status="classified" if section.confidence == "high" else "needs_confirmation",
            classification_confidence=1.0 if section.confidence == "high" else 0.5,
            classification_source="reducto",
            structured_sections=(
                json.dumps(child_pipeline_result["_reducto_structured_sections"], ensure_ascii=False)
                if child_pipeline_result.get("_reducto_structured_sections", {}).get("sections")
                else None
            ),
            parsed_content=(
                json.dumps(child_pipeline_result["parsed_content"], ensure_ascii=False)
                if child_pipeline_result.get("parsed_content")
                else None
            ),
            is_verified=False,
            created_at=now_iso(),
            public_id=generate_public_id("brg-doc"),
        )
        db.add(child_document)
        db.flush()
        child_ids.append(child_document.id)

        for lab in child_parsed_data.get("labs", []) or []:
            lab_result = models.LabResult(
                document_id=child_document.id,
                raw_test_name=lab.get("raw_test_name"),
                canonical_name=lab.get("canonical_name"),
                display_name=lab.get("display_name"),
                category=lab.get("category"),
                source_section=lab.get("source_section"),
                value=lab.get("value"),
                flag=lab.get("flag"),
                reference_range=lab.get("reference_range"),
                unit=lab.get("unit"),
                observation_datetime=child_parsed_data.get("collected_on") or child_parsed_data.get("reported_on"),
                institution=child_parsed_data.get("lab_name"),
                extraction_confidence=lab.get("confidence"),
                normalization_confidence=lab.get("normalization_confidence"),
                normalization_method=lab.get("normalization_method"),
            )
            db.add(lab_result)
            db.flush()

            evidence = lab.get("evidence")
            if evidence is not None:
                db.add(
                    models.SourceEvidence(
                        document_id=child_document.id,
                        lab_result_id=lab_result.id,
                        source_text=evidence.source_text,
                        page_number=_original_page(evidence.page),
                        bbox_x=evidence.bbox_x,
                        bbox_y=evidence.bbox_y,
                        bbox_width=evidence.bbox_width,
                        bbox_height=evidence.bbox_height,
                        row_bbox_x=evidence.row_bbox[0] if evidence.row_bbox else None,
                        row_bbox_y=evidence.row_bbox[1] if evidence.row_bbox else None,
                        row_bbox_width=evidence.row_bbox[2] if evidence.row_bbox else None,
                        row_bbox_height=evidence.row_bbox[3] if evidence.row_bbox else None,
                        extraction_confidence=evidence.confidence,
                        provider="reducto",
                        parser_version=reducto_extraction.PARSER_VERSION,
                        created_at=now_iso(),
                    )
                )

        add_audit_log(
            db=db, document_id=child_document.id, action="uploaded", actor=user.full_name,
            details=f"Split from {job.filename} (original pages {min(section.pages)}-{max(section.pages)}) as {document_type}.",
        )

    job.status = "done"
    job.progress = 100
    job.document_id = parent_document.id
    job.message = f"Split into {len(child_ids)} document(s): {section_summary}."
    job.finished_at = now_iso()
    db.commit()


def process_upload_job(job_id: int):
    db = SessionLocal()

    try:
        job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

        if not job:
            return

        job.status = "processing"
        job.progress = 10
        job.message = "Reading and structuring document..."
        job.started_at = now_iso()
        db.commit()

        user = db.query(models.User).filter(models.User.id == job.user_id).first()
        patient = db.query(models.Patient).filter(models.Patient.id == job.patient_id).first()

        if not user or not patient:
            job.status = "error"
            job.progress = 100
            job.message = "Upload failed."
            job.error = "Upload user or patient no longer exists."
            job.finished_at = now_iso()
            db.commit()
            return

        file_path = Path(job.saved_to)

        if not file_path.exists():
            print(f"UPLOAD JOB {job_id}: saved file not found at {job.saved_to}")
            job.status = "error"
            job.progress = 100
            job.message = "Upload failed."
            job.error = "Uploaded file could not be located for processing."
            job.finished_at = now_iso()
            db.commit()
            return

        # Security-scan pipeline boundary (Priority 9,
        # BRAGI_SECURITY_GDPR_PLAN.md §10 — see
        # app/services/security_scan.py and
        # docs/security/MALWARE_SCANNING_PLAN.md): a file that scans as
        # explicitly malicious never reaches SHA-256/duplicate detection,
        # Reducto, OpenAI, or any other clinical-processing step below —
        # it is quarantined here, before any of that runs. A
        # scan_unavailable verdict (no real scanner configured, or the
        # heuristic screen's narrow scope didn't apply) does NOT block —
        # uploads keep working exactly as before in any environment that
        # hasn't configured CLAMAV_HOST, per this plan's "never make the
        # app unusable" rule.
        scan_result = run_security_scan(file_path)
        if scan_result.blocks_processing:
            print(
                f"UPLOAD JOB {job_id}: security scan blocked processing — "
                f"provider={scan_result.provider} reason={scan_result.reason}"
            )
            job.status = "security_quarantined"
            job.progress = 100
            job.message = "This file could not be processed and has been set aside for security review."
            # Short, non-PHI marker (provider name only) — the durable
            # audit trail for WHY is the print() line above (server logs,
            # operator-only), not this user-visible field.
            job.error = f"security_scan:{scan_result.provider}"
            job.finished_at = now_iso()
            db.commit()
            return

        # Phase 2, Level 1 duplicate detection: identical file already on
        # this patient's record. Detect before spending any OCR/AI cost,
        # and never create a second Document/LabResult set for it.
        try:
            job.file_sha256 = compute_sha256(file_path)
        except Exception:
            job.file_sha256 = None

        if job.file_sha256:
            existing_document = (
                db.query(models.Document)
                .filter(
                    models.Document.patient_id == patient.id,
                    models.Document.file_sha256 == job.file_sha256,
                )
                .order_by(models.Document.id.asc())
                .first()
            )

            if existing_document:
                job.status = "duplicate"
                job.document_id = existing_document.id
                job.progress = 100
                job.message = "This file was already uploaded."
                job.finished_at = now_iso()
                db.commit()

                add_audit_log(
                    db=db,
                    document_id=existing_document.id,
                    action="duplicate_detected",
                    actor="system",
                    details=f"Re-upload of {job.filename} matched existing document {existing_document.id} by SHA-256.",
                )
                db.commit()
                return

        reducto_file_id = None

        if job.section == AUTO_CLASSIFY_SECTION:
            job.progress = 25
            job.message = "Identifying document type..."
            db.commit()

            provider, used_fallback, fallback_reason = get_extraction_provider()

            if provider.name == REDUCTO and provider.is_enabled():
                # Real Reducto Classify + Split, run CONCURRENTLY against the
                # same uploaded file (see reducto_extraction.
                # classify_and_check_split) — they're independent calls, and
                # benchmarking found Split costs ~7-10s even on a trivial
                # single-page document that turns out non-mixed, on top of
                # Classify's own ~3-4s. Running them in parallel bounds the
                # "identifying document type" wait by the slower of the two
                # instead of their sum. Any Reducto failure (auth/timeout/
                # malformed response/etc.) falls back to the legacy keyword
                # classifier rather than failing the whole upload — a
                # Reducto outage must never block classification.
                try:
                    stage_started = time.monotonic()
                    classification, split_result = reducto_extraction.classify_and_check_split(
                        str(file_path), filename=job.filename
                    )
                    reducto_file_id = classification.file_id
                    processing_meta = ProcessingMetadata(
                        provider=REDUCTO,
                        parser_version=reducto_extraction.PARSER_VERSION,
                        processing_time_ms=int((time.monotonic() - stage_started) * 1000),
                        confidence=classification.confidence,
                        reducto_file_id=reducto_file_id,
                    )

                    if split_result and split_result.is_mixed:
                        job.message = "Separating records..."
                        db.commit()
                        _finish_mixed_reducto_upload(db, job, user, patient, file_path, split_result)
                        return
                except ReductoError as reducto_error:
                    print(f"UPLOAD JOB {job_id}: Reducto classify failed, falling back to legacy_rules: {reducto_error}")
                    from app.services.extraction_provider import LegacyExtractionProvider

                    provider = LegacyExtractionProvider()
                    used_fallback = True
                    fallback_reason = f"Reducto classify failed: {reducto_error}"

            if reducto_file_id is None:
                # Legacy path (Reducto disabled, or just fell back above):
                # classification input is a plain-text OCR pass, independent
                # of any type-specific pipeline.
                try:
                    classification_ocr = ocr_extract_text(
                        file_path=file_path, filename=job.filename, temp_dir=UPLOAD_DIR
                    )
                    classification_text = classification_ocr.get("text") or ""
                except Exception:
                    print(f"UPLOAD JOB {job_id}: classification OCR pass failed:")
                    print(traceback.format_exc())
                    classification_text = ""

                classification, processing_meta = provider.classify(classification_text)

            job.document_type = classification.document_type.value
            job.classification_status = classification.status
            job.classification_confidence = classification.confidence
            job.classification_source = (
                f"{processing_meta.provider}_fallback" if used_fallback else processing_meta.provider
            )

            if classification.status == "needs_confirmation":
                job.status = "needs_confirmation"
                job.progress = 30
                job.message = "We're not sure what type of document this is. Please confirm."
                db.commit()
                return

            job.section = legacy_section_for(classification.document_type)
            db.commit()

        # Real Reducto Extract, only for the document types it's wired up
        # for (laboratory_results + the narrative reader types) and only
        # when classification actually ran through Reducto this call. Falls
        # through to the existing legacy pipelines for everything else
        # (discharge_summary keeps its own dedicated pipeline; Reducto
        # disabled; or a Reducto extract failure) — never a hard failure.
        pipeline_result = None

        # Set BEFORE the (slow, ~15-30s) extraction call runs, not after —
        # otherwise the frontend shows a stale "Identifying document
        # type..."/prior message for the entire extraction phase, then
        # jumps straight to "Saving structured record..." once it's already
        # done. See BRAGI_REDUCTO_PLAN.md's classification-latency fix.
        if reducto_file_id and job.document_type == "laboratory_results":
            job.progress = 45
            job.message = "Extracting results..."
        elif reducto_file_id and job.document_type in READER_SECTION_KEYS:
            job.progress = 45
            job.message = "Reading document..."
        else:
            job.progress = 45
            job.message = "Processing document..."
        db.commit()

        if reducto_file_id and job.document_type == "laboratory_results":
            try:
                pipeline_result = reducto_extraction.build_pipeline_result_labs(reducto_file_id)
            except ReductoError as reducto_error:
                print(f"UPLOAD JOB {job_id}: Reducto lab extract failed, falling back to legacy pipeline: {reducto_error}")
        elif reducto_file_id and job.document_type in READER_SECTION_KEYS:
            try:
                pipeline_result = reducto_extraction.build_pipeline_result_reader(reducto_file_id, job.document_type)
            except ReductoError as reducto_error:
                print(f"UPLOAD JOB {job_id}: Reducto reader extract failed, falling back to legacy pipeline: {reducto_error}")

        if pipeline_result is None:
            if job.section == "discharge_summary":
                pipeline_result = process_uploaded_discharge_summary(
                    file_path=file_path,
                    filename=job.filename,
                )
            else:
                pipeline_result = process_uploaded_document(
                    file_path=file_path,
                    filename=job.filename,
                    section=job.section,
                    temp_dir=UPLOAD_DIR,
                )

        job.progress = 70
        job.message = "Checking patient..."
        db.commit()

        parsed_data = (
            pipeline_result.get("parsed_data")
            or pipeline_result.get("payload")
            or {}
        )

        labs = parsed_data.get("labs") or pipeline_result.get("labs") or []

        extracted_text = (
            pipeline_result.get("extracted_text")
            or parsed_data.get("extracted_text")
            or ""
        )

        note_body = (
            pipeline_result.get("note_body")
            or parsed_data.get("note_body")
            or extracted_text
            or None
        )

        report_name = (
            parsed_data.get("report_name")
            or pipeline_result.get("report_name")
            or ("Discharge summary" if job.section == "discharge_summary" else job.section.replace("_", " ").title())
        )

        report_type = (
            parsed_data.get("report_type")
            or pipeline_result.get("report_type")
            or ("discharge_summary" if job.section == "discharge_summary" else job.section)
        )

        source_language = (
            parsed_data.get("source_language")
            or pipeline_result.get("source_language")
        )

        # Phase 2 — patient identity check. Never let extraction silently
        # overwrite the patient's blank identity fields, or feed clinical
        # data into the wrong patient's record, without this passing.
        if job.identity_override:
            identity_result = IdentityCheckResult(
                status="matched_override",
                reasons=["Manually confirmed by the uploader after a mismatch/uncertainty review."],
            )
        else:
            identity_result = check_patient_identity(
                patient_full_name=patient.full_name,
                patient_dob=patient.date_of_birth,
                patient_cnp=patient.cnp,
                patient_identifier=patient.patient_identifier,
                extracted_full_name=parsed_data.get("patient_name"),
                extracted_dob=parsed_data.get("date_of_birth"),
                extracted_cnp=parsed_data.get("cnp"),
                extracted_patient_identifier=parsed_data.get("patient_identifier"),
            )

        job.identity_status = identity_result.status

        if identity_result.status == NEEDS_CONFIRMATION and not job.identity_override:
            # Ambiguous, not a clear mismatch — pause rather than guess.
            # Nothing is persisted yet; confirming re-runs this job from
            # scratch (same accepted shortcut as classification
            # needs_confirmation — see BRAGI_REDUCTO_PLAN.md known issues).
            job.status = "needs_identity_confirmation"
            job.progress = 60
            job.message = "; ".join(identity_result.reasons) or "Please confirm this document belongs to you."
            db.commit()
            return

        if identity_result.status == MISMATCH:
            quarantined_document = models.Document(
                patient_id=None,
                intended_patient_id=patient.id,
                uploaded_by_user_id=user.id,
                section=job.section,
                filename=job.filename,
                content_type=job.content_type,
                saved_to=job.saved_to,
                extracted_text=extracted_text,
                file_sha256=job.file_sha256,
                patient_name=parsed_data.get("patient_name"),
                date_of_birth=parsed_data.get("date_of_birth"),
                age=parsed_data.get("age"),
                sex=parsed_data.get("sex"),
                cnp=parsed_data.get("cnp"),
                patient_identifier=parsed_data.get("patient_identifier"),
                report_name=report_name,
                report_type=report_type,
                source_language=source_language,
                document_type=job.document_type,
                classification_status=job.classification_status,
                classification_confidence=job.classification_confidence,
                classification_source=job.classification_source,
                identity_status=MISMATCH,
                review_status="quarantined",
                is_verified=False,
                created_at=now_iso(),
                public_id=generate_public_id("brg-doc"),
            )
            db.add(quarantined_document)
            db.flush()

            add_audit_log(
                db=db,
                document_id=quarantined_document.id,
                action="quarantined",
                actor="system",
                details=f"Identity mismatch for {job.filename}: {'; '.join(identity_result.reasons)}",
            )

            job.status = "quarantined"
            job.document_id = quarantined_document.id
            job.progress = 100
            job.message = "This document appears to belong to a different patient and has been set aside for review."
            job.finished_at = now_iso()
            db.commit()
            return

        # matched / insufficient_identity / matched_override: safe to fill
        # blank patient fields and proceed with full processing.
        if parsed_data.get("patient_name") and not patient.full_name:
            patient.full_name = parsed_data.get("patient_name")

        if parsed_data.get("date_of_birth") and not patient.date_of_birth:
            patient.date_of_birth = parsed_data.get("date_of_birth")

        if parsed_data.get("age") and not patient.age:
            patient.age = parsed_data.get("age")

        if parsed_data.get("sex") and not patient.sex:
            patient.sex = parsed_data.get("sex")

        if parsed_data.get("cnp") and not patient.cnp:
            patient.cnp = parsed_data.get("cnp")

        if parsed_data.get("patient_identifier") and not patient.patient_identifier:
            patient.patient_identifier = parsed_data.get("patient_identifier")

        document = models.Document(
            patient_id=patient.id,
            uploaded_by_user_id=user.id,
            section=job.section,
            filename=job.filename,
            content_type=job.content_type,
            saved_to=job.saved_to,

            extracted_text=extracted_text,
            file_sha256=job.file_sha256,
            identity_status=identity_result.status,

            patient_name=parsed_data.get("patient_name") or patient.full_name,
            date_of_birth=parsed_data.get("date_of_birth") or patient.date_of_birth,
            age=parsed_data.get("age") or patient.age,
            sex=parsed_data.get("sex") or patient.sex,
            cnp=parsed_data.get("cnp") or patient.cnp,
            patient_identifier=parsed_data.get("patient_identifier") or patient.patient_identifier,

            lab_name=parsed_data.get("lab_name"),
            sample_type=parsed_data.get("sample_type"),
            referring_doctor=parsed_data.get("referring_doctor"),

            report_name=report_name,
            report_type=report_type,
            source_language=source_language,

            test_date=parsed_data.get("test_date"),
            collected_on=parsed_data.get("collected_on") or pipeline_result.get("collected_on"),
            reported_on=parsed_data.get("reported_on") or pipeline_result.get("reported_on"),
            registered_on=parsed_data.get("registered_on"),
            generated_on=parsed_data.get("generated_on"),

            note_body=note_body,

            document_type=job.document_type,
            classification_status=job.classification_status,
            classification_confidence=job.classification_confidence,
            classification_source=job.classification_source,
            parsed_content=(
                json.dumps(pipeline_result["parsed_content"], ensure_ascii=False)
                if pipeline_result.get("parsed_content")
                else None
            ),

            is_verified=False,
            verified_by=None,
            verified_at=None,
            last_edited_at=None,
            created_at=now_iso(),
            public_id=generate_public_id("brg-doc"),
        )

        db.add(document)
        db.flush()

        job.progress = 85
        job.message = "Organizing..."
        db.commit()

        observation_datetime = (
            document.collected_on
            or document.test_date
            or document.reported_on
            or document.registered_on
        )
        linked_duplicate_count = 0

        for lab in labs:
            lab_result = models.LabResult(
                document_id=document.id,
                raw_test_name=lab.get("raw_test_name"),
                canonical_name=lab.get("canonical_name"),
                display_name=lab.get("display_name"),
                category=lab.get("category"),
                source_section=lab.get("source_section"),
                value=lab.get("value"),
                flag=lab.get("flag"),
                reference_range=lab.get("reference_range"),
                unit=lab.get("unit"),
                observation_datetime=observation_datetime,
                institution=document.lab_name,
                extraction_confidence=lab.get("confidence"),
                normalization_confidence=lab.get("normalization_confidence"),
                normalization_method=lab.get("normalization_method"),
            )

            # Phase 2, Level 3 duplicate-observation detection: same
            # patient + same canonical test + same observation date +
            # identical value + identical unit is treated as the same
            # real-world measurement rather than a second one. Exact-match
            # only, on purpose — false merging is worse than a harmless
            # extra row (see BRAGI_REDUCTO_PLAN.md).
            identity_key = (lab.get("canonical_name") or lab.get("raw_test_name") or "").strip().lower()
            duplicate_target = None

            if identity_key and observation_datetime and lab.get("value") is not None:
                duplicate_target = (
                    db.query(models.LabResult)
                    .join(models.Document, models.LabResult.document_id == models.Document.id)
                    .filter(
                        models.Document.patient_id == patient.id,
                        models.LabResult.duplicate_of_lab_result_id.is_(None),
                        models.LabResult.observation_datetime == observation_datetime,
                        models.LabResult.value == lab.get("value"),
                        models.LabResult.unit == lab.get("unit"),
                        func.lower(func.coalesce(models.LabResult.canonical_name, models.LabResult.raw_test_name))
                        == identity_key,
                    )
                    .order_by(models.LabResult.id.asc())
                    .first()
                )

            if duplicate_target:
                lab_result.duplicate_of_lab_result_id = duplicate_target.id
                linked_duplicate_count += 1

            db.add(lab_result)
            db.flush()

            source_text_parts = [
                str(part)
                for part in [lab.get("raw_test_name"), lab.get("value"), lab.get("unit"), lab.get("reference_range")]
                if part
            ]

            # Real bbox/page provenance when the lab came from Reducto
            # Extract (see reducto_extraction.py) — never fabricated for the
            # legacy pipeline, which has no coordinate data to offer.
            evidence = lab.get("evidence")
            source_text = " | ".join(source_text_parts) if source_text_parts else None
            if evidence is not None and evidence.source_text:
                source_text = evidence.source_text

            if source_text_parts or evidence is not None:
                db.add(
                    models.SourceEvidence(
                        document_id=document.id,
                        lab_result_id=duplicate_target.id if duplicate_target else lab_result.id,
                        source_text=source_text,
                        page_number=evidence.page if evidence else None,
                        bbox_x=evidence.bbox_x if evidence else None,
                        bbox_y=evidence.bbox_y if evidence else None,
                        bbox_width=evidence.bbox_width if evidence else None,
                        bbox_height=evidence.bbox_height if evidence else None,
                        row_bbox_x=(evidence.row_bbox[0] if evidence and evidence.row_bbox else None),
                        row_bbox_y=(evidence.row_bbox[1] if evidence and evidence.row_bbox else None),
                        row_bbox_width=(evidence.row_bbox[2] if evidence and evidence.row_bbox else None),
                        row_bbox_height=(evidence.row_bbox[3] if evidence and evidence.row_bbox else None),
                        extraction_confidence=lab.get("confidence"),
                        provider=job.classification_source or "legacy_pipeline",
                        parser_version=(reducto_extraction.PARSER_VERSION if evidence is not None else None),
                        created_at=now_iso(),
                    )
                )

        if linked_duplicate_count:
            add_audit_log(
                db=db,
                document_id=document.id,
                action="duplicate_observation_linked",
                actor="system",
                details=f"{linked_duplicate_count} lab row(s) matched existing observations by date/value/unit and were linked rather than duplicated.",
            )

        add_audit_log(
            db=db,
            document_id=document.id,
            action="uploaded",
            actor=user.full_name,
            details=f"Uploaded {job.filename} to {job.section}",
        )

        if job.document_type:
            add_audit_log(
                db=db,
                document_id=document.id,
                action="classification_completed",
                actor=job.classification_source or "system",
                details=(
                    f"Classified as {job.document_type} "
                    f"(status={job.classification_status}, confidence={job.classification_confidence})"
                ),
            )

        warnings = (
            pipeline_result.get("warnings")
            or parsed_data.get("warnings")
            or []
        )

        for warning in warnings:
            add_audit_log(
                db=db,
                document_id=document.id,
                action="processing_warning",
                actor="system",
                details=str(warning),
            )

        # Phase 4 — conservative structured extraction for document types
        # with no dedicated pipeline of their own. Best-effort: a failure
        # or missing OPENAI_API_KEY here must never fail the upload — the
        # Reader always has extracted_text as a fallback.
        if document.document_type in READER_SECTION_KEYS:
            try:
                # Reuse the Reducto reader extraction already done above
                # (build_pipeline_result_reader) instead of paying for a
                # second, redundant OpenAI vision call on the same file.
                # Only falls through to OpenAI when Reducto is disabled,
                # wasn't applicable, or genuinely returned nothing.
                reader_result = (pipeline_result or {}).get("_reducto_structured_sections")
                reader_actor = "reducto"

                if not reader_result or not reader_result.get("sections"):
                    reader_result = extract_structured_sections(
                        document_type=document.document_type,
                        file_path=file_path,
                        filename=job.filename,
                        content_type=job.content_type,
                    )
                    reader_actor = "legacy_openai_reader"

                if reader_result.get("sections"):
                    document.structured_sections = json.dumps(reader_result, ensure_ascii=False)
                    add_audit_log(
                        db=db,
                        document_id=document.id,
                        action="structured_extraction_completed",
                        actor=reader_actor,
                        details=f"Extracted {len(reader_result['sections'])} section(s) for {document.document_type}.",
                    )
                else:
                    for warning in reader_result.get("warnings", []):
                        add_audit_log(
                            db=db,
                            document_id=document.id,
                            action="processing_warning",
                            actor="system",
                            details=str(warning),
                        )
            except Exception:
                print(f"UPLOAD JOB {job_id}: structured reader extraction failed:")
                print(traceback.format_exc())

        job.status = "done"
        job.progress = 100
        job.message = f"{job.filename} was uploaded."
        job.document_id = document.id
        job.finished_at = now_iso()

        db.commit()

    except Exception as error:
        db.rollback()

        # Categorize by exception type for a safe, non-generic job.error —
        # never the raw exception text/traceback (could contain a file
        # path or similar), but specific enough that "provider is broken",
        # "our database had a problem", and "this document type needs
        # configuration we're missing" are distinguishable rather than one
        # indistinguishable "try again" for every failure mode. See
        # BRAGI_REDUCTO_PLAN.md's classification-latency/failure fix.
        category = "internal_error"
        user_message = "An error occurred during document processing. Please try again."

        if isinstance(error, ReductoError):
            category = f"reducto_{type(error).__name__}"
            user_message = "Document processing is temporarily unavailable. Please try again shortly."
        elif isinstance(error, SQLAlchemyError):
            category = "database_error"
            user_message = "A database error occurred while saving this document. Please try again."
        elif isinstance(error, RuntimeError) and "OPENAI_API_KEY" in str(error):
            category = "missing_openai_config"
            user_message = "This document type needs additional configuration that isn't available yet."

        print(f"UPLOAD JOB {job_id} ERROR: category={category} exception_type={type(error).__name__}")
        print(traceback.format_exc())

        try:
            job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

            if job:
                job.status = "error"
                job.progress = 100
                job.message = "Upload failed."
                job.error = user_message
                job.finished_at = now_iso()
                db.commit()

        except Exception:
            db.rollback()
            print(f"UPLOAD JOB {job_id}: failed to persist error state:")
            print(traceback.format_exc())

    finally:
        db.close()


PCP_DEPARTMENT_VALUES = frozenset([
    "pcp", "primary care", "family medicine", "family physician",
    "general practice", "gp", "doctor de familie", "medic de familie",
    "medicina de familie", "medicină de familie", "medicina familiala",
    "medicină familială",
])


def _normalize_doctor_type(doctor_type_input: str | None, department: str | None) -> str | None:
    if doctor_type_input:
        if doctor_type_input.lower() == "pcp":
            return "pcp"
        return "specialist"
    # Fall back to department sniffing for backwards compat
    if department:
        dept_lower = department.lower()
        for val in PCP_DEPARTMENT_VALUES:
            if val in dept_lower:
                return "pcp"
    return "specialist"


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str
    # 8 is the OWASP-recommended floor for a length-only policy (no
    # composition rules — composition requirements are no longer
    # recommended; length is the strongest single lever) — see
    # docs/security/THREAT_MODEL.md. No pre-existing account is affected;
    # this only gates new signups (and any future password-change/reset
    # flow) going forward.
    password: str = Field(min_length=8, max_length=256)
    role: str
    department: str | None = None
    hospital_name: str | None = None
    date_of_birth: str | None = None
    age: str | None = None
    sex: str | None = None
    cnp: str | None = None
    patient_identifier: str | None = None
    care_partner_code: str | None = None
    doctor_type: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LabResultUpdate(BaseModel):
    raw_test_name: str | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    category: str | None = None
    source_section: str | None = None
    value: str | None = None
    flag: str | None = None
    reference_range: str | None = None
    unit: str | None = None


class ParsedDataUpdate(BaseModel):
    patient_name: str | None = None
    date_of_birth: str | None = None
    age: str | None = None
    sex: str | None = None
    cnp: str | None = None
    patient_identifier: str | None = None
    lab_name: str | None = None
    sample_type: str | None = None
    referring_doctor: str | None = None
    report_name: str | None = None
    report_type: str | None = None
    source_language: str | None = None
    test_date: str | None = None
    collected_on: str | None = None
    reported_on: str | None = None
    registered_on: str | None = None
    generated_on: str | None = None
    note_body: str | None = None
    labs: list[LabResultUpdate] = Field(default_factory=list)


class DocumentUpdateRequest(BaseModel):
    parsed_data: ParsedDataUpdate
    editor_name: str | None = "Manual User"


class VerifyRequest(BaseModel):
    verifier_name: str | None = "Manual Reviewer"


class AssignmentCreateRequest(BaseModel):
    doctor_user_id: int
    patient_id: int


class AccessRequestCreateRequest(BaseModel):
    patient_id: int


class AccessRequestRespondRequest(BaseModel):
    status: str


class PatientEventCreateRequest(BaseModel):
    patient_id: int
    event_type: str = "hospitalization"
    status: str = "active"
    title: str
    description: str | None = None
    hospital_name: str | None = None
    department: str | None = None
    admitted_at: str
    discharged_at: str | None = None


@app.get("/")
def root():
    return {"message": "API is running"}


@app.get("/admin/ops/rate-limit-status")
def rate_limit_status(current_user=Depends(require_role("admin"))):
    """Read-only diagnostic so ops can confirm which rate-limit backend is
    actually active in a given environment — never inferred from an env
    var alone, since a misconfigured/unreachable Redis silently falls
    back to the in-memory (per-instance-only) backend. See
    docs/security/RATE_LIMITING.md."""
    from app.rate_limit import RATE_LIMIT_DISABLED, RATE_LIMIT_REDIS_URL, is_distributed

    return {
        "distributed": is_distributed(),
        "redis_configured": bool(RATE_LIMIT_REDIS_URL),
        "disabled": RATE_LIMIT_DISABLED,
    }


@app.post("/auth/signup")
def signup(
    payload: SignupRequest,
    db: Session = Depends(get_db),
    _rl=Depends(RateLimiter(limit=10, window_seconds=3600, key_prefix="signup")),
):
    if payload.role not in {"patient", "doctor", "admin", "care_partner", "emergency_worker"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(models.User).filter(models.User.email == payload.email).first()

    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    doctor_type = None
    if payload.role == "doctor":
        doctor_type = _normalize_doctor_type(payload.doctor_type, payload.department)

    user = models.User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
        hospital_name=payload.hospital_name,
        doctor_type=doctor_type,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    if payload.role == "patient":
        patient = models.Patient(
            linked_user_id=user.id,
            full_name=payload.full_name,
            date_of_birth=payload.date_of_birth,
            age=payload.age,
            sex=payload.sex,
            cnp=payload.cnp,
            patient_identifier=payload.patient_identifier,
            public_id=generate_public_id("brg-pt"),
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        _ensure_patient_code(db, patient.id)

    if payload.role == "care_partner":
        if not payload.care_partner_code:
            raise HTTPException(status_code=400, detail="Patient access code is required.")

        code_record = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.code == payload.care_partner_code.upper().strip())
            .first()
        )

        if not code_record:
            raise HTTPException(status_code=400, detail="Invalid patient access code.")

        link = models.CarePartnerPatientLink(
            care_partner_user_id=user.id,
            patient_id=code_record.patient_id,
            linked_at=now_iso(),
        )
        db.add(link)
        db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": serialize_user(user),
    }


@app.post("/auth/login")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rl=Depends(RateLimiter(limit=15, window_seconds=300, key_prefix="login")),
):
    user = db.query(models.User).filter(models.User.email == payload.email).first()

    # Always pays real bcrypt cost, whether or not `user` exists — see
    # verify_password_timing_safe's docstring.
    if not verify_password_timing_safe(payload.password, user.password_hash if user else None):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.deleted_at:
        # Soft-deleted account (doctor/admin self-deletion) — same generic
        # message as any other failed login, deliberately not
        # distinguished (no new enumeration signal).
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.role == "patient":
        ensure_patient_for_user(db, user)

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": serialize_user(user),
    }


@app.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    return serialize_user(current_user)


@app.get("/users/doctors")
def get_doctors(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctors = db.query(models.User).filter(models.User.role == "doctor").all()
    return [serialize_user(doctor) for doctor in doctors]


@app.get("/assignments")
def get_assignments(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    assignments = db.query(models.DoctorPatientAccess).all()
    results = []

    for assignment in assignments:
        doctor = db.query(models.User).filter(models.User.id == assignment.doctor_user_id).first()
        patient = db.query(models.Patient).filter(models.Patient.id == assignment.patient_id).first()
        granter = None

        if assignment.granted_by_user_id:
            granter = db.query(models.User).filter(models.User.id == assignment.granted_by_user_id).first()

        results.append(
            {
                "id": assignment.id,
                "doctor_user_id": assignment.doctor_user_id,
                "doctor_name": doctor.full_name if doctor else None,
                "doctor_email": doctor.email if doctor else None,
                "doctor_department": doctor.department if doctor else None,
                "doctor_hospital_name": doctor.hospital_name if doctor else None,
                "patient_id": assignment.patient_id,
                "patient_name": patient.full_name if patient else None,
                "granted_by_user_id": assignment.granted_by_user_id,
                "granted_by_name": granter.full_name if granter else None,
                "granted_at": assignment.granted_at,
            }
        )

    return results


@app.post("/assignments")
def create_assignment(
    payload: AssignmentCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctor = db.query(models.User).filter(models.User.id == payload.doctor_user_id).first()
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()

    if not doctor or doctor.role != "doctor":
        raise HTTPException(status_code=400, detail="Doctor user not found")

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    existing = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == payload.doctor_user_id,
            models.DoctorPatientAccess.patient_id == payload.patient_id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="Assignment already exists")

    assignment = models.DoctorPatientAccess(
        doctor_user_id=payload.doctor_user_id,
        patient_id=payload.patient_id,
        granted_by_user_id=current_user.id,
        granted_at=now_iso(),
        is_active=1,
    )

    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "id": assignment.id,
        "doctor_user_id": assignment.doctor_user_id,
        "patient_id": assignment.patient_id,
        "granted_by_user_id": assignment.granted_by_user_id,
        "granted_at": assignment.granted_at,
    }


@app.post("/access-requests")
def create_access_request(
    payload: AccessRequestCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if doctor_has_patient_access(db, current_user.id, payload.patient_id):
        raise HTTPException(status_code=400, detail="Doctor already has access")

    existing_pending = (
        db.query(models.DoctorPatientAccessRequest)
        .filter(
            models.DoctorPatientAccessRequest.doctor_user_id == current_user.id,
            models.DoctorPatientAccessRequest.patient_id == payload.patient_id,
            models.DoctorPatientAccessRequest.status == "pending",
        )
        .first()
    )

    if existing_pending:
        raise HTTPException(status_code=400, detail="Access request already pending")

    request = models.DoctorPatientAccessRequest(
        doctor_user_id=current_user.id,
        patient_id=payload.patient_id,
        requested_by_user_id=current_user.id,
        status="pending",
        requested_at=now_iso(),
    )

    db.add(request)
    db.commit()
    db.refresh(request)

    return {
        "id": request.id,
        "doctor_user_id": request.doctor_user_id,
        "patient_id": request.patient_id,
        "status": request.status,
        "requested_at": request.requested_at,
    }


@app.get("/my/access-requests")
def get_my_access_requests(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    requests = (
        db.query(models.DoctorPatientAccessRequest)
        .filter(models.DoctorPatientAccessRequest.patient_id == patient.id)
        .order_by(models.DoctorPatientAccessRequest.id.desc())
        .all()
    )

    results = []

    for req in requests:
        doctor = db.query(models.User).filter(models.User.id == req.doctor_user_id).first()
        results.append(
            {
                "id": req.id,
                "doctor_user_id": req.doctor_user_id,
                "doctor_name": doctor.full_name if doctor else None,
                "doctor_email": doctor.email if doctor else None,
                "doctor_department": doctor.department if doctor else None,
                "doctor_hospital_name": doctor.hospital_name if doctor else None,
                "status": req.status,
                "requested_at": req.requested_at,
                "responded_at": req.responded_at,
            }
        )

    return results


@app.post("/access-requests/{request_id}/respond")
def respond_to_access_request(
    request_id: int,
    payload: AccessRequestRespondRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    access_request = (
        db.query(models.DoctorPatientAccessRequest)
        .filter(models.DoctorPatientAccessRequest.id == request_id)
        .first()
    )

    if not access_request:
        raise HTTPException(status_code=404, detail="Access request not found")

    if access_request.patient_id != patient.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if access_request.status != "pending":
        raise HTTPException(status_code=400, detail="Request already handled")

    if payload.status not in {"approved", "denied"}:
        raise HTTPException(status_code=400, detail="Status must be approved or denied")

    access_request.status = payload.status
    access_request.responded_at = now_iso()
    access_request.responded_by_user_id = current_user.id

    if payload.status == "approved":
        existing_access = (
            db.query(models.DoctorPatientAccess)
            .filter(
                models.DoctorPatientAccess.doctor_user_id == access_request.doctor_user_id,
                models.DoctorPatientAccess.patient_id == access_request.patient_id,
            )
            .first()
        )

        if not existing_access:
            access = models.DoctorPatientAccess(
                doctor_user_id=access_request.doctor_user_id,
                patient_id=access_request.patient_id,
                granted_by_user_id=current_user.id,
                granted_at=now_iso(),
            )
            db.add(access)

    db.commit()
    db.refresh(access_request)

    return {
        "id": access_request.id,
        "status": access_request.status,
        "requested_at": access_request.requested_at,
        "responded_at": access_request.responded_at,
    }


@app.get("/patients")
def get_patients(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    if current_user.role == "admin":
        patients = db.query(models.Patient).all()
    else:
        assigned_patient_ids = [
            link.patient_id
            for link in db.query(models.DoctorPatientAccess)
            .filter(
                models.DoctorPatientAccess.doctor_user_id == current_user.id,
                models.DoctorPatientAccess.is_active == 1,
            )
            .all()
        ]

        if not assigned_patient_ids:
            return []

        patients = db.query(models.Patient).filter(models.Patient.id.in_(assigned_patient_ids)).all()

    return [
        {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            # List view: masked. Full CNP isn't needed to browse a patient
            # list, only to confirm identity on a specific record — see
            # build_patient_profile_response / get_document_payload.
            "cnp": _mask_cnp(patient.cnp),
            "patient_identifier": patient.patient_identifier,
        }
        for patient in patients
    ]

@app.get("/my-patients")
def get_my_patients(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    access_links = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == current_user.id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .all()
    )

    patient_ids = [link.patient_id for link in access_links]

    if not patient_ids:
        return []

    patients = (
        db.query(models.Patient)
        .filter(models.Patient.id.in_(patient_ids))
        .all()
    )

    results = []

    for patient in patients:
        active_event = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.patient_id == patient.id,
                models.PatientEvent.status == "active",
            )
            .order_by(models.PatientEvent.id.desc())
            .first()
        )

        latest_event = (
            db.query(models.PatientEvent)
            .filter(models.PatientEvent.patient_id == patient.id)
            .order_by(models.PatientEvent.id.desc())
            .first()
        )

        documents_query = (
            db.query(models.Document)
            .filter(models.Document.patient_id == patient.id)
            .order_by(models.Document.id.desc())
        )

        documents = documents_query.all()

        new_records_count = 0
        abnormal_count = 0
        latest_abnormal_labs = []

        for document in documents:
            reviewed = doctor_reviewed_document(db, current_user.id, document.id)

            if not reviewed:
                new_records_count += 1

            labs = (
                db.query(models.LabResult)
                .filter(models.LabResult.document_id == document.id)
                .all()
            )

            abnormal_labs_for_doc = [
                lab for lab in labs if lab_flag_is_abnormal(lab.flag)
            ]

            if abnormal_labs_for_doc and not reviewed:
                abnormal_count += len(abnormal_labs_for_doc)

                for lab in abnormal_labs_for_doc[:3]:
                    latest_abnormal_labs.append(
                        {
                            "id": lab.id,
                            "display_name": lab.display_name or lab.raw_test_name or lab.canonical_name,
                            "value": lab.value,
                            "unit": lab.unit,
                            "flag": lab.flag,
                            "reference_range": lab.reference_range,
                        }
                    )

            if len(latest_abnormal_labs) >= 3:
                latest_abnormal_labs = latest_abnormal_labs[:3]

        care_context = "outpatient"
        care_context_label = "Outpatient follow-up"

        if active_event:
            care_context = "active_admission"
            care_context_label = "Active admission"
        elif latest_event:
            care_context = "past_admission"
            care_context_label = "Past admission"

        results.append(
            {
                "patient": {
                    "id": patient.id,
                    "full_name": patient.full_name,
                    "date_of_birth": patient.date_of_birth,
                    "age": patient.age,
                    "sex": patient.sex,
                    "cnp": _mask_cnp(patient.cnp),
                    "patient_identifier": patient.patient_identifier,
                },
                "active_event": serialize_patient_event(active_event) if active_event else None,
                "care_context": care_context,
                "care_context_label": care_context_label,
                "new_records_count": new_records_count,
                "has_new_records": new_records_count > 0,
                "abnormal_count": abnormal_count,
                "latest_abnormal_labs": latest_abnormal_labs,
            }
        )

    return results


# ── PCP Workspace endpoints ────────────────────────────────────────────────────

def _is_pcp_doctor(user) -> bool:
    return user.role == "doctor" and user.doctor_type == "pcp"


def require_pcp_or_admin():
    def dependency(current_user=Depends(get_current_user)):
        if current_user.role == "admin":
            return current_user
        if current_user.role == "doctor" and current_user.doctor_type == "pcp":
            return current_user
        raise HTTPException(status_code=403, detail="PCP workspace is only available for primary care / family medicine doctors.")
    return dependency


@app.get("/pcp/patients")
def pcp_get_patients(
    db: Session = Depends(get_db),
    current_user=Depends(require_pcp_or_admin()),
):
    access_links = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == current_user.id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .all()
    )
    if not access_links:
        return []
    patient_ids = [link.patient_id for link in access_links]
    patients = (
        db.query(models.Patient)
        .filter(models.Patient.id.in_(patient_ids))
        .order_by(models.Patient.full_name)
        .all()
    )
    return [
        {
            "id": p.id,
            "full_name": p.full_name,
            "age": p.age,
            "sex": p.sex,
            "date_of_birth": p.date_of_birth,
            "patient_identifier": p.patient_identifier,
        }
        for p in patients
    ]


@app.get("/pcp/patients/{patient_id}/summary")
def pcp_get_patient_summary(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_pcp_or_admin()),
):
    # Validate access
    if current_user.role != "admin" and not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="No active access to this patient.")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Bragi code
    code_record = db.query(models.PatientCarePartnerCode).filter(
        models.PatientCarePartnerCode.patient_id == patient_id
    ).first()

    # Care context
    active_event = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id, models.PatientEvent.status == "active")
        .order_by(models.PatientEvent.id.desc())
        .first()
    )
    latest_event = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id)
        .order_by(models.PatientEvent.id.desc())
        .first()
    )
    care_context = "active_admission" if active_event else ("past_admission" if latest_event else "outpatient")
    care_context_label = (
        "Active admission" if active_event else
        ("Past admission" if latest_event else "Outpatient follow-up")
    )

    # Medications (active first)
    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient_id)
        .order_by(models.PatientMedication.status, models.PatientMedication.name)
        .limit(20)
        .all()
    )

    # Recent documents (last 10)
    recent_docs = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .limit(10)
        .all()
    )

    # Latest bloodwork labs
    latest_labs = None
    for doc in recent_docs:
        if doc.section == "bloodwork":
            labs = (
                db.query(models.LabResult)
                .filter(models.LabResult.document_id == doc.id)
                .limit(40)
                .all()
            )
            latest_labs = {
                "document_id": doc.id,
                "test_date": doc.test_date,
                "lab_name": doc.lab_name,
                "labs": [
                    {
                        "name": lab.display_name or lab.raw_test_name,
                        "value": lab.value,
                        "unit": lab.unit,
                        "flag": lab.flag,
                        "reference_range": lab.reference_range,
                        "category": lab.category,
                    }
                    for lab in labs
                ],
            }
            break

    # Patient events for hospitalization timeline entries
    patient_events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id)
        .order_by(models.PatientEvent.id.desc())
        .limit(20)
        .all()
    )

    # All documents for timeline (broader than recent_docs)
    all_docs_for_timeline = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .limit(40)
        .all()
    )

    # Recent notes
    recent_notes = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id, models.Document.section == "notes")
        .order_by(models.Document.id.desc())
        .limit(5)
        .all()
    )

    _SECTION_EVENT_TYPE = {
        "bloodwork": "lab_panel",
        "discharge_summary": "discharge_summary",
        "scans": "imaging_report",
        "notes": "clinical_note",
        "medications": "medication_record",
        "hospitalizations": "hospitalization_record",
        "procedures": "procedure_report",
        "pathology": "pathology_report",
    }

    _DOC_SUMMARY_BY_EVENT_TYPE = {
        "lab_panel": "Lab panel with structured values extracted.",
        "clinical_note": "Clinical note recorded in patient file.",
        "discharge_summary": "Discharge summary recorded.",
        "imaging_report": "Imaging report recorded in patient file.",
        "medication_record": "Medication document recorded.",
        "operative_report": "Operative report recorded in patient file.",
        "pathology_report": "Pathology report recorded in patient file.",
        "prescription": "Prescription recorded in patient file.",
        "specialist_consultation": "Specialist consultation recorded in patient file.",
        "emergency_department_note": "Emergency department note recorded.",
        "hospital_admission_note": "Hospital admission note recorded.",
        "procedure_report": "Procedure report recorded in patient file.",
        "referral": "Referral recorded in patient file.",
    }

    def _event_type_for(doc) -> str:
        # Phase 5 — prefer Bragi's finer-grained document_type (Phase 1+
        # uploads) over the coarse legacy section, so e.g. an imaging vs.
        # operative vs. pathology document reads as a distinct, meaningful
        # timeline event instead of all three collapsing into whatever the
        # legacy "scans"/"hospitalizations" bucket implied. Falls back to
        # the section-based mapping for documents uploaded before automatic
        # classification existed (document_type is null there).
        if doc.document_type and doc.document_type != "other":
            return doc.document_type
        return _SECTION_EVENT_TYPE.get(doc.section, "source_document")

    def _doc_summary(doc, event_type: str) -> str:
        return _DOC_SUMMARY_BY_EVENT_TYPE.get(event_type, "Source document recorded in patient file.")

    pcp_timeline = []

    for doc in all_docs_for_timeline:
        event_type = _event_type_for(doc)
        pcp_timeline.append({
            "id": f"doc_{doc.id}",
            "event_type": event_type,
            "title": doc.report_name or doc.lab_name or doc.filename,
            "date": doc.test_date or doc.collected_on or doc.created_at or "",
            "source_id": doc.id,
            "source_type": "document",
            "summary": _doc_summary(doc, event_type),
            "route": f"/documents/{doc.id}",
            "is_source_linked": True,
        })

    for ev in patient_events:
        parts = [p for p in [ev.hospital_name, ev.department] if p]
        pcp_timeline.append({
            "id": f"event_{ev.id}",
            "event_type": "hospitalization_record",
            "title": ev.title,
            "date": ev.admitted_at or "",
            "source_id": None,
            "source_type": "event",
            "summary": " · ".join(parts) if parts else None,
            "route": None,
            "is_source_linked": False,
        })

    def _sort_key(e):
        d = e["date"] or "1970-01-01"
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(d.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    pcp_timeline.sort(key=_sort_key, reverse=True)

    return {
        "patient": {
            "id": patient.id,
            "public_id": patient.public_id,
            "full_name": patient.full_name,
            "age": patient.age,
            "sex": patient.sex,
            "date_of_birth": patient.date_of_birth,
            "patient_identifier": patient.patient_identifier,
            "bragi_code": code_record.code if code_record else None,
        },
        "care_context": care_context,
        "care_context_label": care_context_label,
        "access": {"has_active_access": True},
        "medications": [
            {
                "id": m.id,
                "name": m.name,
                "dose_strength": m.dose_strength,
                "frequency": m.frequency,
                "status": m.status,
                "route_form": m.route_form,
                "is_uncertain": bool(m.is_uncertain),
                "created_at": m.created_at,
            }
            for m in medications
        ],
        "recent_documents": [
            {
                "id": d.id,
                "section": d.section,
                "filename": d.filename,
                "report_name": d.report_name,
                "lab_name": d.lab_name,
                "test_date": d.test_date or d.created_at,
                "is_verified": bool(d.is_verified),
                "created_at": d.created_at,
            }
            for d in recent_docs
        ],
        "latest_labs": latest_labs,
        "pcp_timeline": pcp_timeline,
        "recent_notes": [
            {
                "id": n.id,
                "filename": n.filename,
                "report_name": n.report_name,
                "note_preview": (n.note_body or "")[:200] if n.note_body else None,
                "created_at": n.created_at,
            }
            for n in recent_notes
        ],
    }


@app.get("/patients/search")
def search_patients(
    q: str = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    term = q.strip().lower()
    patients = db.query(models.Patient).all()
    results = []

    for patient in patients:
        code_record = db.query(models.PatientCarePartnerCode).filter(
            models.PatientCarePartnerCode.patient_id == patient.id
        ).first()
        patient_code = (code_record.code or "").lower() if code_record else ""

        haystack = " ".join(
            [
                (patient.full_name or "").lower(),
                (patient.patient_identifier or "").lower(),
                patient_code,
            ]
        )

        if term not in haystack:
            continue

        has_access = True
        pending_request = False

        if current_user.role == "doctor":
            has_access = doctor_has_patient_access(db, current_user.id, patient.id)
            pending_request = (
                db.query(models.DoctorPatientAccessRequest)
                .filter(
                    models.DoctorPatientAccessRequest.doctor_user_id == current_user.id,
                    models.DoctorPatientAccessRequest.patient_id == patient.id,
                    models.DoctorPatientAccessRequest.status == "pending",
                )
                .first()
                is not None
            )

        results.append(
            {
                "id": patient.id,
                "full_name": patient.full_name,
                "date_of_birth": patient.date_of_birth,
                "age": patient.age,
                "sex": patient.sex,
                "cnp": _mask_cnp(patient.cnp),
                "patient_identifier": patient.patient_identifier,
                "care_partner_code": code_record.code if code_record else None,
                "has_access": has_access,
                "pending_request": pending_request,
            }
        )

    return results


@app.get("/patients/{patient_id}/profile")
def get_patient_profile(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if not can_access_patient(db, current_user, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    return build_patient_profile_response(db, patient, current_user)


def _delete_care_partner_account(db: Session, current_user) -> None:
    """Real row delete — a care_partner's only rows are their own access
    grants (CarePartnerPatientLink) and document shares
    (SharedStructuredPage), neither of which is part of any patient's
    clinical record or another party's audit trail, unlike a doctor's or
    admin's. Safe to remove outright, same spirit as patient deletion."""
    db.query(models.CarePartnerPatientLink).filter(
        models.CarePartnerPatientLink.care_partner_user_id == current_user.id
    ).delete(synchronize_session=False)
    db.query(models.SharedStructuredPage).filter(
        models.SharedStructuredPage.care_partner_user_id == current_user.id
    ).delete(synchronize_session=False)
    db.flush()
    db.delete(current_user)


def _soft_delete_clinical_or_admin_account(db: Session, current_user) -> None:
    """Deactivate rather than delete the row — see run_migrations()'s
    comment on `users.deleted_at` for exactly why a real delete isn't
    offered for doctor/admin: too many NOT NULL clinical/audit references
    across other patients' own records would either block the delete
    (FK violation -> 500) or have to be silently orphaned/anonymized,
    which would itself corrupt those patients' care history. This still
    satisfies "no orphaned PHI" and "no 500s": the account becomes
    unusable (get_current_user()/login() both reject it), its own login
    credential (email/password) is irreversibly replaced, and every
    active patient-access grant is explicitly ended — nothing about the
    ACCOUNT's own login-identifying PHI survives; what survives is other
    people's clinical records that legitimately reference this person's
    professional involvement, which erasure does not override (GDPR
    Art.17(3)(b) — see docs/privacy/RETENTION_POLICY.md).

    `[LEGAL REVIEW]`: whether this is the correct final policy (vs. e.g.
    a longer grace period, or a different anonymization depth) is a
    legal/product decision, not an engineering one — documented
    separately in docs/privacy/DSAR_RUNBOOK.md rather than assumed here.
    """
    if current_user.role == "doctor":
        db.query(models.DoctorPatientAccess).filter(
            models.DoctorPatientAccess.doctor_user_id == current_user.id,
            models.DoctorPatientAccess.is_active == 1,
        ).update(
            {"is_active": 0, "ended_at": now_iso()},
            synchronize_session=False,
        )

    current_user.email = f"deleted-user-{current_user.id}-{uuid.uuid4().hex[:10]}@deleted.bragi.invalid"
    current_user.password_hash = hash_password(secrets.token_urlsafe(32))
    current_user.deleted_at = now_iso()
    db.add(current_user)


@app.delete("/my/account")
def delete_my_account(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor", "admin", "care_partner")),
):
    # Deletion semantics are NOT identical across roles — see
    # BRAGI_SECURITY_GDPR_PLAN.md §19/Priority 8. Patient (below) and
    # care_partner are real row deletes. Doctor/admin are a soft-delete
    # (row persists, login disabled) — see
    # _soft_delete_clinical_or_admin_account's docstring for exactly why.
    # emergency_worker is deliberately not offered self-deletion yet
    # (product/legal decision required — see docs/privacy/DSAR_RUNBOOK.md).
    if current_user.role == "care_partner":
        _delete_care_partner_account(db, current_user)
        db.commit()
        return {"deleted": True}

    if current_user.role in ("doctor", "admin"):
        _soft_delete_clinical_or_admin_account(db, current_user)
        db.commit()
        return {"deleted": True}

    patient = get_patient_for_user(db, current_user.id)

    if patient:
        # Includes documents quarantined FOR this patient (identity
        # mismatch — patient_id is NULL, intended_patient_id points here;
        # see process_upload_job) as well as this patient's own documents
        # — both hold a real FK to patients.id and must be cleared before
        # the patient row itself can be deleted.
        docs = (
            db.query(models.Document)
            .filter(
                (models.Document.patient_id == patient.id)
                | (models.Document.intended_patient_id == patient.id)
            )
            .all()
        )
        doc_ids = [d.id for d in docs]

        if doc_ids:
            db.query(models.SharedStructuredPage).filter(
                models.SharedStructuredPage.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
            db.query(models.DoctorDocumentReview).filter(
                models.DoctorDocumentReview.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
            db.query(models.UploadJob).filter(
                models.UploadJob.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
            # SourceEvidence.document_id is a required (NOT NULL) FK with no
            # ON DELETE CASCADE at the DB level, and Document itself only
            # declares an ORM cascade for its lab_results, not for
            # source_evidence directly — LabResult.source_evidence *does*
            # cascade (see LabResult model), so lab-linked evidence rows are
            # already cleared when their LabResult is cascade-deleted below.
            # But document-level evidence (lab_result_id IS NULL — the
            # narrative-document citation fallback added for Ask Bragi, see
            # _ensure_document_level_evidence) has no LabResult to ride that
            # cascade, so it must be cleared here explicitly. Without this,
            # deleting a patient who has ever had a document-level Ask Bragi
            # citation fails with a ForeignKeyViolation (reproduced against
            # both a local and a production account before this fix).
            db.query(models.SourceEvidence).filter(
                models.SourceEvidence.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
            # Document.parent_document_id (Reducto Split) and LabResult.
            # duplicate_of_lab_result_id (Phase 2 Level-3 dedup linking)
            # are both self-references that would otherwise block
            # deleting either side depending on order — both are now
            # ON DELETE SET NULL at the DB level (see run_migrations()),
            # so no manual clearing is needed here.

        db.query(models.UploadJob).filter(
            models.UploadJob.patient_id == patient.id,
            models.UploadJob.document_id.is_(None),
        ).delete(synchronize_session=False)

        for doc in docs:
            db.delete(doc)
        db.flush()

        db.query(models.DoctorPatientAccessRequest).filter(
            models.DoctorPatientAccessRequest.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.DoctorPatientAccess).filter(
            models.DoctorPatientAccess.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.CarePartnerPatientLink).filter(
            models.CarePartnerPatientLink.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.PatientCarePartnerCode).filter(
            models.PatientCarePartnerCode.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.PatientEvent).filter(
            models.PatientEvent.patient_id == patient.id
        ).delete(synchronize_session=False)
        # The patient's own authored data (unlike emergency-access-session/
        # audit-log rows, which are detached via ON DELETE SET NULL instead
        # — see run_migrations() — because those are access-audit records,
        # not this patient's own content).
        db.query(models.PatientMedication).filter(
            models.PatientMedication.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.EmergencyContact).filter(
            models.EmergencyContact.patient_id == patient.id
        ).delete(synchronize_session=False)

        # Ask Bragi conversations/messages (found by this feature's own
        # test suite before it ever shipped — the same class of
        # FK-cascade gap §3 item 6 fixed for other tables). A bulk
        # .delete(synchronize_session=False) doesn't trigger the ORM
        # relationship's cascade, so messages must be cleared explicitly
        # before the conversations that reference patient.id.
        conversation_ids = [
            c.id
            for c in db.query(models.AskBragiConversation.id).filter(
                models.AskBragiConversation.patient_id == patient.id
            )
        ]
        if conversation_ids:
            db.query(models.AskBragiMessage).filter(
                models.AskBragiMessage.conversation_id.in_(conversation_ids)
            ).delete(synchronize_session=False)
            db.query(models.AskBragiConversation).filter(
                models.AskBragiConversation.id.in_(conversation_ids)
            ).delete(synchronize_session=False)

        # Interoperability (BRAGI_INTEROP_PLAN.md) — same FK-cascade class
        # of gap as Ask Bragi above, found the same way (this feature's own
        # test suite, before shipping). ExternalPatientIdentityLink.patient_id
        # is a required FK with no DB-level cascade; InteropIdentityConflict.
        # attempted_patient_id is nullable and only ever a historical
        # reference, so it's detached (SET NULL) rather than deleted — the
        # conflict record itself is an audit trail, not this patient's data.
        identity_link_ids = [
            link_id
            for (link_id,) in db.query(models.ExternalPatientIdentityLink.id).filter(
                models.ExternalPatientIdentityLink.patient_id == patient.id
            )
        ]
        if identity_link_ids:
            # InteropIdentityConflict.existing_link_id points back at a link
            # row — detach (SET NULL) rather than delete the conflict itself,
            # since the conflict is an audit record, not this patient's data.
            for conflict in db.query(models.InteropIdentityConflict).filter(
                models.InteropIdentityConflict.existing_link_id.in_(identity_link_ids)
            ):
                conflict.existing_link_id = None
            # SessionLocal is autoflush=False (see app/db.py) — the ORM
            # UPDATEs above are only pending in memory until flushed, but the
            # next statement is a bulk `.delete(synchronize_session=False)`,
            # which issues a raw DELETE directly and does NOT trigger
            # autoflush. Without this explicit flush, the DB still sees the
            # OLD existing_link_id value and the DELETE fails its FK check
            # (reproduced for real against Neon before this fix).
            db.flush()
            db.query(models.ExternalPatientIdentityLink).filter(
                models.ExternalPatientIdentityLink.id.in_(identity_link_ids)
            ).delete(synchronize_session=False)
        for conflict in db.query(models.InteropIdentityConflict).filter(
            models.InteropIdentityConflict.attempted_patient_id == patient.id
        ):
            conflict.attempted_patient_id = None

        db.delete(patient)
        db.flush()

    db.delete(current_user)
    db.commit()
    return {"deleted": True}


@app.delete("/my/access/{doctor_user_id}")
def revoke_doctor_access(
    doctor_user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    access = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
            models.DoctorPatientAccess.patient_id == patient.id,
        )
        .first()
    )

    if not access:
        raise HTTPException(status_code=404, detail="Access record not found")

    db.delete(access)
    db.commit()

    return {"revoked": True, "doctor_user_id": doctor_user_id}


@app.get("/my/profile")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)
    return build_patient_profile_response(db, patient, current_user)


# Cap on how many original document files a single export embeds — this
# is a per-patient, self-service export, so the input is bounded by their
# own real usage, but a hard ceiling protects the server from an
# unbounded temp-file/disk-space blowup regardless. Documents beyond the
# cap are still fully described in documents_manifest.json; only the raw
# file bytes are left out, with a note explaining why.
DSAR_EXPORT_MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB total original-file payload


@app.post("/my/export")
def export_my_data(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
    _rl=Depends(RateLimiter(limit=3, window_seconds=86400, key_prefix="dsar_export")),
):
    """DSAR data export (GDPR Article 15/20) for the patient making the
    request — see docs/privacy/DSAR_RUNBOOK.md. Uses the same
    authorization as every other patient-scoped endpoint
    (require_role("patient") + get_patient_for_user, which only ever
    resolves to the requester's own linked Patient row) — there is no
    separate "which patient" parameter for this to get wrong, unlike a
    lookup-by-id endpoint.

    Returns a zip: profile.json, lab_results.json, medications.json,
    events.json, access_relationships.json, emergency_contacts.json,
    documents_manifest.json, ai_conversations.json (the patient's own Ask
    Bragi conversations — full message content/citations, whether the
    patient or a doctor asked; empty list if there are none or the
    feature is disabled), README.txt, and documents/ (the patient's own
    original uploaded files, up to DSAR_EXPORT_MAX_FILE_BYTES total).

    Deliberately excludes: any other patient's data (every query below is
    scoped to `patient.id`, never a caller-supplied id); quarantined
    documents uploaded under this identity but not yet confirmed as this
    patient's own record (`Document.patient_id` must match exactly —
    `intended_patient_id`-only rows are unconfirmed, not included);
    internal security metadata (password hashes, JWT internals, other
    users' emergency-access audit trail).
    """
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient.id)
        .order_by(models.Document.id.asc())
        .all()
    )
    doc_ids = [d.id for d in documents]

    lab_results = (
        db.query(models.LabResult).filter(models.LabResult.document_id.in_(doc_ids)).all()
        if doc_ids
        else []
    )
    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient.id)
        .all()
    )
    events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient.id)
        .order_by(models.PatientEvent.admitted_at.desc())
        .all()
    )
    doctor_access = (
        db.query(models.DoctorPatientAccess)
        .filter(models.DoctorPatientAccess.patient_id == patient.id)
        .all()
    )
    access_requests = (
        db.query(models.DoctorPatientAccessRequest)
        .filter(models.DoctorPatientAccessRequest.patient_id == patient.id)
        .all()
    )
    care_partner_links = (
        db.query(models.CarePartnerPatientLink)
        .filter(models.CarePartnerPatientLink.patient_id == patient.id)
        .all()
    )
    emergency_contacts = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient.id)
        .all()
    )
    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )

    def _doctor_label(doctor_user_id: int | None) -> dict | None:
        if not doctor_user_id:
            return None
        doctor = db.query(models.User).filter(models.User.id == doctor_user_id).first()
        if not doctor:
            return None
        # A recipient's identity is itself something a DSAR is entitled to
        # disclose (GDPR Art. 15(1)(c), "recipients ... to whom the
        # personal data have been disclosed") — name/role only, never
        # their password hash or other account internals.
        return {"full_name": doctor.full_name, "role": doctor.role}

    profile_payload = {
        "id": patient.id,
        "public_id": patient.public_id,
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth,
        "age": patient.age,
        "sex": patient.sex,
        "cnp": patient.cnp,
        "patient_identifier": patient.patient_identifier,
        "emergency_search_enabled": bool(patient.emergency_search_enabled),
        "account_email": current_user.email,
        "care_partner_code": code_record.code if code_record else None,
    }

    lab_results_payload = [
        {
            "document_id": lr.document_id,
            "raw_test_name": lr.raw_test_name,
            "canonical_name": lr.canonical_name,
            "display_name": lr.display_name,
            "category": lr.category,
            "value": lr.value,
            "flag": lr.flag,
            "reference_range": lr.reference_range,
            "unit": lr.unit,
            "observation_datetime": lr.observation_datetime,
            "institution": lr.institution,
            "specimen": lr.specimen,
            "verification_state": lr.verification_state,
        }
        for lr in lab_results
    ]

    medications_payload = [
        {
            "name": m.name,
            "dose_strength": m.dose_strength,
            "frequency": m.frequency,
            "reason": m.reason,
            "status": m.status,
            "route_form": m.route_form,
            "start_date": m.start_date,
            "stop_date": m.stop_date,
            "prescriber": m.prescriber,
            "extra_info": m.extra_info,
            "is_uncertain": bool(m.is_uncertain),
            "created_at": m.created_at,
            "updated_at": m.updated_at,
            "official_source_name": m.official_source_name,
            "official_source_url": m.official_source_url,
        }
        for m in medications
    ]

    events_payload = [
        {
            "event_type": e.event_type,
            "status": e.status,
            "title": e.title,
            "description": e.description,
            "hospital_name": e.hospital_name,
            "department": e.department,
            "admitted_at": e.admitted_at,
            "discharged_at": e.discharged_at,
            "attending_doctor": _doctor_label(e.doctor_user_id),
        }
        for e in events
    ]

    access_payload = {
        "doctor_access_grants": [
            {
                "doctor": _doctor_label(a.doctor_user_id),
                "granted_at": a.granted_at,
                "is_active": bool(a.is_active),
                "ended_at": a.ended_at,
            }
            for a in doctor_access
        ],
        "doctor_access_requests": [
            {
                "doctor": _doctor_label(r.doctor_user_id),
                "status": r.status,
                "requested_at": r.requested_at,
                "responded_at": r.responded_at,
            }
            for r in access_requests
        ],
        "care_partner_links": [
            {
                "care_partner": _doctor_label(link.care_partner_user_id),
                "linked_at": link.linked_at,
            }
            for link in care_partner_links
        ],
    }

    emergency_contacts_payload = [
        {
            "name": c.name,
            "relationship": c.contact_relationship,
            "phone": c.phone,
            "notes": c.notes,
        }
        for c in emergency_contacts
    ]

    # Ask Bragi conversations (feature-flagged; empty list wherever the
    # feature doesn't exist/hasn't been used — this is the patient's own
    # data being exported to themselves, so full question/answer text is
    # included here even though it's deliberately excluded from server
    # audit logs (see main.py's Ask Bragi section / BRAGI_ASK_BRAGI_PLAN.md).
    ask_bragi_conversations = (
        db.query(models.AskBragiConversation)
        .filter(models.AskBragiConversation.patient_id == patient.id)
        .order_by(models.AskBragiConversation.id.asc())
        .all()
    )
    ask_bragi_payload = [
        {
            "conversation_id": conv.id,
            "scope": conv.scope,
            "document_id": conv.document_id,
            "created_at": conv.created_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "citations": json.loads(m.citations_json) if m.citations_json else [],
                    "created_at": m.created_at,
                }
                for m in conv.messages
            ],
        }
        for conv in ask_bragi_conversations
    ]

    documents_manifest: list[dict] = []
    embedded_bytes = 0
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".zip", prefix="bragi-dsar-export-")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)

    try:
        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for document in documents:
                entry = {
                    "document_id": document.id,
                    "public_id": document.public_id,
                    "filename": document.filename,
                    "section": document.section,
                    "document_type": document.document_type,
                    "report_name": document.report_name,
                    "test_date": document.test_date,
                    "created_at": document.created_at,
                    "uploaded_by": _doctor_label(document.uploaded_by_user_id),
                    "included_in_documents_folder": False,
                }
                if document.saved_to:
                    file_path = Path(document.saved_to)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        if embedded_bytes + size <= DSAR_EXPORT_MAX_FILE_BYTES:
                            arcname = f"documents/{document.id}_{document.filename}"
                            zf.write(file_path, arcname=arcname)
                            embedded_bytes += size
                            entry["included_in_documents_folder"] = True
                        else:
                            entry["note"] = "Original file omitted — export size cap reached (see README.txt)."
                documents_manifest.append(entry)
                add_audit_log(
                    db=db,
                    document_id=document.id,
                    action="dsar_export",
                    actor=f"patient_self:{current_user.id}",
                    details="Included in a self-service data export (GDPR DSAR).",
                )

            readme = f"""Bragi data export
Generated: {now_iso()}
Patient: {patient.full_name} (internal id {patient.id})

This archive contains the personal data Bragi holds about you, generated
in response to a data export request (GDPR Article 15/20). See
docs/privacy/DSAR_RUNBOOK.md in the Bragi source repository for the
policy this implements.

Contents:
- profile.json — your account/profile data
- lab_results.json — structured lab results extracted from your documents
- medications.json — your medication list
- events.json — your care timeline (admissions, discharges)
- access_relationships.json — clinicians/care partners who have or had
  access to your record, and any pending access requests
- emergency_contacts.json — emergency contacts you added
- documents_manifest.json — metadata for every uploaded document
- documents/ — the original uploaded files themselves, where the export
  size cap allowed inclusion (see documents_manifest.json's
  "included_in_documents_folder"/"note" fields for any that were left out)
- ai_conversations.json — your Ask Bragi conversations, if any (empty
  list if you have none, or if this feature is not enabled)

Not included: any other patient's data; documents uploaded under your
identity but not yet confirmed as belonging to your record (an identity
mismatch/review queue, not your official record); internal account
security metadata (password hash, auth tokens).
"""
            zf.writestr("README.txt", readme)
            zf.writestr("profile.json", json.dumps(profile_payload, indent=2))
            zf.writestr("lab_results.json", json.dumps(lab_results_payload, indent=2))
            zf.writestr("medications.json", json.dumps(medications_payload, indent=2))
            zf.writestr("events.json", json.dumps(events_payload, indent=2))
            zf.writestr("access_relationships.json", json.dumps(access_payload, indent=2))
            zf.writestr("emergency_contacts.json", json.dumps(emergency_contacts_payload, indent=2))
            zf.writestr("documents_manifest.json", json.dumps(documents_manifest, indent=2))
            zf.writestr("ai_conversations.json", json.dumps(ask_bragi_payload, indent=2))

        db.commit()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # PHI-free summary log only (counts, never content) — this export's
    # per-document AuditLog rows above are the durable, queryable audit
    # trail; this line is just an operational breadcrumb.
    print(
        f"DSAR EXPORT: patient_id={patient.id} user_id={current_user.id} "
        f"documents={len(documents)} embedded_bytes={embedded_bytes}"
    )

    background_tasks.add_task(lambda: tmp_path.unlink(missing_ok=True))
    export_filename = f"bragi-export-{patient.public_id or patient.id}.zip"
    return FileResponse(
        path=str(tmp_path),
        filename=export_filename,
        media_type="application/zip",
        background=background_tasks,
    )


@app.get("/patients/{patient_id}/documents")
def get_patient_documents(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .all()
    )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            # Masked — this is a document-list view, not an identity/edit
            # workflow; see build_patient_profile_response for the one
            # place the full value is returned.
            "cnp": _mask_cnp(patient.cnp),
            "patient_identifier": patient.patient_identifier,
        },
        "documents": [serialize_document_card(db, document, current_user) for document in documents],
    }

def resolve_upload_patient(db: Session, current_user: models.User, patient_id: int | None = None):
    if current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)

        if not patient:
            raise HTTPException(status_code=404, detail="Patient profile not found.")

        return patient

    if current_user.role == "doctor":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for doctor uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        if not doctor_has_patient_access(db, current_user.id, patient.id):
            raise HTTPException(status_code=403, detail="You do not have access to this patient.")

        return patient

    if current_user.role == "admin":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for admin uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        return patient

    if current_user.role == "care_partner":
        if not patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for care partner uploads.")

        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == patient_id)
            .first()
        )

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        link = (
            db.query(models.CarePartnerPatientLink)
            .filter(
                models.CarePartnerPatientLink.care_partner_user_id == current_user.id,
                models.CarePartnerPatientLink.patient_id == patient_id,
            )
            .first()
        )

        if not link:
            raise HTTPException(status_code=403, detail="You are not linked to this patient.")

        return patient

    raise HTTPException(status_code=403, detail="Invalid user role.")

@app.post("/upload/background")
async def create_background_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    section: str = Form("bloodwork"),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    if section not in ALLOWED_SECTIONS:
        raise HTTPException(status_code=400, detail="Invalid document section")

    patient = resolve_upload_patient(db, current_user, patient_id)

    original_filename = file.filename or "uploaded_document"
    _safe_ext = _validate_upload_extension(original_filename)
    file_data = await _read_and_validate_upload(file, _safe_ext)
    saved_filename = f"{uuid.uuid4().hex}{_safe_ext}"
    saved_path = UPLOAD_DIR / saved_filename

    try:
        saved_path.write_bytes(file_data)
    except Exception as save_error:
        # Full detail (which can include server-side I/O/OS error text — e.g.
        # actual filesystem paths) goes to server logs only; the client gets
        # a generic message. See docs/security/THREAT_MODEL.md — "verbose
        # error disclosure."
        print(f"UPLOAD SAVE FAILED: {save_error}")
        raise HTTPException(status_code=500, detail="Could not save uploaded file.")
    finally:
        try:
            await file.close()
        except Exception:
            pass

    job = models.UploadJob(
        user_id=current_user.id,
        patient_id=patient.id,
        section=section,
        filename=original_filename,
        content_type=file.content_type,
        saved_to=str(saved_path),
        status="queued",
        progress=0,
        message="Queued for processing.",
        error=None,
        document_id=None,
        created_at=now_iso(),
        started_at=None,
        finished_at=None,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


@app.post("/upload")
async def upload_compatibility_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    section: str = Form("bloodwork"),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    return await create_background_upload(
        background_tasks=background_tasks,
        file=file,
        section=section,
        patient_id=patient_id,
        db=db,
        current_user=current_user,
    )


async def _save_incoming_file(file: UploadFile) -> tuple[str, str]:
    """Save an uploaded file to UPLOAD_DIR under a randomized name.

    Returns (original_filename, saved_path). Shared by the batch upload
    endpoint; the single-file endpoints above intentionally keep their
    own inline copy of this logic unchanged.
    """
    original_filename = file.filename or "uploaded_document"
    _safe_ext = _validate_upload_extension(original_filename)
    file_data = await _read_and_validate_upload(file, _safe_ext)
    saved_filename = f"{uuid.uuid4().hex}{_safe_ext}"
    saved_path = UPLOAD_DIR / saved_filename

    try:
        saved_path.write_bytes(file_data)
    except Exception as save_error:
        # Full detail (which can include server-side I/O/OS error text — e.g.
        # actual filesystem paths) goes to server logs only; the client gets
        # a generic message. See docs/security/THREAT_MODEL.md — "verbose
        # error disclosure."
        print(f"UPLOAD SAVE FAILED: {save_error}")
        raise HTTPException(status_code=500, detail="Could not save uploaded file.")
    finally:
        try:
            await file.close()
        except Exception:
            pass

    return original_filename, str(saved_path)


@app.get("/document-types")
def get_document_types(current_user=Depends(get_current_user)):
    return document_type_choices()


@app.post("/upload/batch")
async def create_batch_upload(
    files: list[UploadFile] = File(...),
    patient_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="upload")),
):
    """Independent multi-file ingestion.

    Each file becomes its own UploadJob and is classified + processed
    independently (see process_upload_job) — one bad or ambiguous file
    never blocks the others. No `section` is accepted here: document type
    is always determined from content.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files were provided.")

    patient = resolve_upload_patient(db, current_user, patient_id)

    created_jobs = []

    for file in files:
        try:
            original_filename, saved_path = await _save_incoming_file(file)
        except HTTPException as save_error:
            created_jobs.append(
                {
                    "filename": file.filename or "uploaded_document",
                    "status": "error",
                    "error": save_error.detail,
                }
            )
            continue

        job = models.UploadJob(
            user_id=current_user.id,
            patient_id=patient.id,
            section=AUTO_CLASSIFY_SECTION,
            filename=original_filename,
            content_type=file.content_type,
            saved_to=saved_path,
            status="queued",
            progress=0,
            message="Queued for processing.",
            error=None,
            document_id=None,
            created_at=now_iso(),
            started_at=None,
            finished_at=None,
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        # Bounded worker pool, not BackgroundTasks — see UPLOAD_JOB_POOL's
        # definition. Each file starts processing as soon as a worker slot
        # frees up, instead of strictly after every earlier file in the
        # batch has fully finished.
        UPLOAD_JOB_POOL.submit(process_upload_job, job.id)
        created_jobs.append(serialize_upload_job(job))

    return created_jobs


class ConfirmDocumentTypeRequest(BaseModel):
    document_type: str


@app.post("/upload-jobs/{job_id}/confirm-type")
def confirm_upload_job_document_type(
    job_id: int,
    payload: ConfirmDocumentTypeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resolve a needs_confirmation upload job with a user-chosen type.

    This is the only path that resumes a job stuck in needs_confirmation —
    see the classification block in process_upload_job.
    """
    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status != "needs_confirmation":
        raise HTTPException(status_code=400, detail="This upload is not awaiting confirmation.")

    if not is_valid_document_type(payload.document_type):
        raise HTTPException(status_code=400, detail="Unknown document type.")

    job.document_type = payload.document_type
    job.section = legacy_section_for(payload.document_type)
    job.classification_status = "classified"
    job.classification_source = "user_confirmed"
    job.status = "queued"
    job.progress = 0
    job.message = "Confirmed. Processing..."
    job.error = None
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


class ConfirmIdentityRequest(BaseModel):
    confirmed: bool


@app.post("/upload-jobs/{job_id}/confirm-identity")
def confirm_upload_job_identity(
    job_id: int,
    payload: ConfirmIdentityRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resolve a needs_identity_confirmation upload job.

    `confirmed=True` is an audited manual override: the uploader asserts
    this document is really theirs despite the ambiguous signal, and
    reprocessing skips the identity check this one time
    (UploadJob.identity_override). `confirmed=False` sets the job aside —
    nothing was persisted yet (see process_upload_job), so there is
    nothing to quarantine.
    """
    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status != "needs_identity_confirmation":
        raise HTTPException(status_code=400, detail="This upload is not awaiting identity confirmation.")

    if not payload.confirmed:
        job.status = "quarantined"
        job.progress = 100
        job.message = "Set aside — not associated with your record."
        job.finished_at = now_iso()
        db.commit()
        return serialize_upload_job(job)

    job.identity_override = 1
    job.identity_status = None
    job.status = "queued"
    job.progress = 0
    job.message = "Confirmed. Processing..."
    job.error = None
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_upload_job, job.id)

    return serialize_upload_job(job)


class IdentityReviewRequest(BaseModel):
    action: str  # "confirm_mine" | "reject"


@app.get("/documents/quarantined")
def get_quarantined_documents(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Documents set aside for a wrong-patient identity mismatch.

    Patients see quarantined documents intended for their own record;
    admins see everything. Doctors do not have a review surface here yet
    (out of scope for this phase — see BRAGI_REDUCTO_PLAN.md).
    """
    query = db.query(models.Document).filter(models.Document.review_status == "quarantined")

    if current_user.role == "admin":
        pass
    elif current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)
        if not patient:
            return []
        query = query.filter(models.Document.intended_patient_id == patient.id)
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = query.order_by(models.Document.id.desc()).all()

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "document_type": doc.document_type,
            "created_at": doc.created_at,
            "identity_status": doc.identity_status,
        }
        for doc in documents
    ]


@app.post("/documents/{document_id}/identity-review")
def review_quarantined_document(
    document_id: int,
    payload: IdentityReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.review_status != "quarantined":
        raise HTTPException(status_code=400, detail="This document is not awaiting identity review.")

    if current_user.role == "admin":
        pass
    elif current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)
        if not patient or document.intended_patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    if payload.action == "reject":
        document.review_status = "resolved_rejected"
        db.commit()

        add_audit_log(
            db=db,
            document_id=document.id,
            action="quarantine_rejected",
            actor=current_user.full_name,
            details="Uploader confirmed this document does not belong to them.",
        )
        db.commit()

        return {"ok": True, "document_id": document.id, "review_status": document.review_status}

    if payload.action == "confirm_mine":
        if not document.intended_patient_id:
            raise HTTPException(status_code=400, detail="This document has no intended patient to confirm.")

        job = models.UploadJob(
            user_id=current_user.id,
            patient_id=document.intended_patient_id,
            section=(legacy_section_for(document.document_type) if document.document_type else AUTO_CLASSIFY_SECTION),
            filename=document.filename,
            content_type=document.content_type,
            saved_to=document.saved_to,
            status="queued",
            progress=0,
            message="Reprocessing after identity confirmation...",
            error=None,
            document_id=None,
            file_sha256=document.file_sha256,
            identity_override=1,
            created_at=now_iso(),
            started_at=None,
            finished_at=None,
        )

        db.add(job)
        document.review_status = "resolved_confirmed"
        db.commit()
        db.refresh(job)

        add_audit_log(
            db=db,
            document_id=document.id,
            action="identity_manually_confirmed",
            actor=current_user.full_name,
            details=f"Uploader confirmed this document is theirs; reprocessing as upload job {job.id}.",
        )
        db.commit()

        background_tasks.add_task(process_upload_job, job.id)

        return {"ok": True, "document_id": document.id, "new_upload_job": serialize_upload_job(job)}

    raise HTTPException(status_code=400, detail="Unknown action.")


@app.get("/upload-jobs")
def get_my_upload_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    jobs = (
        db.query(models.UploadJob)
        .filter(models.UploadJob.user_id == current_user.id)
        .order_by(models.UploadJob.id.desc())
        .limit(30)
        .all()
    )

    return [serialize_upload_job(job) for job in jobs]


@app.get("/upload-jobs/{job_id}")
def get_upload_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    return serialize_upload_job(job)


@app.get("/documents/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document_id):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.role == "doctor":
        mark_doctor_reviewed_document(db, current_user.id, document.id)
        db.commit()

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)


# ── Public-ID lookup endpoints (pretty URL resolution) ────────────────────────

@app.get("/patients/by-public-id/{public_id}")
def get_patient_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.public_id == public_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if current_user.role == "patient":
        if patient.linked_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied.")
    elif current_user.role in ("doctor",):
        if not doctor_has_patient_access(db, current_user.id, patient.id):
            raise HTTPException(status_code=403, detail="No active access to this patient.")
    elif current_user.role == "care_partner":
        link = (
            db.query(models.CarePartnerPatientLink)
            .filter(
                models.CarePartnerPatientLink.care_partner_user_id == current_user.id,
                models.CarePartnerPatientLink.patient_id == patient.id,
            )
            .first()
        )
        if not link:
            raise HTTPException(status_code=403, detail="Access denied.")
    elif current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied.")
    return {"id": patient.id, "public_id": patient.public_id}


@app.get("/documents/by-public-id/{public_id}")
def get_document_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.public_id == public_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    if current_user.role == "care_partner":
        if not care_partner_can_access_document(db, current_user.id, document.id):
            raise HTTPException(status_code=403, detail="Forbidden.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden.")
    return {"id": document.id, "public_id": document.public_id}


@app.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access raw document files.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not document.saved_to:
        raise HTTPException(status_code=404, detail="File path not found")

    file_path = Path(document.saved_to)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        path=str(file_path),
        filename=document.filename,
        media_type=document.content_type or "application/octet-stream",
    )


@app.get("/source-evidence/{source_evidence_id}/view")
def get_source_evidence_view(
    source_evidence_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    """Resolve one SourceEvidence row into everything the shared Bragi
    source viewer needs to open it — the general-purpose
    `openSourceEvidence(sourceEvidenceId)` backend contract (see
    BRAGI_REDUCTO_PLAN.md), used today by Analize/charts and intended as
    the canonical citation-resolution endpoint for future Ask Bragi too.

    Authorization is identical to the existing `/documents/{id}/file`
    route (`can_access_patient`, no care-partner access) — this endpoint
    exposes bbox/page metadata, never a bare/public file URL; the actual
    PDF bytes are still fetched through the existing authenticated file
    route using the `document_id` this returns.
    """
    evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.id == source_evidence_id).first()

    if not evidence:
        raise HTTPException(status_code=404, detail="Source evidence not found")

    document = db.query(models.Document).filter(models.Document.id == evidence.document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Source document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access source evidence.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    has_bbox = evidence.bbox_x is not None and evidence.bbox_y is not None
    if evidence.page_number and has_bbox:
        precision = "exact_bbox"
    elif evidence.page_number:
        precision = "page_only"
    elif evidence.source_text:
        precision = "text_only"
    else:
        precision = "document_only"

    return {
        "source_evidence_id": evidence.id,
        "document_id": document.id,
        "document_filename": document.filename,
        "document_type": document.document_type,
        "report_name": document.report_name,
        "lab_result_id": evidence.lab_result_id,
        "page_number": evidence.page_number,
        "bbox_x": evidence.bbox_x,
        "bbox_y": evidence.bbox_y,
        "bbox_width": evidence.bbox_width,
        "bbox_height": evidence.bbox_height,
        "row_bbox_x": evidence.row_bbox_x,
        "row_bbox_y": evidence.row_bbox_y,
        "row_bbox_width": evidence.row_bbox_width,
        "row_bbox_height": evidence.row_bbox_height,
        "source_text": evidence.source_text,
        "provider": evidence.provider,
        "precision": precision,
    }


@app.get("/lab-results/{lab_result_id}/source")
def get_lab_result_source(
    lab_result_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _rl=Depends(RateLimiter(limit=120, window_seconds=300, key_prefix="source_retrieval")),
):
    """Provenance for one structured lab row — the "View original" flagship
    feature's data source (see BRAGI_REDUCTO_PLAN.md Phase 3).

    Returns every SourceEvidence row for this lab result (there can be
    more than one once Level-3 duplicate-observation linking has
    attached evidence from more than one document to the same
    observation). Page/bbox fields are present but null until a real
    Reducto Parse integration can supply them — never fabricated.
    """
    lab = db.query(models.LabResult).filter(models.LabResult.id == lab_result_id).first()

    if not lab:
        raise HTTPException(status_code=404, detail="Lab result not found")

    document = db.query(models.Document).filter(models.Document.id == lab.document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role == "care_partner":
        raise HTTPException(status_code=403, detail="Care partners cannot access source evidence.")
    elif not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    evidence_rows = (
        db.query(models.SourceEvidence)
        .filter(models.SourceEvidence.lab_result_id == lab_result_id)
        .order_by(models.SourceEvidence.id.asc())
        .all()
    )

    return {
        "lab_result_id": lab.id,
        "document_id": document.id,
        "document_filename": document.filename,
        "evidence": [
            {
                "id": row.id,
                "document_id": row.document_id,
                "page_number": row.page_number,
                "bbox_x": row.bbox_x,
                "bbox_y": row.bbox_y,
                "bbox_width": row.bbox_width,
                "bbox_height": row.bbox_height,
                "source_text": row.source_text,
                "extraction_confidence": row.extraction_confidence,
                "provider": row.provider,
            }
            for row in evidence_rows
        ],
    }


@app.put("/documents/{document_id}")
def update_document(
    document_id: int,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    parsed = payload.parsed_data

    document.patient_name = parsed.patient_name
    document.date_of_birth = parsed.date_of_birth
    document.age = parsed.age
    document.sex = parsed.sex
    document.cnp = parsed.cnp
    document.patient_identifier = parsed.patient_identifier
    document.lab_name = parsed.lab_name
    document.sample_type = parsed.sample_type
    document.referring_doctor = parsed.referring_doctor
    document.report_name = parsed.report_name
    document.report_type = parsed.report_type
    document.source_language = parsed.source_language
    document.test_date = parsed.test_date
    document.collected_on = parsed.collected_on
    document.reported_on = parsed.reported_on
    document.registered_on = parsed.registered_on
    document.generated_on = parsed.generated_on
    document.note_body = parsed.note_body
    document.last_edited_at = now_iso()

    db.query(models.LabResult).filter(models.LabResult.document_id == document.id).delete()

    for lab in parsed.labs:
        db.add(
            models.LabResult(
                document_id=document.id,
                raw_test_name=lab.raw_test_name,
                canonical_name=lab.canonical_name,
                display_name=lab.display_name,
                category=lab.category,
                source_section=lab.source_section,
                value=lab.value,
                flag=lab.flag,
                reference_range=lab.reference_range,
                unit=lab.unit,
            )
        )

    add_audit_log(
        db=db,
        document_id=document.id,
        action="edited",
        actor=payload.editor_name or current_user.full_name,
        details="Structured fields were manually edited.",
    )

    db.commit()
    db.refresh(document)

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)


@app.post("/documents/{document_id}/verify")
def verify_document(
    document_id: int,
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    document.is_verified = True
    document.verified_by = payload.verifier_name or current_user.full_name
    document.verified_at = now_iso()

    add_audit_log(
        db=db,
        document_id=document.id,
        action="verified",
        actor=document.verified_by,
        details="Document was verified.",
    )

    db.commit()
    db.refresh(document)

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    return get_document_payload(db, document, labs, audit_logs, current_user)

@app.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.role == "patient":
        patient = get_patient_for_user(db, current_user.id)

        if not patient or patient.id != document.patient_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    saved_to = document.saved_to

    db.query(models.NoteDocumentLink).filter(
        (models.NoteDocumentLink.note_document_id == document.id)
        | (models.NoteDocumentLink.linked_document_id == document.id)
    ).delete(synchronize_session=False)

    db.query(models.DoctorDocumentReview).filter(
        models.DoctorDocumentReview.document_id == document.id
    ).delete(synchronize_session=False)

    db.query(models.UploadJob).filter(
        models.UploadJob.document_id == document.id
    ).update({"document_id": None}, synchronize_session=False)

    db.delete(document)
    db.commit()

    if saved_to:
        try:
            path = Path(saved_to)
            if path.exists():
                path.unlink()
        except Exception:
            pass

    return {"ok": True, "deleted_document_id": document_id}


@app.get("/patients/{patient_id}/bloodwork-trends")
def get_patient_bloodwork_trends(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not can_access_patient(db, current_user, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    documents = (
        db.query(models.Document)
        .filter(
            models.Document.patient_id == patient_id,
            models.Document.section == "bloodwork",
        )
        .order_by(models.Document.id.asc())
        .all()
    )

    document_by_id = {document.id: document for document in documents}
    document_ids = list(document_by_id.keys())

    if not document_ids:
        return []

    labs = (
        db.query(models.LabResult)
        .filter(
            models.LabResult.document_id.in_(document_ids),
            # Rows linked as Level-3 duplicate observations describe the
            # same real-world measurement as an earlier row — counting both
            # would plot the same value twice.
            models.LabResult.duplicate_of_lab_result_id.is_(None),
        )
        .all()
    )

    trends = {}

    for lab in labs:
        numeric_value = lab_value_to_float(lab.value)

        # Missing / nil / --- values must never enter trend graphs.
        if numeric_value is None:
            continue

        test_key = (
            lab.canonical_name
            or lab.display_name
            or lab.raw_test_name
            or ""
        ).strip()

        if not test_key:
            continue

        document = document_by_id.get(lab.document_id)

        if not document:
            continue

        display_name = lab.display_name or lab.canonical_name or lab.raw_test_name or test_key
        date = get_best_document_date(document) or ""

        if test_key not in trends:
            trends[test_key] = {
                "test_key": test_key,
                "display_name": display_name,
                "canonical_name": lab.canonical_name,
                "category": lab.category,
                "unit": lab.unit,
                "points": [],
            }

        trends[test_key]["points"].append(
            {
                "document_id": document.id,
                "lab_result_id": lab.id,
                "date": date,
                "value": numeric_value,
                "value_display": str(lab.value).strip(),
                "flag": lab.flag,
                "report_name": document.report_name or document.filename,
                "reference_range": lab.reference_range,
            }
        )

    results = []

    for trend in trends.values():
        points = trend["points"]

        # Sort by clinical date when possible, then document id as a stable fallback.
        def point_sort_key(point):
            raw_date = point.get("date") or ""

            try:
                parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                return (parsed.timestamp(), point.get("document_id") or 0)
            except Exception:
                return (0, point.get("document_id") or 0)

        points.sort(key=point_sort_key)

        # Only the 5 most recent real numeric points.
        points = points[-5:]

        if not points:
            continue

        latest = points[-1]
        previous = points[-2] if len(points) >= 2 else None
        delta = None

        if previous:
            delta = round(latest["value"] - previous["value"], 2)

        trend["points"] = points
        trend["latest"] = latest
        trend["previous"] = previous
        trend["delta"] = delta

        results.append(trend)

    results.sort(
        key=lambda trend: (
            0
            if trend["latest"].get("flag")
            and str(trend["latest"].get("flag")).strip().lower() not in {"", "normal", "none", "ok"}
            else 1,
            trend["display_name"] or "",
        )
    )

    return results

@app.post("/patient-events")
def create_patient_event(
    payload: PatientEventCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    event = models.PatientEvent(
        patient_id=patient.id,
        doctor_user_id=current_user.id,
        event_type=payload.event_type,
        status=payload.status,
        title=payload.title,
        description=payload.description,
        hospital_name=payload.hospital_name or current_user.hospital_name,
        department=payload.department or current_user.department,
        admitted_at=payload.admitted_at,
        discharged_at=payload.discharged_at,
        created_by_user_id=current_user.id,
        discharged_by_user_id=None,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return serialize_patient_event(event)


@app.post("/patient-events/{event_id}/discharge")
def discharge_patient_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    event = db.query(models.PatientEvent).filter(models.PatientEvent.id == event_id).first()

    if not event:
        raise HTTPException(status_code=404, detail="Patient event not found")

    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, event.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    event.status = "discharged"
    event.discharged_at = now_iso()
    event.discharged_by_user_id = current_user.id

    db.commit()
    db.refresh(event)


# ── Care Partner endpoints ────────────────────────────────────────────────────


@app.get("/my/care-partner-code")
def get_care_partner_code(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )

    if not code_record:
        code = _generate_unique_care_partner_code(db)
        code_record = models.PatientCarePartnerCode(
            patient_id=patient.id,
            code=code,
            created_at=now_iso(),
        )
        db.add(code_record)
        db.commit()
        db.refresh(code_record)

    return {"code": code_record.code, "created_at": code_record.created_at}


@app.post("/my/care-partner-code/regenerate")
def regenerate_care_partner_code(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )

    new_code = _generate_unique_care_partner_code(db)

    if code_record:
        code_record.code = new_code
        code_record.created_at = now_iso()
    else:
        code_record = models.PatientCarePartnerCode(
            patient_id=patient.id,
            code=new_code,
            created_at=now_iso(),
        )
        db.add(code_record)

    db.commit()
    db.refresh(code_record)

    log = models.AdminActionLog(
        admin_user_id=current_user.id,
        action="patient_code_regenerated",
        patient_id=patient.id,
        timestamp=now_iso(),
        details=f"Patient regenerated their access code. New code: {new_code}",
    )
    db.add(log)
    db.commit()

    return {"code": code_record.code, "created_at": code_record.created_at}


class EmergencyAccessSettingRequest(BaseModel):
    emergency_search_enabled: bool


class EmergencyContactPayload(BaseModel):
    name: str
    relationship: str | None = None
    phone: str | None = None
    notes: str | None = None


@app.get("/my/settings/emergency-access")
def get_emergency_access_setting(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return {
        "emergency_search_enabled": bool(patient.emergency_search_enabled),
        "updated_at": patient.emergency_search_updated_at,
    }


@app.put("/my/settings/emergency-access")
def update_emergency_access_setting(
    payload: EmergencyAccessSettingRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    old_value = bool(patient.emergency_search_enabled)
    new_value = payload.emergency_search_enabled

    patient.emergency_search_enabled = 1 if new_value else 0
    patient.emergency_search_updated_at = now_iso()

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None

    action = "patient_enabled_emergency_discoverability" if new_value else "patient_disabled_emergency_discoverability"
    _add_emergency_audit(
        db,
        action=action,
        emergency_user_id=current_user.id,
        patient_id=patient.id,
        ip_address=ip,
        user_agent=ua,
        details=f"old={old_value} new={new_value}",
    )

    # If disabling, revoke all active emergency sessions for this patient
    if not new_value and old_value:
        now_str = now_iso()
        active_sessions = (
            db.query(models.EmergencyAccessSession)
            .filter(
                models.EmergencyAccessSession.patient_id == patient.id,
                models.EmergencyAccessSession.closed_at.is_(None),
                models.EmergencyAccessSession.revoked_at.is_(None),
                models.EmergencyAccessSession.expires_at > now_str,
            )
            .all()
        )
        for s in active_sessions:
            s.revoked_at = now_iso()
            s.revoked_reason = "patient_disabled_emergency_discoverability"
            _add_emergency_audit(
                db,
                action="active_emergency_sessions_revoked",
                emergency_user_id=current_user.id,
                patient_id=patient.id,
                session_id=s.id,
                ip_address=ip,
                user_agent=ua,
                details=f"session_id={s.id} revoked_by_patient",
            )

    db.commit()
    db.refresh(patient)

    return {
        "emergency_search_enabled": bool(patient.emergency_search_enabled),
        "updated_at": patient.emergency_search_updated_at,
    }


def _contact_dict(c: models.EmergencyContact) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "relationship": c.contact_relationship,
        "phone": c.phone,
        "notes": c.notes,
        "created_at": c.created_at,
    }


@app.get("/my/settings/emergency-contacts")
def get_emergency_contacts(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    contacts = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient.id)
        .order_by(models.EmergencyContact.id)
        .all()
    )
    return [_contact_dict(c) for c in contacts]


@app.post("/my/settings/emergency-contacts")
def create_emergency_contact(
    payload: EmergencyContactPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    existing = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient.id)
        .count()
    )
    if existing >= 5:
        raise HTTPException(status_code=400, detail="Maximum of 5 emergency contacts allowed")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Contact name is required")
    contact = models.EmergencyContact(
        patient_id=patient.id,
        name=payload.name.strip(),
        contact_relationship=payload.relationship,
        phone=payload.phone,
        notes=payload.notes,
        created_at=now_iso(),
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _contact_dict(contact)


@app.put("/my/settings/emergency-contacts/{contact_id}")
def update_emergency_contact(
    contact_id: int,
    payload: EmergencyContactPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    contact = db.query(models.EmergencyContact).filter(
        models.EmergencyContact.id == contact_id,
        models.EmergencyContact.patient_id == patient.id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Contact name is required")
    contact.name = payload.name.strip()
    contact.contact_relationship = payload.relationship
    contact.phone = payload.phone
    contact.notes = payload.notes
    db.commit()
    db.refresh(contact)
    return _contact_dict(contact)


@app.delete("/my/settings/emergency-contacts/{contact_id}")
def delete_emergency_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    contact = db.query(models.EmergencyContact).filter(
        models.EmergencyContact.id == contact_id,
        models.EmergencyContact.patient_id == patient.id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"ok": True}


@app.get("/my/care-partners")
def get_my_care_partners(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)

    if not patient:
        return []

    links = (
        db.query(models.CarePartnerPatientLink)
        .filter(models.CarePartnerPatientLink.patient_id == patient.id)
        .all()
    )

    return [
        {
            "care_partner_user_id": link.care_partner_user.id,
            "care_partner_name": link.care_partner_user.full_name,
            "care_partner_email": link.care_partner_user.email,
            "linked_at": link.linked_at,
        }
        for link in links
    ]


@app.get("/my/dependants")
def get_my_dependants(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("care_partner")),
):
    links = (
        db.query(models.CarePartnerPatientLink)
        .filter(models.CarePartnerPatientLink.care_partner_user_id == current_user.id)
        .all()
    )

    return [
        {
            "patient_id": link.patient.id,
            "full_name": link.patient.full_name,
            "date_of_birth": link.patient.date_of_birth,
            "sex": link.patient.sex,
            "linked_at": link.linked_at,
        }
        for link in links
    ]


@app.get("/my/shared-pages")
def get_my_shared_pages(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("care_partner")),
):
    shares = (
        db.query(models.SharedStructuredPage)
        .filter(models.SharedStructuredPage.care_partner_user_id == current_user.id)
        .all()
    )

    result = []
    for share in shares:
        doc = share.document
        patient = doc.patient if doc else None
        result.append(
            {
                "document_id": doc.id if doc else None,
                "patient_full_name": patient.full_name if patient else None,
                "section": doc.section if doc else None,
                "test_date": doc.test_date if doc else None,
                "report_name": doc.report_name if doc else None,
                "filename": doc.filename if doc else None,
                "shared_at": share.shared_at,
            }
        )

    return result


@app.get("/documents/{document_id}/shares")
def get_document_shares(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    shares = (
        db.query(models.SharedStructuredPage)
        .filter(models.SharedStructuredPage.document_id == document_id)
        .all()
    )

    return [
        {
            "care_partner_user_id": share.care_partner_user.id,
            "care_partner_name": share.care_partner_user.full_name,
            "care_partner_email": share.care_partner_user.email,
            "shared_at": share.shared_at,
        }
        for share in shares
    ]


class ShareDocumentRequest(BaseModel):
    care_partner_user_id: int


@app.post("/documents/{document_id}/share")
def share_document(
    document_id: int,
    payload: ShareDocumentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    patient = get_patient_for_user(db, current_user.id)

    link = (
        db.query(models.CarePartnerPatientLink)
        .filter(
            models.CarePartnerPatientLink.care_partner_user_id == payload.care_partner_user_id,
            models.CarePartnerPatientLink.patient_id == patient.id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=400, detail="This person is not your care partner.")

    existing = (
        db.query(models.SharedStructuredPage)
        .filter(
            models.SharedStructuredPage.document_id == document_id,
            models.SharedStructuredPage.care_partner_user_id == payload.care_partner_user_id,
        )
        .first()
    )

    if not existing:
        share = models.SharedStructuredPage(
            document_id=document_id,
            care_partner_user_id=payload.care_partner_user_id,
            shared_by_patient_user_id=current_user.id,
            shared_at=now_iso(),
        )
        db.add(share)
        db.commit()

    return {"ok": True}


@app.delete("/documents/{document_id}/share/{care_partner_user_id}")
def unshare_document(
    document_id: int,
    care_partner_user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    share = (
        db.query(models.SharedStructuredPage)
        .filter(
            models.SharedStructuredPage.document_id == document_id,
            models.SharedStructuredPage.care_partner_user_id == care_partner_user_id,
        )
        .first()
    )

    if share:
        db.delete(share)
        db.commit()

    return {"ok": True}


# ---------------------------------------------------------------------------
# ADMIN PORTAL — scoped to admin's department + hospital
# ---------------------------------------------------------------------------

def _validate_doctor_in_admin_scope(admin_user, doctor) -> None:
    if admin_user.department and doctor.department != admin_user.department:
        raise HTTPException(status_code=403, detail="Doctor is not in your department.")
    if admin_user.hospital_name and doctor.hospital_name != admin_user.hospital_name:
        raise HTTPException(status_code=403, detail="Doctor is not in your hospital.")


@app.get("/admin/patients/search")
def admin_search_patients(
    q: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    if not q.strip():
        return []
    term = f"%{q.strip()}%"
    patients = (
        db.query(models.Patient)
        .outerjoin(models.PatientCarePartnerCode, models.PatientCarePartnerCode.patient_id == models.Patient.id)
        .filter(
            or_(
                models.Patient.full_name.ilike(term),
                models.PatientCarePartnerCode.code.ilike(term),
            )
        )
        .limit(30)
        .all()
    )
    results = []
    for p in patients:
        code_rec = db.query(models.PatientCarePartnerCode).filter(
            models.PatientCarePartnerCode.patient_id == p.id
        ).first()
        results.append({
            "id": p.id,
            "full_name": p.full_name,
            "date_of_birth": p.date_of_birth,
            "cnp": _mask_cnp(p.cnp),
            "patient_identifier": p.patient_identifier,
            "care_partner_code": code_rec.code if code_rec else None,
        })
    return results


@app.get("/admin/doctors")
def admin_get_doctors(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    query = db.query(models.User).filter(models.User.role == "doctor")
    if current_user.department:
        query = query.filter(models.User.department == current_user.department)
    if current_user.hospital_name:
        query = query.filter(models.User.hospital_name == current_user.hospital_name)
    doctors = query.all()

    result = []
    for doc in doctors:
        current_count = (
            db.query(models.DoctorPatientAccess)
            .filter(
                models.DoctorPatientAccess.doctor_user_id == doc.id,
                models.DoctorPatientAccess.is_active == 1,
            )
            .count()
        )
        result.append(
            {
                "id": doc.id,
                "full_name": doc.full_name,
                "email": doc.email,
                "department": doc.department,
                "hospital_name": doc.hospital_name,
                "current_patient_count": current_count,
            }
        )
    return result


@app.get("/admin/doctors/{doctor_id}")
def admin_get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctor = db.query(models.User).filter(models.User.id == doctor_id, models.User.role == "doctor").first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    _validate_doctor_in_admin_scope(current_user, doctor)

    current_count = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .count()
    )
    historical_count = (
        db.query(models.DoctorPatientAccess)
        .filter(models.DoctorPatientAccess.doctor_user_id == doctor_id)
        .count()
    )
    return {
        "id": doctor.id,
        "full_name": doctor.full_name,
        "email": doctor.email,
        "department": doctor.department,
        "hospital_name": doctor.hospital_name,
        "current_patient_count": current_count,
        "historical_assignment_count": historical_count,
    }


@app.get("/admin/doctors/{doctor_id}/current-patients")
def admin_doctor_current_patients(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctor = db.query(models.User).filter(models.User.id == doctor_id, models.User.role == "doctor").first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    _validate_doctor_in_admin_scope(current_user, doctor)

    assignments = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .all()
    )
    return [
        {
            "assignment_id": a.id,
            "patient_id": a.patient.id,
            "full_name": a.patient.full_name,
            "date_of_birth": a.patient.date_of_birth,
            "cnp": _mask_cnp(a.patient.cnp),
            "patient_identifier": a.patient.patient_identifier,
            "assigned_at": a.granted_at,
        }
        for a in assignments
    ]


@app.get("/admin/doctors/{doctor_id}/patient-history")
def admin_doctor_patient_history(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctor = db.query(models.User).filter(models.User.id == doctor_id, models.User.role == "doctor").first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    _validate_doctor_in_admin_scope(current_user, doctor)

    assignments = (
        db.query(models.DoctorPatientAccess)
        .filter(models.DoctorPatientAccess.doctor_user_id == doctor_id)
        .order_by(models.DoctorPatientAccess.granted_at.desc())
        .all()
    )
    return [
        {
            "assignment_id": a.id,
            "patient_id": a.patient.id,
            "full_name": a.patient.full_name,
            "date_of_birth": a.patient.date_of_birth,
            "cnp": _mask_cnp(a.patient.cnp),
            "patient_identifier": a.patient.patient_identifier,
            "assigned_at": a.granted_at,
            "ended_at": a.ended_at,
            "is_active": bool(a.is_active),
        }
        for a in assignments
    ]


@app.get("/admin/patients/{patient_id}/assignments")
def admin_get_patient_assignments(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    assignments = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.patient_id == patient_id,
            models.DoctorPatientAccess.is_active == 1,
        )
        .all()
    )
    return [{"doctor_user_id": a.doctor_user_id} for a in assignments]


class BatchAssignRequest(BaseModel):
    patient_id: int
    doctor_user_ids: list[int]


@app.post("/admin/assignments/batch")
def admin_batch_assign(
    payload: BatchAssignRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")

    created = 0
    skipped = 0
    for doctor_id in payload.doctor_user_ids:
        doctor = db.query(models.User).filter(models.User.id == doctor_id, models.User.role == "doctor").first()
        if not doctor:
            raise HTTPException(status_code=400, detail=f"Doctor {doctor_id} not found.")
        _validate_doctor_in_admin_scope(current_user, doctor)

        existing = (
            db.query(models.DoctorPatientAccess)
            .filter(
                models.DoctorPatientAccess.doctor_user_id == doctor_id,
                models.DoctorPatientAccess.patient_id == payload.patient_id,
                models.DoctorPatientAccess.is_active == 1,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        link = models.DoctorPatientAccess(
            doctor_user_id=doctor_id,
            patient_id=payload.patient_id,
            granted_by_user_id=current_user.id,
            granted_at=now_iso(),
            is_active=1,
        )
        db.add(link)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped}


@app.post("/admin/assignments/{assignment_id}/end")
def admin_end_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    assignment = db.query(models.DoctorPatientAccess).filter(models.DoctorPatientAccess.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    doctor = db.query(models.User).filter(models.User.id == assignment.doctor_user_id).first()
    if doctor:
        _validate_doctor_in_admin_scope(current_user, doctor)

    if not assignment.is_active:
        raise HTTPException(status_code=400, detail="Assignment is already ended.")

    assignment.is_active = 0
    assignment.ended_at = now_iso()
    db.commit()
    return {"ok": True}


class LinkPatientRequest(BaseModel):
    care_partner_code: str


@app.post("/my/link-patient")
def link_patient(
    payload: LinkPatientRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("care_partner")),
):
    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.code == payload.care_partner_code.strip().upper())
        .first()
    )

    if not code_record:
        raise HTTPException(status_code=400, detail="Invalid access code.")

    existing = (
        db.query(models.CarePartnerPatientLink)
        .filter(
            models.CarePartnerPatientLink.care_partner_user_id == current_user.id,
            models.CarePartnerPatientLink.patient_id == code_record.patient_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="You are already linked to this patient.")

    link = models.CarePartnerPatientLink(
        care_partner_user_id=current_user.id,
        patient_id=code_record.patient_id,
        linked_at=now_iso(),
    )
    db.add(link)
    db.commit()

    patient = code_record.patient
    return {
        "patient_id": patient.id,
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth,
        "sex": patient.sex,
        "linked_at": link.linked_at,
    }

    return serialize_patient_event(event)


@app.get("/admin/analyte-gaps")
def admin_analyte_gaps(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """
    Return distinct canonical_name values from lab_results that have no match
    in the Python lab catalog, ordered by occurrence count descending.
    """
    rows = (
        db.query(
            models.LabResult.canonical_name,
            func.count(models.LabResult.id).label("count"),
            func.max(models.LabResult.document_id).label("last_document_id"),
        )
        .filter(models.LabResult.canonical_name.isnot(None))
        .filter(models.LabResult.canonical_name != "")
        .group_by(models.LabResult.canonical_name)
        .order_by(func.count(models.LabResult.id).desc())
        .all()
    )

    gaps = []
    for row in rows:
        canonical = row.canonical_name
        if find_lab_definition(canonical) is not None:
            continue

        raw_names_rows = (
            db.query(models.LabResult.raw_test_name)
            .filter(
                models.LabResult.canonical_name == canonical,
                models.LabResult.raw_test_name.isnot(None),
            )
            .distinct()
            .limit(6)
            .all()
        )
        raw_names = [r.raw_test_name for r in raw_names_rows if r.raw_test_name]

        gaps.append({
            "canonical_name": canonical,
            "raw_names": raw_names,
            "count": row.count,
            "last_document_id": row.last_document_id,
        })

    return gaps


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

VALID_MED_STATUSES = {"active", "as_needed", "paused", "stopped"}


def serialize_medication(med: models.PatientMedication) -> dict:
    official_info = None
    if med.official_info_json:
        try:
            official_info = json.loads(med.official_info_json)
        except Exception:
            pass
    return {
        "id": med.id,
        "patient_id": med.patient_id,
        "name": med.name,
        "dose_strength": med.dose_strength,
        "frequency": med.frequency,
        "reason": med.reason,
        "status": med.status,
        "route_form": med.route_form,
        "start_date": med.start_date,
        "stop_date": med.stop_date,
        "prescriber": med.prescriber,
        "extra_info": med.extra_info,
        "is_uncertain": bool(med.is_uncertain),
        "created_at": med.created_at,
        "updated_at": med.updated_at,
        "created_by": {
            "id": med.created_by_user.id,
            "full_name": med.created_by_user.full_name,
        } if med.created_by_user else None,
        "official_match_status": med.official_match_status,
        "official_source_name": med.official_source_name,
        "official_source_url": med.official_source_url,
        "rxnorm_rxcui": med.rxnorm_rxcui,
        "dailymed_setid": med.dailymed_setid,
        "official_info": official_info,
        "official_retrieved_at": med.official_retrieved_at,
        "official_label_date": med.official_label_date,
    }


def _apply_official_info(db: Session, medication_id: int) -> None:
    """Background task: fetch official info and persist it."""
    try:
        med = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == medication_id
        ).first()
        if not med:
            return
        result = lookup_medication(med.name)
        med.official_match_status = result["official_match_status"]
        med.official_source_name = result["official_source_name"]
        med.official_source_url = result["official_source_url"]
        med.rxnorm_rxcui = result["rxnorm_rxcui"]
        med.dailymed_setid = result["dailymed_setid"]
        med.official_info_json = result["official_info_json"]
        med.official_retrieved_at = result["official_retrieved_at"]
        med.official_label_date = result["official_label_date"]
        db.commit()
    except Exception:
        pass


class MedicationCreateRequest(BaseModel):
    name: str
    dose_strength: str | None = None
    frequency: str | None = None
    reason: str | None = None
    status: str = "active"
    route_form: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    prescriber: str | None = None
    extra_info: str | None = None
    is_uncertain: bool = False


class MedicationUpdateRequest(BaseModel):
    name: str | None = None
    dose_strength: str | None = None
    frequency: str | None = None
    reason: str | None = None
    status: str | None = None
    route_form: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    prescriber: str | None = None
    extra_info: str | None = None
    is_uncertain: bool | None = None


class MedicationRxcuiSelectRequest(BaseModel):
    rxcui: str
    name: str


# --- Patient endpoints ---

@app.get("/my/medications")
def list_my_medications(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)
    meds = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient.id)
        .order_by(models.PatientMedication.id.desc())
        .all()
    )
    return [serialize_medication(m) for m in meds]


@app.post("/my/medications", status_code=201)
def create_medication(
    payload: MedicationCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Medication name is required.")

    status = payload.status.strip().lower()
    if status not in VALID_MED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(VALID_MED_STATUSES)}")

    med = models.PatientMedication(
        patient_id=patient.id,
        created_by_user_id=current_user.id,
        name=name,
        dose_strength=payload.dose_strength,
        frequency=payload.frequency,
        reason=payload.reason,
        status=status,
        route_form=payload.route_form,
        start_date=payload.start_date,
        stop_date=payload.stop_date,
        prescriber=payload.prescriber,
        extra_info=payload.extra_info,
        is_uncertain=1 if payload.is_uncertain else 0,
        created_at=now_iso(),
        official_match_status="pending",
    )
    db.add(med)
    db.commit()
    db.refresh(med)

    background_tasks.add_task(_apply_official_info, db, med.id)

    return serialize_medication(med)


@app.get("/my/medications/{medication_id}")
def get_my_medication(
    medication_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    return serialize_medication(med)


@app.put("/my/medications/{medication_id}")
def update_medication(
    medication_id: int,
    payload: MedicationUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")

    name_changed = False

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Medication name cannot be empty.")
        if new_name != med.name:
            med.name = new_name
            name_changed = True

    if payload.dose_strength is not None:
        med.dose_strength = payload.dose_strength
    if payload.frequency is not None:
        med.frequency = payload.frequency
    if payload.reason is not None:
        med.reason = payload.reason
    if payload.status is not None:
        s = payload.status.strip().lower()
        if s not in VALID_MED_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status.")
        med.status = s
    if payload.route_form is not None:
        med.route_form = payload.route_form
    if payload.start_date is not None:
        med.start_date = payload.start_date
    if payload.stop_date is not None:
        med.stop_date = payload.stop_date
    if payload.prescriber is not None:
        med.prescriber = payload.prescriber
    if payload.extra_info is not None:
        med.extra_info = payload.extra_info
    if payload.is_uncertain is not None:
        med.is_uncertain = 1 if payload.is_uncertain else 0

    med.updated_by_user_id = current_user.id
    med.updated_at = now_iso()

    if name_changed:
        med.official_match_status = "pending"
        med.official_info_json = None
        med.rxnorm_rxcui = None
        med.dailymed_setid = None
        med.official_retrieved_at = None
        background_tasks.add_task(_apply_official_info, db, med.id)

    db.commit()
    db.refresh(med)
    return serialize_medication(med)


@app.delete("/my/medications/{medication_id}")
def delete_medication(
    medication_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    db.delete(med)
    db.commit()
    return {"ok": True}


@app.post("/my/medications/{medication_id}/refresh-official-info")
def refresh_medication_official_info(
    medication_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="external_lookup")),
):
    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    med.official_match_status = "pending"
    db.commit()
    background_tasks.add_task(_apply_official_info, db, med.id)
    return {"ok": True, "status": "refreshing"}


@app.post("/my/medications/{medication_id}/select-rxcui")
def select_medication_rxcui(
    medication_id: int,
    payload: MedicationRxcuiSelectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    """Patient explicitly selects one RxCUI from multiple candidates."""
    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    med.official_match_status = "pending"
    db.commit()
    background_tasks.add_task(_fetch_and_apply_rxcui, db, med.id, payload.rxcui, payload.name)
    return {"ok": True}


def _fetch_and_apply_rxcui(db: Session, medication_id: int, rxcui: str, name: str) -> None:
    try:
        med = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == medication_id
        ).first()
        if not med:
            return
        result = lookup_medication(name, rxcui_override=rxcui)
        med.official_match_status = result["official_match_status"]
        med.official_source_name = result["official_source_name"]
        med.official_source_url = result["official_source_url"]
        med.rxnorm_rxcui = result["rxnorm_rxcui"]
        med.dailymed_setid = result["dailymed_setid"]
        med.official_info_json = result["official_info_json"]
        med.official_retrieved_at = result["official_retrieved_at"]
        med.official_label_date = result["official_label_date"]
        db.commit()
    except Exception:
        pass


# --- Doctor / admin read-only endpoints ---

@app.get("/patients/{patient_id}/medications")
def get_patient_medications(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden.")
    meds = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient_id)
        .order_by(models.PatientMedication.id.desc())
        .all()
    )
    return [serialize_medication(m) for m in meds]


@app.get("/patients/{patient_id}/medications/{medication_id}")
def get_patient_medication(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden.")
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient_id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    return serialize_medication(med)


# ─────────────────────────────────────────────────────────────────────────────
# EMERGENCY ACCESS PORTAL
# ─────────────────────────────────────────────────────────────────────────────

EMERGENCY_SESSION_MINUTES = 30


def require_emergency_role():
    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in ("emergency_worker", "admin"):
            raise HTTPException(status_code=403, detail="Emergency access only")
        return current_user
    return dependency


def _get_active_emergency_session(
    db: Session,
    session_id: int,
    user_id: int,
) -> models.EmergencyAccessSession | None:
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == user_id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
        )
        .first()
    )
    if not session:
        return None
    if session.expires_at < now_iso():
        return None
    return session


def _add_emergency_audit(
    db: Session,
    action: str,
    emergency_user_id: int | None = None,
    patient_id: int | None = None,
    session_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: str | None = None,
) -> None:
    db.add(
        models.EmergencyAuditLog(
            emergency_user_id=emergency_user_id,
            patient_id=patient_id,
            session_id=session_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            timestamp=now_iso(),
        )
    )


def _mask_cnp(cnp: str | None) -> str | None:
    if not cnp:
        return None
    n = len(cnp)
    if n <= 4:
        return "*" * n
    return cnp[:2] + "*" * (n - 4) + cnp[-2:]


def _serialize_emergency_search_result(patient, code_record) -> dict:
    masked_id = _mask_cnp(patient.cnp)
    if not masked_id and patient.patient_identifier:
        raw = patient.patient_identifier
        masked_id = raw[:3] + "***" if len(raw) > 3 else "***"
    return {
        "id": patient.id,
        "full_name": patient.full_name,
        "age": patient.age,
        "sex": patient.sex,
        "bragi_code": code_record.code if code_record else None,
        "masked_identifier": masked_id,
    }


class EmergencySessionCreateRequest(BaseModel):
    patient_id: int
    reason: str
    reason_note: str | None = None


class EmergencySearchRequest(BaseModel):
    type: str
    q: str


def _run_emergency_search(type: str, q: str, request: Request, db: Session, current_user) -> list[dict]:
    q = q.strip()
    if not q:
        return []

    results: list[dict] = []

    if type == "code":
        term = q.upper().replace(" ", "")
        code_records = (
            db.query(models.PatientCarePartnerCode)
            .filter(func.upper(models.PatientCarePartnerCode.code).contains(term))
            .limit(20)
            .all()
        )
        for cr in code_records:
            patient = db.query(models.Patient).filter(
                models.Patient.id == cr.patient_id,
                models.Patient.emergency_search_enabled == 1,
            ).first()
            if patient:
                results.append(_serialize_emergency_search_result(patient, cr))
                if len(results) >= 5:
                    break

    elif type == "cnp":
        patient = db.query(models.Patient).filter(
            models.Patient.cnp == q,
            models.Patient.emergency_search_enabled == 1,
        ).first()
        if patient:
            cr = db.query(models.PatientCarePartnerCode).filter(
                models.PatientCarePartnerCode.patient_id == patient.id
            ).first()
            results.append(_serialize_emergency_search_result(patient, cr))

    elif type == "name":
        term = f"%{q.lower()}%"
        patients = (
            db.query(models.Patient)
            .filter(
                func.lower(models.Patient.full_name).like(term),
                models.Patient.emergency_search_enabled == 1,
            )
            .limit(10)
            .all()
        )
        for patient in patients:
            cr = db.query(models.PatientCarePartnerCode).filter(
                models.PatientCarePartnerCode.patient_id == patient.id
            ).first()
            results.append(_serialize_emergency_search_result(patient, cr))

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_patient_search",
        emergency_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        details=f"type={type} q_len={len(q)} results={len(results)}",
    )
    db.commit()

    return results


@app.post("/emergency/search")
def emergency_search_post(
    payload: EmergencySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=60, window_seconds=300, key_prefix="emergency_search")),
):
    """POST form of emergency search — the only path that accepts a CNP
    lookup. CNP travels in the JSON request body, never in a URL query
    string (so it never lands in browser history, server access logs, or
    a proxy/CDN's request-URL logging). This is the endpoint every
    current frontend caller uses, for every search type."""
    return _run_emergency_search(payload.type, payload.q, request, db, current_user)


@app.get("/emergency/search")
def emergency_search(
    type: str = Query(...),
    q: str = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=60, window_seconds=300, key_prefix="emergency_search")),
):
    """Legacy GET form, kept only for `code`/`name` lookups (a Bragi
    care-partner code or a name substring are not direct identifiers the
    same way a national ID is). A CNP is a direct identifier and must
    never be placed in a URL query string — that path is closed here
    unconditionally, independent of which client is calling. Use
    POST /emergency/search for CNP lookups."""
    if type == "cnp":
        raise HTTPException(
            status_code=400,
            detail="CNP search requires POST /emergency/search with a JSON body, not a query string.",
        )
    return _run_emergency_search(type, q, request, db, current_user)


@app.post("/emergency/access-sessions")
def create_emergency_session(
    payload: EmergencySessionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="emergency_session")),
):
    from datetime import timedelta

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient or not patient.emergency_search_enabled:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        _add_emergency_audit(
            db,
            action="emergency_session_denied_patient_not_searchable",
            emergency_user_id=current_user.id,
            patient_id=payload.patient_id if patient else None,
            ip_address=ip,
            user_agent=ua,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="No emergency-searchable patient found.")

    # Return existing active session for same patient — no duplicate tabs
    now_str = now_iso()
    existing = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.patient_id == payload.patient_id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .first()
    )
    if existing:
        cr = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.patient_id == patient.id)
            .first()
        )
        return {
            "id": existing.id,
            "patient_id": existing.patient_id,
            "patient_name": patient.full_name,
            "bragi_code": cr.code if cr else None,
            "reason": existing.reason,
            "started_at": existing.started_at,
            "expires_at": existing.expires_at,
            "existing": True,
        }

    # Enforce max 8 active sessions per emergency worker
    active_count = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .count()
    )
    if active_count >= 8:
        raise HTTPException(status_code=409, detail="Maximum 8 active emergency sessions reached")

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=EMERGENCY_SESSION_MINUTES)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    session = models.EmergencyAccessSession(
        emergency_user_id=current_user.id,
        patient_id=payload.patient_id,
        reason=payload.reason,
        reason_note=payload.reason_note,
        started_at=now.isoformat(),
        expires_at=expires.isoformat(),
        closed_at=None,
        ip_address=ip,
        user_agent=ua,
        created_at=now.isoformat(),
        public_id=generate_public_id("brg-em"),
    )
    db.add(session)
    db.flush()

    _add_emergency_audit(
        db,
        action="emergency_session_started",
        emergency_user_id=current_user.id,
        patient_id=payload.patient_id,
        session_id=session.id,
        ip_address=ip,
        user_agent=ua,
        details=f"reason={payload.reason}",
    )
    db.commit()
    db.refresh(session)

    cr = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )
    return {
        "id": session.id,
        "public_id": session.public_id,
        "patient_id": session.patient_id,
        "patient_name": patient.full_name,
        "bragi_code": cr.code if cr else None,
        "reason": session.reason,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "existing": False,
    }


@app.get("/emergency/access-sessions/active")
def get_active_emergency_sessions(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    from datetime import timezone
    now_str = now_iso()
    sessions = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .order_by(models.EmergencyAccessSession.created_at.asc())
        .all()
    )
    result = []
    for s in sessions:
        patient = db.query(models.Patient).filter(models.Patient.id == s.patient_id).first()
        if not patient or not patient.emergency_search_enabled:
            continue
        cr = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.patient_id == s.patient_id)
            .first()
        )
        expires_dt = datetime.fromisoformat(s.expires_at)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        secs = max(0, int((expires_dt - datetime.now(timezone.utc)).total_seconds()))
        result.append({
            "id": s.id,
            "patient_id": s.patient_id,
            "patient_name": patient.full_name,
            "bragi_code": cr.code if cr else None,
            "started_at": s.started_at,
            "expires_at": s.expires_at,
            "seconds_remaining": secs,
            "reason": s.reason,
        })
    _add_emergency_audit(
        db,
        action="emergency_workspace_opened",
        emergency_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return result


@app.get("/emergency/sessions/by-public-id/{public_id}")
def get_emergency_session_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.public_id == public_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"id": session.id, "public_id": session.public_id}


@app.get("/emergency/access-sessions/{session_id}")
def get_emergency_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    is_active = session.closed_at is None and session.expires_at > now_iso()
    return {
        "id": session.id,
        "patient_id": session.patient_id,
        "reason": session.reason,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "closed_at": session.closed_at,
        "is_active": is_active,
    }


@app.post("/emergency/access-sessions/{session_id}/close")
def close_emergency_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.closed_at is None:
        session.closed_at = now_iso()
        _add_emergency_audit(
            db,
            action="emergency_session_closed_manually",
            emergency_user_id=current_user.id,
            patient_id=session.patient_id,
            session_id=session_id,
        )
        db.commit()

    return {"ok": True}


@app.get("/emergency/patients/{patient_id}")
def emergency_get_patient(
    patient_id: int,
    session_id: int = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    active_session = _get_active_emergency_session(db, session_id, current_user.id)
    if not active_session:
        raise HTTPException(status_code=403, detail="Emergency session expired or not found")
    if active_session.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Session does not cover this patient")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not patient.emergency_search_enabled:
        raise HTTPException(status_code=403, detail="Emergency access is no longer available for this patient.")

    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient_id)
        .order_by(models.PatientMedication.status, models.PatientMedication.name)
        .all()
    )

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .limit(100)
        .all()
    )

    # Latest bloodwork with labs (no extracted text)
    latest_bloodwork = None
    for doc in documents:
        if doc.section == "bloodwork":
            labs = (
                db.query(models.LabResult)
                .filter(models.LabResult.document_id == doc.id)
                .limit(40)
                .all()
            )
            latest_bloodwork = {
                "document_id": doc.id,
                "filename": doc.filename,
                "test_date": doc.test_date,
                "lab_name": doc.lab_name,
                "labs": [
                    {
                        "name": lab.display_name or lab.raw_test_name,
                        "value": lab.value,
                        "unit": lab.unit,
                        "flag": lab.flag,
                        "reference_range": lab.reference_range,
                    }
                    for lab in labs
                ],
            }
            break

    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient_id)
        .first()
    )

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_patient_page_opened",
        emergency_user_id=current_user.id,
        patient_id=patient_id,
        session_id=session_id,
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()

    emergency_contacts = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient_id)
        .order_by(models.EmergencyContact.id)
        .all()
    )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            "bragi_code": code_record.code if code_record else None,
            # CNP intentionally omitted
        },
        "session": {
            "id": active_session.id,
            "started_at": active_session.started_at,
            "expires_at": active_session.expires_at,
            "reason": active_session.reason,
        },
        "medications": [
            {
                "id": m.id,
                "name": m.name,
                "dose_strength": m.dose_strength,
                "frequency": m.frequency,
                "status": m.status,
                "route_form": m.route_form,
                "is_uncertain": bool(m.is_uncertain),
            }
            for m in medications
        ],
        "documents": [
            {
                "id": doc.id,
                "section": doc.section,
                "filename": doc.filename,
                "test_date": doc.test_date or doc.created_at,
                "lab_name": doc.lab_name,
                "report_name": doc.report_name,
                "is_verified": bool(doc.is_verified),
                "created_at": doc.created_at,
            }
            for doc in documents
        ],
        "latest_bloodwork": latest_bloodwork,
        "emergency_contacts": [
            {
                "id": c.id,
                "name": c.name,
                "relationship": c.contact_relationship,
                "phone": c.phone,
                "notes": c.notes,
            }
            for c in emergency_contacts
        ],
    }


@app.get("/emergency/documents/{document_id}")
def emergency_get_document(
    document_id: int,
    session_id: int = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    active_session = _get_active_emergency_session(db, session_id, current_user.id)
    if not active_session:
        raise HTTPException(status_code=403, detail="Emergency session expired or not found")

    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.patient_id != active_session.patient_id:
        raise HTTPException(status_code=403, detail="Document does not belong to this emergency session's patient")

    session_patient = db.query(models.Patient).filter(models.Patient.id == active_session.patient_id).first()
    if not session_patient or not session_patient.emergency_search_enabled:
        raise HTTPException(status_code=403, detail="Emergency access is no longer available for this patient.")

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_document_opened",
        emergency_user_id=current_user.id,
        patient_id=active_session.patient_id,
        session_id=session_id,
        ip_address=ip,
        user_agent=ua,
        details=f"document_id={document_id}",
    )
    db.commit()

    payload = get_document_payload(db, document, labs, audit_logs, current_user=None)
    if payload.get("parsed_data"):
        payload["parsed_data"].pop("cnp", None)
    return payload


# ── Ask Bragi ──────────────────────────────────────────────────────────────
# See BRAGI_ASK_BRAGI_PLAN.md for the full architecture. Feature-flagged
# (ASK_BRAGI_ENABLED, default false) — merging this code does not enable
# it in production; see docs/security/RATE_LIMITING.md's identical
# "activation is a config change, not a deploy" pattern.

def require_ask_bragi_enabled():
    if not ASK_BRAGI_ENABLED:
        raise HTTPException(status_code=404, detail="Ask Bragi is not enabled in this environment.")


class AskBragiConversationCreateRequest(BaseModel):
    # Patients never supply this — their own patient_id is always
    # resolved server-side (see resolve_patient_id_for_new_conversation).
    # Doctors must supply it, validated against a real active
    # DoctorPatientAccess grant, identically to every other doctor-facing
    # patient route in this app.
    patient_id: int | None = None
    # Optional: scope this conversation to one document instead of the
    # full record (see BRAGI_ASK_BRAGI_PLAN.md's scope model).
    document_id: int | None = None


class AskBragiMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Explicit scope toggle from the contextual UI ("This document" /
    # "Full record") — optional; when omitted, the server falls back to
    # keyword-based intent detection (see service.py's
    # _resolve_turn_scope). Only ever WIDENS a document-scoped
    # conversation; has no effect on a patient_record-scoped one.
    requested_scope: str | None = None


def _serialize_ask_bragi_conversation(conversation) -> dict:
    return {
        "id": conversation.id,
        "public_id": conversation.public_id,
        "patient_id": conversation.patient_id,
        "scope": conversation.scope,
        "document_id": conversation.document_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _serialize_ask_bragi_message(message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": json.loads(message.citations_json) if message.citations_json else [],
        "chart": json.loads(message.chart_json) if message.chart_json else None,
        "follow_ups": json.loads(message.follow_ups_json) if message.follow_ups_json else [],
        "status": message.status,
        "scope_used": message.scope_used,
        "created_at": message.created_at,
    }


def _load_ask_bragi_conversation_for_owner(db: Session, conversation_id: int, current_user):
    conversation = (
        db.query(models.AskBragiConversation)
        .filter(models.AskBragiConversation.id == conversation_id)
        .first()
    )
    if not conversation or conversation.owner_user_id != current_user.id or conversation.archived_at:
        # Same non-existence-leaking shape as every other resource lookup
        # in this app (test_idor_regression.py's convention) — a
        # conversation ID that exists but isn't yours reads identically
        # to one that doesn't exist at all.
        raise HTTPException(status_code=404, detail="Conversation not found.")
    # Conversation ownership is NOT the same as current patient access —
    # re-check both independently every time (Priority: "conversation ID
    # is not authorization").
    if not recheck_access(
        db,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        patient_id=conversation.patient_id,
    ):
        raise HTTPException(status_code=403, detail="Access to this patient's record is no longer authorized.")
    return conversation


@app.post("/ask-bragi/conversations")
def create_ask_bragi_conversation(
    payload: AskBragiConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="ask_bragi_conversation")),
):
    try:
        patient_id = resolve_patient_id_for_new_conversation(
            db, current_user=current_user, requested_patient_id=payload.patient_id
        )
    except AskBragiAccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    scope = "patient_record"
    document_id = None
    if payload.document_id is not None:
        try:
            document_id = resolve_document_scope(db, patient_id=patient_id, document_id=payload.document_id)
        except AskBragiAccessDenied as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        scope = "document"

    conversation = models.AskBragiConversation(
        public_id=generate_public_id("brg-chat"),
        owner_user_id=current_user.id,
        patient_id=patient_id,
        scope=scope,
        document_id=document_id,
        owner_role=current_user.role,
        created_at=now_iso(),
    )
    db.add(conversation)
    db.commit()
    return _serialize_ask_bragi_conversation(conversation)


@app.get("/ask-bragi/conversations")
def list_ask_bragi_conversations(
    patient_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    """Without `patient_id`: every conversation this user owns, across
    every patient — used by the patient's own /ask-bragi history and (for
    a doctor) as a fallback. With `patient_id`: only that patient's
    conversations — how a doctor's per-patient history sidebar stays
    scoped to the patient they're actually looking at (BRAGI product
    spec: doctor history must be PATIENT-SCOPED, never a mixed list
    across every patient they've ever asked about). Authorization is
    re-checked here independently of `owner_user_id`, same convention as
    _load_ask_bragi_conversation_for_owner — a doctor whose access to
    this patient has since been revoked gets an empty list, not a 403,
    matching how every other "list what I can currently see" endpoint in
    this app degrades (no existence/authorization signal leaked either
    way).

    Excludes conversations with zero messages: with lazy conversation
    creation (a row is only ever created once a first user message is
    actually sent — see POST /ask-bragi/conversations/{id}/messages and
    /messages/stream), a real zero-message row should no longer occur in
    normal use, but this filter is kept as a defense-in-depth backstop
    (e.g. a client that creates a conversation and then crashes/loses
    connectivity before ever sending a message) so history never shows a
    "New conversation" entry with nothing in it."""
    query = db.query(models.AskBragiConversation).filter(
        models.AskBragiConversation.owner_user_id == current_user.id,
        models.AskBragiConversation.archived_at.is_(None),
        models.AskBragiConversation.messages.any(),
    )
    if patient_id is not None:
        if not recheck_access(
            db,
            requester_user_id=current_user.id,
            requester_role=current_user.role,
            patient_id=patient_id,
        ):
            return []
        query = query.filter(models.AskBragiConversation.patient_id == patient_id)
    conversations = query.order_by(models.AskBragiConversation.id.desc()).all()
    return [_serialize_ask_bragi_conversation(c) for c in conversations]


@app.get("/ask-bragi/conversations/{conversation_id}")
def get_ask_bragi_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    return {
        **_serialize_ask_bragi_conversation(conversation),
        "messages": [_serialize_ask_bragi_message(m) for m in conversation.messages],
    }


@app.delete("/ask-bragi/conversations/{conversation_id}")
def delete_ask_bragi_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    db.delete(conversation)  # cascades to messages — see models.py relationship
    db.commit()
    return {"deleted": True}


@app.post("/ask-bragi/conversations/{conversation_id}/messages")
def send_ask_bragi_message(
    conversation_id: int,
    payload: AskBragiMessageRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="ask_bragi_message")),
):
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)

    prior_messages = list(conversation.messages)
    prior_turns = [(m.role, m.content) for m in prior_messages]

    ctx = AskBragiContext(
        db=db,
        patient_id=conversation.patient_id,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        scope=conversation.scope,
        document_id=conversation.document_id,
    )
    audience = "patient" if current_user.role == "patient" else "doctor"

    try:
        result = run_turn(
            ctx=ctx,
            audience=audience,
            user_message=payload.message,
            prior_turns=prior_turns,
            requested_scope=payload.requested_scope,
        )
    except AskBragiError as exc:
        # Never the raw provider error/secret — a generic, safe message.
        print(f"ASK BRAGI: turn failed for conversation {conversation_id}: {exc}")
        raise HTTPException(status_code=502, detail="Ask Bragi could not process this message. Please try again.")
    except Exception as exc:  # provider SDK exceptions (auth/429/timeout/500/etc.)
        print(f"ASK BRAGI: unexpected error for conversation {conversation_id}: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Ask Bragi could not process this message. Please try again.")

    now = now_iso()
    user_row = models.AskBragiMessage(
        conversation_id=conversation.id,
        role="user",
        content=payload.message,
        created_at=now,
    )
    assistant_row = models.AskBragiMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=result.response.answer,
        citations_json=json.dumps([c.model_dump() for c in result.response.citations]),
        chart_json=json.dumps(result.response.chart.model_dump()) if result.response.chart else None,
        follow_ups_json=json.dumps(result.response.follow_ups),
        status=result.response.status,
        scope_used=result.response.scope_used,
        tool_categories_json=json.dumps(result.tool_categories),
        prompt_version=result.prompt_version,
        tool_schema_version=result.tool_schema_version,
        model=result.model,
        created_at=now_iso(),
    )
    db.add(user_row)
    db.add(assistant_row)
    conversation.updated_at = now_iso()
    if not conversation.title:
        conversation.title = payload.message[:80]
    db.add(conversation)
    db.commit()

    # PHI-free audit/metrics line (counts and categories only — never the
    # question/answer text or raw tool output, per Priority "audit"/"cost
    # controls"). The durable, queryable audit trail is
    # tool_categories_json on the message row itself.
    print(
        f"ASK BRAGI: conversation={conversation.id} user_id={current_user.id} "
        f"tool_rounds={result.tool_rounds} tools={result.tool_categories} "
        f"citations={len(result.response.citations)} dropped_citations={result.response.dropped_citation_count} "
        f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} model={result.model}"
    )

    return _serialize_ask_bragi_message(assistant_row)


def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame. `data` is always a JSON object — never
    raw text — so the frontend has one parsing path for every event type."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/ask-bragi/conversations/{conversation_id}/messages/stream")
async def stream_ask_bragi_message(
    conversation_id: int,
    payload: AskBragiMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor")),
    _flag=Depends(require_ask_bragi_enabled),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="ask_bragi_message")),
):
    """Streaming counterpart to POST .../messages — same authorization,
    same persistence, same validated final content; the only difference
    is the answer text reaches the browser progressively (Server-Sent
    Events) instead of all at once. See run_turn_streaming's own
    docstring for the trust-boundary argument (unchanged from the
    non-streaming route: only the FINAL, fully-validated JSON is ever
    parsed for citations/chart/follow_ups/status).

    Real cancellation: `should_stop` is checked between provider events
    and between tool-call rounds inside run_turn_streaming — a client
    that aborts its fetch (Stop button, navigating away, switching
    patients) closes this connection, `request.is_disconnected()` starts
    returning True, and the provider stream is closed from our side
    (stream.close()) rather than left running unread. A stopped turn is
    NOT persisted — its text never passed citation/chart validation, so
    nothing about it is trustworthy enough to store; the conversation
    simply has no assistant reply for that turn, exactly as if the
    request had never been made.
    """
    conversation = _load_ask_bragi_conversation_for_owner(db, conversation_id, current_user)
    prior_messages = list(conversation.messages)
    prior_turns = [(m.role, m.content) for m in prior_messages]

    ctx = AskBragiContext(
        db=db,
        patient_id=conversation.patient_id,
        requester_user_id=current_user.id,
        requester_role=current_user.role,
        scope=conversation.scope,
        document_id=conversation.document_id,
    )
    audience = "patient" if current_user.role == "patient" else "doctor"

    async def should_stop() -> bool:
        return await request.is_disconnected()

    async def event_stream():
        completed_payload: dict | None = None
        try:
            async for event_name, data in run_turn_streaming(
                ctx=ctx,
                audience=audience,
                user_message=payload.message,
                prior_turns=prior_turns,
                requested_scope=payload.requested_scope,
                should_stop=should_stop,
            ):
                if event_name == "completed":
                    completed_payload = data
                yield _sse(event_name, data)
        except Exception as exc:  # provider SDK exceptions (auth/429/timeout/500/etc.)
            print(f"ASK BRAGI STREAM: unexpected error for conversation {conversation_id}: {type(exc).__name__}")
            yield _sse("error", {"message": "Ask Bragi could not process this message. Please try again."})
            return

        if completed_payload is None:
            return  # stopped or errored — nothing to persist, see docstring above

        now = now_iso()
        user_row = models.AskBragiMessage(
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            created_at=now,
        )
        assistant_row = models.AskBragiMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=completed_payload["answer"],
            citations_json=json.dumps(completed_payload["citations"]),
            chart_json=json.dumps(completed_payload["chart"]) if completed_payload["chart"] else None,
            follow_ups_json=json.dumps(completed_payload["follow_ups"]),
            status=completed_payload["status"],
            scope_used=completed_payload["scope_used"],
            tool_categories_json=json.dumps(completed_payload["tool_categories"]),
            prompt_version=completed_payload["prompt_version"],
            tool_schema_version=completed_payload["tool_schema_version"],
            model=completed_payload["model"],
            created_at=now_iso(),
        )
        db.add(user_row)
        db.add(assistant_row)
        conversation.updated_at = now_iso()
        if not conversation.title:
            conversation.title = payload.message[:80]
        db.add(conversation)
        db.commit()

        # Same PHI-free audit/metrics line as the non-streaming route.
        print(
            f"ASK BRAGI: conversation={conversation.id} user_id={current_user.id} "
            f"tool_rounds={completed_payload.get('tool_rounds')} tools={completed_payload['tool_categories']} "
            f"citations={len(completed_payload['citations'])} "
            f"dropped_citations={completed_payload['dropped_citation_count']} "
            f"input_tokens={completed_payload.get('input_tokens')} output_tokens={completed_payload.get('output_tokens')} "
            f"model={completed_payload['model']}"
        )
        # The message's own real id/created_at only exist after this
        # commit — tell the frontend so it can reconcile its optimistic,
        # in-progress bubble with the persisted row (citation click-
        # through, React key, etc. all key off the real id).
        yield _sse("saved", {"message": _serialize_ask_bragi_message(assistant_row)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx and similar) so deltas flush immediately
            "Connection": "keep-alive",
        },
    )



# ============================================================================
# Interoperability — /admin/interop/* (BRAGI_INTEROP_PLAN.md, Phase 1)
#
# Feature-flagged off by default (INTEROP_FHIR_ENABLED, same pattern as
# ASK_BRAGI_ENABLED above) — merging this code changes nothing for any real
# user until explicitly activated. Every route below is admin-only AND
# checks the flag first. Business logic lives in app/services/interop/;
# these routes are thin — resolve the connection, call the service, shape
# the response, same division of responsibility as the Ask Bragi routes.
# ============================================================================


def _require_interop_enabled():
    if not INTEROP_FHIR_ENABLED:
        raise HTTPException(status_code=404, detail="Interoperability is not enabled on this deployment.")


def _get_interop_connection_or_404(db: Session, connection_id: int) -> models.InteropConnection:
    connection = db.query(models.InteropConnection).filter(models.InteropConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _serialize_interop_connection(connection: models.InteropConnection) -> dict:
    """Never includes secret_ref's ciphertext (secret_ref itself is just an
    opaque pointer, not the secret) — safe to return to any admin caller."""
    return {
        "id": connection.id,
        "public_id": connection.public_id,
        "name": connection.name,
        "connector_type": connection.connector_type,
        "status": connection.status,
        "base_url": connection.base_url,
        "fhir_version": connection.fhir_version,
        "allow_private_network": connection.allow_private_network,
        "auth_type": connection.auth_type,
        "auth_config": json.loads(connection.auth_config_json or "{}"),
        "has_secret": bool(connection.secret_ref),
        "patient_identity": json.loads(connection.patient_identity_json or "{}"),
        "capabilities": json.loads(connection.capabilities_json or "{}"),
        "capabilities_discovered_at": connection.capabilities_discovered_at,
        "terminology_overrides": json.loads(connection.terminology_overrides_json or "{}"),
        "sync_config": json.loads(connection.sync_config_json or "{}"),
        "version": connection.version,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


class InteropConnectionCreateRequest(BaseModel):
    name: str
    base_url: str
    connector_type: str = "fhir"
    allow_private_network: bool = False
    patient_identity_primary_system: str | None = None


class InteropConnectionUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_type: str | None = None
    auth_config: dict | None = None
    patient_identity: dict | None = None
    terminology_overrides: dict | None = None
    sync_config: dict | None = None
    change_reason: str | None = None


class InteropSecretSetRequest(BaseModel):
    secret_plaintext: str


class InteropIdentityLinkRequest(BaseModel):
    patient_id: int
    identifier_system: str
    identifier_value: str


class InteropTerminologyApproveRequest(BaseModel):
    target_canonical_name: str
    target_display_name: str
    target_category: str | None = None
    target_unit: str | None = None


class InteropProfileImportRequest(BaseModel):
    profile: dict


@app.get("/admin/interop/templates")
def list_interop_templates(current_user=Depends(require_role("admin"))):
    _require_interop_enabled()
    return {
        "templates": interop_templates.CONNECTOR_TEMPLATES,
        "unimplemented_connection_types": interop_templates.UNIMPLEMENTED_CONNECTION_TYPES,
    }


@app.post("/admin/interop/connections")
def create_interop_connection(
    payload: InteropConnectionCreateRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    _require_interop_enabled()
    if payload.allow_private_network and IS_PRODUCTION:
        raise HTTPException(
            status_code=400,
            detail="allow_private_network cannot be set in production — this is reserved for local sandbox/test connections.",
        )
    identity_json = json.dumps(
        {"primary_system": payload.patient_identity_primary_system} if payload.patient_identity_primary_system else {}
    )
    connection = models.InteropConnection(
        public_id=generate_public_id("interop"),
        name=payload.name,
        connector_type=payload.connector_type,
        status="draft",
        base_url=payload.base_url,
        allow_private_network=payload.allow_private_network,
        auth_type="none",
        patient_identity_json=identity_json,
        created_by_user_id=current_user.id,
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@app.get("/admin/interop/connections")
def list_interop_connections(current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connections = db.query(models.InteropConnection).order_by(models.InteropConnection.id.desc()).all()
    return {"connections": [_serialize_interop_connection(c) for c in connections]}


@app.get("/admin/interop/connections/{connection_id}")
def get_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    return _serialize_interop_connection(_get_interop_connection_or_404(db, connection_id))


@app.patch("/admin/interop/connections/{connection_id}")
def update_interop_connection(
    connection_id: int,
    payload: InteropConnectionUpdateRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P64 — configuration versioning: every update bumps `version` and can
    record a change_reason; nothing here mutates an ACTIVE connection's
    behavior mid-sync (a running sync reads its own connection row once at
    the start)."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    if payload.name is not None:
        connection.name = payload.name
    if payload.base_url is not None:
        connection.base_url = payload.base_url
    if payload.auth_type is not None:
        if payload.auth_type not in interop_auth_providers.SUPPORTED_AUTH_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown auth_type. Supported: {interop_auth_providers.SUPPORTED_AUTH_TYPES}")
        connection.auth_type = payload.auth_type
    if payload.auth_config is not None:
        connection.auth_config_json = json.dumps(payload.auth_config)
    if payload.patient_identity is not None:
        connection.patient_identity_json = json.dumps(payload.patient_identity)
    if payload.terminology_overrides is not None:
        # Validate every rule up front — a malformed/unknown-op rule is
        # refused here rather than failing silently mid-sync.
        for _key, rule in payload.terminology_overrides.items():
            try:
                parse_mapping_rule(rule)
            except MappingError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid mapping rule for {_key!r}: {exc}") from exc
        connection.terminology_overrides_json = json.dumps(payload.terminology_overrides)
    if payload.sync_config is not None:
        connection.sync_config_json = json.dumps(payload.sync_config)

    connection.version += 1
    connection.change_reason = payload.change_reason
    connection.updated_at = now_iso()
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@app.post("/admin/interop/connections/{connection_id}/secret")
def set_interop_connection_secret(
    connection_id: int,
    payload: InteropSecretSetRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Stores the secret encrypted (see app/services/interop/crypto.py) and
    points the connection at it by opaque reference. The plaintext is never
    echoed back, never logged, and never included in any export."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    ref = connection.secret_ref or f"interop-secret-{connection.public_id}"
    ciphertext = interop_encrypt_secret(payload.secret_plaintext)
    existing = db.query(models.InteropSecret).filter_by(ref=ref).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.rotated_at = now_iso()
    else:
        db.add(
            models.InteropSecret(
                ref=ref,
                ciphertext=ciphertext,
                created_at=now_iso(),
                created_by_user_id=current_user.id,
            )
        )
    # SessionLocal is autoflush=False (see app/db.py) — without an explicit
    # flush here, the new InteropSecret row and the InteropConnection
    # UPDATE that references it by FK (secret_ref) are both only pending in
    # memory, and nothing guarantees the INSERT is sent before the UPDATE
    # when db.commit() flushes everything together (reproduced for real
    # against Neon: a fresh secret_ref FK violation on first secret-set).
    # Flushing the new secret row first makes the ordering explicit rather
    # than relying on SQLAlchemy's flush-ordering heuristics across two
    # mapped classes with no declared relationship() between them.
    db.flush()
    connection.secret_ref = ref
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return {"ok": True, "has_secret": True}


@app.post("/admin/interop/connections/{connection_id}/generate-signing-key")
def generate_interop_signing_key(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """For smart_backend_services: generates an RSA keypair, stores the
    private key as this connection's secret, and returns the PUBLIC JWK for
    the admin to register with the partner (or host at a JWKS URL) — see
    app/services/interop/jwks.py."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)

    private_pem, public_jwk = interop_jwks.generate_keypair()
    ref = connection.secret_ref or f"interop-secret-{connection.public_id}"
    ciphertext = interop_encrypt_secret(private_pem)
    existing = db.query(models.InteropSecret).filter_by(ref=ref).first()
    if existing:
        existing.ciphertext = ciphertext
        existing.rotated_at = now_iso()
    else:
        db.add(models.InteropSecret(ref=ref, ciphertext=ciphertext, created_at=now_iso(), created_by_user_id=current_user.id))
    db.flush()  # see set_interop_connection_secret's comment — same FK-ordering hazard
    connection.secret_ref = ref
    auth_config = json.loads(connection.auth_config_json or "{}")
    auth_config["jwks"] = {"keys": [public_jwk]}
    connection.auth_config_json = json.dumps(auth_config)
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return {"public_jwk": public_jwk}


def _record_sync_run(db: Session, connection: models.InteropConnection, run_type: str, current_user) -> models.InteropSyncRun:
    run = models.InteropSyncRun(
        connection_id=connection.id,
        run_type=run_type,
        status="running",
        started_at=now_iso(),
        started_by_user_id=current_user.id if current_user else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_sync_run(db: Session, run: models.InteropSyncRun, *, status: str, summary: dict | None = None, error: str | None = None):
    run.status = status
    run.finished_at = now_iso()
    if summary is not None:
        run.summary_json = json.dumps(summary)
    if error is not None:
        run.error_message = error
    db.commit()


@app.post("/admin/interop/connections/{connection_id}/discover")
def discover_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    run = _record_sync_run(db, connection, "discover", current_user)
    try:
        result = fhir_connector.run_discovery(connection)
    except fhir_connector.ConnectorError as exc:
        _finish_sync_run(db, run, status="failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    connection.capabilities_json = json.dumps(result)
    connection.capabilities_discovered_at = result["discovered_at"]
    connection.fhir_version = result["capability"].get("fhir_version")
    if connection.status == "draft":
        connection.status = "discovered"
    if result.get("recommended_auth_type") and connection.auth_type == "none":
        # Recommend only — never silently activate real auth (P8). The
        # admin still has to call PATCH .../secret to supply credentials.
        auth_config = json.loads(connection.auth_config_json or "{}")
        auth_config.setdefault("_recommended_auth_type", result["recommended_auth_type"])
        connection.auth_config_json = json.dumps(auth_config)
    connection.updated_at = now_iso()
    db.commit()

    _finish_sync_run(db, run, status="succeeded", summary={"resources_found": len(result["capability"].get("resources", {}))})
    return {"capability": result, "compatibility_report": result["compatibility_report"]}


@app.post("/admin/interop/connections/{connection_id}/test")
def test_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    run = _record_sync_run(db, connection, "test", current_user)
    stages = fhir_connector.run_connection_test(connection)
    all_passed = all(s.passed for s in stages)
    if all_passed and connection.status == "discovered":
        connection.status = "validated"
        connection.updated_at = now_iso()
        db.commit()
    _finish_sync_run(
        db,
        run,
        status="succeeded" if all_passed else "failed",
        summary={"stages": [{"stage": s.stage, "passed": s.passed, "message": s.message} for s in stages]},
    )
    return {"passed": all_passed, "stages": [{"stage": s.stage, "passed": s.passed, "message": s.message} for s in stages]}


@app.post("/admin/interop/connections/{connection_id}/preview")
def preview_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P66/P67 — shadow sync. Commits no clinical data — see
    fhir_connector.preview_sync's own docstring for exactly what it does
    persist (terminology-review bookkeeping only)."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    run = _record_sync_run(db, connection, "preview", current_user)
    try:
        result = fhir_connector.preview_sync(db, connection)
    except fhir_connector.ConnectorError as exc:
        _finish_sync_run(db, run, status="failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if connection.status == "validated":
        connection.status = "shadow"
        connection.updated_at = now_iso()
        db.commit()
    _finish_sync_run(db, run, status="succeeded", summary=result["summary"])
    return result


@app.post("/admin/interop/connections/{connection_id}/connect")
def connect_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """The real activation step (spec STEP 8) — only reachable after a
    connection has been discovered, tested, and shadow-previewed at least
    once (status == "shadow"). Runs one real, idempotent commit sync."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    if connection.status not in ("shadow", "active", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Connection must be shadow-previewed before connecting (current status: {connection.status}).",
        )
    run = _record_sync_run(db, connection, "sync", current_user)
    try:
        result = fhir_connector.run_sync(db, connection, user_id=current_user.id)
    except fhir_connector.ConnectorError as exc:
        _finish_sync_run(db, run, status="failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    connection.status = "active"
    connection.updated_at = now_iso()
    db.commit()
    _finish_sync_run(db, run, status="succeeded", summary=result["summary"])
    return result


@app.post("/admin/interop/connections/{connection_id}/pause")
def pause_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P69/P70 — stops future sync/token use immediately; never deletes
    already-imported clinical history."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    connection.status = "paused"
    connection.updated_at = now_iso()
    db.commit()
    interop_auth_providers.clear_token_cache(connection.id)
    return _serialize_interop_connection(connection)


@app.get("/admin/interop/connections/{connection_id}/export")
def export_interop_connection(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    return interop_reports.export_connection_profile(connection)


@app.post("/admin/interop/connections/import")
def import_interop_connection(
    payload: InteropProfileImportRequest, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    try:
        draft_fields = interop_reports.import_connection_profile(payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    connection = models.InteropConnection(
        public_id=generate_public_id("interop"),
        status="draft",
        created_by_user_id=current_user.id,
        created_at=now_iso(),
        updated_at=now_iso(),
        **draft_fields,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _serialize_interop_connection(connection)


@app.get("/admin/interop/connections/{connection_id}/report")
def get_interop_partner_report(
    connection_id: int, format: str = "json", current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    cached = json.loads(connection.capabilities_json or "{}")
    compatibility_report = cached.get("compatibility_report")
    if not compatibility_report:
        raise HTTPException(status_code=400, detail="Run discovery before requesting a partner readiness report.")
    report = interop_reports.build_partner_readiness_report(connection, compatibility_report)
    if format == "markdown":
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(interop_reports.render_partner_readiness_markdown(report))
    return report


@app.get("/admin/interop/connections/{connection_id}/diagnostic-bundle")
def get_interop_diagnostic_bundle(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    """P74 — sanitized, PHI-free, secret-free troubleshooting bundle."""
    _require_interop_enabled()
    connection = _get_interop_connection_or_404(db, connection_id)
    recent_runs = (
        db.query(models.InteropSyncRun)
        .filter(models.InteropSyncRun.connection_id == connection_id)
        .order_by(models.InteropSyncRun.id.desc())
        .limit(20)
        .all()
    )
    return interop_reports.build_diagnostic_bundle(connection, recent_runs)


@app.get("/admin/interop/connections/{connection_id}/identity/conflicts")
def list_interop_identity_conflicts(connection_id: int, current_user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    conflicts = (
        db.query(models.InteropIdentityConflict)
        .filter(models.InteropIdentityConflict.connection_id == connection_id, models.InteropIdentityConflict.resolved.is_(False))
        .all()
    )
    return {
        "conflicts": [
            {
                "id": c.id,
                "identifier_system": c.identifier_system,
                "identifier_value": c.identifier_value,
                "existing_link_id": c.existing_link_id,
                "attempted_patient_id": c.attempted_patient_id,
                "detected_at": c.detected_at,
            }
            for c in conflicts
        ]
    }


@app.post("/admin/interop/connections/{connection_id}/identity/links")
def create_interop_identity_link(
    connection_id: int,
    payload: InteropIdentityLinkRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P32/P33 — the only way an identity link is ever created: an explicit
    admin action naming both sides. Refuses (400, with an IDENTITY CONFLICT
    recorded for review) rather than silently overwriting a link that
    already points at a different patient."""
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    try:
        link = interop_identity.create_identity_link(
            db,
            connection_id=connection_id,
            patient_id=payload.patient_id,
            identifier_system=payload.identifier_system,
            identifier_value=payload.identifier_value,
            verified_by_user_id=current_user.id,
        )
    except ValueError as exc:
        db.commit()  # persist the conflict row create_identity_link recorded before raising
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"id": link.id, "patient_id": link.patient_id, "status": link.status}


@app.get("/admin/interop/connections/{connection_id}/terminology")
def list_interop_terminology_mappings(
    connection_id: int, status: str = "pending", current_user=Depends(require_role("admin")), db: Session = Depends(get_db)
):
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    mappings = (
        db.query(models.InteropTerminologyMapping)
        .filter(models.InteropTerminologyMapping.connection_id == connection_id, models.InteropTerminologyMapping.status == status)
        .order_by(models.InteropTerminologyMapping.frequency_seen.desc())
        .all()
    )
    return {
        "mappings": [
            {
                "id": m.id,
                "source_system": m.source_system,
                "source_code": m.source_code,
                "source_display": m.source_display,
                "frequency_seen": m.frequency_seen,
                "status": m.status,
                "example": json.loads(m.example_json) if m.example_json else None,
            }
            for m in mappings
        ]
    }


@app.post("/admin/interop/connections/{connection_id}/terminology/{mapping_id}/approve")
def approve_interop_terminology_mapping(
    connection_id: int,
    mapping_id: int,
    payload: InteropTerminologyApproveRequest,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """P15/P19/P73 — a human-approved local-code override, reused
    automatically by every future sync from this connection (never
    re-guessed per import)."""
    _require_interop_enabled()
    _get_interop_connection_or_404(db, connection_id)
    mapping = (
        db.query(models.InteropTerminologyMapping)
        .filter(models.InteropTerminologyMapping.id == mapping_id, models.InteropTerminologyMapping.connection_id == connection_id)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    mapping.target_canonical_name = payload.target_canonical_name
    mapping.target_display_name = payload.target_display_name
    mapping.target_category = payload.target_category
    mapping.target_unit = payload.target_unit
    mapping.mapping_type = "local_override"
    mapping.status = "approved"
    mapping.approved_at = now_iso()
    mapping.approved_by_user_id = current_user.id
    db.commit()
    return {"ok": True}
