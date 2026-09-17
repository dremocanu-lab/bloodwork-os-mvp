"""Focused tests for medication candidate extraction — Clinical Document
Intelligence V3, Phase 7. Pure (no DB)."""

from app.services.clinical_document.events import ClinicalEvent
from app.services.clinical_document.medication_extraction import (
    MEDICATION_BEARING_CANONICAL_KEYS,
    extract_medication_candidates_from_event,
    extract_medication_candidates_from_segment,
)
from app.services.clinical_document.segments import SourceSegment


def _segment(text: str, *, canonical_key_hint: str = "discharge_medications") -> SourceSegment:
    return SourceSegment(
        segment_id="seg-000-medicatie",
        index=0,
        raw_heading="MEDICAȚIE LA EXTERNARE",
        raw_text=text,
    )


def _extract(text: str, canonical_key: str = "discharge_medications"):
    return extract_medication_candidates_from_segment(
        _segment(text), canonical_key=canonical_key, source_section_id="section-discharge_medications"
    )


# --- Context classification -------------------------------------------------


def test_started_context_detected():
    c = _extract("BESREMI 250mcg subcutanat, se initiaza tratamentul.")
    assert len(c) == 1
    assert c[0].status_context == "started"


def test_continued_context_detected():
    c = _extract("Metoprolol 50mg 1-0-1, se continua tratamentul cu doza anterioara.")
    assert c[0].status_context == "continued"


def test_stopped_context_detected():
    c = _extract("Metformin 850mg, oprit din cauza efectelor adverse.")
    assert c[0].status_context == "stopped"


def test_paused_context_detected():
    c = _extract("BESREMI 250mcg, suspendat temporar.")
    assert c[0].status_context == "paused"


def test_completed_context_detected():
    c = _extract("Amoxicilina 500mg, tratament finalizat.")
    assert c[0].status_context == "completed"


def test_historical_context_detected():
    c = _extract("Ibuprofen 400mg, tratament anterior pentru un episod similar.")
    assert c[0].status_context == "historical"


def test_prescribed_from_prescriptions_section_fallback():
    c = _extract("Amoxicilina 500mg 1-1-1", canonical_key="prescriptions")
    assert c[0].status_context == "prescribed"


def test_uncertain_when_no_keyword_and_not_prescriptions_section():
    c = _extract("Metformin 500mg 1-0-1", canonical_key="discharge_medications")
    assert c[0].status_context == "uncertain"


# --- Negative-context exclusion (must NOT become a candidate at all) --------


def test_allergy_statement_excluded():
    assert _extract("Pacientul este alergic la Penicilina.") == []


def test_refused_medication_excluded():
    assert _extract("Pacientul a refuzat Warfarina.") == []


def test_hypothetical_medication_excluded():
    assert _extract("Se va lua in considerare Metformin in viitor.") == []


def test_family_member_medication_excluded():
    assert _extract("Sotia ia Aspirina zilnic.") == []


def test_narrative_number_not_mistaken_for_medication():
    assert _extract("Pacientul a fost internat de 3 ori in ultimul an.") == []


# --- Dose / route / frequency ------------------------------------------------


def test_dose_route_frequency_parsed():
    c = _extract("Metoprolol 50mg 1-0-1 per os")
    assert c[0].raw_medication_name == "Metoprolol"
    assert c[0].dose_text == "50mg"
    assert c[0].frequency == "1-0-1"
    assert c[0].route == "oral"


def test_english_frequency_and_route_parsed():
    c = _extract("Aspirin 100mg once a day oral")
    assert c[0].dose_text == "100mg"
    assert c[0].frequency == "once a day"
    assert c[0].route == "oral"


def test_subcutaneous_route_parsed():
    c = _extract("BESREMI 250mcg subcutanat saptamanal, se initiaza tratamentul.")
    assert c[0].route == "subcutaneous"


# --- PRN / duration / scheme --------------------------------------------------


def test_prn_detected():
    c = _extract("Ibuprofen 400mg la nevoie pentru durere.")
    assert c[0].prn is True


def test_duration_extracted():
    c = _extract("Amoxicilina 500mg 1-1-1 timp de 7 zile.")
    assert c[0].raw_duration is not None
    assert c[0].parsed_duration.total_days == 7


def test_n_days_per_month_excludes_plain_duration_and_flags_intermittent():
    c = _extract("BESREMI 250mcg subcutanat, 5 zile pe luna, se initiaza tratamentul.")
    assert c[0].scheme_or_intermittent is True
    assert c[0].parsed_duration is None


def test_scheme_marker_excludes_duration_derivation_input():
    c = _extract("Metotrexat 10mg, conform schemei oncologice.")
    assert c[0].scheme_or_intermittent is True


def test_indefinite_marker_detected():
    c = _extract("Levotiroxina 50mcg, continua tratamentul pana la control.")
    assert c[0].indefinite is True


def test_taper_without_duration_flagged():
    c = _extract("Prednison 20mg, scadere progresiva a dozei.")
    assert c[0].taper_without_clear_duration is True


# --- Dates -------------------------------------------------------------------


def test_explicit_start_date_extracted():
    c = _extract("BESREMI 250mcg, se initiaza tratamentul din data de 10.03.2026.")
    assert c[0].explicit_start_date == "10.03.2026"


def test_explicit_end_date_extracted():
    c = _extract("Amoxicilina 500mg, tratament pana la 20.03.2026.")
    assert c[0].explicit_end_date == "20.03.2026"


def test_din_data_de_after_stopped_context_is_read_as_a_stop_date_not_a_start_date():
    """'oprit din data de <DATE>' describes WHEN the medication stopped
    — the same 'din data de' phrasing that means 'starting from' for a
    started/continued context means something different here."""
    c = _extract("Metformin 850mg, oprit din data de 05.03.2026 din cauza efectelor adverse.")
    assert c[0].status_context == "stopped"
    assert c[0].explicit_start_date is None
    assert c[0].explicit_end_date == "05.03.2026"


def test_starts_at_discharge_detected():
    c = _extract("Metformin 500mg 1-0-1, incepand de azi.")
    assert c[0].starts_at_discharge_or_encounter is True


def test_no_date_label_means_no_fabricated_start_date():
    c = _extract("Metformin 500mg 1-0-1, revizuit ultima data pe 10.03.2026.")
    assert c[0].explicit_start_date is None


def test_prescription_date_extracted():
    c = _extract("Amoxicilina 500mg, data eliberarii retetei: 08.03.2026.", canonical_key="prescriptions")
    assert c[0].prescription_date == "08.03.2026"


# --- Provenance ----------------------------------------------------------------


def test_source_segment_provenance_retained():
    c = _extract("Metoprolol 50mg 1-0-1")
    assert c[0].source_segment_id == "seg-000-medicatie"
    assert c[0].source_heading == "MEDICAȚIE LA EXTERNARE"
    assert c[0].source_evidence_text == "Metoprolol 50mg 1-0-1"


def test_multiple_lines_produce_multiple_candidates_in_order():
    text = "Metoprolol 50mg 1-0-1\nBESREMI 250mcg subcutanat"
    candidates = _extract(text)
    assert [c.raw_medication_name for c in candidates] == ["Metoprolol", "BESREMI"]


# --- Section scope -------------------------------------------------------------


def test_medication_bearing_canonical_keys_is_the_expected_set():
    assert MEDICATION_BEARING_CANONICAL_KEYS == {
        "treatment",
        "medications",
        "discharge_medications",
        "recommendations",
        "prescriptions",
    }


# --- Event-based extraction (treatment_change) ---------------------------------


def test_treatment_change_event_produces_candidate():
    event = ClinicalEvent(
        source_event_id="seg-005-epicriza-event-0",
        raw_date_text="14.03.2026",
        normalized_date="2026-03-14",
        date_confidence=0.95,
        event_type="treatment_change",
        raw_text="S-a oprit BESREMI in data de 14.03.2026 din cauza reactiei adverse.",
    )
    candidates = extract_medication_candidates_from_event(event)
    assert len(candidates) == 1
    assert candidates[0].raw_medication_name == "BESREMI"
    assert candidates[0].status_context == "stopped"


def test_treatment_change_event_falls_back_to_event_date_for_started_context():
    event = ClinicalEvent(
        source_event_id="seg-005-epicriza-event-1",
        raw_date_text="12.03.2026",
        normalized_date="2026-03-12",
        date_confidence=0.95,
        event_type="treatment_change",
        raw_text="S-a initiat tratament cu METFORMIN.",
    )
    candidates = extract_medication_candidates_from_event(event)
    assert len(candidates) == 1
    assert candidates[0].status_context == "started"
    assert candidates[0].explicit_start_date == "12.03.2026"


def test_non_treatment_change_event_produces_no_candidates():
    event = ClinicalEvent(
        source_event_id="e1",
        raw_date_text="10.01.2026",
        normalized_date="2026-01-10",
        date_confidence=0.95,
        event_type="admission",
        raw_text="Internat la 10.01.2026 pentru dureri abdominale.",
    )
    assert extract_medication_candidates_from_event(event) == []
