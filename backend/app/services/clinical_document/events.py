"""Clinical Course dated-event construction — Clinical Document
Intelligence V3, Phase 5 (second increment).

Turns dates found by `dates.find_dates_in_text` into real, typed
`ClinicalEvent` instances (schema.py) — deterministic keyword-context
classification for `event_type`, no LLM call anywhere in this module,
per the V3 contract's own instruction.

Hard rule enforced here: **do not infer an encounter when the source
only contains narrative history.** A date with no recognizable
admission/discharge/procedure/etc. keyword nearby classifies as
`event_type="other"` — it is NEVER guessed as "admission" or
"discharge" just because it happens to be the first or only date found.
`event_type` is only ever one of the 7 specific values when a real
keyword signal is present in the surrounding text; `"other"` is the
honest default otherwise.

Suspicious clinical VALUES (not dates — see dates.py for the date half
of this rule) are also never silently repaired here: `find_vital_sign_
warnings` flags an implausible vital sign (e.g. "AV 1008" — a heart
rate of 1008 bpm) as a warning string, but the source text it came from
is never rewritten.
"""

from __future__ import annotations

import re

from app.services.lab_catalog import normalize_text

from .dates import find_dates_in_text
from .schema import ClinicalEvent, EventType

# How far (in characters) around a found date to look for an event-type
# keyword. Deliberately narrow — a keyword this many characters away is
# reasonably attributable to the same clinical mention as the date;
# widening it risks attaching an unrelated sentence's keyword to this
# date instead.
_CONTEXT_WINDOW_CHARS = 60

# Checked in this order — first match wins. "discharge"/"admission"
# checked first since they are the most consequential to get right and
# have the least ambiguous keyword vocabulary.
_EVENT_TYPE_KEYWORDS: tuple[tuple[EventType, tuple[str, ...]], ...] = (
    ("discharge", ("externat", "externare", "iesire din spital", "discharge")),
    ("admission", ("internat", "internare", "admis la", "admission")),
    ("procedure", ("interventie", "operatie", "procedura efectuata", "procedure performed")),
    (
        "treatment_change",
        ("schimbare tratament", "s-a modificat tratamentul", "tratament modificat", "treatment changed"),
    ),
    ("follow_up", ("control", "reevaluare", "vizita de control", "follow-up", "follow up")),
    ("consultation", ("consult", "consultatie", "consultation")),
    ("investigation", ("investigatie", "examinare", "analiza efectuata", "investigation")),
)

# label, regex (one capturing group: the numeric value), plausible min/max
_VITAL_SIGN_PATTERNS: tuple[tuple[str, re.Pattern[str], float, float], ...] = (
    ("heart rate (AV)", re.compile(r"\bAV[:\s]+(\d+(?:[.,]\d+)?)\b", re.IGNORECASE), 20, 300),
    ("respiratory rate (FR)", re.compile(r"\bFR[:\s]+(\d+(?:[.,]\d+)?)\b", re.IGNORECASE), 4, 80),
    ("temperature", re.compile(r"\btemp(?:eratura)?[:\s]+(\d+(?:[.,]\d+)?)\b", re.IGNORECASE), 25, 45),
    # Blood pressure: only the systolic (first) number is checked here —
    # the diastolic figure's own plausible range differs and isn't
    # checked by this pattern; a future increment could add it
    # separately rather than conflating two different thresholds here.
    ("blood pressure systolic (TA)", re.compile(r"\bTA[:\s]+(\d+(?:[.,]\d+)?)\s*/\s*\d+(?:[.,]\d+)?\b", re.IGNORECASE), 40, 300),
)


def classify_event_type_from_context(text: str, date_start: int) -> EventType:
    """Deterministic, no LLM call. Returns `"other"` unless a real
    keyword signal is found in the window around `date_start` — see the
    module's own "do not infer an encounter" rule.

    The text BEFORE the date is checked first, and only if nothing
    matches there is the text AFTER it considered. This matches how
    these mentions actually read in real Romanian clinical text
    ("internat la 10.01.2026", "externat la 20.01.2026, ameliorat") —
    the keyword describing a specific date almost always immediately
    PRECEDES it. Checking a combined before+after window without this
    ordering would misattribute a NEXT sentence's keyword to THIS date
    whenever two dated mentions sit close together (e.g. "Internat la
    D1. Externat la D2." — "externat" is textually closer to D1 than
    "internat" is once the sentence boundary is crossed, but it
    describes D2, not D1) — a real case this ordering was specifically
    added to fix, see the corresponding test."""
    window_start = max(0, date_start - _CONTEXT_WINDOW_CHARS)
    window_end = date_start + _CONTEXT_WINDOW_CHARS
    before = normalize_text(text[window_start:date_start])
    after = normalize_text(text[date_start:window_end])

    for candidate_text in (before, after):
        for event_type, keywords in _EVENT_TYPE_KEYWORDS:
            if any(normalize_text(keyword) in candidate_text for keyword in keywords):
                return event_type
    return "other"


def find_vital_sign_warnings(text: str) -> list[str]:
    """Scans `text` for a small set of common vital-sign mentions and
    flags physiologically implausible values — the value itself is
    NEVER altered; only a warning string is produced, quoting the
    offending text verbatim."""
    warnings: list[str] = []
    for label, pattern, plausible_min, plausible_max in _VITAL_SIGN_PATTERNS:
        for m in pattern.finditer(text):
            raw_value = m.group(1).replace(",", ".")
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if not (plausible_min <= value <= plausible_max):
                warnings.append(
                    f"Implausible {label} value '{m.group(0).strip()}' — preserved verbatim, not corrected."
                )
    return warnings


def build_events_from_segment_text(
    segment_id: str,
    text: str,
    *,
    source_evidence_ids: list[int] | None = None,
) -> tuple[list[ClinicalEvent], list[str]]:
    """Builds one `ClinicalEvent` per date found in `text` (typically one
    Clinical-Course-classified segment's own text). Returns
    `(events, section_level_warnings)` — vital-sign anomalies are
    reported separately from any one event, since a suspicious value is
    not always adjacent to a specific date; callers (see
    `discharge_parser.py`) fold these into the document's own top-level
    `warnings`, not force-attached to an arbitrary event."""
    events: list[ClinicalEvent] = []
    dates = find_dates_in_text(text)
    for index, parsed in enumerate(dates):
        event_type = classify_event_type_from_context(text, parsed.start)
        events.append(
            ClinicalEvent(
                source_event_id=f"{segment_id}-event-{index}",
                raw_date_text=parsed.raw_text,
                normalized_date=parsed.normalized_date,
                date_confidence=parsed.confidence,
                event_type=event_type,
                raw_text=text,
                source_evidence_ids=list(source_evidence_ids or []),
                warnings=list(parsed.warnings),
            )
        )
    section_level_warnings = find_vital_sign_warnings(text)
    return events, section_level_warnings
