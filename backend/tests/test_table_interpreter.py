"""Source Geometry + Clinical Table Intelligence V3 — generic table
classification tests. Deterministic rules tested directly; AI fallback
tested with `classify_table_via_ai`/`_call_model`-equivalent mocked —
never live OpenAI (Part 57)."""

from __future__ import annotations

from app.services.clinical_document.source_geometry import CellGeometry, NormalizedBBox, TableGeometry
from app.services.clinical_document.table_interpreter import (
    TableAIClassificationError,
    classify_table,
    classify_table_deterministic,
)


def _table(rows: list[list[str]]) -> TableGeometry:
    row_count = len(rows)
    col_count = len(rows[0]) if rows else 0
    cells = [
        CellGeometry(row_index=r, col_index=c, text=rows[r][c], bbox=NormalizedBBox(x=0.1 + c * 0.1, y=0.1 + r * 0.05, width=0.09, height=0.04))
        for r in range(row_count)
        for c in range(col_count)
    ]
    return TableGeometry(table_id="p1-t00", bbox=NormalizedBBox(x=0.1, y=0.1, width=0.5, height=0.3), row_count=row_count, col_count=col_count, cells=cells)


def test_classifies_laboratory_table_from_headers_alone():
    table = _table(
        [
            ["Analiza", "Rezultat", "UM", "Interval referinta"],
            ["ALT", "56", "U/L", "10-49"],
            ["WBC", "15.2", "10^3/uL", "4.0-10.0"],
        ]
    )
    result = classify_table_deterministic(table)
    assert result is not None
    assert result.table_type == "laboratory"
    assert result.method == "deterministic"


def test_classifies_administered_treatment_from_heading_context():
    table = _table([["PRODUS", "CANTITATE"], ["Ser fiziologic", "500ml"]])
    result = classify_table_deterministic(table, heading_context="Tratament administrat in spital")
    assert result is not None
    assert result.table_type == "administered_treatment"


def test_administered_treatment_headers_alone_without_heading_context_does_not_classify():
    """PRODUS/CANTITATE headers alone (no heading context) aren't
    confidently ANY specific type — deterministic classification should
    decline rather than guess."""
    table = _table([["PRODUS", "CANTITATE"], ["X", "Y"]])
    result = classify_table_deterministic(table, heading_context=None)
    assert result is None


def test_classifies_prescription_from_heading_context():
    table = _table([["Medicament", "Doza", "Cantitate"], ["Besremi", "150mcg", "1 cutie"]])
    result = classify_table_deterministic(table, heading_context="Retete eliberate")
    assert result is not None
    assert result.table_type == "prescription"


def test_classifies_medication_list_from_headers_and_heading():
    table = _table([["Medicament", "Doza", "Frecventa"], ["Ruxolitinib", "15mg", "x2/zi"]])
    result = classify_table_deterministic(table, heading_context="Medicatie curenta")
    assert result is not None
    assert result.table_type == "medication_list"


def test_classifies_investigation_from_heading_context():
    table = _table([["Investigatie", "Data", "Rezultat"], ["Ecografie abdominala", "04.03.2026", "Splenomegalie"]])
    result = classify_table_deterministic(table, heading_context="Investigatii")
    assert result is not None
    assert result.table_type == "investigation"


def test_classifies_vital_signs_from_header_overlap():
    table = _table([["TA", "AV", "Temperatura", "SpO2"], ["120/80", "78", "36.6", "98%"]])
    result = classify_table_deterministic(table)
    assert result is not None
    assert result.table_type == "vital_signs"


def test_empty_template_takes_priority_even_with_lab_shaped_headers():
    """A table with lab-shaped headers but entirely blank body rows is
    still template noise — Part 20's "empty template" signal must win
    over a header-based guess, never presented as if it were real data."""
    table = _table(
        [
            ["Analiza", "Rezultat", "UM", "Interval"],
            ["____", "____", "____", "____"],
        ]
    )
    result = classify_table_deterministic(table)
    assert result is not None
    assert result.table_type == "empty_template"


def test_genuinely_empty_investigation_template_classifies_as_empty_not_investigation():
    table = _table([["EKG", "ECO", "RX", "ALTELE"], ["____", "____", "____", "____"]])
    result = classify_table_deterministic(table, heading_context="Investigatii")
    assert result is not None
    assert result.table_type == "empty_template"


def test_no_deterministic_rule_matches_returns_none():
    table = _table([["Coloana X", "Coloana Y"], ["a", "b"]])
    result = classify_table_deterministic(table, heading_context=None)
    assert result is None


def test_classify_table_defaults_to_uncertain_when_ai_fallback_disabled():
    table = _table([["Coloana X", "Coloana Y"], ["a", "b"]])
    result = classify_table(table, allow_ai_fallback=False)
    assert result.table_type == "uncertain"
    assert result.method == "default"


def test_classify_table_uses_mocked_ai_fallback_when_deterministic_is_none(monkeypatch):
    from app.services.clinical_document import table_interpreter

    def fake_classify_via_ai(table, **kwargs):
        return table_interpreter.TableClassification("diagnosis", 0.7, "ai", "column headers suggest a diagnosis list")

    monkeypatch.setattr(table_interpreter, "classify_table_via_ai", fake_classify_via_ai)
    table = _table([["Coloana X", "Coloana Y"], ["a", "b"]])
    result = classify_table(table, allow_ai_fallback=True)
    assert result.table_type == "diagnosis"
    assert result.method == "ai"


def test_classify_table_falls_back_to_uncertain_when_ai_classification_fails(monkeypatch):
    from app.services.clinical_document import table_interpreter

    def fake_classify_via_ai(table, **kwargs):
        raise TableAIClassificationError("simulated provider failure")

    monkeypatch.setattr(table_interpreter, "classify_table_via_ai", fake_classify_via_ai)
    table = _table([["Coloana X", "Coloana Y"], ["a", "b"]])
    result = classify_table(table, allow_ai_fallback=True)
    assert result.table_type == "uncertain"


def test_ai_classifier_rejects_unrecognized_table_type(monkeypatch):
    """The model returning a label outside the closed enum must never
    be trusted — this is enforced even though it's also constrained by
    the JSON schema's own enum, as a second, doubly-enforced gate (same
    'never trust the model's JSON merely because it parsed' discipline
    as ai_interpreter.py)."""
    from app.services.clinical_document import table_interpreter

    class FakeResponse:
        output_text = '{"table_type": "not_a_real_type", "confidence": 0.9, "rationale": "x"}'

    class FakeResponses:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(table_interpreter, "_client", lambda: FakeClient())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    table = _table([["Coloana X", "Coloana Y"], ["a", "b"]])
    try:
        table_interpreter.classify_table_via_ai(table, heading_context=None, section_context=None, source_language="ro")
        assert False, "expected TableAIClassificationError"
    except TableAIClassificationError:
        pass
