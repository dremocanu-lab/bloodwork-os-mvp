"""Pre-Phase-11 exact provenance session: tests for the new
`SourceEvidence.field_bboxes_json` column and its exposure through
`GET /source-evidence/{id}/view` — the fix for the reported coarse-
highlight bug (NEUT# covering neighboring PCT/NRBC#/NRBC% rows).

Same skip-gracefully-without-a-real-DB convention as
test_clinical_document_reader_api.py.
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

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"source-evidence-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"Source Evidence Test {role}",
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
    account = _signup("patient", cnp="6000101999981")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    yield {"account": account, "patient_id": profile["patient"]["id"], "user_id": account["user"]["id"]}
    client.delete("/my/account", headers=_auth(account["token"]))


def _make_document(db, *, patient_id: int) -> int:
    doc = models.Document(
        patient_id=patient_id,
        section="lab_results",
        filename="hematology.pdf",
        content_type="application/pdf",
        document_type="lab_report",
        report_name="Hematology Panel",
        created_at="2026-03-05T00:00:00Z",
        is_verified=False,
        public_id=f"brg-doc-se-{uuid.uuid4().hex[:8]}",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc.id


NEUT_HASH_FIELD_RECTS = [
    {"label": "test_name", "x": 0.10, "y": 0.542, "width": 0.13, "height": 0.012},
    {"label": "value", "x": 0.45, "y": 0.542, "width": 0.13, "height": 0.012},
    {"label": "unit", "x": 0.60, "y": 0.542, "width": 0.13, "height": 0.012},
    {"label": "reference_range", "x": 0.75, "y": 0.542, "width": 0.13, "height": 0.012},
]


def _make_evidence(db, *, document_id: int, field_bboxes=None, **overrides) -> int:
    kwargs = dict(
        document_id=document_id,
        page_number=1,
        bbox_x=0.45,
        bbox_y=0.542,
        bbox_width=0.13,
        bbox_height=0.012,
        row_bbox_x=0.10,
        row_bbox_y=0.5378,
        row_bbox_width=0.78,
        row_bbox_height=0.0204,
        source_text="NEUT# 2.73 10^3/uL [1.56-6.13]",
        extraction_confidence=0.95,
        provider="reducto",
        parser_version="reducto-v1",
        created_at="2026-03-05T00:00:00Z",
    )
    kwargs.update(overrides)
    if field_bboxes is not None:
        kwargs["field_bboxes_json"] = json.dumps(field_bboxes)
    evidence = models.SourceEvidence(**kwargs)
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence.id


def test_exact_lab_source_resolution_is_patient_authorized(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        evidence_id = _make_evidence(db, document_id=document_id, field_bboxes=NEUT_HASH_FIELD_RECTS)
    finally:
        db.close()

    response = client.get(
        f"/source-evidence/{evidence_id}/view", headers=_auth(patient_account["account"]["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_id"] == document_id
    assert body["precision"] == "exact_bbox"


def test_cross_patient_source_evidence_denied(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        evidence_id = _make_evidence(db, document_id=document_id, field_bboxes=NEUT_HASH_FIELD_RECTS)
    finally:
        db.close()

    other = _signup("patient", cnp="6000101999982")
    try:
        response = client.get(f"/source-evidence/{evidence_id}/view", headers=_auth(other["token"]))
        assert response.status_code == 403
    finally:
        client.delete("/my/account", headers=_auth(other["token"]))


def test_field_bboxes_belong_only_to_the_requested_evidence(patient_account):
    """A second row's field rects must never leak onto the first row's
    response — each SourceEvidence id resolves strictly to its own
    geometry, never a neighbor's."""
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        neut_id = _make_evidence(db, document_id=document_id, field_bboxes=NEUT_HASH_FIELD_RECTS)
        nrbc_pct_rects = [
            {"label": "test_name", "x": 0.10, "y": 0.528, "width": 0.13, "height": 0.012},
            {"label": "value", "x": 0.45, "y": 0.528, "width": 0.13, "height": 0.012},
        ]
        nrbc_pct_id = _make_evidence(
            db,
            document_id=document_id,
            field_bboxes=nrbc_pct_rects,
            bbox_x=0.45,
            bbox_y=0.528,
            source_text="NRBC% 0.10 %",
        )
    finally:
        db.close()

    token = patient_account["account"]["token"]
    neut_body = client.get(f"/source-evidence/{neut_id}/view", headers=_auth(token)).json()
    nrbc_body = client.get(f"/source-evidence/{nrbc_pct_id}/view", headers=_auth(token)).json()

    neut_ys = {rect["y"] for rect in neut_body["field_bboxes"]}
    nrbc_ys = {rect["y"] for rect in nrbc_body["field_bboxes"]}
    assert neut_ys == {0.542}
    assert nrbc_ys == {0.528}
    assert neut_ys.isdisjoint(nrbc_ys)


def test_multi_rect_geometry_survives_serialization(patient_account):
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        evidence_id = _make_evidence(db, document_id=document_id, field_bboxes=NEUT_HASH_FIELD_RECTS)
    finally:
        db.close()

    body = client.get(
        f"/source-evidence/{evidence_id}/view", headers=_auth(patient_account["account"]["token"])
    ).json()

    assert isinstance(body["field_bboxes"], list)
    assert len(body["field_bboxes"]) == 4
    assert [r["label"] for r in body["field_bboxes"]] == ["test_name", "value", "unit", "reference_range"]
    for original, returned in zip(NEUT_HASH_FIELD_RECTS, body["field_bboxes"]):
        assert returned["x"] == original["x"]
        assert returned["y"] == original["y"]
        assert returned["width"] == original["width"]
        assert returned["height"] == original["height"]


def test_old_coarse_source_evidence_remains_backwards_compatible(patient_account):
    """A row persisted before this session (no field_bboxes_json at all)
    must keep resolving exactly as it did before — row_bbox_*/bbox_* still
    present, field_bboxes simply absent, no error."""
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        evidence_id = _make_evidence(db, document_id=document_id, field_bboxes=None)
    finally:
        db.close()

    response = client.get(
        f"/source-evidence/{evidence_id}/view", headers=_auth(patient_account["account"]["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["field_bboxes"] is None
    assert body["row_bbox_x"] == 0.10
    assert body["bbox_x"] == 0.45
    assert body["precision"] == "exact_bbox"


def test_malformed_field_bboxes_json_fails_safe(patient_account):
    """A row with corrupted JSON in field_bboxes_json must degrade to
    `field_bboxes: null` (falling back to row_bbox_*/bbox_*) rather than
    500ing — provenance resolution must never crash the viewer."""
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        evidence_id = _make_evidence(db, document_id=document_id)
        evidence = db.get(models.SourceEvidence, evidence_id)
        evidence.field_bboxes_json = "{not valid json"
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/source-evidence/{evidence_id}/view", headers=_auth(patient_account["account"]["token"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["field_bboxes"] is None


def test_ambiguous_incomplete_field_rect_is_dropped_not_fabricated(patient_account):
    """A field rect entry missing a required coordinate must be dropped
    from the response, not filled in with a guessed value."""
    db = SessionLocal()
    try:
        document_id = _make_document(db, patient_id=patient_account["patient_id"])
        broken_rects = [
            {"label": "test_name", "x": 0.10, "y": 0.542, "width": 0.13, "height": 0.012},
            {"label": "value", "x": None, "y": 0.542, "width": 0.13, "height": 0.012},
        ]
        evidence_id = _make_evidence(db, document_id=document_id, field_bboxes=broken_rects)
    finally:
        db.close()

    body = client.get(
        f"/source-evidence/{evidence_id}/view", headers=_auth(patient_account["account"]["token"])
    ).json()
    assert body["field_bboxes"] is not None
    assert len(body["field_bboxes"]) == 1
    assert body["field_bboxes"][0]["label"] == "test_name"
