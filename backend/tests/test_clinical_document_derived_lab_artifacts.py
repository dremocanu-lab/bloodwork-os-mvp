"""Focused tests for derived lab artifacts appearing as real, independently
openable Documents entries — Clinical Document Intelligence V3, Phase 9.

Phase 6 already proved persistence/idempotency/deletion at the ORM+
lab_persistence.py level (test_clinical_document_lab_persistence.py). This
file proves the Phase 9 layer on top of that: the API surfaces a derived
artifact never fakes its clinical data — it is a real, independently
openable Document row whose card/detail views are computed from the SAME
canonical LabResult rows Phase 6 created on the parent, never a copy.
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
from app.services.clinical_document.lab_extraction import extract_lab_candidates_from_segment  # noqa: E402
from app.services.clinical_document.lab_persistence import (  # noqa: E402
    DERIVED_ARTIFACT_KIND_LAB_REPORT,
    persist_lab_candidates,
)
from app.services.clinical_document.segments import SourceSegment  # noqa: E402

from tests.test_clinical_document_lab_extraction import HEMATOLOGY_FIXTURE_TEXT  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-derived-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Clinical Doc Derived Test {role}",
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
def discharge_with_derived_lab_report():
    account = _signup("patient", cnp="6000101999982")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="discharge.pdf",
            content_type="application/pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary — Fundeni",
            created_at="2026-03-04T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-clindoc-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        parent_document_id = doc.id

        segment = SourceSegment(
            segment_id="seg-000-laborator",
            index=0,
            raw_heading="EXAMENE DE LABORATOR",
            raw_text=HEMATOLOGY_FIXTURE_TEXT,
        )
        candidates = extract_lab_candidates_from_segment(segment)
        result = persist_lab_candidates(
            db, document=doc, candidates=candidates, source_section_id="section-laboratory_results"
        )
        db.commit()

        derived = (
            db.query(models.Document)
            .filter(
                models.Document.parent_document_id == parent_document_id,
                models.Document.derived_artifact_kind == DERIVED_ARTIFACT_KIND_LAB_REPORT,
            )
            .first()
        )
        derived_document_id = derived.id
        lab_result_ids = [o.lab_result_id for o in result.observations]
    finally:
        db.close()

    yield {
        "account": account,
        "patient_id": patient_id,
        "parent_document_id": parent_document_id,
        "derived_document_id": derived_document_id,
        "lab_result_ids": lab_result_ids,
    }

    client.delete("/my/account", headers=_auth(account["token"]))


# --- Document list: derived artifact appears as a real card -----------------


def test_derived_artifact_appears_in_my_profile_document_listing(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    assert response.status_code == 200
    cards = response.json()["sections"]["bloodwork"]
    ids = {card["id"] for card in cards}
    assert fixture["derived_document_id"] in ids


def test_derived_artifact_card_is_marked_derived_with_kind_lab_report(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["bloodwork"]
    derived_card = next(c for c in cards if c["id"] == fixture["derived_document_id"])
    assert derived_card["derived_artifact_kind"] == "lab_report"


def test_derived_artifact_card_parent_document_id_points_at_real_parent(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["bloodwork"]
    derived_card = next(c for c in cards if c["id"] == fixture["derived_document_id"])
    assert derived_card["parent_document_id"] == fixture["parent_document_id"]


def test_derived_artifact_card_carries_resolved_parent_metadata(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["bloodwork"]
    derived_card = next(c for c in cards if c["id"] == fixture["derived_document_id"])
    assert derived_card["parent_document"] is not None
    assert derived_card["parent_document"]["id"] == fixture["parent_document_id"]
    assert derived_card["parent_document"]["report_name"] == "Discharge Summary — Fundeni"


def test_ordinary_document_card_has_no_derived_artifact_kind_or_parent(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["discharge_summary"]
    parent_card = next(c for c in cards if c["id"] == fixture["parent_document_id"])
    assert parent_card["derived_artifact_kind"] is None
    assert parent_card["parent_document"] is None


def test_reducto_split_child_is_not_mislabeled_as_a_derived_artifact(discharge_with_derived_lab_report):
    """A Reducto Split child ALSO uses parent_document_id — the marker that
    distinguishes a Phase 6 derived artifact is derived_artifact_kind, which
    a plain split child must never have set."""
    fixture = discharge_with_derived_lab_report
    db = SessionLocal()
    try:
        split_child = models.Document(
            patient_id=fixture["patient_id"],
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            parent_document_id=fixture["parent_document_id"],
            derived_artifact_kind=None,
            page_range_start=1,
            page_range_end=3,
            created_at="2026-03-04T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-split-{uuid.uuid4().hex[:8]}",
        )
        db.add(split_child)
        db.commit()
        db.refresh(split_child)
        split_child_id = split_child.id
    finally:
        db.close()

    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["discharge_summary"]
    split_card = next(c for c in cards if c["id"] == split_child_id)
    assert split_card["parent_document_id"] == fixture["parent_document_id"]
    assert split_card["derived_artifact_kind"] is None
    assert split_card["parent_document"] is None


def test_multiple_derived_artifacts_remain_distinct_in_the_listing(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == fixture["parent_document_id"]).first()
        from app.services.clinical_document.lab_extraction import LabCandidate

        second_group_candidates = [
            LabCandidate(
                source_segment_id="seg-001-laborator",
                raw_test_name="WBC",
                raw_value="6.1",
                request_code="LAB-SECOND",
                observation_date="20.01.2026",
                source_evidence_text="WBC 6.1",
            )
        ]
        persist_lab_candidates(db, document=document, candidates=second_group_candidates)
        db.commit()
    finally:
        db.close()

    response = client.get("/my/profile", headers=_auth(fixture["account"]["token"]))
    cards = response.json()["sections"]["bloodwork"]
    derived_cards = [c for c in cards if c["derived_artifact_kind"] == "lab_report"]
    assert len(derived_cards) == 2
    assert len({c["id"] for c in derived_cards}) == 2


# --- Standalone reader detail: canonical rows, never a copy ------------------


def test_derived_artifact_clinical_reader_returns_canonical_lab_result_rows(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.get(
        f"/documents/{fixture['derived_document_id']}/clinical-reader",
        headers=_auth(fixture["account"]["token"]),
    )
    assert response.status_code == 200
    payload = response.json()
    returned_ids = {lab["id"] for lab in payload["labs"]}
    assert returned_ids == set(fixture["lab_result_ids"])
    assert payload["document"]["derived_artifact_kind"] == "lab_report"
    assert payload["derived_artifact"]["parent_document_id"] == fixture["parent_document_id"]


def test_derived_artifact_detail_labs_match_parent_lab_result_values_exactly(discharge_with_derived_lab_report):
    """Never a copy: every value returned for the derived artifact must be
    read live from the same LabResult rows the parent document owns, not a
    frozen snapshot inside the derived artifact's own note_body."""
    fixture = discharge_with_derived_lab_report
    db = SessionLocal()
    try:
        canonical_rows = {
            row.id: row
            for row in db.query(models.LabResult).filter(models.LabResult.id.in_(fixture["lab_result_ids"]))
        }
    finally:
        db.close()

    response = client.get(
        f"/documents/{fixture['derived_document_id']}/clinical-reader",
        headers=_auth(fixture["account"]["token"]),
    )
    for lab in response.json()["labs"]:
        canonical = canonical_rows[lab["id"]]
        assert lab["value"] == canonical.value
        assert lab["flag"] == canonical.flag
        assert lab["canonical_name"] == canonical.canonical_name


def test_derived_artifact_with_no_resolvable_lab_results_does_not_crash():
    """A derived artifact whose pointer references LabResult ids that no
    longer exist (or an empty list) must degrade to an empty labs array,
    never a 500."""
    account = _signup("patient", cnp="6000101999983")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        parent = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="discharge.pdf",
            document_type="discharge_summary",
            report_name="Discharge Summary",
            created_at="2026-03-04T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        db.add(parent)
        db.commit()
        db.refresh(parent)

        import json as _json

        derived = models.Document(
            patient_id=patient_id,
            parent_document_id=parent.id,
            derived_artifact_kind=DERIVED_ARTIFACT_KIND_LAB_REPORT,
            section="bloodwork",
            document_type="laboratory_results",
            filename=parent.filename,
            report_name="Structured laboratory results extracted from Discharge Summary",
            note_body=_json.dumps(
                {
                    "document_type": "derived_lab_report",
                    "artifact_type": DERIVED_ARTIFACT_KIND_LAB_REPORT,
                    "group_key": "missing-group",
                    "source_section_id": None,
                    "lab_result_ids": [999999999],
                }
            ),
            created_at="2026-03-04T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        db.add(derived)
        db.commit()
        db.refresh(derived)
        derived_id = derived.id
    finally:
        db.close()

    try:
        response = client.get(f"/documents/{derived_id}/clinical-reader", headers=_auth(account["token"]))
        assert response.status_code == 200
        assert response.json()["labs"] == []
    finally:
        client.delete("/my/account", headers=_auth(account["token"]))


def test_derived_artifact_with_missing_parent_handled_safely():
    """If a derived artifact's parent_document_id somehow points at nothing
    (should not happen via the app's own delete cascade, but must not crash
    if it ever does), the detail endpoint still returns 200 with null parent
    fields instead of a 500."""
    account = _signup("patient", cnp="6000101999984")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        import json as _json

        derived = models.Document(
            patient_id=patient_id,
            parent_document_id=None,
            derived_artifact_kind=DERIVED_ARTIFACT_KIND_LAB_REPORT,
            section="bloodwork",
            document_type="laboratory_results",
            filename="orphan.pdf",
            report_name="Structured laboratory results",
            note_body=_json.dumps(
                {
                    "document_type": "derived_lab_report",
                    "artifact_type": DERIVED_ARTIFACT_KIND_LAB_REPORT,
                    "group_key": "orphan-group",
                    "source_section_id": None,
                    "lab_result_ids": [],
                }
            ),
            created_at="2026-03-04T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        db.add(derived)
        db.commit()
        db.refresh(derived)
        derived_id = derived.id
    finally:
        db.close()

    try:
        response = client.get(f"/documents/{derived_id}/clinical-reader", headers=_auth(account["token"]))
        assert response.status_code == 200
        payload = response.json()
        assert payload["derived_artifact"]["parent_document_id"] is None
        assert payload["derived_artifact"]["parent_report_name"] is None

        list_response = client.get("/my/profile", headers=_auth(account["token"]))
        card = next(
            c for c in list_response.json()["sections"]["bloodwork"] if c["id"] == derived_id
        )
        assert card["parent_document"] is None
    finally:
        client.delete("/my/account", headers=_auth(account["token"]))


# --- Authorization: identical to parent's own access rule --------------------


def test_unauthorized_cross_patient_access_to_derived_artifact_is_denied(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    other_account = _signup("patient", cnp="6000101999985")
    try:
        response = client.get(
            f"/documents/{fixture['derived_document_id']}/clinical-reader",
            headers=_auth(other_account["token"]),
        )
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(other_account["token"]))


def test_doctor_with_patient_access_can_see_derived_artifact_via_parent_policy(discharge_with_derived_lab_report):
    """access.py's can_access_patient checks the derived artifact's OWN
    patient_id (inherited from its parent at creation) — no chase through
    parent_document_id needed; this proves that already works end-to-end."""
    fixture = discharge_with_derived_lab_report
    doctor = _signup("doctor")
    try:
        db = SessionLocal()
        try:
            db.add(
                models.DoctorPatientAccess(
                    doctor_user_id=doctor["user"]["id"],
                    patient_id=fixture["patient_id"],
                    granted_by_user_id=fixture["account"]["user"]["id"],
                    granted_at="2026-01-01T00:00:00+00:00",
                    is_active=1,
                )
            )
            db.commit()
        finally:
            db.close()

        response = client.get(
            f"/documents/{fixture['derived_document_id']}/clinical-reader",
            headers=_auth(doctor["token"]),
        )
        assert response.status_code == 200

        list_response = client.get(
            f"/patients/{fixture['patient_id']}/documents", headers=_auth(doctor["token"])
        )
        assert list_response.status_code == 200
        ids = {d["id"] for d in list_response.json()["documents"]}
        assert fixture["derived_document_id"] in ids
    finally:
        pass


# --- Deletion semantics -------------------------------------------------------


def test_derived_artifact_cannot_be_deleted_directly(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.delete(
        f"/documents/{fixture['derived_document_id']}", headers=_auth(fixture["account"]["token"])
    )
    assert response.status_code == 400

    db = SessionLocal()
    try:
        assert db.query(models.Document).filter(models.Document.id == fixture["derived_document_id"]).count() == 1
    finally:
        db.close()


def test_deleting_parent_still_cleanly_removes_derived_artifact_via_the_route(discharge_with_derived_lab_report):
    fixture = discharge_with_derived_lab_report
    response = client.delete(
        f"/documents/{fixture['parent_document_id']}", headers=_auth(fixture["account"]["token"])
    )
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(models.Document).filter(models.Document.id == fixture["derived_document_id"]).count() == 0
    finally:
        db.close()
