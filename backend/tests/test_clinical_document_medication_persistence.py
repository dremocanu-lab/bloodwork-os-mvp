"""Focused tests for canonical medication persistence — Clinical
Document Intelligence V3, Phase 7. Needs real DB connectivity (same
skip-gracefully convention as test_idor_regression.py/
test_clinical_document_lab_persistence.py).
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
from app.services.clinical_document.events import ClinicalEvent  # noqa: E402
from app.services.clinical_document.medication_extraction import (  # noqa: E402
    MedicationCandidate,
    extract_medication_candidates_from_event,
    extract_medication_candidates_from_segment,
)
from app.services.clinical_document.medication_persistence import (  # noqa: E402
    persist_medication_candidates,
)
from app.services.clinical_document.segments import SourceSegment  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-med-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Clinical Doc Med Test {role}",
        "password": "TestPass123!",
        "role": role,
        **extra,
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": {**data["user"]}, "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def discharge_document():
    account = _signup("patient", cnp="6000101999991")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-clindoc-med-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
        created_by_user_id = doc.uploaded_by_user_id
    finally:
        db.close()

    yield {
        "account": account,
        "patient_id": patient_id,
        "document_id": document_id,
        "created_by_user_id": account["user"]["id"],
    }

    client.delete("/my/account", headers=_auth(account["token"]))


DISCHARGE_MEDICATIONS_FIXTURE_TEXT = """\
Metoprolol 50mg 1-0-1 per os, se continua tratamentul cu doza anterioara.
BESREMI 250mcg subcutanat, se initiaza tratamentul din data de 05.03.2026, 14 zile.
Amoxicilina 500mg 1-1-1, 14 zile, incepand de azi.
Ibuprofen 400mg la nevoie pentru durere.
Metotrexat 10mg, conform schemei oncologice.
Prednison 20mg, scadere progresiva a dozei.
Levotiroxina 50mcg, continua tratamentul pana la control.
Metformin 850mg, oprit din data de 04.03.2026 din cauza efectelor adverse.
Amoxicilina 875mg, tratament pana la 20.03.2026, 14 zile.
"""


def _segment() -> SourceSegment:
    return SourceSegment(
        segment_id="seg-000-medicatie",
        index=0,
        raw_heading="MEDICAȚIE LA EXTERNARE",
        raw_text=DISCHARGE_MEDICATIONS_FIXTURE_TEXT,
    )


def _extract_fixture_candidates() -> list[MedicationCandidate]:
    return extract_medication_candidates_from_segment(
        _segment(), canonical_key="discharge_medications", source_section_id="section-discharge_medications"
    )


def _by_name(candidates_or_observations, name: str):
    return next(c for c in candidates_or_observations if getattr(c, "raw_medication_name", None) == name or getattr(c, "name", None) == name)


def _persist(db, discharge_document, candidates=None, **kwargs):
    document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
    return persist_medication_candidates(
        db,
        document=document,
        created_by_user_id=discharge_document["created_by_user_id"],
        candidates=candidates if candidates is not None else _extract_fixture_candidates(),
        **kwargs,
    )


# --- Status/context mapping ---------------------------------------------------


def test_current_medication_extraction(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        obs = _by_name(result.observations, "Metoprolol")
        assert obs.status == "active"
    finally:
        db.close()


def test_medication_started_explicitly(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == _by_name(result.observations, "BESREMI").medication_id
        ).first()
        assert row.status == "active"
        assert row.start_date == "2026-03-05"
    finally:
        db.close()


def test_medication_stopped_explicitly(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        obs = _by_name(result.observations, "Metformin")
        assert obs.status == "stopped"
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.stop_date == "2026-03-04"
        assert row.stop_date_basis == "explicit"
    finally:
        db.close()


def test_historical_medication_not_marked_current():
    from app.services.clinical_document.medication_persistence import _resolve_status

    candidate = MedicationCandidate(
        source_segment_id="s", canonical_key="treatment", raw_text="Ibuprofen 400mg, tratament anterior.",
        raw_medication_name="Ibuprofen", status_context="historical", source_evidence_text="x",
    )
    status, _ = _resolve_status(candidate)
    assert status != "active"
    assert status == "stopped"


def test_uncertain_context_becomes_requires_review(discharge_document):
    candidate = MedicationCandidate(
        source_segment_id="seg-x", canonical_key="medications", raw_text="Simvastatin 20mg",
        raw_medication_name="Simvastatin", status_context="uncertain", source_evidence_text="Simvastatin 20mg",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[candidate])
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == result.observations[0].medication_id
        ).first()
        assert bool(row.is_uncertain) is True
    finally:
        db.close()


def test_completed_course_maps_to_stopped_status_with_distinguishing_note(discharge_document):
    candidate = MedicationCandidate(
        source_segment_id="seg-c", canonical_key="treatment", raw_text="Amoxicilina 500mg, tratament finalizat.",
        raw_medication_name="Amoxicilina", status_context="completed", source_evidence_text="Amoxicilina 500mg, tratament finalizat.",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[candidate])
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == result.observations[0].medication_id
        ).first()
        assert row.status == "stopped"
        assert "completed as planned" in (row.extra_info or "")
    finally:
        db.close()


def test_literal_discontinued_wording_never_produces_active_medication(discharge_document):
    candidate = MedicationCandidate(
        source_segment_id="seg-d", canonical_key="treatment", raw_text="Warfarin 5mg, discontinued due to bleeding risk.",
        raw_medication_name="Warfarin", status_context="stopped", source_evidence_text="Warfarin 5mg, discontinued due to bleeding risk.",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[candidate])
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == result.observations[0].medication_id
        ).first()
        assert row.status != "active"
        assert row.status == "stopped"
    finally:
        db.close()


def test_prescription_issued_does_not_pretend_medication_was_taken(discharge_document):
    candidate = MedicationCandidate(
        source_segment_id="seg-rx", canonical_key="prescriptions", raw_text="Amoxicilina 500mg 1-1-1",
        raw_medication_name="Amoxicilina", status_context="prescribed", source_evidence_text="Amoxicilina 500mg 1-1-1",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[candidate])
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == result.observations[0].medication_id
        ).first()
        assert bool(row.is_uncertain) is True
        assert "does not confirm administration" in (row.extra_info or "")
    finally:
        db.close()


# --- Start-date priority --------------------------------------------------


def test_explicit_start_date_wins_priority_tier_1(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="10.03.2026")  # a DIFFERENT date than the explicit one
        db.commit()
        obs = _by_name(result.observations, "BESREMI")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.start_date == "2026-03-05"  # the EXPLICIT date, not the discharge_date
    finally:
        db.close()


def test_discharge_recommendation_uses_discharge_date_tier_3():
    """A discharge_medications entry newly STARTED at discharge, with NO
    explicit date and NO 'starting today' phrasing at all, still
    reliably starts at the discharge date — tier 3."""
    from app.services.clinical_document.medication_persistence import _resolve_start_date

    candidate = MedicationCandidate(
        source_segment_id="s", canonical_key="discharge_medications", raw_text="Metformin 500mg 1-0-1",
        raw_medication_name="Metformin", status_context="started", source_evidence_text="x",
    )
    start_iso, basis = _resolve_start_date(candidate, discharge_date="12.03.2026")
    assert start_iso == "2026-03-12"
    assert basis == "discharge_recommendation"


def test_continued_medication_does_not_use_tier_3_discharge_recommendation():
    """Tier 3 only applies to a NEWLY started/prescribed mention — a
    'continued' medication was already ongoing before this document, so
    inferring it started AT discharge would be a fabrication."""
    from app.services.clinical_document.medication_persistence import _resolve_start_date

    candidate = MedicationCandidate(
        source_segment_id="s", canonical_key="discharge_medications", raw_text="Metoprolol 50mg, continua.",
        raw_medication_name="Metoprolol", status_context="continued", source_evidence_text="x",
    )
    start_iso, basis = _resolve_start_date(candidate, discharge_date="12.03.2026")
    assert start_iso is None
    assert basis is None


def test_start_today_uses_reliable_discharge_date_tier_2(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="10.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Amoxicilina")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.start_date == "2026-03-10"
    finally:
        db.close()


def test_upload_and_ingestion_date_never_used_as_start_date(discharge_document):
    """No discharge_date/admission_date supplied at all — even though the
    Document row itself has a real created_at, start_date must stay
    null, never silently backed by that unrelated timestamp."""
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)  # no discharge_date passed
        db.commit()
        obs = _by_name(result.observations, "Amoxicilina")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.start_date is None
    finally:
        db.close()


def test_no_reliable_start_date_stays_null_not_invented(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        obs = _by_name(result.observations, "Metoprolol")  # "continued" — no start signal at all
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.start_date is None
    finally:
        db.close()


# --- End-date derivation ----------------------------------------------------


def test_end_date_derived_from_reliable_start_plus_duration(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")  # BESREMI: explicit start 05.03.2026, 14 zile
        db.commit()
        obs = _by_name(result.observations, "BESREMI")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.start_date == "2026-03-05"
        assert row.stop_date == "2026-03-19"
        assert row.stop_date_basis == "derived"
    finally:
        db.close()


def test_prn_never_gets_a_derived_end_date(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Ibuprofen")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.status == "as_needed"
        assert row.stop_date is None
    finally:
        db.close()


def test_scheme_regimen_never_gets_a_derived_end_date(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Metotrexat")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.stop_date is None
    finally:
        db.close()


def test_indefinite_regimen_never_gets_a_derived_end_date(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Levotiroxina")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.stop_date is None
    finally:
        db.close()


def test_taper_without_clear_duration_never_gets_a_derived_end_date(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Prednison")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.stop_date is None
    finally:
        db.close()


def test_explicit_end_date_preserved(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        obs = _by_name(result.observations, "Amoxicilina")  # 875mg row: explicit end 20.03.2026
        rows = db.query(models.PatientMedication).filter(
            models.PatientMedication.id.in_([o.medication_id for o in result.observations if o.raw_medication_name == "Amoxicilina"])
        ).all()
        explicit_row = next(r for r in rows if r.stop_date == "2026-03-20")
        assert explicit_row.stop_date_basis == "explicit"
    finally:
        db.close()


def test_explicit_and_derived_end_date_conflict_is_preserved_not_overwritten():
    candidate = MedicationCandidate(
        source_segment_id="seg-conflict", canonical_key="discharge_medications",
        raw_text="Doxiciclina 100mg, din data de 05.03.2026, 14 zile, pana la 25.03.2026.",
        raw_medication_name="Doxiciclina", status_context="started",
        explicit_start_date="05.03.2026", explicit_end_date="25.03.2026",
        raw_duration="14 zile",
        source_evidence_text="x",
    )
    from app.services.clinical_document.medication_duration import parse_duration
    candidate = candidate.model_copy(update={"parsed_duration": parse_duration("14 zile")})

    from app.services.clinical_document.medication_persistence import _resolve_start_date, _resolve_stop_date

    start_iso, _basis = _resolve_start_date(candidate, discharge_date=None)
    assert start_iso == "2026-03-05"
    stop_iso, stop_basis, warnings = _resolve_stop_date(candidate, start_date_iso=start_iso)
    # 2026-03-05 + 14 days = 2026-03-19, which DISAGREES with the explicit 2026-03-25.
    assert stop_iso == "2026-03-25"  # explicit value wins, never silently overwritten
    assert stop_basis == "explicit_with_derived_conflict"
    assert warnings  # the conflict is named, not silently dropped


def test_duration_preserved_in_extra_info_even_when_no_start_date_to_derive_from(discharge_document):
    """A documented 14-day course must not silently disappear just
    because there's no reliable start date to actually derive stop_date
    from — Phase 7M's 'preserve duration' requirement."""
    candidate = MedicationCandidate(
        source_segment_id="seg-nd", canonical_key="treatment", raw_text="Ciprofloxacin 500mg, 10 zile.",
        raw_medication_name="Ciprofloxacin", status_context="uncertain", raw_duration="10 zile",
        source_evidence_text="Ciprofloxacin 500mg, 10 zile.",
    )
    from app.services.clinical_document.medication_duration import parse_duration
    candidate = candidate.model_copy(update={"parsed_duration": parse_duration("10 zile")})

    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[candidate])
        db.commit()
        row = db.query(models.PatientMedication).filter(
            models.PatientMedication.id == result.observations[0].medication_id
        ).first()
        assert row.stop_date is None
        assert row.stop_date_basis is None
        assert "10 zile" in (row.extra_info or "")
    finally:
        db.close()


# --- Conflicts / distinct transitions ---------------------------------------


def test_same_drug_start_then_later_stop_remains_two_distinct_rows_not_a_conflict(discharge_document):
    started = MedicationCandidate(
        source_segment_id="seg-a", canonical_key="clinical_course", raw_text="S-a initiat tratament cu BESREMI.",
        raw_medication_name="BESREMI", status_context="started", explicit_start_date="01.03.2026",
        source_evidence_text="S-a initiat tratament cu BESREMI.",
    )
    stopped = MedicationCandidate(
        source_segment_id="seg-b", canonical_key="clinical_course", raw_text="S-a oprit BESREMI.",
        raw_medication_name="BESREMI", status_context="stopped", explicit_start_date=None,
        source_evidence_text="S-a oprit BESREMI.",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[started, stopped])
        db.commit()
        assert len(result.observations) == 2
        assert not any(o.conflict for o in result.observations)
        statuses = {o.status for o in result.observations}
        assert statuses == {"active", "stopped"}
    finally:
        db.close()


def test_conflicting_medication_status_across_sources_is_preserved_and_flagged(discharge_document):
    active_claim = MedicationCandidate(
        source_segment_id="seg-a", canonical_key="medications", raw_text="BESREMI 250mcg continua.",
        raw_medication_name="BESREMI", status_context="continued",
        source_evidence_text="BESREMI 250mcg continua.",
    )
    stopped_claim = MedicationCandidate(
        source_segment_id="seg-b", canonical_key="medications", raw_text="BESREMI oprit.",
        raw_medication_name="BESREMI", status_context="stopped",
        source_evidence_text="BESREMI oprit.",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[active_claim, stopped_claim])
        db.commit()
        assert all(o.conflict for o in result.observations)
        rows = db.query(models.PatientMedication).filter(
            models.PatientMedication.id.in_([o.medication_id for o in result.observations])
        ).all()
        assert all(bool(r.is_uncertain) for r in rows)
        assert all("Conflicting status" in (r.extra_info or "") for r in rows)
    finally:
        db.close()


# --- Idempotency --------------------------------------------------------------


def test_repeated_identical_extraction_does_not_duplicate_medications(discharge_document):
    db = SessionLocal()
    try:
        first = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()
        second = _persist(db, discharge_document, discharge_date="05.03.2026")
        db.commit()

        assert all(o.was_new for o in first.observations)
        assert all(not o.was_new for o in second.observations)

        count = db.query(models.PatientMedication).filter(
            models.PatientMedication.source_document_id == discharge_document["document_id"]
        ).count()
        assert count == len(first.observations)
    finally:
        db.close()


def test_genuinely_separate_source_medication_events_do_not_over_deduplicate(discharge_document):
    started = MedicationCandidate(
        source_segment_id="seg-a", canonical_key="clinical_course", raw_text="S-a initiat tratament cu BESREMI.",
        raw_medication_name="BESREMI", status_context="started",
        source_evidence_text="S-a initiat tratament cu BESREMI.",
    )
    stopped = MedicationCandidate(
        source_segment_id="seg-b", canonical_key="clinical_course", raw_text="S-a oprit BESREMI.",
        raw_medication_name="BESREMI", status_context="stopped",
        source_evidence_text="S-a oprit BESREMI.",
    )
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document, candidates=[started, stopped])
        db.commit()
        assert len({o.medication_id for o in result.observations}) == 2
    finally:
        db.close()


# --- Provenance ----------------------------------------------------------------


def test_source_segment_and_evidence_preserved(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        obs = _by_name(result.observations, "Metoprolol")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.source_segment_id == "seg-000-medicatie"
        assert row.source_document_id == discharge_document["document_id"]

        evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.medication_id == row.id).first()
        assert evidence is not None
        assert evidence.source_block_id == "seg-000-medicatie"
        assert "Metoprolol" in evidence.source_text
    finally:
        db.close()


def test_non_pdf_evidence_never_fakes_geometry(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        for obs in result.observations:
            evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.medication_id == obs.medication_id).first()
            assert evidence.page_number is None
            assert evidence.bbox_x is None
    finally:
        db.close()


def test_raw_medication_name_survives_verbatim_without_mandatory_normalization(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        obs = _by_name(result.observations, "BESREMI")
        row = db.query(models.PatientMedication).filter(models.PatientMedication.id == obs.medication_id).first()
        assert row.name == "BESREMI"
        # No RxNorm lookup was triggered by persistence — this is a
        # deterministic, network-free service; official_match_status
        # stays whatever the DB default leaves it (never forced to
        # "matched").
        assert row.official_match_status != "matched"
    finally:
        db.close()


# --- Deletion semantics ------------------------------------------------------


# --- No second medication datastore -----------------------------------------


def test_no_second_medication_model_exists():
    """Phase 7's hard rule: PatientMedication (or the exact canonical
    persistence architecture already in the repo) is the ONLY medication
    table — never a DischargeMedication/ExtractedMedication/
    MedicationEpisode/DocumentMedication table."""
    table_names = set(models.Base.metadata.tables.keys())
    forbidden = {"discharge_medications", "extracted_medications", "medication_episodes", "document_medications"}
    assert table_names.isdisjoint(forbidden)
    assert "patient_medications" in table_names


def test_deleting_source_document_clears_provenance_but_keeps_the_medication(discharge_document):
    db = SessionLocal()
    try:
        result = _persist(db, discharge_document)
        db.commit()
        medication_ids = [o.medication_id for o in result.observations]
    finally:
        db.close()

    response = client.delete(
        f"/documents/{discharge_document['document_id']}", headers=_auth(discharge_document["account"]["token"])
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        rows = db.query(models.PatientMedication).filter(models.PatientMedication.id.in_(medication_ids)).all()
        assert len(rows) == len(medication_ids)  # medications survive
        assert all(r.source_document_id is None for r in rows)  # provenance cleared

        evidence_count = db.query(models.SourceEvidence).filter(
            models.SourceEvidence.medication_id.in_(medication_ids)
        ).count()
        assert evidence_count == 0  # evidence explicitly removed, no dangling FK
    finally:
        db.close()
