"""Tabular/spreadsheet adapters: .csv / .tsv (stdlib csv), .xlsx
(openpyxl), .ods (minimal direct content.xml parse — see office_text_
adapter.py's ODT function for why this doesn't use odfpy).

These are parsed as real workbook/tabular structure — never rasterized
or OCR'd, and never assumed to be a lab report just because they're
tabular (Part K: "an unrelated spreadsheet" must not be misclassified).
The rendered text feeds the SAME downstream classifier every other
format uses; classification, not this adapter, decides whether the
content is actually lab data.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as DefusedET

from app.services.ingestion.adapters.text_adapter import decode_text_bytes
from app.services.ingestion.contract import ExtractionResult, ExtractionStatus
from app.services.ingestion.security import IngestionSecurityError, safe_open_zip

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_ROWS_PER_SHEET = 20_000  # a real lab/clinical spreadsheet is never this large; a safety cap, not a real-world limit


def _render_rows_as_text(sheet_name: str, rows: list[list[str]]) -> str:
    lines = [f"--- SHEET: {sheet_name} ---"] if sheet_name else []
    for row in rows:
        if any(cell.strip() for cell in row):
            lines.append(" | ".join(row))
    return "\n".join(lines)


def extract_csv(file_path: Path, delimiter: str = ",") -> ExtractionResult:
    try:
        raw = file_path.read_bytes()
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".csv", reason=f"Could not read file: {error}")

    decoded = decode_text_bytes(raw)
    extension = ".tsv" if delimiter == "\t" else ".csv"

    try:
        reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
        rows = [[cell for cell in row] for row in reader]
    except csv.Error as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=extension, reason=f"Could not parse this file as {extension.strip('.').upper()}: {error}")

    rows = rows[:MAX_ROWS_PER_SHEET]
    text = _render_rows_as_text("", rows)
    table = {"sheet": None, "headers": rows[0] if rows else [], "rows": rows[1:] if len(rows) > 1 else []}

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=[line for line in text.splitlines() if line.strip()],
        tables=[table],
        source_extension=extension,
        source_mime="text/tab-separated-values" if delimiter == "\t" else "text/csv",
        extraction_provider="local_spreadsheet",
        warnings=[] if text else ["No rows found in this file."],
        structured_payload={"rows": rows},
    )


def extract_xlsx(file_path: Path) -> ExtractionResult:
    try:
        with file_path.open("rb") as handle:
            if handle.read(8) == _OLE_MAGIC:
                return ExtractionResult(
                    status=ExtractionStatus.ENCRYPTED,
                    source_extension=".xlsx",
                    reason="This spreadsheet appears to be password-protected — Bragi cannot open encrypted files. Please remove the password and re-upload.",
                )
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xlsx", reason=f"Could not read file: {error}")

    try:
        safe_open_zip(file_path).close()
    except IngestionSecurityError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xlsx", reason=str(error))

    try:
        import openpyxl
    except ImportError:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xlsx", reason="XLSX text extraction is not available in this environment.")

    try:
        # data_only=True: read the LAST CACHED COMPUTED VALUE Excel itself
        # stored for each formula cell — openpyxl never evaluates a
        # formula itself (it has no formula engine at all), so this is
        # inherently safe; a formula string is only ever read as inert
        # text/cached data, never executed.
        workbook = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
    except Exception as error:  # noqa: BLE001 — any of openpyxl's own parse errors
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".xlsx", reason=f"Could not read this spreadsheet: {error}")

    tables: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    sections: list[str] = []

    try:
        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            rows: list[list[str]] = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= MAX_ROWS_PER_SHEET:
                    break
                rows.append(["" if cell is None else str(cell) for cell in row])

            sections.append(sheet_name)
            rendered = _render_rows_as_text(sheet_name, rows)
            if rendered:
                text_blocks.append(rendered)
            tables.append({"sheet": sheet_name, "headers": rows[0] if rows else [], "rows": rows[1:] if len(rows) > 1 else []})
    finally:
        workbook.close()

    text = "\n\n".join(text_blocks).strip()

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=[line for block in text_blocks for line in block.splitlines() if line.strip()],
        tables=tables,
        sections=sections,
        source_extension=".xlsx",
        source_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extraction_provider="local_spreadsheet",
        warnings=[] if text else ["No data found in this spreadsheet."],
    )


_ODF_TABLE_NS_LOCALS = {"table": "table", "table-row": "row", "table-cell": "cell"}


def extract_ods(file_path: Path) -> ExtractionResult:
    try:
        with file_path.open("rb") as handle:
            if handle.read(8) == _OLE_MAGIC:
                return ExtractionResult(
                    status=ExtractionStatus.ENCRYPTED,
                    source_extension=".ods",
                    reason="This spreadsheet appears to be password-protected — Bragi cannot open encrypted files.",
                )
    except OSError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".ods", reason=f"Could not read file: {error}")

    try:
        archive = safe_open_zip(file_path)
    except IngestionSecurityError as error:
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".ods", reason=str(error))

    try:
        with archive:
            try:
                content_xml = archive.read("content.xml")
            except KeyError:
                return ExtractionResult(
                    status=ExtractionStatus.EXTRACTION_FAILED,
                    source_extension=".ods",
                    reason="This file doesn't contain a recognizable OpenDocument content.xml — it may not really be an ODS file.",
                )
    except Exception as error:  # noqa: BLE001
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".ods", reason=f"Could not read this document: {error}")

    try:
        root = DefusedET.fromstring(content_xml)
    except Exception as error:  # noqa: BLE001
        return ExtractionResult(status=ExtractionStatus.EXTRACTION_FAILED, source_extension=".ods", reason=f"Could not parse this document's contents: {error}")

    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    tables: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    sections: list[str] = []

    for table_el in root.iter():
        if local_name(table_el.tag) != "table":
            continue
        sheet_name = None
        for attr_name, attr_value in table_el.attrib.items():
            if local_name(attr_name) == "name":
                sheet_name = attr_value
                break
        rows: list[list[str]] = []
        for row_el in table_el:
            if local_name(row_el.tag) != "table-row":
                continue
            cells: list[str] = []
            for cell_el in row_el:
                if local_name(cell_el.tag) != "table-cell":
                    continue
                cells.append("".join(cell_el.itertext()).strip())
            if len(rows) < MAX_ROWS_PER_SHEET:
                rows.append(cells)

        if sheet_name:
            sections.append(sheet_name)
        rendered = _render_rows_as_text(sheet_name or "", rows)
        if rendered:
            text_blocks.append(rendered)
        tables.append({"sheet": sheet_name, "headers": rows[0] if rows else [], "rows": rows[1:] if len(rows) > 1 else []})

    text = "\n\n".join(text_blocks).strip()

    return ExtractionResult(
        status=ExtractionStatus.LOCAL_TEXT,
        text=text,
        blocks=[line for block in text_blocks for line in block.splitlines() if line.strip()],
        tables=tables,
        sections=sections,
        source_extension=".ods",
        source_mime="application/vnd.oasis.opendocument.spreadsheet",
        extraction_provider="local_spreadsheet",
        warnings=[] if text else ["No data found in this spreadsheet."],
    )
