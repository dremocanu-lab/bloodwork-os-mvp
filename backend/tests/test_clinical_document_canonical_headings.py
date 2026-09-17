"""Tests for the Phase 4 deterministic canonical-heading classifier —
app/services/clinical_document/canonical_headings.py. Pure function
tests, no DB needed."""

import pytest

from app.services.clinical_document.canonical_headings import (
    classify_canonical_heading,
    merge_headings_into_sections,
)


# The V3 contract's own worked examples — these MUST classify exactly as
# specified, not merely "reasonably."
@pytest.mark.parametrize(
    "raw_heading,expected_canonical_key",
    [
        ("EPICRIZĂ", "clinical_course"),
        ("Epicriza", "clinical_course"),
        ("TRATAMENT RECOMANDAT", "recommendations"),
        ("REȚETE ELIBERATE", "prescriptions"),
        ("EXAMENE DE LABORATOR", "laboratory_results"),
        ("DIAGNOSTIC PRINCIPAL", "diagnoses"),
        ("DIAGNOSTIC SECUNDAR", "diagnoses"),
    ],
)
def test_contracts_own_worked_examples_classify_exactly_as_specified(raw_heading, expected_canonical_key):
    assert classify_canonical_heading(raw_heading) == expected_canonical_key


def test_unrecognized_heading_falls_back_to_other():
    assert classify_canonical_heading("Ceva complet necunoscut XYZ123") == "other"


def test_empty_or_none_heading_falls_back_to_other():
    assert classify_canonical_heading("") == "other"
    assert classify_canonical_heading(None) == "other"


def test_discharge_medications_is_distinguished_from_generic_medications():
    """More specific phrase must win over the broader category it would
    otherwise also match as a substring."""
    assert classify_canonical_heading("Medicație la externare") == "discharge_medications"
    assert classify_canonical_heading("Medicamente") == "medications"


def test_recommended_treatment_does_not_collide_with_generic_treatment():
    assert classify_canonical_heading("Tratament recomandat") == "recommendations"
    assert classify_canonical_heading("Tratament administrat în timpul internării") == "treatment"


def test_investigations_imaging_compound_heading_prefers_investigations():
    """Real regression: the CURRENT discharge pipeline's own fallback
    title for its legacy "investigations" key is literally
    "Investigations / imaging" (see discharge_summary_pipeline.py's
    SECTION_TITLE_BY_KEY) — this exact compound heading must classify as
    investigations, not imaging, or a real existing document's section
    would silently reclassify under the wrong canonical key."""
    assert classify_canonical_heading("Investigations / imaging") == "investigations"


def test_imaging_specific_modality_headings_still_classify_as_imaging():
    assert classify_canonical_heading("Ecografie abdominală") == "imaging"
    assert classify_canonical_heading("Radiologie") == "imaging"


def test_case_and_diacritics_insensitive():
    assert classify_canonical_heading("epicriză") == "clinical_course"
    assert classify_canonical_heading("EpIcRiZa") == "clinical_course"
    assert classify_canonical_heading("reţete eliberate") == "prescriptions"


# ── merge_headings_into_sections ────────────────────────────────────────


def test_repeated_real_headings_merge_into_one_canonical_section_preserving_both_texts():
    """The general form of the V3 contract's own worked lab example
    (EXAMENE DE LABORATOR appearing more than once across pages) —
    exercised here against TWO real, differently-worded EPICRIZĂ
    occurrences, which is the contract's actual named scenario
    ("repeated source headings such as multiple EPICRIZĂ segments")."""
    sections = merge_headings_into_sections(
        [
            ("EPICRIZĂ", "Pacient internat la data de 10.01.2026 pentru dureri abdominale."),
            ("Diagnostic principal", "K80.2 Colelitiază"),
            ("EPICRIZĂ (continuare)", "Evoluție favorabilă sub tratament, externat la 20.01.2026."),
        ]
    )

    by_key = {s.canonical_key: s for s in sections}
    assert set(by_key.keys()) == {"clinical_course", "diagnoses"}

    clinical_course = by_key["clinical_course"]
    assert clinical_course.source_headings == ["EPICRIZĂ", "EPICRIZĂ (continuare)"]
    assert len(clinical_course.blocks) == 2
    assert clinical_course.blocks[0].text.startswith("Pacient internat")
    assert clinical_course.blocks[1].text.startswith("Evoluție favorabilă")
    # First-occurrence order is preserved even though "Diagnostic
    # principal" (a different canonical section) was interleaved between
    # the two EPICRIZĂ occurrences in the source document.
    assert clinical_course.order == 0
    assert by_key["diagnoses"].order == 1


def test_merged_section_ids_are_stable_and_unique():
    sections = merge_headings_into_sections(
        [("EPICRIZĂ", "Text A"), ("Diagnostic principal", "Text B"), ("EPICRIZĂ", "Text C")]
    )
    ids = [s.id for s in sections]
    assert len(ids) == len(set(ids))


def test_a_section_with_no_body_text_still_produces_a_section_with_no_blocks():
    sections = merge_headings_into_sections([("Semnătura", "")])
    assert len(sections) == 1
    assert sections[0].canonical_key == "signatures"
    assert sections[0].blocks == []


def test_classifier_correctly_handles_every_real_legacy_fallback_title():
    """Every fallback title discharge_summary_pipeline.py's own
    SECTION_TITLE_BY_KEY actually produces today (used whenever the
    model didn't supply its own page-level title) — verified against
    hardcoded expected canonical keys chosen the same way
    persistence.py's backward-compat upconversion path documents its own
    reasoning (see that module's docstring), now that both paths share
    THIS classifier as their one implementation rather than maintaining
    two separate mappings that could silently drift apart."""
    expected_canonical_key_by_fallback_title = {
        "Administrative information": "administrative_information",
        "Diagnoses": "diagnoses",
        "Discharge status": "encounter_details",
        "EPICRIZA": "clinical_course",
        "Investigations / imaging": "investigations",
        "Consults": "other",
        "Examen de laborator cu valori normale": "laboratory_results",
        "Examen de laborator cu valori patologice": "laboratory_results",
        "Tratament administrat in timpul internarii": "treatment",
        "Tratament recomandat": "recommendations",
        "Retete eliberate": "prescriptions",
        "Recomandari": "recommendations",
        "Other": "other",
    }
    for title, expected in expected_canonical_key_by_fallback_title.items():
        actual = classify_canonical_heading(title)
        assert actual == expected, f"{title!r}: expected {expected!r}, classifier says {actual!r}"


def test_merged_sections_are_auto_review_state_not_needs_review():
    """Distinguishes THIS (a real, deterministic classification of an
    actual heading) from persistence.py's legacy upconversion (which
    honestly marks its output needs_review, since it's a coarser
    backward-compat stopgap operating on the OLD 13-key vocabulary, not
    real heading text)."""
    sections = merge_headings_into_sections([("EPICRIZĂ", "Text")])
    assert sections[0].review_state == "auto"
