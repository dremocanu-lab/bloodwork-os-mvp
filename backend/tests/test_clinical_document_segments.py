"""Tests for Phase 4's segment-aware consolidation —
app/services/clinical_document/segments.py +
canonical_headings.consolidate_segments(). No DB needed."""

from app.services.clinical_document.canonical_headings import consolidate_segments
from app.services.clinical_document.segments import (
    SourceSegment,
    build_segments_from_legacy_discharge_payload,
)


def _seg(index: int, heading: str | None, text: str) -> SourceSegment:
    return SourceSegment(segment_id=f"seg-{index}", index=index, raw_heading=heading, raw_text=text)


# ── build_segments_from_legacy_discharge_payload ────────────────────────


def test_builds_one_segment_per_raw_section_in_order():
    payload = {
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Text A"},
            {"key": "diagnoses", "title": "Diagnostic principal", "body": "K80.2"},
        ]
    }
    segments = build_segments_from_legacy_discharge_payload(payload)
    assert [s.raw_heading for s in segments] == ["EPICRIZĂ", "Diagnostic principal"]
    assert [s.index for s in segments] == [0, 1]
    assert [s.raw_text for s in segments] == ["Text A", "K80.2"]


def test_segment_ids_are_stable_across_repeated_calls_on_the_same_payload():
    """Required for later idempotency (Phase 13) — reprocessing the SAME
    document must produce the SAME segment ids, not random ones."""
    payload = {"sections": [{"key": "epicriza", "title": "EPICRIZĂ", "body": "Text"}]}
    first = build_segments_from_legacy_discharge_payload(payload)
    second = build_segments_from_legacy_discharge_payload(payload)
    assert [s.segment_id for s in first] == [s.segment_id for s in second]


def test_malformed_section_entries_are_skipped_not_a_crash():
    payload = {"sections": [{"key": "epicriza", "title": "EPICRIZĂ", "body": "Text"}, "not a dict", None]}
    segments = build_segments_from_legacy_discharge_payload(payload)
    assert len(segments) == 1


def test_no_sections_produces_no_segments():
    assert build_segments_from_legacy_discharge_payload({"sections": []}) == []
    assert build_segments_from_legacy_discharge_payload({}) == []


# ── consolidate_segments ─────────────────────────────────────────────────


def test_repeated_epicriza_merges_into_one_clinical_course_section_preserving_order_and_headings():
    segments = [
        _seg(0, "EPICRIZĂ", "Pacient internat la 10.01.2026."),
        _seg(1, "Diagnostic principal", "K80.2 Colelitiaza"),
        _seg(2, "EPICRIZĂ (continuare)", "Evolutie favorabila, externat la 20.01.2026."),
    ]
    sections = consolidate_segments(segments)
    by_key = {s.canonical_key: s for s in sections}

    assert set(by_key) == {"clinical_course", "diagnoses"}
    clinical_course = by_key["clinical_course"]
    assert clinical_course.source_headings == ["EPICRIZĂ", "EPICRIZĂ (continuare)"]
    assert clinical_course.source_segment_ids == ["seg-0", "seg-2"]
    assert len(clinical_course.blocks) == 2
    assert clinical_course.blocks[0].text == "Pacient internat la 10.01.2026."
    assert clinical_course.blocks[1].text == "Evolutie favorabila, externat la 20.01.2026."
    # First-occurrence order preserved even with a different-category
    # segment interleaved between the two EPICRIZĂ occurrences.
    assert clinical_course.order == 0
    assert by_key["diagnoses"].order == 1
    assert by_key["diagnoses"].source_segment_ids == ["seg-1"]


def test_repeated_diagnoses_headings_merge_into_one_diagnoses_section():
    segments = [
        _seg(0, "Diagnostic principal", "K80.2 Colelitiaza"),
        _seg(1, "Diagnostic secundar", "E11.9 Diabet zaharat tip 2"),
    ]
    sections = consolidate_segments(segments)
    assert len(sections) == 1
    diagnoses = sections[0]
    assert diagnoses.canonical_key == "diagnoses"
    assert diagnoses.source_headings == ["Diagnostic principal", "Diagnostic secundar"]
    assert len(diagnoses.blocks) == 2
    assert diagnoses.source_segment_ids == ["seg-0", "seg-1"]


def test_repeated_administrative_sections_merge():
    segments = [
        _seg(0, "Date administrative", "CNP: ..., Nume: ..."),
        _seg(1, "Informatii administrative", "Sectie: Cardiologie"),
    ]
    sections = consolidate_segments(segments)
    assert len(sections) == 1
    admin = sections[0]
    assert admin.canonical_key == "administrative_information"
    assert len(admin.blocks) == 2


def test_investigations_imaging_heading_classifies_as_investigations_via_segments():
    segments = [_seg(0, "Investigations / imaging", "CT torace: fara modificari.")]
    sections = consolidate_segments(segments)
    assert len(sections) == 1
    assert sections[0].canonical_key == "investigations"


def test_unknown_heading_falls_back_to_other_via_segments():
    segments = [_seg(0, "Ceva complet necunoscut XYZ", "Text oarecare.")]
    sections = consolidate_segments(segments)
    assert len(sections) == 1
    assert sections[0].canonical_key == "other"


def test_empty_sections_are_dropped_not_prominent():
    """A one-off heading with no real body content must not become a
    hollow canonical section — the V3 contract's own 'empty/non-
    substantive sections should not become prominent canonical
    sections' rule, enforced here (contrast with the older
    merge_headings_into_sections, which does NOT apply this rule and
    keeps its own existing tested behavior unchanged)."""
    segments = [_seg(0, "Semnătura", ""), _seg(1, "  ", "   ")]
    sections = consolidate_segments(segments)
    assert sections == []


def test_a_section_with_at_least_one_non_empty_contributor_is_kept_in_full():
    """An empty contributor to an otherwise-substantive section is NOT
    silently dropped from provenance — its segment id still appears,
    only the section itself survives because SOME contributor had text."""
    segments = [_seg(0, "EPICRIZĂ", ""), _seg(1, "EPICRIZĂ", "Text real aici.")]
    sections = consolidate_segments(segments)
    assert len(sections) == 1
    assert sections[0].source_segment_ids == ["seg-0", "seg-1"]
    assert len(sections[0].blocks) == 1  # only the non-empty contributor produced a block
    assert sections[0].blocks[0].text == "Text real aici."


def test_mixed_romanian_and_english_headings_both_classify_correctly():
    segments = [
        _seg(0, "EPICRIZĂ", "Romanian text."),
        _seg(1, "Recommendations", "Follow up in 2 weeks."),
        _seg(2, "Laboratory Results", "WBC 7.2, normal."),
    ]
    sections = consolidate_segments(segments)
    by_key = {s.canonical_key: s for s in sections}
    assert set(by_key) == {"clinical_course", "recommendations", "laboratory_results"}


def test_original_heading_order_is_reconstructable_from_first_occurrence_order():
    segments = [
        _seg(0, "Administrative information", "A"),
        _seg(1, "EPICRIZĂ", "B"),
        _seg(2, "Diagnostic principal", "C"),
        _seg(3, "Recomandari", "D"),
    ]
    sections = consolidate_segments(segments)
    ordered = sorted(sections, key=lambda s: s.order)
    assert [s.canonical_key for s in ordered] == [
        "administrative_information",
        "clinical_course",
        "diagnoses",
        "recommendations",
    ]


def test_consolidate_segments_from_a_real_legacy_payload_end_to_end():
    """The full segments -> consolidate pipeline against the actual
    current discharge pipeline's payload shape (not hand-built tuples)."""
    payload = {
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Internat 10.01.2026."},
            {"key": "laboratory_normal", "title": "Examen de laborator cu valori normale", "body": "Glicemie 90."},
            {"key": "laboratory_abnormal", "title": "Examen de laborator cu valori patologice", "body": "WBC 15.2 (H)."},
            {"key": "other", "title": "Semnaturi", "body": ""},
        ]
    }
    segments = build_segments_from_legacy_discharge_payload(payload)
    sections = consolidate_segments(segments)
    by_key = {s.canonical_key: s for s in sections}

    assert "clinical_course" in by_key
    assert "laboratory_results" in by_key
    lab = by_key["laboratory_results"]
    assert lab.source_headings == [
        "Examen de laborator cu valori normale",
        "Examen de laborator cu valori patologice",
    ]
    assert len(lab.blocks) == 2
    # The empty "Semnaturi" section was dropped entirely.
    assert "signatures" not in by_key
    assert len(sections) == 2
