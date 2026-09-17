"""P0 upload-reliability session — tests for the final-classification
decision policy (app/services/document_classification_service.py): the
one place that reconciles the AI semantic classifier against the
existing legacy/Reducto fallback result. All AI calls are mocked.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import ai_document_classifier as classifier_module
from app.services.document_classifier import CLASSIFIED, NEEDS_CONFIRMATION
from app.services.document_classification_service import (
    AI_NEEDS_CONFIRMATION_SOURCE,
    AI_SOURCE,
    resolve_final_classification,
)
from app.services.document_taxonomy import DocumentType


def _fake_response(**overrides) -> SimpleNamespace:
    payload = {
        "document_type": "discharge_summary",
        "confidence": 0.95,
        "ambiguous": False,
        "alternative_document_type": None,
        "reason_codes": ["DISCHARGE_TITLE"],
    }
    payload.update(overrides)
    return SimpleNamespace(output_text=json.dumps(payload), output=[])


def _mock_ai(monkeypatch, response=None, side_effect=None):
    fake_client = MagicMock()
    if side_effect is not None:
        fake_client.responses.create.side_effect = side_effect
    else:
        fake_client.responses.create.return_value = response or _fake_response()
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)
    return fake_client


def _fallback_kwargs(**overrides):
    base = dict(
        classification_text="BILET DE IESIRE DIN SPITAL, epicriza, diagnostic la externare.",
        fallback_document_type=DocumentType.LABORATORY_RESULTS,
        fallback_status=NEEDS_CONFIRMATION,
        fallback_confidence=0.6,
        fallback_source="legacy_rules",
    )
    base.update(overrides)
    return base


# --- Core policy -----------------------------------------------------------


def test_confident_unambiguous_ai_result_becomes_final(monkeypatch):
    _mock_ai(monkeypatch, _fake_response(document_type="discharge_summary", confidence=0.95, ambiguous=False))

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.document_type == DocumentType.DISCHARGE_SUMMARY
    assert decision.status == CLASSIFIED
    assert decision.classification_source == AI_SOURCE
    assert decision.ai_attempted is True


def test_low_confidence_ai_result_needs_confirmation_not_other(monkeypatch):
    _mock_ai(monkeypatch, _fake_response(document_type="discharge_summary", confidence=0.4, ambiguous=False))

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.status == NEEDS_CONFIRMATION
    assert decision.document_type == DocumentType.DISCHARGE_SUMMARY  # AI's best guess pre-fills confirmation
    assert decision.classification_source == AI_NEEDS_CONFIRMATION_SOURCE
    assert decision.status != "other"


def test_ambiguous_ai_result_needs_confirmation_even_at_high_confidence(monkeypatch):
    _mock_ai(
        monkeypatch,
        _fake_response(
            document_type="discharge_summary",
            confidence=0.9,
            ambiguous=True,
            alternative_document_type="laboratory_results",
        ),
    )

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.status == NEEDS_CONFIRMATION
    assert decision.classification_source == AI_NEEDS_CONFIRMATION_SOURCE
    assert decision.ai_ambiguous is True


def test_custom_confidence_threshold_is_respected(monkeypatch):
    _mock_ai(monkeypatch, _fake_response(confidence=0.8, ambiguous=False))

    below_custom_threshold = resolve_final_classification(**_fallback_kwargs(), ai_min_confidence=0.85)
    assert below_custom_threshold.status == NEEDS_CONFIRMATION

    above_custom_threshold = resolve_final_classification(**_fallback_kwargs(), ai_min_confidence=0.5)
    assert above_custom_threshold.status == CLASSIFIED


# --- Fallback behavior -------------------------------------------------


def test_ai_unavailable_falls_back_entirely_to_existing_result(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.document_type == DocumentType.LABORATORY_RESULTS
    assert decision.status == NEEDS_CONFIRMATION
    assert decision.confidence == 0.6
    assert decision.classification_source == "legacy_rules"
    assert decision.status != "other"


def test_ai_timeout_falls_back_without_raising(monkeypatch):
    class FakeTimeout(Exception):
        pass

    _mock_ai(monkeypatch, side_effect=FakeTimeout("timed out"))

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.classification_source == "legacy_rules"
    assert decision.ai_attempted is True
    assert decision.ai_error is not None


def test_ai_invalid_json_falls_back_without_raising(monkeypatch):
    fake_client = MagicMock()
    fake_client.responses.create.return_value = SimpleNamespace(output_text="not valid json {{{", output=[])
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.classification_source == "legacy_rules"
    assert decision.document_type == DocumentType.LABORATORY_RESULTS


def test_no_classification_text_skips_ai_entirely_without_error(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(classifier_module, "_client", lambda: fake_client)

    decision = resolve_final_classification(**_fallback_kwargs(classification_text=""))

    fake_client.responses.create.assert_not_called()
    assert decision.classification_source == "legacy_rules"
    assert decision.ai_attempted is False


def test_audit_details_never_includes_raw_document_text(monkeypatch):
    _mock_ai(monkeypatch, _fake_response())
    long_text = "BILET DE IESIRE DIN SPITAL " + ("secret patient content " * 50)

    decision = resolve_final_classification(**_fallback_kwargs(classification_text=long_text))

    details = decision.audit_details()
    assert "secret patient content" not in details
    assert len(details) < 500


# --- Dominant-purpose adversarial cases (mocked AI, realistic outputs) ---


@pytest.mark.parametrize(
    "scenario,ai_payload,expected_type",
    [
        (
            "discharge_with_3_pages_of_labs",
            dict(document_type="discharge_summary", confidence=0.92, ambiguous=False,
                 reason_codes=["DISCHARGE_TITLE", "EPICRISIS", "EMBEDDED_LAB_TABLE_SECONDARY"]),
            DocumentType.DISCHARGE_SUMMARY,
        ),
        (
            "discharge_with_medication_list",
            dict(document_type="discharge_summary", confidence=0.9, ambiguous=False,
                 reason_codes=["DISCHARGE_TITLE", "DISCHARGE_RECOMMENDATIONS"]),
            DocumentType.DISCHARGE_SUMMARY,
        ),
        (
            "operative_report_with_postop_labs",
            dict(document_type="operative_report", confidence=0.88, ambiguous=False,
                 reason_codes=["OPERATIVE_TECHNIQUE"]),
            DocumentType.OPERATIVE_REPORT,
        ),
        (
            "consultation_with_attached_labs",
            dict(document_type="specialist_consultation", confidence=0.85, ambiguous=False,
                 reason_codes=["OUTPATIENT_CONSULTATION"]),
            DocumentType.SPECIALIST_CONSULTATION,
        ),
        (
            "admission_note_mentioning_future_discharge_plan",
            dict(document_type="hospital_admission_note", confidence=0.87, ambiguous=False,
                 reason_codes=["ADMISSION_ONLY_NO_DISCHARGE"]),
            DocumentType.HOSPITAL_ADMISSION_NOTE,
        ),
    ],
)
def test_dominant_purpose_scenarios(monkeypatch, scenario, ai_payload, expected_type):
    _mock_ai(monkeypatch, _fake_response(**ai_payload))

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.document_type == expected_type, scenario
    assert decision.status == CLASSIFIED, scenario


# --- Required classification-category coverage (mocked AI, realistic outputs) ---


@pytest.mark.parametrize(
    "scenario,ai_payload,expected_type",
    [
        (
            "bilet_de_iesire_with_embedded_labs",
            dict(document_type="discharge_summary", confidence=0.95, ambiguous=False,
                 reason_codes=["DISCHARGE_TITLE", "EPICRISIS", "EMBEDDED_LAB_TABLE_SECONDARY"]),
            DocumentType.DISCHARGE_SUMMARY,
        ),
        (
            "fisa_de_externare",
            dict(document_type="discharge_summary", confidence=0.93, ambiguous=False,
                 reason_codes=["DISCHARGE_TITLE"]),
            DocumentType.DISCHARGE_SUMMARY,
        ),
        (
            "foaie_de_internare",
            dict(document_type="hospital_admission_note", confidence=0.9, ambiguous=False,
                 reason_codes=["ADMISSION_ONLY_NO_DISCHARGE"]),
            DocumentType.HOSPITAL_ADMISSION_NOTE,
        ),
        (
            "outpatient_scrisoare_medicala",
            dict(document_type="specialist_consultation", confidence=0.86, ambiguous=False,
                 reason_codes=["OUTPATIENT_CONSULTATION"]),
            DocumentType.SPECIALIST_CONSULTATION,
        ),
        (
            "standalone_cbc",
            dict(document_type="laboratory_results", confidence=0.97, ambiguous=False,
                 reason_codes=["LAB_TABLE_ONLY"]),
            DocumentType.LABORATORY_RESULTS,
        ),
        (
            "pathology_report",
            dict(document_type="pathology_report", confidence=0.91, ambiguous=False,
                 reason_codes=["PATHOLOGY_DIAGNOSIS"]),
            DocumentType.PATHOLOGY_REPORT,
        ),
        (
            "operative_report",
            dict(document_type="operative_report", confidence=0.9, ambiguous=False,
                 reason_codes=["OPERATIVE_TECHNIQUE"]),
            DocumentType.OPERATIVE_REPORT,
        ),
        (
            "prescription",
            dict(document_type="prescription", confidence=0.94, ambiguous=False,
                 reason_codes=["PRESCRIPTION_FORMAT"]),
            DocumentType.PRESCRIPTION,
        ),
        (
            "imaging_report",
            dict(document_type="imaging_report", confidence=0.93, ambiguous=False,
                 reason_codes=["IMAGING_FINDINGS"]),
            DocumentType.IMAGING_REPORT,
        ),
        (
            "genuinely_unclassified_document",
            dict(document_type="other", confidence=0.8, ambiguous=False,
                 reason_codes=["INSUFFICIENT_SIGNAL"]),
            DocumentType.OTHER,
        ),
    ],
)
def test_required_classification_categories(monkeypatch, scenario, ai_payload, expected_type):
    _mock_ai(monkeypatch, _fake_response(**ai_payload))

    decision = resolve_final_classification(**_fallback_kwargs())

    assert decision.document_type == expected_type, scenario
    assert decision.status == CLASSIFIED, scenario


def test_other_is_never_produced_merely_from_ai_unavailability(monkeypatch):
    """Explicit invariant: an AI outage falls back to the existing
    classifier's own result — it must never manifest as `other`, which
    is reserved for a genuine semantic "this doesn't fit any type"
    outcome only the classifier itself can assert."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    decision = resolve_final_classification(
        **_fallback_kwargs(fallback_document_type=DocumentType.DISCHARGE_SUMMARY, fallback_status=CLASSIFIED, fallback_confidence=0.9)
    )

    assert decision.document_type == DocumentType.DISCHARGE_SUMMARY
    assert decision.document_type != DocumentType.OTHER
