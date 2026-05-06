import json
import os
from typing import Any, Dict, List, Optional

from google.cloud import documentai
from google.oauth2 import service_account


def _get_document_ai_client() -> documentai.DocumentProcessorServiceClient:
    credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    location = os.getenv("GOOGLE_DOCUMENT_AI_LOCATION", "eu")

    client_options = {
        "api_endpoint": f"{location}-documentai.googleapis.com",
    }

    if credentials_json:
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)

        return documentai.DocumentProcessorServiceClient(
            credentials=credentials,
            client_options=client_options,
        )

    return documentai.DocumentProcessorServiceClient(client_options=client_options)


def _text_from_anchor(full_text: str, text_anchor: Optional[Any]) -> str:
    if not text_anchor or not getattr(text_anchor, "text_segments", None):
        return ""

    pieces: List[str] = []

    for segment in text_anchor.text_segments:
        start = int(segment.start_index or 0)
        end = int(segment.end_index or 0)
        pieces.append(full_text[start:end])

    return "".join(pieces).strip()


def _box_from_layout(layout: Any, page_width: float, page_height: float) -> Dict[str, float]:
    polygon = getattr(layout, "bounding_poly", None)

    if not polygon:
        return {"x": 0, "y": 0, "w": 0, "h": 0}

    if getattr(polygon, "normalized_vertices", None):
        xs = [float(vertex.x or 0) * page_width for vertex in polygon.normalized_vertices]
        ys = [float(vertex.y or 0) * page_height for vertex in polygon.normalized_vertices]
    elif getattr(polygon, "vertices", None):
        xs = [float(vertex.x or 0) for vertex in polygon.vertices]
        ys = [float(vertex.y or 0) for vertex in polygon.vertices]
    else:
        return {"x": 0, "y": 0, "w": 0, "h": 0}

    if not xs or not ys:
        return {"x": 0, "y": 0, "w": 0, "h": 0}

    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)

    return {
        "x": round(min_x, 2),
        "y": round(min_y, 2),
        "w": round(max_x - min_x, 2),
        "h": round(max_y - min_y, 2),
    }


def _extract_paragraph_blocks(full_text: str, page: Any, page_width: float, page_height: float) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []

    for index, paragraph in enumerate(getattr(page, "paragraphs", []) or []):
        layout = paragraph.layout
        text = _text_from_anchor(full_text, layout.text_anchor)

        if not text:
            continue

        box = _box_from_layout(layout, page_width, page_height)

        blocks.append(
            {
                "id": f"p-{index}",
                "type": "paragraph",
                "text": text,
                **box,
            }
        )

    return blocks


def _extract_line_blocks_from_tokens(full_text: str, page: Any, page_width: float, page_height: float) -> List[Dict[str, Any]]:
    tokens: List[Dict[str, Any]] = []

    for token in getattr(page, "tokens", []) or []:
        layout = token.layout
        text = _text_from_anchor(full_text, layout.text_anchor)

        if not text:
            continue

        box = _box_from_layout(layout, page_width, page_height)

        if box["w"] <= 0 or box["h"] <= 0:
            continue

        tokens.append(
            {
                "text": text,
                "x": box["x"],
                "y": box["y"],
                "w": box["w"],
                "h": box["h"],
                "center_y": box["y"] + box["h"] / 2,
            }
        )

    tokens.sort(key=lambda item: (item["center_y"], item["x"]))

    grouped_lines: List[List[Dict[str, Any]]] = []

    for token in tokens:
        placed = False

        for line in grouped_lines:
            avg_y = sum(item["center_y"] for item in line) / len(line)
            avg_height = sum(item["h"] for item in line) / len(line)
            tolerance = max(4.5, avg_height * 0.55)

            if abs(token["center_y"] - avg_y) <= tolerance:
                line.append(token)
                placed = True
                break

        if not placed:
            grouped_lines.append([token])

    line_blocks: List[Dict[str, Any]] = []

    for line_index, line in enumerate(grouped_lines):
        line.sort(key=lambda item: item["x"])

        text_parts: List[str] = []

        for token_index, token in enumerate(line):
            token_text = token["text"]

            if token_index == 0:
                text_parts.append(token_text)
                continue

            previous = line[token_index - 1]
            previous_right = previous["x"] + previous["w"]
            gap = token["x"] - previous_right
            average_height = (previous["h"] + token["h"]) / 2

            if gap > max(2.2, average_height * 0.18):
                text_parts.append(" ")

            text_parts.append(token_text)

        text = "".join(text_parts).strip()

        if not text:
            continue

        x = min(item["x"] for item in line)
        y = min(item["y"] for item in line)
        right = max(item["x"] + item["w"] for item in line)
        bottom = max(item["y"] + item["h"] for item in line)

        line_blocks.append(
            {
                "id": f"l-{line_index}",
                "type": "line",
                "text": text,
                "x": round(x, 2),
                "y": round(y, 2),
                "w": round(right - x, 2),
                "h": round(bottom - y, 2),
            }
        )

    return line_blocks


def process_document_with_layout(file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    location = os.getenv("GOOGLE_DOCUMENT_AI_LOCATION", "eu")
    processor_id = os.getenv("GOOGLE_DOCUMENT_AI_PROCESSOR_ID")

    if not project_id or not processor_id:
        raise RuntimeError(
            "Google Document AI is not configured. Missing GOOGLE_CLOUD_PROJECT_ID or GOOGLE_DOCUMENT_AI_PROCESSOR_ID."
        )

    client = _get_document_ai_client()
    processor_name = client.processor_path(project_id, location, processor_id)

    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=documentai.RawDocument(
            content=file_bytes,
            mime_type=mime_type,
        ),
    )

    result = client.process_document(request=request)
    document = result.document
    full_text = document.text or ""

    pages: List[Dict[str, Any]] = []

    for page_index, page in enumerate(document.pages):
        dimension = page.dimension
        page_width = float(dimension.width or 1)
        page_height = float(dimension.height or 1)

        paragraph_blocks = _extract_paragraph_blocks(full_text, page, page_width, page_height)
        line_blocks = _extract_line_blocks_from_tokens(full_text, page, page_width, page_height)

        pages.append(
            {
                "page_number": page_index + 1,
                "width": page_width,
                "height": page_height,
                "paragraph_blocks": paragraph_blocks,
                "line_blocks": line_blocks,
            }
        )

    return {
        "provider": "google_document_ai",
        "plain_text": full_text,
        "pages": pages,
    }