"""Emergency access portal (break-glass) routes (BRAGI backend
modularization, Phase 4).

Moved verbatim from app/main.py (docs/refactor/BACKEND_DECOMPOSITION_PLAN.md,
"emergency (break-glass)" domain — high risk, security-critical, heavily
audited). Every route here is independently audited via
`_add_emergency_audit` (EmergencyAuditLog) — every call site and every
`details=`/action string is preserved exactly, since this is the durable
compliance trail for break-glass access, not just informational logging.

`_add_emergency_audit` is exported from here (not lazily re-defined)
because app/api/routers/care_partner_settings.py's patient-side
emergency-discoverability toggle also needs to write the same audit
trail when it revokes active sessions — that router imports it lazily
as `from app.api.routers.emergency import _add_emergency_audit`, the
same deferred-import pattern used everywhere else this phase (safe
regardless of router registration order, since it's resolved at call
time, well after both routers are fully loaded).

`get_document_payload` stays in app.main (shared with the documents
domain) and is imported lazily here, same as every prior router.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_current_user, get_db
from app.core.utils import _mask_cnp, generate_public_id, now_iso
from app.rate_limit import RateLimiter

router = APIRouter()

EMERGENCY_SESSION_MINUTES = 30


def require_emergency_role():
    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in ("emergency_worker", "admin"):
            raise HTTPException(status_code=403, detail="Emergency access only")
        return current_user
    return dependency


def _get_active_emergency_session(
    db: Session,
    session_id: int,
    user_id: int,
) -> models.EmergencyAccessSession | None:
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == user_id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
        )
        .first()
    )
    if not session:
        return None
    if session.expires_at < now_iso():
        return None
    return session


def _add_emergency_audit(
    db: Session,
    action: str,
    emergency_user_id: int | None = None,
    patient_id: int | None = None,
    session_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: str | None = None,
) -> None:
    db.add(
        models.EmergencyAuditLog(
            emergency_user_id=emergency_user_id,
            patient_id=patient_id,
            session_id=session_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            timestamp=now_iso(),
        )
    )


def _serialize_emergency_search_result(patient, code_record) -> dict:
    masked_id = _mask_cnp(patient.cnp)
    if not masked_id and patient.patient_identifier:
        raw = patient.patient_identifier
        masked_id = raw[:3] + "***" if len(raw) > 3 else "***"
    return {
        "id": patient.id,
        "full_name": patient.full_name,
        "age": patient.age,
        "sex": patient.sex,
        "bragi_code": code_record.code if code_record else None,
        "masked_identifier": masked_id,
    }


class EmergencySessionCreateRequest(BaseModel):
    patient_id: int
    reason: str
    reason_note: str | None = None


class EmergencySearchRequest(BaseModel):
    type: str
    q: str


def _run_emergency_search(type: str, q: str, request: Request, db: Session, current_user) -> list[dict]:
    q = q.strip()
    if not q:
        return []

    results: list[dict] = []

    if type == "code":
        term = q.upper().replace(" ", "")
        code_records = (
            db.query(models.PatientCarePartnerCode)
            .filter(func.upper(models.PatientCarePartnerCode.code).contains(term))
            .limit(20)
            .all()
        )
        for cr in code_records:
            patient = db.query(models.Patient).filter(
                models.Patient.id == cr.patient_id,
                models.Patient.emergency_search_enabled == 1,
            ).first()
            if patient:
                results.append(_serialize_emergency_search_result(patient, cr))
                if len(results) >= 5:
                    break

    elif type == "cnp":
        patient = db.query(models.Patient).filter(
            models.Patient.cnp == q,
            models.Patient.emergency_search_enabled == 1,
        ).first()
        if patient:
            cr = db.query(models.PatientCarePartnerCode).filter(
                models.PatientCarePartnerCode.patient_id == patient.id
            ).first()
            results.append(_serialize_emergency_search_result(patient, cr))

    elif type == "name":
        term = f"%{q.lower()}%"
        patients = (
            db.query(models.Patient)
            .filter(
                func.lower(models.Patient.full_name).like(term),
                models.Patient.emergency_search_enabled == 1,
            )
            .limit(10)
            .all()
        )
        for patient in patients:
            cr = db.query(models.PatientCarePartnerCode).filter(
                models.PatientCarePartnerCode.patient_id == patient.id
            ).first()
            results.append(_serialize_emergency_search_result(patient, cr))

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_patient_search",
        emergency_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        details=f"type={type} q_len={len(q)} results={len(results)}",
    )
    db.commit()

    return results


@router.post("/emergency/search")
def emergency_search_post(
    payload: EmergencySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=60, window_seconds=300, key_prefix="emergency_search")),
):
    """POST form of emergency search — the only path that accepts a CNP
    lookup. CNP travels in the JSON request body, never in a URL query
    string (so it never lands in browser history, server access logs, or
    a proxy/CDN's request-URL logging). This is the endpoint every
    current frontend caller uses, for every search type."""
    return _run_emergency_search(payload.type, payload.q, request, db, current_user)


@router.get("/emergency/search")
def emergency_search(
    type: str = Query(...),
    q: str = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=60, window_seconds=300, key_prefix="emergency_search")),
):
    """Legacy GET form, kept only for `code`/`name` lookups (a Bragi
    care-partner code or a name substring are not direct identifiers the
    same way a national ID is). A CNP is a direct identifier and must
    never be placed in a URL query string — that path is closed here
    unconditionally, independent of which client is calling. Use
    POST /emergency/search for CNP lookups."""
    if type == "cnp":
        raise HTTPException(
            status_code=400,
            detail="CNP search requires POST /emergency/search with a JSON body, not a query string.",
        )
    return _run_emergency_search(type, q, request, db, current_user)


@router.post("/emergency/access-sessions")
def create_emergency_session(
    payload: EmergencySessionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
    _rl=Depends(RateLimiter(limit=30, window_seconds=3600, key_prefix="emergency_session")),
):
    from datetime import timedelta

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient or not patient.emergency_search_enabled:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        _add_emergency_audit(
            db,
            action="emergency_session_denied_patient_not_searchable",
            emergency_user_id=current_user.id,
            patient_id=payload.patient_id if patient else None,
            ip_address=ip,
            user_agent=ua,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="No emergency-searchable patient found.")

    # Return existing active session for same patient — no duplicate tabs
    now_str = now_iso()
    existing = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.patient_id == payload.patient_id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .first()
    )
    if existing:
        cr = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.patient_id == patient.id)
            .first()
        )
        return {
            "id": existing.id,
            "patient_id": existing.patient_id,
            "patient_name": patient.full_name,
            "bragi_code": cr.code if cr else None,
            "reason": existing.reason,
            "started_at": existing.started_at,
            "expires_at": existing.expires_at,
            "existing": True,
        }

    # Enforce max 8 active sessions per emergency worker
    active_count = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .count()
    )
    if active_count >= 8:
        raise HTTPException(status_code=409, detail="Maximum 8 active emergency sessions reached")

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=EMERGENCY_SESSION_MINUTES)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    session = models.EmergencyAccessSession(
        emergency_user_id=current_user.id,
        patient_id=payload.patient_id,
        reason=payload.reason,
        reason_note=payload.reason_note,
        started_at=now.isoformat(),
        expires_at=expires.isoformat(),
        closed_at=None,
        ip_address=ip,
        user_agent=ua,
        created_at=now.isoformat(),
        public_id=generate_public_id("brg-em"),
    )
    db.add(session)
    db.flush()

    _add_emergency_audit(
        db,
        action="emergency_session_started",
        emergency_user_id=current_user.id,
        patient_id=payload.patient_id,
        session_id=session.id,
        ip_address=ip,
        user_agent=ua,
        details=f"reason={payload.reason}",
    )
    db.commit()
    db.refresh(session)

    cr = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient.id)
        .first()
    )
    return {
        "id": session.id,
        "public_id": session.public_id,
        "patient_id": session.patient_id,
        "patient_name": patient.full_name,
        "bragi_code": cr.code if cr else None,
        "reason": session.reason,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "existing": False,
    }


@router.get("/emergency/access-sessions/active")
def get_active_emergency_sessions(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    from datetime import timezone
    now_str = now_iso()
    sessions = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
            models.EmergencyAccessSession.closed_at.is_(None),
            models.EmergencyAccessSession.revoked_at.is_(None),
            models.EmergencyAccessSession.expires_at > now_str,
        )
        .order_by(models.EmergencyAccessSession.created_at.asc())
        .all()
    )
    result = []
    for s in sessions:
        patient = db.query(models.Patient).filter(models.Patient.id == s.patient_id).first()
        if not patient or not patient.emergency_search_enabled:
            continue
        cr = (
            db.query(models.PatientCarePartnerCode)
            .filter(models.PatientCarePartnerCode.patient_id == s.patient_id)
            .first()
        )
        expires_dt = datetime.fromisoformat(s.expires_at)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        secs = max(0, int((expires_dt - datetime.now(timezone.utc)).total_seconds()))
        result.append({
            "id": s.id,
            "patient_id": s.patient_id,
            "patient_name": patient.full_name,
            "bragi_code": cr.code if cr else None,
            "started_at": s.started_at,
            "expires_at": s.expires_at,
            "seconds_remaining": secs,
            "reason": s.reason,
        })
    _add_emergency_audit(
        db,
        action="emergency_workspace_opened",
        emergency_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return result


@router.get("/emergency/sessions/by-public-id/{public_id}")
def get_emergency_session_by_public_id(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.public_id == public_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"id": session.id, "public_id": session.public_id}


@router.get("/emergency/access-sessions/{session_id}")
def get_emergency_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    is_active = session.closed_at is None and session.expires_at > now_iso()
    return {
        "id": session.id,
        "patient_id": session.patient_id,
        "reason": session.reason,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "closed_at": session.closed_at,
        "is_active": is_active,
    }


@router.post("/emergency/access-sessions/{session_id}/close")
def close_emergency_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    session = (
        db.query(models.EmergencyAccessSession)
        .filter(
            models.EmergencyAccessSession.id == session_id,
            models.EmergencyAccessSession.emergency_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.closed_at is None:
        session.closed_at = now_iso()
        _add_emergency_audit(
            db,
            action="emergency_session_closed_manually",
            emergency_user_id=current_user.id,
            patient_id=session.patient_id,
            session_id=session_id,
        )
        db.commit()

    return {"ok": True}


@router.get("/emergency/patients/{patient_id}")
def emergency_get_patient(
    patient_id: int,
    session_id: int = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    active_session = _get_active_emergency_session(db, session_id, current_user.id)
    if not active_session:
        raise HTTPException(status_code=403, detail="Emergency session expired or not found")
    if active_session.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Session does not cover this patient")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not patient.emergency_search_enabled:
        raise HTTPException(status_code=403, detail="Emergency access is no longer available for this patient.")

    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.patient_id == patient_id)
        .order_by(models.PatientMedication.status, models.PatientMedication.name)
        .all()
    )

    documents = (
        db.query(models.Document)
        .filter(models.Document.patient_id == patient_id)
        .order_by(models.Document.id.desc())
        .limit(100)
        .all()
    )

    # Latest bloodwork with labs (no extracted text)
    latest_bloodwork = None
    for doc in documents:
        if doc.section == "bloodwork":
            labs = (
                db.query(models.LabResult)
                .filter(models.LabResult.document_id == doc.id)
                .limit(40)
                .all()
            )
            latest_bloodwork = {
                "document_id": doc.id,
                "filename": doc.filename,
                "test_date": doc.test_date,
                "lab_name": doc.lab_name,
                "labs": [
                    {
                        "name": lab.display_name or lab.raw_test_name,
                        "value": lab.value,
                        "unit": lab.unit,
                        "flag": lab.flag,
                        "reference_range": lab.reference_range,
                    }
                    for lab in labs
                ],
            }
            break

    code_record = (
        db.query(models.PatientCarePartnerCode)
        .filter(models.PatientCarePartnerCode.patient_id == patient_id)
        .first()
    )

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_patient_page_opened",
        emergency_user_id=current_user.id,
        patient_id=patient_id,
        session_id=session_id,
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()

    emergency_contacts = (
        db.query(models.EmergencyContact)
        .filter(models.EmergencyContact.patient_id == patient_id)
        .order_by(models.EmergencyContact.id)
        .all()
    )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "sex": patient.sex,
            "bragi_code": code_record.code if code_record else None,
            # CNP intentionally omitted
        },
        "session": {
            "id": active_session.id,
            "started_at": active_session.started_at,
            "expires_at": active_session.expires_at,
            "reason": active_session.reason,
        },
        "medications": [
            {
                "id": m.id,
                "name": m.name,
                "dose_strength": m.dose_strength,
                "frequency": m.frequency,
                "status": m.status,
                "route_form": m.route_form,
                "is_uncertain": bool(m.is_uncertain),
            }
            for m in medications
        ],
        "documents": [
            {
                "id": doc.id,
                "section": doc.section,
                "filename": doc.filename,
                "test_date": doc.test_date or doc.created_at,
                "lab_name": doc.lab_name,
                "report_name": doc.report_name,
                "is_verified": bool(doc.is_verified),
                "created_at": doc.created_at,
            }
            for doc in documents
        ],
        "latest_bloodwork": latest_bloodwork,
        "emergency_contacts": [
            {
                "id": c.id,
                "name": c.name,
                "relationship": c.contact_relationship,
                "phone": c.phone,
                "notes": c.notes,
            }
            for c in emergency_contacts
        ],
    }


@router.get("/emergency/documents/{document_id}")
def emergency_get_document(
    document_id: int,
    session_id: int = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_emergency_role()),
):
    from app.main import get_document_payload

    active_session = _get_active_emergency_session(db, session_id, current_user.id)
    if not active_session:
        raise HTTPException(status_code=403, detail="Emergency session expired or not found")

    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.patient_id != active_session.patient_id:
        raise HTTPException(status_code=403, detail="Document does not belong to this emergency session's patient")

    session_patient = db.query(models.Patient).filter(models.Patient.id == active_session.patient_id).first()
    if not session_patient or not session_patient.emergency_search_enabled:
        raise HTTPException(status_code=403, detail="Emergency access is no longer available for this patient.")

    labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
    audit_logs = db.query(models.AuditLog).filter(models.AuditLog.document_id == document.id).all()

    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    _add_emergency_audit(
        db,
        action="emergency_document_opened",
        emergency_user_id=current_user.id,
        patient_id=active_session.patient_id,
        session_id=session_id,
        ip_address=ip,
        user_agent=ua,
        details=f"document_id={document_id}",
    )
    db.commit()

    payload = get_document_payload(db, document, labs, audit_logs, current_user=None)
    if payload.get("parsed_data"):
        payload["parsed_data"].pop("cnp", None)
    return payload
