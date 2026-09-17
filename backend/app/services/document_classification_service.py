"""Final-classification decision service (P0 upload-reliability
session) — the ONE place that reconciles the AI semantic classifier
against the existing legacy/Reducto classification result, so no
three-way silent-overwrite race exists between them.

Policy (deliberately conservative, values centralized here):
- AI succeeds, confidence >= AI_CLASSIFIER_MIN_CONFIDENCE, ambiguous is
  False -> AI's type is final, status="classified",
  classification_source="ai".
- AI succeeds but confidence is low OR ambiguous is True ->
  status="needs_confirmation", document_type = AI's own best guess (so
  the confirmation UI can pre-fill it), classification_source=
  "ai_needs_confirmation". This is never silently resolved to `other` —
  `other` stays a genuine semantic outcome, not an ambiguity bucket.
- AI unavailable/misconfigured/errors for any reason -> fall back
  ENTIRELY to the existing (Reducto/legacy) classification result,
  completely unchanged from before this session — an AI outage or an
  environment with no OPENAI_API_KEY configured must never alter upload
  behavior.

Non-PHI disagreement metadata (ai_type/ai_confidence/fallback_type/
fallback_confidence/final_type/reason_codes) is returned on the result
for the caller to write to the EXISTING AuditLog mechanism once a
Document row exists — this module never persists anything itself and
never logs document text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.ai_document_classifier import AIClassificationError, classify_document_text_with_ai
from app.services.document_classifier import CLASSIFIED, NEEDS_CONFIRMATION
from app.services.document_taxonomy import DocumentType

AI_SOURCE = "ai"
AI_NEEDS_CONFIRMATION_SOURCE = "ai_needs_confirmation"


@dataclass
class FinalClassificationDecision:
    document_type: DocumentType
    status: str
    confidence: float | None
    classification_source: str
    # Non-PHI debug/provenance metadata only — never document text.
    ai_attempted: bool = False
    ai_document_type: str | None = None
    ai_confidence: float | None = None
    ai_ambiguous: bool | None = None
    ai_reason_codes: list[str] = field(default_factory=list)
    ai_error: str | None = None
    fallback_document_type: str | None = None
    fallback_confidence: float | None = None
    fallback_source: str | None = None

    def audit_details(self) -> str:
        """A short, non-PHI summary line for AuditLog.details — never
        includes document text or model reasoning, only the enum/number
        fields already safe to log."""
        parts = [f"final={self.document_type.value}({self.classification_source})"]
        if self.ai_attempted:
            if self.ai_error:
                parts.append(f"ai_error={self.ai_error}")
            else:
                parts.append(f"ai={self.ai_document_type}({self.ai_confidence}) ambiguous={self.ai_ambiguous}")
        if self.fallback_document_type:
            parts.append(f"fallback={self.fallback_document_type}({self.fallback_confidence})")
        return " ".join(parts)


def resolve_final_classification(
    *,
    classification_text: str,
    fallback_document_type: DocumentType,
    fallback_status: str,
    fallback_confidence: float | None,
    fallback_source: str,
    ai_min_confidence: float | None = None,
) -> FinalClassificationDecision:
    from app.services.ai_document_classifier import AI_CLASSIFIER_MIN_CONFIDENCE

    threshold = ai_min_confidence if ai_min_confidence is not None else AI_CLASSIFIER_MIN_CONFIDENCE

    fallback_decision = FinalClassificationDecision(
        document_type=fallback_document_type,
        status=fallback_status,
        confidence=fallback_confidence,
        classification_source=fallback_source,
        fallback_document_type=fallback_document_type.value,
        fallback_confidence=fallback_confidence,
        fallback_source=fallback_source,
    )

    if not classification_text or not classification_text.strip():
        return fallback_decision

    try:
        ai_result = classify_document_text_with_ai(classification_text)
    except AIClassificationError as error:
        fallback_decision.ai_attempted = True
        fallback_decision.ai_error = str(error)
        return fallback_decision

    confident_and_unambiguous = ai_result.confidence >= threshold and not ai_result.ambiguous

    if confident_and_unambiguous:
        status = CLASSIFIED
        source = AI_SOURCE
    else:
        status = NEEDS_CONFIRMATION
        source = AI_NEEDS_CONFIRMATION_SOURCE

    return FinalClassificationDecision(
        document_type=ai_result.document_type,
        status=status,
        confidence=ai_result.confidence,
        classification_source=source,
        ai_attempted=True,
        ai_document_type=ai_result.document_type.value,
        ai_confidence=ai_result.confidence,
        ai_ambiguous=ai_result.ambiguous,
        ai_reason_codes=ai_result.reason_codes,
        fallback_document_type=fallback_document_type.value,
        fallback_confidence=fallback_confidence,
        fallback_source=fallback_source,
    )
