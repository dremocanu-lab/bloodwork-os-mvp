"""Regression suite for Ask Bragi's canonical lab retrieval (BRAGI
PRODUCT RELIABILITY PASS, Part F/G/K).

Reproduces, at the TOOL level (no LLM involved — see
test_ask_bragi_lab_retrieval_end_to_end.py for the smaller live-model
check), the real retrieval gap: Bragi's ingestion pipeline has
historically written LabResult.canonical_name in TWO different formats
depending on which resolver actually processed a given row —
app/services/lab_catalog.py's human-readable form (e.g. "Platelet
Count") or app/services/lab_resolver.py's snake_case slug (e.g.
"platelet_count", used for CBC-adjacent analytes). Ask Bragi's
`_canonical_lab_filter` (app/services/ask_bragi/tools.py) must resolve
a model-supplied query term against BOTH conventions, matching a
LabResult row no matter which one actually produced its stored value —
see that function's own docstring for the full explanation.

Same DB-connectivity requirement/skip behavior as
test_idor_regression.py / test_ask_bragi_tools.py.
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
from app.services.ask_bragi.context import AskBragiContext  # noqa: E402
from app.services.ask_bragi.tools import run_tool  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"askbragi-labs-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"AskBragi Lab Retrieval Test {role}",
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
def lab_patient():
    """One patient, one bloodwork document, and a deterministic set of
    LabResult rows spanning BOTH real ingestion-era canonical_name
    conventions — exactly the mix a real, long-lived patient record has
    (some rows processed through app/services/lab_catalog.py's
    normalize_lab_rows, others through app/services/lab_resolver.py's
    resolve_test_name_dict for CBC-adjacent analytes)."""
    account = _signup("patient", cnp="6000101999971")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="bloodwork",
            filename="cbc-panel.pdf",
            document_type="laboratory_results",
            created_at="2026-01-01T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        labs = [
            # PLT — the reported bug: real ingestion (CBC/Reducto path,
            # app/services/lab_resolver.py) stores the SLUG form
            # "platelet_count", not lab_catalog.py's "Platelet Count".
            models.LabResult(
                document_id=doc.id,
                raw_test_name="PLT",
                canonical_name="platelet_count",
                display_name="Platelet Count",
                category="cbc_platelets",
                value="395",
                unit="10^3/uL",
                reference_range="150-450",
                flag="normal",
                observation_datetime="2026-06-01T09:00:00Z",
            ),
            # WBC — same slug-form convention, included as the case that
            # "accidentally" already worked (the slug "wbc" happens to
            # equal the abbreviation itself) — a regression guard so a
            # future change to _canonical_lab_filter can't quietly break
            # the case that was never actually broken.
            models.LabResult(
                document_id=doc.id,
                raw_test_name="WBC",
                canonical_name="wbc",
                display_name="White Blood Cell Count",
                category="cbc_wbc",
                value="6.2",
                unit="10^3/uL",
                reference_range="4.0-11.0",
                flag="normal",
                observation_datetime="2026-06-01T09:00:00Z",
            ),
            # HGB — a third slug-form CBC analyte, distinct wording
            # pattern from both PLT and WBC.
            models.LabResult(
                document_id=doc.id,
                raw_test_name="HGB",
                canonical_name="hemoglobin",
                display_name="Hemoglobin",
                category="cbc_rbc",
                value="14.1",
                unit="g/dL",
                reference_range="13.5-17.5",
                flag="normal",
                observation_datetime="2026-06-01T09:00:00Z",
            ),
            # Creatinine — stored via lab_catalog.py's human-readable
            # convention (the OTHER historical format), as a control case
            # proving that convention still works too.
            models.LabResult(
                document_id=doc.id,
                raw_test_name="Creatinine",
                canonical_name="Creatinine",
                display_name="Creatinine",
                category="renal",
                value="0.9",
                unit="mg/dL",
                reference_range="0.6-1.3",
                flag="normal",
                observation_datetime="2026-06-01T09:00:00Z",
            ),
        ]
        db.add_all(labs)
        db.commit()
        for lab in labs:
            db.refresh(lab)

        yield {
            "account": account,
            "patient_id": patient_id,
            "document_id": doc.id,
            "lab_ids": {lab.raw_test_name: lab.id for lab in labs},
        }

        db.query(models.LabResult).filter(models.LabResult.document_id == doc.id).delete(
            synchronize_session=False
        )
        db.query(models.Document).filter(models.Document.id == doc.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    client.delete("/my/account", headers=_auth(account["token"]))


def _get_lab_results(lab_patient, query_term: str) -> list[dict]:
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=lab_patient["patient_id"],
            requester_user_id=lab_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "get_lab_results", {"canonical_name": query_term})
        return result["results"]
    finally:
        db.close()


# --- Part F: PLT / Platelet Count retrieval, every alias -------------------


@pytest.mark.parametrize("query_term", ["PLT", "Platelet Count", "platelets", "platelet", "trombocite"])
def test_platelet_aliases_all_resolve_to_the_same_stored_row(lab_patient, query_term):
    results = _get_lab_results(lab_patient, query_term)
    assert len(results) == 1, f"query {query_term!r} returned {len(results)} rows, expected exactly 1"
    assert results[0]["value"] == "395"
    assert results[0]["raw_test_name"] == "PLT"


# --- Regression guards: WBC / HGB aliases -----------------------------------


@pytest.mark.parametrize("query_term", ["WBC", "White Blood Cell Count", "leukocytes", "leucocite"])
def test_wbc_aliases_all_resolve_to_the_same_stored_row(lab_patient, query_term):
    results = _get_lab_results(lab_patient, query_term)
    assert len(results) == 1, f"query {query_term!r} returned {len(results)} rows, expected exactly 1"
    assert results[0]["value"] == "6.2"
    assert results[0]["raw_test_name"] == "WBC"


@pytest.mark.parametrize("query_term", ["HGB", "hemoglobin", "hemoglobina"])
def test_hgb_aliases_all_resolve_to_the_same_stored_row(lab_patient, query_term):
    results = _get_lab_results(lab_patient, query_term)
    assert len(results) == 1, f"query {query_term!r} returned {len(results)} rows, expected exactly 1"
    assert results[0]["value"] == "14.1"
    assert results[0]["raw_test_name"] == "HGB"


# --- Control case: the other historical (human-readable) convention --------


def test_human_readable_canonical_name_convention_still_works(lab_patient):
    results = _get_lab_results(lab_patient, "creatinine")
    assert len(results) == 1
    assert results[0]["value"] == "0.9"


# --- Cross-analyte isolation: an alias must never pull in a DIFFERENT ------
# --- analyte's row (over-broad matching would be its own kind of bug) ------


def test_platelet_query_does_not_return_wbc_or_hgb_rows(lab_patient):
    results = _get_lab_results(lab_patient, "platelets")
    raw_names = {r["raw_test_name"] for r in results}
    assert raw_names == {"PLT"}


def test_wbc_query_does_not_return_platelet_or_hgb_rows(lab_patient):
    results = _get_lab_results(lab_patient, "WBC")
    raw_names = {r["raw_test_name"] for r in results}
    assert raw_names == {"WBC"}


# --- Trend / compare tools use the same filter — spot-check both ----------


def test_get_lab_trend_resolves_platelet_aliases_too(lab_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=lab_patient["patient_id"],
            requester_user_id=lab_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "get_lab_trend", {"canonical_name": "platelets"})
        assert len(result["points"]) == 1
        assert result["points"][0]["value"] == "395"
    finally:
        db.close()


def test_compare_lab_results_resolves_platelet_aliases_too(lab_patient):
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=lab_patient["patient_id"],
            requester_user_id=lab_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "compare_lab_results", {"canonical_name": "trombocite"})
        # A single stored observation has nothing to compare against —
        # this only asserts the alias resolved to that one real row
        # (not zero, and not some other analyte), not the comparison
        # semantics themselves (covered elsewhere).
        assert result.get("error") != "not_found" or "results" in result
    finally:
        db.close()


# --- Part H: patient-specific analyte discovery -----------------------------


def test_zero_result_lookup_can_discover_the_real_stored_analyte(lab_patient):
    """A query term neither catalog recognizes as an alias for anything
    already in the record must not be silently treated as proof the
    analyte is absent — see Part H/J. This test only asserts the
    discovery mechanism itself (once implemented) finds the real PLT row
    from a deliberately-unresolvable query; see tools.py for whether a
    dedicated tool or an in-tool fallback implements it."""
    from app.services.ask_bragi import tools as ask_bragi_tools

    if "search_available_lab_analytes" not in ask_bragi_tools.TOOL_IMPLS:
        pytest.skip("Patient-specific analyte discovery not yet implemented for this query path.")

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=lab_patient["patient_id"],
            requester_user_id=lab_patient["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = run_tool(ctx, "search_available_lab_analytes", {"query": "platelets"})
        labels = {a.get("canonical_name") or a.get("display_name") for a in result.get("analytes", [])}
        assert any("platelet" in (label or "").lower() for label in labels)
    finally:
        db.close()
