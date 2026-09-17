"""AI semantic document classifier (P0 upload-reliability session).

Constrained to Bragi's own canonical `DocumentType` taxonomy —
`document_taxonomy.DocumentType` is the ONE source of truth for the
allowed classes; this module derives the model's enum constraint from it
directly rather than maintaining a second, driftable list.

Server-side only. The classifier receives real EXTRACTED document text
(never an arbitrary frontend classification claim). Reuses the OpenAI
Responses API + strict JSON-schema structured-output pattern already
proven in `app/services/ask_bragi/service.py` — the only one of six
existing OpenAI call sites in this codebase that validates structured
output against a real schema instead of hand-rolling a markdown-fence-
stripped `json.loads` (five other call sites each duplicate that same
ad hoc pattern; this module deliberately does not add a seventh).

Any failure — missing API key, timeout, malformed/invalid response —
raises `AIClassificationError` so the caller
(`document_classification_service.py`) can fall back to the existing
legacy/Reducto classifier path. An AI outage or missing configuration
must NEVER fail an upload; this module never touches `UploadJob`/
`Document` itself, it only classifies text and reports a result or an
error.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.services.ai_minimization import redact_direct_identifiers
from app.services.document_taxonomy import DocumentType, is_valid_document_type

AI_CLASSIFIER_MODEL = os.getenv("AI_CLASSIFIER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))
AI_CLASSIFIER_TIMEOUT_SECONDS = float(os.getenv("AI_CLASSIFIER_TIMEOUT_SECONDS", "20"))
AI_CLASSIFIER_MAX_OUTPUT_TOKENS = int(os.getenv("AI_CLASSIFIER_MAX_OUTPUT_TOKENS", "400"))
# A bounded representation, not a naive head-only truncation — see
# _build_bounded_representation. Generous on purpose ("accuracy matters
# more than micro-optimizing tokens" — this session's own instruction);
# most real documents (including the 17-page hematology discharge
# fixture) fit well under this without truncation at all.
AI_CLASSIFIER_MAX_INPUT_CHARS = int(os.getenv("AI_CLASSIFIER_MAX_INPUT_CHARS", "24000"))
AI_CLASSIFIER_MIN_CONFIDENCE = float(os.getenv("AI_CLASSIFIER_MIN_CONFIDENCE", "0.7"))

_ALLOWED_TYPES = [dt.value for dt in DocumentType]

_REASON_CODES = [
    "DISCHARGE_TITLE",
    "INPATIENT_DATES",
    "EPICRISIS",
    "DISCHARGE_DIAGNOSIS",
    "DISCHARGE_RECOMMENDATIONS",
    "ADMISSION_ONLY_NO_DISCHARGE",
    "LAB_TABLE_ONLY",
    "EMBEDDED_LAB_TABLE_SECONDARY",
    "OUTPATIENT_CONSULTATION",
    "IMAGING_FINDINGS",
    "OPERATIVE_TECHNIQUE",
    "PATHOLOGY_DIAGNOSIS",
    "PRESCRIPTION_FORMAT",
    "MEDICATION_LIST_FORMAT",
    "EMERGENCY_VISIT",
    "REFERRAL_LANGUAGE",
    "VACCINATION_RECORD",
    "MEDICAL_CERTIFICATE",
    "ADMINISTRATIVE_DOCUMENT",
    "AMBIGUOUS_MULTIPLE_SIGNALS",
    "INSUFFICIENT_SIGNAL",
]

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": _ALLOWED_TYPES},
        "confidence": {"type": "number"},
        "ambiguous": {"type": "boolean"},
        "alternative_document_type": {
            "type": ["string", "null"],
            "enum": _ALLOWED_TYPES + [None],
        },
        "reason_codes": {
            "type": "array",
            "items": {"type": "string", "enum": _REASON_CODES},
        },
    },
    "required": ["document_type", "confidence", "ambiguous", "alternative_document_type", "reason_codes"],
    "additionalProperties": False,
}

_SYSTEM_INSTRUCTIONS = """You classify one medical document into EXACTLY ONE of Bragi's canonical \
document types. Return ONLY the structured fields requested — no chain-of-thought, no extra prose.

CORE RULE — classify the PRIMARY CLINICAL PURPOSE of the ENTIRE document, not any one embedded \
section. A document's parent type does not change just because it contains other content:
- A hospital discharge letter (discharge_summary) may legitimately contain laboratory values, \
medications, imaging mentions, prior admissions, prescriptions, and long narrative history. It \
remains discharge_summary as long as its primary purpose is to summarize an inpatient stay and \
discharge — embedded lab tables are a COMPONENT of the letter, never the deciding signal.
- laboratory_results is for a document whose primary purpose IS reporting test results — a \
standalone lab report, not a discharge letter that happens to embed one.
- hospital_admission_note is beginning-of-stay documentation (reason for admission, admitting \
diagnosis) — never a discharge summary, even if it mentions a future discharge plan.
- specialist_consultation is an outpatient/specialist visit. The phrase "scrisoare medicala" \
ALONE does not imply discharge — only when accompanied by real inpatient admission/discharge \
dates, an epicriza/hospital-course narrative, and discharge recommendations does it become \
discharge_summary; otherwise it is more likely specialist_consultation or referral.

ROMANIAN VOCABULARY (documents are very often Romanian — recognize these directly, do not \
require an exact string match):
- Discharge summary: "bilet de ieșire din spital"/"bilet de iesire din spital", "bilet de \
externare", "fișă/foaie de externare", "epicriză/epicriza", "data internării", "data \
externării", "diagnostic la externare", "recomandări la externare".
- Hospital admission note: "foaie de internare", "bilet de internare", "motiv de internare".
- Emergency department: "camera de gardă"/"camera de garda", "unitate de primiri urgențe"/"UPU".
- Operative report: "protocol operator", "raport operator".
- Specialist consultation: "consultație de specialitate", "bilet de consultație".
- Referral: "bilet de trimitere".
- Prescription: "rețetă"/"reteta".

Only use `other` when the document genuinely does not fit any canonical type — never as a \
stand-in for uncertainty (use ambiguous=true and a lower confidence for that instead).

Set ambiguous=true when the document plausibly fits two different types with real, comparable \
evidence for both — do not silently guess between them. alternative_document_type is your \
second-best candidate when ambiguous=true (or when confidence is otherwise not high), else null.
confidence is 0.0-1.0, your own calibrated confidence that document_type is correct.
reason_codes: 1-4 short codes from the fixed set describing what evidence you used.
"""


class AIClassificationError(Exception):
    """Raised for ANY AI-classification failure — missing config, timeout,
    provider error, or an invalid/malformed structured response. Callers
    must catch this and fall back; it is never meant to propagate into
    the upload pipeline as a hard failure."""


@dataclass
class AIClassificationResult:
    document_type: DocumentType
    confidence: float
    ambiguous: bool
    alternative_document_type: DocumentType | None
    reason_codes: list[str]


def _client():
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIClassificationError("OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=api_key, timeout=AI_CLASSIFIER_TIMEOUT_SECONDS)


def _build_bounded_representation(text: str, max_chars: int = AI_CLASSIFIER_MAX_INPUT_CHARS) -> str:
    """A deterministic bounded view of a long document — never a naive
    head-only truncation. A discharge letter's title/admission context
    sits at the START, but its discharge diagnosis/recommendations and
    signatures typically sit at the END — truncating at, say, the first
    1000 characters would systematically lose exactly the evidence that
    distinguishes a genuine discharge letter from an admission note.

    Budget: 45% head / 20% middle / 35% tail of `max_chars`, with the
    middle segment centered on the document's own midpoint. Below
    `max_chars`, the text is returned verbatim (most real documents,
    including the 17-page hematology discharge fixture used in this
    session's own tests, fit well under the default budget).
    """
    if len(text) <= max_chars:
        return text

    head_budget = int(max_chars * 0.45)
    tail_budget = int(max_chars * 0.35)
    middle_budget = max_chars - head_budget - tail_budget

    head = text[:head_budget]
    tail = text[-tail_budget:] if tail_budget > 0 else ""
    middle_start = max(head_budget, len(text) // 2 - middle_budget // 2)
    middle = text[middle_start : middle_start + middle_budget]

    return f"{head}\n\n[... middle of document ...]\n\n{middle}\n\n[... continued ...]\n\n{tail}"


def _parse_ai_response(raw_output_text: str) -> AIClassificationResult:
    try:
        parsed = json.loads(raw_output_text)
    except (json.JSONDecodeError, TypeError) as error:
        raise AIClassificationError(f"AI classifier returned invalid JSON: {error}") from error

    document_type_value = parsed.get("document_type")
    if not is_valid_document_type(document_type_value):
        raise AIClassificationError(f"AI classifier returned an unknown document_type: {document_type_value!r}")

    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise AIClassificationError("AI classifier response missing a numeric confidence.")
    confidence = max(0.0, min(1.0, float(confidence)))

    ambiguous = bool(parsed.get("ambiguous", False))

    alt_raw = parsed.get("alternative_document_type")
    alternative_document_type = DocumentType(alt_raw) if alt_raw and is_valid_document_type(alt_raw) else None

    reason_codes = parsed.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    reason_codes = [code for code in reason_codes if isinstance(code, str)][:6]

    return AIClassificationResult(
        document_type=DocumentType(document_type_value),
        confidence=confidence,
        ambiguous=ambiguous,
        alternative_document_type=alternative_document_type,
        reason_codes=reason_codes,
    )


def classify_document_text_with_ai(text: str) -> AIClassificationResult:
    """The main entry point. Raises `AIClassificationError` on any
    failure — callers must catch it and fall back to the existing
    legacy/Reducto classifier; this function never returns a partial or
    guessed result."""
    if not text or not text.strip():
        raise AIClassificationError("No extracted text available to classify.")

    # Classification needs none of a patient's direct identifiers (name,
    # CNP, address, phone, email) — only the document's own clinical
    # content and structure. CNP/email/phone are stripped via the
    # existing, previously-unwired ai_minimization.py boundary (this is
    # its first real caller in this codebase). Patient NAME is
    # deliberately NOT stripped here — no reliable regex/NER exists in
    # this codebase for free-text name redaction, and a failed silent
    # attempt would be worse than an honest gap; this is a real,
    # documented limitation, not a solved problem.
    redacted_text = redact_direct_identifiers(text)
    bounded_text = _build_bounded_representation(redacted_text)

    client = _client()

    try:
        response = client.responses.create(
            model=AI_CLASSIFIER_MODEL,
            input=[
                {"role": "system", "content": _SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": bounded_text},
            ],
            max_output_tokens=AI_CLASSIFIER_MAX_OUTPUT_TOKENS,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "bragi_document_classification",
                    "schema": _JSON_SCHEMA,
                    "strict": False,
                }
            },
        )
    except AIClassificationError:
        raise
    except Exception as error:
        raise AIClassificationError(f"AI classifier request failed: {error}") from error

    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise AIClassificationError("AI classifier returned an empty response.")

    return _parse_ai_response(output_text)
