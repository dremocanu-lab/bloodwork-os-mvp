from app.services.document_taxonomy import (
    LEGACY_SECTIONS,
    DocumentType,
    document_type_choices,
    is_valid_document_type,
    legacy_section_for,
)


def test_every_document_type_maps_to_a_known_legacy_section():
    for doc_type in DocumentType:
        assert legacy_section_for(doc_type) in LEGACY_SECTIONS


def test_document_type_choices_covers_every_enum_member():
    choices = document_type_choices()
    values = {choice["value"] for choice in choices}
    assert values == {doc_type.value for doc_type in DocumentType}
    for choice in choices:
        assert choice["label_en"]
        assert choice["label_ro"]


def test_is_valid_document_type():
    assert is_valid_document_type("laboratory_results") is True
    assert is_valid_document_type("not_a_real_type") is False
    assert is_valid_document_type(None) is False
    assert is_valid_document_type("") is False
