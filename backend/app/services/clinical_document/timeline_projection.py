"""Canonical Timeline projection — Clinical Document Intelligence V3,
Phase 10.

`PatientEvent` (the existing, sole persisted Timeline architecture —
see models.py) is a PROJECTION target here, never a second source of
truth: every field this module writes is read straight from an already-
canonical `PatientMedication` row (Phase 7), never copied clinical
judgement, never a re-parse of source text. Reprocessing the same
document is idempotent — a `PatientMedication` row projects to at most
one `PatientEvent` PER event kind, looked up by
`(patient_id, source_medication_id, event_type)`, never by `created_at`.

**Deliberate scope decision — why this module does NOT project a
top-level Timeline event for a clinical document or a derived lab
artifact** (the "does the Timeline need a new event TYPE for a derived
lab artifact, or does it read the existing rows directly" question the
Phase 9 handoff left open): it already does, today, with zero new code.
`frontend/app/my-records/timeline/page.tsx` and `frontend/app/patients/
[id]/timeline/page.tsx` already fuse every `Document` row (via
`GET /my/profile`'s `sections`, which already includes a derived lab
artifact — Phase 9) into the rendered Timeline client-side
(`buildTimelineItems`), grouped under whichever admission/discharge
document or `PatientEvent` its own clinical date falls inside. Adding a
SECOND, backend-projected `PatientEvent` for the same document would
duplicate it on the Timeline (two cards for one document) unless the
existing client-side fusion were also taught to suppress its own
document-based card for a projected one — a redesign of that existing,
working mechanism, which the Phase 10 contract explicitly says not to
do ("do not rebuild Timeline from scratch unless the current
architecture genuinely requires it"). Phase 10's only genuine gap is
medications: a `PatientMedication` row has ZERO existing Timeline
representation (no `Document` row of its own, nothing already surfaces
it) — that is what this module actually projects.

**Two independent moments per medication row**: a single
`PatientMedication` row can carry BOTH a `start_date` and a `stop_date`
(e.g. a 14-day course documented in one mention — the fixture's own
Amoxicilina case), and both are independently Timeline-worthy: "started
on X" and "completed/stopped on Y" are two distinct real-world moments,
so this module can project up to TWO `PatientEvent` rows from one
`PatientMedication` row — never a THIRD; there is no dose-change or
prescription event kind (see below).

**Deliberate scope decision — dose-change and prescription-issued
events are NOT implemented here**: a reliable dose-change requires
comparing two same-drug rows with a trustworthy chronology, which is
exactly the shape of case `medication_persistence.py`'s own
`_detect_conflicts` already treats with suspicion (two same-drug rows,
no explaining date) — building a "confident" dose-change detector on
top of that would risk manufacturing a false state transition from
what may genuinely be an unresolvable conflict, the one thing the V3
contract's Timeline principles are most explicit about never doing.
Prescription-issued has no real data to project from at all yet:
`PrescriptionRow.medication_id` (schema.py) is never populated by any
parser (confirmed in the Phase 8/9 handoff sections) — there is no
document today that distinguishes "a prescription was issued" from
"a medication mention" as a separate canonical fact. Both are honestly
left for a future increment, not silently faked.

**Deliberate scope decision — a single "medication_stopped" event kind
covers both an explicit early discontinuation and a naturally-completed
course**: Phase 7's own `_STATUS_CONTEXT_TO_STATUS` mapping already
collapses "stopped"/"completed"/"historical" into the same `status`
value ("no parallel status vocabulary" — medication_persistence.py's
own explicit rule), and a naturally-completed course (`status` stays
"active", only `stop_date` is set) is told apart from an explicit
"stopped" mention only by the SAME `status` field this module already
reads. Phase 10 cannot invent a distinction Phase 7 itself declined to
keep — the projected event's `description` still always marks a
DERIVED completion date as calculated, never provider-authored (see
`_medication_description`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models

MEDICATION_STARTED_EVENT_TYPE = "medication_started"
MEDICATION_STOPPED_EVENT_TYPE = "medication_stopped"
_PROJECTED_EVENT_TYPES = (MEDICATION_STARTED_EVENT_TYPE, MEDICATION_STOPPED_EVENT_TYPE)


@dataclass
class TimelineProjectionResult:
    created: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    retracted: list[int] = field(default_factory=list)


def _find_existing_projection(
    db: Session, *, patient_id: int, source_medication_id: int, event_type: str
) -> models.PatientEvent | None:
    """Idempotency lookup — a `PatientMedication` row projects to at
    most ONE `PatientEvent` per `event_type`, looked up by its own id,
    never by `created_at`. Reprocessing the same document does not
    duplicate this row's event(s)."""
    return (
        db.query(models.PatientEvent)
        .filter(
            models.PatientEvent.patient_id == patient_id,
            models.PatientEvent.source_medication_id == source_medication_id,
            models.PatientEvent.event_type == event_type,
        )
        .first()
    )


def _resolve_doctor_user_id(document: models.Document, medication: models.PatientMedication) -> int:
    """`PatientEvent.doctor_user_id` is NOT NULL (a manually-created
    event always has a real doctor/admin actor) — a projected event has
    no such actor, so this picks the closest honest attribution: the
    document's own uploader if known, else the medication's own
    `created_by_user_id` (never null, per its own column definition)."""
    return document.uploaded_by_user_id or medication.created_by_user_id


def _medication_description(medication: models.PatientMedication, *, event_type: str) -> str | None:
    if event_type == MEDICATION_STARTED_EVENT_TYPE:
        parts = [p for p in (medication.dose_strength, medication.frequency) if p]
        return " · ".join(parts) if parts else None

    # event_type == MEDICATION_STOPPED_EVENT_TYPE — a derived stop_date
    # must never read as if the source itself wrote it (models.py's own
    # stop_date_basis docstring); this is the SAME distinction
    # medication-list.tsx already renders for the canonical medication
    # list, reused verbatim here rather than reworded.
    if medication.stop_date_basis == "derived":
        return "Calculated from a documented course — not provider-stated."
    return None


@dataclass
class _UpsertOutcome:
    event_id: int | None = None
    was_new: bool = False
    was_retracted: bool = False


def _upsert_or_retract(
    db: Session,
    *,
    document: models.Document,
    medication: models.PatientMedication,
    event_type: str,
    event_date: str | None,
) -> _UpsertOutcome:
    """`event_date` of `None` (no reliable date — Phase 10D/10E's own
    "never invent a date" rule) retracts any previously-projected event
    of this kind instead of projecting one."""
    existing = _find_existing_projection(
        db, patient_id=document.patient_id, source_medication_id=medication.id, event_type=event_type
    )

    if not event_date:
        if existing is not None:
            db.delete(existing)
            return _UpsertOutcome(was_retracted=True)
        return _UpsertOutcome()

    title = medication.name
    description = _medication_description(medication, event_type=event_type)

    if existing is not None:
        existing.title = title
        existing.description = description
        existing.admitted_at = event_date
        db.add(existing)
        return _UpsertOutcome(event_id=existing.id, was_new=False)

    projected = models.PatientEvent(
        patient_id=document.patient_id,
        doctor_user_id=_resolve_doctor_user_id(document, medication),
        event_type=event_type,
        status="active",
        title=title,
        description=description,
        admitted_at=event_date,
        created_by_user_id=medication.created_by_user_id,
        source_document_id=document.id,
        source_medication_id=medication.id,
    )
    db.add(projected)
    db.flush()
    return _UpsertOutcome(event_id=projected.id, was_new=True)


def _project_medication_events(
    db: Session, *, document: models.Document, medication: models.PatientMedication
) -> tuple[list[int], list[int], bool]:
    """Returns `(created_ids, updated_ids, was_retracted)` for this one
    medication row. Retracts (deletes) any previously-projected event
    if the medication has since become uncertain/conflicting, or if a
    date it was projected from is no longer present — see the module
    docstring's conflict-safety note; never leaves a stale, falsely
    confident Timeline card in place."""
    created: list[int] = []
    updated: list[int] = []
    retracted = False

    # Conflict safety (V3 contract, Phase 10G): a conflicting/uncertain
    # medication row NEVER projects a definitive state-change event —
    # canonical medication conflict UI (the medication list itself)
    # remains the authoritative place this is surfaced.
    event_dates = {
        MEDICATION_STARTED_EVENT_TYPE: None if medication.is_uncertain else medication.start_date,
        # Continuation suppression (V3 contract, Phase 10E): a "continue
        # X" mention resolves to the SAME status ("active") as a genuine
        # new start, with no other reliable signal preserved by Phase 7's
        # own persistence — except that a genuine start is the only case
        # that ever receives a real start_date (medication_persistence.py's
        # own start-date priority never applies to a mere continuation).
        # No start_date -> no event, never an invented one.
        #
        # Same conservative rule as a lab report with no reliable date
        # (Phase 10D) for the stop side: never invent a stop date. A row
        # with no explicit/derived stop_date stays un-projected for that
        # event kind.
        MEDICATION_STOPPED_EVENT_TYPE: None if medication.is_uncertain else medication.stop_date,
    }

    for event_type, event_date in event_dates.items():
        outcome = _upsert_or_retract(
            db, document=document, medication=medication, event_type=event_type, event_date=event_date
        )
        if outcome.event_id is not None:
            (created if outcome.was_new else updated).append(outcome.event_id)
        if outcome.was_retracted:
            retracted = True

    return created, updated, retracted


def project_clinical_document_to_timeline(db: Session, document: models.Document) -> TimelineProjectionResult:
    """The one Phase 10 entry point a future live-ingestion write path
    can invoke without knowing each individual projection rule — see
    module docstring for exactly what it does and, deliberately, does
    not project. Never commits — same transaction convention as
    `lab_persistence.persist_lab_candidates`/`medication_persistence.
    persist_medication_candidates`: the caller commits once, so a
    partial failure never leaves half-projected state committed.
    """
    result = TimelineProjectionResult()

    medications = (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.source_document_id == document.id)
        .order_by(models.PatientMedication.id.asc())
        .all()
    )

    for medication in medications:
        created, updated, retracted = _project_medication_events(db, document=document, medication=medication)
        result.created.extend(created)
        result.updated.extend(updated)
        if retracted:
            result.retracted.append(medication.id)

    return result
