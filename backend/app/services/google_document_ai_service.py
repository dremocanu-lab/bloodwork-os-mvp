from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import fitz

from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.oauth2 import service_account


def get_env_value(name: str) -> str | None:
    value = os.getenv(name)

    if value is None:
        return None

    value = value.strip()
    return value or None


def get_document_ai_debug_config() -> dict[str, Any]:
    credentials_path = get_env_value("GOOGLE_APPLICATION_CREDENTIALS")
    credentials_json = get_env_value("GOOGLE_DOCUMENT_AI_CREDENTIALS_JSON")

    return {
        "project_id": get_env_value("GOOGLE_DOCUMENT_AI_PROJECT_ID"),
        "location": get_env_value("GOOGLE_DOCUMENT_AI_LOCATION"),
        "processor_id": get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_ID"),
        "processor_version": get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_VERSION"),
        "has_credentials_path": bool(credentials_path),
        "credentials_path_exists": bool(credentials_path and Path(credentials_path).exists()),
        "has_credentials_json_env": bool(credentials_json),
    }


def is_google_document_ai_configured() -> bool:
    return bool(
        get_env_value("GOOGLE_DOCUMENT_AI_PROJECT_ID")
        and get_env_value("GOOGLE_DOCUMENT_AI_LOCATION")
        and get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_ID")
    )


def get_document_ai_client(location: str):
    api_endpoint = f"{location}-documentai.googleapis.com"

    credentials_json = get_env_value("GOOGLE_DOCUMENT_AI_CREDENTIALS_JSON")
    credentials_path = get_env_value("GOOGLE_APPLICATION_CREDENTIALS")

    if credentials_json:
        try:
            credentials_info = json.loads(credentials_json)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"GOOGLE_DOCUMENT_AI_CREDENTIALS_JSON is not valid JSON: {error}") from error

        credentials = service_account.Credentials.from_service_account_info(credentials_info)

        return documentai.DocumentProcessorServiceClient(
            credentials=credentials,
            client_options=ClientOptions(api_endpoint=api_endpoint),
        )

    if credentials_path:
        path = Path(credentials_path)

        if not path.exists():
            raise RuntimeError(f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {credentials_path}")

        credentials = service_account.Credentials.from_service_account_file(str(path))

        return documentai.DocumentProcessorServiceClient(
            credentials=credentials,
            client_options=ClientOptions(api_endpoint=api_endpoint),
        )

    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=api_endpoint),
    )


def guess_mime_type(file_path: Path, filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename or str(file_path))

    if guessed:
        return guessed

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return "application/pdf"

    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"

    if suffix == ".png":
        return "image/png"

    if suffix in {".tif", ".tiff"}:
        return "image/tiff"

    if suffix == ".webp":
        return "image/webp"

    return "application/octet-stream"


def layout_to_text(layout, full_text: str) -> str:
    if not layout or not layout.text_anchor:
        return ""

    parts: list[str] = []

    for segment in layout.text_anchor.text_segments:
        start = int(segment.start_index) if segment.start_index else 0
        end = int(segment.end_index) if segment.end_index else 0

        if end > start:
            parts.append(full_text[start:end])

    return "".join(parts).strip()


def clean_inline_text(value: str | None) -> str:
    if not value:
        return ""

    cleaned = str(value)
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = cleaned.replace("｜", "|")
    cleaned = cleaned.replace("＃", "#")
    cleaned = cleaned.replace("％", "%")
    cleaned = " ".join(cleaned.split())

    return cleaned.strip()


def clean_block_text(value: str | None) -> str:
    if not value:
        return ""

    cleaned = str(value)
    cleaned = cleaned.replace("\ufeff", "")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    cleaned = cleaned.replace("｜", "|")
    cleaned = cleaned.replace("＃", "#")
    cleaned = cleaned.replace("％", "%")

    lines: list[str] = []

    for line in cleaned.splitlines():
        line = " ".join(line.split()).strip()

        if line:
            lines.append(line)

    return "\n".join(lines).strip()


def get_page_dimensions(page) -> tuple[float, float]:
    width = 1.0
    height = 1.0

    if page.dimension:
        if page.dimension.width:
            width = float(page.dimension.width)
        if page.dimension.height:
            height = float(page.dimension.height)

    return width, height


def bounding_poly_to_box(layout, page_width: float, page_height: float) -> dict[str, float]:
    if not layout or not layout.bounding_poly:
        return {
            "left": 0.0,
            "top": 0.0,
            "width": 1.0,
            "height": 1.0,
        }

    vertices: list[tuple[float, float]] = []

    if layout.bounding_poly.normalized_vertices:
        for vertex in layout.bounding_poly.normalized_vertices:
            vertices.append(
                (
                    float(vertex.x or 0) * page_width,
                    float(vertex.y or 0) * page_height,
                )
            )
    elif layout.bounding_poly.vertices:
        for vertex in layout.bounding_poly.vertices:
            vertices.append(
                (
                    float(vertex.x or 0),
                    float(vertex.y or 0),
                )
            )

    if not vertices:
        return {
            "left": 0.0,
            "top": 0.0,
            "width": 1.0,
            "height": 1.0,
        }

    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]

    left = min(xs)
    top = min(ys)
    right = max(xs)
    bottom = max(ys)

    return {
        "left": left,
        "top": top,
        "width": max(right - left, 1.0),
        "height": max(bottom - top, 1.0),
    }


def extract_tokens_from_document(document) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    full_text = document.text or ""

    for page_index, page in enumerate(document.pages or []):
        page_width, page_height = get_page_dimensions(page)

        for token_index, token in enumerate(page.tokens or []):
            token_text = layout_to_text(token.layout, full_text)
            token_text = clean_inline_text(token_text)

            if not token_text:
                continue

            box = bounding_poly_to_box(
                token.layout,
                page_width=page_width,
                page_height=page_height,
            )

            try:
                confidence = float(token.layout.confidence or 0)
            except Exception:
                confidence = 0.0

            words.append(
                {
                    "text": token_text,
                    "confidence": confidence,
                    "conf": confidence * 100,
                    "left": box["left"],
                    "top": box["top"],
                    "width": box["width"],
                    "height": box["height"],
                    "page": page_index,
                    "token_index": token_index,
                    "provider": "google_document_ai",
                }
            )

    return words


def extract_lines_from_document(document) -> list[dict[str, Any]]:
    full_text = document.text or ""
    lines: list[dict[str, Any]] = []

    for page_index, page in enumerate(document.pages or []):
        page_width, page_height = get_page_dimensions(page)

        for line_index, line in enumerate(page.lines or []):
            line_text = layout_to_text(line.layout, full_text)
            line_text = clean_inline_text(line_text)

            if not line_text:
                continue

            box = bounding_poly_to_box(
                line.layout,
                page_width=page_width,
                page_height=page_height,
            )

            try:
                confidence = float(line.layout.confidence or 0)
            except Exception:
                confidence = 0.0

            lines.append(
                {
                    "page": page_index,
                    "line_index": line_index,
                    "text": line_text,
                    "confidence": confidence,
                    **box,
                }
            )

    return lines


def extract_tables_from_document(document) -> list[dict[str, Any]]:
    full_text = document.text or ""
    tables: list[dict[str, Any]] = []

    for page_index, page in enumerate(document.pages or []):
        page_width, page_height = get_page_dimensions(page)

        for table_index, table in enumerate(page.tables or []):
            parsed_rows: list[dict[str, Any]] = []

            source_rows = []

            for header_row in table.header_rows or []:
                source_rows.append(("header", header_row))

            for body_row in table.body_rows or []:
                source_rows.append(("body", body_row))

            for row_index, (row_type, row) in enumerate(source_rows):
                parsed_cells: list[dict[str, Any]] = []

                for cell_index, cell in enumerate(row.cells or []):
                    cell_text = layout_to_text(cell.layout, full_text)
                    cell_text = clean_inline_text(cell_text)

                    box = bounding_poly_to_box(
                        cell.layout,
                        page_width=page_width,
                        page_height=page_height,
                    )

                    try:
                        confidence = float(cell.layout.confidence or 0)
                    except Exception:
                        confidence = 0.0

                    parsed_cells.append(
                        {
                            "cell_index": cell_index,
                            "text": cell_text,
                            "confidence": confidence,
                            "row_span": int(cell.row_span or 1),
                            "col_span": int(cell.col_span or 1),
                            **box,
                        }
                    )

                if parsed_cells:
                    parsed_rows.append(
                        {
                            "row_index": row_index,
                            "row_type": row_type,
                            "cells": parsed_cells,
                        }
                    )

            if parsed_rows:
                tables.append(
                    {
                        "page": page_index,
                        "table_index": table_index,
                        "rows": parsed_rows,
                    }
                )

    return tables


def render_tables_as_text(tables: list[dict[str, Any]]) -> str:
    blocks: list[str] = []

    for table in tables:
        blocks.append(
            f"--- GOOGLE DOCUMENT AI TABLE page={table['page'] + 1} table={table['table_index'] + 1} ---"
        )

        for row in table.get("rows", []):
            cells = [cell.get("text", "") for cell in row.get("cells", [])]
            cells = [clean_inline_text(cell) for cell in cells]
            blocks.append(" | ".join(cells))

    return "\n".join(blocks).strip()


def render_lines_as_text(lines: list[dict[str, Any]]) -> str:
    ordered = sorted(
        lines or [],
        key=lambda item: (
            int(item.get("page", 0)),
            float(item.get("top", 0)),
            float(item.get("left", 0)),
        ),
    )

    return "\n".join(line["text"] for line in ordered if line.get("text")).strip()


def render_tokens_as_text(words: list[dict[str, Any]]) -> str:
    ordered = sorted(
        words or [],
        key=lambda item: (
            int(item.get("page", 0)),
            float(item.get("top", 0)),
            float(item.get("left", 0)),
        ),
    )

    return " ".join(word["text"] for word in ordered if word.get("text")).strip()

def should_render_pdf_for_google(file_path: Path, mime_type: str) -> bool:
    if mime_type != "application/pdf":
        return False

    if file_path.suffix.lower() != ".pdf":
        return False

    value = get_env_value("GOOGLE_DOCUMENT_AI_RENDER_PDFS")

    if value is None:
        return True

    return value.lower() not in {"0", "false", "no", "off"}


def get_render_dpi() -> int:
    raw_value = get_env_value("GOOGLE_DOCUMENT_AI_RENDER_DPI")

    if not raw_value:
        return 350

    try:
        dpi = int(raw_value)
    except Exception:
        return 350

    return max(200, min(dpi, 450))


def render_pdf_pages_to_png_bytes(file_path: Path, dpi: int) -> list[bytes]:
    rendered_pages: list[bytes] = []

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(str(file_path)) as pdf:
        for page in pdf:
            pixmap = page.get_pixmap(
                matrix=matrix,
                alpha=False,
                colorspace=fitz.csRGB,
            )

            rendered_pages.append(pixmap.tobytes("png"))

    return rendered_pages


def process_single_google_document(
    client,
    name: str,
    file_content: bytes,
    mime_type: str,
):
    raw_document = documentai.RawDocument(
        content=file_content,
        mime_type=mime_type,
    )

    try:
        process_options = documentai.ProcessOptions(
            ocr_config=documentai.OcrConfig(
                enable_native_pdf_parsing=True,
                enable_image_quality_scores=True,
                enable_symbol=False,
            )
        )

        request = documentai.ProcessRequest(
            name=name,
            raw_document=raw_document,
            process_options=process_options,
        )
    except Exception:
        request = documentai.ProcessRequest(
            name=name,
            raw_document=raw_document,
        )

    result = client.process_document(request=request)
    return result.document


def extraction_from_google_document(
    document,
    method: str,
    mime_type: str,
    warnings: list[str] | None = None,
    debug_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plain_text = clean_block_text(document.text or "")
    tables = extract_tables_from_document(document)
    lines = extract_lines_from_document(document)
    words = extract_tokens_from_document(document)

    table_text = render_tables_as_text(tables)
    lines_text = render_lines_as_text(lines)
    tokens_text = render_tokens_as_text(words)

    combined_parts: list[str] = []

    if plain_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI PLAIN TEXT ---")
        combined_parts.append(plain_text)

    if lines_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI LINES ---")
        combined_parts.append(lines_text)

    if table_text:
        combined_parts.append(table_text)

    if tokens_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI TOKENS ---")
        combined_parts.append(tokens_text)

    combined_text = "\n".join(combined_parts).strip()

    return {
        "text": combined_text,
        "plain_text": plain_text,
        "lines_text": lines_text,
        "table_text": table_text,
        "tokens_text": tokens_text,
        "tables": tables,
        "lines": lines,
        "words": words,
        "method": method,
        "warnings": warnings or ["Google Document AI extraction was used."],
        "debug": {
            "table_count": len(tables),
            "line_count": len(lines),
            "token_count": len(words),
            "mime_type": mime_type,
            "config": get_document_ai_debug_config(),
            **(debug_extra or {}),
        },
    }


def shift_extraction_page_indexes(extraction: dict[str, Any], page_offset: int) -> dict[str, Any]:
    if page_offset <= 0:
        return extraction

    for table in extraction.get("tables") or []:
        table["page"] = int(table.get("page") or 0) + page_offset

    for line in extraction.get("lines") or []:
        line["page"] = int(line.get("page") or 0) + page_offset

    for word in extraction.get("words") or []:
        word["page"] = int(word.get("page") or 0) + page_offset

    return extraction


def combine_google_page_extractions(
    page_extractions: list[dict[str, Any]],
    original_mime_type: str,
    dpi: int,
) -> dict[str, Any]:
    plain_parts: list[str] = []
    line_parts: list[str] = []
    table_parts: list[str] = []
    token_parts: list[str] = []
    tables: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []

    warnings: list[str] = [
        f"Google Document AI extraction was used after rendering PDF pages at {dpi} DPI."
    ]

    for page_number, extraction in enumerate(page_extractions, start=1):
        plain_text = extraction.get("plain_text") or ""
        lines_text = extraction.get("lines_text") or ""
        table_text = extraction.get("table_text") or ""
        tokens_text = extraction.get("tokens_text") or ""

        if plain_text:
            plain_parts.append(f"--- RENDERED PAGE {page_number} ---")
            plain_parts.append(plain_text)

        if lines_text:
            line_parts.append(f"--- RENDERED PAGE {page_number} ---")
            line_parts.append(lines_text)

        if table_text:
            table_parts.append(f"--- RENDERED PAGE {page_number} ---")
            table_parts.append(table_text)

        if tokens_text:
            token_parts.append(f"--- RENDERED PAGE {page_number} ---")
            token_parts.append(tokens_text)

        tables.extend(extraction.get("tables") or [])
        lines.extend(extraction.get("lines") or [])
        words.extend(extraction.get("words") or [])

    plain_text = "\n".join(plain_parts).strip()
    lines_text = "\n".join(line_parts).strip()
    table_text = "\n".join(table_parts).strip()
    tokens_text = "\n".join(token_parts).strip()

    combined_parts: list[str] = []

    if plain_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI PLAIN TEXT ---")
        combined_parts.append(plain_text)

    if lines_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI LINES ---")
        combined_parts.append(lines_text)

    if table_text:
        combined_parts.append(table_text)

    if tokens_text:
        combined_parts.append("--- GOOGLE DOCUMENT AI TOKENS ---")
        combined_parts.append(tokens_text)

    combined_text = "\n".join(combined_parts).strip()

    return {
        "text": combined_text,
        "plain_text": plain_text,
        "lines_text": lines_text,
        "table_text": table_text,
        "tokens_text": tokens_text,
        "tables": tables,
        "lines": lines,
        "words": words,
        "method": "google_document_ai_rendered_pdf",
        "warnings": warnings,
        "debug": {
            "table_count": len(tables),
            "line_count": len(lines),
            "token_count": len(words),
            "mime_type": original_mime_type,
            "rendered_pdf": True,
            "render_dpi": dpi,
            "rendered_pages": len(page_extractions),
            "config": get_document_ai_debug_config(),
        },
    }

def process_with_google_document_ai(file_path: Path, filename: str) -> dict[str, Any]:
    project_id = get_env_value("GOOGLE_DOCUMENT_AI_PROJECT_ID")
    location = get_env_value("GOOGLE_DOCUMENT_AI_LOCATION") or "eu"
    processor_id = get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_ID")
    processor_version = get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_VERSION")

    if not project_id or not processor_id:
        raise RuntimeError("Google Document AI is not configured. Missing project ID or processor ID.")

    client = get_document_ai_client(location)

    if processor_version:
        name = client.processor_version_path(
            project_id,
            location,
            processor_id,
            processor_version,
        )
    else:
        name = client.processor_path(
            project_id,
            location,
            processor_id,
        )

    mime_type = guess_mime_type(file_path, filename)

    if should_render_pdf_for_google(file_path, mime_type):
        dpi = get_render_dpi()

        try:
            rendered_pages = render_pdf_pages_to_png_bytes(file_path, dpi=dpi)
            page_extractions: list[dict[str, Any]] = []

            for page_offset, rendered_content in enumerate(rendered_pages):
                document = process_single_google_document(
                    client=client,
                    name=name,
                    file_content=rendered_content,
                    mime_type="image/png",
                )

                extraction = extraction_from_google_document(
                    document=document,
                    method="google_document_ai_rendered_pdf_page",
                    mime_type="image/png",
                    warnings=[
                        f"Google Document AI extraction was used on rendered PDF page {page_offset + 1}."
                    ],
                    debug_extra={
                        "rendered_pdf": True,
                        "render_dpi": dpi,
                        "rendered_page_number": page_offset + 1,
                    },
                )

                extraction = shift_extraction_page_indexes(extraction, page_offset)
                page_extractions.append(extraction)

            if page_extractions:
                return combine_google_page_extractions(
                    page_extractions=page_extractions,
                    original_mime_type=mime_type,
                    dpi=dpi,
                )

        except Exception as error:
            with file_path.open("rb") as file:
                file_content = file.read()

            document = process_single_google_document(
                client=client,
                name=name,
                file_content=file_content,
                mime_type=mime_type,
            )

            return extraction_from_google_document(
                document=document,
                method="google_document_ai",
                mime_type=mime_type,
                warnings=[
                    "Google Document AI extraction was used.",
                    (
                        "PDF high-resolution rendering failed; Google Document AI used the original file. "
                        f"Error: {error}"
                    ),
                ],
                debug_extra={
                    "rendered_pdf": False,
                    "render_failed": True,
                    "render_error": str(error),
                },
            )

    with file_path.open("rb") as file:
        file_content = file.read()

    document = process_single_google_document(
        client=client,
        name=name,
        file_content=file_content,
        mime_type=mime_type,
    )

    return extraction_from_google_document(
        document=document,
        method="google_document_ai",
        mime_type=mime_type,
        warnings=["Google Document AI extraction was used."],
        debug_extra={
            "rendered_pdf": False,
        },
    )