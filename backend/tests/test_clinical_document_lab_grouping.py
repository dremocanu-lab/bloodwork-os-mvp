"""Focused tests for coherent lab-report grouping — Clinical Document
Intelligence V3, Phase 6. Pure (no DB)."""

from app.services.clinical_document.lab_extraction import LabCandidate
from app.services.clinical_document.lab_grouping import group_lab_candidates


def _candidate(**overrides) -> LabCandidate:
    defaults = dict(
        source_segment_id="seg-000-laborator",
        raw_test_name="WBC",
        raw_value="5.5",
        source_evidence_text="WBC 5.5",
    )
    defaults.update(overrides)
    return LabCandidate(**defaults)


def test_same_request_and_date_group_together():
    candidates = [
        _candidate(request_code="LAB-1", observation_date="10.01.2026", raw_test_name="WBC"),
        _candidate(request_code="LAB-1", observation_date="10.01.2026", raw_test_name="RBC"),
    ]
    groups = group_lab_candidates(candidates)
    assert len(groups) == 1
    assert len(groups[0].candidates) == 2


def test_separate_request_and_date_groups_remain_separate():
    candidates = [
        _candidate(request_code="LAB-1", observation_date="10.01.2026"),
        _candidate(request_code="LAB-2", observation_date="15.01.2026"),
    ]
    groups = group_lab_candidates(candidates)
    assert len(groups) == 2


def test_no_distinguishing_signal_falls_back_to_same_segment_not_a_guess():
    candidates = [
        _candidate(source_segment_id="seg-000-laborator", raw_test_name="WBC"),
        _candidate(source_segment_id="seg-000-laborator", raw_test_name="RBC"),
    ]
    groups = group_lab_candidates(candidates)
    assert len(groups) == 1
    assert groups[0].request_code is None
    assert groups[0].observation_date is None


def test_no_distinguishing_signal_and_different_segments_stay_separate():
    candidates = [
        _candidate(source_segment_id="seg-000-laborator"),
        _candidate(source_segment_id="seg-001-laborator"),
    ]
    groups = group_lab_candidates(candidates)
    assert len(groups) == 2


def test_group_key_is_deterministic_across_calls():
    candidates = [_candidate(request_code="LAB-1", observation_date="10.01.2026")]
    first = group_lab_candidates(candidates)[0].group_key
    second = group_lab_candidates(candidates)[0].group_key
    assert first == second


def test_source_segment_ids_collected_per_group():
    candidates = [
        _candidate(source_segment_id="seg-000-laborator", request_code="LAB-1", observation_date="10.01.2026"),
        _candidate(source_segment_id="seg-001-laborator", request_code="LAB-1", observation_date="10.01.2026"),
    ]
    groups = group_lab_candidates(candidates)
    assert len(groups) == 1
    assert set(groups[0].source_segment_ids) == {"seg-000-laborator", "seg-001-laborator"}


def test_no_panel_fabrication_when_not_present_in_source():
    candidates = [_candidate(request_code="LAB-1", observation_date="10.01.2026")]
    groups = group_lab_candidates(candidates)
    assert groups[0].source_panel is None
