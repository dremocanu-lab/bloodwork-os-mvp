"""AI Clinical Document Interpreter tests — Clinical Reader Intelligence
V2. NEVER depends on live OpenAI (see Part 30 of the task this closes):
`ai_interpreter._call_model` is monkeypatched to return deterministic,
controlled dicts standing in for whatever the model would have returned.
`interpret_structured_document`'s own real, non-mocked logic — grounding
validation, Pydantic re-construction, graceful fallback on failure — is
what's actually under test.
"""

from __future__ import annotations

import pytest

from app.services.clinical_document import ai_interpreter
from app.services.clinical_document.ai_interpreter import (
    AIInterpretationError,
    apply_interpretation,
    interpret_structured_document,
    validate_and_filter_interpretation,
)
from app.services.clinical_document.schema import (
    ClinicalEvent,
    ClinicalSection,
    DocumentMetadata,
    ParagraphBlock,
    StructuredClinicalDocument,
)
from app.services.document_taxonomy import DocumentType


def _sample_document() -> StructuredClinicalDocument:
    return StructuredClinicalDocument(
        parser_version="test",
        document_kind=DocumentType.DISCHARGE_SUMMARY,
        metadata=DocumentMetadata(admission_date="2026-03-04", discharge_date="2026-03-05"),
        sections=[
            ClinicalSection(
                id="section-diagnoses",
                canonical_key="diagnoses",
                display_title="Diagnoses",
                order=0,
                blocks=[ParagraphBlock(text="Diagnostic principal: D45 Policitemie esentiala")],
            ),
            ClinicalSection(
                id="section-clinical_course",
                canonical_key="clinical_course",
                display_title="Clinical course",
                order=1,
                blocks=[ParagraphBlock(text="Pacient internat la 04.03.2026, externat la 05.03.2026.")],
            ),
        ],
        dated_events=[
            ClinicalEvent(
                source_event_id="seg-1-event-0",
                raw_date_text="04.03.2026",
                normalized_date="2026-03-04",
                event_type="admission",
                raw_text="Pacient internat la 04.03.2026.",
            ),
            ClinicalEvent(
                source_event_id="seg-1-event-1",
                raw_date_text="05.03.2026",
                normalized_date="2026-03-05",
                event_type="discharge",
                raw_text="Externat la 05.03.2026.",
            ),
        ],
    )


# ─── validate_and_filter_interpretation: the real grounding gate ──────────


def test_valid_grounded_output_is_kept():
    document = _sample_document()
    raw = {
        "diagnoses": [
            {"code": "D45", "text": "Policitemie esentiala", "role": "principal", "source_section_id": "section-diagnoses", "source_event_ids": []}
        ],
        "investigations": [],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {
            "admission_date": "2026-03-04",
            "discharge_date": "2026-03-05",
            "section_ids": ["section-clinical_course"],
            "event_ids": ["seg-1-event-0", "seg-1-event-1"],
        },
        "encounter_scope_assignments": [{"target_type": "event", "target_id": "seg-1-event-0", "scope": "current"}],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    assert len(cleaned["diagnoses"]) == 1
    assert cleaned["current_encounter"]["event_ids"] == ["seg-1-event-0", "seg-1-event-1"]
    assert len(cleaned["encounter_scope_assignments"]) == 1


def test_hallucinated_section_reference_rejected():
    document = _sample_document()
    raw = {
        "diagnoses": [
            {"code": None, "text": "Fabricated diagnosis", "role": "secondary", "source_section_id": "section-does-not-exist", "source_event_ids": []}
        ],
        "investigations": [],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert cleaned["diagnoses"] == []
    assert len(rejections) == 1
    assert "Fabricated diagnosis" in rejections[0]


def test_hallucinated_event_reference_rejected():
    document = _sample_document()
    raw = {
        "diagnoses": [],
        "investigations": [
            {
                "investigation_type": "imaging",
                "title": "Fabricated scan",
                "findings": None,
                "conclusion": None,
                "source_section_id": None,
                "source_event_ids": ["event-that-does-not-exist"],
            }
        ],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert cleaned["investigations"] == []
    assert any("Fabricated scan" in r for r in rejections)


def test_cross_document_style_id_rejected_same_as_any_other_unknown_id():
    """A section_id that looks plausible (same naming convention as a
    real id) but belongs to a DIFFERENT document is structurally
    indistinguishable from any other unknown id here — the allow-list is
    built fresh from THIS document instance every call, so there is no
    way for a stale/foreign id to ever be considered valid."""
    document = _sample_document()
    raw = {
        "diagnoses": [
            {"code": None, "text": "Cross-document diagnosis", "role": "principal", "source_section_id": "section-diagnoses-from-another-doc", "source_event_ids": []}
        ],
        "investigations": [],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert cleaned["diagnoses"] == []
    assert rejections


def test_treatment_era_with_no_valid_events_rejected():
    document = _sample_document()
    raw = {
        "diagnoses": [],
        "investigations": [],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [{"label": "Fake era", "start_date": None, "end_date": None, "description": "", "event_ids": ["not-real"]}],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert cleaned["treatment_eras"] == []
    assert rejections


def test_scope_assignment_to_unknown_target_rejected():
    document = _sample_document()
    raw = {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [{"target_type": "section", "target_id": "nonexistent-section", "scope": "current"}],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert cleaned["encounter_scope_assignments"] == []
    assert rejections


def test_partially_valid_response_keeps_the_valid_items_only():
    document = _sample_document()
    raw = {
        "diagnoses": [
            {"code": "D45", "text": "Real diagnosis", "role": "principal", "source_section_id": "section-diagnoses", "source_event_ids": []},
            {"code": None, "text": "Fake diagnosis", "role": "secondary", "source_section_id": "fake-section", "source_event_ids": []},
        ],
        "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert len(cleaned["diagnoses"]) == 1
    assert cleaned["diagnoses"][0]["text"] == "Real diagnosis"
    assert len(rejections) == 1


# ─── apply_interpretation: constructs a real, re-validated document ───────


def test_apply_interpretation_constructs_valid_schema_objects():
    document = _sample_document()
    cleaned = {
        "diagnoses": [{"code": "D45", "text": "Policitemie", "role": "principal", "source_section_id": "section-diagnoses", "source_event_ids": []}],
        "investigations": [],
        "anomalies": [{"anomaly_type": "physiologically_implausible_value", "message": "AV 1008 implausible", "original_value": "AV 1008", "source_section_id": None, "source_event_ids": []}],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": ["section-clinical_course"], "event_ids": ["seg-1-event-0"]},
        "encounter_scope_assignments": [{"target_type": "event", "target_id": "seg-1-event-0", "scope": "current"}],
    }
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    assert result.diagnoses[0].text == "Policitemie"
    assert result.diagnoses[0].role == "principal"
    assert result.anomalies[0].original_value == "AV 1008"
    assert result.current_encounter.event_ids == ["seg-1-event-0"]
    event = next(e for e in result.dated_events if e.source_event_id == "seg-1-event-0")
    assert event.encounter_scope == "current"
    other_event = next(e for e in result.dated_events if e.source_event_id == "seg-1-event-1")
    assert other_event.encounter_scope is None  # not assigned — never guessed
    assert result.interpretation.status == "complete"
    assert result.interpretation.model == ai_interpreter.AI_INTERPRETER_MODEL


# ─── interpret_structured_document: end-to-end with a mocked model call ───


def test_end_to_end_valid_interpretation(monkeypatch):
    document = _sample_document()

    def fake_call_model(_input):
        return {
            "diagnoses": [{"code": "D45", "text": "Policitemie", "role": "principal", "source_section_id": "section-diagnoses", "source_event_ids": []}],
            "investigations": [],
            "anomalies": [],
            "recommendations": [],
            "treatment_eras": [],
            "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": [], "event_ids": []},
            "encounter_scope_assignments": [],
            "warnings": [],
        }

    monkeypatch.setattr(ai_interpreter, "_call_model", fake_call_model)
    result = interpret_structured_document(document)
    assert result.interpretation.status == "complete"
    assert len(result.diagnoses) == 1


def test_end_to_end_hallucination_downgrades_to_partial_but_never_crashes(monkeypatch):
    document = _sample_document()

    def fake_call_model(_input):
        return {
            "diagnoses": [{"code": None, "text": "Fabricated", "role": "principal", "source_section_id": "not-real", "source_event_ids": []}],
            "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
            "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
            "encounter_scope_assignments": [],
            "warnings": [],
        }

    monkeypatch.setattr(ai_interpreter, "_call_model", fake_call_model)
    result = interpret_structured_document(document)
    assert result.diagnoses == []  # the fabricated item never made it in
    assert result.interpretation.status == "partial"
    assert any("Fabricated" in w for w in result.interpretation.warnings)


def test_malformed_json_response_falls_back_gracefully(monkeypatch):
    document = _sample_document()

    def fake_call_model(_input):
        raise AIInterpretationError("Clinical interpreter returned invalid JSON: bad token")

    monkeypatch.setattr(ai_interpreter, "_call_model", fake_call_model)
    result = interpret_structured_document(document)
    # Falls back to the ORIGINAL deterministic document — never crashes,
    # never loses the existing dated_events/sections.
    assert result.interpretation.status == "unavailable"
    assert result.diagnoses == []
    assert len(result.dated_events) == len(document.dated_events)
    assert len(result.sections) == len(document.sections)


def test_missing_api_key_falls_back_gracefully(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    document = _sample_document()
    result = interpret_structured_document(document)
    assert result.interpretation.status == "unavailable"
    assert "OPENAI_API_KEY" in result.interpretation.warnings[0]
    # The reader still has everything it had before — an AI outage never
    # makes the document unreadable.
    assert len(result.dated_events) == 2


def test_provider_timeout_style_failure_falls_back_gracefully(monkeypatch):
    document = _sample_document()

    def fake_call_model(_input):
        raise AIInterpretationError("Clinical interpreter request failed: timed out")

    monkeypatch.setattr(ai_interpreter, "_call_model", fake_call_model)
    result = interpret_structured_document(document)
    assert result.interpretation.status == "unavailable"


def test_reprocessing_is_idempotent_at_the_document_level(monkeypatch):
    """Running interpretation twice on the SAME underlying deterministic
    document (as a reprocess would) replaces the interpretation-derived
    fields rather than accumulating duplicates — since these are in-JSON
    fields, not separate DB rows, "run again" is naturally idempotent as
    long as the caller always interprets FROM the deterministic base
    document, never from a previously-interpreted one."""
    document = _sample_document()

    def fake_call_model(_input):
        return {
            "diagnoses": [{"code": "D45", "text": "Policitemie", "role": "principal", "source_section_id": "section-diagnoses", "source_event_ids": []}],
            "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
            "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
            "encounter_scope_assignments": [],
            "warnings": [],
        }

    monkeypatch.setattr(ai_interpreter, "_call_model", fake_call_model)
    first = interpret_structured_document(document)
    second = interpret_structured_document(document)  # re-run from the SAME base document
    assert len(first.diagnoses) == 1
    assert len(second.diagnoses) == 1  # not 2 — no accumulation
