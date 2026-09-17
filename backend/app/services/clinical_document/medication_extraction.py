"""Medication candidate extraction — Clinical Document Intelligence V3,
Phase 7.

Turns a medication-bearing canonical section's raw text (or a Phase 5
`treatment_change` `ClinicalEvent`'s own text) into typed, not-yet-
canonical `MedicationCandidate`s — the same discipline Phase 6 used for
labs: a typed intermediate, never a direct ORM mutation while reading
text, never a second persisted datastore. Nothing here writes to the
database or touches `PatientMedication` — that happens in
`medication_persistence.py`.

Scope (per the V3 contract's Phase 7 text): extraction only looks at
`treatment`, `medications`, `discharge_medications`, `recommendations`,
and `prescriptions` canonical sections (`MEDICATION_BEARING_CANONICAL_
KEYS`), plus `treatment_change`-classified Clinical Course events (Phase
5's own classification, reused — NOT independently re-segmented here;
see events.py). `medical_history` and every other section are
deliberately never scanned — a historical medication mention there is
excluded by never being extraction input at all, not by a runtime
guess.

Precision over recall throughout: a mention discussing an allergy, a
refusal, a hypothetical, or a family member's medication is excluded
entirely (`_is_excluded_context`) rather than persisted as an uncertain
row — persisting something is a stronger claim than staying silent, and
the V3 contract's own list of things that must NOT automatically become
a current medication is explicit about this.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.services.lab_catalog import normalize_text

from . import medication_duration
from .dates import find_dates_in_text
from .events import ClinicalEvent
from .schema import CanonicalSectionKey
from .segments import SourceSegment

MEDICATION_BEARING_CANONICAL_KEYS: frozenset[str] = frozenset(
    {"treatment", "medications", "discharge_medications", "recommendations", "prescriptions"}
)

MedicationContext = Literal[
    "started",
    "continued",  # covers "current/active" — ongoing as of this document
    "stopped",
    "paused",
    "completed",  # course finished as planned — distinct from "stopped" (interrupted)
    "prescribed",  # a prescription was issued; administration is NOT confirmed
    "historical",
    "uncertain",
]

StartDateSemantics = Literal[
    "explicit",
    "start_today_at_encounter",
    "discharge_recommendation",
    "prescription_issue_date",
]


class MedicationCandidate(BaseModel):
    """One raw, not-yet-canonicalized medication mention. Every raw
    field is kept verbatim; `medication_persistence.py` is the only
    place these get resolved into a real `PatientMedication` row."""

    source_segment_id: str
    source_section_id: str | None = None
    source_heading: str | None = None
    # The canonical section key this candidate came from (e.g.
    # "discharge_medications"), or "clinical_course" for an event-sourced
    # candidate — used by medication_persistence.py's start-date tier 3
    # ("a discharge recommendation that clearly indicates medication
    # starts at discharge").
    canonical_key: str | None = None
    raw_text: str

    raw_medication_name: str
    dose_text: str | None = None
    route: str | None = None
    frequency: str | None = None
    instructions: str | None = None

    status_context: MedicationContext

    # Start-date candidates — see medication_persistence.py's exact
    # 4-tier priority. Only `explicit_start_date` is ever a genuine
    # DATE by itself; the other two are SIGNALS the persistence layer
    # combines with the document's own admission/discharge metadata.
    # NEVER upload/ingestion/created_at — that value is never even
    # threaded into this candidate in the first place.
    explicit_start_date: str | None = None  # raw text, e.g. "10.03.2026"
    starts_at_discharge_or_encounter: bool = False  # "starting today" / "la externare" style phrasing
    prescription_date: str | None = None  # raw text of a stated prescription/issue date

    explicit_end_date: str | None = None  # raw text, e.g. "20.03.2026"
    raw_duration: str | None = None
    parsed_duration: medication_duration.ParsedDuration | None = None

    prn: bool = False
    scheme_or_intermittent: bool = False
    indefinite: bool = False
    taper_without_clear_duration: bool = False

    source_evidence_text: str
    source_page: int | None = None

    confidence: float = 0.7
    warnings: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# ── Negative-context exclusion — per the V3 contract's explicit list of
# mentions that must NEVER automatically become a current medication.
_ALLERGY_MARKERS = ("alergie la", "alergic la", "allergy to", "allergic to")
_REFUSED_MARKERS = ("refuza", "a refuzat", "refused", "declined", "declines")
_HYPOTHETICAL_MARKERS = (
    "se va lua in considerare",
    "posibil se va incepe",
    "eventual",
    "consider starting",
    "may consider",
    "could be considered",
    "to be considered",
)
_FAMILY_MEMBER_MARKERS = (
    "sotul ia",
    "sotia ia",
    "mama ia",
    "tatal ia",
    "his wife takes",
    "her husband takes",
    "mother takes",
    "father takes",
    "sibling takes",
)


def _is_excluded_context(line: str) -> bool:
    normalized = normalize_text(line)
    all_markers = _ALLERGY_MARKERS + _REFUSED_MARKERS + _HYPOTHETICAL_MARKERS + _FAMILY_MEMBER_MARKERS
    return any(normalize_text(marker) in normalized for marker in all_markers)


# ── Context classification — checked in this priority order, first
# match wins. Mirrors events.py's own deterministic, keyword-based
# convention (no LLM call). A line matching none of these AND not in
# the `prescriptions` section classifies "uncertain" — per the V3
# contract's own "if context is genuinely ambiguous, preserve it as
# uncertain" rule; never silently guessed as "current".
_STOPPED_MARKERS = ("oprit", "intrerupt", "stopat", "discontinuat", "sistat", "stopped", "discontinued")
_PAUSED_MARKERS = ("suspendat temporar", "pausat", "held temporarily", "paused", "on hold")
_COMPLETED_MARKERS = ("curs finalizat", "tratament finalizat", "course completed", "completed the course")
_HISTORICAL_MARKERS = (
    "anterior a luat",
    "in antecedente",
    "tratament anterior",
    "a urmat anterior",
    "previously took",
    "prior therapy",
    "in the past",
    "used to take",
)
_STARTED_MARKERS = ("se initiaza", "initiat", "incepe tratamentul", "nou introdus", "started", "initiated", "newly started")
_CONTINUED_MARKERS = ("se continua", "continua tratamentul cu", "mentine", "continued", "maintained", "unchanged", "same dose")


def _classify_medication_context(line: str, canonical_key: str | None) -> MedicationContext:
    normalized = normalize_text(line)
    for markers, label in (
        (_STOPPED_MARKERS, "stopped"),
        (_PAUSED_MARKERS, "paused"),
        (_COMPLETED_MARKERS, "completed"),
        (_HISTORICAL_MARKERS, "historical"),
        (_STARTED_MARKERS, "started"),
        (_CONTINUED_MARKERS, "continued"),
    ):
        if any(normalize_text(marker) in normalized for marker in markers):
            return label  # type: ignore[return-value]
    if canonical_key == "prescriptions":
        return "prescribed"
    return "uncertain"


# ── Start/end/prescription date labels — only used to decide WHICH
# nearby date (if any) is being labeled, never to guess an unlabeled one.
_START_DATE_LABEL_RE = re.compile(
    r"(?:din\s*data\s*de|incepand\s*(?:cu|din)|starting\s*(?:on|from)|from)\s*[:\-]?\s*$", re.IGNORECASE
)
_END_DATE_LABEL_RE = re.compile(r"(?:pana\s*(?:la|in)|until|through)\s*[:\-]?\s*$", re.IGNORECASE)
_PRESCRIPTION_DATE_LABEL_RE = re.compile(
    r"(?:data\s*(?:eliberarii|eliberării)?\s*ret[ei]t[ei]i?|data\s*prescri[ei]rii|prescription\s*(?:date|issued)|issued\s*on)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
_TODAY_OR_ENCOUNTER_RE = re.compile(
    r"\b(?:incepand\s*de\s*azi|incepe\s*azi|din\s*ziua\s*externarii|la\s*externare|"
    r"starting\s*today|start(?:s|ed)?\s*today|from\s*discharge|at\s*discharge)\b",
    re.IGNORECASE,
)


def _find_labeled_date(text: str, label_re: re.Pattern[str]) -> str | None:
    for parsed in find_dates_in_text(text):
        window_start = max(0, parsed.start - 40)
        preceding = text[window_start : parsed.start]
        if label_re.search(preceding):
            return parsed.raw_text
    return None


# ── Medication line parsing ─────────────────────────────────────────────
_DOSE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|ug|g|ml|ui|iu|u|%)\b", re.IGNORECASE)
_FREQUENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d\s*-\s*\d\s*-\s*\d\b"),
    re.compile(r"\bde\s+\d+\s+ori\s+pe\s+zi\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*x\s*/?\s*zi\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*times?\s*(?:a|per)\s*day\b", re.IGNORECASE),
    re.compile(r"\bo\s*data\s*pe\s*zi\b", re.IGNORECASE),
    re.compile(r"\bonce\s*(?:a|per)\s*day\b", re.IGNORECASE),
    re.compile(r"\btwice\s*(?:a|per)\s*day\b", re.IGNORECASE),
    re.compile(r"\bla\s*\d+\s*ore\b", re.IGNORECASE),
    re.compile(r"\bevery\s*\d+\s*hours\b", re.IGNORECASE),
    re.compile(r"\b(?:qd|bid|tid|qid)\b", re.IGNORECASE),
)
_ROUTE_KEYWORDS: dict[str, str] = {
    "per os": "oral",
    "oral": "oral",
    "po": "oral",
    "subcutanat": "subcutaneous",
    "subcutaneous": "subcutaneous",
    "sc": "subcutaneous",
    "intravenos": "intravenous",
    "intravenous": "intravenous",
    "iv": "intravenous",
    "intramuscular": "intramuscular",
    "im": "intramuscular",
    "inhalator": "inhaled",
    "inhalation": "inhaled",
    "topic": "topical",
    "topical": "topical",
}
_MAX_NAME_WORDS = 6

# Narrative fallback (used only when no dose/frequency/route boundary is
# found at all — typically a treatment_change EVENT's free-text
# sentence, e.g. "S-a oprit BESREMI ..."): a drug name mentioned in
# prose is usually the one clearly capitalized/brand-cased token, so a
# capitalized-word run is a reasonable, deterministic signal — never
# used for a structured medication-list line, which the boundary-based
# path above already handles.
_CAPITALIZED_NAME_RE = re.compile(
    r"\b[A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț]{2,}(?:\s+[A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț]{2,}){0,2}\b"
)
# Common Romanian/English sentence-initial capitalized words that are
# NOT drug names — excluded so a plain narrative sentence's own opening
# word never gets mistaken for a medication.
_NARRATIVE_NAME_STOPWORDS = {
    "pacientul", "pacienta", "tratamentul", "medicatia",
    "din", "dupa", "la", "in", "se", "s",
    "the", "patient", "treatment", "medication",
}


def _find_capitalized_drug_name(line: str) -> str | None:
    for match in _CAPITALIZED_NAME_RE.finditer(line):
        candidate = match.group(0)
        if candidate.lower() in _NARRATIVE_NAME_STOPWORDS:
            continue
        return candidate
    return None


def _find_route(line: str) -> str | None:
    normalized = normalize_text(line)
    for keyword, canonical in _ROUTE_KEYWORDS.items():
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            return canonical
    return None


def _find_frequency(line: str) -> str | None:
    for pattern in _FREQUENCY_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(0).strip()
    return None


def _isolate_medication_name(line: str, *, boundary_start: int | None) -> str | None:
    if boundary_start is not None:
        name = line[:boundary_start]
    else:
        name = line.split(",")[0]
    name = name.strip(" \t:-–,;")
    if not name:
        return None
    if len(name.split()) > _MAX_NAME_WORDS:
        return None
    if not re.search(r"[A-Za-zĂÂÎȘȚăâîșț]", name):
        return None
    return name


def _parse_medication_line(line: str) -> tuple[str, str | None] | None:
    """Returns `(medication_name, dose_text)` or None if `line` doesn't
    confidently look like a single medication mention. Precision over
    recall: a name can't be isolated confidently -> the line is not
    treated as a medication mention at all, rather than guessing."""
    text = line.strip()
    if not text or len(text) > 300:
        return None

    dose_match = _DOSE_RE.search(text)
    boundary_candidates = [m.start() for m in [dose_match] if m]
    for pattern in _FREQUENCY_PATTERNS:
        match = pattern.search(text)
        if match:
            boundary_candidates.append(match.start())
    # Searched directly against the ORIGINAL text (case-insensitively),
    # never against normalize_text()'s output — normalization can change
    # string length (accent-stripping, punctuation collapsing), which
    # would make a match index there unsafe to slice the original `text`
    # with. None of these keywords contain diacritics, so a plain
    # case-insensitive search on the original text is safe and exact.
    for keyword in _ROUTE_KEYWORDS:
        m = re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])", text, re.IGNORECASE)
        if m:
            boundary_candidates.append(m.start())
            break

    boundary_start = min(boundary_candidates) if boundary_candidates else None
    name = _isolate_medication_name(text, boundary_start=boundary_start)
    if name is None and boundary_start is None:
        # No structural boundary at all — likely free NARRATIVE prose
        # (e.g. a treatment_change event's sentence) rather than a
        # structured medication-list line. Try the capitalized-drug-name
        # fallback before giving up entirely.
        name = _find_capitalized_drug_name(text)
    if name is None:
        return None

    dose_text = dose_match.group(0) if dose_match else None
    return name, dose_text


def _build_candidate(
    line: str,
    *,
    segment: SourceSegment,
    canonical_key: str | None,
    source_section_id: str | None,
) -> MedicationCandidate | None:
    if _is_excluded_context(line):
        return None
    parsed = _parse_medication_line(line)
    if parsed is None:
        return None
    name, dose_text = parsed

    route = _find_route(line)
    frequency = _find_frequency(line)

    scheme_or_intermittent = medication_duration.find_scheme_or_intermittent_marker(line)
    duration = None if scheme_or_intermittent else medication_duration.parse_duration(line)
    indefinite = medication_duration.find_indefinite_marker(line)
    taper_without_duration = medication_duration.find_taper_without_clear_duration(line, duration)
    prn = medication_duration.find_prn_marker(line)

    status_context = _classify_medication_context(line, canonical_key)
    start_label_date = _find_labeled_date(line, _START_DATE_LABEL_RE)
    end_label_date = _find_labeled_date(line, _END_DATE_LABEL_RE)
    if status_context in ("stopped", "completed", "paused") and start_label_date and not end_label_date:
        # "<drug>, oprit din data de <DATE>" — "din data de" ("starting
        # from") here describes WHEN the medication stopped, not when it
        # started. Only reinterpreted for a stop/complete/pause context;
        # a "started"/"continued"/"prescribed" line keeps the normal
        # start-date reading.
        end_label_date, start_label_date = start_label_date, None

    return MedicationCandidate(
        source_segment_id=segment.segment_id,
        source_section_id=source_section_id,
        source_heading=segment.raw_heading,
        canonical_key=canonical_key,
        raw_text=line,
        raw_medication_name=name,
        dose_text=dose_text,
        route=route,
        frequency=frequency,
        status_context=status_context,
        explicit_start_date=start_label_date,
        starts_at_discharge_or_encounter=bool(_TODAY_OR_ENCOUNTER_RE.search(line)),
        prescription_date=_find_labeled_date(line, _PRESCRIPTION_DATE_LABEL_RE),
        explicit_end_date=end_label_date,
        raw_duration=duration.raw_text if duration else None,
        parsed_duration=duration,
        prn=prn,
        scheme_or_intermittent=scheme_or_intermittent,
        indefinite=indefinite,
        taper_without_clear_duration=taper_without_duration,
        source_evidence_text=line,
        source_page=segment.page,
        confidence=0.75,
    )


def extract_medication_candidates_from_segment(
    segment: SourceSegment,
    *,
    canonical_key: CanonicalSectionKey | str,
    source_section_id: str | None = None,
) -> list[MedicationCandidate]:
    """Extracts `MedicationCandidate`s from ONE medication-bearing
    segment's raw text. Callers are responsible for only calling this
    for a segment whose canonical classification is in
    `MEDICATION_BEARING_CANONICAL_KEYS` — matching lab_extraction.py's
    existing convention (the function itself does not re-check
    classification)."""
    candidates: list[MedicationCandidate] = []
    for raw_line in (segment.raw_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        candidate = _build_candidate(
            line, segment=segment, canonical_key=str(canonical_key), source_section_id=source_section_id
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def extract_medication_candidates_from_event(
    event: ClinicalEvent, *, source_section_id: str | None = None
) -> list[MedicationCandidate]:
    """Extracts `MedicationCandidate`s from a Phase 5 `ClinicalEvent`
    whose `event_type == "treatment_change"` — reuses Phase 5's own
    classification of Clinical Course narrative rather than
    independently re-segmenting that text (the V3 contract's "one parser
    architecture" instruction). A caller is expected to only pass
    `treatment_change` events; this function does not itself filter by
    `event_type`, matching this package's existing "caller scopes,
    function doesn't re-check" convention."""
    if event.event_type != "treatment_change":
        return []
    candidate = _build_candidate(
        event.raw_text,
        segment=SourceSegment(segment_id=event.source_event_id, index=0, raw_text=event.raw_text),
        canonical_key="clinical_course",
        source_section_id=source_section_id,
    )
    if candidate is None:
        return []
    # An event-sourced candidate's explicit_start_date, if genuinely
    # absent from the mention's own text, can still fall back to the
    # event's own normalized_date (Phase 5 already parsed it) — but only
    # for a "started" context, where the event's own date plausibly
    # describes WHEN the change happened. Not extended to "stopped" (its
    # end-date reading is handled separately, see _build_candidate's
    # din-data-de swap) or to "historical"/"uncertain", where attaching
    # any date at all would overstate what the source actually says.
    if not candidate.explicit_start_date and event.normalized_date and candidate.status_context == "started":
        candidate = candidate.model_copy(update={"explicit_start_date": event.raw_date_text})
    return [candidate]
