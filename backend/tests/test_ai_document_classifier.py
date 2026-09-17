"""P0 upload-reliability session — tests for the AI semantic document
classifier (app/services/ai_document_classifier.py). All OpenAI calls
are mocked (same pattern as test_ask_bragi_service.py's `fake_client`) —
this file makes no real API call and needs no API key.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import ai_document_classifier as classifier_module
from app.services.ai_document_classifier import (
    AIClassificationError,
    AIClassificationResult,
    _build_bounded_representation,
    _parse_ai_response,
    classify_document_text_with_ai,
)
from app.services.document_taxonomy import DocumentType


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(output_text=json.dumps(payload), output=[])


def _valid_payload(**overrides) -> dict:
    base = {
        "document_type": "discharge_summary",
        "confidence": 0.95,
        "ambiguous": False,
        "alternative_document_type": None,
        "reason_codes": ["DISCHARGE_TITLE", "EPICRISIS"],
    }
    base.update(overrides)
    return base


# --- _build_bounded_representation ------------------------------------


def test_bounded_representation_returns_short_text_verbatim():
    text = "short document text"
    assert _build_bounded_representation(text, max_chars=1000) == text


def test_bounded_representation_preserves_head_middle_and_tail_markers():
    head_marker = "BILET DE IESIRE DIN SPITAL START-MARKER"
    middle_marker = "MIDDLE-MARKER-EPICRIZA-CONTENT"
    tail_marker = "TAIL-MARKER-RECOMANDARI-LA-EXTERNARE"

    filler = "x" * 500
    text = f"{head_marker}\n{filler}\n{middle_marker}\n{filler}\n{tail_marker}"

    bounded = _build_bounded_representation(text, max_chars=400)

    assert head_marker in bounded
    assert tail_marker in bounded
    # A naive head-only truncation at 400 chars would lose everything
    # past the filler — this proves the tail survives deliberately.
    assert bounded.index(head_marker) < bounded.index(tail_marker)


def test_bounded_representation_never_exceeds_a_reasonable_multiple_of_the_budget():
    text = "y" * 100_000
    bounded = _build_bounded_representation(text, max_chars=1000)
    # Allows for the small "[... middle of document ...]" markers added.
    assert len(bounded) < 1200


# --- _parse_ai_response --------------------------------------------------


def test_parse_valid_response():
    result = _parse_ai_response(json.dumps(_valid_payload()))
    assert result.document_type == DocumentType.DISCHARGE_SUMMARY
    assert result.confidence == 0.95
    assert result.ambiguous is False
    assert result.alternative_document_type is None
    assert "DISCHARGE_TITLE" in result.reason_codes


def test_parse_rejects_invalid_json():
    with pytest.raises(AIClassificationError):
        _parse_ai_response("not json at all {{{")


def test_parse_rejects_non_enum_document_type():
    payload = _valid_payload(document_type="some_made_up_type_the_model_invented")
    with pytest.raises(AIClassificationError):
        _parse_ai_response(json.dumps(payload))


def test_parse_rejects_missing_confidence():
    payload = _valid_payload()
    del payload["confidence"]
    with pytest.raises(AIClassificationError):
        _parse_ai_response(json.dumps(payload))


def test_parse_clamps_out_of_range_confidence():
    payload = _valid_payload(confidence=1.7)
    result = _parse_ai_response(json.dumps(payload))
    assert result.confidence == 1.0

    payload = _valid_payload(confidence=-0.3)
    result = _parse_ai_response(json.dumps(payload))
    assert result.confidence == 0.0


def test_parse_handles_null_alternative_type():
    result = _parse_ai_response(json.dumps(_valid_payload(alternative_document_type=None)))
    assert result.alternative_document_type is None


def test_parse_handles_valid_alternative_type():
    payload = _valid_payload(ambiguous=True, alternative_document_type="laboratory_results")
    result = _parse_ai_response(json.dumps(payload))
    assert result.alternative_document_type == DocumentType.LABORATORY_RESULTS


def test_parse_ignores_invalid_alternative_type_rather_than_raising():
    payload = _valid_payload(alternative_document_type="not_a_real_type")
    result = _parse_ai_response(json.dumps(payload))
    assert result.alternative_document_type is None


def test_parse_defaults_missing_reason_codes_to_empty_list():
    payload = _valid_payload()
    del payload["reason_codes"]
    result = _parse_ai_response(json.dumps(payload))
    assert result.reason_codes == []


# --- classify_document_text_with_ai (end-to-end within this module) -----


def test_empty_text_raises_without_calling_the_client(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    with pytest.raises(AIClassificationError):
        classify_document_text_with_ai("")

    fake_client.responses.create.assert_not_called()


def test_missing_api_key_raises_ai_classification_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIClassificationError):
        classify_document_text_with_ai("BILET DE IESIRE DIN SPITAL, epicriza completa.")


def test_successful_classification_returns_result(monkeypatch):
    fake_client = MagicMock()
    fake_client.responses.create.return_value = _fake_response(_valid_payload())
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    result = classify_document_text_with_ai("BILET DE IESIRE DIN SPITAL, epicriza completa.")
    assert isinstance(result, AIClassificationResult)
    assert result.document_type == DocumentType.DISCHARGE_SUMMARY

    # Confirm the request used the JSON-schema structured-output format,
    # never a hand-rolled markdown-fence-stripped json.loads pattern.
    _, kwargs = fake_client.responses.create.call_args
    assert kwargs["text"]["format"]["type"] == "json_schema"


def test_provider_exception_is_wrapped_as_ai_classification_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.responses.create.side_effect = RuntimeError("connection reset")
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    with pytest.raises(AIClassificationError):
        classify_document_text_with_ai("some real document text here")


def test_timeout_like_exception_is_wrapped_as_ai_classification_error(monkeypatch):
    fake_client = MagicMock()

    class FakeTimeout(Exception):
        pass

    fake_client.responses.create.side_effect = FakeTimeout("timed out")
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    with pytest.raises(AIClassificationError):
        classify_document_text_with_ai("some real document text here")


def test_empty_output_text_raises(monkeypatch):
    fake_client = MagicMock()
    fake_client.responses.create.return_value = SimpleNamespace(output_text="", output=[])
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    with pytest.raises(AIClassificationError):
        classify_document_text_with_ai("some real document text here")


def test_direct_identifiers_are_redacted_before_leaving_this_module(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured["input"] = kwargs["input"]
        return _fake_response(_valid_payload())

    fake_client = MagicMock()
    fake_client.responses.create.side_effect = fake_create
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    text_with_cnp = "Pacient CNP 1234567890123, email test@example.com. BILET DE IESIRE DIN SPITAL."
    classify_document_text_with_ai(text_with_cnp)

    sent_text = captured["input"][1]["content"]
    assert "1234567890123" not in sent_text
    assert "test@example.com" not in sent_text
    assert "BILET DE IESIRE DIN SPITAL" in sent_text
