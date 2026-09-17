"""Image normalization before handing a file to the OCR provider
(Google Document AI, via app/services/ocr_service.py — unchanged). This
adapter does NOT do OCR itself — images stay ExtractionStatus.
DEFER_TO_PROVIDER (see router.py) — it only fixes two real, common
problems that would otherwise silently reach the provider wrong:

1. EXIF rotation: a phone photo is very often stored "sideways" with an
   EXIF orientation tag telling a viewer how to rotate it for display —
   a provider reading raw pixel data without respecting that tag sees a
   rotated image. Baking the rotation into the actual pixels once, here,
   makes every downstream consumer (OCR, the source viewer) agree.
2. Formats Google Document AI's raw-bytes API doesn't reliably accept
   (HEIC/HEIF — common for iPhone photos — and BMP) are converted to PNG
   (lossless) before the provider ever sees them.

Returns the ORIGINAL file path unchanged when no normalization is
needed (the common case — most uploaded JPEG/PNG/TIFF/WebP need
nothing) so callers never pay a re-encode cost for nothing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

_FORMATS_REQUIRING_CONVERSION = {".heic", ".heif", ".bmp"}


def normalize_image_for_ocr(file_path: Path, extension: str) -> tuple[Path, list[str]]:
    """Returns (path_to_use, warnings). `path_to_use` is either
    `file_path` itself (nothing needed) or a NEW temporary file the
    caller is responsible for cleaning up once OCR has read it."""
    warnings: list[str] = []

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return file_path, ["Image normalization library unavailable — sending the original file as-is."]

    needs_format_conversion = extension in _FORMATS_REQUIRING_CONVERSION

    if extension in {".heic", ".heif"}:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:
            return file_path, ["HEIC/HEIF support is unavailable in this environment — the original file will likely fail OCR."]

    try:
        with Image.open(file_path) as image:
            # PIL.ImageOps.exif_transpose() always returns a NEW image
            # object (never the same instance, even when no rotation is
            # actually needed) — checking the real EXIF orientation tag
            # value directly is the only reliable way to know whether a
            # rotation fix is actually required, rather than assuming
            # every call produced one.
            orientation = image.getexif().get(0x0112, 1)
            needs_rotation_fix = orientation not in (0, 1)
            transposed = ImageOps.exif_transpose(image) if needs_rotation_fix else image

            if not needs_rotation_fix and not needs_format_conversion:
                return file_path, warnings

            rgb_image = transposed.convert("RGB") if transposed.mode not in ("RGB", "L") else transposed
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = Path(tmp.name)
            tmp.close()
            rgb_image.save(tmp_path, format="PNG")

            if needs_rotation_fix:
                warnings.append("Image was rotated based on its embedded orientation data before processing.")
            if needs_format_conversion:
                warnings.append(f"Image was converted from {extension} to PNG for processing.")

            return tmp_path, warnings
    except Exception as error:  # noqa: BLE001 — a genuinely corrupt/unreadable image; let the existing OCR call fail normally on the original file rather than masking this
        return file_path, [f"Image normalization skipped due to an error ({error}); attempting OCR on the original file."]
