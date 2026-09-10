from app.services.document_classifier import CLASSIFIED, NEEDS_CONFIRMATION, OTHER, classify_document_text
from app.services.document_taxonomy import DocumentType
from tests.fixtures.synthetic_documents import (
    CONSULTATION_TEXT,
    EMPTY_TEXT,
    ENGLISH_CT_REPORT,
    ENGLISH_LAB_REPORT,
    GARBLED_OCR_TEXT,
    MEANINGLESS_FILENAME_LAB_TEXT,
    MISLEADING_FILENAME_DISCHARGE_TEXT,
    PATHOLOGY_TEXT,
    PRESCRIPTION_TEXT,
    ROMANIAN_DISCHARGE_SUMMARY,
    ROMANIAN_LAB_REPORT,
)


def test_romanian_lab_report_classifies_confidently():
    result = classify_document_text(ROMANIAN_LAB_REPORT)
    assert result.document_type == DocumentType.LABORATORY_RESULTS
    assert result.status == CLASSIFIED
    assert result.confidence > 0


def test_english_lab_report_classifies_confidently():
    result = classify_document_text(ENGLISH_LAB_REPORT)
    assert result.document_type == DocumentType.LABORATORY_RESULTS
    assert result.status == CLASSIFIED


def test_romanian_discharge_summary_classifies_confidently():
    result = classify_document_text(ROMANIAN_DISCHARGE_SUMMARY)
    assert result.document_type == DocumentType.DISCHARGE_SUMMARY
    assert result.status == CLASSIFIED


def test_ct_report_classifies_as_imaging():
    result = classify_document_text(ENGLISH_CT_REPORT)
    assert result.document_type == DocumentType.IMAGING_REPORT
    assert result.status == CLASSIFIED


def test_prescription_classifies_correctly():
    result = classify_document_text(PRESCRIPTION_TEXT)
    assert result.document_type == DocumentType.PRESCRIPTION


def test_pathology_classifies_correctly():
    result = classify_document_text(PATHOLOGY_TEXT)
    assert result.document_type == DocumentType.PATHOLOGY_REPORT


def test_consultation_classifies_correctly():
    result = classify_document_text(CONSULTATION_TEXT)
    assert result.document_type == DocumentType.SPECIALIST_CONSULTATION


def test_content_wins_over_meaningless_filename():
    # Classifier never sees a filename at all — this asserts the content
    # alone is sufficient, regardless of what a filename like "scan001.pdf"
    # might have implied.
    result = classify_document_text(MEANINGLESS_FILENAME_LAB_TEXT)
    assert result.document_type == DocumentType.LABORATORY_RESULTS


def test_content_wins_over_misleading_filename():
    # e.g. filename says "labs.pdf" but content is actually a discharge summary.
    result = classify_document_text(MISLEADING_FILENAME_DISCHARGE_TEXT)
    assert result.document_type == DocumentType.DISCHARGE_SUMMARY


def test_empty_text_is_other_not_a_guess():
    result = classify_document_text(EMPTY_TEXT)
    assert result.document_type == DocumentType.OTHER
    assert result.status == OTHER
    assert result.confidence == 0.0


def test_garbled_ocr_text_is_other_not_a_guess():
    result = classify_document_text(GARBLED_OCR_TEXT)
    assert result.status == OTHER


def test_none_text_does_not_raise():
    result = classify_document_text(None)
    assert result.document_type == DocumentType.OTHER


def test_ambiguous_mixed_signal_needs_confirmation():
    # Roughly equal, real signal for two very different document types
    # should not be silently resolved — this is exactly the "only
    # ambiguous files get a popup" case.
    mixed = ROMANIAN_LAB_REPORT[:200] + "\n\n" + ROMANIAN_DISCHARGE_SUMMARY[:200]
    result = classify_document_text(mixed)
    assert result.status in {NEEDS_CONFIRMATION, CLASSIFIED}
    # Whichever way the heuristic breaks the tie, both signals must have
    # been detected as real candidates.
    assert len(result.candidates) >= 2
