"""Source Geometry + Clinical Table Intelligence V3 — end-to-end
reprocessing tests against the REAL synthetic PDF fixture (Part 56):
table routing into canonical LabResult/PatientMedication rows with real
cell geometry, and per-narrative-fact SourceEvidence upgraded from
page_only to real block bbox precision. Needs real DB connectivity (same
skip-gracefully convention as the other clinical_document persistence
test files).
"""

import json
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — this file needs real DB connectivity.", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.reprocessing import reprocess_discharge_document  # noqa: E402
from tests.fixtures.clinical_reader_v3_pdf_fixture import (  # noqa: E402
    BCR_ABL_TEXT,
    BONE_MARROW_TEXT,
    JAK2_TEXT,
    ULTRASOUND_TEXT,
    build_synthetic_discharge_v3_fixture,
)

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-reproc-v3-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {"email": email, "full_name": f"Reprocess V3 Test {role}", "password": "TestPass123!", "role": role, **extra}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _fake_call_model(_input):
    return {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }


@pytest.fixture
def v3_discharge_document():
    _, legacy_payload = build_synthetic_discharge_v3_fixture()

    account = _signup("patient", cnp="6000101999985")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="discharge_v3.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary V3 Fixture",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-reproc-v3-{uuid.uuid4().hex[:8]}",
            note_body=json.dumps(legacy_payload),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    yield {"account": account, "patient_id": patient_id, "document_id": document_id}

    client.delete("/my/account", headers=_auth(account["token"]))


def test_table_routing_creates_lab_and_medication_rows_with_real_cell_geometry(v3_discharge_document, monkeypatch):
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == v3_discharge_document["document_id"]).first()
        result = reprocess_discharge_document(db, document=document, actor_user_id=v3_discharge_document["account"]["user"]["id"])

        assert result.lab_results_created >= 3  # ALT + 2 conflicting HGB rows
        assert result.medications_created >= 1  # at least one of the medication/prescription table rows

        labs = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        alt = next(l for l in labs if l.raw_test_name.strip().upper() == "ALT")
        alt_evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.lab_result_id == alt.id).first()
        assert alt_evidence is not None
        assert alt_evidence.bbox_x is not None  # exact_bbox precision, not page_only
        assert alt_evidence.field_bboxes_json is not None
        field_bboxes = json.loads(alt_evidence.field_bboxes_json)
        assert len(field_bboxes) == 4  # name/value/unit/reference_range cells all real

        hgb_rows = [l for l in labs if l.raw_test_name.strip().upper() == "HGB"]
        assert len(hgb_rows) == 2  # conflicting rows preserved, never silently deduped
        assert {row.value for row in hgb_rows} == {"9.8", "11.2"}

        meds = db.query(models.PatientMedication).filter(models.PatientMedication.source_document_id == document.id).all()
        med_names = {m.name for m in meds}
        # The table's own placeholder pointer text ("Vezi medicatia
        # structurata de mai jos.") must never itself become a fabricated
        # medication candidate — a real bug this fixture caught.
        assert not any(name.lower().startswith("vezi ") for name in med_names)

        hidroxiuree = next(m for m in meds if m.name == "Hidroxiuree")
        hidroxiuree_evidence = db.query(models.SourceEvidence).filter(models.SourceEvidence.medication_id == hidroxiuree.id).first()
        assert hidroxiuree_evidence is not None
        assert hidroxiuree_evidence.bbox_x is not None  # exact_bbox precision, not page_only
        assert hidroxiuree_evidence.field_bboxes_json is not None
        med_field_bboxes = json.loads(hidroxiuree_evidence.field_bboxes_json)
        assert len(med_field_bboxes) >= 2  # name + dose cells at minimum, all real
    finally:
        db.close()


def test_narrative_facts_on_the_same_page_resolve_to_distinct_evidence(v3_discharge_document, monkeypatch):
    """The core Part 14/58 requirement, verified through the REAL
    reprocessing pipeline (not just geometry_alignment directly, as
    test_clinical_reader_v3_pdf_fixture.py already covers): JAK2/bone
    marrow/ultrasound/BCR-ABL each land on a DIFFERENT SourceEvidence
    row with its own real bbox — never one shared page-4 evidence
    blob."""
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == v3_discharge_document["document_id"]).first()
        reprocess_discharge_document(db, document=document, actor_user_id=v3_discharge_document["account"]["user"]["id"])

        evidence_rows = db.query(models.SourceEvidence).filter(models.SourceEvidence.document_id == document.id).all()
        by_text = {row.source_text: row for row in evidence_rows if row.source_text}

        for expected_text in (ULTRASOUND_TEXT, JAK2_TEXT, BONE_MARROW_TEXT, BCR_ABL_TEXT):
            assert expected_text in by_text, f"missing evidence for: {expected_text[:40]}..."
            assert by_text[expected_text].bbox_x is not None, f"no real bbox for: {expected_text[:40]}..."

        distinct_ids = {by_text[t].id for t in (ULTRASOUND_TEXT, JAK2_TEXT, BONE_MARROW_TEXT, BCR_ABL_TEXT)}
        assert len(distinct_ids) == 4  # four genuinely distinct evidence rows

        distinct_bboxes = {
            (row.bbox_x, row.bbox_y, row.bbox_width, row.bbox_height)
            for row in (by_text[t] for t in (ULTRASOUND_TEXT, JAK2_TEXT, BONE_MARROW_TEXT, BCR_ABL_TEXT))
        }
        assert len(distinct_bboxes) == 4  # and four genuinely distinct rectangles, not the same one repeated
    finally:
        db.close()


def test_empty_template_tables_never_produce_canonical_rows(v3_discharge_document, monkeypatch):
    """Page 8's blank TRATAMENT/INVESTIGATII templates must never turn
    into a fabricated medication or lab row (Part 20/61)."""
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == v3_discharge_document["document_id"]).first()
        reprocess_discharge_document(db, document=document, actor_user_id=v3_discharge_document["account"]["user"]["id"])

        meds = db.query(models.PatientMedication).filter(models.PatientMedication.source_document_id == document.id).all()
        for med in meds:
            assert med.name.strip().upper() not in {"PRODUS", "EKG", "ECO", "RX", "ALTELE"}
    finally:
        db.close()


def test_reprocessing_v3_fixture_twice_does_not_duplicate_or_downgrade_evidence(v3_discharge_document, monkeypatch):
    """Idempotency + evidence-upgrade-never-regresses (Part 44/56):
    running reprocessing twice against the same real-geometry payload
    must not duplicate LabResult/SourceEvidence rows, and every bbox
    achieved on the first pass must survive the second pass unchanged."""
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == v3_discharge_document["document_id"]).first()

        first = reprocess_discharge_document(db, document=document, actor_user_id=v3_discharge_document["account"]["user"]["id"])
        labs_after_first = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        evidence_after_first = {
            row.id: (row.bbox_x, row.bbox_y, row.bbox_width, row.bbox_height)
            for row in db.query(models.SourceEvidence).filter(models.SourceEvidence.document_id == document.id).all()
        }

        second = reprocess_discharge_document(db, document=document, actor_user_id=v3_discharge_document["account"]["user"]["id"])
        assert second.lab_results_created == 0
        assert second.lab_results_reused == first.lab_results_created

        labs_after_second = db.query(models.LabResult).filter(models.LabResult.document_id == document.id).all()
        assert len(labs_after_second) == len(labs_after_first)  # no duplicates

        evidence_after_second = {
            row.id: (row.bbox_x, row.bbox_y, row.bbox_width, row.bbox_height)
            for row in db.query(models.SourceEvidence).filter(models.SourceEvidence.document_id == document.id).all()
        }
        assert evidence_after_second == evidence_after_first  # no id churn, no bbox regression
    finally:
        db.close()
