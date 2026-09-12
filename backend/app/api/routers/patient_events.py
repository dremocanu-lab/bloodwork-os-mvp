"""Patient-event (hospitalization timeline) routes (BRAGI backend
modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"patient events/timeline" domain — small, low fan-out). The read/list side
of this timeline (GET .../patient-events as part of a patient's profile) is
still served by `build_patient_profile_response` in app/main.py, which is
extracted separately with the patients domain; these are the two mutation
routes (create + discharge) that stand alone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import now_iso
from app.policies.access import doctor_has_patient_access
from app.schemas.serializers import serialize_patient_event

router = APIRouter()


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


@router.post("/patient-events")
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


@router.post("/patient-events/{event_id}/discharge")
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
