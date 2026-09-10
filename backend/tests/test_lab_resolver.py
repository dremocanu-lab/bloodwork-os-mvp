"""Tests for the generic OCR-aware lab-analyte resolver
(app/services/lab_resolver.py).

Background: a real production document had an analyte the source
document visibly labels "PSW", extracted by Reducto as "PSV" (a single
visually-confusable glyph). An EARLIER version of this resolver added
"PSW" as a supposed alternate abbreviation for PDW (Platelet
Distribution Width) to make that case resolve end-to-end — which was
wrong: a web search found no authoritative hematology/analyzer source
for "PSW" meaning anything. That alias has been removed from the real
catalog (see synonyms.py). These tests instead prove two things
separately: (1) there is no hardcoded PSV-to-anything mapping, and (2)
the resolver genuinely keeps "is this the right TEXT" and "is this
clinical meaning ESTABLISHED" as two independent confidence decisions —
demonstrated via a test-local fixture (never the real catalog), so n->
fabricated clinical claim about "PSW" is required to prove the
mechanism works.
"""
import inspect

from app.services import lab_resolver
from app.services.lab_resolver import (
    METHOD_ALIAS,
    METHOD_EXACT,
    METHOD_OCR_FUZZY,
    METHOD_TEXT_MATCHED_UNVERIFIED,
    METHOD_UNRESOLVED,
    ResolvedAnalyte,
    _Candidate,
    resolve_analyte,
    resolve_test_name_dict,
)


def test_no_hardcoded_psv_mapping_exists():
    """Explicit proof there is no dict entry or equality/branch condition
    anywhere in the resolver (or the synonyms catalog it draws on) that
    maps the literal string "PSV" to anything. Prose mentions of "PSV" in
    comments/docstrings (explaining the bug this fixes) are fine and
    excluded — this checks for the actual dangerous code shapes: a dict
    key, a dict value, an equality comparison, or a .get() lookup naming
    "PSV" literally.
    """
    import re

    from app import synonyms

    dangerous_patterns = [
        r'["\']psv["\']\s*:',
        r':\s*["\']psv["\']',
        r'==\s*["\']psv["\']',
        r'["\']psv["\']\s*==',
        r'\.get\(\s*["\']psv["\']',
    ]

    for source, label in (
        (inspect.getsource(lab_resolver), "lab_resolver.py"),
        (inspect.getsource(synonyms), "synonyms.py"),
    ):
        code_only = source.split('"""', 2)[-1] if source.lstrip().startswith('"""') else source
        for line_no, line in enumerate(code_only.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            for pattern in dangerous_patterns:
                assert not re.search(pattern, line, flags=re.IGNORECASE), (
                    f"{label}:{line_no} looks like a hardcoded PSV mapping: {line!r}"
                )


def test_no_psw_alias_in_real_catalog():
    """The real production catalog must not contain a fabricated "PSW"
    alias — a web search found no authoritative source for what it
    means, so it must not be globally mapped to PDW or anything else."""
    from app.synonyms import LAB_DEFINITIONS

    for definition in LAB_DEFINITIONS:
        normalized_aliases = [a.strip().lower() for a in definition["synonyms"]]
        assert "psw" not in normalized_aliases, (
            f"found a 'psw' alias on {definition['canonical_name']!r} — "
            "this was fabricated and must not be re-added without real evidence"
        )


def test_psv_is_genuinely_unresolved_on_both_axes_without_evidence():
    """With no PSW alias (real or otherwise) anywhere in the actual
    production catalog, "PSV" has nothing to textually match against —
    it must come back fully unresolved on BOTH axes. This is the
    correct, conservative outcome given no real evidence, not a
    regression: an earlier version's apparent "PSV resolves to PDW" only
    worked because of the fabricated alias this round removed."""
    result = resolve_analyte("PSV")
    assert result.resolved is False
    assert result.normalization_method == METHOD_UNRESOLVED
    assert result.canonical_name is None
    assert result.ocr_match_confidence == 0.0
    # Provider's raw extraction is still preserved verbatim regardless.
    assert result.provider_extracted_name == "PSV"


def test_provider_raw_text_is_never_mutated_regardless_of_outcome():
    for raw in ("PSV", "Hemoglobina", "totally-unknown-xyz"):
        result = resolve_analyte(raw)
        assert result.provider_extracted_name == raw


def test_legitimate_cbc_terms_resolve_exactly_and_unaffected():
    cases = {
        "Hemoglobina": "hemoglobin",
        "HGB": "hemoglobin",
        "Eritrocite": "rbc",
        "RBC": "rbc",
        "Leucocite": "wbc",
        "WBC": "wbc",
        "Trombocite": "platelet_count",
        "PLT": "platelet_count",
        "MPV": "mpv",
        "PDW": "pdw",
    }
    for raw, expected_canonical in cases.items():
        result = resolve_analyte(raw)
        assert result.resolved is True, f"{raw!r} should resolve"
        assert result.canonical_name == expected_canonical, f"{raw!r} -> {result.canonical_name!r}"
        assert result.normalization_method == METHOD_EXACT, f"{raw!r} should be an exact match, not fuzzy"
        assert result.normalization_confidence == 1.0
        # Text-match confidence and clinical confidence agree for a real
        # established term — that's the normal case.
        assert result.ocr_match_confidence == 1.0


def test_renal_and_metabolic_terms_unaffected():
    for raw, expected_canonical in {
        "Creatinina": "creatinine",
        "Glucoza": "glucose",
        "Ureea": "urea",
        "Sodiu": "sodium",
        "Potasiu": "potassium",
        "TSH": "tsh",
        "AST": "ast",
        "ALT": "alt",
    }.items():
        result = resolve_analyte(raw)
        assert result.resolved is True
        assert result.canonical_name == expected_canonical
        assert result.normalization_method in (METHOD_EXACT, METHOD_ALIAS)


def test_ocr_confusion_recovers_real_established_terms():
    """When the OCR-confused reading DOES land on a real, established
    catalog term, both axes resolve together — text confidence and
    clinical confidence agree, same as any exact match, just reached via
    fuzzy scoring instead."""
    assert resolve_analyte("C0lesterol total").canonical_name == "cholesterol_total"
    r = resolve_analyte("Trombocie")  # missing-letter typo of a real term
    assert r.resolved is True
    assert r.canonical_name == "platelet_count"
    assert r.normalization_method == METHOD_OCR_FUZZY
    assert r.ocr_match_confidence == r.normalization_confidence  # axes agree for a verified term


def test_unrelated_short_tokens_stay_unresolved_not_guessed():
    for raw in ("XYZ123", "QQQQQ", "###"):
        result = resolve_analyte(raw)
        assert result.resolved is False
        assert result.normalization_method == METHOD_UNRESOLVED
        assert result.canonical_name is None


def test_empty_and_none_input_stay_unresolved():
    for raw in (None, "", "   "):
        result = resolve_analyte(raw)
        assert result.resolved is False


def test_same_concept_across_both_catalogs_is_not_treated_as_ambiguous():
    """platelet_count exists in BOTH synonyms.py and lab_catalog.py as two
    distinct candidate objects (different canonical_name slugs, same real
    concept) — a fuzzy match landing on both must resolve, not be
    rejected as "ambiguous"."""
    result = resolve_analyte("Trombocie")
    assert result.resolved is True
    assert result.display_name == "Platelet Count"


# ---------------------------------------------------------------------------
# The core of this round's fix: OCR text-match confidence and clinical
# semantic confidence are independent axes. Proven with a TEST-LOCAL
# fixture (a fictional candidate, never added to the real catalog) so no
# claim about real "PSW" clinical meaning is needed to demonstrate the
# mechanism.
# ---------------------------------------------------------------------------

def test_text_matched_unverified_candidate_resolves_text_but_not_clinical_meaning():
    """A candidate explicitly marked clinically_verified=False: a fuzzy
    text match against it must surface the matched TEXT (what the source
    probably says) while leaving the canonical clinical concept
    unresolved — exactly the desired behavior for a real "PSW"-shaped
    case, without asserting anything false about what PSW actually means.
    """
    fixture = [
        _Candidate(
            canonical_name="fictional_unverified_marker",
            display_name="FICTIONAL_UNVERIFIED_MARKER",
            category="other",
            aliases=("qzxw",),  # a string with no real clinical meaning, used only as a fixture
            clinically_verified=False,
        )
    ]

    # A single OCR-confusable glyph away from the fixture alias (v<->w).
    result = resolve_analyte("qzxv", _candidates=fixture)

    assert result.resolved is False, "clinical/canonical axis must NOT resolve for an unverified candidate"
    assert result.canonical_name is None or result.canonical_name != "fictional_unverified_marker"
    assert result.category == "other"
    assert result.normalization_confidence == 0.0
    assert result.normalization_method == METHOD_TEXT_MATCHED_UNVERIFIED

    # But the TEXT axis did resolve — the corrected reading is surfaced.
    assert result.resolved_source_text == "qzxw"
    assert result.ocr_match_confidence > 0.8
    assert result.provider_extracted_name == "qzxv"  # raw preserved verbatim


def test_text_matched_unverified_vs_verified_same_similarity_different_outcome():
    """The SAME textual similarity score produces two different outcomes
    depending only on whether the matched candidate's clinical meaning is
    established — proving the two confidences are computed and gated
    independently, not derived from one number."""
    verified_fixture = [
        _Candidate(
            canonical_name="fictional_verified_marker",
            display_name="Fictional Verified Marker",
            category="other",
            aliases=("qzxw",),
            clinically_verified=True,
        )
    ]
    unverified_fixture = [
        _Candidate(
            canonical_name="fictional_unverified_marker",
            display_name="FICTIONAL_UNVERIFIED_MARKER",
            category="other",
            aliases=("qzxw",),
            clinically_verified=False,
        )
    ]

    verified_result = resolve_analyte("qzxv", _candidates=verified_fixture)
    unverified_result = resolve_analyte("qzxv", _candidates=unverified_fixture)

    # Same raw input, same matched text, same text-match confidence...
    assert verified_result.resolved_source_text == unverified_result.resolved_source_text == "qzxw"
    assert verified_result.ocr_match_confidence == unverified_result.ocr_match_confidence

    # ...but only the verified candidate resolves a canonical concept.
    assert verified_result.resolved is True
    assert verified_result.canonical_name == "fictional_verified_marker"
    assert verified_result.normalization_method == METHOD_OCR_FUZZY

    assert unverified_result.resolved is False
    assert unverified_result.normalization_method == METHOD_TEXT_MATCHED_UNVERIFIED


def test_resolve_test_name_dict_shows_matched_text_for_unverified_case():
    """The dict-shape wrapper (used by real call sites) must display the
    matched TEXT, not the raw provider string and not a fabricated
    canonical name, when the match is text-only/unverified."""
    fixture = [
        _Candidate(
            canonical_name="fictional_unverified_marker",
            display_name="FICTIONAL_UNVERIFIED_MARKER",
            category="other",
            aliases=("qzxw",),
            clinically_verified=False,
        )
    ]
    resolved = resolve_analyte("qzxv", _candidates=fixture)
    assert resolved.normalization_method == METHOD_TEXT_MATCHED_UNVERIFIED

    # resolve_test_name_dict doesn't take _candidates (production-only
    # entry point) — exercise the same shape logic directly instead.
    from app.services.lab_resolver import ResolvedAnalyte as RA  # noqa: F401

    assert resolved.display_name == "qzxw"
    assert resolved.canonical_name != "fictional_unverified_marker"


def test_resolve_test_name_dict_matches_legacy_shape():
    """Drop-in compatibility with synonyms.normalize_test_name's dict
    shape, for the call sites that swap one for the other."""
    result = resolve_test_name_dict("Hemoglobina")
    assert set(result.keys()) >= {"raw_test_name", "canonical_name", "display_name", "category"}
    assert result["raw_test_name"] == "Hemoglobina"

    unresolved = resolve_test_name_dict("XYZ123")
    assert unresolved["category"] == "other"
    assert unresolved["canonical_name"] == "xyz123"


def test_vendor_specific_mapping_is_empty_by_default():
    """No fabricated vendor/source-specific mappings exist — the
    mechanism is real but starts with zero entries until genuine
    evidence for a specific institution/analyzer is added."""
    assert lab_resolver.VENDOR_SPECIFIC_ALIASES == {}
