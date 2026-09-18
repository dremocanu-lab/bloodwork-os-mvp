"""Source Intelligence + Provenance V2 — regression tests.

Section A: pure, no DB — page threading (segments.py) and extraction
coverage (discharge_parser.py/discharge_summary_pipeline.py's payload
shape). Section B: pure, no DB — the AI interpreter's evidence-id
resolver (ai_interpreter.py::_resolve_evidence_ids), the actual
mechanism that gives diagnoses/investigations/anomalies/recommendations/
treatment_eras real "View in original" provenance instead of an always-
empty list. Section C: real DB — end-to-end reprocessing against the
full synthetic Romanian discharge fixture, proving segment-level
SourceEvidence rows are created with real page numbers, idempotently
reused on a second reprocess, resolved onto the AI interpreter's
grounded items, and correctly exposed through the `/source-evidence/
{id}/view` endpoint (including `document_content_type`, and cross-
document isolation).
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.services.clinical_document.ai_interpreter import _resolve_evidence_ids  # noqa: E402
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.schema import (  # noqa: E402
    ClinicalEvent,
    ClinicalSection,
    DocumentMetadata,
    ExtractionCoverage,
    ParagraphBlock,
    StructuredClinicalDocument,
)
from app.services.clinical_document.segments import build_segments_from_legacy_discharge_payload  # noqa: E402
from app.services.document_taxonomy import DocumentType  # noqa: E402
from tests.fixtures.clinical_reader_v2_fixture import SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD  # noqa: E402


# ─── Section A: page threading + extraction coverage, no DB, no AI ────────


def test_page_start_threads_into_segment_page():
    segments = build_segments_from_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)
    by_text = {seg.raw_text: seg for seg in segments}

    d45_segment = next(seg for seg in segments if "D45" in seg.raw_text)
    assert d45_segment.page == 1

    phlebotomy_2019 = next(seg for seg in segments if "10.05.2019" in seg.raw_text)
    assert phlebotomy_2019.page == 2

    phlebotomy_2020 = next(seg for seg in segments if "22.11.2020" in seg.raw_text)
    assert phlebotomy_2020.page == 3

    labs_segment = next(seg for seg in segments if "WBC 15.2" in seg.raw_text)
    assert labs_segment.page == 5

    assert by_text  # sanity: dict actually built from real segments


def test_page_start_missing_or_invalid_stays_none_never_guessed():
    payload = {
        "sections": [
            {"title": "EPICRIZĂ", "body": "No page info at all."},
            {"title": "EPICRIZĂ", "body": "Invalid page info.", "page_start": "not-a-number"},
            {"title": "EPICRIZĂ", "body": "Zero page.", "page_start": 0},
        ]
    }
    segments = build_segments_from_legacy_discharge_payload(payload)
    assert all(seg.page is None for seg in segments)


def test_extraction_coverage_parsed_from_payload_when_present():
    document = parse_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)
    coverage = document.extraction_coverage
    assert coverage is not None
    assert coverage.total_pages == 6
    assert coverage.attempted_pages == 6
    assert coverage.successful_pages == 6
    assert coverage.failed_pages == []
    assert coverage.extraction_complete is True


def test_extraction_coverage_reflects_real_failures_never_hides_them():
    payload = {**SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD, "extraction_coverage": {
        "total_pages": 15,
        "attempted_pages": 15,
        "successful_pages": 12,
        "failed_pages": [13, 14, 15],
        "warning_pages": [],
        "extraction_complete": False,
    }}
    document = parse_legacy_discharge_payload(payload)
    assert document.extraction_coverage is not None
    assert document.extraction_coverage.extraction_complete is False
    assert document.extraction_coverage.failed_pages == [13, 14, 15]


def test_extraction_coverage_reconstructed_for_older_payload_without_the_field():
    """A document persisted before extraction_coverage existed still gets
    an honest reconstruction from page_count/page_payloads, rather than
    silently reporting nothing — the record must NOT be silently labeled
    fully extracted (Part 5)."""
    payload = {
        "sections": [{"title": "EPICRIZĂ", "body": "Some text.", "page_start": 1}],
        "page_count": 5,
        "page_payloads": [
            {"page_number": 1, "sections": []},
            {"page_number": 2, "sections": []},
            {"page_number": 3, "sections": []},
            # pages 4 and 5 never produced a payload at all — a real
            # partial-extraction scenario.
        ],
    }
    document = parse_legacy_discharge_payload(payload)
    assert document.extraction_coverage is not None
    assert document.extraction_coverage.total_pages == 5
    assert document.extraction_coverage.successful_pages == 3
    assert document.extraction_coverage.failed_pages == [4, 5]
    assert document.extraction_coverage.extraction_complete is False


def test_extraction_coverage_is_none_when_genuinely_nothing_to_report():
    payload = {"sections": [{"title": "X", "body": "y"}]}
    document = parse_legacy_discharge_payload(payload)
    assert document.extraction_coverage is None


# ─── Section B: AI interpreter evidence-id resolution, no DB ──────────────


def _document_with_evidence() -> StructuredClinicalDocument:
    return StructuredClinicalDocument(
        parser_version="test",
        document_kind=DocumentType.DISCHARGE_SUMMARY,
        metadata=DocumentMetadata(),
        sections=[
            ClinicalSection(
                id="section-diagnoses",
                canonical_key="diagnoses",
                display_title="Diagnoses",
                order=0,
                blocks=[ParagraphBlock(text="D45")],
                source_evidence_ids=[101],
            ),
            ClinicalSection(
                id="section-clinical_course",
                canonical_key="clinical_course",
                display_title="Clinical course",
                order=1,
                blocks=[ParagraphBlock(text="narrative")],
                source_evidence_ids=[],
            ),
        ],
        dated_events=[
            ClinicalEvent(
                source_event_id="seg-001-event-0",
                raw_date_text="18.09.2022",
                normalized_date="2022-09-18",
                event_type="treatment_change",
                raw_text="ruxolitinib transition",
                source_evidence_ids=[202],
            ),
            ClinicalEvent(
                source_event_id="seg-002-event-0",
                raw_date_text="05.02.2024",
                normalized_date="2024-02-05",
                event_type="other",
                raw_text="besremi start",
                source_evidence_ids=[203],
            ),
        ],
    )


def test_resolve_evidence_ids_from_section():
    document = _document_with_evidence()
    assert _resolve_evidence_ids(document, section_id="section-diagnoses") == [101]


def test_resolve_evidence_ids_unions_multiple_events_deduped_and_sorted():
    document = _document_with_evidence()
    ids = _resolve_evidence_ids(
        document, section_id=None, event_ids=["seg-002-event-0", "seg-001-event-0", "seg-001-event-0"]
    )
    assert ids == [202, 203]  # deduped, sorted — not insertion order


def test_resolve_evidence_ids_prefers_events_over_section_never_unions_tiers():
    """A precedence CHAIN, not a union — an event citation (tier 2) is
    more precise than a section citation (tier 3), so when both are
    given, the event's own evidence wins outright rather than being
    diluted by unioning in the section's broader evidence too."""
    document = _document_with_evidence()
    ids = _resolve_evidence_ids(document, section_id="section-diagnoses", event_ids=["seg-001-event-0"])
    assert ids == [202]


def test_resolve_evidence_ids_prefers_segments_over_events_and_section():
    """Tier 1 (segments) wins over BOTH tier 2 (events) and tier 3
    (section) when a segment_evidence_by_id map resolves something —
    the most precise citation available always wins, never diluted."""
    document = _document_with_evidence()
    ids = _resolve_evidence_ids(
        document,
        section_id="section-diagnoses",
        event_ids=["seg-001-event-0"],
        segment_ids=["seg-999"],
        segment_evidence_by_id={"seg-999": 999},
    )
    assert ids == [999]


def test_resolve_evidence_ids_falls_back_to_events_when_segment_ids_dont_resolve():
    """A cited segment_id that isn't in segment_evidence_by_id (e.g. no
    reprocessing has run yet to create the mapping) must not silently
    swallow the item's evidence — falls through to the next tier rather
    than returning nothing when something more precise was attempted but
    unavailable."""
    document = _document_with_evidence()
    ids = _resolve_evidence_ids(
        document,
        section_id="section-diagnoses",
        event_ids=["seg-001-event-0"],
        segment_ids=["seg-999"],
        segment_evidence_by_id=None,
    )
    assert ids == [202]


def test_resolve_evidence_ids_empty_when_nothing_grounded():
    document = _document_with_evidence()
    assert _resolve_evidence_ids(document, section_id="section-clinical_course", event_ids=[]) == []
    assert _resolve_evidence_ids(document, section_id=None, event_ids=[]) == []
    assert _resolve_evidence_ids(document, section_id="section-does-not-exist", event_ids=["not-real"]) == []


# ─── Section C: real DB, full reprocessing pipeline ────────────────────────

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — Section C needs real DB connectivity.", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.persistence import parse_structured_document  # noqa: E402
from app.services.clinical_document.reprocessing import reprocess_discharge_document  # noqa: E402
from app.services.source_evidence import ensure_segment_evidence  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"sipv2-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {"email": email, "full_name": f"SIPV2 Test {role}", "password": "TestPass123!", "role": role, **extra}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_document(db, *, patient_id: int, content_type: str | None = "application/pdf") -> "models.Document":
    doc = models.Document(
        patient_id=patient_id,
        section="discharge_summary",
        filename="synthetic-discharge-fixture.pdf",
        content_type=content_type,
        document_type="discharge_summary",
        report_name="Synthetic Discharge Fixture",
        created_at="2026-03-05T00:00:00Z",
        is_verified=False,
        public_id=f"brg-doc-sipv2-{uuid.uuid4().hex[:8]}",
        note_body=json.dumps(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def fixture_document():
    account = _signup("patient", cnp="6000102999985")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = _make_document(db, patient_id=patient_id)
        document_id = doc.id
    finally:
        db.close()

    yield {"account": account, "patient_id": patient_id, "document_id": document_id}

    client.delete("/my/account", headers=_auth(account["token"]))


def _realistic_mock_interpretation():
    """Mirrors backend/scripts/seed_e2e_clinical_reader_v2_document.py's
    own mocked response, built by a dry-run parse of the SAME payload so
    every id cited is real and deterministic."""
    probe = parse_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)

    def _section_id(canonical_key: str) -> str:
        return next(s.id for s in probe.sections if s.canonical_key == canonical_key)

    def _event_id_containing(text: str) -> str:
        return next(e.source_event_id for e in probe.dated_events if text in e.raw_text)

    def _segment_id_containing(text: str) -> str:
        for section in probe.sections:
            paragraph_texts = [b.text for b in section.blocks if getattr(b, "type", None) == "paragraph"]
            if len(paragraph_texts) != len(section.source_segment_ids):
                continue
            for segment_id, block_text in zip(section.source_segment_ids, paragraph_texts):
                if text in block_text:
                    return segment_id
        raise ValueError(f"No segment found containing {text!r}")

    clinical_course_id = _section_id("clinical_course")
    diagnoses_id = _section_id("diagnoses")
    ruxolitinib_event_id = _event_id_containing("trecerea de la Hidroxiuree la Ruxolitinib")
    besremi_start_id = _event_id_containing("s-a initiat tratament cu Besremi")
    besremi_dose_id = _event_id_containing("doza de Besremi a fost crescuta")
    historical_onset_segment_id = _segment_id_containing("JAK2 V617F pozitiva")
    d45_segment_id = _segment_id_containing("D45 Policitemie vera")

    def raw(_input):
        return {
            "diagnoses": [
                {
                    "code": "D45", "text": "Policitemie vera", "role": "principal",
                    "source_section_id": diagnoses_id, "source_event_ids": [],
                    "source_segment_ids": [d45_segment_id],
                },
            ],
            "investigations": [
                {
                    "investigation_type": "molecular", "title": "JAK2 V617F",
                    "findings": "Mutatia JAK2 V617F pozitiva.", "conclusion": None,
                    "source_section_id": clinical_course_id, "source_event_ids": [],
                    "source_segment_ids": [historical_onset_segment_id],
                },
            ],
            "anomalies": [], "recommendations": [],
            "treatment_eras": [
                {
                    "label": "Ruxolitinib", "start_date": "2022-09-18", "end_date": "2024-02-05",
                    "description": "Trecere de la Hidroxiuree la Ruxolitinib.",
                    "event_ids": [ruxolitinib_event_id],
                },
                {
                    "label": "Besremi", "start_date": "2024-02-05", "end_date": None,
                    "description": "Initiere Besremi, ulterior titrare.",
                    "event_ids": [besremi_start_id, besremi_dose_id],
                },
            ],
            "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": [], "event_ids": []},
            "encounter_scope_assignments": [],
            "warnings": [],
        }

    return raw, {"clinical_course_id": clinical_course_id, "diagnoses_id": diagnoses_id}


def test_reprocessing_attaches_real_page_evidence_to_diagnoses(fixture_document, monkeypatch):
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        result = reprocess_discharge_document(db, document=document, actor_user_id=fixture_document["account"]["user"]["id"])

        assert result.segment_evidence_created > 0
        assert result.segments_with_page > 0
        assert result.segments_without_page == 0  # every fixture segment has a page_start
        assert result.extraction_complete is True

        structured = parse_structured_document(document.note_body)
        assert structured is not None
        assert len(structured.diagnoses) == 1
        diagnosis = structured.diagnoses[0]
        assert diagnosis.source_evidence_ids  # no longer hardcoded []

        evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.id == diagnosis.source_evidence_ids[0]).first()
        assert evidence is not None
        assert evidence.page_number == 1  # the D45 section's own page_start
        assert evidence.bbox_x is None  # never a fabricated bbox
        # Exactly ONE evidence id (the D45 segment itself), never the
        # whole 2-segment diagnoses section (D45 + the blank secondary
        # field) — segment-level citation is precise, not just correct.
        assert len(diagnosis.source_evidence_ids) == 1
    finally:
        db.close()


def test_reprocessing_resolves_investigation_to_the_one_specific_segment_not_the_whole_section(fixture_document, monkeypatch):
    """The real bug this locks down: an investigation with no dated
    event (the historical JAK2 mention has no parseable date) used to
    resolve to its SECTION's entire aggregate evidence — for
    clinical_course, that meant EVERY one of its 13+ contributing
    segments' evidence, not just the one paragraph that actually
    mentions JAK2. Segment-level citation fixes this precisely."""
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        reprocess_discharge_document(db, document=document, actor_user_id=fixture_document["account"]["user"]["id"])

        structured = parse_structured_document(document.note_body)
        assert structured is not None
        jak2 = next(inv for inv in structured.investigations if inv.title == "JAK2 V617F")
        assert len(jak2.source_evidence_ids) == 1

        evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.id == jak2.source_evidence_ids[0]).first()
        assert "JAK2 V617F" in (evidence.source_text or "")
        assert evidence.page_number == 2  # the historical-onset segment's own page_start

        # The clinical_course SECTION's own aggregate is still much
        # larger (every contributing segment) — proving the investigation
        # deliberately did NOT resolve to that broader set.
        clinical_course = next(s for s in structured.sections if s.canonical_key == "clinical_course")
        assert len(clinical_course.source_evidence_ids) > 5
    finally:
        db.close()


def test_treatment_era_source_evidence_ids_are_union_of_its_events(fixture_document, monkeypatch):
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        reprocess_discharge_document(db, document=document, actor_user_id=fixture_document["account"]["user"]["id"])

        structured = parse_structured_document(document.note_body)
        assert structured is not None
        besremi_era = next(era for era in structured.treatment_eras if era.label == "Besremi")
        assert len(besremi_era.source_evidence_ids) == 2  # start event (page 3) + dose-change event (page 3)

        pages = set()
        for eid in besremi_era.source_evidence_ids:
            evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.id == eid).first()
            pages.add(evidence.page_number)
        assert pages == {3}
    finally:
        db.close()


def test_reprocessing_segment_evidence_is_idempotent(fixture_document, monkeypatch):
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()

        first = reprocess_discharge_document(db, document=document, actor_user_id=fixture_document["account"]["user"]["id"])
        assert first.segment_evidence_created > 0
        assert first.segment_evidence_reused == 0

        total_after_first = db.query(models.SourceEvidence).filter(models.SourceEvidence.document_id == document.id).count()

        second = reprocess_discharge_document(db, document=document, actor_user_id=fixture_document["account"]["user"]["id"])
        assert second.segment_evidence_created == 0
        assert second.segment_evidence_reused == first.segment_evidence_created + first.segment_evidence_reused

        total_after_second = db.query(models.SourceEvidence).filter(models.SourceEvidence.document_id == document.id).count()
        assert total_after_second == total_after_first  # no duplicate rows
    finally:
        db.close()


def test_segment_evidence_isolated_per_document_even_with_identical_segment_ids(fixture_document):
    """Part 52 — cross-document evidence must never bleed together, even
    when two documents happen to produce the SAME synthetic
    source_block_id (deterministic ids derived from position+heading, so
    two documents built from the same fixture legitimately do)."""
    db = SessionLocal()
    try:
        document_a = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        document_b = _make_document(db, patient_id=fixture_document["patient_id"])

        segments = build_segments_from_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)
        d45_segment = next(seg for seg in segments if "D45" in seg.raw_text)

        evidence_a, was_new_a = ensure_segment_evidence(
            db, document_a, source_block_id=d45_segment.segment_id, page_number=d45_segment.page, source_text=d45_segment.raw_text
        )
        evidence_b, was_new_b = ensure_segment_evidence(
            db, document_b, source_block_id=d45_segment.segment_id, page_number=d45_segment.page, source_text=d45_segment.raw_text
        )

        assert was_new_a is True
        assert was_new_b is True  # NOT reused across documents despite the identical source_block_id
        assert evidence_a.id != evidence_b.id
        assert evidence_a.document_id == document_a.id
        assert evidence_b.document_id == document_b.id
    finally:
        db.close()


def test_source_evidence_view_endpoint_reports_page_only_precision_and_content_type(fixture_document, monkeypatch):
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)
    headers = _auth(fixture_document["account"]["token"])

    response = client.post(
        f"/documents/{fixture_document['document_id']}/reprocess-clinical-structure", headers=headers
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        structured = parse_structured_document(document.note_body)
        assert structured is not None
        evidence_id = structured.diagnoses[0].source_evidence_ids[0]
    finally:
        db.close()

    view = client.get(f"/source-evidence/{evidence_id}/view", headers=headers)
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["precision"] == "page_only"  # page known, no bbox — never fabricated
    assert body["page_number"] == 1
    assert body["document_content_type"] == "application/pdf"
    assert body["bbox_x"] is None


def test_source_evidence_view_endpoint_rejects_cross_patient_access(fixture_document, monkeypatch):
    mock_fn, _ids = _realistic_mock_interpretation()
    monkeypatch.setattr(ai_interpreter, "_call_model", mock_fn)
    owner_headers = _auth(fixture_document["account"]["token"])

    response = client.post(
        f"/documents/{fixture_document['document_id']}/reprocess-clinical-structure", headers=owner_headers
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture_document["document_id"]).first()
        structured = parse_structured_document(document.note_body)
        evidence_id = structured.diagnoses[0].source_evidence_ids[0]
    finally:
        db.close()

    other_account = _signup("patient", cnp="6000102999986")
    try:
        response = client.get(f"/source-evidence/{evidence_id}/view", headers=_auth(other_account["token"]))
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(other_account["token"]))
