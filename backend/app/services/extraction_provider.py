"""Document extraction provider abstraction.

Bragi's document understanding (classification today; split/parse/extract
in later phases) is routed through a small provider interface so a real
Reducto integration can be dropped in later without ripping out the
rule-based fallback that ships in Phase 1.

    DocumentExtractionProvider
        |-- LegacyExtractionProvider   (keyword-rule classifier; always available)
        `-- ReductoExtractionProvider  (Reducto Classify/Split/Parse/Extract; disabled
                                        until REDUCTO_ENABLED=true and REDUCTO_API_KEY
                                        is set)

Selection is controlled by two env vars (see backend/.env.example):

    DOCUMENT_EXTRACTION_PROVIDER   "legacy" (default) | "reducto"
    DOCUMENT_EXTRACTION_FALLBACK   provider to use if the requested one is
                                    unavailable (default "legacy")
    REDUCTO_ENABLED                "true" to allow the Reducto provider to
                                    actually be used (default false)
    REDUCTO_API_KEY                backend-only credential; never sent to
                                    the frontend

`get_extraction_provider()` never raises for missing Reducto config — it
resolves to the fallback and reports *why*, so callers can persist that a
fallback occurred (per the "fallback must not silently hide meaningful
extraction differences" requirement) instead of silently behaving as if
Reducto had run.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.document_classifier import ClassificationResult, classify_document_text
from app.services.reducto_client import ReductoError

LEGACY = "legacy"
REDUCTO = "reducto"


@dataclass
class ProcessingMetadata:
    provider: str
    parser_version: str
    processing_time_ms: int
    confidence: float | None = None
    # Reducto-only: the uploaded file's Reducto file_id, so a subsequent
    # extract()/split() call for the same document can reuse it instead of
    # uploading the same bytes to Reducto a second time.
    reducto_file_id: str | None = None


class ReductoNotConfiguredError(RuntimeError):
    """Raised if code attempts to call the Reducto provider while it is disabled."""


class DocumentExtractionProvider(ABC):
    name: str

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    def classify(
        self, text: str, file_path: str | None = None, filename: str | None = None
    ) -> tuple[ClassificationResult, ProcessingMetadata]: ...


class LegacyExtractionProvider(DocumentExtractionProvider):
    """Rule-based classifier. Always available — no external dependency."""

    name = "legacy_rules"
    PARSER_VERSION = "legacy_rules@1"

    def is_enabled(self) -> bool:
        return True

    def classify(
        self, text: str, file_path: str | None = None, filename: str | None = None
    ) -> tuple[ClassificationResult, ProcessingMetadata]:
        started = time.monotonic()
        result = classify_document_text(text)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        metadata = ProcessingMetadata(
            provider=self.name,
            parser_version=self.PARSER_VERSION,
            processing_time_ms=elapsed_ms,
            confidence=result.confidence,
        )
        return result, metadata


class ReductoExtractionProvider(DocumentExtractionProvider):
    """Real Reducto-backed classification, split, and extraction.

    Implemented and verified against the live Reducto API
    (platform.reducto.ai) with synthetic Romanian medical documents — see
    `reducto_extraction.py`'s module docstring for the test transcript
    summary and BRAGI_REDUCTO_PLAN.md §3 for the full account. Disabled
    unless both `REDUCTO_ENABLED=true` and `REDUCTO_API_KEY` are set;
    `get_extraction_provider()` falls back to legacy otherwise, and every
    Reducto call here can raise `ReductoError` — callers (process_upload_job)
    must catch it and fall back rather than ever marking a document ready
    on a failed/partial Reducto result.
    """

    name = "reducto"

    def __init__(self) -> None:
        self.api_key = os.getenv("REDUCTO_API_KEY", "").strip()
        self.explicitly_enabled = os.getenv("REDUCTO_ENABLED", "false").strip().lower() == "true"

    def is_enabled(self) -> bool:
        return self.explicitly_enabled and bool(self.api_key)

    def classify(
        self, text: str, file_path: str | None = None, filename: str | None = None
    ) -> tuple[ClassificationResult, ProcessingMetadata]:
        if not self.is_enabled():
            raise ReductoNotConfiguredError(
                "Reducto provider is disabled (REDUCTO_ENABLED/REDUCTO_API_KEY not set)."
            )
        if not file_path:
            # Reducto Classify operates on the uploaded file directly, not
            # OCR'd text (verified live — see reducto_extraction.py) —
            # unlike the legacy keyword classifier there is no text-only
            # path.
            raise ReductoNotConfiguredError("ReductoExtractionProvider.classify() requires file_path.")

        from app.services import reducto_extraction as _reducto

        started = time.monotonic()
        try:
            classification = _reducto.classify_file(file_path, filename=filename)
        except ReductoError:
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)

        result = ClassificationResult(
            document_type=classification.document_type,
            status=classification.status,
            confidence=classification.confidence,
            matched_terms=[],
            candidates=classification.category_scores,
        )
        metadata = ProcessingMetadata(
            provider=self.name,
            parser_version=_reducto.PARSER_VERSION,
            processing_time_ms=elapsed_ms,
            confidence=classification.confidence,
            reducto_file_id=classification.file_id,
        )
        return result, metadata


def get_extraction_provider() -> tuple[DocumentExtractionProvider, bool, str | None]:
    """Resolve the configured provider.

    Returns (provider, used_fallback, fallback_reason). `used_fallback` is
    True whenever the requested DOCUMENT_EXTRACTION_PROVIDER could not be
    used and DOCUMENT_EXTRACTION_FALLBACK was substituted instead —
    callers should persist this rather than silently reporting the
    fallback provider's result as if it were the requested one.
    """
    requested = os.getenv("DOCUMENT_EXTRACTION_PROVIDER", LEGACY).strip().lower()
    fallback_name = os.getenv("DOCUMENT_EXTRACTION_FALLBACK", LEGACY).strip().lower()

    providers = {
        LEGACY: LegacyExtractionProvider,
        REDUCTO: ReductoExtractionProvider,
    }

    provider_cls = providers.get(requested, LegacyExtractionProvider)
    provider = provider_cls()

    if provider.is_enabled():
        return provider, False, None

    fallback_cls = providers.get(fallback_name, LegacyExtractionProvider)
    fallback_provider = fallback_cls()

    if not fallback_provider.is_enabled():
        # Legacy is always enabled, so this only happens if someone points
        # the fallback at "reducto" too while it's disabled. Hard-fall to
        # legacy rather than raising, since classification must never block
        # a whole batch.
        fallback_provider = LegacyExtractionProvider()

    reason = (
        f"Requested provider '{requested}' is not enabled; using fallback '{fallback_provider.name}'."
        if requested != fallback_provider.name
        else None
    )

    return fallback_provider, requested != fallback_provider.name, reason
