"""Server-owned Ask Bragi patient/document scope.

This is the single most important file for Ask Bragi's security model —
see BRAGI_ASK_BRAGI_PLAN.md §"Patient-context model". The rule this file
exists to enforce: **the model never chooses a patient**. A conversation
is bound to exactly one `patient_id` (and optionally one `document_id`)
at creation time, resolved from the AUTHENTICATED CALLER's own
authorization, never from anything the model or a tool argument could
influence. No tool schema in `tools.py` accepts a `patient_id` parameter
— it is not a parameter that exists to be spoofed.

`recheck_access()` deliberately re-implements the same two authorization
checks `can_access_patient()`/`doctor_has_patient_access()` already
enforce in `app/main.py`, rather than importing them, to avoid a
circular import (`main.py` is where the FastAPI app and those functions
live; this module is imported BY `main.py`'s route handlers). Kept
intentionally tiny (a handful of lines, mirroring main.py's own logic
exactly) specifically so it's easy to keep in sync by inspection — see
BRAGI_ASK_BRAGI_PLAN.md for this trade-off's rationale. Every sensitive
tool call re-runs this (Priority: "re-authorize every tool call, not
just once" — see `tools.py`'s dispatcher).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models


class AskBragiAccessDenied(Exception):
    """Raised by recheck_access()/resolve_context() on any authorization
    failure. Callers must turn this into a 403/404 at the route layer —
    never leak *why* (existence vs. access) any more precisely than the
    rest of this app's routes already do."""


def recheck_access(db: Session, *, requester_user_id: int, requester_role: str, patient_id: int) -> bool:
    """Mirrors app/main.py's can_access_patient()/doctor_has_patient_access()
    exactly. Re-run on every tool call, not cached — a revoked doctor or a
    deleted patient must fail the very next tool call, not just future
    conversations."""
    if requester_role == "admin":
        return True

    if requester_role == "doctor":
        active_grant = (
            db.query(models.DoctorPatientAccess)
            .filter(
                models.DoctorPatientAccess.doctor_user_id == requester_user_id,
                models.DoctorPatientAccess.patient_id == patient_id,
                models.DoctorPatientAccess.is_active == 1,
            )
            .first()
        )
        return active_grant is not None

    if requester_role == "patient":
        patient = (
            db.query(models.Patient)
            .filter(models.Patient.linked_user_id == requester_user_id)
            .first()
        )
        return patient is not None and patient.id == patient_id

    return False


@dataclass
class AskBragiContext:
    """Bound once per request (built fresh from the DB every time — never
    cached across requests/conversations). Tools receive this, never a
    raw patient_id parameter they could set themselves."""

    db: Session
    patient_id: int
    requester_user_id: int
    requester_role: str
    scope: str  # "patient_record" | "document"
    document_id: int | None = None
    authorized_evidence_ids: set[int] = field(default_factory=set)
    authorized_document_ids: set[int] = field(default_factory=set)

    def require_current_access(self) -> None:
        """Call at the top of EVERY tool dispatch — see tools.py. Raises
        AskBragiAccessDenied if access no longer holds (revoked doctor,
        deleted patient, etc.)."""
        if not recheck_access(
            self.db,
            requester_user_id=self.requester_user_id,
            requester_role=self.requester_role,
            patient_id=self.patient_id,
        ):
            raise AskBragiAccessDenied("Access to this patient's record is no longer authorized.")

    def register_evidence(self, source_evidence_id: int | None) -> None:
        if source_evidence_id is not None:
            self.authorized_evidence_ids.add(source_evidence_id)

    def register_document(self, document_id: int | None) -> None:
        if document_id is not None:
            self.authorized_document_ids.add(document_id)


def resolve_patient_id_for_new_conversation(
    db: Session,
    *,
    current_user,
    requested_patient_id: int | None,
) -> int:
    """Used ONLY at conversation-creation time (POST /ask-bragi/conversations)
    — never inside the tool loop. A patient never supplies a patient_id
    (their own is always resolved server-side); a doctor must supply one,
    validated against a real active DoctorPatientAccess grant, exactly
    like every other doctor-facing patient route in this app. Raises
    AskBragiAccessDenied on any failure."""
    if current_user.role == "patient":
        patient = (
            db.query(models.Patient)
            .filter(models.Patient.linked_user_id == current_user.id)
            .first()
        )
        if not patient:
            raise AskBragiAccessDenied("Patient profile not found.")
        return patient.id

    if current_user.role == "doctor":
        # Deliberately doctor-only for V1 — admin/care_partner/
        # emergency_worker are not enabled (see BRAGI_ASK_BRAGI_PLAN.md's
        # "Supported roles" section: narrow initial access, no documented
        # product requirement yet justifies broader rollout). PCP is the
        # same `doctor` role with `doctor_type == "pcp"` (see
        # docs/security/AUTHORIZATION_MATRIX.md) — already covered here,
        # no separate branch needed.
        if not requested_patient_id:
            raise AskBragiAccessDenied("A patient_id is required for this role.")
        if not recheck_access(
            db,
            requester_user_id=current_user.id,
            requester_role=current_user.role,
            patient_id=requested_patient_id,
        ):
            raise AskBragiAccessDenied("Not authorized for this patient.")
        patient = db.query(models.Patient).filter(models.Patient.id == requested_patient_id).first()
        if not patient:
            raise AskBragiAccessDenied("Patient not found.")
        return patient.id

    raise AskBragiAccessDenied("This role is not supported by Ask Bragi.")


def resolve_document_scope(db: Session, *, patient_id: int, document_id: int) -> int:
    """Validates a document belongs to the patient a conversation is
    scoped to, at conversation-creation time. Raises AskBragiAccessDenied
    otherwise (never silently falls back to patient_record scope for an
    unauthorized document — see BRAGI_ASK_BRAGI_PLAN.md's scope-model
    section)."""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document or document.patient_id != patient_id:
        raise AskBragiAccessDenied("Document not found for this patient.")
    return document.id
