"""Unit tests for app/services/ingestion/adapters/image_adapter.py — EXIF
rotation normalization and format conversion before OCR (Part C3/L). No
DB/network required; images themselves still DEFER_TO_PROVIDER for OCR
(unchanged, untested here — see test_ingestion_router.py) — this only
covers the normalization step that runs before that handoff.
"""

from __future__ import annotations

from PIL import Image

from app.services.ingestion.adapters.image_adapter import normalize_image_for_ocr


def _save_with_exif_orientation(path, orientation: int) -> None:
    image = Image.new("RGB", (40, 20), color=(255, 0, 0))
    exif = image.getexif()
    exif[0x0112] = orientation  # the standard EXIF "Orientation" tag
    image.save(path, exif=exif)


def test_plain_jpeg_needs_no_normalization(tmp_path):
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (40, 20), color=(0, 255, 0)).save(path)

    result_path, warnings = normalize_image_for_ocr(path, ".jpg")

    assert result_path == path  # nothing needed — the original is used as-is
    assert warnings == []


def test_rotated_jpeg_gets_exif_transpose_applied(tmp_path):
    path = tmp_path / "rotated.jpg"
    # Orientation 6 = "rotate 270 CW to display correctly" — a very common
    # real value for a phone photo taken in portrait mode.
    _save_with_exif_orientation(path, orientation=6)

    result_path, warnings = normalize_image_for_ocr(path, ".jpg")

    assert result_path != path  # a new, normalized file was produced
    assert any("rotated" in w.lower() for w in warnings)
    with Image.open(result_path) as normalized:
        # The original was 40x20 (landscape); a 90-degree rotation baked
        # into the pixels makes it 20x40 (portrait) — proves the rotation
        # was actually applied to the pixel data, not just noted.
        assert normalized.size == (20, 40)
    result_path.unlink()


def test_bmp_is_converted_to_png_for_provider_compatibility(tmp_path):
    path = tmp_path / "scan.bmp"
    Image.new("RGB", (10, 10), color=(0, 0, 255)).save(path, format="BMP")

    result_path, warnings = normalize_image_for_ocr(path, ".bmp")

    assert result_path != path
    assert result_path.suffix == ".png"
    assert any("converted" in w.lower() for w in warnings)
    with Image.open(result_path) as normalized:
        assert normalized.format == "PNG"
    result_path.unlink()


def test_corrupt_image_falls_back_to_original_path_without_raising(tmp_path):
    path = tmp_path / "corrupt.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"not actually a real jpeg body")

    result_path, warnings = normalize_image_for_ocr(path, ".jpg")

    # Never raises — worst case, the original (unreadable) file is handed
    # back so the EXISTING OCR call fails normally on it, exactly as
    # before this session, rather than this normalization step itself
    # becoming a new, silent point of failure.
    assert result_path == path
    assert warnings  # explains why normalization was skipped
