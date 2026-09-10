"""Reducto-backed classification, split, and extraction — the real
implementation behind `ReductoExtractionProvider` (see
`extraction_provider.py`).

Kept as its own module (rather than folded into extraction_provider.py)
because it does real work — HTTP calls, response mapping, page-range
filtering — while extraction_provider.py stays the thin interface
`process_upload_job` depends on, matching this repo's existing
one-concern-per-service-module convention.

Every mapping function here was validated against real Reducto API
responses for synthetic Romanian documents before being written (see the
Reducto integration commit message for the full test transcript):
classify (clean + genuinely ambiguous), parse, extract (with citations,
including a 2-page multi-panel lab report), and split (a synthetic 9-page
mixed PDF: pages 1-2 lab / page 3 imaging / pages 4-8 discharge / page 9
prescription, which split correctly at "high" confidence for every
section).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.services.document_taxonomy import DocumentType, is_valid_document_type
from app.services.reducto_client import (
    ReductoClient,
    ReductoError,
    ReductoMalformedResponseError,
)
from app.services.reducto_schemas import (
    CLASSIFICATION_SCHEMA,
    IDENTITY_EXTRACT_SCHEMA,
    LAB_EXTRACT_SCHEMA,
    MIN_CONFIDENT_WINNER_CONFIDENCE,
    NEEDS_CONFIRMATION_MAX_MARGIN,
    NEEDS_CONFIRMATION_RUNNER_UP_MIN_CONFIDENCE,
    READER_EXTRACT_SCHEMAS,
)
from app.services.lab_resolver import resolve_test_name_dict

CLASSIFIED = "classified"
NEEDS_CONFIRMATION = "needs_confirmation"
OTHER = "other"

PARSER_VERSION = "reducto@2026-09"


@dataclass
class ReductoClassification:
    document_type: DocumentType
    status: str
    confidence: float
    category_scores: dict[str, float]
    file_id: str
    job_id: str | None = None


@dataclass
class ReductoSplitSection:
    name: str
    document_type: DocumentType | None
    pages: list[int]
    confidence: str  # "high" | "low", as reported by Reducto


@dataclass
class ReductoSplitResult:
    file_id: str
    total_pages: int
    sections: list[ReductoSplitSection]

    @property
    def is_mixed(self) -> bool:
        """True when Split found more than one *distinct* section — pages
        that don't overlap with any other section's pages, i.e. this
        single upload really does contain multiple separate documents
        back to back.

        Found by testing (not assumed): a genuinely ambiguous single-page
        document — legitimately readable as either of two categories, the
        same real case Classify's own confidence-tie detection exists for
        — comes back from Split as two sections that both claim the SAME
        page, not two sections on different pages. That is same-content
        ambiguity, not a mixed PDF, and must defer to Classify's
        needs_confirmation decision rather than silently becoming two
        overlapping child documents. Only disjoint page sets count as a
        real split.
        """
        non_empty = [s for s in self.sections if s.pages]
        if len(non_empty) <= 1:
            return False

        seen_pages: set[int] = set()
        for section in non_empty:
            pages = set(section.pages)
            if seen_pages & pages:
                return False
            seen_pages |= pages

        return True


@dataclass
class ReductoEvidence:
    page: int | None
    bbox_x: float | None
    bbox_y: float | None
    bbox_width: float | None
    bbox_height: float | None
    source_text: str | None
    confidence: float | None


@dataclass
class ReductoLabExtraction:
    labs: list[dict[str, Any]]
    identity: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReductoReaderExtraction:
    sections: dict[str, str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReductoParseResult:
    text: str
    blocks: list[dict[str, Any]]


def _client() -> ReductoClient:
    return ReductoClient()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _build_classification(file_id: str, body: dict[str, Any]) -> ReductoClassification:
    winner_raw = body["result"]["category"]
    categories = body.get("response_confidence", {}).get("categories", [])
    category_scores = {c["category"]: float(c.get("confidence") or 0.0) for c in categories}

    if not is_valid_document_type(winner_raw):
        # Reducto returned a category string outside our taxonomy — treat
        # conservatively as "other" rather than guessing or crashing.
        winner_raw = "other"

    status, confidence = _decide_status(category_scores, winner_raw)

    return ReductoClassification(
        document_type=DocumentType(winner_raw),
        status=status,
        confidence=confidence,
        category_scores=category_scores,
        file_id=file_id,
        job_id=body.get("job_id"),
    )


def _build_split_result(file_id: str, body: dict[str, Any]) -> ReductoSplitResult:
    result = body["result"]
    total_pages = body.get("usage", {}).get("num_pages") or 0

    sections: list[ReductoSplitSection] = []
    for raw_section in result.get("splits", []):
        name = raw_section.get("name")
        doc_type = DocumentType(name) if is_valid_document_type(name) else None
        sections.append(
            ReductoSplitSection(
                name=name,
                document_type=doc_type,
                pages=sorted(raw_section.get("pages") or []),
                confidence=raw_section.get("conf") or "low",
            )
        )

    return ReductoSplitResult(file_id=file_id, total_pages=total_pages, sections=sections)


def classify_file(file_path: str, filename: str | None = None) -> ReductoClassification:
    client = _client()
    file_id = client.upload(file_path, filename=filename)
    body = client.classify(file_id, CLASSIFICATION_SCHEMA)
    return _build_classification(file_id, body)


def _decide_status(category_scores: dict[str, float], winner: str) -> tuple[str, float]:
    """Ambiguity decision, calibrated against real Reducto output (see
    module docstring) rather than an invented threshold:

    - `winner == "other"` -> file automatically as other, no popup.
    - the winning category's own confidence below
      MIN_CONFIDENT_WINNER_CONFIDENCE -> no real signal -> `other`
      (distinct from ambiguity: "we don't know" vs "we see two
      possibilities").
    - a runner-up scoring close behind (>= its own confidence floor, and
      within the margin of the winner) -> genuine conflicting evidence,
      as observed for a document that legitimately contained both a lab
      table and discharge-summary language -> `needs_confirmation`.
    - otherwise -> `classified`, auto-accept.
    """
    winner_confidence = category_scores.get(winner, 0.0)

    if winner == OTHER:
        return OTHER, winner_confidence

    runner_up_scores = sorted(
        (score for category, score in category_scores.items() if category != winner),
        reverse=True,
    )
    runner_up = runner_up_scores[0] if runner_up_scores else 0.0

    if winner_confidence < MIN_CONFIDENT_WINNER_CONFIDENCE:
        return OTHER, winner_confidence

    if (
        runner_up >= NEEDS_CONFIRMATION_RUNNER_UP_MIN_CONFIDENCE
        and (winner_confidence - runner_up) <= NEEDS_CONFIRMATION_MAX_MARGIN
    ):
        return NEEDS_CONFIRMATION, winner_confidence

    return CLASSIFIED, winner_confidence


# ---------------------------------------------------------------------------
# Split — detect a single upload that actually contains multiple logically
# separate documents (a mixed PDF), so it can be filed as several child
# documents instead of one.
# ---------------------------------------------------------------------------

def split_file(file_id: str, total_pages_hint: int | None = None) -> ReductoSplitResult:
    client = _client()
    body = client.split(file_id, CLASSIFICATION_SCHEMA_AS_SPLIT_DESCRIPTION())
    result = _build_split_result(file_id, body)
    if not result.total_pages and total_pages_hint:
        result.total_pages = total_pages_hint
    return result


def classify_and_check_split(
    file_path: str, filename: str | None = None
) -> tuple[ReductoClassification, ReductoSplitResult | None]:
    """Classify AND check for a mixed-PDF split in parallel, against the
    same uploaded file — they're independent Reducto calls (neither's
    input depends on the other's output), and benchmarking found Split
    costs ~7-10s even on a trivial single-page document that turns out
    non-mixed (vs. ~3-4s for Classify): running them sequentially made
    every single-file upload pay ~12-14s just to learn the document type,
    for no benefit in the (common) non-mixed case. Run concurrently, the
    wait is bounded by the slower call instead of their sum.

    A Split failure here is non-fatal — the caller proceeds as a normal
    single document, exactly as before this existed; only a genuine
    Classify failure propagates.
    """
    client = _client()
    file_id = client.upload(file_path, filename=filename)

    with ThreadPoolExecutor(max_workers=2) as pool:
        classify_future = pool.submit(client.classify, file_id, CLASSIFICATION_SCHEMA)
        split_future = pool.submit(client.split, file_id, CLASSIFICATION_SCHEMA_AS_SPLIT_DESCRIPTION())

        classify_body = classify_future.result()  # real Classify failures should propagate

        try:
            split_body = split_future.result()
        except ReductoError:
            split_body = None

    classification = _build_classification(file_id, classify_body)
    split_result = _build_split_result(file_id, split_body) if split_body is not None else None

    return classification, split_result


def CLASSIFICATION_SCHEMA_AS_SPLIT_DESCRIPTION() -> list[dict[str, Any]]:
    """Split's `split_description` shape is {name, description} — the same
    category/criteria pairs already curated for Classify, reused so a
    mixed document is partitioned along the exact same taxonomy."""
    return [
        {"name": entry["category"], "description": " ".join(entry["criteria"])}
        for entry in CLASSIFICATION_SCHEMA
        if entry["category"] != "other"  # Split has no use for a page range labeled "other"
    ]


# ---------------------------------------------------------------------------
# Extract — laboratory_results
# ---------------------------------------------------------------------------

def _field_value(field_obj: Any) -> Any:
    if isinstance(field_obj, dict) and "value" in field_obj:
        return field_obj.get("value")
    return field_obj


def _field_evidence(field_obj: Any) -> ReductoEvidence | None:
    if not isinstance(field_obj, dict):
        return None
    citations = field_obj.get("citations") or []
    if not citations:
        return None
    citation = citations[0]
    bbox = citation.get("bbox") or {}
    granular = citation.get("granular_confidence") or {}
    confidence = granular.get("extract_confidence")
    if confidence is None:
        confidence = 1.0 if citation.get("confidence") == "high" else 0.0

    return ReductoEvidence(
        page=bbox.get("original_page") or bbox.get("page"),
        bbox_x=bbox.get("left"),
        bbox_y=bbox.get("top"),
        bbox_width=bbox.get("width"),
        bbox_height=bbox.get("height"),
        source_text=citation.get("content"),
        confidence=confidence,
    )


def _in_page_range(evidence: ReductoEvidence | None, page_range: tuple[int, int] | None) -> bool:
    if page_range is None:
        return True
    if evidence is None or evidence.page is None:
        # No page info to filter on — conservatively keep it rather than
        # silently dropping a real result because provenance was thin.
        return True
    start, end = page_range
    return start <= evidence.page <= end


def extract_lab_results(
    file_id: str,
    page_range: tuple[int, int] | None = None,
) -> ReductoLabExtraction:
    client = _client()
    body = client.extract(file_id, LAB_EXTRACT_SCHEMA, citations=True)
    result = body["result"]

    if not isinstance(result, dict):
        raise ReductoMalformedResponseError("Reducto lab extract result was not an object.")

    identity = {
        "patient_name": _field_value(result.get("patient_full_name")),
        "cnp": _field_value(result.get("patient_cnp")),
        "date_of_birth": _field_value(result.get("date_of_birth")),
        "lab_name": _field_value(result.get("institution")),
        "referring_doctor": _field_value(result.get("referring_doctor")),
        "collected_on": _field_value(result.get("collection_date")),
        "reported_on": _field_value(result.get("reported_date")),
    }

    labs: list[dict[str, Any]] = []
    warnings: list[str] = []

    raw_results = result.get("results")
    raw_items = _field_value(raw_results) if isinstance(raw_results, dict) else raw_results
    if not isinstance(raw_items, list):
        raw_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        test_name = _field_value(item.get("test_name"))
        if not test_name:
            continue

        name_evidence = _field_evidence(item.get("test_name"))
        if not _in_page_range(name_evidence, page_range):
            continue

        item_unit = _field_value(item.get("unit"))
        item_section = _field_value(item.get("section"))
        # Generic OCR-aware resolver (app/services/lab_resolver.py) — tries
        # the existing exact/alias matchers first; only falls to
        # confusion-aware fuzzy scoring if those find nothing. Never
        # modifies `test_name` itself — the provider's raw extraction is
        # preserved verbatim as `raw_test_name` below regardless of what
        # (if anything) it resolves to.
        normalized = resolve_test_name_dict(test_name, unit=item_unit, category_hint=item_section)
        value = _field_value(item.get("value"))
        confidence_parts = [
            _field_evidence(item.get(k)) for k in ("test_name", "value", "unit", "reference_range")
        ]
        confidences = [e.confidence for e in confidence_parts if e and e.confidence is not None]
        overall_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

        evidence = _field_evidence(item.get("value")) or name_evidence

        labs.append(
            {
                "raw_test_name": normalized["raw_test_name"],
                "canonical_name": normalized["canonical_name"],
                "display_name": normalized["display_name"],
                "category": normalized["category"],
                "source_section": item_section,
                "value": value,
                "unit": item_unit,
                "reference_range": _field_value(item.get("reference_range")),
                "flag": _field_value(item.get("flag")),
                "confidence": overall_confidence,
                "normalization_confidence": normalized.get("normalization_confidence"),
                "normalization_method": normalized.get("normalization_method"),
                "evidence": evidence,
            }
        )

    if not labs:
        warnings.append("Reducto extract returned no laboratory results for this document.")

    return ReductoLabExtraction(labs=labs, identity=identity, warnings=warnings)


# ---------------------------------------------------------------------------
# Extract — identity only (used for narrative document types whose reader
# schema has no identity fields of its own)
# ---------------------------------------------------------------------------

def extract_identity(file_id: str) -> dict[str, Any]:
    client = _client()
    body = client.extract(file_id, IDENTITY_EXTRACT_SCHEMA, citations=False)
    result = body["result"]

    if isinstance(result, list):
        result = result[0] if result else {}

    return {
        "patient_name": _field_value(result.get("patient_full_name")),
        "cnp": _field_value(result.get("patient_cnp")),
        "date_of_birth": _field_value(result.get("date_of_birth")),
        "patient_identifier": _field_value(result.get("patient_identifier")),
    }


# ---------------------------------------------------------------------------
# Extract — narrative reader types (imaging/operative/pathology/
# prescription/medication_list/specialist_consultation)
# ---------------------------------------------------------------------------

def extract_reader_sections(file_id: str, document_type: str) -> ReductoReaderExtraction:
    schema = READER_EXTRACT_SCHEMAS.get(document_type)
    if not schema or not schema.get("properties"):
        return ReductoReaderExtraction(sections={}, warnings=[f"No Reducto reader schema for {document_type}."])

    client = _client()
    body = client.extract(file_id, schema, citations=False)
    result = body["result"]

    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        return ReductoReaderExtraction(sections={}, warnings=["Reducto reader extract result was not an object."])

    sections: dict[str, str] = {}
    for key in schema["properties"]:
        value = _field_value(result.get(key))
        if isinstance(value, str) and value.strip() and value.strip().lower() not in ("null", "none"):
            sections[key] = value.strip()
        elif isinstance(value, (list, dict)) and value:
            import json as _json

            sections[key] = _json.dumps(value, ensure_ascii=False)

    warnings = [] if sections else ["No structured sections were extracted from this document."]
    return ReductoReaderExtraction(sections=sections, warnings=warnings)


# ---------------------------------------------------------------------------
# Parse — the full document read (text + page/bbox-tagged blocks), stored
# so the Reader and full-text search have the complete document, not just
# whatever a narrow Extract schema happened to ask for. Verified live: a
# 2-page synthetic lab report came back as a single chunk whose `content`
# is the full page-ordered markdown (headings, both tables, signature
# line) — used directly as `extracted_text` in place of the earlier
# labs-only/sections-only synthesized text.
# ---------------------------------------------------------------------------

def parse_document(file_id: str) -> ReductoParseResult:
    client = _client()
    body = client.parse(file_id)
    result = body["result"]

    chunks = result.get("chunks") or []
    text = "\n\n".join(chunk.get("content", "") for chunk in chunks if chunk.get("content"))

    blocks: list[dict[str, Any]] = []
    for chunk in chunks:
        for block in chunk.get("blocks") or []:
            bbox = block.get("bbox") or {}
            blocks.append(
                {
                    "type": block.get("type"),
                    "page": bbox.get("original_page") or bbox.get("page"),
                    "bbox_x": bbox.get("left"),
                    "bbox_y": bbox.get("top"),
                    "bbox_width": bbox.get("width"),
                    "bbox_height": bbox.get("height"),
                    "content": block.get("content"),
                    "confidence": block.get("confidence"),
                }
            )

    return ReductoParseResult(text=text, blocks=blocks)


# ---------------------------------------------------------------------------
# Pipeline-result builders — shape-compatible with what process_upload_job
# already expects from process_uploaded_document/process_uploaded_discharge_summary
# (see main.py), so the Document/LabResult/SourceEvidence creation code
# downstream runs completely unchanged regardless of which provider produced
# the data.
# ---------------------------------------------------------------------------

def _labs_to_extracted_text(labs: list[dict[str, Any]], identity: dict[str, Any]) -> str:
    lines = ["BULETIN DE ANALIZE (Reducto)"]
    for key, label in (("patient_name", "Pacient"), ("cnp", "CNP"), ("lab_name", "Laborator")):
        if identity.get(key):
            lines.append(f"{label}: {identity[key]}")
    lines.append("")
    for lab in labs:
        parts = [lab.get("raw_test_name"), lab.get("value"), lab.get("unit")]
        row = " ".join(str(p) for p in parts if p)
        if lab.get("reference_range"):
            row += f" (ref: {lab['reference_range']})"
        if lab.get("flag"):
            row += f" [{lab['flag']}]"
        lines.append(row)
    return "\n".join(lines)


def _sections_to_extracted_text(sections: dict[str, str]) -> str:
    return "\n\n".join(f"{key.replace('_', ' ').upper()}\n{value}" for key, value in sections.items())


def _try_parse_document(file_id: str) -> ReductoParseResult | None:
    """Parse is best-effort on top of a successful Extract — a Parse
    failure must not blank out labs/sections that already extracted fine.
    Falls back to None; callers use their own synthesized text instead."""
    try:
        return parse_document(file_id)
    except ReductoError as error:
        print(f"Reducto parse (persistence) failed for {file_id}, falling back to synthesized text: {error}")
        return None


def build_pipeline_result_labs(file_id: str, page_range: tuple[int, int] | None = None) -> dict[str, Any]:
    """Real Reducto Extract for a laboratory_results document, mapped into
    the same `{extracted_text, parsed_data: {..., labs: [...]}}` shape the
    legacy bloodwork pipeline (`document_pipeline.process_bloodwork_document`)
    already produces — main.py's Document/LabResult/SourceEvidence creation
    code is untouched. Also runs real Reducto Parse and persists its full
    text + page/bbox blocks (`parsed_content`) so the Reader/search have
    the complete document, not just the lab table Extract asked for."""
    extraction = extract_lab_results(file_id, page_range=page_range)
    parsed = _try_parse_document(file_id)

    parsed_data = {
        "patient_name": extraction.identity.get("patient_name"),
        "date_of_birth": extraction.identity.get("date_of_birth"),
        "cnp": extraction.identity.get("cnp"),
        "lab_name": extraction.identity.get("lab_name"),
        "referring_doctor": extraction.identity.get("referring_doctor"),
        "collected_on": extraction.identity.get("collected_on"),
        "reported_on": extraction.identity.get("reported_on"),
        "labs": extraction.labs,
        "report_name": "Laboratory Results",
        "report_type": "laboratory_results",
        "warnings": extraction.warnings,
    }

    extracted_text = (parsed.text if parsed and parsed.text else None) or _labs_to_extracted_text(
        extraction.labs, extraction.identity
    )

    return {
        "extracted_text": extracted_text,
        "parsed_data": parsed_data,
        "parsed_content": {"blocks": parsed.blocks, "provider": "reducto", "parser_version": PARSER_VERSION} if parsed else None,
        "warnings": extraction.warnings,
    }


def build_pipeline_result_reader(file_id: str, document_type: str) -> dict[str, Any]:
    """Real Reducto Extract for a narrative reader document type, mapped
    into the same pipeline_result shape process_upload_job already reads,
    plus `_reducto_structured_sections` (already in the exact
    `structured_reader_service.extract_structured_sections` return shape)
    so the Phase 4 Reader call site can use it directly instead of paying
    for a second (OpenAI) extraction of the same document."""
    reader = extract_reader_sections(file_id, document_type)
    parsed = _try_parse_document(file_id)

    try:
        identity = extract_identity(file_id)
    except ReductoMalformedResponseError:
        identity = {}

    extracted_text = (parsed.text if parsed and parsed.text else None) or _sections_to_extracted_text(reader.sections)

    parsed_data = {
        "patient_name": identity.get("patient_name"),
        "date_of_birth": identity.get("date_of_birth"),
        "cnp": identity.get("cnp"),
        "patient_identifier": identity.get("patient_identifier"),
        "labs": [],
        "report_name": document_type.replace("_", " ").title(),
        "report_type": document_type,
        "warnings": reader.warnings,
    }

    return {
        "extracted_text": extracted_text,
        "note_body": extracted_text or None,
        "parsed_data": parsed_data,
        "_reducto_structured_sections": {"language": None, "sections": reader.sections, "warnings": reader.warnings},
        "parsed_content": {"blocks": parsed.blocks, "provider": "reducto", "parser_version": PARSER_VERSION} if parsed else None,
        "warnings": reader.warnings,
    }
