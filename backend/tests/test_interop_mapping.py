"""Mapping DSL unit tests (BRAGI_INTEROP_PLAN.md P15/P16). No DB, no
network. Confirms the schema-validated allowlist actually rejects unknown
operations rather than silently accepting or evaluating them."""

import pytest

from app.services.interop.mapping import (
    MappingError,
    apply_mapping_rule,
    extract_field_path,
    parse_mapping_rule,
)

OBSERVATION = {
    "code": {
        "coding": [
            {"system": "http://hospital.example.ro/local-lab-codes", "code": "HGB-LOCAL-X7", "display": "Hgb local test X7"}
        ],
        "text": "Hgb local test X7",
    },
    "valueQuantity": {"value": 14.3, "unit": "g/dL"},
}


def test_field_path_dotted_and_indexed():
    assert extract_field_path(OBSERVATION, "code.coding[0].code") == "HGB-LOCAL-X7"
    assert extract_field_path(OBSERVATION, "valueQuantity.value") == 14.3


def test_field_path_filter_by_system():
    assert (
        extract_field_path(OBSERVATION, "code.coding[system=http://hospital.example.ro/local-lab-codes].display")
        == "Hgb local test X7"
    )


def test_field_path_missing_segment_returns_none_not_error():
    assert extract_field_path(OBSERVATION, "code.coding[0].nonexistent") is None
    assert extract_field_path(OBSERVATION, "nope.nope") is None


def test_unknown_op_is_rejected():
    with pytest.raises(MappingError):
        parse_mapping_rule({"op": "eval", "code": "os.system('rm -rf /')"})


def test_arbitrary_python_like_ops_are_never_valid():
    for forbidden_op in ("exec", "eval", "shell", "python", "javascript"):
        with pytest.raises(MappingError):
            parse_mapping_rule({"op": forbidden_op})


def test_lookup_table_maps_local_unit_to_canonical():
    rule = parse_mapping_rule(
        {
            "op": "unit_map",
            "source": {"op": "field_path", "path": "valueQuantity.unit"},
            "table": {"g/dL": "g/dL", "gr%": "g/dL"},
        }
    )
    assert apply_mapping_rule(rule, OBSERVATION) == "g/dL"


def test_constant_and_string_normalize():
    rule = parse_mapping_rule({"op": "string_normalize", "source": {"op": "constant", "value": "  Hemoglobin  "}, "case": "lower"})
    assert apply_mapping_rule(rule, OBSERVATION) == "hemoglobin"


def test_malformed_rule_is_rejected():
    with pytest.raises(MappingError):
        parse_mapping_rule({"op": "field_path"})  # missing required "path"
