"""Auth routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"auth" domain — highest risk, extracted genuinely last since
`get_current_user`/`require_role` — imported by literally every other
router — were factored out (into app/api/dependencies.py) in the very
first extraction of this phase, precisely so every other domain could
be moved one at a time without touching auth's own routes until now).

Nothing about token semantics, password handling, or role-assignment
behavior changed: same JWT claims (`{"sub": ..., "role": ...}`), same
`verify_password_timing_safe` (constant-time password check that always
pays real bcrypt cost, whether or not the account exists — see its own
docstring), same generic "Invalid email or password" for both a wrong
password and a soft-deleted account (no new enumeration signal), same
role validation, same PCP/specialist doctor_type normalization, same
patient/care_partner signup side effects.

`serialize_user` and `ensure_patient_for_user` are imported lazily
(inside each function body) rather than at module load time: both are
still shared with several other already-extracted routers (which import
them the same lazy way), and neither has moved out of app.main in this
pass — relocating them is a separate service-extraction decision this
phase deliberately leaves for a dedicated follow-up (see
docs/KNOWN_GAPS.md), not folded into finishing the route-extraction
pass itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db
from app.auth import create_access_token, hash_password, verify_password_timing_safe
from app.core.utils import generate_public_id, now_iso
from app.rate_limit import RateLimiter

router = APIRouter()

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


@router.post("/auth/signup")
def signup(
    payload: SignupRequest,
    db: Session = Depends(get_db),
    _rl=Depends(RateLimiter(limit=10, window_seconds=3600, key_prefix="signup")),
):
    from app.main import _ensure_patient_code, serialize_user

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


@router.post("/auth/login")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rl=Depends(RateLimiter(limit=15, window_seconds=300, key_prefix="login")),
):
    from app.main import ensure_patient_for_user, serialize_user

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


@router.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    from app.main import serialize_user

    return serialize_user(current_user)
