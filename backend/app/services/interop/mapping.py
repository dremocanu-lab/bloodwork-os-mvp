"""A small, SAFE declarative mapping DSL (P15/P16).

Deliberately NOT a general expression language: every rule is a schema-
validated Pydantic model restricted to a fixed, enumerated set of
operations. There is no `eval()`, no arbitrary Python/JavaScript/shell,
and no way to construct an operation outside this allowlist — Pydantic's
`Literal` type rejects an unknown `op` at validation time, before a rule
is ever stored or run.

P17 (FHIRPath) note: this Phase does not pull in a maintained FHIRPath
library. `field_path` here is a deliberately restricted subset (dotted
attribute/array-index access plus one `coding[system=...]` filter for the
single real FHIR shape this connector needs: picking a coding out of a
CodeableConcept by system) — enough for the FHIR resource shapes Phase 1
actually consumes, documented as a subset rather than claimed as full
FHIRPath. If a later phase needs richer extraction, swap this function's
body for a real FHIRPath library's `.get()` without changing the rule
schema below.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

_PATH_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\[(-?\d+|[^\]=]+=[^\]]+)\])?")


class MappingError(ValueError):
    pass


def _split_path(path: str) -> list[str]:
    """Split on "." at the top level only — a bracket filter's VALUE
    (e.g. a FHIR system URI like http://loinc.org) commonly contains dots
    of its own and must not be split on."""
    segments: list[str] = []
    current: list[str] = []
    depth = 0
    for char in path:
        if char == "[":
            depth += 1
            current.append(char)
        elif char == "]":
            depth -= 1
            current.append(char)
        elif char == "." and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    segments.append("".join(current))
    return segments


def extract_field_path(resource: dict[str, Any], path: str) -> Any:
    """Restricted safe accessor — see module docstring for exactly what's
    supported. Returns None if any segment is missing (never raises for a
    merely-absent field; raises MappingError only for a malformed path)."""
    current: Any = resource
    if not path:
        return current

    pos = 0
    for segment in _split_path(path):
        if current is None:
            return None
        match = _PATH_TOKEN.fullmatch(segment)
        if not match:
            raise MappingError(f"Invalid field_path segment: {segment!r}")
        name, _, index_or_filter = match.groups()

        if not isinstance(current, dict) or name not in current:
            return None
        current = current[name]

        if index_or_filter is not None:
            if not isinstance(current, list):
                return None
            if "=" in index_or_filter:
                key, _, value = index_or_filter.partition("=")
                value = value.strip("'\"")
                matched = [item for item in current if isinstance(item, dict) and item.get(key) == value]
                current = matched[0] if matched else None
            else:
                try:
                    idx = int(index_or_filter)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
        pos += 1
    return current


class ConstantRule(BaseModel):
    op: Literal["constant"]
    value: Any


class FieldPathRule(BaseModel):
    op: Literal["field_path"]
    path: str


class LookupTableRule(BaseModel):
    op: Literal["lookup_table"]
    source: "MappingRule"
    table: dict[str, Any]
    default: Any = None


class CodeMapRule(BaseModel):
    """Maps a FHIR `system`+`code` pair to a Bragi canonical concept. Reads
    from InteropTerminologyMapping (approved rows only) at call time — see
    fhir_connector.py; this model just declares the rule shape."""

    op: Literal["code_map"]
    system_path: str
    code_path: str


class UnitMapRule(BaseModel):
    op: Literal["unit_map"]
    source: "MappingRule"
    table: dict[str, str]


class StringNormalizeRule(BaseModel):
    op: Literal["string_normalize"]
    source: "MappingRule"
    trim: bool = True
    case: Literal["none", "upper", "lower"] = "none"


class DateParseRule(BaseModel):
    op: Literal["date_parse"]
    source: "MappingRule"


MappingRule = Union[
    ConstantRule,
    FieldPathRule,
    LookupTableRule,
    CodeMapRule,
    UnitMapRule,
    StringNormalizeRule,
    DateParseRule,
]

for _cls in (LookupTableRule, UnitMapRule, StringNormalizeRule, DateParseRule):
    _cls.model_rebuild()


def parse_mapping_rule(raw: dict[str, Any]) -> MappingRule:
    """Validate an untrusted dict (e.g. from ConnectionProfile.terminology_overrides_json)
    into a real MappingRule, raising MappingError (never letting a malformed
    or unknown-op rule through) on failure."""
    op = raw.get("op")
    model_by_op: dict[str, type[BaseModel]] = {
        "constant": ConstantRule,
        "field_path": FieldPathRule,
        "lookup_table": LookupTableRule,
        "code_map": CodeMapRule,
        "unit_map": UnitMapRule,
        "string_normalize": StringNormalizeRule,
        "date_parse": DateParseRule,
    }
    model = model_by_op.get(op)
    if model is None:
        raise MappingError(f"Unknown mapping op {op!r}. Allowed: {sorted(model_by_op)}")
    try:
        return model.model_validate(raw)
    except Exception as exc:
        raise MappingError(f"Invalid mapping rule: {exc}") from exc


def apply_mapping_rule(rule: MappingRule, resource: dict[str, Any]) -> Any:
    if isinstance(rule, ConstantRule):
        return rule.value
    if isinstance(rule, FieldPathRule):
        return extract_field_path(resource, rule.path)
    if isinstance(rule, LookupTableRule):
        source_value = apply_mapping_rule(rule.source, resource)
        return rule.table.get(str(source_value), rule.default)
    if isinstance(rule, UnitMapRule):
        source_value = apply_mapping_rule(rule.source, resource)
        return rule.table.get(str(source_value), source_value)
    if isinstance(rule, StringNormalizeRule):
        value = apply_mapping_rule(rule.source, resource)
        if value is None:
            return None
        value = str(value)
        if rule.trim:
            value = value.strip()
        if rule.case == "upper":
            value = value.upper()
        elif rule.case == "lower":
            value = value.lower()
        return value
    if isinstance(rule, DateParseRule):
        value = apply_mapping_rule(rule.source, resource)
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None
    if isinstance(rule, CodeMapRule):
        # Resolved by the caller (fhir_connector.py), which has DB access to
        # InteropTerminologyMapping — this function only extracts the raw
        # system/code pair for the caller to look up.
        system = extract_field_path(resource, rule.system_path)
        code = extract_field_path(resource, rule.code_path)
        return {"system": system, "code": code}
    raise MappingError(f"Unhandled rule type: {type(rule)}")
