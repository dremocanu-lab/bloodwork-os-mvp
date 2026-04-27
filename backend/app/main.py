import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import fitz
import pytesseract
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.db import SessionLocal, engine
from app.report_fields import extract_report_metadata
from app.synonyms import get_cbc_template, identify_test_from_line, normalize_test_name

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


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def value_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    if value in {"", "-", "—", "–", "?", "-?"}:
        return None
    return value


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


def extract_text_from_pdf(file_path: Path) -> str:
    text = ""
    pdf_document = fitz.open(file_path)
    try:
        for page in pdf_document:
            text += page.get_text()
    finally:
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
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            temp_image_path = UPLOAD_DIR / f"temp_page_{page_index}_{int(datetime.now(UTC).timestamp())}.png"
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

    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        return extract_text_from_image(file_path)

    return ""


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        cleaned = value.replace(",", ".").strip()
        return float(cleaned)
    except Exception:
        return None


def infer_flag(value: str | None, reference_range: str | None) -> str | None:
    numeric_value = parse_number(value)
    if numeric_value is None or not reference_range:
        return None

    matches = re.findall(r"[-+]?\d+(?:[.,]\d+)?", reference_range)
    if len(matches) < 2:
        return None

    low = parse_number(matches[0])
    high = parse_number(matches[1])

    if low is None or high is None:
        return None

    if numeric_value < low:
        return "Low"
    if numeric_value > high:
        return "High"

    return "Normal"


def extract_explicit_flag(line: str) -> str | None:
    lowered = line.lower()

    if re.search(r"\b(high|mare|crescut|crescută|h)\b", lowered):
        return "High"

    if re.search(r"\b(low|mic|scazut|scăzut|scazuta|scăzută|l)\b", lowered):
        return "Low"

    return None


def clean_unit(unit: str | None) -> str | None:
    unit = value_or_none(unit)
    if not unit:
        return None

    unit = unit.strip()
    unit = unit.replace("10^", "10^")
    unit = re.sub(r"\s+", "", unit)

    junk_words = {
        "normal",
        "high",
        "low",
        "mare",
        "mic",
        "crescut",
        "scazut",
        "scăzut",
    }

    if unit.lower() in junk_words:
        return None

    return unit


def clean_reference_range(reference_range: str | None) -> str | None:
    reference_range = value_or_none(reference_range)
    if not reference_range:
        return None

    reference_range = reference_range.strip()
    reference_range = re.sub(r"\s+", " ", reference_range)
    return reference_range


def extract_result_parts(line: str, matched_label: str | None = None) -> dict:
    working = line

    if matched_label:
        working = re.sub(re.escape(matched_label), " ", working, flags=re.IGNORECASE)

    working = working.replace(",", ".")
    working = re.sub(r"[|;]", " ", working)
    working = re.sub(r"\s+", " ", working).strip()

    explicit_flag = extract_explicit_flag(working)

    number_pattern = r"[-+]?\d+(?:\.\d+)?"
    numbers = re.findall(number_pattern, working)

    value = numbers[0] if numbers else None
    reference_range = None

    range_match = re.search(
        rf"({number_pattern})\s*(?:-|–|—|to|pana la|până la)\s*({number_pattern})",
        working,
        re.IGNORECASE,
    )
    if range_match:
        reference_range = f"{range_match.group(1)} - {range_match.group(2)}"
    elif len(numbers) >= 3:
        reference_range = f"{numbers[1]} - {numbers[2]}"
    elif len(numbers) == 2:
        reference_range = numbers[1]

    unit = None

    if value:
        value_index = working.find(value)
        after_value = working[value_index + len(value):].strip()

        unit_match = re.search(
            r"([xX]?\s*10\^?\d+\s*/?\s*[a-zA-Zµu%/]+|[a-zA-Zµu%/]+(?:/[a-zA-Zµu]+)?|%)",
            after_value,
        )
        if unit_match:
            possible_unit = unit_match.group(1).strip()
            if not re.match(r"^(high|low|normal|mare|mic|crescut|scazut|scăzut)$", possible_unit, re.IGNORECASE):
                unit = possible_unit

    if not unit and "%" in working:
        unit = "%"

    reference_range = clean_reference_range(reference_range)
    unit = clean_unit(unit)

    return {
        "value": value_or_none(value),
        "flag": explicit_flag or infer_flag(value, reference_range),
        "reference_range": reference_range,
        "unit": unit,
    }


def build_lab_result(
    raw_test_name: str | None,
    canonical_name: str | None,
    display_name: str | None,
    category: str | None,
    value: str | None = None,
    flag: str | None = None,
    reference_range: str | None = None,
    unit: str | None = None,
    source: str = "extracted",
    is_present: bool = True,
) -> dict:
    normalized = normalize_test_name(raw_test_name or display_name or canonical_name or "")

    return {
        "raw_test_name": raw_test_name or normalized["raw_test_name"],
        "canonical_name": canonical_name or normalized["canonical_name"],
        "display_name": display_name or normalized["display_name"],
        "category": category or normalized["category"],
        "value": value_or_none(value),
        "flag": value_or_none(flag),
        "reference_range": value_or_none(reference_range),
        "unit": value_or_none(unit),
        "source": source,
        "is_present": is_present,
    }


def should_use_for_existing_result(existing: dict | None, candidate: dict) -> bool:
    if existing is None:
        return True

    existing_score = 0
    candidate_score = 0

    for key in ["value", "reference_range", "unit", "flag"]:
        if existing.get(key):
            existing_score += 1
        if candidate.get(key):
            candidate_score += 1

    return candidate_score > existing_score


def parse_structured_cbc(text: str) -> list[dict]:
    template = get_cbc_template()
    results_by_canonical = {item["canonical_name"]: item for item in template}

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for original_line in lines:
        compact_line = re.sub(r"\s+", " ", original_line).strip()
        definition = identify_test_from_line(compact_line)

        if not definition:
            continue

        parts = extract_result_parts(compact_line)

        if not parts.get("value"):
            continue

        candidate = build_lab_result(
            raw_test_name=definition["short_name"],
            canonical_name=definition["canonical_name"],
            display_name=definition["display_name"],
            category=definition["category"],
            value=parts.get("value"),
            flag=parts.get("flag"),
            reference_range=parts.get("reference_range"),
            unit=parts.get("unit"),
            source="ocr",
            is_present=True,
        )

        current = results_by_canonical.get(definition["canonical_name"])
        if should_use_for_existing_result(current, candidate):
            results_by_canonical[definition["canonical_name"]] = candidate

    ordered_results = []
    for item in template:
        canonical = item["canonical_name"]
        ordered_results.append(results_by_canonical.get(canonical, item))

    return ordered_results


def parse_bloodwork_text(text: str) -> dict:
    metadata = extract_report_metadata(text)
    cbc_labs = parse_structured_cbc(text)

    report_name = metadata.get("report_type") or "Complete Blood Count"

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
        "report_type": metadata.get("report_type") or "cbc",
        "source_language": metadata.get("source_language"),
        "test_date": metadata.get("collected_on") or metadata.get("reported_on") or metadata.get("generated_on"),
        "collected_on": metadata.get("collected_on"),
        "reported_on": metadata.get("reported_on"),
        "registered_on": metadata.get("registered_on"),
        "generated_on": metadata.get("generated_on"),
        "labs": cbc_labs,
    }


def get_document_payload(document, labs, audit_logs):
    return {
        "document_id": document.id,
        "patient_id": document.patient_id,
        "filename": document.filename,
        "content_type": document.content_type,
        "saved_to": document.saved_to,
        "section": document.section,
        "uploaded_by_user_id": document.uploaded_by_user_id,
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


def resolve_or_create_patient(db: Session, parsed_data: dict):
    patient = None
    patient_name = parsed_data.get("patient_name")
    patient_dob = parsed_data.get("date_of_birth")
    patient_age = parsed_data.get("age")
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

    return patient


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
                "age": payload.age,
                "sex": payload.sex,
                "cnp": payload.cnp,
                "patient_identifier": payload.patient_identifier,
            },
        )
        if patient:
            patient.linked_user_id = user.id
            db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@app.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
    }


@app.get("/users/doctors")
def get_doctors(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    doctors = db.query(models.User).filter(models.User.role == "doctor").all()
    return [
        {
            "id": doctor.id,
            "email": doctor.email,
            "full_name": doctor.full_name,
            "role": doctor.role,
        }
        for doctor in doctors
    ]


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


@app.get("/")
def root():
    return {"message": "API is running"}


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

    return [
        {
            "id": doc.id,
            "patient_id": doc.patient_id,
            "filename": doc.filename,
            "patient_name": doc.patient_name,
            "report_name": doc.report_name,
            "test_date": doc.test_date,
            "section": doc.section,
            "is_verified": doc.is_verified,
        }
        for doc in documents
    ]


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
        grouped_documents[section].append(
            {
                "id": doc.id,
                "filename": doc.filename,
                "report_name": doc.report_name,
                "test_date": doc.test_date,
                "section": doc.section,
                "is_verified": doc.is_verified,
            }
        )

    doctor_access = []
    for link in patient.doctor_access_links:
        doctor = db.query(models.User).filter(models.User.id == link.doctor_user_id).first()
        if doctor:
            doctor_access.append(
                {
                    "doctor_user_id": doctor.id,
                    "doctor_name": doctor.full_name,
                    "doctor_email": doctor.email,
                    "granted_at": link.granted_at,
                }
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
        "sections": grouped_documents,
        "doctor_access": doctor_access,
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

    documents = db.query(models.Document).filter(models.Document.patient_id == patient_id).all()

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
        "documents": [
            {
                "id": doc.id,
                "patient_id": doc.patient_id,
                "filename": doc.filename,
                "report_name": doc.report_name,
                "test_date": doc.test_date,
                "section": doc.section,
                "is_verified": doc.is_verified,
            }
            for doc in documents
        ],
    }


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
        normalized = normalize_test_name(lab.raw_test_name or lab.display_name or lab.canonical_name or "")
        new_lab = models.LabResult(
            document_id=document.id,
            raw_test_name=lab.raw_test_name or normalized["raw_test_name"],
            canonical_name=lab.canonical_name or normalized["canonical_name"],
            display_name=lab.display_name or normalized["display_name"],
            category=lab.category or normalized["category"],
            value=value_or_none(lab.value),
            flag=value_or_none(lab.flag),
            reference_range=value_or_none(lab.reference_range),
            unit=value_or_none(lab.unit),
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

    safe_filename = re.sub(r"[^a-zA-Z0-9_.-]+", "_", file.filename or "upload")
    safe_name = f"{int(datetime.now(UTC).timestamp())}_{safe_filename}"
    file_path = UPLOAD_DIR / safe_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted_text = extract_text(file_path, file.filename or safe_filename)
    parsed_data = parse_bloodwork_text(extracted_text) if section == "bloodwork" else {
        "patient_name": None,
        "date_of_birth": None,
        "age": None,
        "sex": None,
        "cnp": None,
        "patient_identifier": None,
        "lab_name": None,
        "sample_type": None,
        "referring_doctor": None,
        "report_name": section.title(),
        "report_type": section,
        "source_language": None,
        "test_date": None,
        "collected_on": None,
        "reported_on": None,
        "registered_on": None,
        "generated_on": None,
        "labs": [],
    }

    if target_patient:
        parsed_data["patient_name"] = target_patient.full_name
        parsed_data["date_of_birth"] = target_patient.date_of_birth
        parsed_data["age"] = target_patient.age
        parsed_data["sex"] = target_patient.sex
        parsed_data["cnp"] = target_patient.cnp
        parsed_data["patient_identifier"] = target_patient.patient_identifier

    document = models.Document(
        patient_id=target_patient.id if target_patient else None,
        uploaded_by_user_id=current_user.id,
        section=section,
        filename=file.filename or safe_filename,
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
                value=value_or_none(lab.get("value")),
                flag=value_or_none(lab.get("flag")),
                reference_range=value_or_none(lab.get("reference_range")),
                unit=value_or_none(lab.get("unit")),
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
