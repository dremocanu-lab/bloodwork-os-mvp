from __future__ import annotations

import re
from typing import Any

from app.report_fields import extract_report_metadata
from app.synonyms import normalize_test_name


KNOWN_TEST_ALIASES = {
    "WBC": "White Blood Cell Count",
    "RBC": "Red Blood Cell Count",
    "HGB": "Hemoglobin",
    "HB": "Hemoglobin",
    "HCT": "Hematocrit",
    "MCV": "Mean Corpuscular Volume",
    "MCH": "Mean Corpuscular Hemoglobin",
    "MCHC": "Mean Corpuscular Hemoglobin Concentration",
    "PLT": "Platelet Count",
    "RDW": "Red Cell Distribution Width",
    "RDW-SD": "Red Cell Distribution Width - SD",
    "RDWSD": "Red Cell Distribution Width - SD",
    "RDW-CV": "Red Cell Distribution Width - CV",
    "RDWCV": "Red Cell Distribution Width - CV",
    "PDW": "Platelet Distribution Width",
    "MPV": "Mean Platelet Volume",
    "P-LCR": "P-LCR",
    "PLCR": "P-LCR",
    "PCT": "Plateletcrit",
    "NRBC#": "Nucleated Red Blood Cells Absolute",
    "NRBC": "Nucleated Red Blood Cells Absolute",
    "NRBC%": "NRBC Percent",
    "NEUT#": "Neutrophils Absolute",
    "NEUT": "Neutrophils Absolute",
    "NEUT%": "Neutrophils Percent",
    "LYMPH#": "Lymphocytes Absolute",
    "LYMPH": "Lymphocytes Absolute",
    "LYMPH%": "Lymphocytes Percent",
    "MONO#": "Monocytes Absolute",
    "MONO": "Monocytes Absolute",
    "MONO%": "Monocytes Percent",
    "EO#": "Eosinophils Absolute",
    "EO": "Eosinophils Absolute",
    "EO%": "Eosinophils Percent",
    "EOS#": "Eosinophils Absolute",
    "EOS": "Eosinophils Absolute",
    "EOS%": "Eosinophils Percent",
    "BASO#": "Basophils Absolute",
    "BASO": "Basophils Absolute",
    "BASO%": "Basophils Percent",
    "IG#": "Immature Granulocytes Absolute",
    "IG": "Immature Granulocytes Absolute",
    "IG%": "Immature Granulocytes Percent",
    "GLU": "Glucose",
    "GLUCOSE": "Glucose",
    "GLUCOZA": "Glucose",
    "GLICEMIE": "Glucose",
    "CREATININA": "Creatinine",
    "CREATININĂ": "Creatinine",
    "CREATININE": "Creatinine",
    "UREE": "Urea",
    "UREA": "Urea",
    "BUN": "Urea",
    "ALT": "ALT",
    "ALAT": "ALT",
    "TGP": "ALT",
    "AST": "AST",
    "ASAT": "AST",
    "TGO": "AST",
    "GGT": "GGT",
    "TSH": "TSH",
    "CRP": "CRP",
    "HDL": "HDL Cholesterol",
    "LDL": "LDL Cholesterol",
}

CBC_ORDER = [
    "WBC",
    "RBC",
    "HGB",
    "HCT",
    "MCV",
    "MCH",
    "MCHC",
    "PLT",
    "RDW-SD",
    "RDW-CV",
    "PDW",
    "MPV",
    "P-LCR",
    "PCT",
    "NRBC#",
    "NRBC%",
    "NEUT#",
    "NEUT%",
    "LYMPH#",
    "LYMPH%",
    "MONO#",
    "MONO%",
    "EO#",
    "EO%",
    "BASO#",
    "BASO%",
    "IG#",
    "IG%",
]

DEFAULT_CBC_UNITS = {
    "WBC": "10^3/uL",
    "RBC": "10^6/uL",
    "HGB": "g/dL",
    "HB": "g/dL",
    "HCT": "%",
    "MCV": "fL",
    "MCH": "pg",
    "MCHC": "g/dL",
    "PLT": "10^3/uL",
    "RDW": "%",
    "RDW-SD": "fL",
    "RDW-CV": "%",
    "PDW": "fL",
    "MPV": "fL",
    "P-LCR": "%",
    "PCT": "%",
    "NRBC#": "10^3/uL",
    "NRBC": "10^3/uL",
    "NRBC%": "%",
    "NEUT#": "10^3/uL",
    "NEUT": "10^3/uL",
    "NEUT%": "%",
    "LYMPH#": "10^3/uL",
    "LYMPH": "10^3/uL",
    "LYMPH%": "%",
    "MONO#": "10^3/uL",
    "MONO": "10^3/uL",
    "MONO%": "%",
    "EO#": "10^3/uL",
    "EO": "10^3/uL",
    "EO%": "%",
    "BASO#": "10^3/uL",
    "BASO": "10^3/uL",
    "BASO%": "%",
    "IG#": "10^3/uL",
    "IG": "10^3/uL",
    "IG%": "%",
}

NULL_RESULT_TOKENS = {
    "",
    "-",
    "--",
    "---",
    "----",
    "-----",
    "------",
    "—",
    "–",
    "nil",
    "n/a",
    "na",
    "null",
    "none",
}

ARROW_HIGH_MARKERS = {"↑", "▲", "↗", "⬆", "➚"}
ARROW_LOW_MARKERS = {"↓", "▼", "↘", "⬇", "➘"}

NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
RANGE_RE = re.compile(
    r"(?P<low>[-+]?\d+(?:[.,]\d+)?)\s*[-–—]\s*(?P<high>[-+]?\d+(?:[.,]\d+)?)"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    cleaned = str(value)
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def normalize_decimal(value: Any) -> str | None:
    cleaned = clean_text(value)

    if not cleaned:
        return None

    if cleaned.lower() in NULL_RESULT_TOKENS:
        return None

    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^0-9.+-]", "", cleaned)

    if cleaned.startswith("."):
        cleaned = "0" + cleaned

    if cleaned in {"", "+", "-", ".", "+.", "-."}:
        return None

    return cleaned


def to_float(value: Any) -> float | None:
    normalized = normalize_decimal(value)

    if normalized is None:
        return None

    try:
        return float(normalized)
    except Exception:
        return None


def is_null_result(value: Any) -> bool:
    cleaned = clean_text(value).lower()
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")

    if cleaned in NULL_RESULT_TOKENS:
        return True

    return re.fullmatch(r"[-_]{2,}", cleaned) is not None


def normalize_test_token(value: Any) -> str:
    cleaned = clean_text(value).upper()
    cleaned = cleaned.replace("_", "-")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace(".", "")
    cleaned = cleaned.replace("＃", "#")
    cleaned = cleaned.replace("％", "%")

    if cleaned == "RDWSD":
        return "RDW-SD"

    if cleaned == "RDWCV":
        return "RDW-CV"

    if cleaned == "PLCR":
        return "P-LCR"

    if cleaned == "P-LCR%":
        return "P-LCR"

    return cleaned


def detect_test_key(value: Any) -> str | None:
    text = clean_text(value)

    if not text:
        return None

    parts = re.split(r"[\s|:;]+", text)

    # Exact token pass first.
    for part in parts:
        token = normalize_test_token(part)

        if token in KNOWN_TEST_ALIASES:
            return token

    # Compact row pass.
    compact = normalize_test_token(text)

    for alias in sorted(KNOWN_TEST_ALIASES.keys(), key=len, reverse=True):
        pattern = re.escape(alias).replace(r"\-", r"[-\s]?")

        if re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", compact, re.IGNORECASE):
            return normalize_test_token(alias)

    return None


def clean_unit(unit: Any, test_key: str | None = None) -> str | None:
    cleaned = clean_text(unit)

    if not cleaned:
        if test_key:
            return DEFAULT_CBC_UNITS.get(test_key)
        return None

    compact = cleaned.replace(" ", "")
    lower = compact.lower()

    if compact == "%":
        return "%"

    if lower in {"fl", "femtoliter"}:
        return "fL"

    if lower == "pg":
        return "pg"

    if lower in {"g/dl", "g/dL".lower()}:
        return "g/dL"

    if re.search(r"10\^?3/?u?l", compact, re.IGNORECASE):
        return "10^3/uL"

    if re.search(r"10\^?6/?u?l", compact, re.IGNORECASE):
        return "10^6/uL"

    if "/" in compact and len(compact) <= 18:
        return compact

    if test_key:
        return DEFAULT_CBC_UNITS.get(test_key)

    return cleaned


def extract_unit_from_reference(reference_cell: str, test_key: str | None = None) -> str | None:
    text = clean_text(reference_cell)

    unit_patterns = [
        r"10\s*\^?\s*3\s*/?\s*u?L",
        r"10\s*\^?\s*6\s*/?\s*u?L",
        r"10\s*\^?\s*3\s*/?\s*u?l",
        r"10\s*\^?\s*6\s*/?\s*u?l",
        r"g\s*/\s*dL",
        r"g\s*/\s*dl",
        r"fL",
        r"FL",
        r"fl",
        r"pg",
        r"%",
    ]

    for pattern in unit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return clean_unit(match.group(0), test_key)

    return clean_unit(None, test_key)


def extract_reference_range(value: Any) -> str | None:
    text = clean_text(value)

    if not text:
        return None

    match = RANGE_RE.search(text)

    if not match:
        return None

    low = normalize_decimal(match.group("low"))
    high = normalize_decimal(match.group("high"))

    if low is None or high is None:
        return None

    low_float = to_float(low)
    high_float = to_float(high)

    if low_float is None or high_float is None:
        return None

    if high_float < low_float:
        low, high = high, low

    return f"{low} - {high}"


def extract_first_number(value: Any) -> str | None:
    text = clean_text(value)

    if is_null_result(text):
        return None

    match = NUMBER_RE.search(text)

    if not match:
        return None

    return normalize_decimal(match.group(0))


def infer_flag(value: Any, reference_range: Any) -> str | None:
    numeric = to_float(value)

    if numeric is None:
        return None

    reference = clean_text(reference_range)

    if not reference:
        return None

    nums = NUMBER_RE.findall(reference)

    if len(nums) < 2:
        return None

    low = to_float(nums[0])
    high = to_float(nums[1])

    if low is None or high is None:
        return None

    if high < low:
        low, high = high, low

    if numeric < low:
        return "Low"

    if numeric > high:
        return "High"

    return "Normal"


def detect_explicit_flag(row_text: str) -> str | None:
    lowered = f" {clean_text(row_text).lower()} "

    if any(marker in row_text for marker in ARROW_HIGH_MARKERS):
        return "High"

    if any(marker in row_text for marker in ARROW_LOW_MARKERS):
        return "Low"

    if " high " in lowered or " crescut " in lowered:
        return "High"

    if " low " in lowered or " scazut " in lowered:
        return "Low"

    return None


def build_lab_result(
    raw_test_name: str,
    value: Any,
    flag: Any = None,
    reference_range: Any = None,
    unit: Any = None,
    confidence: float = 0.85,
) -> dict:
    test_key = normalize_test_token(raw_test_name)
    display_candidate = KNOWN_TEST_ALIASES.get(test_key, clean_text(raw_test_name))
    normalized = normalize_test_name(display_candidate)

    final_value = normalize_decimal(value)
    final_reference = extract_reference_range(reference_range) or clean_text(reference_range) or None
    final_unit = clean_unit(unit, test_key)

    final_flag = None

    if final_value is not None:
        explicit_flag = None

        if flag:
            lowered = str(flag).strip().lower()

            if lowered in {"high", "h", "crescut"}:
                explicit_flag = "High"
            elif lowered in {"low", "l", "scazut"}:
                explicit_flag = "Low"
            elif lowered == "normal":
                explicit_flag = "Normal"

        final_flag = explicit_flag or infer_flag(final_value, final_reference)

        if not final_reference and final_flag == "Normal":
            final_flag = None

    return {
        "raw_test_name": test_key or clean_text(raw_test_name),
        "canonical_name": normalized["canonical_name"],
        "display_name": normalized["display_name"],
        "category": normalized["category"],
        "value": final_value,
        "flag": final_flag,
        "reference_range": final_reference,
        "unit": final_unit,
        "confidence": confidence,
    }


def build_nil_result(
    raw_test_name: str,
    reference_range: Any = None,
    unit: Any = None,
    confidence: float = 0.95,
) -> dict:
    return build_lab_result(
        raw_test_name=raw_test_name,
        value=None,
        flag=None,
        reference_range=reference_range,
        unit=unit,
        confidence=confidence,
    )


def split_google_table_lines(text: str) -> list[str]:
    lines = []

    for line in (text or "").splitlines():
        clean_line = clean_text(line)

        if not clean_line:
            continue

        if "|" in clean_line:
            lines.append(clean_line)

    return lines


def parse_google_table_row(line: str) -> dict | None:
    cells = [clean_text(cell) for cell in line.split("|")]
    cells = [cell for cell in cells if cell]

    if len(cells) < 2:
        return None

    test_key = None
    test_index = -1

    for index, cell in enumerate(cells):
        detected = detect_test_key(cell)

        if detected:
            test_key = detected
            test_index = index
            break

    if not test_key:
        return None

    after = cells[test_index + 1 :]

    if not after:
        return None

    row_joined = " | ".join(cells)
    explicit_flag = detect_explicit_flag(row_joined)

    value = None
    value_cell_index = None

    for index, cell in enumerate(after):
        if is_null_result(cell):
            value = None
            value_cell_index = index
            break

        maybe_number = extract_first_number(cell)

        if maybe_number is not None:
            value = maybe_number
            value_cell_index = index
            break

    if value_cell_index is None:
        return None

    reference_range = None
    unit = None

    for cell in after[value_cell_index + 1 :]:
        maybe_range = extract_reference_range(cell)

        if maybe_range:
            reference_range = maybe_range
            unit = extract_unit_from_reference(cell, test_key)
            break

    if not unit:
        for cell in after[value_cell_index + 1 :]:
            maybe_unit = clean_unit(cell, test_key)

            if maybe_unit:
                unit = maybe_unit
                break

    if value is None:
        return build_nil_result(
            raw_test_name=test_key,
            reference_range=reference_range,
            unit=unit,
            confidence=0.98,
        )

    return build_lab_result(
        raw_test_name=test_key,
        value=value,
        flag=explicit_flag,
        reference_range=reference_range,
        unit=unit,
        confidence=0.96 if reference_range else 0.82,
    )


def parse_google_document_ai_tables(text: str) -> list[dict]:
    labs = []
    seen = set()

    for line in split_google_table_lines(text):
        parsed = parse_google_table_row(line)

        if not parsed:
            continue

        key = parsed.get("canonical_name") or parsed.get("display_name") or parsed.get("raw_test_name")

        if not key:
            continue

        key = str(key).lower()

        if key in seen:
            continue

        seen.add(key)
        labs.append(parsed)

    return labs


def compact_alias_pattern(alias: str) -> str:
    escaped = re.escape(alias)
    escaped = escaped.replace(r"\-", r"[-\s]?")
    escaped = escaped.replace(r"\#", r"[#＃]?")
    escaped = escaped.replace(r"\%", r"[%％]?")
    return escaped


def parse_flat_known_cbc_rows(text: str) -> list[dict]:
    """
    Last-resort text parser for Fundeni CBC pages.

    It looks for known CBC aliases in order and tries to capture:
      alias result reference-low reference-high unit

    This is intentionally conservative. It will not call Normal without a reference.
    """
    flat = clean_text(text)
    labs = []
    seen = set()

    for test_key in CBC_ORDER:
        aliases = [test_key]

        if test_key == "P-LCR":
            aliases.append("PLCR")
        if test_key == "RDW-SD":
            aliases.append("RDW SD")
        if test_key == "RDW-CV":
            aliases.append("RDW CV")

        match = None

        for alias in aliases:
            pattern = compact_alias_pattern(alias)
            match = re.search(
                rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])(?P<tail>.{{0,180}})",
                flat,
                re.IGNORECASE,
            )

            if match:
                break

        if not match:
            continue

        tail = match.group("tail") or ""

        # Stop at next CBC alias if found.
        cut = len(tail)

        for other_key in CBC_ORDER:
            if other_key == test_key:
                continue

            other_pattern = compact_alias_pattern(other_key)
            other_match = re.search(rf"(?<![A-Za-z0-9]){other_pattern}(?![A-Za-z0-9])", tail, re.IGNORECASE)

            if other_match:
                cut = min(cut, other_match.start())

        tail = tail[:cut]

        explicit_flag = detect_explicit_flag(tail)

        if re.search(r"(^|\s)(?:-{2,}|_{2,}|nil|n/a|null)(\s|$)", tail, re.IGNORECASE):
            labs.append(
                build_nil_result(
                    raw_test_name=test_key,
                    reference_range=extract_reference_range(tail),
                    unit=extract_unit_from_reference(tail, test_key),
                    confidence=0.78,
                )
            )
            continue

        numbers = NUMBER_RE.findall(tail)

        if not numbers:
            continue

        value = normalize_decimal(numbers[0])
        reference_range = None

        if len(numbers) >= 3:
            low = normalize_decimal(numbers[1])
            high = normalize_decimal(numbers[2])

            if low and high:
                low_f = to_float(low)
                high_f = to_float(high)

                if low_f is not None and high_f is not None and low_f != high_f:
                    if high_f < low_f:
                        low, high = high, low
                    reference_range = f"{low} - {high}"

        unit = extract_unit_from_reference(tail, test_key)

        row = build_lab_result(
            raw_test_name=test_key,
            value=value,
            flag=explicit_flag,
            reference_range=reference_range,
            unit=unit,
            confidence=0.72 if reference_range else 0.55,
        )

        key = str(row.get("canonical_name") or row.get("raw_test_name")).lower()

        if key in seen:
            continue

        seen.add(key)
        labs.append(row)

    return labs


def dedupe_labs(lab_lists: list[list[dict]]) -> list[dict]:
    merged: dict[str, dict] = {}

    def score(row: dict) -> float:
        value = 0.0
        value += float(row.get("confidence") or 0)

        if row.get("value") is not None:
            value += 0.35

        if row.get("reference_range"):
            value += 0.45

        if row.get("unit"):
            value += 0.15

        if row.get("flag") in {"High", "Low"}:
            value += 0.10

        return value

    for labs in lab_lists:
        for row in labs:
            key = str(row.get("canonical_name") or row.get("display_name") or row.get("raw_test_name") or "").lower()

            if not key:
                continue

            if key not in merged or score(row) >= score(merged[key]):
                merged[key] = row

    return list(merged.values())


def parse_bloodwork_text(text: str) -> dict:
    metadata = extract_report_metadata(text or "")

    table_labs = parse_google_document_ai_tables(text or "")
    flat_labs = parse_flat_known_cbc_rows(text or "")

    labs = dedupe_labs([table_labs, flat_labs])

    warnings = []

    if not metadata.get("collected_on") and not metadata.get("test_date"):
        warnings.append("Clinical collection date was not found by deterministic parser.")

    rows_with_values = [row for row in labs if row.get("value") is not None]
    rows_with_references = [row for row in rows_with_values if row.get("reference_range")]

    if rows_with_values and len(rows_with_references) < max(3, int(len(rows_with_values) * 0.55)):
        warnings.append("Most lab values are missing reference ranges. AI organizer fallback may be needed.")

    return {
        **metadata,
        "labs": labs,
        "warnings": warnings,
    }