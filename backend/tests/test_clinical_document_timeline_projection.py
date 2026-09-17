"""Focused tests for canonical Timeline projection — Clinical Document
Intelligence V3, Phase 10. Needs real DB connectivity (same skip-
gracefully convention as test_idor_regression.py/test_clinical_document_
lab_persistence.py/test_clinical_document_medication_persistence.py).

See app/services/clinical_document/timeline_projection.py's own module
docstring for the full architectural reasoning this file proves:
- ONLY medication start/stop moments are projected as new PatientEvent
  rows (documents/derived-lab-artifacts already appear on the Timeline
  via the existing frontend document/event fusion — no backend
  projection needed or wanted for those, see the docstring's "why not"
  section);
- conflict safety (an uncertain/conflicting medication never projects);
- continuation suppression (a "continue X" mention never projects a
  started event, since it never receives a start_date);
- idempotency (reprocessing never duplicates);
- manual PatientEvents are untouched;
- deletion semantics (SET NULL on the document link, CASCADE on the
  medication link — a deliberate divergence from a naive "always
  cascade" design, explained in models.py's own field docstring).
"""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not configured — this file needs real DB connectivity.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.clinical_document.medication_extraction import MedicationCandidate  # noqa: E402
from app.services.clinical_document.medication_persistence import (  # noqa: E402
    persist_medication_candidates,
)
from app.services.clinical_document.timeline_projection import (  # noqa: E402
    MEDICATION_STARTED_EVENT_TYPE,
    MEDICATION_STOPPED_EVENT_TYPE,
    project_clinical_document_to_timeline,
)

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-tl-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Clinical Doc Timeline Test {role}",
        "password": "TestPass123!",
        "role": role,
        **extra,
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def discharge_document():
    account = _signup("patient", cnp="6000101999992")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            uploaded_by_user_id=account["user"]["id"],
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-clindoc-tl-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    yield {
        "account": account,
        "patient_id": patient_id,
        "document_id": document_id,
        "created_by_user_id": account["user"]["id"],
    }

    client.delete("/my/account", headers=_auth(account["token"]))


def _resolve_duration(raw: str):
    from app.services.clinical_document.medication_duration import parse_duration

    return parse_duration(raw)


def _fixture_candidates() -> list[MedicationCandidate]:
    """Explicit, hand-built candidates rather than the real free-text
    extractor (`extract_medication_candidates_from_segment`) — Phase 10
    tests the PROJECTOR's behavior against already-resolved
    `PatientMedication` state, not Phase 7's own classifier accuracy on
    ambiguous phrasing (that is already covered by
    test_clinical_document_medication_extraction.py). Mirrors the exact
    pattern `backend/scripts/seed_e2e_discharge_document.py` already
    uses for the same reason."""
    return [
        MedicationCandidate(
            source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
            raw_text="Metoprolol 50mg 1-0-1, se continua tratamentul cu doza anterioara.",
            raw_medication_name="Metoprolol", status_context="continued",
            source_evidence_text="Metoprolol 50mg 1-0-1, se continua tratamentul cu doza anterioara.",
        ),
        MedicationCandidate(
            source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
            raw_text="Amoxicilina 500mg 1-1-1, 14 zile, incepand de azi.",
            raw_medication_name="Amoxicilina", status_context="started",
            starts_at_discharge_or_encounter=True, raw_duration="14 zile",
            parsed_duration=_resolve_duration("14 zile"),
            source_evidence_text="Amoxicilina 500mg 1-1-1, 14 zile, incepand de azi.",
        ),
        MedicationCandidate(
            source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
            raw_text="Ibuprofen 400mg la nevoie pentru durere.",
            raw_medication_name="Ibuprofen", status_context="continued", prn=True,
            source_evidence_text="Ibuprofen 400mg la nevoie pentru durere.",
        ),
        MedicationCandidate(
            source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
            raw_text="Metformin 850mg, oprit din data de 04.03.2026 din cauza efectelor adverse.",
            raw_medication_name="Metformin", status_context="stopped",
            explicit_end_date="04.03.2026",
            source_evidence_text="Metformin 850mg, oprit din data de 04.03.2026 din cauza efectelor adverse.",
        ),
    ]


def _persist_fixture(db, discharge_document, candidates=None, **kwargs):
    document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
    return persist_medication_candidates(
        db,
        document=document,
        created_by_user_id=discharge_document["created_by_user_id"],
        candidates=candidates if candidates is not None else _fixture_candidates(),
        discharge_date=kwargs.pop("discharge_date", "05.03.2026"),
        **kwargs,
    )


def _project(db, discharge_document):
    document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
    return project_clinical_document_to_timeline(db, document)


def _by_name(medications, name):
    return next(m for m in medications if m.name == name)


def _medications_for(db, discharge_document):
    return (
        db.query(models.PatientMedication)
        .filter(models.PatientMedication.source_document_id == discharge_document["document_id"])
        .all()
    )


def _events_for(db, discharge_document):
    return (
        db.query(models.PatientEvent)
        .filter(models.PatientEvent.patient_id == discharge_document["patient_id"])
        .all()
    )


# --- Documents/labs are never re-projected as PatientEvent rows -------------


def test_persisting_medications_never_creates_a_document_or_lab_level_event(discharge_document):
    """A discharge document and any derived lab artifact already appear
    on the Timeline via the existing frontend document/event fusion
    (see the module's own docstring) — Phase 10 must not duplicate them
    as a second, backend-projected PatientEvent."""
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        events = _events_for(db, discharge_document)
        assert all(e.event_type in (MEDICATION_STARTED_EVENT_TYPE, MEDICATION_STOPPED_EVENT_TYPE) for e in events)
    finally:
        db.close()


def test_reprocessing_the_same_document_does_not_duplicate_events(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()
        first_count = len(_events_for(db, discharge_document))

        # Reprocess: same candidates persisted again (idempotent per
        # Phase 7), then project again (idempotent per Phase 10).
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        assert len(_events_for(db, discharge_document)) == first_count
    finally:
        db.close()


# --- Medication started -------------------------------------------------------


def test_medication_with_explicit_start_date_projects_a_started_event(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        amox = _by_name(medications, "Amoxicilina")
        event = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == amox.id,
                models.PatientEvent.event_type == MEDICATION_STARTED_EVENT_TYPE,
            )
            .first()
        )
        assert event is not None
        assert event.title == "Amoxicilina"
        assert event.admitted_at == amox.start_date
        assert event.source_document_id == discharge_document["document_id"]
    finally:
        db.close()


def test_continued_medication_with_no_start_date_does_not_project_a_started_event(discharge_document):
    """Metoprolol is a plain 'continua tratamentul' mention with no
    date — this must never fabricate a started event, or every
    unrelated visit would create a duplicate 'Metoprolol started' card."""
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        metoprolol = _by_name(medications, "Metoprolol")
        assert metoprolol.start_date is None

        event = (
            db.query(models.PatientEvent)
            .filter(models.PatientEvent.source_medication_id == metoprolol.id)
            .first()
        )
        assert event is None
    finally:
        db.close()


def test_prn_medication_with_no_date_does_not_project_any_event(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        ibuprofen = _by_name(medications, "Ibuprofen")
        event = (
            db.query(models.PatientEvent)
            .filter(models.PatientEvent.source_medication_id == ibuprofen.id)
            .first()
        )
        assert event is None
    finally:
        db.close()


# --- Medication stopped / completed ------------------------------------------


def test_finite_duration_course_projects_both_started_and_completed_events(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        amox = _by_name(medications, "Amoxicilina")
        assert amox.stop_date_basis == "derived"

        started = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == amox.id,
                models.PatientEvent.event_type == MEDICATION_STARTED_EVENT_TYPE,
            )
            .first()
        )
        stopped = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == amox.id,
                models.PatientEvent.event_type == MEDICATION_STOPPED_EVENT_TYPE,
            )
            .first()
        )
        assert started is not None
        assert stopped is not None
        assert stopped.admitted_at == amox.stop_date
        # Never reads as provider-authored — the derived-date label
        # survives all the way into the Timeline event's own text.
        assert stopped.description is not None
        assert "calculated" in stopped.description.lower()
    finally:
        db.close()


def test_explicit_stop_date_does_not_carry_the_calculated_label(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        metformin = _by_name(medications, "Metformin")
        assert metformin.stop_date_basis == "explicit"

        stopped = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == metformin.id,
                models.PatientEvent.event_type == MEDICATION_STOPPED_EVENT_TYPE,
            )
            .first()
        )
        assert stopped is not None
        assert stopped.admitted_at == metformin.stop_date
        assert stopped.description is None
    finally:
        db.close()


# --- Conflict safety -----------------------------------------------------------


def test_conflicting_same_drug_mentions_never_project_a_state_change_event(discharge_document):
    db = SessionLocal()
    try:
        candidates = [
            MedicationCandidate(
                source_segment_id="seg-000-medicatie", canonical_key="medications",
                raw_text="BESREMI continua.", raw_medication_name="BESREMI",
                status_context="continued", source_evidence_text="BESREMI continua.",
            ),
            MedicationCandidate(
                source_segment_id="seg-001-medicatie", canonical_key="medications",
                raw_text="BESREMI oprit.", raw_medication_name="BESREMI",
                status_context="stopped", source_evidence_text="BESREMI oprit.",
            ),
        ]
        _persist_fixture(db, discharge_document, candidates=candidates)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        assert all(m.is_uncertain for m in medications if m.name == "BESREMI")

        events = _events_for(db, discharge_document)
        assert len(events) == 0
    finally:
        db.close()


def test_a_medication_that_becomes_uncertain_on_reprocessing_retracts_its_earlier_event(discharge_document):
    """A safety-critical edge case: an event projected while a row
    looked unambiguous must be retracted, not left stale, once a later
    reprocessing run reveals it is actually conflicting."""
    db = SessionLocal()
    try:
        # Gets its start_date via tier 3 ("a discharge recommendation
        # that clearly indicates the medication starts at discharge" —
        # canonical_key + status_context alone, discharge_date supplied
        # by _persist_fixture) rather than an explicit/starts-at-
        # discharge SIGNAL — deliberately, so _detect_conflicts (which
        # only checks those two signals, not tier 3) still sees this
        # candidate as having NO explaining date once a second, later
        # mention arrives. On its own (this first run, group size 1) it
        # is trivially not a conflict either way.
        first_candidate = [
            MedicationCandidate(
                source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
                raw_text="BESREMI 250mcg, initiat azi.", raw_medication_name="BESREMI",
                status_context="started",
                source_evidence_text="BESREMI 250mcg, initiat azi.",
            ),
        ]
        _persist_fixture(db, discharge_document, candidates=first_candidate)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        besremi = _by_name(medications, "BESREMI")
        assert besremi.is_uncertain == 0
        started = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == besremi.id,
                models.PatientEvent.event_type == MEDICATION_STARTED_EVENT_TYPE,
            )
            .first()
        )
        assert started is not None

        # Reprocessing re-extracts the FULL current candidate set for the
        # document (the real discharge_parser.py convention — never just
        # the new mention alone) — this time a second, conflicting
        # mention with no explaining date is also present, so
        # _detect_conflicts (which only ever sees one persist_medication_
        # candidates call's own candidates list) can actually see both.
        second_mention = MedicationCandidate(
            source_segment_id="seg-002-medicatie", canonical_key="medications",
            raw_text="BESREMI oprit.", raw_medication_name="BESREMI",
            status_context="stopped", source_evidence_text="BESREMI oprit.",
        )
        _persist_fixture(db, discharge_document, candidates=[*first_candidate, second_mention])
        db.commit()

        db.refresh(besremi)
        assert besremi.is_uncertain == 1

        _project(db, discharge_document)
        db.commit()

        started_after = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == besremi.id,
                models.PatientEvent.event_type == MEDICATION_STARTED_EVENT_TYPE,
            )
            .first()
        )
        assert started_after is None
    finally:
        db.close()


# --- Distinctness / manual events ---------------------------------------------


def test_distinct_medications_project_distinct_events(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        events = _events_for(db, discharge_document)
        medication_ids = {e.source_medication_id for e in events}
        assert len(medication_ids) >= 2
    finally:
        db.close()


def test_manual_patient_event_is_untouched_by_projection(discharge_document):
    db = SessionLocal()
    try:
        manual = models.PatientEvent(
            patient_id=discharge_document["patient_id"],
            doctor_user_id=discharge_document["created_by_user_id"],
            event_type="hospitalization",
            status="active",
            title="Manual admission",
            admitted_at="2026-02-01",
        )
        db.add(manual)
        db.commit()
        db.refresh(manual)
        manual_id = manual.id

        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        db.refresh(manual)
        assert manual.title == "Manual admission"
        assert manual.source_document_id is None
        assert manual.source_medication_id is None
        assert db.query(models.PatientEvent).filter(models.PatientEvent.id == manual_id).count() == 1
    finally:
        db.close()


# --- Provenance / serialization -------------------------------------------------


def test_projected_event_is_serialized_with_source_provenance_via_my_profile(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()
    finally:
        db.close()

    response = client.get("/my/profile", headers=_auth(discharge_document["account"]["token"]))
    assert response.status_code == 200
    events = response.json()["events"]
    projected = [e for e in events if e["event_type"] == MEDICATION_STARTED_EVENT_TYPE]
    assert len(projected) >= 1
    assert projected[0]["source_document_id"] == discharge_document["document_id"]
    assert projected[0]["source_medication_id"] is not None


# --- Deletion semantics ---------------------------------------------------------


def test_deleting_source_document_does_not_delete_the_projected_event(discharge_document):
    """Mirrors PatientMedication.source_document_id's own SET NULL
    choice (Phase 7): the medication fact — and the Timeline event
    representing it — stays independently meaningful once its source
    document is gone."""
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()

        medications = _medications_for(db, discharge_document)
        amox = _by_name(medications, "Amoxicilina")
        event_id = (
            db.query(models.PatientEvent)
            .filter(
                models.PatientEvent.source_medication_id == amox.id,
                models.PatientEvent.event_type == MEDICATION_STARTED_EVENT_TYPE,
            )
            .first()
            .id
        )
    finally:
        db.close()

    response = client.delete(
        f"/documents/{discharge_document['document_id']}", headers=_auth(discharge_document["account"]["token"])
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        # Post-Phase-10 integration check (Part C): the invariant is "no
        # Timeline event may continue asserting a fact with no canonical
        # support" — verified here by confirming the CANONICAL FACT
        # (PatientMedication) itself is what actually survives, not just
        # asserting the projection survives in isolation. This schema has
        # no multi-document-support concept for a medication row (exactly
        # ONE source_document_id per row, by Phase 7's own idempotency
        # design — a genuinely different mention gets its own row) so
        # there is no "Case A vs Case B" ambiguity to resolve: a
        # medication row is either supported by its one source document
        # (now gone, SET NULL) or it isn't tracked as supported by
        # anything else at all — Phase 7 already decided the fact stays
        # independently meaningful either way, and Phase 10 correctly
        # inherits that decision rather than inventing a stricter rule.
        event = db.query(models.PatientEvent).filter(models.PatientEvent.id == event_id).first()
        assert event is not None
        assert event.source_document_id is None
        assert event.title == "Amoxicilina"

        medication = db.query(models.PatientMedication).filter(models.PatientMedication.id == amox.id).first()
        assert medication is not None
        assert medication.source_document_id is None
        assert event.source_medication_id == medication.id
    finally:
        db.close()


def test_deleting_the_medication_directly_removes_its_projected_events():
    account = _signup("patient", cnp="6000101999993")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            uploaded_by_user_id=account["user"]["id"],
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-clindoc-tl-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        candidates = [
            MedicationCandidate(
                source_segment_id="seg-000-medicatie", canonical_key="discharge_medications",
                raw_text="Amoxicilina 500mg, 14 zile, incepand de azi.", raw_medication_name="Amoxicilina",
                status_context="started", starts_at_discharge_or_encounter=True,
                raw_duration="14 zile",
                source_evidence_text="Amoxicilina 500mg, 14 zile, incepand de azi.",
            ),
        ]
        from app.services.clinical_document.medication_duration import parse_duration

        candidates[0].parsed_duration = parse_duration("14 zile")

        persist_medication_candidates(
            db, document=doc, created_by_user_id=account["user"]["id"], candidates=candidates,
            discharge_date="05.03.2026",
        )
        db.commit()

        project_clinical_document_to_timeline(db, doc)
        db.commit()

        medication_id = (
            db.query(models.PatientMedication).filter(models.PatientMedication.source_document_id == doc.id).first().id
        )
        event_count_before = (
            db.query(models.PatientEvent).filter(models.PatientEvent.source_medication_id == medication_id).count()
        )
        assert event_count_before >= 1
    finally:
        db.close()

    response = client.delete(f"/my/medications/{medication_id}", headers=_auth(account["token"]))
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        event_count_after = (
            db.query(models.PatientEvent).filter(models.PatientEvent.source_medication_id == medication_id).count()
        )
        assert event_count_after == 0
    finally:
        db.close()

    client.delete("/my/account", headers=_auth(account["token"]))


# --- Authorization ---------------------------------------------------------------


def test_projected_events_are_scoped_to_their_own_patient(discharge_document):
    db = SessionLocal()
    try:
        _persist_fixture(db, discharge_document)
        db.commit()
        _project(db, discharge_document)
        db.commit()
    finally:
        db.close()

    other_account = _signup("patient", cnp="6000101999994")
    try:
        response = client.get("/my/profile", headers=_auth(other_account["token"]))
        assert response.status_code == 200
        assert response.json()["events"] == []
    finally:
        client.delete("/my/account", headers=_auth(other_account["token"]))
