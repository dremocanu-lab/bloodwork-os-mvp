"""Admin portal routes: doctor/patient management (BRAGI backend
modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"admin (doctor/patient mgmt)" domain — moderate, admin-only throughout).
Covers admin patient/doctor search and lookup (scoped to the admin's own
department/hospital via `_validate_doctor_in_admin_scope`), doctor
assignment batch-create/end, and the care-partner-code redemption route
(`/my/link-patient` — role `care_partner`, grouped here per the
decomposition plan for its physical/conceptual adjacency to the other
patient-linking routes), plus the analyte-gap report.

Note: `link_patient` (below) has one line of pre-existing dead code
(`return serialize_patient_event(event)` after the function's real
return) inherited unchanged from app/main.py — `event` was never even
defined in this function's scope. It is unreachable and has zero
behavioral effect, so it is moved verbatim rather than silently
"cleaned up" here; per Phase 4's own rule, dead-code removal happens
only in the dedicated cleanup pass at the end, with evidence, not
folded into a domain-extraction commit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import _mask_cnp, now_iso
from app.services.lab_catalog import find_lab_definition

router = APIRouter()


def _validate_doctor_in_admin_scope(admin_user, doctor) -> None:
    if admin_user.department and doctor.department != admin_user.department:
        raise HTTPException(status_code=403, detail="Doctor is not in your department.")
    if admin_user.hospital_name and doctor.hospital_name != admin_user.hospital_name:
        raise HTTPException(status_code=403, detail="Doctor is not in your hospital.")


@router.get("/admin/patients/search")
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


@router.get("/admin/doctors")
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


@router.get("/admin/doctors/{doctor_id}")
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


@router.get("/admin/doctors/{doctor_id}/current-patients")
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


@router.get("/admin/doctors/{doctor_id}/patient-history")
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


@router.get("/admin/patients/{patient_id}/assignments")
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


@router.post("/admin/assignments/batch")
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


@router.post("/admin/assignments/{assignment_id}/end")
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


@router.post("/my/link-patient")
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

    return serialize_patient_event(event)  # noqa: F821 — pre-existing unreachable dead code, moved verbatim


@router.get("/admin/analyte-gaps")
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
