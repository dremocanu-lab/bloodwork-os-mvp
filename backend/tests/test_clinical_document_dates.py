"""Tests for the Phase 5 deterministic date-first parser —
app/services/clinical_document/dates.py. Pure function tests, no DB
needed."""

import pytest

from app.services.clinical_document.dates import find_dates_in_text, parse_date_token


@pytest.mark.parametrize("raw,expected_iso", [
    ("10.01.2026", "2026-01-10"),
    ("10/01/2026", "2026-01-10"),
    ("10-01-2026", "2026-01-10"),
    ("1.1.2026", "2026-01-01"),
])
def test_numeric_date_forms_parse_with_high_confidence_and_no_warnings(raw, expected_iso):
    parsed = parse_date_token(raw)
    assert parsed is not None
    assert parsed.normalized_date == expected_iso
    assert parsed.confidence >= 0.9
    assert parsed.warnings == ()
    assert parsed.raw_text == raw  # verbatim, never reformatted


def test_mismatched_separators_are_not_treated_as_a_date():
    """'10.01/2026' is malformed — never guessed into a date anyway."""
    assert parse_date_token("10.01/2026") is None


@pytest.mark.parametrize("raw,expected_iso", [
    ("10 ianuarie 2026", "2026-01-10"),
    ("10 Ianuarie 2026", "2026-01-10"),
    ("5 august 2025", "2025-08-05"),
    ("20 dec 2025", "2025-12-20"),
])
def test_romanian_named_month_dates_parse_correctly(raw, expected_iso):
    parsed = parse_date_token(raw)
    assert parsed is not None
    assert parsed.normalized_date == expected_iso
    assert parsed.confidence >= 0.9


def test_unrecognized_month_name_is_not_treated_as_a_date():
    assert parse_date_token("10 blorbuary 2026") is None


def test_two_digit_year_is_assumed_not_confirmed():
    """The V3 contract's own 'never silently repair' spirit applied to
    dates: a 2-digit year's century is genuinely ambiguous. The
    assumption is made (2000+YY, since every real document here is
    contemporary) but ALWAYS flagged — never presented as a verified
    fact — and confidence must reflect the reduced certainty."""
    parsed = parse_date_token("10.01.26")
    assert parsed is not None
    assert parsed.normalized_date == "2026-01-10"
    assert parsed.confidence < 0.9
    assert any("assumed" in w for w in parsed.warnings)


def test_invalid_calendar_date_is_preserved_verbatim_never_corrected():
    """The contract's explicit 'NEVER silently repair suspicious dates'
    rule: February 31st does not exist. This must NOT be silently
    reinterpreted as, say, February 28th or March 3rd — normalized_date
    must be None, raw_text must survive exactly as written, and a
    warning must explain why."""
    parsed = parse_date_token("31.02.2026")
    assert parsed is not None
    assert parsed.raw_text == "31.02.2026"
    assert parsed.normalized_date is None
    assert any("Invalid calendar date" in w for w in parsed.warnings)
    assert parsed.confidence < 0.9


def test_implausible_future_year_is_flagged_but_normalized_date_is_kept():
    """The V3 contract's own fixture example: '14/09/3036' — calendrically
    VALID (date(3036, 9, 14) constructs fine) but chronologically absurd
    for a clinical record. Unlike an invalid calendar date, this must NOT
    null out normalized_date — the contract says such a date 'may
    produce warnings but must never be corrected', meaning the value
    itself survives, just flagged."""
    parsed = parse_date_token("14/09/3036")
    assert parsed is not None
    assert parsed.normalized_date == "3036-09-14"
    assert parsed.raw_text == "14/09/3036"
    assert any("outside the plausible range" in w for w in parsed.warnings)
    assert parsed.confidence < 0.9


def test_implausible_past_year_is_also_flagged_but_kept():
    parsed = parse_date_token("01.01.1850")
    assert parsed is not None
    assert parsed.normalized_date == "1850-01-01"
    assert any("outside the plausible range" in w for w in parsed.warnings)


def test_plausible_year_boundary_does_not_warn():
    parsed = parse_date_token("01.01.1900")
    assert parsed is not None
    assert parsed.warnings == ()


def test_invalid_month_number_is_also_preserved_not_corrected():
    parsed = parse_date_token("10.13.2026")  # month 13 doesn't exist
    assert parsed is not None
    assert parsed.normalized_date is None
    assert any("Invalid calendar date" in w for w in parsed.warnings)


def test_empty_or_non_date_text_returns_none_not_a_crash():
    assert parse_date_token("") is None
    assert parse_date_token("not a date at all") is None
    assert parse_date_token("Hemoglobina 13.5 g/dL") is None


# ── find_dates_in_text ───────────────────────────────────────────────────


def test_find_dates_in_text_returns_empty_list_for_no_dates():
    assert find_dates_in_text("") == []
    assert find_dates_in_text("Pacientul se simte bine, fara acuze.") == []


def test_find_dates_in_text_finds_multiple_dates_in_document_order():
    text = "Internat la 10.01.2026 pentru dureri abdominale. Externat la 20 ianuarie 2026, ameliorat."
    dates = find_dates_in_text(text)
    assert [d.normalized_date for d in dates] == ["2026-01-10", "2026-01-20"]
    # Document order, not pattern-registration order — the numeric match
    # occurs before the named-month match in this text.
    assert dates[0].start < dates[1].start


def test_find_dates_in_text_does_not_false_positive_on_lab_value_ranges():
    """A reference range like '0.7-1.3' or a lab value like '10.5/2026'-
    shaped decimal must never be mistaken for a date."""
    text = "Creatinina 0.9 mg/dL (interval 0.7-1.3), Glicemie 95 mg/dL."
    assert find_dates_in_text(text) == []


def test_find_dates_in_text_does_not_deduplicate_repeated_dates():
    """The same date mentioned twice is reported twice — a later event-
    extraction step may need each occurrence's own surrounding
    sentence."""
    text = "Vizita din 10.01.2026. Control tot la 10.01.2026 (aceeasi zi, doua notari)."
    dates = find_dates_in_text(text)
    assert len(dates) == 2
    assert all(d.normalized_date == "2026-01-10" for d in dates)


def test_find_dates_in_text_preserves_an_invalid_date_alongside_valid_ones():
    text = "Internat 10.01.2026. Data eronata in document: 31.02.2026. Externat 20.01.2026."
    dates = find_dates_in_text(text)
    normalized = [d.normalized_date for d in dates]
    assert normalized == ["2026-01-10", None, "2026-01-20"]
