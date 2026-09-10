"""Conservative, rule-based document classifier.

This is the "legacy_rules" classifier — a keyword-matching stand-in for
Reducto Classify. It exists so multi-file auto-classification works
today, without a Reducto account, and so the extraction-provider
abstraction (`extraction_provider.py`) has a real default implementation
to fall back to. It is deliberately conservative: confidence is a
heuristic score in [0, 1], not a calibrated probability, and ties are
resolved toward `needs_confirmation` rather than a guess.

When Reducto is enabled, `ReductoExtractionProvider.classify()` should
supersede this for accounts with REDUCTO_ENABLED=true; this module stays
as the offline fallback (`DOCUMENT_EXTRACTION_FALLBACK=legacy`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.document_taxonomy import DocumentType
from app.synonyms import normalize_text

# Status values mirror the spec's classification states:
#   classified          -> high enough confidence, no margin ambiguity, auto-accept
#   needs_confirmation   -> plausible but ambiguous, ask the user
#   other                -> no meaningful signal (empty/garbled/unrecognized), file as Other
CLASSIFIED = "classified"
NEEDS_CONFIRMATION = "needs_confirmation"
OTHER = "other"

MIN_TEXT_LENGTH_FOR_SIGNAL = 25
CONFIDENT_SCORE_THRESHOLD = 3.0
CONFIDENT_MARGIN_THRESHOLD = 1.5


@dataclass
class ClassificationResult:
    document_type: DocumentType
    status: str
    confidence: float
    matched_terms: list[str] = field(default_factory=list)
    candidates: dict[str, float] = field(default_factory=dict)


# Each keyword may be a plain substring match (after normalize_text) or a
# short phrase. Multi-word phrases are weighted higher than single words
# since they are far less likely to appear by accident. Romanian terms
# are written accent-stripped/lowercase already where possible, but
# normalize_text() strips accents from the input too, so either form
# matches ("scazut"/"scăzut", "rezultate"/"rezultate").
_KEYWORDS: dict[DocumentType, list[tuple[str, float]]] = {
    DocumentType.LABORATORY_RESULTS: [
        ("hemoglobina", 2), ("hemoglobin", 1.5), ("hematologie", 2), ("biochimie", 2),
        ("analize", 1.5), ("buletin de analize", 3), ("rezultate analize", 3),
        ("leucocite", 2), ("eritrocite", 2), ("trombocite", 2), ("glicemie", 1.5),
        ("creatinina", 1.5), ("colesterol", 1.5), ("hemoleucograma", 2.5),
        ("valoare referinta", 2), ("interval de referinta", 2.5), ("reference range", 2.5),
        ("reference interval", 2), ("specimen", 0.5), ("cbc", 1.5), ("wbc", 1),
        ("rbc", 1), ("blood test", 1.5), ("laboratory results", 2.5), ("lab results", 2),
        ("test results", 1), ("units", 0.5), ("normal range", 1.5), ("flag", 0.3),
        ("sange venos", 1.5), ("ser", 0.5), ("urina", 1), ("urinalysis", 2),
        ("sumar de urina", 2.5),
    ],
    DocumentType.DISCHARGE_SUMMARY: [
        ("fisa de externare", 3), ("foaie de externare", 3), ("bilet de externare", 3),
        ("scrisoare medicala", 2.5), ("epicriza", 3), ("discharge summary", 3),
        ("discharge diagnosis", 2), ("hospital course", 2), ("data internarii", 2),
        ("data externarii", 2), ("admission date", 1.5), ("discharge date", 1.5),
        ("motivul internarii", 2), ("reason for admission", 2), ("diagnostic la externare", 2.5),
        ("recomandari la externare", 2.5), ("discharge condition", 1.5), ("discharge instructions", 2),
        ("follow-up", 0.5), ("control peste", 1),
    ],
    DocumentType.IMAGING_REPORT: [
        ("computer tomograf", 3), ("tomografie computerizata", 3), ("rezonanta magnetica", 3),
        ("ecografie", 2.5), ("radiografie", 2.5), ("examen ct", 2), ("examen rmn", 2),
        ("ct abdomen", 2.5), ("rmn cerebral", 2.5), ("substanta de contrast", 1.5),
        ("imagistica", 2), ("modalitate", 0.5), ("indicatie", 0.3), ("tehnica de examinare", 1.5),
        ("ct scan", 2.5), ("mri", 1.5), ("ultrasound", 2), ("x-ray", 2), ("radiograph", 1.5),
        ("impression", 0.5), ("findings", 0.3), ("comparison", 0.3), ("body region", 0.5),
        ("secventele", 0.5), ("achizitie", 0.5),
    ],
    DocumentType.OPERATIVE_REPORT: [
        ("protocol operator", 3), ("raport operator", 3), ("interventie chirurgicala", 2.5),
        ("proces verbal operator", 3), ("descrierea interventiei", 2), ("anestezie", 1),
        ("chirurg", 1), ("operative report", 3), ("surgical procedure", 2), ("surgeon", 1),
        ("estimated blood loss", 2), ("postoperative plan", 1.5), ("drenaj", 0.7),
        ("specimen trimis la anatomie patologica", 2),
    ],
    DocumentType.PATHOLOGY_REPORT: [
        ("examen anatomopatologic", 3), ("histopatologie", 3), ("examen histopatologic", 3),
        ("descriere microscopica", 2.5), ("descriere macroscopica", 2), ("diagnostic final", 1),
        ("biopsie", 1.5), ("specimen", 0.3), ("pathology report", 3), ("histology", 2),
        ("microscopic description", 2.5), ("gross description", 2), ("margins", 0.7),
        ("grad histologic", 2), ("imunohistochimie", 2),
    ],
    DocumentType.PRESCRIPTION: [
        ("reteta", 2.5), ("reteta medicala", 3), ("prescriptie", 2.5), ("cod parafa", 2),
        ("prescription", 2.5), ("rx", 0.5), ("dosage", 0.7), ("sig:", 1), ("dispensare", 1),
        ("nr. comprimate", 1.5), ("pastile", 0.5), ("posologie", 1.5),
    ],
    DocumentType.MEDICATION_LIST: [
        ("lista medicatie", 3), ("lista de medicamente", 3), ("tratament actual", 2),
        ("medication list", 3), ("current medications", 2.5), ("home medications", 2),
        ("medicatie la domiciliu", 2.5),
    ],
    DocumentType.SPECIALIST_CONSULTATION: [
        ("consultatie", 2), ("bilet de consultatie", 3), ("scrisoare medicala consultatie", 2.5),
        ("cabinet de specialitate", 1.5), ("examen clinic", 1), ("anamneza", 1),
        ("consultation note", 2.5), ("specialist consultation", 3), ("chief complaint", 1.5),
        ("assessment and plan", 1.5), ("history of present illness", 2),
    ],
    DocumentType.EMERGENCY_DEPARTMENT_NOTE: [
        ("camera de garda", 3), ("unitate de primiri urgente", 3), ("upu", 1.5),
        ("emergency department", 3), ("ed note", 2), ("triage", 1), ("emergency room", 2),
    ],
    DocumentType.HOSPITAL_ADMISSION_NOTE: [
        ("foaie de internare", 3), ("bilet de internare", 3), ("admission note", 3),
        ("history and physical", 2), ("motiv de internare", 2), ("admitting diagnosis", 2),
    ],
    DocumentType.PROCEDURE_REPORT: [
        ("raport procedura", 2.5), ("procedure report", 2.5), ("procedura efectuata", 1.5),
        ("endoscopie", 2), ("colonoscopie", 2), ("bronhoscopie", 2), ("cateterism", 2),
    ],
    DocumentType.REFERRAL: [
        ("bilet de trimitere", 3), ("trimitere medicala", 2.5), ("referral letter", 3),
        ("referral to", 2), ("va rog sa evaluati", 1.5),
    ],
    DocumentType.VACCINATION_RECORD: [
        ("fisa de vaccinare", 3), ("carnet de vaccinare", 3), ("vaccination record", 3),
        ("immunization record", 3), ("vaccin", 1), ("lot vaccin", 2),
    ],
    DocumentType.MEDICAL_CERTIFICATE: [
        ("certificat medical", 3), ("concediu medical", 2.5), ("medical certificate", 3),
        ("fit to work", 2), ("sick note", 2),
    ],
    DocumentType.INSURANCE_OR_ADMINISTRATIVE: [
        ("asigurare de sanatate", 2.5), ("polita de asigurare", 2.5), ("insurance claim", 2.5),
        ("declaratie pe propria raspundere", 1.5), ("factura", 1), ("invoice", 1),
        ("explanation of benefits", 2.5),
    ],
}


def classify_document_text(text: str | None) -> ClassificationResult:
    normalized = normalize_text(text or "")

    if len(normalized) < MIN_TEXT_LENGTH_FOR_SIGNAL:
        return ClassificationResult(
            document_type=DocumentType.OTHER,
            status=OTHER,
            confidence=0.0,
            matched_terms=[],
            candidates={},
        )

    scores: dict[DocumentType, float] = {}
    matched: dict[DocumentType, list[str]] = {}

    for doc_type, keywords in _KEYWORDS.items():
        total = 0.0
        hits: list[str] = []

        for phrase, weight in keywords:
            if phrase in normalized:
                total += weight
                hits.append(phrase)

        if total > 0:
            scores[doc_type] = total
            matched[doc_type] = hits

    if not scores:
        return ClassificationResult(
            document_type=DocumentType.OTHER,
            status=OTHER,
            confidence=0.0,
            matched_terms=[],
            candidates={},
        )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    # Heuristic confidence: saturating function of the winning score,
    # discounted when the runner-up is close behind. Not a probability.
    raw_confidence = min(best_score / (CONFIDENT_SCORE_THRESHOLD * 2), 1.0)
    if margin < CONFIDENT_MARGIN_THRESHOLD:
        raw_confidence *= 0.6

    confident = best_score >= CONFIDENT_SCORE_THRESHOLD and margin >= CONFIDENT_MARGIN_THRESHOLD

    status = CLASSIFIED if confident else NEEDS_CONFIRMATION

    return ClassificationResult(
        document_type=best_type,
        status=status,
        confidence=round(raw_confidence, 3),
        matched_terms=matched.get(best_type, []),
        candidates={doc_type.value: round(score, 2) for doc_type, score in ranked[:4]},
    )
