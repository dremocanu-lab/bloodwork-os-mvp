"""Medication routes (BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"medications" domain — moderate size, clear boundary, own serializers).
Must preserve exactly: active/as_needed/paused/stopped status semantics
(VALID_MED_STATUSES), and the shape consumed by Ask Bragi's
medication-conflict tool — that tool queries `models.PatientMedication`
directly (app/services/ask_bragi/*), not through this module, so it is
unaffected by this move; nothing here was renamed or restructured.

`ensure_patient_for_user` is imported lazily (inside each function body)
rather than at module load time: it still lives in app.main (it belongs
conceptually with the not-yet-extracted care-partner-code domain, since
it transitively calls `_ensure_patient_code` /
`_generate_unique_care_partner_code`), and app.main itself imports this
router at the end of its own module body — a top-level `from app.main
import ...` here would be circular. A local import deferred to call time
is safe because app.main has always finished executing (including
registering this router) before any request is served. The same pattern
already exists in app.main's own `rate_limit_status` route.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import now_iso
from app.policies.access import doctor_has_patient_access
from app.rate_limit import RateLimiter
from app.services.medication_lookup import lookup_medication

router = APIRouter()

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

@router.get("/my/medications")
def list_my_medications(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

    patient = ensure_patient_for_user(db, current_user)
    meds = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient.id)
        .order_by(models.PatientMedication.id.desc())
        .all()
    )
    return [serialize_medication(m) for m in meds]


@router.post("/my/medications", status_code=201)
def create_medication(
    payload: MedicationCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

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


@router.get("/my/medications/{medication_id}")
def get_my_medication(
    medication_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

    patient = ensure_patient_for_user(db, current_user)
    med = db.query(models.PatientMedication).filter(
        models.PatientMedication.id == medication_id,
        models.PatientMedication.patient_id == patient.id,
    ).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    return serialize_medication(med)


@router.put("/my/medications/{medication_id}")
def update_medication(
    medication_id: int,
    payload: MedicationUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

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


@router.delete("/my/medications/{medication_id}")
def delete_medication(
    medication_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

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


@router.post("/my/medications/{medication_id}/refresh-official-info")
def refresh_medication_official_info(
    medication_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
    _rl=Depends(RateLimiter(limit=20, window_seconds=3600, key_prefix="external_lookup")),
):
    from app.main import ensure_patient_for_user

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


@router.post("/my/medications/{medication_id}/select-rxcui")
def select_medication_rxcui(
    medication_id: int,
    payload: MedicationRxcuiSelectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    """Patient explicitly selects one RxCUI from multiple candidates."""
    from app.main import ensure_patient_for_user

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

@router.get("/patients/{patient_id}/medications")
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


@router.get("/patients/{patient_id}/medications/{medication_id}")
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
