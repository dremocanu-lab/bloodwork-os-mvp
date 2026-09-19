"""Embedded laboratory-result extraction — Clinical Document Intelligence
V3, Phase 6 (first increment).

Turns the raw text/table content of a `laboratory_results`-classified
`SourceSegment` (see segments.py/canonical_headings.py, Phase 4) into
typed `LabCandidate` instances — a deliberate INTERMEDIATE
representation, not yet a canonical `LabResult` row. Nothing here writes
to the database or calls `resolve_analyte()` — that happens in
`lab_persistence.py`, which is the one place a `LabCandidate` is
actually canonicalized and persisted. This module only answers "what
does the source text/table actually say", verbatim, with precision
preferred over recall (see the module's own guards below) — never a
guess.

Hard rules (see the V3 contract's Phase 6 text):
- Raw values/units/ranges/flags are kept VERBATIM — this module never
  silently normalizes away a contradictory or unusual source value.
- Never treat an arbitrary number in narrative prose as a lab result
  merely because it resembles "NAME 5.4" — see `_looks_like_narrative`
  and the line-shape guards in `_parse_lab_line`.
- Never guess an observation date, request/accession code, or panel
  name that isn't actually present in the source text.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.services.lab_catalog import normalize_text

from .dates import find_dates_in_text
from .segments import SourceSegment, SegmentTableData
from .template_detection import is_template_placeholder_text

SourceSectionStatus = Literal["normal", "pathological"]


class LabCandidate(BaseModel):
    """One raw, not-yet-canonicalized embedded lab observation extracted
    from a discharge document's `laboratory_results` section. Every raw
    field is kept verbatim; only `parsed_value` is a genuine
    interpretation (a best-effort float parse of `raw_value`), and it is
    never used to overwrite `raw_value` itself."""

    source_segment_id: str
    source_heading: str | None = None
    raw_test_name: str
    raw_value: str
    parsed_value: float | None = None
    raw_unit: str | None = None
    normalized_unit: str | None = None
    reference_range: str | None = None
    # An explicit provider/source abnormal marker literally present next
    # to this value (e.g. "H", "L", "*", "crescut") — NOT Bragi's own
    # numeric-range judgement. See lab_persistence.py's flag-precedence
    # rule for how this interacts with source_section_status and a
    # computed range comparison.
    source_flag: str | None = None
    # Which named subsection (if any) this value was written under —
    # "normal" / "pathological" — only ever set from an EXPLICIT source
    # marker (see `_SUBSECTION_MARKERS` below), never inferred from the
    # value itself.
    source_section_status: SourceSectionStatus | None = None
    observation_date: str | None = None
    request_code: str | None = None
    source_panel: str | None = None
    # The exact source line/row this candidate was read from — the
    # provenance anchor when no real PDF bbox exists (see
    # lab_persistence.py's SourceEvidence construction).
    source_evidence_text: str
    # Copied verbatim from the originating SourceSegment.page (segments.py)
    # when a real one exists — NEVER fabricated. Today's discharge
    # pipeline never populates SourceSegment.page (see segments.py's own
    # docstring), so this is None for every real candidate today; a
    # future per-page segmentation increment can populate it honestly
    # without any change needed here or in lab_persistence.py, which
    # already reads this field rather than hardcoding None.
    source_page: int | None = None
    confidence: float = 0.8
    warnings: list[str] = Field(default_factory=list)
    # Source Geometry + Clinical Table Intelligence V3 — set ONLY when
    # this candidate came from a REAL extracted table row (see
    # `_extract_from_table` below). `primary_bbox` is the single most
    # specific real cell (the VALUE cell when identified, else the row
    # union — see `SourceEvidence.bbox_*`'s own "exact_bbox precision"
    # contract in api/routers/source_evidence.py); `row_bbox` is the
    # union of every contributing cell (frames the whole row);
    # `field_bboxes` is every real per-cell rect, labeled by field
    # (`{label, x, y, width, height}`). All three are None for a
    # prose-line candidate — never estimated from character width.
    primary_bbox: dict[str, float] | None = None
    row_bbox: dict[str, float] | None = None
    field_bboxes: list[dict] | None = None


# ── Subsection markers (normal/pathological) ───────────────────────────
# Checked as a normalized substring of an otherwise-short "heading-like"
# line (see `_is_marker_line`) — never inferred from a value itself.
_NORMAL_MARKERS: tuple[str, ...] = (
    "valori normale",
    "rezultate normale",
    "rezultate in limite normale",
    "valori in limite normale",
    "in limite normale",
    "normal results",
    "normal values",
)
_PATHOLOGICAL_MARKERS: tuple[str, ...] = (
    "valori patologice",
    "valori modificate patologic",
    "rezultate patologice",
    "valori anormale",
    "rezultate modificate",
    "pathological results",
    "pathological values",
    "abnormal results",
    "abnormal values",
)

# A short line (no numeric value of its own) that isn't a subsection
# marker but looks like a named panel heading (e.g. "HEMATOLOGIE",
# "Biochimie", "Coagulare") — tracked as `source_panel` for subsequent
# candidate lines until the next such heading. Deliberately conservative:
# only a short (<=4 word), letter-only line with no digits qualifies, so
# an ordinary prose sentence is never mistaken for a panel heading.
_PANEL_HEADING_RE = re.compile(r"^[A-Za-zĂÂÎȘȚăâîșțŞŢ][A-Za-zĂÂÎȘȚăâîșțŞŢ \-/]{1,40}$")

_ACCESSION_RE = re.compile(
    r"(?:nr\.?\s*(?:cerere|comanda|comandă|proba|probă|accession)|accession\s*(?:no\.?|#)?|req(?:uest)?\s*#?|"
    r"numar cerere)\s*[:\-]?\s*([A-Za-z0-9\-/]{2,20})",
    re.IGNORECASE,
)

_DATE_KEYWORD_RE = re.compile(
    r"(?:data\s*(?:recolt[aă]rii|recolt[aă]rii probei|recolt[aă]rii)?|recoltat(?:a|ă)?\s*(?:la|in|în)?|"
    r"data\s*rezultat(?:ului)?|collected\s*(?:on)?|sampled\s*(?:on)?|test\s*date)\s*[:\-]?\s*$",
    re.IGNORECASE,
)

# One numeric value with an optional decimal part (comma or dot).
_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")

# Trailing explicit flag markers — an actual provider mark, never a
# computed judgement. Romanian "crescut"/"scazut"/"scăzut" ("increased"/
# "decreased") and their English equivalents count as explicit flags
# specifically because they are markers a source document prints next to
# an out-of-range value, not Bragi's own interpretation.
_FLAG_RE = re.compile(
    # H/L require a PRECEDING WHITESPACE, not just a word boundary — a
    # bare `\b` would also match the trailing "L" inside a unit like
    # "mmol/L" or "U/L" (the "/" is a non-word character too, so a plain
    # \bL\b would false-positive on the unit itself).
    r"(?:(?<=\s)(H|L)\b|(\*{1,2})|(↑|↓)|\b(crescut|sc[ăa]zut|high|low|abnormal|patologic[ăa]?)\b)\s*$",
    re.IGNORECASE,
)

# A parenthesized/bracketed reference interval, e.g. "(3.98-10.40)" or
# "[13.0 - 17.0]". Requires two numbers separated by a dash so a stray
# single-number parenthetical (rare, but possible) is never misread as a
# range.
_RANGE_RE = re.compile(
    r"[\(\[]\s*([-+]?\d+(?:[.,]\d+)?)\s*[-–]\s*([-+]?\d+(?:[.,]\d+)?)\s*[\)\]]"
)

_MAX_NAME_WORDS = 5
_MAX_LINE_WORDS_FOR_A_LAB_ROW = 12


def _normalize_flag(raw_flag: str) -> str:
    return raw_flag.strip()


def _to_float(raw_value: str) -> float | None:
    try:
        return float(raw_value.replace(",", "."))
    except ValueError:
        return None


def _is_marker_line(line: str) -> str | None:
    """Returns "normal"/"pathological" if `line` is an explicit
    subsection marker, else None. A marker line never also carries a
    numeric lab value — a marker is a heading, not a data row."""
    normalized = normalize_text(line)
    if not normalized or _NUMBER_RE.search(line):
        return None
    if any(marker in normalized for marker in _PATHOLOGICAL_MARKERS):
        return "pathological"
    if any(marker in normalized for marker in _NORMAL_MARKERS):
        return "normal"
    return None


def _is_panel_heading_line(line: str) -> str | None:
    stripped = line.strip().rstrip(":").strip()
    if not stripped or _NUMBER_RE.search(stripped):
        return None
    if len(stripped.split()) > 4:
        return None
    if _PANEL_HEADING_RE.match(stripped):
        return stripped
    return None


class _ParsedLabLine(BaseModel):
    name: str
    raw_value: str
    unit: str | None = None
    reference_range: str | None = None
    flag: str | None = None


def _parse_qualitative_lab_line(
    text: str, *, reference_range: str | None, flag: str | None
) -> _ParsedLabLine | None:
    """A non-numeric lab observation, e.g. "Grup sanguin: A", "VDRL:
    Negativ" — only recognized from an explicit colon-separated
    "NAME: short value" shape, never a bare sentence that happens to
    contain a colon (a narrative aside like "Diagnostic: suspiciune de
    pneumonie" is 1 word longer than this guard allows on the value
    side, specifically to stay conservative)."""
    if ":" not in text:
        return None
    name, _, value = text.partition(":")
    name = name.strip()
    value = value.strip()
    if not name or not value:
        return None
    if len(name.split()) > _MAX_NAME_WORDS:
        return None
    if len(value.split()) > 3:
        return None
    if value.endswith(".") and len(value.split()) > 1:
        return None  # reads like the end of a sentence, not a short field value
    if not re.search(r"[A-Za-zĂÂÎȘȚăâîșțŞŢ]", name):
        return None
    return _ParsedLabLine(name=name, raw_value=value, unit=None, reference_range=reference_range, flag=flag)


def _parse_lab_line(line: str) -> _ParsedLabLine | None:
    """Parses ONE line/row of the form `NAME VALUE [UNIT] [(RANGE)]
    [FLAG]` (colon- or space-separated). Returns None when the line
    doesn't confidently look like a single lab observation — precision
    over recall, per the V3 contract's Phase 6 rule: a narrative
    sentence that happens to contain a number must never be mistaken for
    a lab row."""
    text = line.strip()
    if not text or len(text) > 200:
        return None
    if len(text.split()) > _MAX_LINE_WORDS_FOR_A_LAB_ROW:
        return None

    reference_range = None
    range_match = _RANGE_RE.search(text)
    if range_match:
        reference_range = f"{range_match.group(1)}-{range_match.group(2)}"
        text = (text[: range_match.start()] + " " + text[range_match.end() :]).strip()

    flag = None
    flag_match = _FLAG_RE.search(text)
    if flag_match:
        flag = _normalize_flag(flag_match.group(0))
        text = text[: flag_match.start()].strip()

    value_match = _NUMBER_RE.search(text)
    if not value_match:
        # No numeric value at all — a QUALITATIVE result (e.g. "Grup
        # sanguin: A", "VDRL: Negativ") is still a real lab observation
        # whose text value must be preserved verbatim, not discarded
        # just because it isn't numeric. Only attempted for an explicit
        # colon-separated "NAME: short value" shape — see
        # `_parse_qualitative_lab_line`'s own precision guards.
        return _parse_qualitative_lab_line(text, reference_range=reference_range, flag=flag)

    name = text[: value_match.start()].strip(" :\t-–")
    if not name:
        return None
    name_words = name.split()
    if len(name_words) > _MAX_NAME_WORDS:
        return None
    if not re.search(r"[A-Za-zĂÂÎȘȚăâîșțŞŢ]", name):
        return None
    # A name that is itself entirely numeric-punctuation-shaped (e.g. a
    # stray date fragment "10.01") is not a test name.
    if re.fullmatch(r"[\d.\-/]+", name):
        return None

    raw_value = value_match.group(0)
    rest = text[value_match.end() :].strip(" :\t-–")
    # A second embedded number immediately after the value with no unit
    # letters at all (e.g. "10.01.2026" mis-split) is a strong signal
    # this was a date-shaped token, not a lab value — reject rather than
    # guess.
    if rest and re.fullmatch(r"[\d.\-/,]+", rest):
        return None
    unit = rest or None

    return _ParsedLabLine(name=name, raw_value=raw_value, unit=unit, reference_range=reference_range, flag=flag)


def _find_segment_date(text: str) -> str | None:
    """An observation date is only ever taken from text EXPLICITLY
    preceded by a recognized date-label keyword (e.g. "Data recoltarii:
    10.01.2026") — never the first date-shaped substring found anywhere
    in the segment, which could easily be an unrelated mention."""
    for parsed in find_dates_in_text(text):
        window_start = max(0, parsed.start - 40)
        preceding = text[window_start : parsed.start]
        if _DATE_KEYWORD_RE.search(preceding):
            return parsed.raw_text
    return None


def _find_segment_request_code(text: str) -> str | None:
    match = _ACCESSION_RE.search(text)
    return match.group(1) if match else None


def _iter_candidate_lines_from_text(text: str) -> list[tuple[str, str | None, str | None]]:
    """Walks `text` line by line, tracking the current
    normal/pathological subsection and panel heading, yielding
    `(line, section_status, panel)` for every line that is NOT itself a
    marker/heading line (i.e. every line that's a candidate for
    `_parse_lab_line`)."""
    current_status: str | None = None
    current_panel: str | None = None
    out: list[tuple[str, str | None, str | None]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        marker = _is_marker_line(line)
        if marker:
            current_status = marker
            continue
        panel = _is_panel_heading_line(line)
        if panel:
            current_panel = panel
            continue
        out.append((line, current_status, current_panel))
    return out


def _table_row_to_line(headers: list[str], row: list[str]) -> tuple[str, dict[str, int]] | None:
    """Best-effort reconstruction of a table row into the same
    `NAME VALUE UNIT (RANGE) FLAG`-shaped line `_parse_lab_line` already
    understands, using header names to identify which column is which —
    never guessed positionally when headers give no signal. Also returns
    which column index fed each field (`{"name": 0, "value": 1, ...}`) so
    a caller with real per-cell geometry (see `_extract_from_table`) can
    label each contributing cell's bbox correctly."""
    if not row:
        return None
    normalized_headers = [normalize_text(h) for h in headers]

    def _header_matches(header: str, keyword: str) -> bool:
        # Short keywords (e.g. "um" for "unitate de masura") need a
        # whole-word match — a plain substring check would wrongly match
        # "um" inside an unrelated header like "denumire".
        if len(keyword) <= 3:
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", header))
        return keyword in header

    def _col(*keywords: str) -> tuple[str, int] | None:
        for idx, header in enumerate(normalized_headers):
            if idx >= len(row):
                continue
            if any(_header_matches(header, keyword) for keyword in keywords):
                return row[idx].strip(), idx
        return None

    name_match = _col("test", "analiz", "denumire", "parametru", "nume")
    value_match = _col("valoare", "rezultat", "value", "result")
    unit_match = _col("um", "unitate", "unit")
    ref_range_match = _col("interval", "referinta", "referinţa", "range", "normal")
    flag_match = _col("flag", "semnificatie", "interpretare")

    columns: dict[str, int] = {}
    name = value = unit = ref_range = flag = None
    if name_match:
        name, columns["name"] = name_match
    if value_match:
        value, columns["value"] = value_match
    if unit_match:
        unit, columns["unit"] = unit_match
    if ref_range_match:
        ref_range, columns["reference_range"] = ref_range_match
    if flag_match:
        flag, columns["flag"] = flag_match

    if name is None or value is None:
        # No header gave a confident column match — fall back to
        # positional only when there are exactly the minimum 2 columns
        # (name, value), the narrowest case where position is unambiguous.
        if len(row) == 2 and not name and not value:
            name, value = row[0].strip(), row[1].strip()
            columns = {"name": 0, "value": 1}
        else:
            return None

    pieces = [f"{name} {value}"]
    if unit:
        pieces[-1] += f" {unit}"
    if ref_range:
        pieces[-1] += f" ({ref_range})"
    if flag:
        pieces[-1] += f" {flag}"
    return pieces[0], columns


def _union_bbox(bboxes: list[dict[str, float]]) -> dict[str, float] | None:
    if not bboxes:
        return None
    x0 = min(b["x"] for b in bboxes)
    y0 = min(b["y"] for b in bboxes)
    x1 = max(b["x"] + b["width"] for b in bboxes)
    y1 = max(b["y"] + b["height"] for b in bboxes)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


_TableRowGeometry = tuple[dict[str, float] | None, dict[str, float] | None, list[dict] | None]


def _extract_from_table(table: SegmentTableData) -> list[tuple[str, _TableRowGeometry]]:
    """Returns one `(line, (primary_bbox, row_bbox, field_bboxes))` tuple
    per real table row. All three geometry values are populated only
    when the table carries matching `cell_bboxes` (real geometry — see
    segments.py); otherwise they stay None, degrading gracefully to
    text-only evidence exactly as before geometry existed."""
    out: list[tuple[str, _TableRowGeometry]] = []
    has_geometry = len(table.cell_bboxes) == len(table.rows)
    for row_index, row in enumerate(table.rows):
        parsed = _table_row_to_line(table.headers, row)
        if parsed is None:
            continue
        line, columns = parsed
        primary_bbox: dict[str, float] | None = None
        row_bbox: dict[str, float] | None = None
        field_bboxes: list[dict] | None = None
        if has_geometry:
            row_cells = table.cell_bboxes[row_index]
            field_bboxes = [
                {"label": label, **row_cells[col_idx]}
                for label, col_idx in columns.items()
                if col_idx < len(row_cells) and row_cells[col_idx] is not None
            ]
            row_bbox = _union_bbox([{k: v for k, v in fb.items() if k != "label"} for fb in field_bboxes])
            primary_field = next((fb for fb in field_bboxes if fb["label"] == "value"), None)
            primary_bbox = (
                {k: v for k, v in primary_field.items() if k != "label"} if primary_field else row_bbox
            )
        out.append((line, (primary_bbox, row_bbox, field_bboxes or None)))
    return out


def extract_lab_candidates_from_segment(segment: SourceSegment) -> list[LabCandidate]:
    """Extracts `LabCandidate`s from ONE `laboratory_results`-classified
    segment. Callers (see lab_persistence.py) are responsible for
    scoping this to segments that actually classified as
    `laboratory_results` — this function does not re-check the
    segment's canonical classification itself, matching this package's
    existing convention (segments.py/events.py are likewise pure
    text-in, typed-out functions with no classification logic of their
    own)."""
    candidates: list[LabCandidate] = []

    segment_date = _find_segment_date(segment.raw_text or "")
    segment_request_code = _find_segment_request_code(segment.raw_text or "")

    # Source Geometry + Clinical Table Intelligence V3 (Part 20/61) —
    # a segment whose ENTIRE raw text is known template noise (blank
    # PRODUS/CANTITATE/EKG/ECO/RX/ALTELE headers and fill-in blanks,
    # never real patient content) never yields a text-line candidate —
    # reusing Clinical Reader V2's own deterministic template detector,
    # never a second implementation of the same judgment. `table_data`
    # (if any) is unaffected: an empty-template TABLE is already
    # excluded from ever reaching `table_data` in the first place (see
    # segments.py::_table_data_for_segment's own empty_template check).
    text_is_template_noise = is_template_placeholder_text(segment.raw_text)
    lines_with_context: list[tuple[str, SourceSectionStatus | None, str | None, _TableRowGeometry]] = (
        []
        if text_is_template_noise
        else [
            (line, status, panel, (None, None, None))
            for line, status, panel in _iter_candidate_lines_from_text(segment.raw_text or "")
        ]
    )
    if segment.table_data is not None:
        for line, geometry in _extract_from_table(segment.table_data):
            lines_with_context.append((line, None, None, geometry))

    for line, section_status, panel, (primary_bbox, row_bbox, field_bboxes) in lines_with_context:
        parsed = _parse_lab_line(line)
        if parsed is None:
            continue

        warnings: list[str] = []
        parsed_value = _to_float(parsed.raw_value)
        if parsed_value is None:
            warnings.append(f"Value '{parsed.raw_value}' could not be parsed as numeric — kept as text only.")

        candidates.append(
            LabCandidate(
                source_segment_id=segment.segment_id,
                source_heading=segment.raw_heading,
                raw_test_name=parsed.name,
                raw_value=parsed.raw_value,
                parsed_value=parsed_value,
                raw_unit=parsed.unit,
                normalized_unit=(parsed.unit.strip() if parsed.unit else None),
                reference_range=parsed.reference_range,
                source_flag=parsed.flag,
                source_section_status=section_status,
                observation_date=segment_date,
                request_code=segment_request_code,
                source_panel=panel,
                source_evidence_text=line,
                source_page=segment.page,
                confidence=0.8 if parsed_value is not None else 0.5,
                warnings=warnings,
                primary_bbox=primary_bbox,
                row_bbox=row_bbox,
                field_bboxes=field_bboxes,
            )
        )

    return candidates
