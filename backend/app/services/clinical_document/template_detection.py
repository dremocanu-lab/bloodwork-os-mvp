"""Deterministic (no LLM) empty-template detection — Clinical Reader
Intelligence V2.

A Romanian hospital discharge form often has fixed sections (e.g. a
"PRODUS / CANTITATE" treatment table, a "COD CERERE / DATA /
INVESTIGAȚII" investigations table) that, for a given patient, were
never filled in — only the column headers/labels and blank
underscore-fill lines survive extraction. That is template noise, not
clinical content, and must never be presented to a clinician as if it
were real treatment/investigation data (see schema.py's
`ClinicalSection.is_template_only`).

This is intentionally NOT an AI judgment call: whether a block of text
is "only column headers and blanks" is a mechanical, auditable check —
using a model for it would add cost, latency, and non-determinism for a
decision that doesn't need any of the three.
"""

from __future__ import annotations

import re

from app.services.lab_catalog import normalize_text

# Exact (normalized) known template header/label words seen in real
# Bragi discharge-form extractions — never inferred, always this named
# list, so a line is only ever treated as "not real content" for an
# explicit, auditable reason.
_KNOWN_TEMPLATE_LABELS: frozenset[str] = frozenset(
    {
        "produs",
        "cantitate",
        "cod cerere",
        "cod cerere / data",
        "data",
        "investigatii",
        "diagnostic principal",
        "diagnostic secundar",
        "diagnostic principal drg cod 1",
        "diagnostic principal drg cod 2",
        "diagnostice secundare",
        "drg cod 1",
        "drg cod 2",
        "eco",
        "ekg",
        "rx",
        "altele",
        "nota",
    }
)

# A line that is nothing but underscores/dashes/dots/colons/whitespace —
# the classic "fill in the blank, never filled in" shape.
_BLANK_FILL_RE = re.compile(r"^[_\-.:\s]*$")

# A short boilerplate instructional note explaining how the form SHOULD
# be filled in — real, seen verbatim in Bragi discharge-form
# extractions — is itself template noise, not patient-specific content,
# even though it's non-blank prose.
_KNOWN_BOILERPLATE_NOTE_PATTERNS: tuple[str, ...] = (
    "se completeaza doar daca",
    "se va completa de catre medic",
    "a nu se completa",
    "campurile de mai jos se completeaza",
)


def _line_is_template_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _BLANK_FILL_RE.match(stripped):
        return True
    normalized = normalize_text(stripped).rstrip(":").strip()
    if normalized in _KNOWN_TEMPLATE_LABELS:
        return True
    if any(pattern in normalized for pattern in _KNOWN_BOILERPLATE_NOTE_PATTERNS):
        return True
    return False


def is_template_placeholder_text(text: str | None) -> bool:
    """True only when EVERY non-empty line of `text` is a known template
    label, a blank fill-in line, or known boilerplate instructional text
    — i.e. there is no real, patient-specific clinical content anywhere
    in it. A single real content line (a filled-in product name, an
    actual finding, a real note) makes this False for the whole text —
    this function never discards partial real content, only recognizes
    the all-noise case."""
    if not text or not text.strip():
        return False  # empty text is handled by the existing "drop empty sections" rule, not this one
    lines = text.splitlines()
    return all(_line_is_template_noise(line) for line in lines)


def section_blocks_are_all_template_noise(block_texts: list[str]) -> bool:
    """`block_texts` is every text-bearing block's own text within one
    ClinicalSection (see canonical_headings.consolidate_segments). The
    whole section is template-only only when it has at least one
    text-bearing block AND every one of them is template noise — a
    section with zero text blocks at all is already dropped entirely by
    the existing empty-section rule, not flagged here."""
    if not block_texts:
        return False
    return all(is_template_placeholder_text(text) for text in block_texts)
