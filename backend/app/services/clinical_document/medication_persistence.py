"""Canonical medication persistence — Clinical Document Intelligence V3,
Phase 7.

The ONE service responsible for turning validated `MedicationCandidate`s
(medication_extraction.py) into real `PatientMedication` rows — the
EXISTING canonical medication model/status vocabulary
(`VALID_MED_STATUSES` in `app/api/routers/medications.py`), never a
second medication datastore, never a parallel status vocabulary.

Start-date priority (exact, non-negotiable — see `_resolve_start_date`):
    1. an explicit start date in the source text;
    2. explicit "start today"/equivalent tied to a reliable discharge
       date;
    3. a discharge recommendation that clearly indicates the medication
       starts at discharge;
    4. a prescription issue date, ONLY when the source semantics clearly
       tie it to treatment start.
NEVER upload/ingestion/`created_at` — no code path in this module ever
reads those as a candidate start date in the first place.

End-date: derived ONLY when both a reliable start date AND an explicit
finite duration exist (`_resolve_stop_date`), via
`medication_duration.derive_end_date`. `stop_date_basis` distinguishes
"explicit" / "derived" / "explicit_with_derived_conflict" — the exact
mechanism that keeps a calculated date from ever reading as
provider-authored (see models.py's own field docstring).

Ownership rule: every `PatientMedication` row created here carries
`source_document_id`/`source_segment_id` (Phase 7's own additive
provenance columns), but is a REAL, independently meaningful medication
fact — not a pointer-only artifact like Phase 6's derived lab report.
Deleting the source document clears the provenance link
(`ondelete="SET NULL"`) rather than deleting the medication itself (see
DELETE /documents/{id}'s paired SourceEvidence cleanup this requires).

Idempotency: reprocessing the SAME document must not duplicate the same
source medication fact. Never `created_at` — an exact-match lookup on
(patient, source_document_id, source_segment_id, raw_medication_name,
raw_text) runs before every insert. Genuinely distinct candidates (a
different segment, a different raw_text, e.g. a later "stopped" mention
of the same drug) are NEVER collapsed into one row — see
`test_genuinely_separate_source_medication_events_do_not_over_
deduplicate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models
from app.api.routers.medications import VALID_MED_STATUSES
from app.core.utils import now_iso
from app.services.lab_catalog import normalize_text

from . import medication_duration
from .dates import parse_date_token
from .medication_extraction import MedicationCandidate

# status_context -> VALID_MED_STATUSES. PRN (candidate.prn) overrides
# this mapping entirely to "as_needed" — see _resolve_status. "completed"
# and "historical" both map to "stopped": the existing vocabulary has no
# dedicated bucket for either, and inventing one would violate the "no
# parallel status vocabulary" rule — the distinction survives instead in
# `extra_info` (human-readable) and is never lost.
_STATUS_CONTEXT_TO_STATUS: dict[str, str] = {
    "started": "active",
    "continued": "active",
    "stopped": "stopped",
    "paused": "paused",
    "completed": "stopped",
    "prescribed": "active",
    "historical": "stopped",
    "uncertain": "active",
}
assert set(_STATUS_CONTEXT_TO_STATUS.values()) <= VALID_MED_STATUSES

# status_context values that can never be confidently asserted as "the
# patient is definitely on this medication" — is_uncertain is always set
# for these, regardless of any other signal.
_INHERENTLY_UNCERTAIN_CONTEXTS = {"uncertain", "prescribed"}

# Start-date tier 3 ("a discharge recommendation that clearly indicates
# medication starts at discharge") only applies to a mention that is
# ITSELF being newly introduced — never to "continued" (already ongoing
# before this document) or any status this module can't assert a genuine
# start for.
_TIER3_ELIGIBLE_STATUS_CONTEXTS = {"started", "prescribed"}


@dataclass
class PersistedMedicationObservation:
    medication_id: int
    raw_medication_name: str
    status: str
    was_new: bool
    conflict: bool = False


@dataclass
class MedicationPersistenceResult:
    observations: list[PersistedMedicationObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _resolve_start_date(
    candidate: MedicationCandidate, *, discharge_date: str | None
) -> tuple[str | None, str | None]:
    """Returns `(start_date_iso, basis)`. Never falls back to any kind of
    processing/ingestion timestamp — see this module's own docstring."""
    if candidate.explicit_start_date:
        parsed = parse_date_token(candidate.explicit_start_date)
        if parsed and parsed.normalized_date:
            return parsed.normalized_date, "explicit"

    if candidate.starts_at_discharge_or_encounter and discharge_date:
        parsed = parse_date_token(discharge_date)
        if parsed and parsed.normalized_date:
            return parsed.normalized_date, "start_today_at_encounter"

    if (
        candidate.canonical_key == "discharge_medications"
        and candidate.status_context in _TIER3_ELIGIBLE_STATUS_CONTEXTS
        and discharge_date
    ):
        parsed = parse_date_token(discharge_date)
        if parsed and parsed.normalized_date:
            return parsed.normalized_date, "discharge_recommendation"

    if candidate.prescription_date and candidate.starts_at_discharge_or_encounter:
        parsed = parse_date_token(candidate.prescription_date)
        if parsed and parsed.normalized_date:
            return parsed.normalized_date, "prescription_issue_date"

    return None, None


def _resolve_stop_date(candidate: MedicationCandidate, *, start_date_iso: str | None) -> tuple[str | None, str | None, list[str]]:
    """Returns `(stop_date_iso, stop_date_basis, warnings)`. Derivation
    is skipped entirely (stays None) for PRN, scheme/intermittent,
    indefinite, or an unclear taper — see the V3 contract's exact
    exclusion list; `medication_duration`'s own marker functions are
    what `medication_extraction.py` already used to set these flags on
    the candidate, reused here rather than re-checked independently."""
    warnings: list[str] = []

    explicit_stop_iso = None
    if candidate.explicit_end_date:
        parsed = parse_date_token(candidate.explicit_end_date)
        if parsed and parsed.normalized_date:
            explicit_stop_iso = parsed.normalized_date

    derived_stop_iso = None
    can_derive = (
        start_date_iso is not None
        and candidate.parsed_duration is not None
        and not candidate.prn
        and not candidate.scheme_or_intermittent
        and not candidate.indefinite
        and not candidate.taper_without_clear_duration
    )
    if can_derive:
        derived_stop_iso = medication_duration.derive_end_date(start_date_iso, candidate.parsed_duration)

    if explicit_stop_iso and derived_stop_iso and explicit_stop_iso != derived_stop_iso:
        warnings.append(
            f"Explicit end date {explicit_stop_iso} conflicts with a documented "
            f"{candidate.raw_duration} course from {start_date_iso} (would compute {derived_stop_iso}) "
            "— explicit source value preserved, conflict flagged, never silently resolved."
        )
        return explicit_stop_iso, "explicit_with_derived_conflict", warnings

    if explicit_stop_iso:
        return explicit_stop_iso, "explicit", warnings

    if derived_stop_iso:
        return derived_stop_iso, "derived", warnings

    return None, None, warnings


def _resolve_status(candidate: MedicationCandidate) -> tuple[str, bool]:
    """Returns `(status, is_uncertain)`. PRN overrides the
    status_context mapping entirely — "as_needed" is exactly what that
    existing status value means."""
    if candidate.prn:
        return "as_needed", candidate.status_context in _INHERENTLY_UNCERTAIN_CONTEXTS
    status = _STATUS_CONTEXT_TO_STATUS[candidate.status_context]
    is_uncertain = candidate.status_context in _INHERENTLY_UNCERTAIN_CONTEXTS
    return status, is_uncertain


def _build_extra_info(candidate: MedicationCandidate, *, stop_basis: str | None) -> str | None:
    """Human-readable notes preserving nuance the closed status/date
    vocabulary can't itself carry — e.g. distinguishing "completed" from
    a plain "stopped", or explaining a derived end date so it never
    reads as provider-authored (see models.py's stop_date_basis
    docstring)."""
    parts: list[str] = []
    if candidate.status_context == "completed":
        parts.append("Source indicates this course was completed as planned (not an early discontinuation).")
    if candidate.status_context == "historical":
        parts.append("Source describes this as a past/historical medication, not a current one.")
    if candidate.status_context == "prescribed":
        parts.append("A prescription was documented; the source does not confirm administration actually started.")
    if candidate.status_context == "uncertain":
        parts.append("Medication context in the source text was not clearly classifiable — requires review.")
    if candidate.indefinite:
        parts.append("Source indicates an indefinite/ongoing/chronic course with no stated end.")
    if candidate.taper_without_clear_duration:
        parts.append("Source describes a taper with no clearly computable total duration.")
    if candidate.scheme_or_intermittent:
        parts.append(f"Source describes an intermittent/scheme-based regimen ('{candidate.raw_text}') — no end date derived.")
    # The documented duration itself is always preserved (Phase 7M's own
    # "preserve duration" requirement) — PatientMedication has no
    # dedicated duration column, so this is the one place it survives
    # when a reliable start date wasn't available to actually derive
    # stop_date from it (stop_basis stays None in that case, but the
    # documented duration fact must not silently disappear).
    if candidate.raw_duration:
        if stop_basis == "derived":
            parts.append(f"stop_date calculated from a documented {candidate.raw_duration} course — not provider-stated.")
        else:
            parts.append(f"Source documents a {candidate.raw_duration} course; no reliable start date to compute stop_date from.")
    if candidate.instructions:
        parts.append(candidate.instructions)
    return " ".join(parts) if parts else None


def _find_existing_medication(
    db: Session, *, patient_id: int, source_document_id: int, candidate: MedicationCandidate
) -> models.PatientMedication | None:
    """Idempotency lookup — exact match on the deterministic identity of
    ONE source medication mention. `raw_text` (the full verbatim source
    line/sentence) is part of the key specifically so a genuinely
    different mention of the same drug in the same segment (rare, but
    possible in a table with repeated rows) is never treated as the
    same fact as this one — never `created_at`."""
    return (
        db.query(models.PatientMedication)
        .filter(
            models.PatientMedication.patient_id == patient_id,
            models.PatientMedication.source_document_id == source_document_id,
            models.PatientMedication.source_segment_id == candidate.source_segment_id,
            models.PatientMedication.name == candidate.raw_medication_name,
            models.PatientMedication.reason == candidate.raw_text,
        )
        .first()
    )


def _detect_conflicts(candidates: list[MedicationCandidate]) -> set[int]:
    """Returns the set of `id(candidate)` for candidates involved in a
    genuine same-drug status conflict — two mentions of the same
    normalized drug name whose resolved statuses differ AND whose
    relative timing this module cannot establish (neither carries a
    start date that would explain a legitimate sequential transition,
    e.g. 'started' then, later, 'stopped'). A resolvable timeline is NOT
    a conflict — see the V3 contract's own BESREMI started/stopped
    example, which must remain two ordinary distinct rows, not a
    flagged conflict."""
    by_name: dict[str, list[MedicationCandidate]] = {}
    for candidate in candidates:
        key = normalize_text(candidate.raw_medication_name)
        by_name.setdefault(key, []).append(candidate)

    conflicting_ids: set[int] = set()
    for group in by_name.values():
        if len(group) < 2:
            continue
        statuses = {_resolve_status(c)[0] for c in group}
        if len(statuses) < 2:
            continue  # same drug, same resolved status — not a conflict
        has_explaining_date = any(c.explicit_start_date or c.starts_at_discharge_or_encounter for c in group)
        if has_explaining_date:
            continue  # a resolvable timeline — a legitimate transition, not a conflict
        conflicting_ids.update(id(c) for c in group)
    return conflicting_ids


def persist_medication_candidates(
    db: Session,
    *,
    document: models.Document,
    created_by_user_id: int,
    candidates: list[MedicationCandidate],
    admission_date: str | None = None,
    discharge_date: str | None = None,
) -> MedicationPersistenceResult:
    """Canonicalizes and persists a document's medication candidates
    into real `PatientMedication` rows, attached to `document.patient_id`
    via `source_document_id`/`source_segment_id`. Deterministic and
    idempotent: calling this twice with the same `candidates` for the
    same `document` produces the same rows, not duplicates."""
    result = MedicationPersistenceResult()
    if not candidates:
        return result

    conflicting_ids = _detect_conflicts(candidates)

    for candidate in candidates:
        existing = _find_existing_medication(
            db, patient_id=document.patient_id, source_document_id=document.id, candidate=candidate
        )
        is_conflict = id(candidate) in conflicting_ids

        if existing is not None:
            if is_conflict and not existing.is_uncertain:
                existing.is_uncertain = 1
            result.observations.append(
                PersistedMedicationObservation(
                    medication_id=existing.id,
                    raw_medication_name=existing.name,
                    status=existing.status,
                    was_new=False,
                    conflict=is_conflict,
                )
            )
            continue

        start_date_iso, _start_basis = _resolve_start_date(candidate, discharge_date=discharge_date)
        stop_date_iso, stop_basis, stop_warnings = _resolve_stop_date(candidate, start_date_iso=start_date_iso)
        status, is_uncertain_from_context = _resolve_status(candidate)
        is_uncertain = is_uncertain_from_context or is_conflict

        extra_info_parts = [_build_extra_info(candidate, stop_basis=stop_basis)]
        if is_conflict:
            other_statuses = sorted(
                {_resolve_status(c)[0] for c in candidates if normalize_text(c.raw_medication_name) == normalize_text(candidate.raw_medication_name)}
            )
            extra_info_parts.append(
                f"Conflicting status for '{candidate.raw_medication_name}' across sources in this document "
                f"({', '.join(other_statuses)}) — requires review; neither source was treated as authoritative."
            )
        extra_info = " ".join(p for p in extra_info_parts if p) or None

        medication = models.PatientMedication(
            patient_id=document.patient_id,
            created_by_user_id=created_by_user_id,
            name=candidate.raw_medication_name,
            dose_strength=candidate.dose_text,
            frequency=candidate.frequency,
            reason=candidate.raw_text,
            status=status,
            route_form=candidate.route,
            start_date=start_date_iso,
            stop_date=stop_date_iso,
            stop_date_basis=stop_basis,
            extra_info=extra_info,
            is_uncertain=1 if is_uncertain else 0,
            created_at=now_iso(),
            source_document_id=document.id,
            source_segment_id=candidate.source_segment_id,
        )
        db.add(medication)
        db.flush()

        if candidate.source_evidence_text:
            db.add(
                models.SourceEvidence(
                    document_id=document.id,
                    medication_id=medication.id,
                    source_text=candidate.source_evidence_text,
                    source_block_id=candidate.source_segment_id,
                    page_number=candidate.source_page,
                    extraction_confidence=candidate.confidence,
                    provider="clinical_document_v3_phase7",
                    parser_version="clinical-document-v3-medication-extraction-v1",
                    created_at=now_iso(),
                )
            )

        result.warnings.extend(stop_warnings)
        result.observations.append(
            PersistedMedicationObservation(
                medication_id=medication.id,
                raw_medication_name=medication.name,
                status=medication.status,
                was_new=True,
                conflict=is_conflict,
            )
        )

    return result
