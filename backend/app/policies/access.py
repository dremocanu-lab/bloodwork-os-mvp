"""Shared patient-access authorization helpers (BRAGI backend
modularization, Phase 4).

Moved verbatim from app/main.py, one function at a time as each caller
needs it outside main.py. These are used by nearly every clinical domain
(patients, patient-events, labs, documents, assignments, medications,
admin) and are exactly the kind of helpers
docs/refactor/AUTHORIZATION_MAP.md calls out as centralization
candidates — they are relocated here now, unchanged, so that domains as
they are extracted can import them without a circular dependency on
app.main. This is a plain code move, not a semantics change: every check
below is byte-for-byte identical to the original. Centralizing/
consolidating authorization logic (as opposed to relocating existing,
already-canonical implementations) happens later, per Phase 4's own
ordering, only after routers are stable.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import models


def get_patient_for_user(db: Session, user_id: int):
    return db.query(models.Patient).filter(models.Patient.linked_user_id == user_id).first()


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
