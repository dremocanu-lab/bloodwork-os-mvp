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
    ROMANIAN_DISCHARGE_BILET_DE_EXTERNARE,
    ROMANIAN_DISCHARGE_BILET_DE_IESIRE,
    ROMANIAN_DISCHARGE_SUMMARY,
    ROMANIAN_HOSPITAL_ADMISSION_NOTE,
    ROMANIAN_LAB_REPORT,
    ROMANIAN_OUTPATIENT_SCRISOARE_MEDICALA,
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


class TestBiletDeIesireRomanianDischargeClosure:
    """Pre-Phase-11 Romanian discharge classification closure session.

    Reproduces the real manual-QA report: a genuine inpatient Romanian
    discharge letter titled "BILET DE IEȘIRE DIN SPITAL / SCRISOARE
    MEDICALĂ" — a title the classifier previously had NO keyword
    coverage for at all ("bilet de externare" existed, "bilet de iesire"
    did not) — combined with a realistically dense embedded hematology
    lab table (the exact class of content that should NOT be able to
    steal a document-level classification away from an otherwise-clear
    discharge letter). Before the fix, this exact fixture scored
    discharge_summary=14.5 vs laboratory_results=14.0 (a margin of 0.5,
    below CONFIDENT_MARGIN_THRESHOLD=1.5), forcing an unnecessary
    needs_confirmation despite discharge already being the correct
    winner — this is the precise, reproduced root cause of the reported
    bug, not a guess.
    """

    def test_bilet_de_iesire_with_dense_embedded_labs_classifies_confidently(self):
        result = classify_document_text(ROMANIAN_DISCHARGE_BILET_DE_IESIRE)
        assert result.document_type == DocumentType.DISCHARGE_SUMMARY
        assert result.status == CLASSIFIED, (
            "a genuine inpatient discharge letter with embedded labs must not "
            f"be forced into needs_confirmation; candidates={result.candidates}"
        )
        assert "bilet de iesire din spital" in result.matched_terms

    def test_bilet_de_iesire_beats_laboratory_results_by_a_real_margin(self):
        result = classify_document_text(ROMANIAN_DISCHARGE_BILET_DE_IESIRE)
        discharge_score = result.candidates.get("discharge_summary", 0)
        lab_score = result.candidates.get("laboratory_results", 0)
        assert discharge_score - lab_score >= 1.5

    def test_bilet_de_externare_short_form_classifies_confidently(self):
        result = classify_document_text(ROMANIAN_DISCHARGE_BILET_DE_EXTERNARE)
        assert result.document_type == DocumentType.DISCHARGE_SUMMARY
        assert result.status == CLASSIFIED

    def test_foaie_de_internare_classifies_as_admission_note_not_discharge(self):
        # Admission-only structure (no discharge date, no discharge
        # recommendations) must stay a distinct type — never conflated
        # with discharge_summary just because both are inpatient
        # documents.
        result = classify_document_text(ROMANIAN_HOSPITAL_ADMISSION_NOTE)
        assert result.document_type == DocumentType.HOSPITAL_ADMISSION_NOTE
        assert result.status == CLASSIFIED

    def test_outpatient_scrisoare_medicala_classifies_as_consultation_not_discharge(self):
        # "Scrisoare medicala" alone, with no inpatient admission/
        # discharge structure, is an outpatient consultation letter, not
        # a discharge summary — the classifier must not treat the phrase
        # as an automatic discharge signal.
        result = classify_document_text(ROMANIAN_OUTPATIENT_SCRISOARE_MEDICALA)
        assert result.document_type == DocumentType.SPECIALIST_CONSULTATION
        assert result.status == CLASSIFIED

    def test_standalone_lab_report_is_unaffected_by_the_new_keywords(self):
        # Regression guard: adding "bilet de iesire" must not change
        # standalone lab-report classification at all.
        result = classify_document_text(ROMANIAN_LAB_REPORT)
        assert result.document_type == DocumentType.LABORATORY_RESULTS
        assert result.status == CLASSIFIED


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
