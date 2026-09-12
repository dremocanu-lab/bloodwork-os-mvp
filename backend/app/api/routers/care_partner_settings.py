"""Care-partner + emergency-contact settings routes (BRAGI backend
modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"care-partner + emergency-contact settings" domain — moderate, mostly
self-contained). Covers care-partner code issuance, the patient-side
emergency-discoverability toggle (which also revokes any active
break-glass sessions when disabled), emergency contacts CRUD, the
patient's/care-partner's own relationship listings, and document-sharing
with care partners.

Two helpers are imported lazily (inside each function body) rather than
at module load time, since they still live in app.main and app.main
imports this router at the end of its own module body (a top-level
import here would be circular — safe only deferred to call time, after
app.main has fully finished loading):

- `ensure_patient_for_user` — belongs with the not-yet-extracted
  care-partner-code *creation* helpers (`_ensure_patient_code` /
  `_generate_unique_care_partner_code`), which is why it stays put for
  now rather than moving piecemeal.
- `_generate_unique_care_partner_code` — same reason.
- `_add_emergency_audit` — belongs to the emergency (break-glass) domain,
  which Phase 4's decomposition plan deliberately extracts last among
  "normal" domains, with extra care, since every route there is
  independently audited. Reusing it unchanged here (not reimplementing
  its audit-logging semantics) is required to preserve exact behavior.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db, require_role
from app.core.utils import now_iso
from app.policies.access import can_access_patient, get_patient_for_user

router = APIRouter()


class EmergencyAccessSettingRequest(BaseModel):
    emergency_search_enabled: bool


class EmergencyContactPayload(BaseModel):
    name: str
    relationship: str | None = None
    phone: str | None = None
    notes: str | None = None


class ShareDocumentRequest(BaseModel):
    care_partner_user_id: int


def _contact_dict(c: models.EmergencyContact) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "relationship": c.contact_relationship,
        "phone": c.phone,
        "notes": c.notes,
        "created_at": c.created_at,
    }


@router.get("/my/care-partner-code")
def get_care_partner_code(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import _generate_unique_care_partner_code, ensure_patient_for_user

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


@router.post("/my/care-partner-code/regenerate")
def regenerate_care_partner_code(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import _generate_unique_care_partner_code, ensure_patient_for_user

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


@router.get("/my/settings/emergency-access")
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


@router.put("/my/settings/emergency-access")
def update_emergency_access_setting(
    payload: EmergencyAccessSettingRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("patient")),
):
    from app.main import _add_emergency_audit

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


@router.get("/my/settings/emergency-contacts")
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


@router.post("/my/settings/emergency-contacts")
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


@router.put("/my/settings/emergency-contacts/{contact_id}")
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


@router.delete("/my/settings/emergency-contacts/{contact_id}")
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


@router.get("/my/care-partners")
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


@router.get("/my/dependants")
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


@router.get("/my/shared-pages")
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


@router.get("/documents/{document_id}/shares")
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


@router.post("/documents/{document_id}/share")
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


@router.delete("/documents/{document_id}/share/{care_partner_user_id}")
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
