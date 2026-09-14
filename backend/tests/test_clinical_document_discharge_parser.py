"""End-to-end tests for the Phase 4+5 orchestration —
app/services/clinical_document/discharge_parser.py. No DB needed (this
module never touches the DB itself — it operates on the same raw
payload dict shape discharge_summary_pipeline.py already produces)."""

from app.services.clinical_document.discharge_parser import (
    PARSER_VERSION,
    parse_legacy_discharge_payload,
)


def test_produces_a_real_validated_structured_document_not_the_backward_compat_label():
    payload = {
        "document_type": "discharge_summary",
        "hospital_name": "Spitalul Județean",
        "admission_date": "10.01.2026",
        "discharge_date": "20.01.2026",
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Internat la 10.01.2026 pentru dureri abdominale."},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert doc.parser_version == PARSER_VERSION
    assert doc.parser_version != "legacy-discharge-upconversion-v1"
    assert doc.document_kind.value == "discharge_summary"
    assert doc.metadata.hospital_name == "Spitalul Județean"


def test_sections_and_events_are_both_produced_from_the_same_clinical_course_text():
    payload = {
        "document_type": "discharge_summary",
        "admission_date": "10.01.2026",
        "discharge_date": "20.01.2026",
        "sections": [
            {
                "key": "epicriza",
                "title": "EPICRIZĂ",
                "body": "Internat la 10.01.2026 pentru dureri abdominale. Externat la 20.01.2026, ameliorat.",
            },
            {"key": "diagnoses", "title": "Diagnostic principal", "body": "K80.2 Colelitiaza"},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)

    by_key = {s.canonical_key: s for s in doc.sections}
    assert "clinical_course" in by_key
    assert "diagnoses" in by_key

    assert len(doc.dated_events) == 2
    assert {e.event_type for e in doc.dated_events} == {"admission", "discharge"}
    # No event was fabricated from the diagnoses section (it has no date
    # at all, but this also proves event extraction stayed scoped to
    # event-bearing canonical sections).
    assert all(e.raw_date_text in ("10.01.2026", "20.01.2026") for e in doc.dated_events)


def test_event_provenance_points_back_to_the_originating_segment_not_just_a_heading():
    payload = {
        "document_type": "discharge_summary",
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Internat la 10.01.2026."},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert len(doc.dated_events) == 1
    event = doc.dated_events[0]
    # source_event_id is derived from the real segment id, not a bare
    # counter — the exact originating segment is reconstructable from it.
    assert event.source_event_id.startswith("seg-000-")


def test_administrative_section_dates_do_not_become_fabricated_events():
    """A date appearing in an administrative/identity section (e.g. a
    birth date) must NOT be turned into a ClinicalEvent — event
    extraction is deliberately scoped to event-bearing canonical
    sections only."""
    payload = {
        "document_type": "discharge_summary",
        "sections": [
            {"key": "administrative_information", "title": "Date administrative", "body": "Data nasterii: 05.03.1980."},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert doc.dated_events == []


# ── The three fixture examples that must survive unchanged ──────────────


def test_future_looking_source_date_survives_unchanged_with_a_warning():
    """'14/09/3036' — calendrically valid, chronologically absurd. Must
    produce a warning but the date itself must never be corrected."""
    payload = {
        "document_type": "discharge_summary",
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Control programat la 14/09/3036 (data neobisnuita)."},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert len(doc.dated_events) == 1
    event = doc.dated_events[0]
    assert event.raw_date_text == "14/09/3036"
    assert event.normalized_date == "3036-09-14"
    assert any("outside the plausible range" in w for w in event.warnings)


def test_chronologically_misplaced_control_is_flagged_not_corrected():
    """A 'control' dated 2024, appearing in a document whose recorded
    admission/discharge window is entirely in 2026, must be flagged as
    chronologically inconsistent — never silently dropped, never
    silently moved into the window."""
    payload = {
        "document_type": "discharge_summary",
        "admission_date": "10.01.2026",
        "discharge_date": "20.01.2026",
        "sections": [
            {
                "key": "epicriza",
                "title": "EPICRIZĂ",
                "body": (
                    "Internat la 10.01.2026 pentru dureri abdominale. "
                    "Control anterior la 05.03.2024, fara modificari semnificative. "
                    "Externat la 20.01.2026, ameliorat."
                ),
            },
        ],
    }
    doc = parse_legacy_discharge_payload(payload)

    misplaced = [e for e in doc.dated_events if e.normalized_date == "2024-03-05"]
    assert len(misplaced) == 1
    assert misplaced[0].event_type == "follow_up"
    # The event itself is untouched — its own normalized_date and
    # warnings carry nothing chronology-related; the flag is a
    # document-level finding instead.
    assert doc.warnings  # non-empty
    chronology_warnings = [w for w in doc.warnings if "admission-discharge window" in w]
    assert len(chronology_warnings) == 1
    assert "Event dated 2024-03-05" in chronology_warnings[0]
    # The other two events (within the window) must NOT ALSO be flagged
    # as their own separate chronology warning (only the ONE misplaced
    # event should be — the window bounds 2026-01-10/2026-01-20
    # legitimately appear as descriptive text inside that one warning).
    assert not any(w.startswith("Event dated 2026-01-10") for w in doc.warnings)
    assert not any(w.startswith("Event dated 2026-01-20") for w in doc.warnings)


def test_impossible_looking_vital_sign_is_flagged_not_corrected():
    """'AV 1008 bpm' must survive verbatim, only flagged with a warning
    — never silently rewritten to a plausible value."""
    payload = {
        "document_type": "discharge_summary",
        "sections": [
            {
                "key": "epicriza",
                "title": "EPICRIZĂ",
                "body": "Internat la 10.01.2026. Status obiectiv: AV 1008 bpm, TA 120/80 mmHg.",
            },
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert any("AV 1008" in w and "Implausible" in w for w in doc.warnings)
    # The event itself still exists and is otherwise unaffected.
    assert len(doc.dated_events) == 1
    assert doc.dated_events[0].event_type == "admission"


def test_no_chronology_warning_when_admission_or_discharge_date_is_unknown():
    """With only one (or neither) bound known, no window comparison is
    attempted — never guessing the missing bound."""
    payload = {
        "document_type": "discharge_summary",
        "admission_date": "10.01.2026",
        # discharge_date deliberately omitted
        "sections": [
            {"key": "epicriza", "title": "EPICRIZĂ", "body": "Control la 05.03.2024."},
        ],
    }
    doc = parse_legacy_discharge_payload(payload)
    assert not any("admission-discharge window" in w for w in doc.warnings)
