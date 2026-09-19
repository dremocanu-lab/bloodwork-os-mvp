"""Source Geometry + Clinical Table Intelligence V3, Part 55 — fixture
geometry expectations, verified against the REAL PDF the fixture
generates (not hand-written fake geometry)."""

from __future__ import annotations

from app.services.clinical_document.geometry_alignment import align_segment_to_blocks
from app.services.clinical_document.source_geometry import PageGeometry
from app.services.clinical_document.table_interpreter import classify_table_deterministic
from tests.fixtures.clinical_reader_v3_pdf_fixture import (
    ADMISSION_TEXT,
    BCR_ABL_TEXT,
    BONE_MARROW_TEXT,
    D45_TEXT,
    JAK2_TEXT,
    PHLEBOTOMY_TEXT,
    RECOMMENDATION_TEXT,
    ULTRASOUND_TEXT,
    build_synthetic_discharge_v3_fixture,
)


def _page_geometry(payload: dict, page_number: int) -> PageGeometry:
    page_payload = next(p for p in payload["page_payloads"] if p["page_number"] == page_number)
    return PageGeometry.model_validate(page_payload["geometry"])


def test_fixture_produces_a_real_pdf_and_matching_payload():
    pdf_bytes, payload = build_synthetic_discharge_v3_fixture()
    assert pdf_bytes[:4] == b"%PDF"
    assert payload["page_count"] == 8
    assert len(payload["page_payloads"]) == 8
    assert payload["extraction_coverage"]["extraction_complete"] is True


def test_d45_resolves_to_a_real_block_bbox_on_page_1():
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 1)
    matched = align_segment_to_blocks(D45_TEXT, geometry)
    assert len(matched) == 1
    assert 0 <= matched[0].bbox.x <= 1
    assert 0 <= matched[0].bbox.y <= 1
    assert matched[0].bbox.width > 0
    assert matched[0].bbox.height > 0


def test_phlebotomy_resolves_to_a_real_paragraph_bbox_on_page_2():
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 2)
    matched = align_segment_to_blocks(PHLEBOTOMY_TEXT, geometry)
    assert len(matched) == 1
    assert matched[0].bbox.width > 0


def test_admission_anomaly_paragraph_resolves_on_page_2():
    """AV 1008 lives inside the admission paragraph — Part 14's 'find
    the most specific real block' with paragraph-level precision
    (never a fabricated tiny rect estimated from character width)."""
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 2)
    matched = align_segment_to_blocks(ADMISSION_TEXT, geometry)
    assert len(matched) == 1
    assert "AV 1008" in matched[0].text


def test_medication_table_has_real_row_and_cell_geometry_on_page_3():
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 3)
    assert len(geometry.tables) == 1
    table = geometry.tables[0]
    rows = table.extract_rows()
    assert rows[0] == ["Medicament", "Doza", "Frecventa"]
    assert rows[1][0] == "Hidroxiuree"
    assert rows[2][0] == "Ruxolitinib"
    assert len(table.cells) == 9  # 3 rows x 3 cols


def test_ultrasound_jak2_bone_marrow_bcr_abl_each_resolve_to_their_own_distinct_block_on_page_4():
    """The core Part 54/58 requirement: four separate narrative facts
    on the SAME page, each with its OWN distinct source block — never
    all four collapsing onto one shared/ambiguous evidence target."""
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 4)

    ultrasound_match = align_segment_to_blocks(ULTRASOUND_TEXT, geometry)
    jak2_match = align_segment_to_blocks(JAK2_TEXT, geometry)
    bone_marrow_match = align_segment_to_blocks(BONE_MARROW_TEXT, geometry)
    bcr_abl_match = align_segment_to_blocks(BCR_ABL_TEXT, geometry)

    for match in (ultrasound_match, jak2_match, bone_marrow_match, bcr_abl_match):
        assert len(match) == 1

    block_ids = {ultrasound_match[0].block_id, jak2_match[0].block_id, bone_marrow_match[0].block_id, bcr_abl_match[0].block_id}
    assert len(block_ids) == 4  # four genuinely distinct blocks, not one shared block


def test_prescription_table_has_row_and_cell_evidence_on_page_5():
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 5)
    assert len(geometry.tables) == 1
    table = geometry.tables[0]
    rows = table.extract_rows()
    assert rows[1] == ["Besremi", "150mcg", "1 cutie"]
    classification = classify_table_deterministic(table, heading_context="Retete eliberate")
    assert classification is not None
    assert classification.table_type == "prescription"


def test_alt_analyte_result_unit_reference_cells_all_exist_on_page_6():
    """Part 55's explicit ALT expectation: analyte/result/unit/reference
    cells must all exist as real, separately-addressable geometry."""
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 6)
    assert len(geometry.tables) == 1
    table = geometry.tables[0]
    rows = table.extract_rows()
    alt_row_index = rows.index(["ALT", "56", "U/L", "10-49"])
    alt_row_cells = [c for c in table.cells if c.row_index == alt_row_index]
    assert len(alt_row_cells) == 4
    for cell in alt_row_cells:
        assert cell.bbox.width > 0
        assert cell.bbox.height > 0

    classification = classify_table_deterministic(table)
    assert classification is not None
    assert classification.table_type == "laboratory"

    # The conflicting HGB values (Part 1H/8F from prior phases) are
    # preserved as two separate rows with their own geometry, never
    # silently deduped.
    hgb_rows = [r for r in rows if r[0] == "HGB"]
    assert len(hgb_rows) == 2
    assert {r[1] for r in hgb_rows} == {"9.8", "11.2"}


def test_recommendation_resolves_to_a_real_paragraph_bbox_on_page_7():
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 7)
    matched = align_segment_to_blocks(RECOMMENDATION_TEXT, geometry)
    assert len(matched) == 1


def test_empty_templates_on_page_8_are_retained_as_source_structure_but_classify_as_empty():
    """Source structure survives (the table geometry is real and
    present) but the CLINICAL classification correctly suppresses it —
    'source table retained, clinical fact suppressed' (Part 55)."""
    _, payload = build_synthetic_discharge_v3_fixture()
    geometry = _page_geometry(payload, 8)
    assert len(geometry.tables) == 2  # both blank tables are still real, extracted source structure

    treatment_table = geometry.tables[0]
    investigation_table = geometry.tables[1]

    treatment_classification = classify_table_deterministic(treatment_table, heading_context="Tratament administrat in spital")
    assert treatment_classification is not None
    assert treatment_classification.table_type == "empty_template"

    investigation_classification = classify_table_deterministic(investigation_table, heading_context="Investigatii")
    assert investigation_classification is not None
    assert investigation_classification.table_type == "empty_template"
