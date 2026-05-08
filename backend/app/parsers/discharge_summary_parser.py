from typing import Any, Dict, Optional

from app.services.openai_discharge_service import process_discharge_with_openai


def parse_discharge_summary(
    file_path: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compatibility wrapper.

    Discharge parsing is now OpenAI-only.
    """

    return process_discharge_with_openai(
        file_path=file_path,
        filename=filename,
        content_type=content_type,
    )


def parse_discharge_document(
    file_path: str,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    return parse_discharge_summary(file_path, filename, content_type)


def parse_discharge_summary_text(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    raise RuntimeError(
        "Text-only discharge parsing has been disabled. "
        "Discharge summaries must be processed directly from the uploaded file with OpenAI."
    )