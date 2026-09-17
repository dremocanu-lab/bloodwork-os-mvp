"""Tests for Phase 5's real ClinicalEvent construction —
app/services/clinical_document/events.py. No DB needed."""

from app.services.clinical_document.events import (
    build_events_from_segment_text,
    classify_event_type_from_context,
    find_vital_sign_warnings,
)


# ── classify_event_type_from_context ────────────────────────────────────


def test_admission_keyword_near_date_classifies_as_admission():
    text = "Pacientul a fost internat la 10.01.2026 pentru dureri abdominale."
    date_start = text.index("10.01.2026")
    assert classify_event_type_from_context(text, date_start) == "admission"


def test_discharge_keyword_near_date_classifies_as_discharge():
    text = "Pacientul a fost externat la 20.01.2026, stare ameliorata."
    date_start = text.index("20.01.2026")
    assert classify_event_type_from_context(text, date_start) == "discharge"


def test_follow_up_keyword_near_date_classifies_as_follow_up():
    text = "Control programat la 15.02.2026."
    date_start = text.index("15.02.2026")
    assert classify_event_type_from_context(text, date_start) == "follow_up"


def test_no_keyword_near_a_narrative_date_classifies_as_other_not_an_encounter():
    """The V3 contract's own rule: do not infer an encounter when the
    source only contains narrative history. A date mentioned in passing
    with no admission/discharge/procedure/etc. signal must NOT be
    guessed into one of those categories."""
    text = "Pacientul mentioneaza ca a avut un episod similar in 10.01.2020, fara alte detalii."
    date_start = text.index("10.01.2020")
    assert classify_event_type_from_context(text, date_start) == "other"


def test_adjacent_admission_and_discharge_dates_each_classify_independently():
    """Real regression: with both dates close together, a naive
    'search the whole window, category-priority wins' approach
    misattributes the SECOND sentence's keyword ('externat') to the
    FIRST date too, since it falls within that date's window. Checking
    the immediately-preceding text first (matching how these mentions
    actually read) fixes this — each date must get its OWN correct
    event_type, not both collapsing to the same one."""
    text = "Internat la 10.01.2026. Externat la 20.01.2026, ameliorat."
    admission_date_start = text.index("10.01.2026")
    discharge_date_start = text.index("20.01.2026")
    assert classify_event_type_from_context(text, admission_date_start) == "admission"
    assert classify_event_type_from_context(text, discharge_date_start) == "discharge"


def test_keyword_far_outside_the_context_window_does_not_attach():
    # Neutral filler with no keyword substrings, long enough to push
    # "internat" more than the 60-char context window away from the date.
    filler = (
        "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
        "tempor incididunt ut labore et dolore magna aliqua"
    )
    text = f"Pacient internat. {filler} Data notata separat: 10.01.2026."
    date_start = text.index("10.01.2026")
    assert classify_event_type_from_context(text, date_start) == "other"


# ── find_vital_sign_warnings ─────────────────────────────────────────────


def test_implausible_heart_rate_is_flagged_verbatim():
    text = "Status la internare: AV 1008 bpm, TA 120/80 mmHg."
    warnings = find_vital_sign_warnings(text)
    assert any("AV 1008" in w for w in warnings)
    assert any("Implausible heart rate" in w for w in warnings)


def test_plausible_vitals_produce_no_warnings():
    text = "Status: AV 78 bpm, TA 120/80 mmHg, FR 16/min, temp 36.6."
    assert find_vital_sign_warnings(text) == []


def test_text_with_no_vitals_produces_no_warnings():
    assert find_vital_sign_warnings("Pacientul se simte bine, fara acuze.") == []


def test_vital_sign_value_is_never_rewritten_only_flagged():
    text = "AV 1008 bpm la internare."
    warnings = find_vital_sign_warnings(text)
    assert len(warnings) == 1
    assert "1008" in warnings[0]  # the implausible value survives verbatim in the warning itself


# ── build_events_from_segment_text ──────────────────────────────────────


def test_builds_one_event_per_date_with_unique_ids():
    text = "Internat la 10.01.2026. Externat la 20.01.2026, ameliorat."
    events, warnings = build_events_from_segment_text("seg-0", text)
    assert len(events) == 2
    assert events[0].source_event_id != events[1].source_event_id
    assert events[0].event_type == "admission"
    assert events[0].normalized_date == "2026-01-10"
    assert events[1].event_type == "discharge"
    assert events[1].normalized_date == "2026-01-20"
    assert warnings == []


def test_events_carry_the_full_segment_text_as_raw_text_and_propagate_evidence_ids():
    text = "Internat la 10.01.2026."
    events, _ = build_events_from_segment_text("seg-7", text, source_evidence_ids=[42, 43])
    assert len(events) == 1
    assert events[0].raw_text == text
    assert events[0].source_evidence_ids == [42, 43]
    assert events[0].source_event_id.startswith("seg-7-event-")


def test_no_dates_in_segment_produces_no_events():
    events, warnings = build_events_from_segment_text("seg-0", "Pacientul se simte bine.")
    assert events == []
    assert warnings == []


def test_suspicious_date_within_an_event_carries_its_own_warning_not_corrected():
    """The V3 contract's fixture example: a future-looking source date
    (14/09/3036) inside Clinical Course text must survive into the
    resulting event's own normalized_date and warnings, never silently
    fixed."""
    text = "Control programat la 14/09/3036 (data neobisnuita in document)."
    events, _ = build_events_from_segment_text("seg-0", text)
    assert len(events) == 1
    assert events[0].normalized_date == "3036-09-14"
    assert any("outside the plausible range" in w for w in events[0].warnings)


def test_vital_sign_warnings_are_returned_separately_from_events():
    text = "Internat la 10.01.2026. AV 1008 bpm la internare."
    events, section_warnings = build_events_from_segment_text("seg-0", text)
    assert len(events) == 1
    # The vital-sign warning is NOT force-attached to the one event —
    # it's a section-level finding the caller decides how to fold in.
    assert not any("Implausible" in w for w in events[0].warnings)
    assert any("Implausible heart rate" in w for w in section_warnings)
