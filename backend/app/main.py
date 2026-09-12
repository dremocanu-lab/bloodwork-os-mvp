import os
import json
import secrets
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

# Loads backend/.env for local development (documented in .env.example).
# No-op if the file doesn't exist — production (Render etc.) sets real
# environment variables directly, so this never overrides those.
load_dotenv()


from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import models
from app.core.utils import _mask_cnp, generate_public_id, now_iso
from app.db import SessionLocal, engine
from app.policies.access import get_patient_for_user
from app.services.document_pipeline import process_uploaded_document
from app.services.discharge_summary_pipeline import process_uploaded_discharge_summary
from app.services.document_taxonomy import AUTO_CLASSIFY_SECTION, DOCUMENT_TYPE_LABELS, legacy_section_for
from app.services.extraction_provider import REDUCTO, ProcessingMetadata, get_extraction_provider
from app.services.reducto_client import ReductoError
from app.services import reducto_extraction
from app.services.ocr_service import extract_text as ocr_extract_text
from app.services.file_hash import compute_sha256
from app.services.security_scan import run_security_scan
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


# ============================================================================
# Router registration — domains extracted into app/api/routers/ (Phase 4
# backend modularization; docs/refactor/BACKEND_DECOMPOSITION_PLAN.md).
# Included at the end so every dependency/model/service it needs is
# already defined above; each extracted router is otherwise fully
# self-contained. Interoperability (/admin/interop/*) was the first
# extraction — see app/api/routers/interop.py's own docstring.
# ============================================================================

from app.api.routers.admin import router as admin_router  # noqa: E402
from app.api.routers.ask_bragi import router as ask_bragi_router  # noqa: E402
from app.api.routers.assignments import router as assignments_router  # noqa: E402
from app.api.routers.auth import router as auth_router  # noqa: E402
from app.api.routers.care_partner_settings import router as care_partner_settings_router  # noqa: E402
from app.api.routers.documents import router as documents_router  # noqa: E402
from app.api.routers.emergency import router as emergency_router  # noqa: E402
from app.api.routers.interop import router as interop_router  # noqa: E402
from app.api.routers.labs import router as labs_router  # noqa: E402
from app.api.routers.medications import router as medications_router  # noqa: E402
from app.api.routers.patient_events import router as patient_events_router  # noqa: E402
from app.api.routers.patients import router as patients_router  # noqa: E402
from app.api.routers.root import router as root_router  # noqa: E402
from app.api.routers.source_evidence import router as source_evidence_router  # noqa: E402

app.include_router(root_router)
app.include_router(admin_router)
app.include_router(ask_bragi_router)
app.include_router(assignments_router)
app.include_router(auth_router)
app.include_router(care_partner_settings_router)
app.include_router(documents_router)
app.include_router(emergency_router)
app.include_router(labs_router)
app.include_router(medications_router)
app.include_router(patient_events_router)
app.include_router(patients_router)
app.include_router(source_evidence_router)
app.include_router(interop_router)
