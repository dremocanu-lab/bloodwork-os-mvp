"""Mocked-model tests for app/services/ask_bragi/service.py — verifies
the tool-calling loop, citation validation, and chart resolution WITHOUT
a real OpenAI API call (CI-safe, no network/key needed). Real-API
verification lives in the live-eval script (see
BRAGI_ASK_BRAGI_PLAN.md's "Real OpenAI testing" section) — deliberately
not run automatically here or in CI (costs real money, needs a real key).

Same DB-connectivity requirement/skip behavior as test_idor_regression.py
(tools.py hits the real DB).
"""

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from app.services.ask_bragi import service as ask_bragi_service  # noqa: E402
from app.services.ask_bragi.context import AskBragiContext  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"askbragi-svc-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"AskBragi Svc Test {role}",
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
def patient_with_data():
    account = _signup("patient", cnp="6000101999951")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="bloodwork",
            filename="cbc.pdf",
            document_type="laboratory_results",
            created_at="2026-01-01T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-svc-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        db.flush()

        lab = models.LabResult(
            document_id=doc.id,
            raw_test_name="Creatinina",
            canonical_name="creatinine",
            value="1.1",
            unit="mg/dL",
            reference_range="0.7-1.3",
            observation_datetime="2026-01-01",
        )
        db.add(lab)
        db.flush()

        evidence = models.SourceEvidence(
            document_id=doc.id,
            lab_result_id=lab.id,
            page_number=1,
            source_text="Creatinina 1.1 mg/dL",
            created_at="2026-01-01T00:00:00Z",
        )
        db.add(evidence)
        db.commit()

        yield {"account": account, "patient_id": patient_id, "document_id": doc.id, "evidence_id": evidence.id}

        db.query(models.SourceEvidence).filter(models.SourceEvidence.id == evidence.id).delete()
        db.query(models.LabResult).filter(models.LabResult.id == lab.id).delete()
        db.query(models.Document).filter(models.Document.id == doc.id).delete()
        db.commit()
    finally:
        db.close()

    client.delete("/my/account", headers=_auth(account["token"]))


def _fake_function_call(name: str, arguments: dict, call_id: str = "call_1"):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(arguments), call_id=call_id)


def _fake_final_response(output_dict: dict):
    return SimpleNamespace(
        output=[],
        output_text=json.dumps(output_dict),
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def _fake_tool_call_response(name: str, arguments: dict):
    return SimpleNamespace(
        output=[_fake_function_call(name, arguments)],
        output_text="",
        usage=SimpleNamespace(input_tokens=80, output_tokens=20),
    )


def test_tool_loop_executes_a_real_tool_and_returns_validated_citation(monkeypatch, patient_with_data):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)

    fake_client = MagicMock()
    fake_client.responses.create.side_effect = [
        _fake_tool_call_response("get_lab_results", {"canonical_name": "creatinine"}),
        _fake_final_response(
            {
                "answer": "Your latest creatinine was 1.1 mg/dL.",
                "citations": [
                    {
                        "source_evidence_id": patient_with_data["evidence_id"],
                        "label": "Lab report",
                    }
                ],
                "chart_request": None,
                "follow_ups": [],
                "status": "complete",
            }
        ),
    ]
    monkeypatch.setattr(ask_bragi_service, "_client", lambda: fake_client)

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_with_data["patient_id"],
            requester_user_id=patient_with_data["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = ask_bragi_service.run_turn(
            ctx=ctx, audience="patient", user_message="What was my latest creatinine?", prior_turns=[]
        )
    finally:
        db.close()

    assert result.response.answer == "Your latest creatinine was 1.1 mg/dL."
    assert len(result.response.citations) == 1
    assert result.response.citations[0].source_evidence_id == patient_with_data["evidence_id"]
    assert result.response.dropped_citation_count == 0
    assert result.tool_categories == ["get_lab_results"]
    assert fake_client.responses.create.call_count == 2


def test_hallucinated_citation_is_dropped_not_trusted(monkeypatch, patient_with_data):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)

    fake_client = MagicMock()
    # The model never actually calls a tool this turn, yet claims a
    # citation anyway — this must be dropped, not trusted.
    fake_client.responses.create.side_effect = [
        _fake_final_response(
            {
                "answer": "Your creatinine is fine.",
                "citations": [{"source_evidence_id": 999999999, "label": "Fabricated"}],
                "chart_request": None,
                "follow_ups": [],
                "status": "complete",
            }
        ),
    ]
    monkeypatch.setattr(ask_bragi_service, "_client", lambda: fake_client)

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_with_data["patient_id"],
            requester_user_id=patient_with_data["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = ask_bragi_service.run_turn(
            ctx=ctx, audience="patient", user_message="Is my creatinine okay?", prior_turns=[]
        )
    finally:
        db.close()

    assert result.response.citations == []
    assert result.response.dropped_citation_count == 1


def test_chart_request_is_resolved_from_real_data_not_model_output(monkeypatch, patient_with_data):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)

    fake_client = MagicMock()
    fake_client.responses.create.side_effect = [
        _fake_final_response(
            {
                "answer": "Here is your creatinine trend.",
                "citations": [],
                # The model can only request a concept — it cannot supply
                # its own data points; service.py must ignore any attempt
                # to smuggle points in here (the schema doesn't even have
                # a place for them) and fetch real ones itself.
                "chart_request": {"canonical_name": "creatinine"},
                "follow_ups": [],
                "status": "complete",
            }
        ),
    ]
    monkeypatch.setattr(ask_bragi_service, "_client", lambda: fake_client)

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_with_data["patient_id"],
            requester_user_id=patient_with_data["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        result = ask_bragi_service.run_turn(
            ctx=ctx, audience="patient", user_message="Graph my creatinine.", prior_turns=[]
        )
    finally:
        db.close()

    assert result.response.chart is not None
    assert result.response.chart.canonical_name == "creatinine"
    # The one real point from the fixture, fetched from the DB, not the model.
    assert len(result.response.chart.points) == 1
    assert result.response.chart.points[0].value == "1.1"
    assert result.response.chart.points[0].source_evidence_id == patient_with_data["evidence_id"]


def test_max_tool_rounds_is_enforced(monkeypatch, patient_with_data):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_MAX_TOOL_ROUNDS", 2)

    fake_client = MagicMock()
    # Always asks for another tool call, never finishes — must not loop forever.
    fake_client.responses.create.side_effect = [
        _fake_tool_call_response("get_patient_context", {}),
        _fake_tool_call_response("get_patient_context", {}),
    ]
    monkeypatch.setattr(ask_bragi_service, "_client", lambda: fake_client)

    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_with_data["patient_id"],
            requester_user_id=patient_with_data["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        with pytest.raises(ask_bragi_service.AskBragiError):
            ask_bragi_service.run_turn(ctx=ctx, audience="patient", user_message="Loop forever?", prior_turns=[])
    finally:
        db.close()

    assert fake_client.responses.create.call_count == 2


def test_no_tool_schema_exposes_a_patient_id_parameter():
    """The core "server owns patient scope" invariant, checked directly
    against the actual schemas sent to OpenAI — not just by code review."""
    from app.services.ask_bragi.tools import TOOL_SCHEMAS

    for tool in TOOL_SCHEMAS:
        properties = tool["parameters"]["properties"]
        assert "patient_id" not in properties, f"{tool['name']} must never accept patient_id from the model"


def test_disabled_flag_raises_before_any_client_call(monkeypatch, patient_with_data):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", False)
    db = SessionLocal()
    try:
        ctx = AskBragiContext(
            db=db,
            patient_id=patient_with_data["patient_id"],
            requester_user_id=patient_with_data["account"]["user"]["id"],
            requester_role="patient",
            scope="patient_record",
        )
        with pytest.raises(ask_bragi_service.AskBragiError):
            ask_bragi_service.run_turn(ctx=ctx, audience="patient", user_message="hi", prior_turns=[])
    finally:
        db.close()
