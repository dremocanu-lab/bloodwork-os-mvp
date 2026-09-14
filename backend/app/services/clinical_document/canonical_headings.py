"""Deterministic canonical-heading classification — Clinical Document
Intelligence V3, Phase 4 (first increment).

Maps a RAW source heading (the text as it actually appears on the page,
e.g. "EPICRIZĂ", "TRATAMENT RECOMANDAT", "REȚETE ELIBERATE") to one of
the fixed 19 `CanonicalSectionKey` values from `schema.py`. Deterministic
keyword/phrase matching only — no LLM call, per the V3 contract's
"deterministic normalization first" instruction. `"other"` is returned
only after every named category has been tried and none matched, never
as a shortcut.

This is DIFFERENT from — and supersedes, for anything parsed going
forward — the `_LEGACY_KEY_TO_CANONICAL` mapping in `persistence.py`:
that one is a narrow backward-compat stopgap translating the CURRENT
discharge pipeline's own fixed 13-key `ALLOWED_SECTION_KEYS` vocabulary
(the model's coarse classification) into a canonical key. This module
instead classifies the REAL heading text itself (`section["title"]` in
the current pipeline's terms), which is what the V3 contract's own
worked examples are actually about, and is closer to what any future
raw/OCR heading would need too — not tied to that fixed 13-key set.

Not yet wired into `discharge_summary_pipeline.py` — that wiring (plus
domain extractors and validated `StructuredClinicalDocument` assembly)
is the rest of Phase 4, tracked separately. This module and
`merge_headings_into_sections` below are usable, tested building blocks
for that wiring, kept independently testable in the meantime.
"""

from __future__ import annotations

from app.services.lab_catalog import normalize_text

from .schema import CanonicalSectionKey, ClinicalSection, ParagraphBlock

# Ordered most-specific-first: a heading is classified into the FIRST
# canonical key whose pattern list contains a normalized substring match.
# Order matters where categories could otherwise collide (e.g.
# "medicatie la externare" must be checked as discharge_medications
# BEFORE the broader "medicatie"/medications patterns get a chance to
# swallow it). Every pattern here is already normalize_text()'d (ASCII,
# lowercase, punctuation collapsed to spaces) so it can be matched with a
# plain substring test against a normalized heading.
_CLASSIFICATION_ORDER: tuple[tuple[CanonicalSectionKey, tuple[str, ...]], ...] = (
    (
        "discharge_medications",
        ("medicatie la externare", "tratament medicamentos la externare", "discharge medications"),
    ),
    (
        "medications",
        ("medicatie curenta", "medicatie de fond", "medicamente", "medicatie", "medications"),
    ),
    (
        "clinical_course",
        ("epicriza", "evolutia bolii", "evolutie clinica", "evolutie sub tratament", "evolutie", "clinical course"),
    ),
    (
        "recommendations",
        ("tratament recomandat", "recomandari la externare", "recomandari", "recommendations"),
    ),
    (
        "treatment",
        (
            "tratament administrat",
            "tratament efectuat",
            "tratament in timpul internarii",
            "tratament in spital",
            "treatment administered",
            "treatment",
        ),
    ),
    (
        "prescriptions",
        ("retete eliberate", "reteta eliberata", "prescriptions", "reteta"),
    ),
    (
        "laboratory_results",
        (
            "examen de laborator",
            "examene de laborator",
            "analize de laborator",
            "rezultate de laborator",
            "laboratory results",
            "laborator",
        ),
    ),
    (
        # Checked BEFORE "imaging": the current discharge pipeline's own
        # fallback title for this legacy key is literally
        # "Investigations / imaging" (see discharge_summary_pipeline.py's
        # SECTION_TITLE_BY_KEY) — a bare "imaging" pattern checked first
        # would wrongly classify that exact compound heading as imaging
        # instead of investigations. Romanian discharge summaries also
        # commonly use "investigatii"/"explorari" as the umbrella heading
        # that INCLUDES imaging findings underneath it.
        "investigations",
        ("investigatii", "examene paraclinice", "explorari paraclinice", "investigations"),
    ),
    (
        "imaging",
        ("imagistica", "radiologie", "ecografie", "tomografie", "rezonanta magnetica"),
    ),
    (
        "procedures",
        ("proceduri efectuate", "interventii chirurgicale", "protocol operator", "procedures"),
    ),
    (
        "diagnoses",
        (
            "diagnostic principal",
            "diagnostic secundar",
            "diagnostic la internare",
            "diagnostic la externare",
            "diagnoze",
            "diagnostic",
            "diagnoses",
        ),
    ),
    (
        "medical_history",
        ("antecedente heredocolaterale", "antecedente personale", "antecedente", "istoric medical", "medical history"),
    ),
    (
        "examination",
        ("examen clinic", "examen obiectiv", "examinare fizica", "examination"),
    ),
    (
        "encounter_details",
        ("stare la externare", "date despre internare", "date internare", "discharge status", "encounter details"),
    ),
    (
        "administrative_information",
        ("date administrative", "date de identificare", "informatii administrative", "administrative information"),
    ),
    (
        "follow_up",
        ("control periodic", "urmarire", "follow up", "follow-up", "control"),
    ),
    (
        "signatures",
        ("semnatura", "semnat", "signatures"),
    ),
    (
        "overview",
        ("rezumat", "sumar", "overview"),
    ),
)


def classify_canonical_heading(raw_heading: str | None) -> CanonicalSectionKey:
    """Deterministic, no LLM call. Returns `"other"` only after every
    named category above has been tried and none matched a normalized
    substring of `raw_heading` — never a shortcut."""
    normalized = normalize_text(raw_heading)
    if not normalized:
        return "other"
    for canonical_key, patterns in _CLASSIFICATION_ORDER:
        if any(pattern in normalized for pattern in patterns):
            return canonical_key
    return "other"


def merge_headings_into_sections(
    raw_sections: list[tuple[str, str]],
) -> list[ClinicalSection]:
    """Classifies and merges a document-ordered list of
    `(raw_heading, body_text)` pairs into canonical `ClinicalSection`s —
    the general form of the V3 contract's "repeated headings merge into
    ONE canonical entry" rule, for ANY raw heading text (not tied to the
    current pipeline's fixed 13-key vocabulary — contrast with
    `persistence.py`'s `_upconvert_legacy_discharge_payload`, which is a
    narrower backward-compat path for that specific old shape).

    Two sections classified to the SAME canonical key merge into ONE
    `ClinicalSection`: `order` is the first occurrence's position,
    `source_headings` preserves every distinct original heading in
    encounter order, and each contributor's body becomes its OWN
    `ParagraphBlock` (never concatenated into one string) — callers with
    richer per-contributor structure (tables, key/value pairs, etc.)
    should build their own blocks and use this function's classification
    step directly instead, rather than forcing everything through
    `ParagraphBlock`.
    """
    merged: dict[str, ClinicalSection] = {}
    order_counter = 0

    for heading, body in raw_sections:
        canonical_key = classify_canonical_heading(heading)
        body_text = (body or "").strip()

        existing = merged.get(canonical_key)
        if existing is None:
            merged[canonical_key] = ClinicalSection(
                id=f"section-{canonical_key}",
                canonical_key=canonical_key,
                display_title=heading or canonical_key.replace("_", " ").title(),
                source_headings=[heading] if heading else [],
                order=order_counter,
                blocks=[ParagraphBlock(text=body_text)] if body_text else [],
                review_state="auto",
            )
            order_counter += 1
        else:
            if heading and heading not in existing.source_headings:
                existing.source_headings.append(heading)
            if body_text:
                existing.blocks.append(ParagraphBlock(text=body_text))

    return list(merged.values())
