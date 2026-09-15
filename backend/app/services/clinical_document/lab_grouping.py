"""Coherent lab-report grouping — Clinical Document Intelligence V3,
Phase 6.

Groups `LabCandidate`s (lab_extraction.py) into the set of coherent
source lab reports a discharge document actually contains, using ONLY
trustworthy source signals (request/accession identifier, observation
date, explicit source panel) — never clinical intuition, and never a
guess when the source itself doesn't distinguish multiple reports (see
`_group_key` below: falls back to the originating segment, the safest
real source boundary already established by Phase 4, rather than
inventing a split or collapsing everything into one artificial group).

This module is deliberately pure (no DB access) — `lab_persistence.py`
is what turns a `LabReportGroup` into a real derived `Document` +
`LabResult` rows.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .lab_extraction import LabCandidate

_UNKNOWN = ""
_SEGMENT_FALLBACK_MARKER = "__segment__"


class LabReportGroup(BaseModel):
    """One coherent source lab report — the unit Phase 6 persists as ONE
    derived lab artifact (see lab_persistence.py's requirement: one
    derived artifact per group, never one per analyte, never one per
    whole discharge document when multiple genuinely distinct reports
    exist)."""

    group_key: str
    request_code: str | None = None
    observation_date: str | None = None
    source_panel: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    candidates: list[LabCandidate] = Field(default_factory=list)


def _group_key_tuple(candidate: LabCandidate) -> tuple[str, str, str]:
    if candidate.request_code or candidate.observation_date or candidate.source_panel:
        return (candidate.request_code or _UNKNOWN, candidate.observation_date or _UNKNOWN, candidate.source_panel or _UNKNOWN)
    # No explicit distinguishing source signal anywhere on this
    # candidate — the safest available grouping is "same originating
    # segment", never an invented cross-segment merge.
    return (_SEGMENT_FALLBACK_MARKER, candidate.source_segment_id, _UNKNOWN)


def _group_key_str(key: tuple[str, str, str]) -> str:
    # Deterministic, stable across runs (same candidates -> same key
    # string) — used both as the group's own identity for idempotent
    # derived-artifact get-or-create (lab_persistence.py) and as a
    # human-inspectable debugging value.
    return "|".join(part.replace("|", "_") for part in key)


def group_lab_candidates(candidates: list[LabCandidate]) -> list[LabReportGroup]:
    """Deterministic, order-preserving grouping. Two candidates land in
    the same group if and only if they share the same
    (request_code, observation_date, source_panel) signal — or, when
    none of those three is present on either, the same originating
    segment. Never groups by clinical similarity of the analyte names
    themselves."""
    groups: dict[str, LabReportGroup] = {}
    order: list[str] = []

    for candidate in candidates:
        key_tuple = _group_key_tuple(candidate)
        key_str = _group_key_str(key_tuple)

        group = groups.get(key_str)
        if group is None:
            group = LabReportGroup(
                group_key=key_str,
                request_code=candidate.request_code,
                observation_date=candidate.observation_date,
                source_panel=candidate.source_panel,
            )
            groups[key_str] = group
            order.append(key_str)

        group.candidates.append(candidate)
        if candidate.source_segment_id not in group.source_segment_ids:
            group.source_segment_ids.append(candidate.source_segment_id)

    return [groups[key] for key in order]
