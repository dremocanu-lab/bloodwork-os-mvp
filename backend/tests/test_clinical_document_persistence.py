"""Persistence-layer tests for Clinical Document Intelligence V3 Phase 3
— app/services/clinical_document/persistence.py. Pure function tests
against plain strings (no DB needed — this module never touches the DB
itself, it operates on whatever `Document.note_body` string a caller
hands it)."""

import json

from app.services.clinical_document.persistence import (
    LEGACY_UPCONVERSION_PARSER_VERSION,
    parse_structured_document,
    serialize_structured_document,
)
from app.services.clinical_document.schema import (
    ClinicalSection,
    ParagraphBlock,
    StructuredClinicalDocument,
)


def test_none_note_body_parses_to_none():
    assert parse_structured_document(None) is None


def test_empty_string_note_body_parses_to_none():
    assert parse_structured_document("") is None


def test_plain_text_note_body_parses_to_none_not_an_error():
    """The overwhelming majority of note_body rows today are plain notes,
    not JSON at all — existing behavior for those must be completely
    unaffected by this module's existence."""
    assert parse_structured_document("Patient called about a refill.") is None


def test_malformed_json_note_body_parses_to_none_not_a_crash():
    assert parse_structured_document("{not valid json") is None


def test_valid_new_shape_document_round_trips_through_note_body():
    doc = StructuredClinicalDocument(
        parser_version="test-v1",
        document_kind="discharge_summary",
        sections=[
            ClinicalSection(
                id="s1",
                canonical_key="clinical_course",
                display_title="Clinical Course",
                order=0,
                blocks=[ParagraphBlock(text="Patient improved steadily.")],
            )
        ],
    )
    note_body = serialize_structured_document(doc)
    reloaded = parse_structured_document(note_body)
    assert reloaded == doc


def test_invalid_new_shape_payload_parses_to_none_never_trusted_unvalidated():
    """A payload that DOES carry schema_version (so it takes the 'new
    shape' path) but fails validation (here: a raw heading instead of a
    real canonical_key) must come back as absence, never as a partially-
    trusted dict — see the module's own 'validate all persisted
    structured output' rule."""
    bad_payload = {
        "schema_version": "v1",
        "parser_version": "test-v1",
        "document_kind": "discharge_summary",
        "sections": [
            {
                "id": "s1",
                "canonical_key": "EPICRIZĂ",  # not a real canonical key
                "display_title": "Epicriza",
                "order": 0,
                "blocks": [],
            }
        ],
        "dated_events": [],
        "derived_artifacts": [],
        "warnings": [],
    }
    assert parse_structured_document(json.dumps(bad_payload)) is None


def test_legacy_discharge_payload_upconverts_and_merges_repeated_lab_headings():
    """Real shape produced by discharge_summary_pipeline.py today (see
    CURRENT_PIPELINE_MAP.md §8) — no schema_version, a fixed 13-key
    vocabulary. laboratory_normal and laboratory_abnormal are two
    DIFFERENT legacy keys that must merge into the SAME canonical
    laboratory_results section (the V3 contract's own worked example),
    preserving both original headings and both bodies as separate
    blocks — not concatenated into one string, not dropped."""
    legacy_payload = {
        "document_type": "discharge_summary",
        "patient_name": "Test Patient",
        "hospital_name": "Spitalul Județean",
        "admission_date": "2026-01-10",
        "discharge_date": "2026-01-20",
        "sections": [
            {
                "key": "epicriza",
                "title": "EPICRIZĂ",
                "body": "Pacient internat pentru...",
                "formatted_body": "Pacient internat pentru...",
            },
            {
                "key": "laboratory_normal",
                "title": "Examen de laborator cu valori normale",
                "body": "Glicemie 90 mg/dL",
                "formatted_body": "Glicemie 90 mg/dL",
            },
            {
                "key": "laboratory_abnormal",
                "title": "Examen de laborator cu valori patologice",
                "body": "WBC 15.2 x10^3/uL (H)",
                "formatted_body": "WBC 15.2 x10^3/uL (H)",
            },
        ],
        "warnings": ["Page 3 OCR confidence low."],
    }

    result = parse_structured_document(json.dumps(legacy_payload))

    assert result is not None
    assert result.parser_version == LEGACY_UPCONVERSION_PARSER_VERSION
    assert result.document_kind.value == "discharge_summary"
    assert result.metadata.hospital_name == "Spitalul Județean"
    assert result.warnings == ["Page 3 OCR confidence low."]

    by_key = {s.canonical_key: s for s in result.sections}
    assert "clinical_course" in by_key  # epicriza -> clinical_course
    assert "laboratory_results" in by_key  # BOTH lab headings merged here

    lab_section = by_key["laboratory_results"]
    # Both original headings preserved, in encounter order — not lost,
    # not silently picked-one-and-dropped-the-other.
    assert lab_section.source_headings == [
        "Examen de laborator cu valori normale",
        "Examen de laborator cu valori patologice",
    ]
    # Each contributor's text is its OWN block — never merged into one
    # giant string (see the V3 contract's "do not let the schema devolve
    # into title + giant text string" rule).
    assert len(lab_section.blocks) == 2
    assert lab_section.blocks[0].text == "Glicemie 90 mg/dL"
    assert lab_section.blocks[1].text == "WBC 15.2 x10^3/uL (H)"
    # A backward-compat upconversion is honestly marked for human review
    # — its canonical-key mapping is a deterministic best guess, not a
    # confidently-parsed result.
    assert lab_section.review_state == "needs_review"
    assert lab_section.confidence is None

    # Constructing the returned object is itself proof it's a REAL,
    # validated StructuredClinicalDocument, not a bag of dicts —
    # re-serializing and re-parsing it must round-trip as the "new
    # shape" this time (it now carries a real schema_version).
    reloaded = parse_structured_document(serialize_structured_document(result))
    assert reloaded == result


def test_legacy_upconversion_produces_real_dated_events_not_empty(monkeypatch):
    """Clinical Reader Intelligence V2 regression: the upconversion path
    used to run its OWN reduced segmentation-only logic (no Clinical
    Course event/anomaly extraction at all), so `dated_events` was always
    empty for every real (legacy-shaped) document — the exact reason the
    "Clinical course" section rendered as one giant undifferentiated text
    block in production regardless of how good discharge_parser.py's real
    event extraction was, since nothing ever routed a real document
    through it. persistence.py now calls the SAME real parser
    (discharge_parser.parse_legacy_discharge_payload) the live forward
    path would use — this proves it, including that an implausible
    vital-sign value survives verbatim with a warning rather than being
    silently corrected."""
    legacy_payload = {
        "document_type": "discharge_summary",
        "patient_name": "Test Patient",
        "admission_date": "2026-03-04",
        "discharge_date": "2026-03-05",
        "sections": [
            {
                "key": "epicriza",
                "title": "EPICRIZĂ",
                "body": "Pacient internat la 04.03.2026. AV: 1008 bpm la internare. Externat la 05.03.2026, ameliorat.",
                "formatted_body": "",
            },
        ],
    }

    result = parse_structured_document(json.dumps(legacy_payload))

    assert result is not None
    assert result.parser_version == LEGACY_UPCONVERSION_PARSER_VERSION
    # The real bug this closes: this used to always be [].
    assert len(result.dated_events) >= 2
    event_types = {event.event_type for event in result.dated_events}
    assert "admission" in event_types
    assert "discharge" in event_types
    # The implausible AV value is preserved verbatim in the source text
    # and flagged, never rewritten to a "plausible" number.
    assert any("1008" in w and "not corrected" in w.lower() for w in result.warnings)
    assert any("AV: 1008 bpm" in event.raw_text for event in result.dated_events)


def test_unmapped_legacy_key_falls_back_to_other_not_a_crash():
    legacy_payload = {
        "document_type": "discharge_summary",
        "sections": [
            {"key": "some_future_key_not_in_the_map", "title": "Mystery Section", "body": "Text."},
        ],
    }
    result = parse_structured_document(json.dumps(legacy_payload))
    assert result is not None
    assert result.sections[0].canonical_key == "other"


def test_legacy_payload_with_no_sections_still_produces_a_valid_empty_document():
    legacy_payload = {"document_type": "discharge_summary", "sections": []}
    result = parse_structured_document(json.dumps(legacy_payload))
    assert result is not None
    assert result.sections == []


def test_non_discharge_json_note_body_is_not_treated_as_a_legacy_discharge_payload():
    """A plain-note JSON blob (some other, unrelated JSON shape a
    different feature might store in note_body) must not be
    misinterpreted as a discharge payload just because it happens to be
    valid JSON."""
    assert parse_structured_document(json.dumps({"some_other_feature": True})) is None
