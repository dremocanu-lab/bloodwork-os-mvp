"""Focused tests for embedded lab-candidate extraction — Clinical
Document Intelligence V3, Phase 6. Pure (no DB) — this module reads a
SourceSegment's already-extracted text/table and produces typed
LabCandidates only; canonicalization/persistence is tested separately in
test_clinical_document_lab_persistence.py (real DB)."""

from app.services.clinical_document.lab_extraction import (
    LabCandidate,
    extract_lab_candidates_from_segment,
)
from app.services.clinical_document.segments import SegmentTableData, SourceSegment


def _segment(text: str, *, table_data: SegmentTableData | None = None) -> SourceSegment:
    return SourceSegment(
        segment_id="seg-000-laborator",
        index=0,
        raw_heading="EXAMENE DE LABORATOR",
        raw_text=text,
        table_data=table_data,
    )


# The synthetic hematology fixture (Phase 6 requirement 16) — reused
# across extraction/grouping/persistence tests. Proves: tables/lines
# survive, analyte aliases normalize, dates survive, abnormal source
# sections survive, a genuine conflict (MCH) survives, provenance
# survives.
HEMATOLOGY_FIXTURE_TEXT = """\
Nr. cerere: LAB-2026-0091
Data recoltarii: 10.01.2026

Valori normale:
AST 33 U/L (10-40)
Bilirubina totala 0.5 mg/dL (0.2-1.2)
Glucoza 78 mg/dL (70-110)
Creatinina 0.70 mg/dL (0.6-1.3)
WBC 5.51 10^3/uL (4.0-10.0)
RBC 4.78 10^6/uL (4.2-5.9)
HGB 14.0 g/dL (13.0-17.0)
HCT 40.6 % (40-52)
PLT 349 10^3/uL (150-400)
APTT 34.8 sec (25-35)
INR 0.96 (0.8-1.2)
MCH 29.0 pg (27-33)

Valori patologice:
ALT 56 U/L (10-40) H
AST 45 U/L (10-40) H
MCH 31.5 pg (27-33)
RDW-SD 50.0 fL (39-46) H
RDW-CV 14.8 % (11.5-14.5) H
NEUT 73.2 % (40-70) H
LYMPH# 0.82 10^3/uL (1.0-4.0) L
"""


def test_normal_lab_section_extraction():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    plt = [c for c in candidates if c.raw_test_name == "PLT" and c.raw_value == "349"]
    assert len(plt) == 1
    assert plt[0].source_section_status == "normal"
    assert plt[0].raw_unit == "10^3/uL"
    assert plt[0].reference_range == "150-400"


def test_pathological_lab_section_extraction():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    alt = [c for c in candidates if c.raw_test_name == "ALT"]
    assert len(alt) == 1
    assert alt[0].source_section_status == "pathological"
    assert alt[0].source_flag == "H"
    assert alt[0].raw_value == "56"


def test_cbc_abbreviations_extracted():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    names = {c.raw_test_name for c in candidates}
    assert {"WBC", "RBC", "HGB", "HCT", "PLT"}.issubset(names)


def test_romanian_analyte_aliases_extracted_verbatim():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    names = {c.raw_test_name for c in candidates}
    assert "Bilirubina totala" in names
    assert "Glucoza" in names
    assert "Creatinina" in names


def test_numeric_value_parsed():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    wbc = next(c for c in candidates if c.raw_test_name == "WBC")
    assert wbc.parsed_value == 5.51


def test_textual_value_preserved_when_not_numeric():
    candidates = extract_lab_candidates_from_segment(_segment("Grup sanguin AB"))
    # "AB" is not a numeric value shape at all — this line should not be
    # mistaken for a lab row rather than fabricating a parse.
    assert candidates == []


def test_textual_qualitative_value_preserved_verbatim():
    """A non-numeric result (e.g. a blood group or a qualitative
    positive/negative test) is still a real lab observation — its text
    value must be preserved, not discarded for lacking a number."""
    candidates = extract_lab_candidates_from_segment(_segment("VDRL: Negativ"))
    assert len(candidates) == 1
    assert candidates[0].raw_test_name == "VDRL"
    assert candidates[0].raw_value == "Negativ"
    assert candidates[0].parsed_value is None


def test_units_and_reference_intervals_captured():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    hgb = next(c for c in candidates if c.raw_test_name == "HGB")
    assert hgb.raw_unit == "g/dL"
    assert hgb.reference_range == "13.0-17.0"


def test_provider_flag_extracted_verbatim():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    lymph = next(c for c in candidates if c.raw_test_name.startswith("LYMPH"))
    assert lymph.source_flag == "L"


def test_pathological_section_conflict_candidate_pair_present():
    """The known MCH conflict: same analyte name appears once under
    'Valori normale' and once under 'Valori patologice' with a DIFFERENT
    value — both extracted, neither dropped."""
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    mch = [c for c in candidates if c.raw_test_name == "MCH"]
    assert len(mch) == 2
    values = {c.raw_value for c in mch}
    assert values == {"29.0", "31.5"}
    statuses = {c.source_section_status for c in mch}
    assert statuses == {"normal", "pathological"}


def test_observation_date_extracted_only_from_explicit_date_label():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    assert all(c.observation_date == "10.01.2026" for c in candidates)


def test_no_date_label_means_no_fabricated_observation_date():
    text = "Un rezultat mentionat pe 10.01.2026 nu este o eticheta de recoltare.\nWBC 5.5 10^3/uL"
    candidates = extract_lab_candidates_from_segment(_segment(text))
    wbc = next(c for c in candidates if c.raw_test_name == "WBC")
    assert wbc.observation_date is None


def test_request_code_extracted():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    assert all(c.request_code == "LAB-2026-0091" for c in candidates)


def test_source_segment_provenance_retained():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    assert all(c.source_segment_id == "seg-000-laborator" for c in candidates)
    assert all(c.source_heading == "EXAMENE DE LABORATOR" for c in candidates)


def test_source_evidence_text_is_verbatim_source_line():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    plt = next(c for c in candidates if c.raw_test_name == "PLT" and c.raw_value == "349")
    assert plt.source_evidence_text == "PLT 349 10^3/uL (150-400)"


def test_narrative_numbers_are_not_treated_as_lab_results():
    """A number appearing in ordinary prose must never be mistaken for a
    lab result merely because it resembles 'NAME 5.4' — precision over
    recall."""
    text = "Pacientul a fost internat de 3 ori in ultimele 5 luni pentru control."
    candidates = extract_lab_candidates_from_segment(_segment(text))
    assert candidates == []


def test_unresolvable_name_still_extracted_as_a_candidate_verbatim():
    """Extraction never decides resolvability — an obscure/unknown test
    name is still extracted verbatim; resolve_analyte (Phase 6
    persistence) is what may later leave it unresolved."""
    candidates = extract_lab_candidates_from_segment(_segment("ZZQFOO 12.3 mg/dL"))
    assert len(candidates) == 1
    assert candidates[0].raw_test_name == "ZZQFOO"


def test_table_like_rows_are_extracted():
    table = SegmentTableData(
        headers=["Denumire", "Rezultat", "UM", "Interval referinta"],
        rows=[
            ["Sodiu", "140", "mmol/L", "136-145"],
            ["Potasiu", "4.1", "mmol/L", "3.5-5.1"],
        ],
    )
    candidates = extract_lab_candidates_from_segment(_segment("", table_data=table))
    names_values = {(c.raw_test_name, c.raw_value) for c in candidates}
    assert ("Sodiu", "140") in names_values
    assert ("Potasiu", "4.1") in names_values
    sodiu = next(c for c in candidates if c.raw_test_name == "Sodiu")
    assert sodiu.raw_unit == "mmol/L"
    assert sodiu.reference_range == "136-145"


def test_source_order_preserved():
    candidates = extract_lab_candidates_from_segment(_segment(HEMATOLOGY_FIXTURE_TEXT))
    names_in_order = [c.raw_test_name for c in candidates]
    assert names_in_order.index("AST") < names_in_order.index("WBC")
    assert names_in_order.index("ALT") < names_in_order.index("NEUT")
