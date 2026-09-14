"""Schema-level tests for Clinical Document Intelligence V3 Phase 3 —
`app/services/clinical_document/schema.py`. Pure model tests, no DB
needed (contrast with test_clinical_document_persistence.py, which
still needs no DB either, but is exercised through the persistence
functions instead of the model directly)."""

import pytest
from pydantic import ValidationError

from app.services.clinical_document.schema import (
    CANONICAL_SECTION_KEYS,
    ClinicalEvent,
    ClinicalSection,
    DatedEventGroupBlock,
    KeyValueBlock,
    LabReportReferenceBlock,
    ParagraphBlock,
    StructuredClinicalDocument,
    WarningBlock,
)


def _minimal_section(canonical_key: str, section_id: str = "s1", order: int = 0) -> ClinicalSection:
    return ClinicalSection(
        id=section_id,
        canonical_key=canonical_key,
        display_title=canonical_key.replace("_", " ").title(),
        order=order,
        blocks=[ParagraphBlock(text="Some text.")],
    )


def test_canonical_section_keys_match_the_v3_contracts_fixed_enum():
    # The exact 19-value list from the V3 contract — if this ever drifts,
    # it must be a deliberate, reviewed change to schema.py, not an
    # accidental typo caught only by a downstream 500.
    assert CANONICAL_SECTION_KEYS == (
        "overview",
        "administrative_information",
        "encounter_details",
        "diagnoses",
        "medical_history",
        "examination",
        "clinical_course",
        "investigations",
        "laboratory_results",
        "imaging",
        "procedures",
        "treatment",
        "medications",
        "discharge_medications",
        "recommendations",
        "follow_up",
        "prescriptions",
        "signatures",
        "other",
    )


def test_minimal_valid_document_round_trips_through_json():
    doc = StructuredClinicalDocument(
        parser_version="test-v1",
        document_kind="discharge_summary",
        sections=[_minimal_section("clinical_course")],
    )
    dumped = doc.model_dump_json()
    reloaded = StructuredClinicalDocument.model_validate_json(dumped)
    assert reloaded == doc


def test_raw_source_heading_is_not_accepted_as_a_canonical_key():
    with pytest.raises(ValidationError):
        _minimal_section("EPICRIZĂ")  # a raw heading, not one of the fixed enum values


def test_duplicate_canonical_key_across_sections_is_rejected():
    """The V3 contract's own rule: repeated source headings (e.g.
    multiple EPICRIZĂ pages) MUST merge into ONE canonical section
    before construction — this must be enforced by the model itself,
    not left to a parser's own discipline."""
    with pytest.raises(ValidationError, match="Duplicate canonical_key"):
        StructuredClinicalDocument(
            parser_version="test-v1",
            document_kind="discharge_summary",
            sections=[
                _minimal_section("clinical_course", section_id="s1", order=0),
                _minimal_section("clinical_course", section_id="s2", order=1),
            ],
        )


def test_duplicate_section_id_is_rejected():
    with pytest.raises(ValidationError, match="ClinicalSection.id must be unique"):
        StructuredClinicalDocument(
            parser_version="test-v1",
            document_kind="discharge_summary",
            sections=[
                _minimal_section("clinical_course", section_id="dup", order=0),
                _minimal_section("diagnoses", section_id="dup", order=1),
            ],
        )


def test_duplicate_dated_event_id_is_rejected():
    def _event(event_id: str) -> ClinicalEvent:
        return ClinicalEvent(
            source_event_id=event_id,
            raw_date_text="05.03.2026",
            event_type="follow_up",
            raw_text="Follow-up visit.",
        )

    with pytest.raises(ValidationError, match="ClinicalEvent.source_event_id must be unique"):
        StructuredClinicalDocument(
            parser_version="test-v1",
            document_kind="discharge_summary",
            dated_events=[_event("e1"), _event("e1")],
        )


def test_unrecognized_top_level_field_is_rejected_not_silently_dropped():
    """'No arbitrary unvalidated model-produced JSON' — an extra field a
    future model-produced payload might invent must fail loudly, not
    silently pass through as if it were part of the schema."""
    with pytest.raises(ValidationError):
        StructuredClinicalDocument.model_validate(
            {
                "parser_version": "test-v1",
                "document_kind": "discharge_summary",
                "sections": [],
                "some_field_the_model_made_up": "surprise",
            }
        )


@pytest.mark.parametrize(
    "block",
    [
        ParagraphBlock(text="Plain prose."),
        KeyValueBlock(items=[{"key": "Admission date", "value": "2026-03-05"}]),
        DatedEventGroupBlock(event_ids=["e1", "e2"]),
        LabReportReferenceBlock(lab_result_ids=[101, 102]),
        WarningBlock(message="AV 1008 bpm — preserved verbatim, not corrected.", source_evidence_ids=[7]),
    ],
)
def test_each_block_type_round_trips_through_the_discriminated_union(block):
    section = ClinicalSection(
        id="s1",
        canonical_key="clinical_course",
        display_title="Clinical Course",
        order=0,
        blocks=[block],
    )
    doc = StructuredClinicalDocument(parser_version="test-v1", document_kind="discharge_summary", sections=[section])
    reloaded = StructuredClinicalDocument.model_validate_json(doc.model_dump_json())
    assert reloaded.sections[0].blocks[0] == block
    assert type(reloaded.sections[0].blocks[0]) is type(block)


def test_suspicious_value_stays_verbatim_alongside_a_warning_not_replaced():
    """Encodes the 'NEVER silently repair' rule at the data-shape level:
    a WarningBlock carries a message, never a 'corrected' value field —
    there is no field anywhere in this schema whose purpose is to hold a
    fixed-up version of a source fact."""
    warning = WarningBlock(message="AV 1008 bpm — preserved verbatim, not corrected.", source_evidence_ids=[])
    assert not hasattr(warning, "corrected_value")
    assert "1008" in warning.message  # the suspicious value survives verbatim in the warning text itself
