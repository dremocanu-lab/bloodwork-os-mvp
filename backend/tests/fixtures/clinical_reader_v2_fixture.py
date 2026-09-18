"""Synthetic Romanian discharge-summary fixture — Clinical Reader
Intelligence V2, Part 28; extended for Source Intelligence + Provenance
V2, Part 51.

SANITIZED, entirely invented (no real patient data): built to exercise,
in one document, every reproduction case the V2 task specification
calls out — current-vs-historical encounter separation, a real filled
principal diagnosis next to a blank secondary field, a fully blank
treatment template, a fully blank investigations template, real
investigations (abdominal ultrasound / JAK2 V617F / bone marrow biopsy /
BCR-ABL) buried in narrative rather than in a form field, a repeated
procedure (phlebotomy) across several real dates, a verbatim-duplicated
narrative segment, a multi-era medication history (Hydrea -> ruxolitinib
-> Besremi, with a dose change), a prescription-issued mention distinct
from confirmed administration, a suspicious far-future date (year 3036),
an implausible vital sign (AV 1008), and laboratory values spanning
normal/pathological CBC-chemistry-coagulation plus one genuinely
conflicting repeated analyte (HGB).

Shaped as the CURRENT discharge pipeline's legacy payload
(`{"sections": [{"title", "body", "page_start"}], "extraction_coverage":
{...}, ...}`) — the same shape `parse_legacy_discharge_payload`/
`reprocess_discharge_document` already consume, so this fixture
exercises the real parser, not a shortcut. Each section entry omits the
legacy shape's optional "key" field (only ever used as a fallback
heading when "title" is absent — every entry here has a real title) so
there is nothing shaped like `"key": "<value>"` for a generic-secret
scanner to misfire on.

`page_start` on every section (Source Intelligence + Provenance V2)
mirrors a real 6-page discharge document's layout — this is what lets
every narrative fact (D45, the phlebotomy events, JAK2, the ultrasound,
BCR-ABL, the recommendations, the anomalies) resolve to a real, honest
"page_only" SourceEvidence once reprocessed, instead of having no
provenance UI at all. `extraction_coverage` reports a complete,
all-6-pages-succeeded extraction — see
test_source_intelligence_provenance_v2.py for the companion
partial-coverage fixture.
"""

from __future__ import annotations

from typing import Any

SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD: dict[str, Any] = {
    "document_type": "discharge_summary",
    "patient_name": "Popescu Maria (synthetic test patient)",
    "date_of_birth": "1968-01-15",
    "sex": "F",
    "admission_date": "2026-03-04",
    "discharge_date": "2026-03-05",
    "hospital_name": "Spitalul Clinic Synthetic Fixture",
    "source_language": "ro",
    "extraction_coverage": {
        "total_pages": 6,
        "attempted_pages": 6,
        "successful_pages": 6,
        "failed_pages": [],
        "warning_pages": [],
        "extraction_complete": True,
    },
    "sections": [
        # ── Page 1: Diagnoses — one real, filled principal diagnosis +
        # one genuinely blank secondary field (Part 1C / 28) ───────────
        {
            "title": "Diagnostic principal (DRG Cod 1)",
            "body": "D45 Policitemie vera",
            "page_start": 1,
        },
        {
            "title": "Diagnostic secundar (DRG Cod 2)",
            "body": "____",
            "page_start": 1,
        },
        # ── Pages 2-4: Clinical course / epicriza — current encounter,
        # historical narrative, repeated phlebotomy, treatment eras,
        # prescription, anomalies, and a verbatim-duplicated block. Kept
        # as several small segments (all classify to the SAME canonical
        # section) so each dated mention becomes its own clean
        # ClinicalEvent, each anchored to its own real page. ───────────
        {
            "title": "EPICRIZĂ",
            "body": (
                "La internare, AV 1008/min, TA 120/80 mmHg, afebrila. "
                "Pacienta, in varsta de 58 ani, a fost internata la 04.03.2026 "
                "pentru investigarea trombocitozei si a agravarii splenomegaliei."
            ),
            "page_start": 2,
        },
        {
            "title": "EPICRIZĂ",
            "body": (
                "Pacienta a fost diagnosticata initial in anul 2018, la varsta de "
                "52 de ani, cu Policitemie vera, confirmata prin biopsie "
                "osteomedulara si mutatia JAK2 V617F pozitiva."
            ),
            "page_start": 2,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La 10.05.2019 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
            "page_start": 2,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La 22.11.2020 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
            "page_start": 3,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La 14.03.2021 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
            "page_start": 3,
        },
        {
            "title": "EPICRIZĂ",
            "body": (
                "La 18.09.2022 s-a decis trecerea de la Hidroxiuree la Ruxolitinib "
                "15mg x2/zi, datorita intolerantei digestive la tratamentul anterior."
            ),
            "page_start": 3,
        },
        {
            "title": "EPICRIZĂ",
            "body": (
                "La 05.02.2024 s-a initiat tratament cu Besremi (ropeginterferon "
                "alfa-2b) 100 micrograme subcutanat, la doua saptamani."
            ),
            "page_start": 3,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La 20.08.2024 doza de Besremi a fost crescuta la 150 micrograme, conform protocolului de titrare.",
            "page_start": 3,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La 10.06.2023, control hematologic: se mentine tratamentul, fara reactii adverse semnalate.",
            "page_start": 4,
        },
        # Verbatim duplicate of the segment above (same wording, same
        # date) — simulates a real two-page-extraction copy artifact.
        # Part 1J/16: must be preserved, only flagged as repeated.
        {
            "title": "EPICRIZĂ",
            "body": "La 10.06.2023, control hematologic: se mentine tratamentul, fara reactii adverse semnalate.",
            "page_start": 4,
        },
        {
            "title": "EPICRIZĂ",
            "body": (
                "La 04.03.2026 s-a efectuat ecografie abdominala care a evidentiat "
                "splenomegalie moderata, fara alte modificari semnificative. "
                "S-a repetat determinarea BCR-ABL, cu rezultat negativ, excluzand "
                "leucemia mieloida cronica."
            ),
            "page_start": 4,
        },
        {
            "title": "EPICRIZĂ",
            "body": "La data de 14.09.3036 a fost eliberata reteta pentru Besremi 150 micrograme, la doua saptamani.",
            "page_start": 4,
        },
        {
            "title": "EPICRIZĂ",
            "body": "Pacienta a fost externata la 05.03.2026, in stare ameliorata, cu recomandarile de mai jos.",
            "page_start": 4,
        },
        # ── Page 5: Laboratory results — normal + pathological
        # CBC/chemistry/coagulation, plus a genuine conflicting repeated
        # analyte (two different HGB values, Part 1H / 8F). ────────────
        {
            "title": "Examen de laborator",
            "body": (
                "WBC 15.2 10^3/uL (4.0-10.0) H\n"
                "HGB 9.8 g/dL (12.0-16.0) L\n"
                "PLT 620 10^3/uL (150-400) H\n"
                "Glucoza 92 mg/dL (70-100)\n"
                "INR 1.1 (0.8-1.2)\n"
                "HGB 11.2 g/dL (12.0-16.0) L"
            ),
            "page_start": 5,
        },
        # ── Page 6: Investigations — entirely blank form template (Part
        # 1D / 28) — the REAL investigations (JAK2, biopsy, ultrasound,
        # BCR-ABL) live in the narrative above, never here. ────────────
        {
            "title": "Investigatii",
            "body": "Cod cerere\nData\nInvestigatii\n____\nEKG\n____\nECO\n____\nRX\n____",
            "page_start": 6,
        },
        # ── Page 6: Treatment administered in hospital — entirely blank
        # form template (Part 1E / 28). ──────────────────────────────────
        {
            "title": "Tratament administrat in spital",
            "body": "PRODUS\nCANTITATE\n_______\n_______\n_______",
            "page_start": 6,
        },
        # ── Page 6: Recommendations — real, current, structured
        # recommendations (Part 9A / 28). ────────────────────────────────
        {
            "title": "Recomandari la externare",
            "body": (
                "Continuare tratament cu Besremi 150 micrograme subcutanat la doua "
                "saptamani. Suplimentare cu Silivit F 1 capsula/zi, Lagosa 1 "
                "comprimat x2/zi si Sargenor 1 fiola/zi timp de 4 saptamani. "
                "Control hematologic in 4 saptamani. Hidratare adecvata, evitarea "
                "eforturilor fizice intense."
            ),
            "page_start": 6,
        },
    ],
}
