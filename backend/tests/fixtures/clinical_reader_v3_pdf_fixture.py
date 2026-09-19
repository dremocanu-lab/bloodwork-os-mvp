"""A REAL, sanitized, synthetic multi-page discharge PDF — Source
Geometry + Clinical Table Intelligence V3, Part 54.

Unlike the previous phases' JSON-only fixtures, this one is a genuine
PDF (built with PyMuPDF's own write capability — no real patient file,
no external asset committed to the repo) with real paragraph text and
real gridded tables, laid out across 8 pages exactly matching Part 54's
required structure. `build_synthetic_discharge_v3_fixture()` is the ONE
source of truth: it builds the PDF bytes, extracts REAL geometry from
the SAME pages via `source_geometry.extract_page_geometry` (never a
hand-written fake bbox), and assembles a `page_payloads`-shaped legacy
JSON payload whose section body text is IDENTICAL to what was actually
placed in the PDF — so every test using this fixture exercises the
REAL geometry-alignment path, not a synthetic stand-in for it.

No real patient data — every name/value here is invented for this
fixture.
"""

from __future__ import annotations

from typing import Any

import fitz

from app.services.clinical_document.source_geometry import extract_page_geometry

PAGE_WIDTH = 595.0  # A4, points
PAGE_HEIGHT = 842.0

_TITLE_FONT = 16
_HEADING_FONT = 12
_BODY_FONT = 10.5
_LINE_HEIGHT = 16


class _PageWriter:
    """Small line-cursor helper so each page's content can be built
    top-to-bottom without manually tracking y-coordinates — keeps the
    fixture readable while still producing real, independent PyMuPDF
    text insertions (never one giant multi-line insert_text call, which
    would collapse into a single PyMuPDF block and defeat the point of
    testing per-paragraph geometry)."""

    def __init__(self, page: "fitz.Page"):
        self.page = page
        self.y = 60.0

    def heading(self, text: str) -> None:
        self.page.insert_text((56, self.y), text, fontsize=_HEADING_FONT, fontname="helv")
        self.y += _LINE_HEIGHT + 6

    def paragraph(self, text: str, *, max_chars_per_line: int = 78) -> None:
        """Wraps `text` onto several lines but inserts it as ONE
        PyMuPDF text call per paragraph so it forms ONE block (matching
        how a real single clinical paragraph renders) — wrapping is
        whitespace-based, never mid-word."""
        words = text.split(" ")
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars_per_line and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        wrapped = "\n".join(lines)
        self.page.insert_text((56, self.y), wrapped, fontsize=_BODY_FONT, fontname="helv", lineheight=1.3)
        self.y += _LINE_HEIGHT * len(lines) + 10

    def spacer(self, height: float = 14.0) -> None:
        self.y += height


def _draw_table(page: "fitz.Page", *, x: float, y: float, rows: list[list[str]], col_widths: list[float], row_height: float = 18.0) -> float:
    """Draws a real gridded table (so PyMuPDF's `find_tables()` can
    detect it as one) — returns the y-coordinate just below the table."""
    for r, row in enumerate(rows):
        cx = x
        for c, cell_text in enumerate(row):
            page.insert_text((cx + 3, y + r * row_height + row_height - 5), cell_text, fontsize=_BODY_FONT - 0.5, fontname="helv")
            cx += col_widths[c]
    total_width = sum(col_widths)
    total_height = row_height * len(rows)
    for r in range(len(rows) + 1):
        page.draw_line((x, y + r * row_height), (x + total_width, y + r * row_height))
    cx = x
    for w in col_widths:
        page.draw_line((cx, y), (cx, y + total_height))
        cx += w
    page.draw_line((cx, y), (cx, y + total_height))
    return y + total_height + 14


# ── Page content — kept as module-level constants so tests can assert
# against the EXACT same strings used to build the PDF, never a
# re-typed/approximate copy that could silently drift. ─────────────────

D45_TEXT = "D45 Policitemie vera"
PHLEBOTOMY_TEXT = "La 22.06.2019 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata de pacienta."
ADMISSION_TEXT = (
    "La internare, AV 1008/min, TA 120/80 mmHg, afebrila. Pacienta a fost internata la 04.03.2026 "
    "pentru investigarea trombocitozei si a agravarii splenomegaliei."
)
ULTRASOUND_TEXT = (
    "Ecografie abdominala: se evidentiaza splenomegalie moderata, cu diametru longitudinal de 14 cm, "
    "fara alte modificari semnificative la nivelul organelor abdominale."
)
JAK2_TEXT = "Determinare moleculara: mutatia JAK2 V617F este pozitiva, confirmand diagnosticul de policitemie vera."
BONE_MARROW_TEXT = (
    "Biopsia osteomedulara efectuata evidentiaza hipercelularitate cu hiperplazie a seriei eritroide, "
    "compatibila cu policitemia vera."
)
BCR_ABL_TEXT = "Testarea BCR-ABL este negativa, excluzand leucemia mieloida cronica ca diagnostic alternativ."
RECOMMENDATION_TEXT = (
    "Continuare tratament cu Besremi 150 micrograme subcutanat la doua saptamani. Control hematologic "
    "programat peste 4 saptamani, cu hidratare adecvata si evitarea eforturilor fizice intense."
)
ANOMALOUS_DATE_TEXT = "Reteta pentru Besremi 150 micrograme a fost eliberata la data de 14.09.3036."

_MEDICATION_ROWS = [
    ["Medicament", "Doza", "Frecventa"],
    ["Hidroxiuree", "500mg", "oprit"],
    ["Ruxolitinib", "15mg", "x2/zi"],
]
_PRESCRIPTION_ROWS = [
    ["Medicament", "Doza", "Cantitate"],
    ["Besremi", "150mcg", "1 cutie"],
]
_LAB_ROWS = [
    ["Analiza", "Rezultat", "UM", "Interval"],
    ["ALT", "56", "U/L", "10-49"],
    ["HGB", "9.8", "g/dL", "12.0-16.0"],
    ["HGB", "11.2", "g/dL", "12.0-16.0"],
]
_EMPTY_TREATMENT_ROWS = [["PRODUS", "CANTITATE"], ["_______", "_______"], ["_______", "_______"]]
_EMPTY_INVESTIGATION_ROWS = [["EKG", "ECO", "RX", "ALTELE"], ["____", "____", "____", "____"]]


def build_synthetic_discharge_v3_fixture() -> tuple[bytes, dict[str, Any]]:
    """Returns `(pdf_bytes, legacy_payload)` — `legacy_payload` is the
    SAME `{"sections": [...], "page_payloads": [...], ...}` shape
    `discharge_summary_pipeline.process_uploaded_discharge_summary()`
    would have produced for this exact PDF (page_start/page_geometry
    included), so `parse_legacy_discharge_payload()`/
    `reprocess_discharge_document()` can consume it directly without
    ever needing a live OpenAI call."""
    doc = fitz.open()

    # ── Page 1: title, admin, D45 ───────────────────────────────────
    # Geometry is extracted IMMEDIATELY after each page is finished, not
    # collected into a `pages` list for later — PyMuPDF page handles can
    # be invalidated by subsequent document mutations (adding further
    # pages), a real gotcha this fixture hit and fixed, not a
    # theoretical concern.
    page_geometries = []

    page1 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w1 = _PageWriter(page1)
    w1.heading("BILET DE IESIRE DIN SPITAL")
    w1.paragraph("Spitalul Clinic Synthetic Fixture. Pacient: Popescu Maria (fixture sintetic).")
    w1.spacer()
    w1.heading("Diagnostic principal (DRG Cod 1)")
    w1.paragraph(D45_TEXT)
    page_geometries.append(extract_page_geometry(page1, page_number=1))

    # ── Page 2: narrative + phlebotomy + admission anomaly ──────────
    page2 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w2 = _PageWriter(page2)
    w2.heading("EPICRIZA")
    w2.paragraph(ADMISSION_TEXT)
    w2.spacer()
    w2.paragraph(PHLEBOTOMY_TEXT)
    page_geometries.append(extract_page_geometry(page2, page_number=2))

    # ── Page 3: medication table ─────────────────────────────────────
    page3 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w3 = _PageWriter(page3)
    w3.heading("Medicatie curenta")
    _draw_table(page3, x=56, y=w3.y, rows=_MEDICATION_ROWS, col_widths=[150, 80, 100])
    page_geometries.append(extract_page_geometry(page3, page_number=3))

    # ── Page 4: ultrasound / JAK2 / bone marrow / BCR-ABL paragraphs ─
    page4 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w4 = _PageWriter(page4)
    w4.heading("Investigatii (narrativ)")
    w4.paragraph(ULTRASOUND_TEXT)
    w4.spacer()
    w4.paragraph(JAK2_TEXT)
    w4.spacer()
    w4.paragraph(BONE_MARROW_TEXT)
    w4.spacer()
    w4.paragraph(BCR_ABL_TEXT)
    page_geometries.append(extract_page_geometry(page4, page_number=4))

    # ── Page 5: prescription table + anomalous date ──────────────────
    page5 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w5 = _PageWriter(page5)
    w5.heading("Retete eliberate")
    y_after_table = _draw_table(page5, x=56, y=w5.y, rows=_PRESCRIPTION_ROWS, col_widths=[120, 80, 100])
    w5.y = y_after_table
    w5.paragraph(ANOMALOUS_DATE_TEXT)
    page_geometries.append(extract_page_geometry(page5, page_number=5))

    # ── Page 6: laboratory table (ALT + conflicting HGB) ──────────────
    page6 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w6 = _PageWriter(page6)
    w6.heading("Examen de laborator")
    _draw_table(page6, x=56, y=w6.y, rows=_LAB_ROWS, col_widths=[80, 80, 80, 100])
    page_geometries.append(extract_page_geometry(page6, page_number=6))

    # ── Page 7: recommendations ───────────────────────────────────────
    page7 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w7 = _PageWriter(page7)
    w7.heading("Recomandari la externare")
    w7.paragraph(RECOMMENDATION_TEXT)
    page_geometries.append(extract_page_geometry(page7, page_number=7))

    # ── Page 8: empty treatment + investigation templates ─────────────
    page8 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    w8 = _PageWriter(page8)
    w8.heading("Tratament administrat in spital")
    y_after = _draw_table(page8, x=56, y=w8.y, rows=_EMPTY_TREATMENT_ROWS, col_widths=[150, 150])
    w8.y = y_after + 20
    w8.heading("Investigatii")
    _draw_table(page8, x=56, y=w8.y, rows=_EMPTY_INVESTIGATION_ROWS, col_widths=[80, 80, 80, 100])
    page_geometries.append(extract_page_geometry(page8, page_number=8))

    pdf_bytes = doc.tobytes()
    doc.close()

    page_payloads = [
        {
            "page_number": 1,
            "sections": [
                {"key": "administrative_information", "title": "BILET DE IESIRE DIN SPITAL", "body": "Spitalul Clinic Synthetic Fixture. Pacient: Popescu Maria (fixture sintetic)."},
                {"key": "diagnoses", "title": "Diagnostic principal (DRG Cod 1)", "body": D45_TEXT},
            ],
        },
        {
            "page_number": 2,
            "sections": [
                {"key": "epicriza", "title": "EPICRIZA", "body": ADMISSION_TEXT},
                {"key": "epicriza", "title": "EPICRIZA", "body": PHLEBOTOMY_TEXT},
            ],
        },
        {
            "page_number": 3,
            "sections": [
                {"key": "medicatie", "title": "Medicatie curenta", "body": "Vezi medicatia structurata de mai jos."},
            ],
        },
        {
            "page_number": 4,
            "sections": [
                # "Investigatii (narrativ)" — the REAL heading drawn on
                # this PDF page (see w4.heading(...) above); classifies
                # to the "investigations" canonical key, matching real
                # page content (was previously mislabeled "EPICRIZA",
                # which never matched what page 4 actually says).
                {"key": "investigatii", "title": "Investigatii (narrativ)", "body": ULTRASOUND_TEXT},
                {"key": "investigatii", "title": "Investigatii (narrativ)", "body": JAK2_TEXT},
                {"key": "investigatii", "title": "Investigatii (narrativ)", "body": BONE_MARROW_TEXT},
                {"key": "investigatii", "title": "Investigatii (narrativ)", "body": BCR_ABL_TEXT},
            ],
        },
        {
            "page_number": 5,
            "sections": [
                {"key": "prescriptions_released", "title": "Retete eliberate", "body": "Vezi reteta structurata de mai jos."},
                {"key": "epicriza", "title": "EPICRIZA", "body": ANOMALOUS_DATE_TEXT},
            ],
        },
        {
            "page_number": 6,
            "sections": [
                {"key": "laborator", "title": "Examen de laborator", "body": "Vezi rezultatele structurate de mai jos."},
            ],
        },
        {
            "page_number": 7,
            "sections": [
                {"key": "recommended_treatment", "title": "Recomandari la externare", "body": RECOMMENDATION_TEXT},
            ],
        },
        {
            "page_number": 8,
            "sections": [
                {"key": "treatment_in_hospital", "title": "Tratament administrat in spital", "body": "PRODUS\nCANTITATE\n_______\n_______"},
                {"key": "investigations", "title": "Investigatii", "body": "EKG\nECO\nRX\nALTELE\n____"},
            ],
        },
    ]
    for payload_page, geometry in zip(page_payloads, page_geometries):
        payload_page["geometry"] = geometry.model_dump()

    sections: list[dict[str, Any]] = []
    for payload_page in page_payloads:
        for section in payload_page["sections"]:
            sections.append({**section, "page_start": payload_page["page_number"], "page_end": payload_page["page_number"], "source_pages": [payload_page["page_number"]]})

    legacy_payload: dict[str, Any] = {
        "document_type": "discharge_summary",
        "patient_name": "Popescu Maria (synthetic test patient)",
        "admission_date": "2026-03-04",
        "discharge_date": "2026-03-05",
        "hospital_name": "Spitalul Clinic Synthetic Fixture",
        "source_language": "ro",
        "page_count": len(page_geometries),
        "page_payloads": page_payloads,
        "sections": sections,
        "extraction_coverage": {
            "total_pages": len(page_geometries),
            "attempted_pages": len(page_geometries),
            "successful_pages": len(page_geometries),
            "failed_pages": [],
            "warning_pages": [],
            "extraction_complete": True,
        },
    }
    return pdf_bytes, legacy_payload
