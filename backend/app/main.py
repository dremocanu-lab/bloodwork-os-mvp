import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import fitz
import pytesseract
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.db import SessionLocal, engine
from app.report_fields import extract_report_metadata
from app.synonyms import normalize_test_name

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

tesseract_cmd = os.getenv("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

ALLOWED_SECTIONS = {"bloodwork", "medications", "scans", "hospitalizations", "other"}
ALLOWED_ROLES = {"patient", "doctor", "admin"}
ALLOWED_EVENT_TYPES = {"hospitalization"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def compute_age_from_dob(dob_string: str | None) -> str | None:
    if not dob_string:
        return None
    try:
        dob = date.fromisoformat(dob_string)
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return str(age)
    except Exception:
        return None


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


def doctor_has_patient_access(db: Session, doctor_user_id: int, patient_id: int) -> bool:
    link = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == doctor_user_id,
            models.DoctorPatientAccess.patient_id == patient_id,
        )
        .first()
    )
    return link is not None


def can_access_patient(db: Session, current_user, patient_id: int) -> bool:
    if current_user.role == "admin":
        return True

    if current_user.role == "doctor":
        return doctor_has_patient_access(db, current_user.id, patient_id)

    if current_user.role == "patient":
        patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
        return patient is not None and patient.id == patient_id

    return False


def value_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str
    date_of_birth: str | None = None
    age: str | None = None
    sex: str | None = None
    cnp: str | None = None
    patient_identifier: str | None = None
    department: str | None = None
    hospital_name: str | None = None


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
    event_type: str = "hospitalization"
    title: str
    description: str | None = None


def extract_text_from_pdf(file_path: Path) -> str:
    text = ""
    pdf_document = fitz.open(file_path)
    for page in pdf_document:
        text += page.get_text()
    pdf_document.close()
    return text


def extract_text_from_image(file_path: Path) -> str:
    image = Image.open(file_path).convert("RGB")
    try:
        return pytesseract.image_to_string(image, lang="ron+eng")
    except Exception:
        return pytesseract.image_to_string(image, lang="eng")


def extract_text_from_scanned_pdf(file_path: Path) -> str:
    pdf_document = fitz.open(file_path)
    all_text = []

    try:
        for page_index in range(len(pdf_document)):
            page = pdf_document.load_page(page_index)
            pix = page.get_pixmap()
            temp_image_path = UPLOAD_DIR / f"temp_page_{page_index}.png"
            pix.save(str(temp_image_path))

            try:
                page_text = extract_text_from_image(temp_image_path)
                all_text.append(page_text)
            finally:
                if temp_image_path.exists():
                    temp_image_path.unlink()

        return "\n".join(all_text)
    finally:
        pdf_document.close()


def extract_text(file_path: Path, filename: str) -> str:
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        extracted_text = extract_text_from_pdf(file_path)
        if extracted_text.strip():
            return extracted_text
        return extract_text_from_scanned_pdf(file_path)

    if lower_name.endswith((".png", ".jpg", ".jpeg")):
        return extract_text_from_image(file_path)

    return ""


def build_lab_result(
    raw_test_name: str,
    value: str,
    flag: str,
    reference_range: str,
    unit: str,
) -> dict:
    normalized = normalize_test_name(raw_test_name)
    return {
        "raw_test_name": normalized["raw_test_name"],
        "canonical_name": normalized["canonical_name"],
        "display_name": normalized["display_name"],
        "category": normalized["category"],
        "value": value,
        "flag": flag,
        "reference_range": reference_range,
        "unit": unit,
    }


def infer_flag(value: str, reference_range: str) -> str:
    try:
        numeric_value = float(value.replace(",", "."))
        matches = re.findall(r"[-+]?\d*\.?\d+", reference_range.replace(",", "."))
        if len(matches) >= 2:
            low = float(matches[0])
            high = float(matches[1])
            if numeric_value < low:
                return "Low"
            if numeric_value > high:
                return "High"
    except Exception:
        pass
    return "Normal"


def parse_bloodwork_text(text: str) -> dict:
    metadata = extract_report_metadata(text)
    labs = []

    lab_patterns = [
        (r"Haemoglobin\s+([\d.,]+)\s+([\d.,\- ]+)\s+([a-zA-Z/%]+)", "Haemoglobin"),
        (r"Hemoglobin\s+([\d.,]+)\s+([\d.,\- ]+)\s+([a-zA-Z/%]+)", "Hemoglobin"),
        (r"Hemoglobina\s+([\d.,]+)\s+([\d.,\- ]+)\s+([a-zA-Z/%]+)", "Hemoglobina"),
        (r"Hemoglobină\s+([\d.,]+)\s+([\d.,\- ]+)\s+([a-zA-Z/%]+)", "Hemoglobină"),
        (
            r"Total Leucocyte Count\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Total Leucocyte Count",
        ),
        (
            r"Total Leukocyte Count\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Total Leukocyte Count",
        ),
        (
            r"Total WBC count\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Total WBC count",
        ),
        (
            r"Leucocite\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Leucocite",
        ),
        (
            r"Leukocite\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Leukocite",
        ),
        (
            r"Total RBC count\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)",
            "Total RBC count",
        ),
        (r"RBC Count\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)", "RBC Count"),
        (r"Eritrocite\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+([a-zA-Z/%]+)", "Eritrocite"),
        (r"Neutrophils\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Neutrophils"),
        (r"Neutrofile\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Neutrofile"),
        (r"Lymphocytes\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Lymphocytes"),
        (r"Limfocite\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Limfocite"),
        (r"Monocytes\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Monocytes"),
        (r"Monocite\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Monocite"),
        (r"Eosinophils\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Eosinophils"),
        (r"Eozinofile\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Eozinofile"),
        (r"Basophils\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Basophils"),
        (r"Bazofile\s+([\d.,]+)\s+(?:High|Low|Borderline)?\s*([\d.,\- ]+)\s+(%)", "Bazofile"),
    ]

    seen = set()

    for pattern, raw_test_name in lab_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        value = match.group(1).strip()
        reference_range = match.group(2).strip()
        unit = match.group(3).strip()

        normalized = normalize_test_name(raw_test_name)
        dedupe_key = normalized["canonical_name"] or normalized["display_name"].lower()

        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        labs.append(
            build_lab_result(
                raw_test_name=raw_test_name,
                value=value,
                flag=infer_flag(value, reference_range),
                reference_range=reference_range,
                unit=unit,
            )
        )

    report_name = metadata.get("report_type") or "Unknown Report"

    return {
        "patient_name": metadata.get("patient_name"),
        "date_of_birth": metadata.get("date_of_birth"),
        "age": metadata.get("age"),
        "sex": metadata.get("sex"),
        "cnp": metadata.get("cnp"),
        "patient_identifier": metadata.get("patient_identifier"),
        "lab_name": metadata.get("lab_name"),
        "sample_type": metadata.get("sample_type"),
        "referring_doctor": metadata.get("referring_doctor"),
        "report_name": report_name,
        "report_type": metadata.get("report_type"),
        "source_language": metadata.get("source_language"),
        "test_date": metadata.get("collected_on") or metadata.get("reported_on") or metadata.get("generated_on"),
        "collected_on": metadata.get("collected_on"),
        "reported_on": metadata.get("reported_on"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "labs": labs,
    }


def get_user_summary(user):
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


def get_event_payload(event):
    doctor_user = (
        event.patient.doctor_access_links[0].doctor_user
        if event.patient and event.patient.doctor_access_links
        else None
    )
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
        "doctor_name": doctor_user.full_name if doctor_user and doctor_user.id == event.doctor_user_id else None,
    }


def get_document_payload(document, labs, audit_logs):
    uploader = document.uploaded_by_user

    return {
        "document_id": document.id,
        "patient_id": document.patient_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "saved_to": document.saved_to,
        "section": document.section,
        "uploaded_by_user_id": document.uploaded_by_user_id,
        "uploaded_by": get_user_summary(uploader),
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
            "is_verified": document.is_verified,
            "verified_by": document.verified_by,
            "verified_at": document.verified_at,
            "last_edited_at": document.last_edited_at,
            "labs": [
                {
                    "id": lab.id,
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


def get_document_card(document):
    uploader = document.uploaded_by_user
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
        "section": document.section,
        "is_verified": document.is_verified,
        "uploaded_by": get_user_summary(uploader),
    }


def resolve_or_create_patient(db: Session, parsed_data: dict):
    patient = None
    patient_name = parsed_data.get("patient_name")
    patient_dob = parsed_data.get("date_of_birth")
    patient_age = parsed_data.get("age") or compute_age_from_dob(patient_dob)
    patient_sex = parsed_data.get("sex")
    patient_cnp = parsed_data.get("cnp")
    patient_identifier = parsed_data.get("patient_identifier")

    def norm(value):
        return (value or "").strip().lower()

    if patient_cnp:
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

    if not patient and patient_name:
        normalized_name = " ".join(patient_name.split()).strip().lower()
        all_patients = db.query(models.Patient).all()

        for existing_patient in all_patients:
            existing_name = " ".join((existing_patient.full_name or "").split()).strip().lower()
            same_name = existing_name == normalized_name
            same_age = norm(existing_patient.age) == norm(patient_age)
            same_sex = norm(existing_patient.sex) == norm(patient_sex)

            if same_name and same_age and same_sex:
                patient = existing_patient
                break

    if not patient and patient_name:
        patient = models.Patient(
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
    elif patient:
        patient.date_of_birth = patient.date_of_birth or patient_dob
        patient.age = patient.age or patient_age
        patient.sex = patient.sex or patient_sex
        patient.cnp = patient.cnp or patient_cnp
        patient.patient_identifier = patient.patient_identifier or patient_identifier
        db.commit()

    return patient


@app.get("/")
def root():
    return {"message": "API is running"}


@app.post("/auth/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if payload.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    computed_age = compute_age_from_dob(payload.date_of_birth) or payload.age

    department = value_or_none(payload.department)
    hospital_name = value_or_none(payload.hospital_name)

    if payload.role == "doctor":
        if not department or not hospital_name:
            raise HTTPException(status_code=400, detail="Doctors must choose a department and hospital")

    user = models.User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password[:72]),
        role=payload.role,
        department=department if payload.role == "doctor" else None,
        hospital_name=hospital_name if payload.role == "doctor" else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if payload.role == "patient":
        patient = resolve_or_create_patient(
            db,
            {
                "patient_name": payload.full_name,
                "date_of_birth": payload.date_of_birth,
                "age": computed_age,
                "sex": payload.sex,
                "cnp": payload.cnp,
                "patient_identifier": payload.patient_identifier,
            },
        )
        if patient:
            patient.linked_user_id = user.id
            patient.age = computed_age or patient.age
            db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": get_user_summary(user),
    }


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password[:72], user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": get_user_summary(user),
    }


@app.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    return get_user_summary(current_user)


@app.get("/users/doctors")
def get_doctors(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctors = (
        db.query(models.User)
        .filter(models.User.role == "doctor")
        .order_by(models.User.full_name.asc())
        .all()
    )
    return [get_user_summary(doctor) for doctor in doctors]


@app.get("/users/doctors/search")
def search_doctors(
    q: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    term = q.strip().lower()
    doctors = db.query(models.User).filter(models.User.role == "doctor").all()

    if not term:
        return [get_user_summary(doctor) for doctor in doctors]

    results = []
    for doctor in doctors:
        haystack = " ".join(
            [
                (doctor.full_name or "").lower(),
                (doctor.email or "").lower(),
                (doctor.department or "").lower(),
                (doctor.hospital_name or "").lower(),
            ]
        )
        if term in haystack:
            results.append(get_user_summary(doctor))
    return results


@app.get("/assignments")
def get_assignments(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    assignments = db.query(models.DoctorPatientAccess).order_by(models.DoctorPatientAccess.id.desc()).all()
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
    patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
    if not patient:
        return []

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
    patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

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


@app.get("/documents")
def get_documents(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(models.Document)

    if current_user.role == "patient":
        patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
        if not patient:
            return []
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
    return [get_document_card(doc) for doc in documents]


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

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )
    return get_document_payload(document, labs, logs)


@app.get("/documents/{document_id}/file")
def open_document_file(
    document_id: int,
    download: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = db.query(models.Document).filter(models.Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.patient_id or not can_access_patient(db, current_user, document.patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    file_path = Path(document.saved_to)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Original file not found on server")

    media_type = document.content_type or "application/octet-stream"
    filename = document.filename or file_path.name

    if download:
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
        )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


@app.get("/patients")
def get_patients(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor", "admin")),
):
    if current_user.role == "admin":
        patients = db.query(models.Patient).order_by(models.Patient.full_name.asc()).all()
    else:
        assigned_patient_ids = [
            link.patient_id
            for link in db.query(models.DoctorPatientAccess)
            .filter(models.DoctorPatientAccess.doctor_user_id == current_user.id)
            .all()
        ]
        if not assigned_patient_ids:
            return []
        patients = (
            db.query(models.Patient)
            .filter(models.Patient.id.in_(assigned_patient_ids))
            .order_by(models.Patient.full_name.asc())
            .all()
        )

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
    q: str = Query(""),
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
        if term and term not in haystack:
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


@app.get("/my-patients")
def get_my_patients(
    admitted_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    links = (
        db.query(models.DoctorPatientAccess)
        .filter(models.DoctorPatientAccess.doctor_user_id == current_user.id)
        .all()
    )

    results = []
    for link in links:
        patient = db.query(models.Patient).filter(models.Patient.id == link.patient_id).first()
        if not patient:
            continue

        active_event = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.patient_id == patient.id,
                models.PatientEvent.doctor_user_id == current_user.id,
                models.PatientEvent.status == "active",
            )
            .order_by(models.PatientEvent.id.desc())
            .first()
        )

        if admitted_only and not active_event:
            continue

        docs = (
            db.query(models.Document)
            .filter(models.Document.patient_id == patient.id)
            .order_by(models.Document.id.desc())
            .all()
        )

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
                "document_count": len(docs),
                "bloodwork_count": len([doc for doc in docs if doc.section == "bloodwork"]),
                "active_event": get_event_payload(active_event) if active_event else None,
                "latest_document": get_document_card(docs[0]) if docs else None,
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

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .all()
    )

    grouped_documents = {
        "bloodwork": [],
        "medications": [],
        "scans": [],
        "hospitalizations": [],
        "other": [],
    }

    for doc in documents:
        section = doc.section if doc.section in grouped_documents else "other"
        grouped_documents[section].append(get_document_card(doc))

    doctor_access = []
    for link in patient.doctor_access_links:
        doctor = db.query(models.User).filter(models.User.id == link.doctor_user_id).first()
        if doctor:
            doctor_access.append(
                {
                    "doctor_user_id": doctor.id,
                    "doctor_name": doctor.full_name,
                    "doctor_email": doctor.email,
                    "department": doctor.department,
                    "hospital_name": doctor.hospital_name,
                    "granted_at": link.granted_at,
                }
            )

    events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id)
        .order_by(models.PatientEvent.id.desc())
        .all()
    )

    event_payloads = []
    for event in events:
        event_payload = get_event_payload(event)
        doctor = db.query(models.User).filter(models.User.id == event.doctor_user_id).first()
        event_payload["doctor_name"] = doctor.full_name if doctor else None
        event_payloads.append(event_payload)

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
        "events": event_payloads,
    }


@app.get("/my/profile")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    return get_patient_profile(patient.id, db, current_user)


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
        "documents": [get_document_card(doc) for doc in documents],
    }


@app.post("/patients/{patient_id}/events")
def create_patient_event(
    patient_id: int,
    payload: PatientEventCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if not doctor_has_patient_access(db, current_user.id, patient_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if payload.event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported event type")

    existing_active = (
        db.query(models.PatientEvent)
        .filter(
            models.PatientEvent.patient_id == patient_id,
            models.PatientEvent.doctor_user_id == current_user.id,
            models.PatientEvent.status == "active",
        )
        .first()
    )
    if existing_active:
        raise HTTPException(status_code=400, detail="This patient already has an active event under your care")

    event = models.PatientEvent(
        patient_id=patient_id,
        doctor_user_id=current_user.id,
        event_type=payload.event_type,
        status="active",
        title=payload.title.strip(),
        description=value_or_none(payload.description),
        hospital_name=current_user.hospital_name,
        department=current_user.department,
        admitted_at=now_iso(),
        created_by_user_id=current_user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    payload = get_event_payload(event)
    payload["doctor_name"] = current_user.full_name
    return payload


@app.post("/patient-events/{event_id}/discharge")
def discharge_patient_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    event = db.query(models.PatientEvent).filter(models.PatientEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.doctor_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only discharge your own patients")

    if event.status != "active":
        raise HTTPException(status_code=400, detail="Event is already discharged")

    event.status = "discharged"
    event.discharged_at = now_iso()
    event.discharged_by_user_id = current_user.id
    db.commit()
    db.refresh(event)

    payload = get_event_payload(event)
    payload["doctor_name"] = current_user.full_name
    return payload


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
    return get_document_payload(document, labs, logs)


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
    parsed_age = parsed.age or compute_age_from_dob(parsed.date_of_birth)

    document.patient_name = parsed.patient_name
    document.date_of_birth = parsed.date_of_birth
    document.age = parsed_age
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
    document.last_edited_at = now_iso()
    document.is_verified = False
    document.verified_by = None
    document.verified_at = None

    patient = resolve_or_create_patient(
        db,
        {
            "patient_name": parsed.patient_name,
            "date_of_birth": parsed.date_of_birth,
            "age": parsed_age,
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
        new_lab = models.LabResult(
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
        db.add(new_lab)

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
    return get_document_payload(document, updated_labs, logs)


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

    target_patient = None

    if current_user.role == "patient":
        target_patient = db.query(models.Patient).filter(models.Patient.linked_user_id == current_user.id).first()
        if not target_patient:
            raise HTTPException(status_code=404, detail="Patient profile not found")
    else:
        if patient_id is None:
            raise HTTPException(status_code=400, detail="patient_id is required")
        target_patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
        if not target_patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        if current_user.role == "doctor" and not doctor_has_patient_access(db, current_user.id, patient_id):
            raise HTTPException(status_code=403, detail="Forbidden")

    safe_name = f"{int(datetime.now(UTC).timestamp())}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted_text = extract_text(file_path, file.filename)
    parsed_data = parse_bloodwork_text(extracted_text)

    if target_patient:
        parsed_data["patient_name"] = target_patient.full_name
        parsed_data["date_of_birth"] = target_patient.date_of_birth
        parsed_data["age"] = target_patient.age or compute_age_from_dob(target_patient.date_of_birth)
        parsed_data["sex"] = target_patient.sex
        parsed_data["cnp"] = target_patient.cnp
        parsed_data["patient_identifier"] = target_patient.patient_identifier

    document = models.Document(
        patient_id=target_patient.id if target_patient else None,
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
        report_name=parsed_data.get("report_name"),
        report_type=parsed_data.get("report_type"),
        source_language=parsed_data.get("source_language"),
        test_date=parsed_data.get("test_date"),
        collected_on=parsed_data.get("collected_on"),
        reported_on=parsed_data.get("reported_on"),
        registered_on=parsed_data.get("registered_on"),
        generated_on=parsed_data.get("generated_on"),
        is_verified=False,
        last_edited_at=None,
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

    add_audit_log(
        db,
        document_id=document.id,
        action="upload",
        actor=current_user.full_name,
        details=f"Document uploaded to section '{section}': {file.filename}",
    )

    db.commit()

    created_labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.document_id == document.id)
        .order_by(models.AuditLog.id.desc())
        .all()
    )
    return get_document_payload(document, created_labs, logs)