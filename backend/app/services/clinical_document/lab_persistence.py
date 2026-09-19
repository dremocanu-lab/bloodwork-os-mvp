"""Embedded-lab canonical persistence — Clinical Document Intelligence
V3, Phase 6.

The ONE service responsible for turning validated `LabCandidate`s
(lab_extraction.py), grouped into coherent reports (lab_grouping.py),
into real `LabResult` + `SourceEvidence` rows — feeding the EXISTING
`resolve_analyte()` canonical resolver, never a private alias
dictionary, and never a second lab datastore. See the V3 contract's own
Phase 6 hard constraint and `docs/handoffs/
CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`.

Ownership rule (Phase 6 requirement 8 — "attach to the correct patient;
attach to the authoritative parent source document"): every persisted
`LabResult`/`SourceEvidence` row's `document_id` is the ORIGINAL
discharge `Document` — the discharge stays the authoritative source of
the fact. A separate, real "derived lab artifact" `Document` row is
ALSO created (one per coherent `LabReportGroup`, never one per analyte,
never one for the whole discharge when multiple genuinely distinct
reports exist) — it is a POINTER-ONLY record (see
`_build_derived_document_note_body`), never a second copy of lab values,
linked to its parent via the existing `parent_document_id` relation plus
the new `derived_artifact_kind` marker (see models.py).

Idempotency (Phase 6 requirement 12): reprocessing the SAME discharge
document must not duplicate LabResult/derived-artifact/SourceEvidence
rows. This module never uses `created_at` for that — every insert is
preceded by an exact-match lookup keyed on the same deterministic
identity fields a real reprocessing run would reproduce byte-for-byte
(document_id, source_segment_id, raw_test_name, raw_value,
observation_date, source_section_status) — see `_find_existing_lab_
result` and `_find_existing_derived_document`.

This module is the ONLY place in the `clinical_document` package that
touches the database — `lab_extraction.py`/`lab_grouping.py` stay pure,
matching this package's existing convention (segments.py/events.py/
dates.py are likewise pure).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models
from app.core.utils import generate_public_id, now_iso
from app.services import lab_resolver
from app.services.document_taxonomy import DocumentType, legacy_section_for

from .dates import parse_date_token
from .lab_extraction import LabCandidate
from .lab_grouping import LabReportGroup, group_lab_candidates
from .schema import DerivedArtifactRef

DERIVED_ARTIFACT_KIND_LAB_REPORT = "lab_report"


@dataclass
class PersistedLabObservation:
    lab_result_id: int
    canonical_name: str | None
    raw_test_name: str
    was_new: bool
    conflict: bool = False


@dataclass
class PersistedLabReportGroup:
    group_key: str
    derived_document_id: int
    derived_document_was_new: bool
    source_section_id: str | None
    lab_result_ids: list[int] = field(default_factory=list)


@dataclass
class LabPersistenceResult:
    groups: list[PersistedLabReportGroup] = field(default_factory=list)
    observations: list[PersistedLabObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def derived_artifact_refs(self) -> list[DerivedArtifactRef]:
        return [
            DerivedArtifactRef(
                artifact_type="lab_report",
                document_id=group.derived_document_id,
                source_section_id=group.source_section_id,
                lab_result_ids=list(group.lab_result_ids),
                group_key=group.group_key,
            )
            for group in self.groups
        ]


def _flag_from_range(parsed_value: float | None, reference_range: str | None) -> str | None:
    """Stage 3 of the flag-precedence chain — a deterministic numeric
    comparison against a trustworthy `reference_range`, ONLY reached when
    no explicit provider flag/section placement exists. Returns None
    (not "normal") on anything ambiguous — an absent/unparseable range or
    value is not evidence of anything, and is never presented as if it
    were a confirmed "normal" reading."""
    if parsed_value is None or not reference_range:
        return None
    parts = reference_range.replace(",", ".").split("-")
    if len(parts) != 2:
        return None
    try:
        low = float(parts[0].strip())
        high = float(parts[1].strip())
    except ValueError:
        return None
    if low > high:
        return None
    if parsed_value < low:
        return "L"
    if parsed_value > high:
        return "H"
    return None


def derive_lab_flag(candidate: LabCandidate) -> str | None:
    """Deterministic priority, per the V3 contract's Phase 6 rule:
    (1) an explicit provider/source abnormal flag literally printed next
        to the value;
    (2) explicit placement under a source "pathological"/"normal"
        subsection heading;
    (3) a deterministic numeric comparison against a trustworthy
        reference range;
    (4) otherwise unknown — never fabricated.
    Bragi's own numeric-range calculation NEVER overrides an explicit
    provider status, even when they'd disagree — both are preserved
    (the source flag lands in LabResult.flag; the numeric-derived one
    only fills the gap when the source gave no signal at all)."""
    if candidate.source_flag:
        return candidate.source_flag
    if candidate.source_section_status == "pathological":
        return "abnormal"
    if candidate.source_section_status == "normal":
        return "normal"
    return _flag_from_range(candidate.parsed_value, candidate.reference_range)


def _normalized_observation_datetime(candidate: LabCandidate) -> str | None:
    if not candidate.observation_date:
        return None
    parsed = parse_date_token(candidate.observation_date)
    if parsed is None or not parsed.normalized_date:
        return None
    return parsed.normalized_date


def _find_existing_lab_result(
    db: Session,
    *,
    document_id: int,
    candidate: LabCandidate,
    observation_datetime: str | None,
) -> models.LabResult | None:
    """Idempotency lookup: the deterministic identity of one embedded
    lab observation is (document, originating segment, raw test name,
    raw value, observation date, section status) — NOT created_at. A
    genuine source conflict (same analyte/date, different VALUE) is
    intentionally excluded from this match by including raw_value in the
    key, so two distinct source observations both persist (see
    `test_conflicting_same_analyte_rows_are_both_preserved`), while a
    byte-identical reprocessing pass matches and is skipped."""
    return (
        db.query(models.LabResult)
        .filter(
            models.LabResult.document_id == document_id,
            models.LabResult.raw_test_name == candidate.raw_test_name,
            models.LabResult.value == candidate.raw_value,
            models.LabResult.observation_datetime == observation_datetime,
            models.LabResult.source_section == (candidate.source_segment_id or None),
        )
        .first()
    )


def _upgrade_lab_evidence_bbox(db: Session, *, lab_result_id: int, candidate: LabCandidate) -> None:
    """Source Geometry + Clinical Table Intelligence V3 evidence-upgrade
    semantics (Part 44): a reprocessing pass that now has real table
    geometry for an ALREADY-persisted `LabResult` (idempotency matched it
    above) upgrades that SAME `SourceEvidence` row's bbox fields in
    place, rather than leaving it stuck at whatever precision the first
    pass achieved. Never regresses an already-geometry-bearing row (only
    fills fields that are currently null), and does nothing when this
    candidate has no real geometry of its own."""
    if candidate.primary_bbox is None:
        return
    evidence = (
        db.query(models.SourceEvidence)
        .filter(models.SourceEvidence.lab_result_id == lab_result_id)
        .order_by(models.SourceEvidence.id.asc())
        .first()
    )
    if evidence is None or evidence.bbox_x is not None:
        return
    evidence.bbox_x = candidate.primary_bbox.get("x")
    evidence.bbox_y = candidate.primary_bbox.get("y")
    evidence.bbox_width = candidate.primary_bbox.get("width")
    evidence.bbox_height = candidate.primary_bbox.get("height")
    if candidate.row_bbox:
        evidence.row_bbox_x = candidate.row_bbox.get("x")
        evidence.row_bbox_y = candidate.row_bbox.get("y")
        evidence.row_bbox_width = candidate.row_bbox.get("width")
        evidence.row_bbox_height = candidate.row_bbox.get("height")
    if candidate.field_bboxes:
        evidence.field_bboxes_json = json.dumps(candidate.field_bboxes)


def _find_existing_derived_document(db: Session, *, parent_document_id: int, group_key: str) -> models.Document | None:
    candidates = (
        db.query(models.Document)
        .filter(
            models.Document.parent_document_id == parent_document_id,
            models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
        )
        .all()
    )
    for candidate in candidates:
        if candidate.report_type == f"derived-lab-report:{group_key}":
            return candidate
    return None


def _build_derived_document_note_body(
    *, group_key: str, source_section_id: str | None, lab_result_ids: list[int]
) -> str:
    """Pointer-only payload — NEVER a copy of lab VALUES (the "no second
    lab datastore" rule). `lab_result_ids` is a list of integer ids —
    exactly `DerivedArtifactRef.lab_result_ids`'s own already-declared
    pointer field (schema.py), never a copy of what those rows contain.
    This is what lets a later reader (Phase 9) resolve "which canonical
    LabResult rows does this artifact represent" via a direct id lookup,
    rather than re-deriving group membership from scratch (request_code/
    date/panel are not stored as their own LabResult columns, so without
    this the only other option would be re-running extraction — a much
    heavier and less honest path). Always rewritten (idempotently, same
    inputs -> same output) each time this group is processed, never
    hand-edited elsewhere."""
    return json.dumps(
        {
            "document_type": "derived_lab_report",
            "artifact_type": DERIVED_ARTIFACT_KIND_LAB_REPORT,
            "group_key": group_key,
            "source_section_id": source_section_id,
            "lab_result_ids": sorted(lab_result_ids),
        },
        ensure_ascii=False,
    )


def _get_or_create_derived_document(
    db: Session,
    *,
    parent_document: models.Document,
    group: LabReportGroup,
    source_section_id: str | None,
) -> tuple[models.Document, bool]:
    existing = _find_existing_derived_document(db, parent_document_id=parent_document.id, group_key=group.group_key)
    if existing is not None:
        return existing, False

    derived = models.Document(
        patient_id=parent_document.patient_id,
        uploaded_by_user_id=parent_document.uploaded_by_user_id,
        parent_document_id=parent_document.id,
        derived_artifact_kind=DERIVED_ARTIFACT_KIND_LAB_REPORT,
        section=legacy_section_for(DocumentType.LABORATORY_RESULTS),
        document_type=DocumentType.LABORATORY_RESULTS.value,
        classification_status="classified",
        classification_source="clinical_document_v3_phase6",
        filename=parent_document.filename,
        report_name=f"Structured laboratory results extracted from {parent_document.report_name or parent_document.filename}",
        report_type=f"derived-lab-report:{group.group_key}",
        note_body=_build_derived_document_note_body(
            group_key=group.group_key, source_section_id=source_section_id, lab_result_ids=[]
        ),
        patient_name=parent_document.patient_name,
        date_of_birth=parent_document.date_of_birth,
        test_date=group.observation_date,
        is_verified=False,
        created_at=now_iso(),
        public_id=generate_public_id("brg-doc"),
    )
    db.add(derived)
    db.flush()
    return derived, True


def persist_lab_candidates(
    db: Session,
    *,
    document: models.Document,
    candidates: list[LabCandidate],
    source_section_id: str | None = None,
) -> LabPersistenceResult:
    """Canonicalizes and persists a document's embedded lab candidates.
    `document` is the AUTHORITATIVE parent (the discharge document
    itself) — every `LabResult`/`SourceEvidence` row is attached to it,
    never to the derived artifact. Deterministic and idempotent: calling
    this twice with the same `candidates` for the same `document`
    produces the same rows, not duplicates (see `_find_existing_lab_
    result`/`_find_existing_derived_document`)."""
    result = LabPersistenceResult()
    if not candidates:
        return result

    groups = group_lab_candidates(candidates)

    # Conflict detection: within a group, two candidates naming the SAME
    # analyte (by raw_test_name — the canonical name isn't known until
    # resolve_analyte runs below, but two candidates sharing a raw name
    # is already sufficient evidence they're describing the same source
    # concept) with DIFFERENT raw_value are a genuine source conflict —
    # both are persisted, neither is preferred, and both are flagged.
    for group in groups:
        seen_raw_values_by_name: dict[str, set[str]] = {}
        for candidate in group.candidates:
            key = candidate.raw_test_name.strip().lower()
            seen_raw_values_by_name.setdefault(key, set()).add(candidate.raw_value)
        conflicting_names = {name for name, values in seen_raw_values_by_name.items() if len(values) > 1}

        derived_document, was_new = _get_or_create_derived_document(
            db, parent_document=document, group=group, source_section_id=source_section_id
        )
        persisted_group = PersistedLabReportGroup(
            group_key=group.group_key,
            derived_document_id=derived_document.id,
            derived_document_was_new=was_new,
            source_section_id=source_section_id,
        )

        for candidate in group.candidates:
            observation_datetime = _normalized_observation_datetime(candidate)
            is_conflict = candidate.raw_test_name.strip().lower() in conflicting_names

            existing = _find_existing_lab_result(
                db, document_id=document.id, candidate=candidate, observation_datetime=observation_datetime
            )
            if existing is not None:
                _upgrade_lab_evidence_bbox(db, lab_result_id=existing.id, candidate=candidate)
                persisted_group.lab_result_ids.append(existing.id)
                result.observations.append(
                    PersistedLabObservation(
                        lab_result_id=existing.id,
                        canonical_name=existing.canonical_name,
                        raw_test_name=existing.raw_test_name,
                        was_new=False,
                        conflict=is_conflict,
                    )
                )
                continue

            resolved = lab_resolver.resolve_analyte(
                candidate.raw_test_name,
                unit=candidate.raw_unit,
                institution=None,
            )

            lab_result = models.LabResult(
                document_id=document.id,
                raw_test_name=candidate.raw_test_name,
                canonical_name=resolved.canonical_name,
                display_name=resolved.display_name,
                category=resolved.category,
                # Reuses the existing free-text `source_section` column as
                # this observation's originating SourceSegment id — the
                # exact provenance anchor Phase 4 already established,
                # never a fabricated section label. (Distinct from
                # `source_section_id`, the canonical ClinicalSection id,
                # which lives on the derived-artifact linkage instead.)
                source_section=candidate.source_segment_id,
                value=candidate.raw_value,
                flag=derive_lab_flag(candidate),
                reference_range=candidate.reference_range,
                unit=candidate.normalized_unit or candidate.raw_unit,
                observation_datetime=observation_datetime,
                extraction_confidence=candidate.confidence,
                normalization_confidence=resolved.normalization_confidence,
                normalization_method=resolved.normalization_method,
                verification_state="conflict" if is_conflict else "unverified",
            )
            db.add(lab_result)
            db.flush()

            db.add(
                models.SourceEvidence(
                    document_id=document.id,
                    lab_result_id=lab_result.id,
                    source_text=candidate.source_evidence_text,
                    source_block_id=candidate.source_segment_id,
                    # Real page number when the originating SourceSegment
                    # genuinely carries one (see LabCandidate.source_page)
                    # — never fabricated otherwise. `row_bbox`/
                    # `field_bboxes` (Source Geometry + Clinical Table
                    # Intelligence V3) are likewise real, verbatim
                    # `TableGeometry` cell geometry when the candidate came
                    # from an extracted table row (see
                    # lab_extraction.py::_extract_from_table); both stay
                    # null for a prose-line candidate, exactly as before
                    # geometry existed.
                    page_number=candidate.source_page,
                    bbox_x=candidate.primary_bbox.get("x") if candidate.primary_bbox else None,
                    bbox_y=candidate.primary_bbox.get("y") if candidate.primary_bbox else None,
                    bbox_width=candidate.primary_bbox.get("width") if candidate.primary_bbox else None,
                    bbox_height=candidate.primary_bbox.get("height") if candidate.primary_bbox else None,
                    row_bbox_x=candidate.row_bbox.get("x") if candidate.row_bbox else None,
                    row_bbox_y=candidate.row_bbox.get("y") if candidate.row_bbox else None,
                    row_bbox_width=candidate.row_bbox.get("width") if candidate.row_bbox else None,
                    row_bbox_height=candidate.row_bbox.get("height") if candidate.row_bbox else None,
                    field_bboxes_json=json.dumps(candidate.field_bboxes) if candidate.field_bboxes else None,
                    extraction_confidence=candidate.confidence,
                    provider="clinical_document_v3_phase6",
                    parser_version="clinical-document-v3-lab-extraction-v1",
                    created_at=now_iso(),
                )
            )

            persisted_group.lab_result_ids.append(lab_result.id)
            result.observations.append(
                PersistedLabObservation(
                    lab_result_id=lab_result.id,
                    canonical_name=lab_result.canonical_name,
                    raw_test_name=lab_result.raw_test_name,
                    was_new=True,
                    conflict=is_conflict,
                )
            )
            if is_conflict:
                result.warnings.append(
                    f"Conflicting source values for '{candidate.raw_test_name}' in group '{group.group_key}': "
                    f"both preserved, neither treated as authoritative — requires review."
                )

        # Rewrite the derived artifact's pointer payload with the now-
        # complete lab_result_ids for this group — deterministic (same
        # candidates -> same ids -> same JSON), so an idempotent re-run
        # is a no-op write, never a duplicate or a drift.
        derived_document.note_body = _build_derived_document_note_body(
            group_key=group.group_key,
            source_section_id=source_section_id,
            lab_result_ids=persisted_group.lab_result_ids,
        )
        db.add(derived_document)

        result.groups.append(persisted_group)

    return result
