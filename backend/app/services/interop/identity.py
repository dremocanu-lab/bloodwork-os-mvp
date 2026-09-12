"""Deterministic patient identity resolution (P31-P34). No fuzzy/name-based
linking anywhere in this module — a link exists only because an admin (or,
in a later phase, a verified PIXm/PDQm result) explicitly created it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app import models


@dataclass
class IdentityResolution:
    outcome: Literal["linked", "requires_review", "conflict"]
    patient_id: int | None
    identifier_system: str
    identifier_value: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def resolve_external_identity(
    db: Session,
    *,
    connection_id: int,
    identifier_system: str,
    identifier_value: str,
) -> IdentityResolution:
    """Look up whether (connection, system, value) is already linked to a
    verified Bragi patient. Never guesses; never picks "the closer match" —
    see P33."""
    link = (
        db.query(models.ExternalPatientIdentityLink)
        .filter(
            models.ExternalPatientIdentityLink.connection_id == connection_id,
            models.ExternalPatientIdentityLink.identifier_system == identifier_system,
            models.ExternalPatientIdentityLink.identifier_value == identifier_value,
            models.ExternalPatientIdentityLink.status == "verified",
        )
        .first()
    )
    if link:
        return IdentityResolution("linked", link.patient_id, identifier_system, identifier_value)

    return IdentityResolution("requires_review", None, identifier_system, identifier_value)


def record_identity_conflict(
    db: Session,
    *,
    connection_id: int,
    identifier_system: str,
    identifier_value: str,
    attempted_patient_id: int | None,
    existing_link_id: int | None,
) -> models.InteropIdentityConflict:
    conflict = models.InteropIdentityConflict(
        connection_id=connection_id,
        identifier_system=identifier_system,
        identifier_value=identifier_value,
        attempted_patient_id=attempted_patient_id,
        existing_link_id=existing_link_id,
        detected_at=_now_iso(),
        resolved=False,
    )
    db.add(conflict)
    db.flush()
    return conflict


def create_identity_link(
    db: Session,
    *,
    connection_id: int,
    patient_id: int,
    identifier_system: str,
    identifier_value: str,
    verified_by_user_id: int,
) -> models.ExternalPatientIdentityLink:
    """The ONLY way a link is created in Phase 1 — always an explicit admin
    action (verification_method="admin_manual"). Refuses (raises ValueError)
    if the identifier is already verified-linked to a DIFFERENT patient
    rather than silently overwriting it — the caller must resolve the
    conflict first."""
    existing = (
        db.query(models.ExternalPatientIdentityLink)
        .filter(
            models.ExternalPatientIdentityLink.connection_id == connection_id,
            models.ExternalPatientIdentityLink.identifier_system == identifier_system,
            models.ExternalPatientIdentityLink.identifier_value == identifier_value,
            models.ExternalPatientIdentityLink.status == "verified",
        )
        .first()
    )
    if existing and existing.patient_id != patient_id:
        record_identity_conflict(
            db,
            connection_id=connection_id,
            identifier_system=identifier_system,
            identifier_value=identifier_value,
            attempted_patient_id=patient_id,
            existing_link_id=existing.id,
        )
        raise ValueError(
            f"identifier {identifier_system}|{identifier_value} is already linked to a different patient "
            f"(patient_id={existing.patient_id}) — an IDENTITY CONFLICT was recorded for review, nothing was linked."
        )
    if existing and existing.patient_id == patient_id:
        return existing

    link = models.ExternalPatientIdentityLink(
        connection_id=connection_id,
        patient_id=patient_id,
        identifier_system=identifier_system,
        identifier_value=identifier_value,
        status="verified",
        verification_method="admin_manual",
        verified_at=_now_iso(),
        verified_by_user_id=verified_by_user_id,
        created_at=_now_iso(),
    )
    db.add(link)
    db.flush()
    return link
