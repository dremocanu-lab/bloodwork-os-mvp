import json
import mimetypes
import os
from pathlib import Path

from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.oauth2 import service_account


def get_env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


def is_google_document_ai_configured() -> bool:
    return bool(
        get_env_value("GOOGLE_DOCUMENT_AI_PROJECT_ID")
        and get_env_value("GOOGLE_DOCUMENT_AI_LOCATION")
        and get_env_value("GOOGLE_DOCUMENT_AI_PROCESSOR_ID")
    )


def get_document_ai_debug_config() -> dict:
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


def get_document_ai_client(location: str):
    api_endpoint = f"{location}-documentai.googleapis.com"

    credentials_json = get_env_value("GOOGLE_DOCUMENT_AI_CREDENTIALS_JSON")
    credentials_path = get_env_value("GOOGLE_APPLICATION_CREDENTIALS")

    if credentials_json:
        credentials_info = json.loads(credentials_json)
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

    parts = []

    for segment in layout.text_anchor.text_segments:
        start = int(segment.start_index) if segment.start_index else 0
        end = int(segment.end_index) if segment.end_index else 0
        parts.append(full_text[start:end])

    return "".join(parts).strip()


def get_page_dimensions(page) -> tuple[float, float]:
    width = 1.0
    height = 1.0

    if page.dimension:
        if page.dimension.width:
            width = float(page.dimension.width)
        if page.dimension.height:
            height = float(page.dimension.height)

    return width, height


def bounding_poly_to_box(layout, page_width: float, page_height: float) -> tuple[int, int, int, int]:
    if not layout or not layout.bounding_poly:
        return 0, 0, 1, 1

    vertices = []

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
        return 0, 0, 1, 1

    xs = [item[0] for item in vertices]
    ys = [item[1] for item in vertices]

    left = int(min(xs))
    top = int(min(ys))
    right = int(max(xs))
    bottom = int(max(ys))

    width = max(right - left, 1)
    height = max(bottom - top, 1)

    return left, top, width, height


def extract_tokens_from_document(document) -> list[dict]:
    words: list[dict] = []
    full_text = document.text or ""

    for page_index, page in enumerate(document.pages or []):
        page_width, page_height = get_page_dimensions(page)

        for token_index, token in enumerate(page.tokens or []):
            token_text = layout_to_text(token.layout, full_text)

            if not token_text:
                continue

            left, top, width, height = bounding_poly_to_box(
                token.layout,
                page_width=page_width,
                page_height=page_height,
            )

            try:
                confidence = float(token.layout.confidence or 0) * 100
            except Exception:
                confidence = 0.0

            words.append(
                {
                    "text": token_text,
                    "conf": confidence,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "page": page_index,
                    "block_num": 0,
                    "par_num": 0,
                    "line_num": 0,
                    "word_num": token_index,
                    "ocr_config": "google_document_ai",
                }
            )

    return words


def extract_lines_from_document(document) -> str:
    full_text = document.text or ""
    lines: list[str] = []

    for page in document.pages or []:
        for line in page.lines or []:
            text = layout_to_text(line.layout, full_text)
            if text:
                lines.append(text)

    return "\n".join(lines).strip()


def extract_tables_from_document(document) -> str:
    full_text = document.text or ""
    table_lines: list[str] = []

    for page_number, page in enumerate(document.pages or [], start=1):
        for table_index, table in enumerate(page.tables or [], start=1):
            table_lines.append(f"--- GOOGLE DOCUMENT AI TABLE page={page_number} table={table_index} ---")

            all_rows = []
            all_rows.extend(table.header_rows or [])
            all_rows.extend(table.body_rows or [])

            for row in all_rows:
                cells = []

                for cell in row.cells or []:
                    cell_text = layout_to_text(cell.layout, full_text)
                    cell_text = " ".join(cell_text.split())
                    cells.append(cell_text)

                if cells:
                    table_lines.append(" | ".join(cells))

    return "\n".join(table_lines).strip()


def process_with_google_document_ai(file_path: Path, filename: str) -> dict:
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

    with file_path.open("rb") as file:
        file_content = file.read()

    process_options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            enable_native_pdf_parsing=True,
            enable_image_quality_scores=True,
            enable_symbol=False,
        )
    )

    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(
            content=file_content,
            mime_type=mime_type,
        ),
        process_options=process_options,
    )

    result = client.process_document(request=request)
    document = result.document

    document_text = document.text or ""
    document_lines = extract_lines_from_document(document)
    table_text = extract_tables_from_document(document)
    words = extract_tokens_from_document(document)

    combined_parts = []

    if document_text:
        combined_parts.append(document_text)

    if document_lines:
        combined_parts.append("--- GOOGLE DOCUMENT AI LINES ---")
        combined_parts.append(document_lines)

    if table_text:
        combined_parts.append(table_text)

    combined_text = "\n".join(combined_parts).strip()

    return {
        "text": combined_text,
        "words": words,
        "method": "google_document_ai",
        "warnings": ["Google Document AI OCR/layout extraction was used."],
    }