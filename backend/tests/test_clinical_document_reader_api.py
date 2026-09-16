"""Focused tests for the Phase 8 clinical-reader API contract —
GET /documents/{id}/clinical-reader. Needs real DB connectivity (same
skip-gracefully convention as test_idor_regression.py).
"""

import json
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
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.lab_extraction import extract_lab_candidates_from_segment  # noqa: E402
from app.services.clinical_document.lab_persistence import persist_lab_candidates  # noqa: E402
from app.services.clinical_document.medication_extraction import MedicationCandidate  # noqa: E402
from app.services.clinical_document.medication_persistence import persist_medication_candidates  # noqa: E402
from app.services.clinical_document.persistence import serialize_structured_document  # noqa: E402
from app.services.clinical_document.segments import SourceSegment  # noqa: E402
from app.services.clinical_document.schema import (  # noqa: E402
    ClinicalSection,
    DerivedArtifactRef,
    DocumentMetadata,
    LabReportReferenceBlock,
    MedicationListBlock,
    StructuredClinicalDocument,
)

from tests.test_clinical_document_lab_extraction import HEMATOLOGY_FIXTURE_TEXT  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-reader-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Clinical Reader Test {role}",
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
def patient_account():
    account = _signup("patient", cnp="6000101999971")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    yield {"account": account, "patient_id": profile["patient"]["id"], "user_id": account["user"]["id"]}
    client.delete("/my/account", headers=_auth(account["token"]))


def _make_document(db, *, patient_id: int, note_body: str | None, uploaded_by_user_id: int | None = None) -> int:
    doc = models.Document(
        patient_id=patient_id,
        uploaded_by_user_id=uploaded_by_user_id,
        section="discharge_summary",
        filename="discharge.pdf",
        content_type="application/pdf",
        document_type="discharge_summary",
        report_name="Discharge Summary",
        created_at="2026-03-05T00:00:00Z",
        is_verified=False,
        note_body=note_body,
        public_id=f"brg-doc-reader-{uuid.uuid4().hex[:8]}",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc.id


LEGACY_REPEATED_EPICRIZA_PAYLOAD = {
    "document_type": "discharge_summary",
    "admission_date": "10.01.2026",
    "discharge_date": "20.01.2026",
    "sections": [
        {"key": "epicriza", "title": "EPICRIZĂ", "body": "Internat la 10.01.2026 pentru dureri abdominale."},
        {"key": "epicriza", "title": "EPICRIZĂ", "body": "Externat la 20.01.2026, ameliorat."},
        {"key": "diagnoses", "title": "Diagnostic principal", "body": "K80.2 Colelitiaza"},
        {"key": "other", "title": "", "body": ""},
    ],
}


# --- 1/3/4: legacy upconversion, repeated headings merge, empty sections excluded ----


def test_legacy_discharge_note_body_upconverts_into_reader_payload(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=json.dumps(LEGACY_REPEATED_EPICRIZA_PAYLOAD)
        )
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["structured_document"] is not None
    assert payload["structured_document"]["parser_version"] == "legacy-discharge-upconversion-v1"


def test_repeated_epicriza_does_not_become_duplicate_sections(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=json.dumps(LEGACY_REPEATED_EPICRIZA_PAYLOAD)
        )
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    sections = response.json()["structured_document"]["sections"]
    clinical_course_sections = [s for s in sections if s["canonical_key"] == "clinical_course"]
    assert len(clinical_course_sections) == 1
    # Both repeated EPICRIZĂ entries merge into ONE section, but each
    # contributor's own text survives as its own block (never
    # concatenated into one string) — source_headings itself lists
    # DISTINCT heading strings (both say "EPICRIZĂ" verbatim here, so
    # that list is correctly length 1; the real "not duplicated but not
    # lost" proof is that both bodies survive as two separate blocks).
    assert len(clinical_course_sections[0]["blocks"]) == 2


def test_empty_sections_not_exposed_prominently(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=json.dumps(LEGACY_REPEATED_EPICRIZA_PAYLOAD)
        )
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    sections = response.json()["structured_document"]["sections"]
    # The 4th source entry (empty title/body) must not produce a section.
    assert all(s["blocks"] for s in sections)


# --- 2: native StructuredClinicalDocument ------------------------------------


def test_native_structured_document_returns_same_reader_contract(patient_account):
    doc = StructuredClinicalDocument(
        parser_version="discharge-parser-phase4-5-v1",
        document_kind="discharge_summary",
        metadata=DocumentMetadata(hospital_name="Spitalul Test"),
        sections=[
            ClinicalSection(id="section-diagnoses", canonical_key="diagnoses", display_title="Diagnoses", order=0, blocks=[]),
        ],
    )
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=serialize_structured_document(doc)
        )
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    assert response.status_code == 200, response.text
    payload = response.json()["structured_document"]
    assert payload["parser_version"] == "discharge-parser-phase4-5-v1"
    assert payload["metadata"]["hospital_name"] == "Spitalul Test"


# --- 5/6/7: dated events, suspicious date, suspicious vital -------------------

SUSPICIOUS_FIXTURE_PAYLOAD = {
    "document_type": "discharge_summary",
    "admission_date": "10.01.2026",
    "discharge_date": "20.01.2026",
    "sections": [
        {
            "key": "epicriza",
            "title": "EPICRIZĂ",
            "body": (
                "Internat la 10.01.2026 cu AV 1008 bpm. "
                "Control programat pentru 14/09/3036. "
                "Externat la 20.01.2026, ameliorat."
            ),
        },
    ],
}


def _suspicious_note_body() -> str:
    # dated_events/warnings are only populated by the REAL forward parser
    # (discharge_parser.py) — the backward-compat legacy-upconversion path
    # (persistence.py, used for an OLD note_body with no schema_version)
    # deliberately only rebuilds sections, not events (see the Phase 4/5
    # handoff). Build a real StructuredClinicalDocument and serialize it
    # with schema_version set, so parse_structured_document reads it via
    # the native path — this is what a real forward-parsed document's
    # note_body actually looks like once Phase 8's dual-write exists.
    structured = parse_legacy_discharge_payload(SUSPICIOUS_FIXTURE_PAYLOAD)
    return serialize_structured_document(structured)


def test_dated_clinical_events_included(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"], note_body=_suspicious_note_body())
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    events = response.json()["structured_document"]["dated_events"]
    assert len(events) >= 2
    assert any(e["event_type"] == "admission" for e in events)


def test_suspicious_date_warning_preserved_not_corrected(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"], note_body=_suspicious_note_body())
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    events = response.json()["structured_document"]["dated_events"]
    suspicious = next(e for e in events if e["raw_date_text"] == "14/09/3036")
    assert suspicious["normalized_date"] == "3036-09-14"  # kept, never "corrected"
    assert suspicious["warnings"]


def test_suspicious_vital_warning_preserved(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"], note_body=_suspicious_note_body())
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    warnings = response.json()["structured_document"]["warnings"]
    assert any("1008" in w for w in warnings)


# --- 8/9/13: labs, lab conflict, SourceEvidence ids ----------------------------


def _segment() -> SourceSegment:
    return SourceSegment(segment_id="seg-000-laborator", index=0, raw_heading="EXAMENE DE LABORATOR", raw_text=HEMATOLOGY_FIXTURE_TEXT)


def test_referenced_lab_results_included(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        candidates = extract_lab_candidates_from_segment(_segment())
        persist_lab_candidates(db, document=document, candidates=candidates)
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    labs = response.json()["labs"]
    assert any(lab["raw_test_name"] == "PLT" and lab["value"] == "349" for lab in labs)


def test_lab_conflict_survives_in_reader_payload(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        candidates = extract_lab_candidates_from_segment(_segment())
        persist_lab_candidates(db, document=document, candidates=candidates)
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    labs = response.json()["labs"]
    mch_rows = [lab for lab in labs if lab["raw_test_name"] == "MCH"]
    assert len(mch_rows) == 2
    assert {row["value"] for row in mch_rows} == {"29.0", "31.5"}


def test_source_evidence_ids_retained_on_labs_and_medications(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        lab_candidates = extract_lab_candidates_from_segment(_segment())
        persist_lab_candidates(db, document=document, candidates=lab_candidates)
        med_candidate = MedicationCandidate(
            source_segment_id="seg-001-medicatie", canonical_key="discharge_medications",
            raw_text="Metoprolol 50mg 1-0-1", raw_medication_name="Metoprolol", status_context="continued",
            source_evidence_text="Metoprolol 50mg 1-0-1",
        )
        persist_medication_candidates(db, document=document, created_by_user_id=document.uploaded_by_user_id, candidates=[med_candidate])
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    payload = response.json()
    assert all(lab["source_evidence_id"] is not None for lab in payload["labs"])
    assert all(med["source_evidence_id"] is not None for med in payload["medications"])
    assert payload["document"]["document_level_source_evidence_id"] is not None


# --- 10/11/12: medications, explicit-vs-derived end date, status conflict -----


def test_referenced_medications_included(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        candidate = MedicationCandidate(
            source_segment_id="seg-001-medicatie", canonical_key="discharge_medications",
            raw_text="BESREMI 250mcg subcutanat, se initiaza tratamentul din data de 05.03.2026, 14 zile.",
            raw_medication_name="BESREMI", status_context="started", explicit_start_date="05.03.2026",
            raw_duration="14 zile", source_evidence_text="BESREMI 250mcg subcutanat, 14 zile.",
        )
        from app.services.clinical_document.medication_duration import parse_duration
        candidate = candidate.model_copy(update={"parsed_duration": parse_duration("14 zile")})
        persist_medication_candidates(db, document=document, created_by_user_id=document.uploaded_by_user_id, candidates=[candidate])
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    medications = response.json()["medications"]
    besremi = next(m for m in medications if m["name"] == "BESREMI")
    assert besremi["start_date"] == "2026-03-05"
    assert besremi["stop_date"] == "2026-03-19"
    assert besremi["stop_date_basis"] == "derived"


def test_explicit_end_date_distinguishable_from_derived(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        candidate = MedicationCandidate(
            source_segment_id="seg-002-medicatie", canonical_key="discharge_medications",
            raw_text="Amoxicilina 500mg, tratament pana la 20.03.2026.",
            raw_medication_name="Amoxicilina", status_context="started", explicit_end_date="20.03.2026",
            source_evidence_text="Amoxicilina 500mg, tratament pana la 20.03.2026.",
        )
        persist_medication_candidates(db, document=document, created_by_user_id=document.uploaded_by_user_id, candidates=[candidate])
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    medications = response.json()["medications"]
    row = next(m for m in medications if m["name"] == "Amoxicilina")
    assert row["stop_date"] == "2026-03-20"
    assert row["stop_date_basis"] == "explicit"


def test_medication_status_conflict_survives(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        active_claim = MedicationCandidate(
            source_segment_id="seg-a", canonical_key="medications", raw_text="BESREMI 250mcg continua.",
            raw_medication_name="BESREMI", status_context="continued", source_evidence_text="BESREMI 250mcg continua.",
        )
        stopped_claim = MedicationCandidate(
            source_segment_id="seg-b", canonical_key="medications", raw_text="BESREMI oprit.",
            raw_medication_name="BESREMI", status_context="stopped", source_evidence_text="BESREMI oprit.",
        )
        persist_medication_candidates(
            db, document=document, created_by_user_id=document.uploaded_by_user_id, candidates=[active_claim, stopped_claim]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    medications = response.json()["medications"]
    besremi_rows = [m for m in medications if m["name"] == "BESREMI"]
    assert len(besremi_rows) == 2
    assert all(row["is_uncertain"] for row in besremi_rows)
    assert {row["status"] for row in besremi_rows} == {"active", "stopped"}


# --- 14/15: missing referenced lab/medication does not crash the document -----


def test_missing_referenced_lab_does_not_crash_whole_document(patient_account):
    doc = StructuredClinicalDocument(
        parser_version="discharge-parser-phase4-5-v1",
        document_kind="discharge_summary",
        sections=[
            ClinicalSection(
                id="section-laboratory_results", canonical_key="laboratory_results", display_title="Labs", order=0,
                blocks=[LabReportReferenceBlock(lab_result_ids=[999999999])],
            ),
        ],
        derived_artifacts=[DerivedArtifactRef(artifact_type="lab_report", lab_result_ids=[999999999])],
    )
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"], note_body=serialize_structured_document(doc))
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    assert response.status_code == 200, response.text
    assert response.json()["labs"] == []  # no matching real LabResult row for this document — empty, not a crash


def test_missing_referenced_medication_does_not_crash_whole_document(patient_account):
    doc = StructuredClinicalDocument(
        parser_version="discharge-parser-phase4-5-v1",
        document_kind="discharge_summary",
        sections=[
            ClinicalSection(
                id="section-discharge_medications", canonical_key="discharge_medications", display_title="Meds", order=0,
                blocks=[MedicationListBlock(medication_ids=[999999999])],
            ),
        ],
    )
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"], note_body=serialize_structured_document(doc))
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(patient_account["account"]["token"]))
    assert response.status_code == 200, response.text
    assert response.json()["medications"] == []


# --- 16/17: authorization ------------------------------------------------------


def test_unauthenticated_user_cannot_access_reader_payload(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
    finally:
        db.close()

    response = client.get(f"/documents/{document_id}/clinical-reader")
    assert response.status_code == 401


def test_cross_patient_document_access_denied(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(
            db, patient_id=patient_account["patient_id"], note_body=None, uploaded_by_user_id=patient_account["user_id"]
        )
    finally:
        db.close()

    other = _signup("patient", cnp="6000101999972")
    try:
        response = client.get(f"/documents/{document_id}/clinical-reader", headers=_auth(other["token"]))
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(other["token"]))
