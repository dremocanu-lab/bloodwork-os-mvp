import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.db import SessionLocal, engine
from app.services.document_pipeline import process_uploaded_document

app = FastAPI()

models.Base.metadata.create_all(bind=engine)

frontend_origins_raw = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
frontend_origins = [origin.strip() for origin in frontend_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_SECTIONS = {
    "notes",
    "bloodwork",
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


def doctor_has_patient_access(db: Session, doctor_user_id: int, patient_id: int) -> bool:
    return (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
            models.DoctorPatientAccess.patient_id == patient_id,
        )
        .first()
        is not None
    )


def get_patient_for_user(db: Session, user_id: int):
    return db.query(models.Patient).filter(models.Patient.linked_user_id == user_id).first()


def ensure_patient_for_user(db: Session, user):
    patient = get_patient_for_user(db, user.id)

    if patient:
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

    return patient


def can_access_patient(db: Session, current_user, patient_id: int) -> bool:
    if current_user.role == "admin":
        return True

    if current_user.role == "doctor":
        return doctor_has_patient_access(db, current_user.id, patient_id)

    if current_user.role == "patient":
        patient = get_patient_for_user(db, current_user.id)
        return patient is not None and patient.id == patient_id

    return False


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
    }


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

    doctor_access = [
        serialize_doctor_access(link)
        for link in patient.doctor_access_links
    ]

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
        "sections": grouped_documents,
        "doctor_access": doctor_access,
        "events": [serialize_patient_event(event) for event in events],
    }


def resolve_or_create_patient(db: Session, parsed_data: dict, linked_user_id: int | None = None):
    patient = None
    patient_name = parsed_data.get("patient_name")
    patient_dob = parsed_data.get("date_of_birth")
    patient_age = parsed_data.get("age")
    patient_sex = parsed_data.get("sex")
    patient_cnp = parsed_data.get("cnp")
    patient_identifier = parsed_data.get("patient_identifier")

    def norm(value):
        return (value or "").strip().lower()

    if linked_user_id:
        patient = db.query(models.Patient).filter(models.Patient.linked_user_id == linked_user_id).first()

    if not patient and patient_cnp:
        patient = db.query(models.Patient).filter(models.Patient.cnp == patient_cnp).first()

    if not patient and patient_identifier:
        patient = db.query(models.Patient).filter(models.Patient.patient_identifier == patient_identifier).first()

    if not patient and patient_name and patient_dob:
        normalized_name = " ".join(patient_name.split()).strip().lower()
        all_patients = db.query(models.Patient).all()

        for existing_patient in all_patients:
            existing_name = " ".join((existing_patient.full_name or "").split()).strip().lower()
            if existing_name == normalized_name and norm(existing_patient.date_of_birth) == norm(patient_dob):
                patient = existing_patient
                break

    if patient and linked_user_id and patient.linked_user_id and patient.linked_user_id != linked_user_id:
        patient = None

    if not patient and patient_name:
        patient = models.Patient(
            linked_user_id=linked_user_id,
            full_name=patient_name.strip(),
            date_of_birth=patient_dob,
            age=patient_age,
            sex=patient_sex,
            cnp=patient_cnp,
            patient_identifier=patient_identifier,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

    if patient and linked_user_id and not patient.linked_user_id:
        patient.linked_user_id = linked_user_id
        db.commit()
        db.refresh(patient)

    return patient


def get_document_payload(db: Session, document, labs, audit_logs, current_user=None):
    uploaded_by = serialize_user(document.uploaded_by_user) if document.uploaded_by_user else None

    return {
        "document_id": document.id,
        "patient_id": document.patient_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "saved_to": document.saved_to,
        "section": document.section,
        "uploaded_by_user_id": document.uploaded_by_user_id,
        "uploaded_by": uploaded_by,
        "extracted_text": document.extracted_text,
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
            "has_abnormal": document_has_abnormal_labs(db, document.id),
            "reviewed_by_current_doctor": (
                current_user.role == "doctor"
                and doctor_reviewed_document(db, current_user.id, document.id)
                if current_user
                else False
            ),
            "labs": [
                {
                    "raw_test_name": lab.raw_test_name,
                    "canonical_name": lab.canonical_name,
                    "display_name": lab.display_name,
                    "category": lab.category,
                    "value": lab.value,
                    "flag": lab.flag,
                    "reference_range": lab.reference_range,
                    "unit": lab.unit,
                }
                for lab in labs
            ],
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LabResultUpdate(BaseModel):
    raw_test_name: str | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    category: str | None = None
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
    if payload.role not in {"patient", "doctor", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    user = models.User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
        hospital_name=payload.hospital_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if payload.role == "patient":
        resolve_or_create_patient(
            db,
            {
                "patient_name": payload.full_name,
                "date_of_birth": payload.date_of_birth,
                "age": payload.age,
                "sex": payload.sex,
                "cnp": payload.cnp,
                "patient_identifier": payload.patient_identifier,
            },
            linked_user_id=user.id,
        )

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
    if not doctor or doctor.role != "doctor":
        raise HTTPException(status_code=400, detail="Doctor user not found")

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    existing = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == payload.doctor_user_id,
            models.DoctorPatientAccess.patient_id == payload.patient_id,
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
        haystack = " ".join(
            [
                (patient.full_name or "").lower(),
                (patient.cnp or "").lower(),
                (patient.patient_identifier or "").lower(),
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


@app.get("/documents")
def get_documents(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(models.Document)

    if current_user.role == "patient":
        patient = ensure_patient_for_user(db, current_user)
        query = query.filter(models.Document.patient_id == patient.id)

    elif current_user.role == "doctor":
        assigned_patient_ids = [
            link.patient_id
            for link in db.query(models.DoctorPatientAccess)
            .filter(models.DoctorPatientAccess.doctor_user_id == current_user.id)
            .all()
        ]

        if not assigned_patient_ids:
            return []

        query = query.filter(models.Document.patient_id.in_(assigned_patient_ids))

    documents = query.order_by(models.Document.id.desc()).all()
    return [serialize_document_card(db, document, current_user) for document in documents]


@app.get("/documents/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.patient_id or not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.role == "doctor" and document_has_abnormal_labs(db, document.id):
        mark_doctor_reviewed_document(db, current_user.id, document.id)
        db.commit()

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )

    return get_document_payload(db, document, labs, logs, current_user)


@app.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.patient_id or not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not document.saved_to:
        raise HTTPException(status_code=404, detail="Original file not found")

    file_path = Path(document.saved_to)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Original file is no longer available")

    return FileResponse(
        path=str(file_path),
        media_type=document.content_type or "application/octet-stream",
        filename=document.filename,
    )


@app.post("/documents/{document_id}/verify")
def verify_document(
    document_id: int,
    payload: VerifyRequest = VerifyRequest(),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.patient_id or not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    document.is_verified = True
    document.verified_by = payload.verifier_name or current_user.full_name
    document.verified_at = now_iso()

    add_audit_log(
        db,
        document_id=document.id,
        action="verify",
        actor=payload.verifier_name or current_user.full_name,
        details="Document marked as verified",
    )

    db.commit()
    db.refresh(document)

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )

    return get_document_payload(db, document, labs, logs, current_user)


@app.put("/documents/{document_id}")
def update_document(
    document_id: int,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.patient_id or not can_access_patient(db, current_user, document.patient_id):
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
    document.is_verified = False
    document.verified_by = None
    document.verified_at = None

    patient = resolve_or_create_patient(
        db,
        {
            "patient_name": parsed.patient_name,
            "date_of_birth": parsed.date_of_birth,
            "age": parsed.age,
            "sex": parsed.sex,
            "cnp": parsed.cnp,
            "patient_identifier": parsed.patient_identifier,
        },
    )

    if patient:
        document.patient_id = patient.id

    existing_labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()

    for lab in existing_labs:
        db.delete(lab)

    db.commit()

    for lab in parsed.labs:
        normalized_lab = models.LabResult(
            document_id=document.id,
            raw_test_name=lab.raw_test_name,
            canonical_name=lab.canonical_name,
            display_name=lab.display_name,
            category=lab.category,
            value=lab.value,
            flag=lab.flag,
            reference_range=lab.reference_range,
            unit=lab.unit,
        )
        db.add(normalized_lab)

    add_audit_log(
        db,
        document_id=document.id,
        action="edit",
        actor=payload.editor_name or current_user.full_name,
        details="Parsed data manually updated",
    )

    db.commit()
    db.refresh(document)

    updated_labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )

    return get_document_payload(db, document, updated_labs, logs, current_user)


@app.get("/patients/{patient_id}/bloodwork-trends")
def get_patient_bloodwork_trends(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

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

    trends_by_test: dict[str, dict] = {}

    for document in documents:
        labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        date_value = get_best_document_date(document) or str(document.id)

        for lab in labs:
            test_key = lab.canonical_name or lab.display_name or lab.raw_test_name

            if not test_key:
                continue

            raw_value = lab.value
            numeric_value = None

            try:
                if raw_value is not None:
                    numeric_value = float(str(raw_value).replace(",", ".").strip())
            except Exception:
                numeric_value = None

            if numeric_value is None:
                continue

            if test_key not in trends_by_test:
                trends_by_test[test_key] = {
                    "test_key": test_key,
                    "display_name": lab.display_name or lab.raw_test_name or lab.canonical_name or "Unknown test",
                    "canonical_name": lab.canonical_name,
                    "category": lab.category,
                    "unit": lab.unit,
                    "latest": None,
                    "previous": None,
                    "delta": None,
                    "points": [],
                }

            value_display = f"{raw_value} {lab.unit or ''}".strip()

            trends_by_test[test_key]["points"].append(
                {
                    "document_id": document.id,
                    "date": date_value,
                    "value": numeric_value,
                    "value_display": value_display,
                    "flag": lab.flag,
                    "report_name": document.report_name,
                    "reference_range": lab.reference_range,
                }
            )

    trends = []

    for trend in trends_by_test.values():
        points = trend["points"]

        if not points:
            continue

        latest = points[-1]
        previous = points[-2] if len(points) >= 2 else None

        trend["latest"] = latest
        trend["previous"] = previous
        trend["delta"] = round(latest["value"] - previous["value"], 3) if previous else None

        trends.append(trend)

    trends.sort(key=lambda item: item.get("display_name") or "")

    return trends


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

    return serialize_patient_event(event)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    patient_id: int | None = Form(default=None),
    section: str = Form(default="bloodwork"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if section not in ALLOWED_SECTIONS:
        raise HTTPException(status_code=400, detail="Invalid section")

    if current_user.role == "patient":
        target_patient = ensure_patient_for_user(db, current_user)
    else:
        if patient_id is None:
            raise HTTPException(status_code=400, detail="patient_id is required")

        target_patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

        if not target_patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
            raise HTTPException(status_code=403, detail="Forbidden")

    safe_filename = f"{int(datetime.now(UTC).timestamp())}_{file.filename}"
    file_path = UPLOAD_DIR / safe_filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if section == "notes":
        extracted_text = ""
        parsed_data = {
            "patient_name": target_patient.full_name,
            "date_of_birth": target_patient.date_of_birth,
            "age": target_patient.age,
            "sex": target_patient.sex,
            "cnp": target_patient.cnp,
            "patient_identifier": target_patient.patient_identifier,
            "report_name": file.filename,
            "report_type": "Clinical Note",
            "labs": [],
        }
        pipeline_warnings = []
    else:
        pipeline_result = process_uploaded_document(
            file_path=file_path,
            filename=file.filename,
            section=section,
            temp_dir=UPLOAD_DIR,
        )
        extracted_text = pipeline_result.get("extracted_text") or ""
        parsed_data = pipeline_result.get("parsed_data") or {}
        pipeline_warnings = pipeline_result.get("warnings") or []

    parsed_data["patient_name"] = target_patient.full_name
    parsed_data["date_of_birth"] = target_patient.date_of_birth
    parsed_data["age"] = target_patient.age
    parsed_data["sex"] = target_patient.sex
    parsed_data["cnp"] = target_patient.cnp
    parsed_data["patient_identifier"] = target_patient.patient_identifier

    document = models.Document(
        patient_id=target_patient.id,
        uploaded_by_user_id=current_user.id,
        section=section,
        filename=file.filename,
        content_type=file.content_type,
        saved_to=str(file_path),
        extracted_text=extracted_text,
        patient_name=parsed_data.get("patient_name"),
        date_of_birth=parsed_data.get("date_of_birth"),
        age=parsed_data.get("age"),
        sex=parsed_data.get("sex"),
        cnp=parsed_data.get("cnp"),
        patient_identifier=parsed_data.get("patient_identifier"),
        lab_name=parsed_data.get("lab_name"),
        sample_type=parsed_data.get("sample_type"),
        referring_doctor=parsed_data.get("referring_doctor"),
        report_name=parsed_data.get("report_name") or file.filename,
        report_type=parsed_data.get("report_type"),
        source_language=parsed_data.get("source_language"),
        test_date=parsed_data.get("test_date"),
        collected_on=parsed_data.get("collected_on"),
        reported_on=parsed_data.get("reported_on"),
        registered_on=parsed_data.get("registered_on"),
        generated_on=parsed_data.get("generated_on"),
        note_body=parsed_data.get("note_body"),
        is_verified=False,
        last_edited_at=None,
        created_at=now_iso(),
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    if section == "bloodwork":
        for lab in parsed_data.get("labs", []):
            lab_result = models.LabResult(
                document_id=document.id,
                raw_test_name=lab.get("raw_test_name"),
                canonical_name=lab.get("canonical_name"),
                display_name=lab.get("display_name"),
                category=lab.get("category"),
                value=lab.get("value"),
                flag=lab.get("flag"),
                reference_range=lab.get("reference_range"),
                unit=lab.get("unit"),
            )
            db.add(lab_result)

    details = f"Document uploaded to section '{section}': {file.filename}"
    if pipeline_warnings:
        details += " | Warnings: " + "; ".join(pipeline_warnings[:5])

    add_audit_log(
        db,
        document_id=document.id,
        action="upload",
        actor=current_user.full_name,
        details=details,
    )

    db.commit()

    created_labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )

    return get_document_payload(db, document, created_labs, logs, current_user)
