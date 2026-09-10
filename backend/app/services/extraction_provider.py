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

LEGACY = "legacy"
REDUCTO = "reducto"


@dataclass
class ProcessingMetadata:
    provider: str
    parser_version: str
    processing_time_ms: int
    confidence: float | None = None


class ReductoNotConfiguredError(RuntimeError):
    """Raised if code attempts to call the Reducto provider while it is disabled."""


class DocumentExtractionProvider(ABC):
    name: str

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    def classify(self, text: str) -> tuple[ClassificationResult, ProcessingMetadata]: ...


class LegacyExtractionProvider(DocumentExtractionProvider):
    """Rule-based classifier. Always available — no external dependency."""

    name = "legacy_rules"
    PARSER_VERSION = "legacy_rules@1"

    def is_enabled(self) -> bool:
        return True

    def classify(self, text: str) -> tuple[ClassificationResult, ProcessingMetadata]:
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
    """Reducto-backed classification.

    NOT YET IMPLEMENTED against the live Reducto API — no Reducto MCP
    connector was available during this phase, so no HTTP integration
    has been written or tested against Reducto's actual Classify
    response shape. Wire this up once REDUCTO_API_KEY is available and
    current Reducto docs have been checked for the Classify/Split/Parse
    request/response contract; until then this provider stays disabled
    and `get_extraction_provider()` always falls back to legacy.
    """

    name = "reducto"

    def __init__(self) -> None:
        self.api_key = os.getenv("REDUCTO_API_KEY", "").strip()
        self.explicitly_enabled = os.getenv("REDUCTO_ENABLED", "false").strip().lower() == "true"

    def is_enabled(self) -> bool:
        return self.explicitly_enabled and bool(self.api_key)

    def classify(self, text: str) -> tuple[ClassificationResult, ProcessingMetadata]:
        if not self.is_enabled():
            raise ReductoNotConfiguredError(
                "Reducto provider is disabled (REDUCTO_ENABLED/REDUCTO_API_KEY not set)."
            )
        raise NotImplementedError(
            "Reducto Classify integration has not been implemented yet. "
            "See BRAGI_REDUCTO_PLAN.md for the Phase 1 follow-up."
        )


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
