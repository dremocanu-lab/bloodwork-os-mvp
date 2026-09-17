"""Focused tests for embedded-lab canonical persistence — Clinical
Document Intelligence V3, Phase 6. Needs real DB connectivity (same
skip-gracefully convention as test_idor_regression.py/
test_ask_bragi_service.py) since this is the one module in the
clinical_document package that actually writes LabResult/SourceEvidence/
derived-Document rows.
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
from app.services import lab_resolver  # noqa: E402
from app.services.clinical_document.lab_extraction import (  # noqa: E402
    LabCandidate,
    extract_lab_candidates_from_segment,
)
from app.services.clinical_document.lab_grouping import group_lab_candidates  # noqa: E402
from app.services.clinical_document.lab_persistence import (  # noqa: E402
    DERIVED_ARTIFACT_KIND_LAB_REPORT,
    derive_lab_flag,
    persist_lab_candidates,
)
from app.services.clinical_document.segments import SourceSegment  # noqa: E402

from tests.test_clinical_document_lab_extraction import HEMATOLOGY_FIXTURE_TEXT  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-lab-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Clinical Doc Lab Test {role}",
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
    account = _signup("patient", cnp="6000101999981")
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
            created_at="2026-01-10T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-clindoc-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    yield {"account": account, "patient_id": patient_id, "document_id": document_id}

    client.delete("/my/account", headers=_auth(account["token"]))


def _hematology_segment() -> SourceSegment:
    return SourceSegment(
        segment_id="seg-000-laborator",
        index=0,
        raw_heading="EXAMENE DE LABORATOR",
        raw_text=HEMATOLOGY_FIXTURE_TEXT,
    )


def _persist_hematology_fixture(db, document_id: int):
    candidates = extract_lab_candidates_from_segment(_hematology_segment())
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    result = persist_lab_candidates(
        db, document=document, candidates=candidates, source_section_id="section-laboratory_results"
    )
    db.commit()
    return result


# --- Canonical resolver reuse -------------------------------------------------


def test_canonical_resolver_reuse_plt_and_aliases_resolve_like_the_shared_resolver():
    """Every alias in the Phase 6 required regression list must resolve
    through the SAME resolve_analyte() the rest of the app uses — not a
    discharge-only mapping."""
    for raw_name in ("PLT", "platelets", "Platelet Count", "trombocite"):
        via_shared_resolver = lab_resolver.resolve_analyte(raw_name)
        assert via_shared_resolver.resolved is True
        assert via_shared_resolver.canonical_name == "platelet_count"

    for raw_name in ("WBC", "leucocite", "leukocytes"):
        assert lab_resolver.resolve_analyte(raw_name).canonical_name == "wbc"

    for raw_name in ("HGB", "hemoglobin", "hemoglobina"):
        assert lab_resolver.resolve_analyte(raw_name).canonical_name == "hemoglobin"


def test_unresolved_analyte_remains_unresolved(discharge_document):
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
        candidate = LabCandidate(
            source_segment_id="seg-000-laborator",
            raw_test_name="ZZQFOO",
            raw_value="12.3",
            source_evidence_text="ZZQFOO 12.3 mg/dL",
        )
        result = persist_lab_candidates(db, document=document, candidates=[candidate])
        db.commit()
        assert len(result.observations) == 1
        assert result.observations[0].canonical_name is None
    finally:
        db.close()


# --- Flag precedence -----------------------------------------------------


def test_explicit_provider_flag_takes_precedence():
    candidate = LabCandidate(
        source_segment_id="s",
        raw_test_name="ALT",
        raw_value="56",
        parsed_value=56.0,
        reference_range="10-40",
        source_flag="H",
        source_section_status="normal",  # deliberately conflicting signal
        source_evidence_text="x",
    )
    assert derive_lab_flag(candidate) == "H"


def test_pathological_section_fallback_when_no_explicit_flag():
    candidate = LabCandidate(
        source_segment_id="s",
        raw_test_name="MCH",
        raw_value="31.5",
        parsed_value=31.5,
        reference_range="27-33",  # in-range numerically, but source PLACED it under pathological
        source_section_status="pathological",
        source_evidence_text="x",
    )
    assert derive_lab_flag(candidate) == "abnormal"


def test_numeric_range_fallback_when_no_explicit_flag_or_section():
    high = LabCandidate(
        source_segment_id="s", raw_test_name="X", raw_value="99", parsed_value=99.0,
        reference_range="10-40", source_evidence_text="x",
    )
    low = LabCandidate(
        source_segment_id="s", raw_test_name="X", raw_value="1", parsed_value=1.0,
        reference_range="10-40", source_evidence_text="x",
    )
    normal = LabCandidate(
        source_segment_id="s", raw_test_name="X", raw_value="20", parsed_value=20.0,
        reference_range="10-40", source_evidence_text="x",
    )
    assert derive_lab_flag(high) == "H"
    assert derive_lab_flag(low) == "L"
    assert derive_lab_flag(normal) is None


def test_no_signal_at_all_means_unknown_flag():
    candidate = LabCandidate(source_segment_id="s", raw_test_name="X", raw_value="20", source_evidence_text="x")
    assert derive_lab_flag(candidate) is None


# --- Persistence: LabResult rows attach to the AUTHORITATIVE parent ------


def test_lab_results_attach_to_the_parent_discharge_document_not_the_derived_artifact(discharge_document):
    db = SessionLocal()
    try:
        result = _persist_hematology_fixture(db, discharge_document["document_id"])
        plt_observation = next(o for o in result.observations if o.raw_test_name == "PLT")
        lab_row = db.query(models.LabResult).filter(models.LabResult.id == plt_observation.lab_result_id).first()
        assert lab_row.document_id == discharge_document["document_id"]
        assert lab_row.canonical_name == "platelet_count"
        assert lab_row.value == "349"
        assert lab_row.unit == "10^3/uL"
        assert lab_row.reference_range == "150-400"
        assert lab_row.observation_datetime == "2026-01-10"
    finally:
        db.close()


def test_source_segment_provenance_retained_on_lab_result_and_evidence(discharge_document):
    db = SessionLocal()
    try:
        result = _persist_hematology_fixture(db, discharge_document["document_id"])
        plt_observation = next(o for o in result.observations if o.raw_test_name == "PLT")
        lab_row = db.query(models.LabResult).filter(models.LabResult.id == plt_observation.lab_result_id).first()
        assert lab_row.source_section == "seg-000-laborator"

        evidence = (
            db.query(models.SourceEvidence)
            .filter(models.SourceEvidence.lab_result_id == lab_row.id)
            .first()
        )
        assert evidence is not None
        assert evidence.source_block_id == "seg-000-laborator"
        assert evidence.source_text == "PLT 349 10^3/uL (150-400)"
    finally:
        db.close()


def test_pdf_evidence_page_retained_when_the_source_segment_genuinely_has_one(discharge_document):
    """Today's discharge pipeline never populates SourceSegment.page
    (see segments.py), but lab_persistence.py must not hardcode that
    absence — if a future/real segment DOES carry a genuine page number,
    it must be threaded through to SourceEvidence.page_number, not
    silently dropped."""
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
        segment = SourceSegment(
            segment_id="seg-002-laborator",
            index=2,
            raw_heading="EXAMENE DE LABORATOR",
            raw_text="WBC 5.5 10^3/uL (4.0-10.0)",
            page=3,
        )
        candidates = extract_lab_candidates_from_segment(segment)
        assert candidates[0].source_page == 3

        result = persist_lab_candidates(db, document=document, candidates=candidates)
        db.commit()
        evidence = (
            db.query(models.SourceEvidence)
            .filter(models.SourceEvidence.lab_result_id == result.observations[0].lab_result_id)
            .first()
        )
        assert evidence.page_number == 3
    finally:
        db.close()


def test_non_pdf_evidence_never_fakes_geometry(discharge_document):
    """The discharge-embedded extraction path operates on already-
    extracted section text with no real PDF bbox — page_number/bbox must
    stay null, never a fabricated guess (contrast with real PDF evidence
    from reducto_extraction.py, which IS allowed to carry a real bbox)."""
    db = SessionLocal()
    try:
        result = _persist_hematology_fixture(db, discharge_document["document_id"])
        for observation in result.observations:
            evidence = (
                db.query(models.SourceEvidence)
                .filter(models.SourceEvidence.lab_result_id == observation.lab_result_id)
                .first()
            )
            assert evidence.page_number is None
            assert evidence.bbox_x is None
    finally:
        db.close()


# --- Conflict preservation -------------------------------------------------


def test_conflicting_same_analyte_rows_are_both_preserved(discharge_document):
    db = SessionLocal()
    try:
        result = _persist_hematology_fixture(db, discharge_document["document_id"])
        mch_observations = [o for o in result.observations if o.raw_test_name == "MCH"]
        assert len(mch_observations) == 2
        assert all(o.conflict for o in mch_observations)

        mch_rows = db.query(models.LabResult).filter(models.LabResult.id.in_([o.lab_result_id for o in mch_observations])).all()
        values = {row.value for row in mch_rows}
        assert values == {"29.0", "31.5"}
        assert all(row.verification_state == "conflict" for row in mch_rows)
        # Neither is "decided" as correct — both keep their own canonical
        # resolution independently, from the SAME shared resolver.
        assert all(row.canonical_name == "mch" for row in mch_rows)
    finally:
        db.close()


# --- Grouping / derived artifacts -----------------------------------------


def test_one_derived_artifact_per_coherent_group_not_per_analyte(discharge_document):
    db = SessionLocal()
    try:
        result = _persist_hematology_fixture(db, discharge_document["document_id"])
        # The whole fixture shares one request/date -> one coherent group.
        assert len(result.groups) == 1
        assert len(result.observations) > 5  # many analytes, still one artifact

        derived_docs = (
            db.query(models.Document)
            .filter(
                models.Document.parent_document_id == discharge_document["document_id"],
                models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
            )
            .all()
        )
        assert len(derived_docs) == 1
        derived = derived_docs[0]
        assert derived.patient_id == discharge_document["patient_id"]
        assert "Structured laboratory results extracted from" in derived.report_name
    finally:
        db.close()


def test_separate_request_date_groups_produce_separate_derived_artifacts(discharge_document):
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == discharge_document["document_id"]).first()
        candidates = [
            LabCandidate(
                source_segment_id="seg-000-laborator", raw_test_name="WBC", raw_value="5.5",
                request_code="LAB-1", observation_date="10.01.2026", source_evidence_text="WBC 5.5",
            ),
            LabCandidate(
                source_segment_id="seg-000-laborator", raw_test_name="WBC", raw_value="6.1",
                request_code="LAB-2", observation_date="15.01.2026", source_evidence_text="WBC 6.1",
            ),
        ]
        result = persist_lab_candidates(db, document=document, candidates=candidates)
        db.commit()
        assert len(result.groups) == 2
        assert len({g.derived_document_id for g in result.groups}) == 2
    finally:
        db.close()


# --- Idempotency ------------------------------------------------------------


def test_repeated_identical_extraction_does_not_duplicate_lab_results(discharge_document):
    db = SessionLocal()
    try:
        first = _persist_hematology_fixture(db, discharge_document["document_id"])
        second = _persist_hematology_fixture(db, discharge_document["document_id"])

        assert all(o.was_new for o in first.observations)
        assert all(not o.was_new for o in second.observations)

        lab_count = (
            db.query(models.LabResult)
            .filter(models.LabResult.document_id == discharge_document["document_id"])
            .count()
        )
        assert lab_count == len(first.observations)
    finally:
        db.close()


def test_repeated_identical_extraction_does_not_duplicate_the_derived_artifact(discharge_document):
    db = SessionLocal()
    try:
        _persist_hematology_fixture(db, discharge_document["document_id"])
        _persist_hematology_fixture(db, discharge_document["document_id"])

        derived_count = (
            db.query(models.Document)
            .filter(
                models.Document.parent_document_id == discharge_document["document_id"],
                models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
            )
            .count()
        )
        assert derived_count == 1
    finally:
        db.close()


def test_repeated_identical_extraction_does_not_duplicate_source_evidence(discharge_document):
    db = SessionLocal()
    try:
        _persist_hematology_fixture(db, discharge_document["document_id"])
        _persist_hematology_fixture(db, discharge_document["document_id"])

        evidence_count = (
            db.query(models.SourceEvidence)
            .filter(models.SourceEvidence.document_id == discharge_document["document_id"])
            .count()
        )
        lab_count = (
            db.query(models.LabResult)
            .filter(models.LabResult.document_id == discharge_document["document_id"])
            .count()
        )
        assert evidence_count == lab_count
    finally:
        db.close()


# --- Deletion semantics ------------------------------------------------------


def test_deleting_parent_discharge_removes_derived_artifact_and_its_lab_results(discharge_document):
    db = SessionLocal()
    try:
        _persist_hematology_fixture(db, discharge_document["document_id"])
        parent_id = discharge_document["document_id"]

        derived_ids = [
            row.id
            for row in db.query(models.Document.id).filter(
                models.Document.parent_document_id == parent_id,
                models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
            )
        ]
        assert derived_ids

        lab_result_ids = [
            row.id for row in db.query(models.LabResult.id).filter(models.LabResult.document_id == parent_id)
        ]
        assert lab_result_ids

        # Mirrors the exact cascade logic in DELETE /documents/{id} (see
        # app/api/routers/documents.py) — a derived artifact must be
        # hard-deleted, never orphaned via parent_document_id's
        # ondelete="SET NULL" (that behavior stays reserved for ordinary
        # Reducto Split children).
        parent = db.query(models.Document).filter(models.Document.id == parent_id).first()
        db.query(models.Document).filter(
            models.Document.parent_document_id == parent_id,
            models.Document.derived_artifact_kind.isnot(None),
        ).delete(synchronize_session=False)
        db.delete(parent)
        db.commit()

        assert db.query(models.Document).filter(models.Document.id.in_(derived_ids)).count() == 0
        assert db.query(models.LabResult).filter(models.LabResult.id.in_(lab_result_ids)).count() == 0
        assert (
            db.query(models.SourceEvidence)
            .filter(models.SourceEvidence.lab_result_id.in_(lab_result_ids))
            .count()
            == 0
        )
    finally:
        db.close()


def test_delete_document_route_removes_derived_artifact_end_to_end(discharge_document):
    """Same proof as the ORM-level test above, but through the REAL
    `DELETE /documents/{id}` route (app/api/routers/documents.py) — not
    just a mirror of its cascade logic."""
    db = SessionLocal()
    try:
        _persist_hematology_fixture(db, discharge_document["document_id"])
        parent_id = discharge_document["document_id"]
        derived_ids = [
            row.id
            for row in db.query(models.Document.id).filter(
                models.Document.parent_document_id == parent_id,
                models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
            )
        ]
        assert derived_ids
    finally:
        db.close()

    response = client.delete(f"/documents/{parent_id}", headers=_auth(discharge_document["account"]["token"]))
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        assert db.query(models.Document).filter(models.Document.id == parent_id).count() == 0
        assert db.query(models.Document).filter(models.Document.id.in_(derived_ids)).count() == 0
    finally:
        db.close()
