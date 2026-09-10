from app.services.patient_identity import (
    INSUFFICIENT_IDENTITY,
    MATCHED,
    MISMATCH,
    NEEDS_CONFIRMATION,
    check_patient_identity,
)


def _check(**overrides):
    base = {
        "patient_full_name": "Popescu Ion",
        "patient_dob": "1980-01-01",
        "patient_cnp": "1800101123456",
        "patient_identifier": None,
        "extracted_full_name": None,
        "extracted_dob": None,
        "extracted_cnp": None,
        "extracted_patient_identifier": None,
    }
    base.update(overrides)
    return check_patient_identity(**base)


def test_nothing_extracted_is_insufficient():
    result = _check()
    assert result.status == INSUFFICIENT_IDENTITY


def test_matching_name_is_matched():
    result = _check(extracted_full_name="Ion Popescu")
    assert result.status == MATCHED


def test_matching_cnp_is_matched_even_if_name_missing():
    result = _check(extracted_cnp="1800101123456")
    assert result.status == MATCHED


def test_different_cnp_is_mismatch_regardless_of_name():
    result = _check(extracted_full_name="Ion Popescu", extracted_cnp="2900101999999")
    assert result.status == MISMATCH


def test_clearly_different_name_with_no_confirming_id_is_mismatch():
    result = _check(extracted_full_name="Maria Ionescu")
    assert result.status == MISMATCH


def test_different_name_but_matching_dob_needs_confirmation():
    result = _check(extracted_full_name="Maria Ionescu", extracted_dob="1980-01-01")
    assert result.status == NEEDS_CONFIRMATION


def test_partial_name_overlap_needs_confirmation():
    # Shares one token ("Popescu") but not a strong match.
    result = _check(extracted_full_name="Popescu Vasile")
    assert result.status == NEEDS_CONFIRMATION


def test_wrong_dob_with_no_name_needs_confirmation():
    result = _check(extracted_dob="1975-05-05")
    assert result.status == NEEDS_CONFIRMATION


def test_matching_identifier_confirms_even_without_name():
    result = _check(patient_identifier="MRN-1", extracted_patient_identifier="MRN-1")
    assert result.status == MATCHED


def test_different_identifier_is_mismatch():
    result = _check(patient_identifier="MRN-1", extracted_patient_identifier="MRN-2")
    assert result.status == MISMATCH
