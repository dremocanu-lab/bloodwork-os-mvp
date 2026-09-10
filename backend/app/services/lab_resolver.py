"""Generic, OCR-tolerant candidate resolver for lab analyte names.

Problem this solves: a real production document had an analyte the source
PDF visibly labels "PSW", which Reducto's extraction returned as "PSV" —
one glyph misread (V/W are visually confusable). Neither existing exact/
substring matcher (`synonyms.normalize_test_name`, `lab_catalog.
find_lab_definition`) resolves that, correctly, since neither does fuzzy
matching — but that also means a genuine one-character OCR slip never
gets corrected, so Bragi displayed the wrong-looking name unchanged.

IMPORTANT — two genuinely independent decisions, not one:
    1. Text-match confidence: how similar is the raw extracted text to a
       KNOWN alias string, allowing for OCR-confusable glyph substitution?
       This is a purely textual/visual-similarity question.
    2. Clinical/semantic confidence: does that matched alias string carry
       an ESTABLISHED clinical meaning we can stand behind?
Both defaulted to the same value in an earlier version of this module,
because every candidate in both source catalogs happens to be a real,
independently-justified clinical term — so a confident text match always
implied a confident clinical meaning too. That version ALSO added "PSW"
as a supposed alternate abbreviation for PDW (Platelet Distribution
Width) to make a specific OCR-misread case resolve — which was wrong: no
authoritative hematology/analyzer source documents "PSW" meaning
anything (checked via web search, not assumed), and the correct,
conservative behavior for text that only *resembles* a known term,
without any real evidence for what it means, is to surface the corrected
TEXT while leaving the CANONICAL CONCEPT unresolved. See `_Candidate.
clinically_verified` and `METHOD_TEXT_MATCHED_UNVERIFIED` below for the
mechanism this module now uses to keep those two decisions separate, and
BRAGI_REDUCTO_PLAN.md §11a/§12 for the full account.

This module adds resolution stages tried only after both existing exact/
alias matchers have already failed to find a confident hit: weighted,
OCR-confusion-aware similarity scoring against the full candidate
universe of both existing catalogs (`synonyms.py`'s CBC/chemistry
definitions + `lab_catalog.py`'s broader catalog), combined with whatever
contextual evidence is available. It NEVER hardcodes a specific raw
string to a specific resolution (no `"PSV": "PSW"`-style dict) — every
resolution is a byproduct of scoring the raw text against the SAME alias
lists the exact matchers already use. Adding a new legitimate alias to
either catalog automatically becomes a fuzzy-resolvable target too; an
unrelated typo never coincidentally resolves onto something it shouldn't,
because scoring, not a lookup table, decides.

Pipeline (`resolve_analyte`):
    1. `synonyms.normalize_test_name` (existing, unchanged) — exact/
       alias/substring match against the CBC+chemistry catalog. Every
       entry there is an established clinical term, so a match resolves
       both axes at once (text confidence == clinical confidence == 1.0).
    2. `lab_catalog.find_lab_definition` (existing, unchanged) — scored
       substring match against the broader catalog. Same reasoning.
    3. Only if neither found a match: OCR-aware fuzzy scoring across BOTH
       catalogs' combined alias lists. If the best-scoring candidate is
       `clinically_verified` (true for every real entry in both catalogs
       today — nothing unverified is in the actual production catalog),
       both axes resolve together, same as stages 1-2 just via fuzzy
       text matching instead of exact. If a future entry is deliberately
       marked `clinically_verified=False` (real evidence for the TEXT
       existing in lab reports, but not for what it clinically means),
       only the text axis resolves — `resolved_source_text` is set,
       `resolved` (the clinical/canonical axis) stays False. Ambiguous
       (two distinct candidates too close together) or low-confidence
       results stay unresolved on both axes — never a silent guess.

Source/vendor-specific authoritative mappings: `VENDOR_SPECIFIC_ALIASES`
below is the intended place to add a real analyzer/lab's own documented
abbreviation set once you actually have it (e.g. a vendor manual PDF or
confirmed-with-the-lab terminology) — scoped to that institution/vendor
only, never promoted to the global catalog on the strength of a single
document. It is empty by default; nothing fabricated lives there.

The raw provider string is NEVER modified by any of this — callers keep
it separately (see `reducto_extraction.extract_lab_results`, which stores
it as `LabResult.raw_test_name`, and the resolution's `canonical_name`/
`display_name`/`normalization_confidence`/`normalization_method` as
distinct columns) — provider output is preserved even when Bragi
displays a different, resolved name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services import lab_catalog
from app.synonyms import LAB_DEFINITIONS as SYNONYMS_DEFINITIONS
from app.synonyms import normalize_test_name
from app.synonyms import normalize_text as _normalize_text

RESOLVED = "resolved"
UNRESOLVED = "unresolved"

METHOD_EXACT = "exact"
METHOD_ALIAS = "alias"
METHOD_OCR_FUZZY = "ocr_fuzzy"
METHOD_VENDOR_SPECIFIC = "vendor_specific"
# Text confidently matched a known, attested string — but that string's
# CLINICAL meaning is not established (candidate marked
# clinically_verified=False). canonical_name/category stay unresolved;
# resolved_source_text/display_name show the matched text, not a guess.
METHOD_TEXT_MATCHED_UNVERIFIED = "text_matched_unverified"
METHOD_UNRESOLVED = "unresolved"

# Calibrated against the confusion classes the product spec names, not
# invented in the abstract: a single OCR-confusable-glyph difference on an
# otherwise-exact alias match (e.g. two same-length tokens differing by one
# same-class substitution) scores 1 - (0.3/len) — comfortably above
# HIGH_CONFIDENCE for realistic analyte-name lengths. A plain (non-
# confusable) one-character difference costs 3x as much, so ordinary
# typos/unrelated short tokens don't spuriously resolve.
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.70
AMBIGUOUS_MARGIN = 0.03

# ---------------------------------------------------------------------------
# OCR confusion classes — scoring evidence only, never a text transform.
# ---------------------------------------------------------------------------
_OCR_CONFUSION_CLASSES: list[set[str]] = [
    {"v", "w"},
    {"i", "l", "1"},
    {"o", "0"},
    {"s", "5"},
    {"b", "8"},
]
_CONFUSION_GROUP_OF: dict[str, int] = {}
for _idx, _group in enumerate(_OCR_CONFUSION_CLASSES):
    for _ch in _group:
        _CONFUSION_GROUP_OF[_ch] = _idx

_BIGRAM_CONFUSIONS: list[tuple[str, str]] = [("rn", "m"), ("m", "rn")]

_SUBSTITUTION_COST_SAME_CLASS = 0.3
_SUBSTITUTION_COST_DEFAULT = 1.0
_INSERT_DELETE_COST = 1.0

# Light, explicitly-partial unit-compatibility hints — real evidence where
# defined, silently skipped (not penalized) where not. Not a claim of
# complete coverage; see BRAGI_REDUCTO_PLAN.md.
_EXPECTED_UNITS: dict[str, set[str]] = {
    "mpv": {"fl"},
    "pdw": {"fl", "%"},
    "glucose": {"mg/dl", "mmol/l"},
    "creatinine": {"mg/dl", "umol/l"},
}

# Real, source/vendor-specific analyte abbreviation mappings — scoped to a
# specific institution/analyzer, never global. Empty by default: nothing
# here is fabricated. Populate a key only when you have an actual
# authoritative source (a vendor manual, a confirmed statement from the
# lab) for that institution's terminology, e.g.:
#   "acme diagnostics ltd": [
#       {"alias": "psw", "canonical_name": "pdw",
#        "display_name": "Platelet Distribution Width",
#        "category": "cbc_platelets",
#        "evidence": "Acme Analyzer XR-500 operator manual v3, p.42"},
#   ],
# Matched only when the caller supplies a matching `institution` hint —
# see `resolve_analyte`'s `institution` parameter.
VENDOR_SPECIFIC_ALIASES: dict[str, list[dict[str, str]]] = {}


def _ocr_variants(token: str) -> set[str]:
    """Alternate raw readings from de-confusing known BIGRAM confusions
    (rn<->m) — single-glyph confusions (V/W etc.) don't change length, so
    they're handled directly as a reduced substitution cost instead."""
    variants = {token}
    for a, b in _BIGRAM_CONFUSIONS:
        if a in token:
            variants.add(token.replace(a, b))
    return variants


def _substitution_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    group_a = _CONFUSION_GROUP_OF.get(a)
    group_b = _CONFUSION_GROUP_OF.get(b)
    if group_a is not None and group_a == group_b:
        return _SUBSTITUTION_COST_SAME_CLASS
    return _SUBSTITUTION_COST_DEFAULT


def _weighted_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance with a reduced substitution cost for known
    OCR-confusable character pairs; everything else costs the same as
    plain edit distance."""
    if a == b:
        return 0.0
    len_a, len_b = len(a), len(b)
    if len_a == 0:
        return len_b * _INSERT_DELETE_COST
    if len_b == 0:
        return len_a * _INSERT_DELETE_COST

    prev_row = [i * _INSERT_DELETE_COST for i in range(len_b + 1)]
    for i in range(1, len_a + 1):
        curr_row = [i * _INSERT_DELETE_COST] + [0.0] * len_b
        for j in range(1, len_b + 1):
            sub_cost = _substitution_cost(a[i - 1], b[j - 1])
            curr_row[j] = min(
                prev_row[j] + _INSERT_DELETE_COST,
                curr_row[j - 1] + _INSERT_DELETE_COST,
                prev_row[j - 1] + sub_cost,
            )
        prev_row = curr_row
    return prev_row[len_b]


def ocr_aware_similarity(raw: str, candidate: str) -> float:
    """1.0 = identical, 0.0 = completely dissimilar. Tries known bigram-
    confusion variants of `raw` and keeps the best (lowest-distance)
    result."""
    if not raw or not candidate:
        return 0.0
    best_distance = min(_weighted_edit_distance(variant, candidate) for variant in _ocr_variants(raw))
    max_len = max(len(raw), len(candidate))
    if max_len == 0:
        return 1.0
    return max(0.0, 1.0 - (best_distance / max_len))


@dataclass
class ResolvedAnalyte:
    provider_extracted_name: str  # raw, verbatim, never modified

    # --- Axis 1: text/OCR match — independent of clinical meaning ---
    resolved_source_text: str = ""  # best textual reading; == raw if no confident text match found
    ocr_match_confidence: float = 0.0  # confidence in resolved_source_text, 0 if it's just the raw text back

    # --- Axis 2: clinical/semantic resolution — independent of text confidence ---
    resolved: bool = False  # whether a CANONICAL CLINICAL CONCEPT was resolved
    canonical_name: str | None = None
    display_name: str | None = None
    category: str | None = None
    normalization_confidence: float = 0.0
    normalization_method: str = METHOD_UNRESOLVED

    candidates_considered: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    canonical_name: str
    display_name: str
    category: str | None
    aliases: tuple[str, ...]
    # False = this text is attested (it's a real string someone put in
    # this catalog), but its CLINICAL MEANING is not established — the
    # fuzzy stage will match the text but must not assert a canonical
    # concept for it. True for every real entry in both source catalogs
    # today (they're all independently-justified clinical terms) — this
    # only matters once something is deliberately added as text-only.
    clinically_verified: bool = True


def _build_candidate_universe() -> list[_Candidate]:
    candidates: list[_Candidate] = []

    for definition in SYNONYMS_DEFINITIONS:
        candidates.append(
            _Candidate(
                canonical_name=definition["canonical_name"],
                display_name=definition["display_name"],
                category=definition.get("category"),
                aliases=tuple(definition["synonyms"]),
            )
        )

    for definition in lab_catalog.LAB_DEFINITIONS:
        canonical_key = lab_catalog.compact_key(definition.canonical_name) or definition.canonical_name
        candidates.append(
            _Candidate(
                canonical_name=canonical_key,
                display_name=definition.canonical_name,
                category=definition.category,
                aliases=tuple(definition.synonyms) + (definition.canonical_name,),
            )
        )

    return candidates


_CANDIDATES = _build_candidate_universe()


def _score_candidate(raw_normalized: str, candidate: _Candidate) -> tuple[float, str]:
    """Returns (best_similarity, matched_alias_text)."""
    best = 0.0
    best_alias = ""
    for alias in candidate.aliases:
        alias_normalized = _normalize_text(alias)
        if not alias_normalized:
            continue
        similarity = ocr_aware_similarity(raw_normalized, alias_normalized)
        if similarity > best:
            best = similarity
            best_alias = alias
    return best, best_alias


def _stage1_exact(raw: str, raw_normalized: str) -> ResolvedAnalyte | None:
    """`synonyms.normalize_test_name`, unchanged, distinguishing a real
    match from its own synthesized unresolved-fallback shape. Every entry
    in this catalog is an established clinical term, so a match resolves
    both the text and clinical axes at once."""
    result = normalize_test_name(raw)
    fallback_canonical = raw_normalized.replace(" ", "_") if raw_normalized else "unknown_test"
    matched = not (result["category"] == "other" and result["canonical_name"] == fallback_canonical)

    if not matched:
        return None

    return ResolvedAnalyte(
        provider_extracted_name=raw,
        resolved_source_text=raw,
        ocr_match_confidence=1.0,
        resolved=True,
        canonical_name=result["canonical_name"],
        display_name=result["display_name"],
        category=result["category"],
        normalization_confidence=1.0,
        normalization_method=METHOD_EXACT,
    )


def _stage2_alias(raw: str) -> ResolvedAnalyte | None:
    """`lab_catalog.find_lab_definition`, unchanged. Same reasoning as
    stage 1 — every entry is an established clinical term."""
    definition = lab_catalog.find_lab_definition(raw)
    if definition is None:
        return None

    canonical_key = lab_catalog.compact_key(definition.canonical_name) or definition.canonical_name
    return ResolvedAnalyte(
        provider_extracted_name=raw,
        resolved_source_text=raw,
        ocr_match_confidence=1.0,
        resolved=True,
        canonical_name=canonical_key,
        display_name=definition.canonical_name,
        category=definition.category,
        normalization_confidence=0.95,
        normalization_method=METHOD_ALIAS,
    )


def _stage_vendor_specific(raw_normalized: str, institution: str | None) -> ResolvedAnalyte | None:
    """Real, source-specific mappings only — see VENDOR_SPECIFIC_ALIASES'
    docstring. Empty by default; a no-op until real evidence is added for
    a specific institution."""
    if not institution or not VENDOR_SPECIFIC_ALIASES:
        return None

    institution_key = _normalize_text(institution)
    entries = None
    for key, value in VENDOR_SPECIFIC_ALIASES.items():
        if _normalize_text(key) == institution_key:
            entries = value
            break
    if not entries:
        return None

    for entry in entries:
        if _normalize_text(entry.get("alias", "")) == raw_normalized:
            return ResolvedAnalyte(
                provider_extracted_name=raw_normalized,
                resolved_source_text=entry.get("alias", raw_normalized),
                ocr_match_confidence=1.0,
                resolved=True,
                canonical_name=entry.get("canonical_name"),
                display_name=entry.get("display_name"),
                category=entry.get("category"),
                normalization_confidence=1.0,
                normalization_method=METHOD_VENDOR_SPECIFIC,
            )
    return None


def _stage3_ocr_fuzzy(
    raw: str,
    raw_normalized: str,
    unit: str | None,
    category_hint: str | None,
    candidates: list[_Candidate],
) -> ResolvedAnalyte:
    scored: list[tuple[_Candidate, float, str]] = []
    for candidate in candidates:
        score, matched_alias = _score_candidate(raw_normalized, candidate)
        if score > 0:
            scored.append((candidate, score, matched_alias))
    scored.sort(key=lambda item: item[1], reverse=True)

    candidates_considered = [(c.canonical_name, round(s, 3)) for c, s, _alias in scored[:5]]

    if not scored:
        return ResolvedAnalyte(provider_extracted_name=raw, candidates_considered=candidates_considered)

    top_candidate, top_score, top_alias = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
    # Compare by normalized DISPLAY name, not canonical_name: the same
    # real-world concept can appear as two distinct candidates (one from
    # each source catalog, e.g. synonyms.py's "platelet_count" and
    # lab_catalog.py's own separate "Platelet Count" entry) with different
    # canonical_name slugs but the same display name — that's not
    # ambiguity, it's catalog duplication, and must not block a resolution
    # two independent catalogs actually agree on.
    runner_up_is_different = len(scored) > 1 and lab_catalog.compact_key(
        scored[1][0].display_name
    ) != lab_catalog.compact_key(top_candidate.display_name)

    # Genuinely ambiguous: two DIFFERENT candidates too close together —
    # never silently pick one. (Multiple aliases of the SAME candidate
    # scoring similarly is not ambiguity.)
    if runner_up_is_different and runner_up_score >= MEDIUM_CONFIDENCE and (top_score - runner_up_score) < AMBIGUOUS_MARGIN:
        return ResolvedAnalyte(provider_extracted_name=raw, candidates_considered=candidates_considered)

    contextual_bonus = 0.0
    if category_hint and top_candidate.category:
        hint_norm = _normalize_text(category_hint)
        cat_norm = _normalize_text(top_candidate.category)
        if hint_norm and cat_norm and (hint_norm in cat_norm or cat_norm in hint_norm):
            contextual_bonus += 0.03

    unit_conflict = False
    expected_units = _EXPECTED_UNITS.get(top_candidate.canonical_name)
    if expected_units and unit:
        unit_norm = _normalize_text(unit)
        if unit_norm in expected_units:
            contextual_bonus += 0.03
        else:
            # A unit we DO have an expectation for, and it doesn't match,
            # is real negative evidence — not a hard veto (units get
            # mis-OCR'd too), but it should never help a borderline case.
            unit_conflict = True

    effective_score = min(1.0, top_score + (0.0 if unit_conflict else contextual_bonus))

    text_confident = effective_score >= HIGH_CONFIDENCE and not unit_conflict
    text_confident_with_context = (
        effective_score >= MEDIUM_CONFIDENCE and contextual_bonus > 0 and not unit_conflict
    )

    if not (text_confident or text_confident_with_context):
        return ResolvedAnalyte(provider_extracted_name=raw, candidates_considered=candidates_considered)

    # The TEXT match is confident either way — that's axis 1, decided.
    # Axis 2 (clinical meaning) only resolves if this candidate's meaning
    # is actually established.
    if not top_candidate.clinically_verified:
        return ResolvedAnalyte(
            provider_extracted_name=raw,
            resolved_source_text=top_alias,
            ocr_match_confidence=round(effective_score, 3),
            resolved=False,
            display_name=top_alias,
            canonical_name=(_normalize_text(top_alias).replace(" ", "_") or None),
            category="other",
            normalization_confidence=0.0,
            normalization_method=METHOD_TEXT_MATCHED_UNVERIFIED,
            candidates_considered=candidates_considered,
        )

    return ResolvedAnalyte(
        provider_extracted_name=raw,
        resolved_source_text=top_alias,
        ocr_match_confidence=round(effective_score, 3),
        resolved=True,
        canonical_name=top_candidate.canonical_name,
        display_name=top_candidate.display_name,
        category=top_candidate.category,
        normalization_confidence=round(effective_score, 3),
        normalization_method=METHOD_OCR_FUZZY,
        candidates_considered=candidates_considered,
    )


def resolve_analyte(
    raw_test_name: str | None,
    *,
    unit: str | None = None,
    category_hint: str | None = None,
    institution: str | None = None,
    _candidates: list[_Candidate] | None = None,
) -> ResolvedAnalyte:
    """Resolve one raw, provider-extracted analyte name to a Bragi
    canonical concept, or leave it unresolved. Never modifies
    `raw_test_name` — always returned verbatim as `provider_extracted_name`.

    `institution`: optional lab/analyzer name hint — checked against
    `VENDOR_SPECIFIC_ALIASES` (real, source-specific mappings only; empty
    by default, see its docstring) before the generic stages.

    `_candidates`: test-only hook to substitute the candidate universe
    (e.g. to add a `clinically_verified=False` fixture without touching
    the real production catalog) — never set by production call sites.
    """
    raw = (raw_test_name or "").strip()
    if not raw:
        return ResolvedAnalyte(provider_extracted_name=raw)

    raw_normalized = _normalize_text(raw)

    vendor = _stage_vendor_specific(raw_normalized, institution)
    if vendor is not None:
        return vendor

    stage1 = _stage1_exact(raw, raw_normalized)
    if stage1 is not None:
        return stage1

    stage2 = _stage2_alias(raw)
    if stage2 is not None:
        return stage2

    return _stage3_ocr_fuzzy(raw, raw_normalized, unit, category_hint, _candidates or _CANDIDATES)


def resolve_test_name_dict(
    raw_test_name: str | None,
    *,
    unit: str | None = None,
    category_hint: str | None = None,
    institution: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper returning the same dict shape
    `synonyms.normalize_test_name` already returns (raw_test_name,
    canonical_name, display_name, category), plus the new provenance
    fields — a drop-in replacement at call sites that want it.

    Three distinct outcomes:
    - Clinically resolved (`resolved=True`): canonical_name/display_name/
      category reflect a real, established concept.
    - Text-matched but clinically unverified: display_name shows the
      best-matched TEXT (e.g. what the source probably says), but
      canonical_name is a synthesized slug of that text, not a real
      concept, and category is "other" — same shape as fully-unresolved,
      distinguishable via normalization_method.
    - Fully unresolved: display_name falls back to the raw provider text.
    """
    resolved = resolve_analyte(raw_test_name, unit=unit, category_hint=category_hint, institution=institution)

    if resolved.resolved:
        return {
            "raw_test_name": resolved.provider_extracted_name,
            "canonical_name": resolved.canonical_name,
            "display_name": resolved.display_name,
            "category": resolved.category,
            "normalization_confidence": resolved.normalization_confidence,
            "normalization_method": resolved.normalization_method,
            "ocr_match_confidence": resolved.ocr_match_confidence,
            "resolved_source_text": resolved.resolved_source_text or resolved.provider_extracted_name,
        }

    if resolved.normalization_method == METHOD_TEXT_MATCHED_UNVERIFIED:
        return {
            "raw_test_name": resolved.provider_extracted_name,
            "canonical_name": resolved.canonical_name,
            "display_name": resolved.display_name,
            "category": resolved.category,
            "normalization_confidence": 0.0,
            "normalization_method": METHOD_TEXT_MATCHED_UNVERIFIED,
            "ocr_match_confidence": resolved.ocr_match_confidence,
            "resolved_source_text": resolved.resolved_source_text,
        }

    normalized = _normalize_text(resolved.provider_extracted_name)
    cleaned_display = resolved.provider_extracted_name.strip() or "Unknown Test"
    return {
        "raw_test_name": resolved.provider_extracted_name,
        "canonical_name": normalized.replace(" ", "_") if normalized else "unknown_test",
        "display_name": cleaned_display,
        "category": "other",
        "normalization_confidence": 0.0,
        "normalization_method": METHOD_UNRESOLVED,
        "ocr_match_confidence": 0.0,
        "resolved_source_text": resolved.provider_extracted_name,
    }
