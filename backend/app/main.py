import os
import re
import json
import secrets
import shutil
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app import models
from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.db import SessionLocal, engine
from app.services.document_pipeline import process_uploaded_document
from app.services.lab_catalog import find_lab_definition
from app.services.discharge_summary_pipeline import process_uploaded_discharge_summary
from app.services.medication_lookup import lookup_medication

app = FastAPI()

models.Base.metadata.create_all(bind=engine)

def run_migrations():
    with engine.connect() as conn:
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
        conn.commit()

run_migrations()

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

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            "cnp": patient.cnp,
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

    return {
        "document_id": document.id,
        "id": document.id,
        "patient_id": document.patient_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "saved_to": document.saved_to,
        "section": document.section,
        "uploaded_by_user_id": document.uploaded_by_user_id,
        "uploaded_by": uploaded_by,
        "extracted_text": document.extracted_text or "",
        "original_layout": original_layout,
        "parsed_data": {
            "patient_name": document.patient_name,
            "date_of_birth": document.date_of_birth,
            "age": document.age,
            "sex": document.sex,
            "cnp": document.cnp,
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
        "section": job.section,
        "filename": job.filename,
        "content_type": job.content_type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "document_id": job.document_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

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
        job.message = "Saving structured record..."
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

            is_verified=0,
            verified_by=None,
            verified_at=None,
            last_edited_at=None,
            created_at=now_iso(),
        )

        db.add(document)
        db.flush()

        for lab in labs:
            db.add(
                models.LabResult(
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
                )
            )

        add_audit_log(
            db=db,
            document_id=document.id,
            action="uploaded",
            actor=user.full_name,
            details=f"Uploaded {job.filename} to {job.section}",
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

        job.status = "done"
        job.progress = 100
        job.message = f"{job.filename} was uploaded."
        job.document_id = document.id
        job.finished_at = now_iso()

        db.commit()

    except Exception as error:
        db.rollback()

        print(f"UPLOAD JOB {job_id} ERROR:")
        print(traceback.format_exc())

        try:
            job = db.query(models.UploadJob).filter(models.UploadJob.id == job_id).first()

            if job:
                job.status = "error"
                job.progress = 100
                job.message = "Upload failed."
                job.error = "An error occurred during document processing. Please try again."
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
    password: str
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


@app.post("/auth/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
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
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
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
            .filter(models.DoctorPatientAccess.doctor_user_id == current_user.id)
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
            "cnp": patient.cnp,
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
        .filter(models.DoctorPatientAccess.doctor_user_id == current_user.id)
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
                    "cnp": patient.cnp,
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

    # Timeline preview (last 5 events)
    timeline_events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id)
        .order_by(models.PatientEvent.id.desc())
        .limit(5)
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

    return {
        "patient": {
            "id": patient.id,
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
        "timeline_preview": [
            {
                "id": e.id,
                "title": e.title,
                "event_type": e.event_type,
                "status": e.status,
                "admitted_at": e.admitted_at,
                "discharged_at": e.discharged_at,
                "hospital_name": e.hospital_name,
                "department": e.department,
            }
            for e in timeline_events
        ],
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
                "cnp": patient.cnp,
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


@app.delete("/my/account")
def delete_my_account(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = get_patient_for_user(db, current_user.id)

    if patient:
        docs = db.query(models.Document).filter(models.Document.patient_id == patient.id).all()
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
            "cnp": patient.cnp,
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
):
    if section not in ALLOWED_SECTIONS:
        raise HTTPException(status_code=400, detail="Invalid document section")

    patient = resolve_upload_patient(db, current_user, patient_id)

    original_filename = file.filename or "uploaded_document"
    _suffix = Path(original_filename).suffix.lower()
    _safe_ext = _suffix if re.match(r"^\.[a-z0-9]{1,10}$", _suffix) else ""
    saved_filename = f"{uuid.uuid4().hex}{_safe_ext}"
    saved_path = UPLOAD_DIR / saved_filename

    try:
        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as save_error:
        raise HTTPException(status_code=500, detail=f"Could not save uploaded file: {str(save_error)}")
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
):
    return await create_background_upload(
        background_tasks=background_tasks,
        file=file,
        section=section,
        patient_id=patient_id,
        db=db,
        current_user=current_user,
    )


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


@app.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
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

    document.is_verified = 1
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
        .filter(models.LabResult.document_id.in_(document_ids))
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
            "cnp": p.cnp,
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
            "cnp": a.patient.cnp,
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
            "cnp": a.patient.cnp,
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


@app.get("/emergency/search")
def emergency_search(
    type: str = Query(...),
    q: str = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
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


@app.post("/emergency/access-sessions")
def create_emergency_session(
    payload: EmergencySessionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
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

