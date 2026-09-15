"""Focused tests for deterministic medication duration parsing and
end-date derivation — Clinical Document Intelligence V3, Phase 7. Pure
(no DB)."""

from app.services.clinical_document.medication_duration import (
    derive_end_date,
    find_indefinite_marker,
    find_prn_marker,
    find_scheme_or_intermittent_marker,
    find_taper_without_clear_duration,
    parse_duration,
)


def test_days_parsed():
    for text, expected in [("3 zile", 3), ("5 zile", 5), ("7 zile", 7), ("10 zile", 10), ("14 zile", 14)]:
        d = parse_duration(text)
        assert d is not None
        assert d.unit == "days"
        assert d.total_days == expected


def test_english_days_parsed():
    d = parse_duration("14 days")
    assert d.unit == "days"
    assert d.total_days == 14


def test_weeks_parsed_as_exactly_14_days():
    for text in ("2 saptamani", "2 săptămâni", "2 weeks"):
        d = parse_duration(text)
        assert d.unit == "weeks"
        assert d.total_days == 14


def test_months_parsed_romanian_and_english():
    for text, expected_value in [("1 luna", 1), ("1 luna", 1), ("3 luni", 3), ("1 month", 1), ("3 months", 3)]:
        d = parse_duration(text)
        assert d.unit == "months"
        assert d.value == expected_value
        assert d.total_days is None  # never approximated as N*30


def test_start_plus_14_days_equals_expected_end_date():
    duration = parse_duration("14 zile")
    assert derive_end_date("2026-03-05", duration) == "2026-03-19"


def test_two_weeks_is_exactly_14_days_not_fuzzy():
    duration = parse_duration("2 weeks")
    assert derive_end_date("2026-03-05", duration) == "2026-03-19"


def test_calendar_month_arithmetic_real_not_30_days():
    duration = parse_duration("1 month")
    # 2026-02-05 + 1 month = 2026-03-05 (28 days later, NOT 30) — proves
    # real calendar-month arithmetic, not `30 * N` day math.
    assert derive_end_date("2026-02-05", duration) == "2026-03-05"


def test_jan_31_plus_one_month_is_deterministic_relativedelta_behavior():
    duration = parse_duration("1 month")
    # dateutil.relativedelta's own documented, deterministic month-end
    # clamping — 2026 is not a leap year, so Feb has 28 days.
    assert derive_end_date("2026-01-31", duration) == "2026-02-28"


def test_prn_marker_detected_romanian_and_english():
    assert find_prn_marker("Paracetamol 500mg la nevoie") is True
    assert find_prn_marker("Ibuprofen 400mg PRN") is True
    assert find_prn_marker("Ibuprofen 400mg as needed") is True
    assert find_prn_marker("Metformin 500mg 1-0-1") is False


def test_scheme_marker_detected():
    assert find_scheme_or_intermittent_marker("conform schemei oncologice") is True
    assert find_scheme_or_intermittent_marker("according to scheme") is True
    assert find_scheme_or_intermittent_marker("Metformin 500mg zilnic") is False


def test_n_days_per_month_is_intermittent_not_a_plain_duration():
    """The critical precision guard: '5 zile pe luna' must NEVER be
    misread as a 5-day course — it describes an ongoing monthly
    intermittent regimen."""
    text = "BESREMI 250mcg subcutanat, 5 zile pe luna"
    assert find_scheme_or_intermittent_marker(text) is True


def test_indefinite_marker_detected():
    assert find_indefinite_marker("continua tratamentul pana la control") is True
    assert find_indefinite_marker("until follow-up") is True
    assert find_indefinite_marker("Metformin 500mg 1-0-1") is False


def test_taper_without_duration_flagged():
    assert find_taper_without_clear_duration("scadere progresiva a dozei", None) is True


def test_taper_with_explicit_duration_not_flagged_by_this_check():
    duration = parse_duration("14 zile")
    assert find_taper_without_clear_duration("taper over 14 zile", duration) is False


def test_invalid_start_date_returns_none_not_a_crash():
    duration = parse_duration("14 zile")
    assert derive_end_date("not-a-date", duration) is None


def test_no_duration_match_for_plain_dose_text():
    assert parse_duration("Metformin 500mg") is None
