"""Patients (core/PCP/search) + account (delete/export/profile) routes
(BRAGI backend modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md
— "patients (core/PCP/search)" and "account (delete/export)" domains,
extracted together since they were physically contiguous in the source
and account/profile routes call the same `build_patient_profile_response`
patients-domain helper). This is the largest and most central domain in
the whole backend, and includes the single highest-risk route in the
codebase: `DELETE /my/account`'s patient-deletion branch, which has a
documented history of FK-cascade bugs (see the inline comments below,
preserved verbatim — they explain exactly why each table is cleared in
this order, including two real bugs found and fixed by this feature's
own test suite before it ever shipped). Nothing about that deletion
logic — table order, what is hard-deleted vs. detached via SET NULL,
or any authorization check — was changed by this move.

Helpers still shared with domains not yet extracted (documents,
emergency, care-partner-code creation) are imported lazily (inside each
function body), consistent with every prior router this phase:
`doctor_reviewed_document`, `lab_flag_is_abnormal`,
`serialize_document_card` (all shared with app.main's still-inline
documents/emergency serialization code), `add_audit_log` (general
audit helper), and `ensure_patient_for_user` (care-partner-code
creation cluster).
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db, require_role
from app.auth import hash_password
from app.core.utils import _mask_cnp, now_iso
from app.policies.access import can_access_patient, doctor_has_patient_access, get_patient_for_user
from app.rate_limit import RateLimiter
from app.schemas.serializers import serialize_patient_event

router = APIRouter()


@router.get("/patients")
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
            .filter(
                models.DoctorPatientAccess.doctor_user_id == current_user.id,
                models.DoctorPatientAccess.is_active == 1,
            )
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
            # List view: masked. Full CNP isn't needed to browse a patient
            # list, only to confirm identity on a specific record — see
            # build_patient_profile_response / get_document_payload.
            "cnp": _mask_cnp(patient.cnp),
            "patient_identifier": patient.patient_identifier,
        }
        for patient in patients
    ]


@router.get("/my-patients")
def get_my_patients(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("doctor")),
):
    from app.main import doctor_reviewed_document, lab_flag_is_abnormal

    access_links = (
        db.query(models.DoctorPatientAccess)
        .filter(
            models.DoctorPatientAccess.doctor_user_id == current_user.id,
            models.DoctorPatientAccess.is_active == 1,
        )
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
                    "cnp": _mask_cnp(patient.cnp),
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


@router.get("/pcp/patients")
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


@router.get("/pcp/patients/{patient_id}/summary")
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

    # Patient events for hospitalization timeline entries
    patient_events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient_id)
        .order_by(models.PatientEvent.id.desc())
        .limit(20)
        .all()
    )

    # All documents for timeline (broader than recent_docs)
    all_docs_for_timeline = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .limit(40)
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

    _SECTION_EVENT_TYPE = {
        "bloodwork": "lab_panel",
        "discharge_summary": "discharge_summary",
        "scans": "imaging_report",
        "notes": "clinical_note",
        "medications": "medication_record",
        "hospitalizations": "hospitalization_record",
        "procedures": "procedure_report",
        "pathology": "pathology_report",
    }

    _DOC_SUMMARY_BY_EVENT_TYPE = {
        "lab_panel": "Lab panel with structured values extracted.",
        "clinical_note": "Clinical note recorded in patient file.",
        "discharge_summary": "Discharge summary recorded.",
        "imaging_report": "Imaging report recorded in patient file.",
        "medication_record": "Medication document recorded.",
        "operative_report": "Operative report recorded in patient file.",
        "pathology_report": "Pathology report recorded in patient file.",
        "prescription": "Prescription recorded in patient file.",
        "specialist_consultation": "Specialist consultation recorded in patient file.",
        "emergency_department_note": "Emergency department note recorded.",
        "hospital_admission_note": "Hospital admission note recorded.",
        "procedure_report": "Procedure report recorded in patient file.",
        "referral": "Referral recorded in patient file.",
    }

    def _event_type_for(doc) -> str:
        # Phase 5 — prefer Bragi's finer-grained document_type (Phase 1+
        # uploads) over the coarse legacy section, so e.g. an imaging vs.
        # operative vs. pathology document reads as a distinct, meaningful
        # timeline event instead of all three collapsing into whatever the
        # legacy "scans"/"hospitalizations" bucket implied. Falls back to
        # the section-based mapping for documents uploaded before automatic
        # classification existed (document_type is null there).
        if doc.document_type and doc.document_type != "other":
            return doc.document_type
        return _SECTION_EVENT_TYPE.get(doc.section, "source_document")

    def _doc_summary(doc, event_type: str) -> str:
        return _DOC_SUMMARY_BY_EVENT_TYPE.get(event_type, "Source document recorded in patient file.")

    pcp_timeline = []

    for doc in all_docs_for_timeline:
        event_type = _event_type_for(doc)
        pcp_timeline.append({
            "id": f"doc_{doc.id}",
            "event_type": event_type,
            "title": doc.report_name or doc.lab_name or doc.filename,
            "date": doc.test_date or doc.collected_on or doc.created_at or "",
            "source_id": doc.id,
            "source_type": "document",
            "summary": _doc_summary(doc, event_type),
            "route": f"/documents/{doc.id}",
            "is_source_linked": True,
        })

    for ev in patient_events:
        parts = [p for p in [ev.hospital_name, ev.department] if p]
        pcp_timeline.append({
            "id": f"event_{ev.id}",
            "event_type": "hospitalization_record",
            "title": ev.title,
            "date": ev.admitted_at or "",
            "source_id": None,
            "source_type": "event",
            "summary": " · ".join(parts) if parts else None,
            "route": None,
            "is_source_linked": False,
        })

    def _sort_key(e):
        d = e["date"] or "1970-01-01"
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(d.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    pcp_timeline.sort(key=_sort_key, reverse=True)

    return {
        "patient": {
            "id": patient.id,
            "public_id": patient.public_id,
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
                "created_at": m.created_at,
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
        "pcp_timeline": pcp_timeline,
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


@router.get("/patients/search")
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
                "cnp": _mask_cnp(patient.cnp),
                "patient_identifier": patient.patient_identifier,
                "care_partner_code": code_record.code if code_record else None,
                "has_access": has_access,
                "pending_request": pending_request,
            }
        )

    return results


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
    from app.main import serialize_document_card

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

    # Full CNP is only returned to the patient viewing their own profile.
    # A doctor/admin viewing someone else's profile through this same
    # response shape (GET /patients/{id}/profile) gets a masked value —
    # the frontend doesn't need the real value merely because the model
    # has it, and no identity-matching logic depends on this response
    # (that comparison happens server-side against the uploaded
    # document's own extracted CNP, not the frontend-supplied value).
    is_self = bool(current_user) and current_user.role == "patient" and patient.linked_user_id == current_user.id
    cnp_out = patient.cnp if is_self else _mask_cnp(patient.cnp)

    return {
        "patient": {
            "id": patient.id,
            "public_id": patient.public_id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            "cnp": cnp_out,
            "patient_identifier": patient.patient_identifier,
            "care_partner_code": code_record.code if code_record else None,
        },
        "sections": grouped_documents,
        "doctor_access": doctor_access,
        "events": [serialize_patient_event(event) for event in events],
    }


@router.get("/patients/{patient_id}/profile")
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


def _delete_care_partner_account(db: Session, current_user) -> None:
    """Real row delete — a care_partner's only rows are their own access
    grants (CarePartnerPatientLink) and document shares
    (SharedStructuredPage), neither of which is part of any patient's
    clinical record or another party's audit trail, unlike a doctor's or
    admin's. Safe to remove outright, same spirit as patient deletion."""
    db.query(models.CarePartnerPatientLink).filter(
        models.CarePartnerPatientLink.care_partner_user_id == current_user.id
    ).delete(synchronize_session=False)
    db.query(models.SharedStructuredPage).filter(
        models.SharedStructuredPage.care_partner_user_id == current_user.id
    ).delete(synchronize_session=False)
    db.flush()
    db.delete(current_user)


def _soft_delete_clinical_or_admin_account(db: Session, current_user) -> None:
    """Deactivate rather than delete the row — see run_migrations()'s
    comment on `users.deleted_at` for exactly why a real delete isn't
    offered for doctor/admin: too many NOT NULL clinical/audit references
    across other patients' own records would either block the delete
    (FK violation -> 500) or have to be silently orphaned/anonymized,
    which would itself corrupt those patients' care history. This still
    satisfies "no orphaned PHI" and "no 500s": the account becomes
    unusable (get_current_user()/login() both reject it), its own login
    credential (email/password) is irreversibly replaced, and every
    active patient-access grant is explicitly ended — nothing about the
    ACCOUNT's own login-identifying PHI survives; what survives is other
    people's clinical records that legitimately reference this person's
    professional involvement, which erasure does not override (GDPR
    Art.17(3)(b) — see docs/privacy/RETENTION_POLICY.md).

    `[LEGAL REVIEW]`: whether this is the correct final policy (vs. e.g.
    a longer grace period, or a different anonymization depth) is a
    legal/product decision, not an engineering one — documented
    separately in docs/privacy/DSAR_RUNBOOK.md rather than assumed here.
    """
    if current_user.role == "doctor":
        db.query(models.DoctorPatientAccess).filter(
            models.DoctorPatientAccess.doctor_user_id == current_user.id,
            models.DoctorPatientAccess.is_active == 1,
        ).update(
            {"is_active": 0, "ended_at": now_iso()},
            synchronize_session=False,
        )

    current_user.email = f"deleted-user-{current_user.id}-{uuid.uuid4().hex[:10]}@deleted.bragi.invalid"
    current_user.password_hash = hash_password(secrets.token_urlsafe(32))
    current_user.deleted_at = now_iso()
    db.add(current_user)


@router.delete("/my/account")
def delete_my_account(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient", "doctor", "admin", "care_partner")),
):
    # Deletion semantics are NOT identical across roles — see
    # BRAGI_SECURITY_GDPR_PLAN.md §19/Priority 8. Patient (below) and
    # care_partner are real row deletes. Doctor/admin are a soft-delete
    # (row persists, login disabled) — see
    # _soft_delete_clinical_or_admin_account's docstring for exactly why.
    # emergency_worker is deliberately not offered self-deletion yet
    # (product/legal decision required — see docs/privacy/DSAR_RUNBOOK.md).
    if current_user.role == "care_partner":
        _delete_care_partner_account(db, current_user)
        db.commit()
        return {"deleted": True}

    if current_user.role in ("doctor", "admin"):
        _soft_delete_clinical_or_admin_account(db, current_user)
        db.commit()
        return {"deleted": True}

    patient = get_patient_for_user(db, current_user.id)

    if patient:
        # Includes documents quarantined FOR this patient (identity
        # mismatch — patient_id is NULL, intended_patient_id points here;
        # see process_upload_job) as well as this patient's own documents
        # — both hold a real FK to patients.id and must be cleared before
        # the patient row itself can be deleted.
        docs = (
            db.query(models.Document)
            .filter(
                (models.Document.patient_id == patient.id)
                | (models.Document.intended_patient_id == patient.id)
            )
            .all()
        )
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
            # SourceEvidence.document_id is a required (NOT NULL) FK with no
            # ON DELETE CASCADE at the DB level, and Document itself only
            # declares an ORM cascade for its lab_results, not for
            # source_evidence directly — LabResult.source_evidence *does*
            # cascade (see LabResult model), so lab-linked evidence rows are
            # already cleared when their LabResult is cascade-deleted below.
            # But document-level evidence (lab_result_id IS NULL — the
            # narrative-document citation fallback added for Ask Bragi, see
            # _ensure_document_level_evidence) has no LabResult to ride that
            # cascade, so it must be cleared here explicitly. Without this,
            # deleting a patient who has ever had a document-level Ask Bragi
            # citation fails with a ForeignKeyViolation (reproduced against
            # both a local and a production account before this fix).
            db.query(models.SourceEvidence).filter(
                models.SourceEvidence.document_id.in_(doc_ids)
            ).delete(synchronize_session=False)
            # Document.parent_document_id (Reducto Split) and LabResult.
            # duplicate_of_lab_result_id (Phase 2 Level-3 dedup linking)
            # are both self-references that would otherwise block
            # deleting either side depending on order — both are now
            # ON DELETE SET NULL at the DB level (see run_migrations()),
            # so no manual clearing is needed here.

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
        # The patient's own authored data (unlike emergency-access-session/
        # audit-log rows, which are detached via ON DELETE SET NULL instead
        # — see run_migrations() — because those are access-audit records,
        # not this patient's own content).
        db.query(models.PatientMedication).filter(
            models.PatientMedication.patient_id == patient.id
        ).delete(synchronize_session=False)
        db.query(models.EmergencyContact).filter(
            models.EmergencyContact.patient_id == patient.id
        ).delete(synchronize_session=False)

        # Ask Bragi conversations/messages (found by this feature's own
        # test suite before it ever shipped — the same class of
        # FK-cascade gap §3 item 6 fixed for other tables). A bulk
        # .delete(synchronize_session=False) doesn't trigger the ORM
        # relationship's cascade, so messages must be cleared explicitly
        # before the conversations that reference patient.id.
        conversation_ids = [
            c.id
            for c in db.query(models.AskBragiConversation.id).filter(
                models.AskBragiConversation.patient_id == patient.id
            )
        ]
        if conversation_ids:
            db.query(models.AskBragiMessage).filter(
                models.AskBragiMessage.conversation_id.in_(conversation_ids)
            ).delete(synchronize_session=False)
            db.query(models.AskBragiConversation).filter(
                models.AskBragiConversation.id.in_(conversation_ids)
            ).delete(synchronize_session=False)

        # Interoperability (BRAGI_INTEROP_PLAN.md) — same FK-cascade class
        # of gap as Ask Bragi above, found the same way (this feature's own
        # test suite, before shipping). ExternalPatientIdentityLink.patient_id
        # is a required FK with no DB-level cascade; InteropIdentityConflict.
        # attempted_patient_id is nullable and only ever a historical
        # reference, so it's detached (SET NULL) rather than deleted — the
        # conflict record itself is an audit trail, not this patient's data.
        identity_link_ids = [
            link_id
            for (link_id,) in db.query(models.ExternalPatientIdentityLink.id).filter(
                models.ExternalPatientIdentityLink.patient_id == patient.id
            )
        ]
        if identity_link_ids:
            # InteropIdentityConflict.existing_link_id points back at a link
            # row — detach (SET NULL) rather than delete the conflict itself,
            # since the conflict is an audit record, not this patient's data.
            for conflict in db.query(models.InteropIdentityConflict).filter(
                models.InteropIdentityConflict.existing_link_id.in_(identity_link_ids)
            ):
                conflict.existing_link_id = None
            # SessionLocal is autoflush=False (see app/db.py) — the ORM
            # UPDATEs above are only pending in memory until flushed, but the
            # next statement is a bulk `.delete(synchronize_session=False)`,
            # which issues a raw DELETE directly and does NOT trigger
            # autoflush. Without this explicit flush, the DB still sees the
            # OLD existing_link_id value and the DELETE fails its FK check
            # (reproduced for real against Neon before this fix).
            db.flush()
            db.query(models.ExternalPatientIdentityLink).filter(
                models.ExternalPatientIdentityLink.id.in_(identity_link_ids)
            ).delete(synchronize_session=False)
        for conflict in db.query(models.InteropIdentityConflict).filter(
            models.InteropIdentityConflict.attempted_patient_id == patient.id
        ):
            conflict.attempted_patient_id = None

        db.delete(patient)
        db.flush()

    db.delete(current_user)
    db.commit()
    return {"deleted": True}


@router.delete("/my/access/{doctor_user_id}")
def revoke_doctor_access(
    doctor_user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

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


@router.get("/my/profile")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import ensure_patient_for_user

    patient = ensure_patient_for_user(db, current_user)
    return build_patient_profile_response(db, patient, current_user)


# Cap on how many original document files a single export embeds — this
# is a per-patient, self-service export, so the input is bounded by their
# own real usage, but a hard ceiling protects the server from an
# unbounded temp-file/disk-space blowup regardless. Documents beyond the
# cap are still fully described in documents_manifest.json; only the raw
# file bytes are left out, with a note explaining why.
DSAR_EXPORT_MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB total original-file payload


@router.post("/my/export")
def export_my_data(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
    _rl=Depends(RateLimiter(limit=3, window_seconds=86400, key_prefix="dsar_export")),
):
    """DSAR data export (GDPR Article 15/20) for the patient making the
    request — see docs/privacy/DSAR_RUNBOOK.md. Uses the same
    authorization as every other patient-scoped endpoint
    (require_role("patient") + get_patient_for_user, which only ever
    resolves to the requester's own linked Patient row) — there is no
    separate "which patient" parameter for this to get wrong, unlike a
    lookup-by-id endpoint.

    Returns a zip: profile.json, lab_results.json, medications.json,
    events.json, access_relationships.json, emergency_contacts.json,
    documents_manifest.json, ai_conversations.json (the patient's own Ask
    Bragi conversations — full message content/citations, whether the
    patient or a doctor asked; empty list if there are none or the
    feature is disabled), README.txt, and documents/ (the patient's own
    original uploaded files, up to DSAR_EXPORT_MAX_FILE_BYTES total).

    Deliberately excludes: any other patient's data (every query below is
    scoped to `patient.id`, never a caller-supplied id); quarantined
    documents uploaded under this identity but not yet confirmed as this
    patient's own record (`Document.patient_id` must match exactly —
    `intended_patient_id`-only rows are unconfirmed, not included);
    internal security metadata (password hashes, JWT internals, other
    users' emergency-access audit trail).
    """
    from app.main import add_audit_log

    patient = get_patient_for_user(db, current_user.id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient.id)
        .order_by(models.Document.id.asc())
        .all()
    )
    doc_ids = [d.id for d in documents]

    lab_results = (
        db.query(models.LabResult).filter(models.LabResult.document_id.in_(doc_ids)).all()
        if doc_ids
        else []
    )
    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient.id)
        .all()
    )
    events = (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == patient.id)
        .order_by(models.PatientEvent.admitted_at.desc())
        .all()
    )
    doctor_access = (
        db.query(models.DoctorPatientAccess)
        .filter(models.DoctorPatientAccess.patient_id == patient.id)
        .all()
    )
    access_requests = (
        db.query(models.DoctorPatientAccessRequest)
        .filter(models.DoctorPatientAccessRequest.patient_id == patient.id)
        .all()
    )
    care_partner_links = (
        db.query(models.CarePartnerPatientLink)
        .filter(models.CarePartnerPatientLink.patient_id == patient.id)
        .all()
    )
    emergency_contacts = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient.id)
        .all()
    )
    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )

    def _doctor_label(doctor_user_id: int | None) -> dict | None:
        if not doctor_user_id:
            return None
        doctor = db.query(models.User).filter(models.User.id == doctor_user_id).first()
        if not doctor:
            return None
        # A recipient's identity is itself something a DSAR is entitled to
        # disclose (GDPR Art. 15(1)(c), "recipients ... to whom the
        # personal data have been disclosed") — name/role only, never
        # their password hash or other account internals.
        return {"full_name": doctor.full_name, "role": doctor.role}

    profile_payload = {
        "id": patient.id,
        "public_id": patient.public_id,
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth,
        "age": patient.age,
        "sex": patient.sex,
        "cnp": patient.cnp,
        "patient_identifier": patient.patient_identifier,
        "emergency_search_enabled": bool(patient.emergency_search_enabled),
        "account_email": current_user.email,
        "care_partner_code": code_record.code if code_record else None,
    }

    lab_results_payload = [
        {
            "document_id": lr.document_id,
            "raw_test_name": lr.raw_test_name,
            "canonical_name": lr.canonical_name,
            "display_name": lr.display_name,
            "category": lr.category,
            "value": lr.value,
            "flag": lr.flag,
            "reference_range": lr.reference_range,
            "unit": lr.unit,
            "observation_datetime": lr.observation_datetime,
            "institution": lr.institution,
            "specimen": lr.specimen,
            "verification_state": lr.verification_state,
        }
        for lr in lab_results
    ]

    medications_payload = [
        {
            "name": m.name,
            "dose_strength": m.dose_strength,
            "frequency": m.frequency,
            "reason": m.reason,
            "status": m.status,
            "route_form": m.route_form,
            "start_date": m.start_date,
            "stop_date": m.stop_date,
            "prescriber": m.prescriber,
            "extra_info": m.extra_info,
            "is_uncertain": bool(m.is_uncertain),
            "created_at": m.created_at,
            "updated_at": m.updated_at,
            "official_source_name": m.official_source_name,
            "official_source_url": m.official_source_url,
        }
        for m in medications
    ]

    events_payload = [
        {
            "event_type": e.event_type,
            "status": e.status,
            "title": e.title,
            "description": e.description,
            "hospital_name": e.hospital_name,
            "department": e.department,
            "admitted_at": e.admitted_at,
            "discharged_at": e.discharged_at,
            "attending_doctor": _doctor_label(e.doctor_user_id),
        }
        for e in events
    ]

    access_payload = {
        "doctor_access_grants": [
            {
                "doctor": _doctor_label(a.doctor_user_id),
                "granted_at": a.granted_at,
                "is_active": bool(a.is_active),
                "ended_at": a.ended_at,
            }
            for a in doctor_access
        ],
        "doctor_access_requests": [
            {
                "doctor": _doctor_label(r.doctor_user_id),
                "status": r.status,
                "requested_at": r.requested_at,
                "responded_at": r.responded_at,
            }
            for r in access_requests
        ],
        "care_partner_links": [
            {
                "care_partner": _doctor_label(link.care_partner_user_id),
                "linked_at": link.linked_at,
            }
            for link in care_partner_links
        ],
    }

    emergency_contacts_payload = [
        {
            "name": c.name,
            "relationship": c.contact_relationship,
            "phone": c.phone,
            "notes": c.notes,
        }
        for c in emergency_contacts
    ]

    # Ask Bragi conversations (feature-flagged; empty list wherever the
    # feature doesn't exist/hasn't been used — this is the patient's own
    # data being exported to themselves, so full question/answer text is
    # included here even though it's deliberately excluded from server
    # audit logs (see main.py's Ask Bragi section / BRAGI_ASK_BRAGI_PLAN.md).
    ask_bragi_conversations = (
        db.query(models.AskBragiConversation)
        .filter(models.AskBragiConversation.patient_id == patient.id)
        .order_by(models.AskBragiConversation.id.asc())
        .all()
    )
    ask_bragi_payload = [
        {
            "conversation_id": conv.id,
            "scope": conv.scope,
            "document_id": conv.document_id,
            "created_at": conv.created_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "citations": json.loads(m.citations_json) if m.citations_json else [],
                    "created_at": m.created_at,
                }
                for m in conv.messages
            ],
        }
        for conv in ask_bragi_conversations
    ]

    documents_manifest: list[dict] = []
    embedded_bytes = 0
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".zip", prefix="bragi-dsar-export-")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)

    try:
        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for document in documents:
                entry = {
                    "document_id": document.id,
                    "public_id": document.public_id,
                    "filename": document.filename,
                    "section": document.section,
                    "document_type": document.document_type,
                    "report_name": document.report_name,
                    "test_date": document.test_date,
                    "created_at": document.created_at,
                    "uploaded_by": _doctor_label(document.uploaded_by_user_id),
                    "included_in_documents_folder": False,
                }
                if document.saved_to:
                    file_path = Path(document.saved_to)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        if embedded_bytes + size <= DSAR_EXPORT_MAX_FILE_BYTES:
                            arcname = f"documents/{document.id}_{document.filename}"
                            zf.write(file_path, arcname=arcname)
                            embedded_bytes += size
                            entry["included_in_documents_folder"] = True
                        else:
                            entry["note"] = "Original file omitted — export size cap reached (see README.txt)."
                documents_manifest.append(entry)
                add_audit_log(
                    db=db,
                    document_id=document.id,
                    action="dsar_export",
                    actor=f"patient_self:{current_user.id}",
                    details="Included in a self-service data export (GDPR DSAR).",
                )

            readme = f"""Bragi data export
Generated: {now_iso()}
Patient: {patient.full_name} (internal id {patient.id})

This archive contains the personal data Bragi holds about you, generated
in response to a data export request (GDPR Article 15/20). See
docs/privacy/DSAR_RUNBOOK.md in the Bragi source repository for the
policy this implements.

Contents:
- profile.json — your account/profile data
- lab_results.json — structured lab results extracted from your documents
- medications.json — your medication list
- events.json — your care timeline (admissions, discharges)
- access_relationships.json — clinicians/care partners who have or had
  access to your record, and any pending access requests
- emergency_contacts.json — emergency contacts you added
- documents_manifest.json — metadata for every uploaded document
- documents/ — the original uploaded files themselves, where the export
  size cap allowed inclusion (see documents_manifest.json's
  "included_in_documents_folder"/"note" fields for any that were left out)
- ai_conversations.json — your Ask Bragi conversations, if any (empty
  list if you have none, or if this feature is not enabled)

Not included: any other patient's data; documents uploaded under your
identity but not yet confirmed as belonging to your record (an identity
mismatch/review queue, not your official record); internal account
security metadata (password hash, auth tokens).
"""
            zf.writestr("README.txt", readme)
            zf.writestr("profile.json", json.dumps(profile_payload, indent=2))
            zf.writestr("lab_results.json", json.dumps(lab_results_payload, indent=2))
            zf.writestr("medications.json", json.dumps(medications_payload, indent=2))
            zf.writestr("events.json", json.dumps(events_payload, indent=2))
            zf.writestr("access_relationships.json", json.dumps(access_payload, indent=2))
            zf.writestr("emergency_contacts.json", json.dumps(emergency_contacts_payload, indent=2))
            zf.writestr("documents_manifest.json", json.dumps(documents_manifest, indent=2))
            zf.writestr("ai_conversations.json", json.dumps(ask_bragi_payload, indent=2))

        db.commit()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # PHI-free summary log only (counts, never content) — this export's
    # per-document AuditLog rows above are the durable, queryable audit
    # trail; this line is just an operational breadcrumb.
    print(
        f"DSAR EXPORT: patient_id={patient.id} user_id={current_user.id} "
        f"documents={len(documents)} embedded_bytes={embedded_bytes}"
    )

    background_tasks.add_task(lambda: tmp_path.unlink(missing_ok=True))
    export_filename = f"bragi-export-{patient.public_id or patient.id}.zip"
    return FileResponse(
        path=str(tmp_path),
        filename=export_filename,
        media_type="application/zip",
        background=background_tasks,
    )
