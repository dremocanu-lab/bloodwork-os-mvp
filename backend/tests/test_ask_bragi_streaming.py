"""Tests for Ask Bragi streaming: the pure extract_streaming_answer_
prefix() helper (no DB/network), plus end-to-end tests of POST
.../messages/stream against a fake ASYNC OpenAI client (same "mock the
model, use the real DB/route/auth" convention test_ask_bragi_service.py
already established for the non-streaming endpoint — CI-safe, no real
API key needed; real-provider verification is the live-eval script,
see BRAGI_ASK_BRAGI_PLAN.md's "Real OpenAI testing" section).
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

from app.services.ask_bragi.service import extract_streaming_answer_prefix

load_dotenv()

if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "DATABASE_URL not configured — this file needs real DB connectivity.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.api.routers import ask_bragi as ask_bragi_router  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ask_bragi import service as ask_bragi_service  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"askbragi-stream-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {
        "email": email,
        "full_name": f"AskBragi Stream Test {role}",
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


class _FakeAsyncStream:
    """Fake of openai.AsyncStream — an async-iterable of fake event
    objects, closeable, matching just the surface run_turn_streaming
    actually uses."""

    def __init__(self, events):
        self._events = events
        self.closed = False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self._events:
            yield event

    async def close(self):
        self.closed = True


def _text_delta(delta: str):
    return SimpleNamespace(type="response.output_text.delta", delta=delta)


def _function_call_done(name: str, arguments: dict, call_id: str = "call_1"):
    item = SimpleNamespace(type="function_call", name=name, arguments=json.dumps(arguments), call_id=call_id)
    return SimpleNamespace(type="response.output_item.done", item=item)


def _completed(input_tokens: int = 10, output_tokens: int = 20):
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))


class _FakeAsyncResponses:
    def __init__(self, streams):
        self._streams = list(streams)

    async def create(self, **kwargs):
        return self._streams.pop(0)


class _FakeAsyncClient:
    def __init__(self, streams):
        self.responses = _FakeAsyncResponses(streams)


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event_name:
            events.append((event_name, data))
    return events


def _stream_message(monkeypatch, token, conversation_id, message, streams):
    monkeypatch.setattr(ask_bragi_service, "_async_client", lambda: _FakeAsyncClient(streams))
    with client.stream(
        "POST",
        f"/ask-bragi/conversations/{conversation_id}/messages/stream",
        json={"message": message},
        headers=_auth(token),
    ) as response:
        assert response.status_code == 200
        raw_text = "".join(response.iter_text())
    return _parse_sse(raw_text)


def test_stream_yields_progressive_text_then_completed_and_persists(monkeypatch):
    monkeypatch.setattr(ask_bragi_router, "ASK_BRAGI_ENABLED", True)
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)
    account = _signup("patient", cnp="6000101999941")
    conv = client.post("/ask-bragi/conversations", json={}, headers=_auth(account["token"])).json()

    final_json = json.dumps(
        {"answer": "You have no documents yet.", "citations": [], "chart_request": None, "follow_ups": [], "status": "complete"}
    )
    streams = [_FakeAsyncStream([_text_delta(final_json), _completed()])]

    events = _stream_message(monkeypatch, account["token"], conv["id"], "Do I have any documents?", streams)
    event_names = [name for name, _ in events]

    assert event_names[0] == "started"
    text_deltas = [d for n, d in events if n == "text_delta"]
    assert "".join(d["delta"] for d in text_deltas) == "You have no documents yet."
    assert event_names[-2] == "completed"
    assert event_names[-1] == "saved"
    completed_data = next(d for n, d in events if n == "completed")
    assert completed_data["answer"] == "You have no documents yet."
    assert completed_data["scope_used"] == "patient_record"

    # Persisted exactly like the non-streaming route — GET reflects it.
    detail = client.get(f"/ask-bragi/conversations/{conv['id']}", headers=_auth(account["token"])).json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][0]["content"] == "Do I have any documents?"
    assert detail["messages"][1]["role"] == "assistant"
    assert detail["messages"][1]["content"] == "You have no documents yet."

    client.delete("/my/account", headers=_auth(account["token"]))


def test_stream_runs_a_tool_round_before_the_final_answer(monkeypatch):
    monkeypatch.setattr(ask_bragi_router, "ASK_BRAGI_ENABLED", True)
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)
    account = _signup("patient", cnp="6000101999942")
    conv = client.post("/ask-bragi/conversations", json={}, headers=_auth(account["token"])).json()

    final_json = json.dumps(
        {"answer": "No active medications found.", "citations": [], "chart_request": None, "follow_ups": [], "status": "complete"}
    )
    streams = [
        _FakeAsyncStream([_function_call_done("get_medications", {})]),
        _FakeAsyncStream([_text_delta(final_json), _completed()]),
    ]

    events = _stream_message(monkeypatch, account["token"], conv["id"], "What medications am I on?", streams)
    event_names = [name for name, _ in events]

    assert "status" in event_names  # the tool-round status update
    status_data = next(d for n, d in events if n == "status")
    assert status_data["label"]  # a restrained label, never the raw tool name
    assert "get_medications" not in status_data["label"]
    completed_data = next(d for n, d in events if n == "completed")
    assert completed_data["answer"] == "No active medications found."
    assert completed_data["tool_categories"] == ["get_medications"]

    client.delete("/my/account", headers=_auth(account["token"]))


def test_stream_stops_and_does_not_persist_when_should_stop_fires(monkeypatch):
    """Service-level (not through the HTTP route, since simulating a real
    mid-request client disconnect isn't practical via TestClient): a
    should_stop() that flips True partway through must stop consuming
    the provider stream, close it, emit "stopped", and never reach
    "completed" — nothing unvalidated gets a chance to be persisted."""
    import asyncio

    from app.services.ask_bragi.context import AskBragiContext

    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)
    account = _signup("patient", cnp="6000101999943")
    db = SessionLocal()
    try:
        patient = (
            db.query(models.Patient)
            .join(models.User, models.User.id == models.Patient.linked_user_id)
            .filter(models.User.email == account["email"])
            .first()
        )
        fake_stream = _FakeAsyncStream(
            [_text_delta('{"answer": "partial'), _text_delta(" text that should never persist")]
        )
        monkeypatch.setattr(ask_bragi_service, "_async_client", lambda: _FakeAsyncClient([fake_stream]))

        call_count = {"n": 0}

        async def should_stop():
            call_count["n"] += 1
            return call_count["n"] > 2  # let a couple of events through, then stop

        async def collect():
            ctx = AskBragiContext(
                db=db,
                patient_id=patient.id,
                requester_user_id=account["user"]["id"],
                requester_role="patient",
                scope="patient_record",
            )
            events = []
            async for name, data in ask_bragi_service.run_turn_streaming(
                ctx=ctx,
                audience="patient",
                user_message="Tell me about my record.",
                prior_turns=[],
                should_stop=should_stop,
            ):
                events.append((name, data))
            return events

        events = asyncio.run(collect())
        event_names = [n for n, _ in events]
        assert "stopped" in event_names
        assert "completed" not in event_names
        assert fake_stream.closed is True
    finally:
        db.close()
        client.delete("/my/account", headers=_auth(account["token"]))


def test_stream_requires_authentication(monkeypatch):
    monkeypatch.setattr(ask_bragi_service, "ASK_BRAGI_ENABLED", True)
    response = client.post(
        "/ask-bragi/conversations/999999/messages/stream",
        json={"message": "hi"},
    )
    assert response.status_code in (401, 403)


def test_extracts_a_simple_complete_answer():
    buffer = '{"answer": "Your creatinine is 1.1 mg/dL.", "citations": []'
    assert extract_streaming_answer_prefix(buffer) == "Your creatinine is 1.1 mg/dL."


def test_extracts_a_growing_partial_answer_as_more_buffer_arrives():
    full = '{"answer": "Your hemoglobin has been trending upward over time."'
    # Simulate the buffer growing one character at a time and assert the
    # extracted prefix is always a valid prefix of the true answer, and
    # the FULL answer is recovered once the buffer is complete.
    for cut in range(len(full)):
        partial = full[: cut + 1]
        extracted = extract_streaming_answer_prefix(partial)
        assert full.startswith('{"answer": "' + extracted) or extracted == ""
    assert extract_streaming_answer_prefix(full) == "Your hemoglobin has been trending upward over time."


def test_returns_empty_before_the_answer_key_appears():
    assert extract_streaming_answer_prefix("") == ""
    assert extract_streaming_answer_prefix('{"ans') == ""
    assert extract_streaming_answer_prefix('{"answer"') == ""
    assert extract_streaming_answer_prefix('{"answer": ') == ""


def test_handles_standard_json_escapes():
    buffer = r'{"answer": "She said \"stop\" and used a backslash \\ then a newline\nhere.'
    assert (
        extract_streaming_answer_prefix(buffer)
        == 'She said "stop" and used a backslash \\ then a newline\nhere.'
    )


def test_handles_unicode_escape():
    # A real \uXXXX escape sequence (not a literal UTF-8 character) —
    # the previous version of this test accidentally used a literal "é"
    # and so never actually exercised the \u decoding branch at all.
    buffer = '{"answer": "Caf\\u00e9 result: normal.'
    assert extract_streaming_answer_prefix(buffer) == "Café result: normal."


def test_stops_at_an_incomplete_escape_rather_than_guessing():
    # Cut off mid-escape-sequence — must not raise, must not fabricate.
    assert extract_streaming_answer_prefix('{"answer": "value is 5\\') == "value is 5"
    assert extract_streaming_answer_prefix('{"answer": "café \\u00') == "café "


def test_never_reads_past_the_closing_quote():
    buffer = '{"answer": "Complete.", "citations": [{"source_evidence_id": 999999}]'
    assert extract_streaming_answer_prefix(buffer) == "Complete."


def test_ignores_an_answer_shaped_string_elsewhere_if_key_is_absent():
    assert extract_streaming_answer_prefix('{"other": "not the answer field"') == ""
