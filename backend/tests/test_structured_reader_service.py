from pathlib import Path

from app.services.structured_reader_service import (
    SECTION_KEYS,
    _build_prompt,
    _extract_json_from_text,
    extract_structured_sections,
)


def test_every_section_type_has_keys():
    for doc_type, keys in SECTION_KEYS.items():
        assert keys, f"{doc_type} has no section keys"


def test_build_prompt_includes_every_section_key():
    for doc_type, keys in SECTION_KEYS.items():
        prompt = _build_prompt(doc_type)
        for key in keys:
            assert key in prompt


def test_extract_json_from_text_handles_markdown_fence():
    raw = '```json\n{"language": "en", "sections": {"findings": "ok"}}\n```'
    parsed = _extract_json_from_text(raw)
    assert parsed["sections"]["findings"] == "ok"


def test_extract_json_from_text_returns_empty_on_garbage():
    assert _extract_json_from_text("not json at all") == {}


def test_extract_structured_sections_without_api_key_is_graceful(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    fake_file = tmp_path / "fake.pdf"
    fake_file.write_bytes(b"%PDF-1.4 fake content")

    result = extract_structured_sections(
        document_type="imaging_report",
        file_path=fake_file,
        filename="fake.pdf",
        content_type="application/pdf",
    )

    assert result["sections"] == {}
    assert result["warnings"]


def test_extract_structured_sections_unknown_type_is_graceful(tmp_path):
    fake_file = tmp_path / "fake.pdf"
    fake_file.write_bytes(b"%PDF-1.4 fake content")

    result = extract_structured_sections(
        document_type="not_a_real_type",
        file_path=fake_file,
        filename="fake.pdf",
        content_type="application/pdf",
    )

    assert result["sections"] == {}
