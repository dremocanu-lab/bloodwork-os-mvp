"""Synthetic Romanian discharge-summary fixture — Clinical Reader
Intelligence V2, Part 28.

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
(`{"sections": [{"key", "title", "body"}], ...}`) — the same shape
`parse_legacy_discharge_payload`/`reprocess_discharge_document` already
consume, so this fixture exercises the real parser, not a shortcut.
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
    "sections": [
        # ── Diagnoses: one real, filled principal diagnosis + one
        # genuinely blank secondary field (Part 1C / 28) ──────────────
        {
            "key": "diagnostic_principal",
            "title": "Diagnostic principal (DRG Cod 1)",
            "body": "D45 Policitemie vera",
        },
        {
            "key": "diagnostic_secundar",
            "title": "Diagnostic secundar (DRG Cod 2)",
            "body": "____",
        },
        # ── Clinical course / epicriza — current encounter, historical
        # narrative, repeated phlebotomy, treatment eras, prescription,
        # anomalies, and a verbatim-duplicated block. Kept as several
        # small segments (all classify to the SAME canonical section) so
        # each dated mention becomes its own clean ClinicalEvent. ──────
        {
            "key": "epicriza_admission",
            "title": "EPICRIZĂ",
            "body": (
                "La internare, AV 1008/min, TA 120/80 mmHg, afebrila. "
                "Pacienta, in varsta de 58 ani, a fost internata la 04.03.2026 "
                "pentru investigarea trombocitozei si a agravarii splenomegaliei."
            ),
        },
        {
            "key": "epicriza_historical_onset",
            "title": "EPICRIZĂ",
            "body": (
                "Pacienta a fost diagnosticata initial in anul 2018, la varsta de "
                "52 de ani, cu Policitemie vera, confirmata prin biopsie "
                "osteomedulara si mutatia JAK2 V617F pozitiva."
            ),
        },
        {
            "key": "epicriza_phlebotomy_1",
            "title": "EPICRIZĂ",
            "body": "La 10.05.2019 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
        },
        {
            "key": "epicriza_phlebotomy_2",
            "title": "EPICRIZĂ",
            "body": "La 22.11.2020 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
        },
        {
            "key": "epicriza_phlebotomy_3",
            "title": "EPICRIZĂ",
            "body": "La 14.03.2021 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.",
        },
        {
            "key": "epicriza_ruxolitinib_transition",
            "title": "EPICRIZĂ",
            "body": (
                "La 18.09.2022 s-a decis trecerea de la Hidroxiuree la Ruxolitinib "
                "15mg x2/zi, datorita intolerantei digestive la tratamentul anterior."
            ),
        },
        {
            "key": "epicriza_besremi_start",
            "title": "EPICRIZĂ",
            "body": (
                "La 05.02.2024 s-a initiat tratament cu Besremi (ropeginterferon "
                "alfa-2b) 100 micrograme subcutanat, la doua saptamani."
            ),
        },
        {
            "key": "epicriza_besremi_dose_change",
            "title": "EPICRIZĂ",
            "body": "La 20.08.2024 doza de Besremi a fost crescuta la 150 micrograme, conform protocolului de titrare.",
        },
        {
            "key": "epicriza_repeated_control_a",
            "title": "EPICRIZĂ",
            "body": "La 10.06.2023, control hematologic: se mentine tratamentul, fara reactii adverse semnalate.",
        },
        # Verbatim duplicate of the segment above (same wording, same
        # date) — simulates a real two-page-extraction copy artifact.
        # Part 1J/16: must be preserved, only flagged as repeated.
        {
            "key": "epicriza_repeated_control_b",
            "title": "EPICRIZĂ",
            "body": "La 10.06.2023, control hematologic: se mentine tratamentul, fara reactii adverse semnalate.",
        },
        {
            "key": "epicriza_current_investigations",
            "title": "EPICRIZĂ",
            "body": (
                "La 04.03.2026 s-a efectuat ecografie abdominala care a evidentiat "
                "splenomegalie moderata, fara alte modificari semnificative. "
                "S-a repetat determinarea BCR-ABL, cu rezultat negativ, excluzand "
                "leucemia mieloida cronica."
            ),
        },
        {
            "key": "epicriza_prescription_and_anomalous_date",
            "title": "EPICRIZĂ",
            "body": "La data de 14.09.3036 a fost eliberata reteta pentru Besremi 150 micrograme, la doua saptamani.",
        },
        {
            "key": "epicriza_discharge",
            "title": "EPICRIZĂ",
            "body": "Pacienta a fost externata la 05.03.2026, in stare ameliorata, cu recomandarile de mai jos.",
        },
        # ── Laboratory results: normal + pathological CBC/chemistry/
        # coagulation, plus a genuine conflicting repeated analyte
        # (two different HGB values, Part 1H / 8F). ────────────────────
        {
            "key": "laborator",
            "title": "Examen de laborator",
            "body": (
                "WBC 15.2 10^3/uL (4.0-10.0) H\n"
                "HGB 9.8 g/dL (12.0-16.0) L\n"
                "PLT 620 10^3/uL (150-400) H\n"
                "Glucoza 92 mg/dL (70-100)\n"
                "INR 1.1 (0.8-1.2)\n"
                "HGB 11.2 g/dL (12.0-16.0) L"
            ),
        },
        # ── Investigations: entirely blank form template (Part 1D / 28)
        # — the REAL investigations (JAK2, biopsy, ultrasound, BCR-ABL)
        # live in the narrative above, never here. ──────────────────────
        {
            "key": "investigatii",
            "title": "Investigatii",
            "body": "Cod cerere\nData\nInvestigatii\n____\nEKG\n____\nECO\n____\nRX\n____",
        },
        # ── Treatment administered in hospital: entirely blank form
        # template (Part 1E / 28). ──────────────────────────────────────
        {
            "key": "tratament_administrat",
            "title": "Tratament administrat in spital",
            "body": "PRODUS\nCANTITATE\n_______\n_______\n_______",
        },
        # ── Recommendations: real, current, structured recommendations
        # (Part 9A / 28). ────────────────────────────────────────────────
        {
            "key": "recomandari",
            "title": "Recomandari la externare",
            "body": (
                "Continuare tratament cu Besremi 150 micrograme subcutanat la doua "
                "saptamani. Suplimentare cu Silivit F 1 capsula/zi, Lagosa 1 "
                "comprimat x2/zi si Sargenor 1 fiola/zi timp de 4 saptamani. "
                "Control hematologic in 4 saptamani. Hidratare adecvata, evitarea "
                "eforturilor fizice intense."
            ),
        },
    ],
}
