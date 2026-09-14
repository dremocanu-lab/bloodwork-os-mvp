"""Deterministic, date-first parsing — Clinical Document Intelligence
V3, Phase 5 (first increment).

Finds and parses date-shaped substrings in Romanian/English clinical
text WITHOUT any LLM call, per the V3 contract's "deterministic
date-first parser... BEFORE any semantic model" instruction. This is a
standalone primitive: turning a block of Clinical Course text into real
`ClinicalEvent` instances (deciding event_type, associating the right
surrounding sentence, medication/procedure mentions, etc.) is a further
Phase 5 increment that BUILDS ON this one — not yet implemented; this
module only answers "what dates are mentioned here, and what do they
normalize to" honestly.

Hard rule enforced here, not just documented: an invalid or ambiguous
date is NEVER silently corrected. `ParsedDate.normalized_date` is `None`
whenever the calendar date is genuinely impossible (e.g. day 31 in
February) — the ORIGINAL text always survives in `raw_text` regardless,
and a human-readable reason is always in `warnings`. Nothing in this
module ever guesses a "probably meant" value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.lab_catalog import normalize_text

# Romanian month names/common abbreviations -> month number. None of
# these carry diacritics in Romanian, but headings/OCR output sometimes
# does anyway (stray combining marks, mixed encodings) — every lookup
# below goes through normalize_text() first for that reason, not because
# these particular words need accent-stripping in principle.
_ROMANIAN_MONTHS: dict[str, int] = {
    "ianuarie": 1,
    "ian": 1,
    "februarie": 2,
    "feb": 2,
    "martie": 3,
    "mar": 3,
    "aprilie": 4,
    "apr": 4,
    "mai": 5,
    "iunie": 6,
    "iun": 6,
    "iulie": 7,
    "iul": 7,
    "august": 8,
    "aug": 8,
    "septembrie": 9,
    "sept": 9,
    "sep": 9,
    "octombrie": 10,
    "oct": 10,
    "noiembrie": 11,
    "noi": 11,
    "nov": 11,
    "decembrie": 12,
    "dec": 12,
}

# DD(.|-|/)MM(.|-|/)YYYY or YY — the separator must match on both sides
# (a real "10.01/2026" typo is NOT silently accepted as if it were
# well-formed; it simply won't match and is treated as not a date here).
_NUMERIC_DATE_RE = re.compile(r"\b(?P<day>\d{1,2})(?P<sep>[.\-/])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{2,4})\b")

# D MonthName YYYY (Romanian convention — no comma, day before month name).
_NAMED_MONTH_DATE_RE = re.compile(r"\b(?P<day>\d{1,2})\s+(?P<month_name>[^\W\d_]+)\s+(?P<year>\d{4})\b", re.UNICODE)


@dataclass(frozen=True)
class ParsedDate:
    """One date-shaped substring and Bragi's own interpretation of it —
    the two are always kept distinguishable (see the module docstring's
    "never silently repair" rule)."""

    raw_text: str
    start: int
    normalized_date: str | None  # ISO YYYY-MM-DD, or None if genuinely invalid/unparseable
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _try_build_iso_date(day: int, month: int, year: int) -> tuple[str | None, list[str]]:
    try:
        return date(year, month, day).isoformat(), []
    except ValueError:
        return (
            None,
            [
                f"Invalid calendar date (day={day}, month={month}, year={year}) "
                "— preserved verbatim in raw_text, not corrected or guessed."
            ],
        )


def _normalize_year(year_str: str) -> tuple[int, list[str]]:
    year = int(year_str)
    if len(year_str) == 2:
        # A 2-digit year's century is genuinely ambiguous — assumed to be
        # 20xx (every real document this app processes is contemporary),
        # but that assumption is never presented as a confirmed fact: a
        # warning always accompanies it and callers should weight
        # confidence accordingly (see parse_date_token's own scoring).
        assumed = 2000 + year
        return assumed, [f"2-digit year '{year_str}' assumed to mean {assumed} — not verified against the source."]
    return year, []


def parse_date_token(raw_text: str, *, start: int = 0) -> ParsedDate | None:
    """Attempts to parse ONE already-isolated date-shaped string (e.g.
    one match from `find_dates_in_text`). Returns `None` if `raw_text`
    doesn't match either supported date shape at all — never raises."""
    text = raw_text.strip()
    if not text:
        return None

    m = _NUMERIC_DATE_RE.fullmatch(text)
    if m:
        day = int(m.group("day"))
        month = int(m.group("month"))
        year, year_warnings = _normalize_year(m.group("year"))
        normalized, date_warnings = _try_build_iso_date(day, month, year)
        warnings = year_warnings + date_warnings
        confidence = 0.95 if not warnings else 0.55
        return ParsedDate(raw_text=text, start=start, normalized_date=normalized, confidence=confidence, warnings=tuple(warnings))

    m = _NAMED_MONTH_DATE_RE.fullmatch(text)
    if m:
        day = int(m.group("day"))
        month = _ROMANIAN_MONTHS.get(normalize_text(m.group("month_name")))
        if month is None:
            return None  # not a recognized month name — not a date shape at all
        year = int(m.group("year"))
        normalized, warnings = _try_build_iso_date(day, month, year)
        confidence = 0.95 if not warnings else 0.55
        return ParsedDate(raw_text=text, start=start, normalized_date=normalized, confidence=confidence, warnings=tuple(warnings))

    return None


def find_dates_in_text(text: str) -> list[ParsedDate]:
    """Scans free text for every date-shaped substring, returned in
    document order. Does NOT deduplicate — the same date mentioned twice
    in one section is reported twice, since a later event-extraction
    increment may need each occurrence's own surrounding context."""
    if not text:
        return []

    candidates: list[ParsedDate] = []
    for pattern in (_NUMERIC_DATE_RE, _NAMED_MONTH_DATE_RE):
        for m in pattern.finditer(text):
            parsed = parse_date_token(m.group(0), start=m.start())
            if parsed is not None:
                candidates.append(parsed)

    candidates.sort(key=lambda p: p.start)
    return candidates
