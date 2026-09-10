"""Upload security-scan pipeline boundary.

    upload -> security_scan -> accepted | security_quarantined -> Reducto/
    clinical processing

See `docs/security/MALWARE_SCANNING_PLAN.md` for the full design
rationale and `docs/security/RATE_LIMITING.md`'s Redis pattern, which
this module follows for the same reason: an external scanner is
configured behind an env var, safely defaults to an always-available
fallback when not configured, and is never silently described as
something it isn't.

**Honesty rule this module exists to enforce**: a verdict is only ever
labeled `provider="clamav"` (a real antivirus engine) when
`CLAMAV_HOST` is actually configured and reachable. Every other case is
labeled `provider="heuristic_screen"` and the word "malware scanning" is
never used for it in code, logs, or any API response — it is a narrow,
conservative structural check for the most unambiguous malicious-intent
markers in a PDF (an auto-launch action, an embedded executable), not a
substitute for real antivirus. `docs/security/MALWARE_SCANNING_PLAN.md`
tracks vendor selection for a real scanner as `[EXTERNAL ACTION]`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CLAMAV_HOST = os.getenv("CLAMAV_HOST")
CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))

# Extensions that have no legitimate reason to be embedded inside a
# clinical PDF (a lab report, discharge summary, etc.) — an embedded file
# with one of these is treated as unambiguous malicious intent, not a
# false-positive-prone guess.
_DANGEROUS_EMBEDDED_EXTENSIONS = (
    ".exe", ".scr", ".bat", ".cmd", ".com", ".js", ".vbs", ".jar", ".ps1", ".msi", ".dll", ".hta",
)

VERDICT_CLEAN = "clean"
VERDICT_INFECTED = "infected"
VERDICT_SCAN_UNAVAILABLE = "scan_unavailable"

PROVIDER_CLAMAV = "clamav"
PROVIDER_HEURISTIC = "heuristic_screen"


@dataclass
class ScanResult:
    verdict: str  # VERDICT_CLEAN | VERDICT_INFECTED | VERDICT_SCAN_UNAVAILABLE
    provider: str  # PROVIDER_CLAMAV | PROVIDER_HEURISTIC
    reason: str | None = None

    @property
    def blocks_processing(self) -> bool:
        """Only a positive verdict blocks the file from reaching
        Reducto/OpenAI/legacy processing — `scan_unavailable` (no real
        scanner configured, or a heuristic check that found nothing
        within its narrow scope) deliberately does NOT block, so uploads
        keep working exactly as before in every environment that hasn't
        configured a real scanner. This is the one place that decision
        is made — never re-implemented ad hoc at a call site."""
        return self.verdict == VERDICT_INFECTED


def is_real_scanner_configured() -> bool:
    return bool(CLAMAV_HOST)


def _scan_with_clamav(file_path: Path) -> ScanResult:
    try:
        import clamd  # local import: only required when CLAMAV_HOST is set

        client = clamd.ClamdNetworkSocket(host=CLAMAV_HOST, port=CLAMAV_PORT, timeout=30)
        with open(file_path, "rb") as fh:
            result = client.instream(fh)
        status, signature = result.get("stream", (None, None))
        if status == "FOUND":
            return ScanResult(verdict=VERDICT_INFECTED, provider=PROVIDER_CLAMAV, reason=signature)
        return ScanResult(verdict=VERDICT_CLEAN, provider=PROVIDER_CLAMAV)
    except Exception as exc:
        # Fail safe, not fail open on the verdict's honesty: if the
        # configured scanner is unreachable, we do NOT pretend a real AV
        # scan happened. Fall back to the heuristic screen (still real
        # protection against the most obvious markers) and log loudly so
        # an unreachable ClamAV doesn't silently degrade forever.
        print(f"SECURITY SCAN: ClamAV at {CLAMAV_HOST}:{CLAMAV_PORT} unreachable/errored ({exc}); falling back to heuristic screen.")
        return _heuristic_screen(file_path)


def _heuristic_screen(file_path: Path) -> ScanResult:
    suffix = file_path.suffix.lower()
    if suffix != ".pdf":
        return ScanResult(
            verdict=VERDICT_SCAN_UNAVAILABLE,
            provider=PROVIDER_HEURISTIC,
            reason="No heuristic check is defined for this file type; no real scanner configured.",
        )

    try:
        import fitz  # PyMuPDF — already a dependency, used elsewhere for PDF handling

        doc = fitz.open(str(file_path))
        try:
            catalog_xref = doc.pdf_catalog()
            catalog_str = doc.xref_object(catalog_xref) or "" if catalog_xref else ""

            if "/Launch" in catalog_str:
                return ScanResult(
                    verdict=VERDICT_INFECTED,
                    provider=PROVIDER_HEURISTIC,
                    reason="PDF document catalog contains a /Launch action (auto-execute intent).",
                )

            for name in doc.embfile_names():
                lowered = (name or "").lower()
                for ext in _DANGEROUS_EMBEDDED_EXTENSIONS:
                    if lowered.endswith(ext):
                        return ScanResult(
                            verdict=VERDICT_INFECTED,
                            provider=PROVIDER_HEURISTIC,
                            reason=f"PDF embeds a file ({name}) with an executable-shaped extension ({ext}).",
                        )
        finally:
            doc.close()
    except Exception as exc:
        return ScanResult(
            verdict=VERDICT_SCAN_UNAVAILABLE,
            provider=PROVIDER_HEURISTIC,
            reason=f"Heuristic screen could not parse this file: {exc}",
        )

    return ScanResult(
        verdict=VERDICT_SCAN_UNAVAILABLE,
        provider=PROVIDER_HEURISTIC,
        reason="No real antivirus scanner is configured (CLAMAV_HOST unset) — this was a narrow structural "
        "screen (auto-launch actions, embedded executables), not malware scanning.",
    )


def run_security_scan(file_path: Path) -> ScanResult:
    """Entry point for the upload pipeline boundary. Always returns a
    ScanResult — never raises (a scan failure must never crash upload
    processing; see `_heuristic_screen`'s except clause and
    `_scan_with_clamav`'s fallback)."""
    if is_real_scanner_configured():
        return _scan_with_clamav(file_path)
    return _heuristic_screen(file_path)
