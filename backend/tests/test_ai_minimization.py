"""Regression tests for the AI-provider data-minimization boundary
(`app/services/ai_minimization.py`) — see BRAGI_SECURITY_GDPR_PLAN.md §21.
"""

from app.services.ai_minimization import (
    DEFAULT_STRIPPED_FIELDS,
    minimize_patient_context,
    minimize_patient_record_for_provider,
    redact_direct_identifiers,
)


def test_redacts_cnp_shaped_number():
    text = "Patient CNP 1960101123456 was admitted yesterday."
    out = redact_direct_identifiers(text)
    assert "1960101123456" not in out
    assert "[REDACTED-ID]" in out


def test_redacts_email():
    text = "Contact the patient at jane.doe@example.com for follow-up."
    out = redact_direct_identifiers(text)
    assert "jane.doe@example.com" not in out
    assert "[REDACTED-EMAIL]" in out


def test_redacts_romanian_phone_number():
    text = "Callback number: 0722 123 456."
    out = redact_direct_identifiers(text)
    assert "0722 123 456" not in out
    assert "[REDACTED-PHONE]" in out


def test_redact_handles_none_and_empty():
    assert redact_direct_identifiers(None) == ""
    assert redact_direct_identifiers("") == ""


def test_redact_leaves_clinical_text_untouched():
    text = "WBC 4.49 10^3/uL, reference range 3.98-10.00, flag Normal."
    assert redact_direct_identifiers(text) == text


def test_minimize_patient_context_strips_defaults():
    patient = {
        "id": 1,
        "full_name": "Jane Doe",
        "cnp": "1960101123456",
        "email": "jane@example.com",
        "phone": "0722123456",
        "address": "1 Main St",
        "patient_identifier": "ABC123",
        "date_of_birth": "1996-01-01",
    }
    out = minimize_patient_context(patient)
    for field in DEFAULT_STRIPPED_FIELDS:
        assert field not in out
    # Non-identifier fields survive.
    assert out["full_name"] == "Jane Doe"
    assert out["date_of_birth"] == "1996-01-01"
    assert out["id"] == 1


def test_minimize_patient_context_explicit_opt_in():
    patient = {"full_name": "Jane Doe", "cnp": "1960101123456"}
    out = minimize_patient_context(patient, keep_fields={"cnp"})
    assert out["cnp"] == "1960101123456"


def test_minimize_patient_record_for_provider_default_no_cnp():
    patient = {"full_name": "Jane Doe", "cnp": "1960101123456"}
    out = minimize_patient_record_for_provider(patient)
    assert "cnp" not in out


def test_minimize_patient_record_for_provider_explicit_cnp_purpose():
    patient = {"full_name": "Jane Doe", "cnp": "1960101123456"}
    out = minimize_patient_record_for_provider(patient, purpose_requires_cnp=True)
    assert out["cnp"] == "1960101123456"
