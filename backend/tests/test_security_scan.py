"""Unit tests for app/services/security_scan.py — no DB required. See
BRAGI_SECURITY_GDPR_PLAN.md §10/Priority 9 and
docs/security/MALWARE_SCANNING_PLAN.md.
"""

import fitz
import pytest

from app.services import security_scan
from app.services.security_scan import (
    PROVIDER_HEURISTIC,
    VERDICT_CLEAN,
    VERDICT_INFECTED,
    VERDICT_SCAN_UNAVAILABLE,
    run_security_scan,
)


def _make_plain_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Synthetic clinical report — no active content.")
    doc.save(str(path))
    doc.close()


def _make_pdf_with_launch_action(path):
    doc = fitz.open()
    doc.new_page()
    catalog_xref = doc.pdf_catalog()
    doc.xref_set_key(catalog_xref, "OpenAction", "<</S/Launch/F(calc.exe)>>")
    doc.save(str(path))
    doc.close()


def _make_pdf_with_dangerous_embedded_file(path):
    doc = fitz.open()
    doc.new_page()
    doc.embfile_add("payload.exe", b"MZ-fake-executable-bytes-for-testing")
    doc.save(str(path))
    doc.close()


def test_clean_pdf_with_no_scanner_configured_is_scan_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    pdf_path = tmp_path / "clean.pdf"
    _make_plain_pdf(pdf_path)

    result = run_security_scan(pdf_path)

    assert result.verdict == VERDICT_SCAN_UNAVAILABLE
    assert result.provider == PROVIDER_HEURISTIC
    assert not result.blocks_processing


def test_pdf_with_launch_action_is_infected(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    pdf_path = tmp_path / "launch.pdf"
    _make_pdf_with_launch_action(pdf_path)

    result = run_security_scan(pdf_path)

    assert result.verdict == VERDICT_INFECTED
    assert result.provider == PROVIDER_HEURISTIC
    assert result.blocks_processing
    assert "Launch" in result.reason


def test_pdf_with_dangerous_embedded_file_is_infected(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    pdf_path = tmp_path / "embedded.pdf"
    _make_pdf_with_dangerous_embedded_file(pdf_path)

    result = run_security_scan(pdf_path)

    assert result.verdict == VERDICT_INFECTED
    assert result.provider == PROVIDER_HEURISTIC
    assert result.blocks_processing
    assert ".exe" in result.reason


def test_non_pdf_file_is_scan_unavailable_not_infected(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    png_path = tmp_path / "image.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")

    result = run_security_scan(png_path)

    assert result.verdict == VERDICT_SCAN_UNAVAILABLE
    assert not result.blocks_processing


def test_scan_unavailable_never_blocks_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"%PDF-1.4 not actually a valid pdf structure at all")

    result = run_security_scan(corrupt_path)

    assert result.verdict == VERDICT_SCAN_UNAVAILABLE
    assert not result.blocks_processing


def test_clamav_configured_but_unreachable_falls_back_to_heuristic(tmp_path, monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setattr(security_scan, "CLAMAV_PORT", 1)  # nothing listens here
    pdf_path = tmp_path / "launch.pdf"
    _make_pdf_with_launch_action(pdf_path)

    result = run_security_scan(pdf_path)

    # Falls back to the heuristic screen rather than crashing or silently
    # claiming a clean AV result it never actually got.
    assert result.provider == PROVIDER_HEURISTIC
    assert result.verdict == VERDICT_INFECTED


def test_is_real_scanner_configured_reflects_env(monkeypatch):
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", None)
    assert security_scan.is_real_scanner_configured() is False
    monkeypatch.setattr(security_scan, "CLAMAV_HOST", "clamav.internal")
    assert security_scan.is_real_scanner_configured() is True
