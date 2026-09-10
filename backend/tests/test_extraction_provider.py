import pytest

from app.services.extraction_provider import (
    LegacyExtractionProvider,
    ReductoExtractionProvider,
    ReductoNotConfiguredError,
    get_extraction_provider,
)
from tests.fixtures.synthetic_documents import ROMANIAN_LAB_REPORT


def test_legacy_provider_is_always_enabled():
    provider = LegacyExtractionProvider()
    assert provider.is_enabled() is True


def test_legacy_provider_classifies_and_returns_metadata():
    provider = LegacyExtractionProvider()
    result, metadata = provider.classify(ROMANIAN_LAB_REPORT)
    assert result.document_type.value == "laboratory_results"
    assert metadata.provider == "legacy_rules"
    assert metadata.processing_time_ms >= 0


def test_reducto_provider_disabled_by_default(monkeypatch):
    monkeypatch.delenv("REDUCTO_ENABLED", raising=False)
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)

    provider = ReductoExtractionProvider()
    assert provider.is_enabled() is False

    with pytest.raises(ReductoNotConfiguredError):
        provider.classify(ROMANIAN_LAB_REPORT)


def test_reducto_provider_requires_both_flag_and_key(monkeypatch):
    monkeypatch.setenv("REDUCTO_ENABLED", "true")
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)
    assert ReductoExtractionProvider().is_enabled() is False

    monkeypatch.delenv("REDUCTO_ENABLED", raising=False)
    monkeypatch.setenv("REDUCTO_API_KEY", "fake-key-for-test")
    assert ReductoExtractionProvider().is_enabled() is False


def test_factory_defaults_to_legacy_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DOCUMENT_EXTRACTION_PROVIDER", raising=False)
    monkeypatch.delenv("REDUCTO_ENABLED", raising=False)
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)

    provider, used_fallback, reason = get_extraction_provider()
    assert provider.name == "legacy_rules"
    assert used_fallback is False
    assert reason is None


def test_factory_falls_back_when_reducto_requested_but_disabled(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_PROVIDER", "reducto")
    monkeypatch.delenv("REDUCTO_ENABLED", raising=False)
    monkeypatch.delenv("REDUCTO_API_KEY", raising=False)

    provider, used_fallback, reason = get_extraction_provider()
    # Must never silently pretend Reducto ran.
    assert provider.name == "legacy_rules"
    assert used_fallback is True
    assert reason is not None
    assert "reducto" in reason.lower()


def test_factory_uses_reducto_when_fully_configured(monkeypatch):
    monkeypatch.setenv("DOCUMENT_EXTRACTION_PROVIDER", "reducto")
    monkeypatch.setenv("REDUCTO_ENABLED", "true")
    monkeypatch.setenv("REDUCTO_API_KEY", "fake-key-for-test")

    provider, used_fallback, reason = get_extraction_provider()
    assert provider.name == "reducto"
    assert used_fallback is False
    assert reason is None
