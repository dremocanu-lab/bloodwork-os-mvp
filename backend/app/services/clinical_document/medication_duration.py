"""Deterministic medication duration parsing and end-date derivation —
Clinical Document Intelligence V3, Phase 7.

No LLM call anywhere in this module, per the V3 contract's "deterministic
duration parsing" instruction. Represents a parsed duration explicitly
(`ParsedDuration`) rather than immediately reducing everything to an end
date — `derive_end_date` is a separate, deliberate step callers only take
when BOTH a reliable start date and an explicit finite duration exist
(see medication_persistence.py).

Exact interval convention: `[start_date, start_date + duration)`. "2
weeks" is EXACTLY 14 days, never fuzzy. Months use REAL calendar-month
arithmetic via `dateutil.relativedelta` — e.g. `2026-01-31 + 1 month =
2026-02-28` (relativedelta's own deterministic month-end clamping to the
last real day of the target month; never hand-rolled `30 * N` day math).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta

from app.services.lab_catalog import normalize_text

DurationUnit = Literal["days", "weeks", "months"]


@dataclass(frozen=True)
class ParsedDuration:
    raw_text: str
    value: int
    unit: DurationUnit
    # Exact day count for days/weeks — deterministic regardless of
    # calendar position. None for months: a calendar month's real length
    # varies by start date, so `derive_end_date` computes a month-based
    # end date via real calendar arithmetic rather than an approximated
    # day count.
    total_days: int | None


_DAY_UNITS = {"zi", "zile", "day", "days"}
_WEEK_UNITS = {"saptamana", "saptamani", "week", "weeks"}
_MONTH_UNITS = {"luna", "luni", "month", "months"}

# Matched against the RAW token (normalize_text() applied per-candidate
# below) so RO diacritics/casing never cause a miss.
_DURATION_RE = re.compile(r"\b(\d{1,3})\s*([A-Za-zĂÂÎȘȚăâîșț]+)\b")

# An "N days/zile PER MONTH"-shaped phrase describes an ONGOING
# intermittent regimen, not a finite N-day course — this must be checked
# BEFORE treating the same text as a plain duration, so "5 zile pe luna"
# is never misread as a 5-day course (see find_scheme_or_intermittent_marker).
_INTERMITTENT_PER_MONTH_RE = re.compile(
    r"\b\d{1,3}\s*(?:zile|zi|days?)\s*"
    r"(?:pe\s*luna|[îi]n\s*fiecare\s*lun[aă]|per\s*month|each\s*month|monthly)\b",
    re.IGNORECASE,
)

_PRN_MARKERS = ("la nevoie", "daca este nevoie", "prn", "as needed", "when needed")

_SCHEME_MARKERS = (
    "conform schemei",
    "dupa schema",
    "according to scheme",
    "per protocol scheme",
    "curs intermitent",
    "intermittent course",
    "zile alterne",
    "alternate days",
    "alternating days",
)

_INDEFINITE_MARKERS = (
    "pana la control",
    "pana la reevaluare",
    "until follow-up",
    "until follow up",
    "until reevaluation",
    "tratament cronic",
    "continua tratamentul",
    "indefinit",
    "indefinitely",
    "chronic treatment",
)

_TAPER_MARKERS = ("scadere progresiva", "descrestere treptata", "taper", "tapering")


def parse_duration(raw_text: str) -> ParsedDuration | None:
    """Matches the FIRST `<N> <unit>` token pair whose unit is a
    recognized day/week/month word. Returns None for anything else.
    Callers MUST check `find_scheme_or_intermittent_marker` first — this
    function does not itself exclude an "N per month" shape (e.g. "5
    zile pe luna" still contains a `5 zile` token this function would
    otherwise happily parse as a plain 5-day duration)."""
    if not raw_text:
        return None
    for match in _DURATION_RE.finditer(raw_text):
        value = int(match.group(1))
        unit_normalized = normalize_text(match.group(2))
        if unit_normalized in _DAY_UNITS:
            return ParsedDuration(raw_text=match.group(0), value=value, unit="days", total_days=value)
        if unit_normalized in _WEEK_UNITS:
            return ParsedDuration(raw_text=match.group(0), value=value, unit="weeks", total_days=value * 7)
        if unit_normalized in _MONTH_UNITS:
            return ParsedDuration(raw_text=match.group(0), value=value, unit="months", total_days=None)
    return None


def is_intermittent_per_month_phrase(text: str) -> bool:
    return bool(_INTERMITTENT_PER_MONTH_RE.search(text or ""))


def find_prn_marker(text: str) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(marker) in normalized for marker in _PRN_MARKERS)


def find_scheme_or_intermittent_marker(text: str) -> bool:
    if is_intermittent_per_month_phrase(text):
        return True
    normalized = normalize_text(text)
    return any(normalize_text(marker) in normalized for marker in _SCHEME_MARKERS)


def find_indefinite_marker(text: str) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(marker) in normalized for marker in _INDEFINITE_MARKERS)


def find_taper_without_clear_duration(text: str, duration: ParsedDuration | None) -> bool:
    """A taper mention with NO parsed total duration is exactly the case
    the V3 contract wants excluded from end-date derivation. A taper
    mention that DOES carry an explicit total duration (e.g. "taper over
    14 days") is not excluded by this check alone — the taper itself may
    still be genuinely ambiguous for other reasons, but this specific
    guard only fires on the "no clear total duration" case."""
    normalized = normalize_text(text)
    has_taper_marker = any(normalize_text(marker) in normalized for marker in _TAPER_MARKERS)
    return has_taper_marker and duration is None


def derive_end_date(start_iso: str, duration: ParsedDuration) -> str | None:
    """Real calendar arithmetic per the exact V3 contract convention.
    Returns None only if `start_iso` isn't a real ISO date — never
    guesses. Callers are responsible for only calling this when BOTH a
    reliable start date AND an explicit finite duration exist (see
    medication_persistence.py) — this function itself does not apply any
    of the PRN/scheme/indefinite/taper exclusion rules above."""
    try:
        start = date.fromisoformat(start_iso)
    except ValueError:
        return None
    if duration.unit == "months":
        end = start + relativedelta(months=duration.value)
    else:
        end = start + timedelta(days=duration.total_days)
    return end.isoformat()
