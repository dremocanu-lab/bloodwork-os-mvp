"""Reducto Classify/Extract schemas for Bragi's document taxonomy.

Criteria text and JSON schemas here were exercised against the live
Reducto API with synthetic Romanian medical documents (see the Reducto
integration commit for the test transcript) before being adopted — not
guessed from documentation alone. In particular:

- The classification criteria below reproduced perfect separation
  (confidence 1.0 for the true category, 0.0 for every other) on six
  distinct synthetic document types, and correctly produced a genuine
  confidence tie (1.0/1.0) between `laboratory_results` and
  `discharge_summary` for a document that legitimately contained both
  (a discharge letter with an embedded lab table) — this is the real
  shape `needs_confirmation` detection has to handle; see
  `extraction_provider.classify_confidence_status`.
- The lab extraction schema correctly pulled Romanian decimal-comma
  values ("13,2", "0,9") and units (g/dL, mg/dL, mii/uL) with per-field
  bounding-box citations.

`document_taxonomy.DocumentType` is the source of truth for the type
values themselves; this module only adds the natural-language criteria
Reducto Classify needs and the JSON schemas Reducto Extract needs.
`operative_report` and `pathology_report` are included for classification
completeness (so a document of that type doesn't get miscategorized as
something else) even though a dedicated extraction schema for them isn't
wired into the upload pipeline yet — see BRAGI_REDUCTO_PLAN.md.
"""

from __future__ import annotations

from typing import Any

from app.services.structured_reader_service import SECTION_KEYS

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Every entry maps 1:1 to a DocumentType value. Kept as a flat list (not a
# dict) because Reducto's classification_schema is order-sensitive for tie
# presentation only, not for scoring — order here doesn't affect results.
CLASSIFICATION_SCHEMA: list[dict[str, Any]] = [
    {
        "category": "laboratory_results",
        "criteria": [
            "Contains a table of laboratory test names with numeric results, "
            "units, and reference ranges (blood work, biochemistry, hematology, "
            "urinalysis)."
        ],
    },
    {
        "category": "discharge_summary",
        "criteria": [
            "A hospital discharge letter summarizing an inpatient admission: "
            "admission/discharge dates, diagnosis, hospital course, discharge "
            "recommendations."
        ],
    },
    {
        "category": "imaging_report",
        "criteria": [
            "A radiology/imaging report (CT, MRI, X-ray, ultrasound) with a "
            "findings and conclusion/impression section describing imaging "
            "results."
        ],
    },
    {
        "category": "operative_report",
        "criteria": [
            "A surgical/operative report describing a procedure performed, "
            "surgical technique, findings, and postoperative plan."
        ],
    },
    {
        "category": "pathology_report",
        "criteria": [
            "A pathology/anatomopathology report describing gross and "
            "microscopic tissue/biopsy analysis and a final diagnosis."
        ],
    },
    {
        "category": "prescription",
        "criteria": [
            "A medical prescription (Rp/reteta) listing prescribed "
            "medications, dosages, and a prescribing doctor."
        ],
    },
    {
        "category": "medication_list",
        "criteria": [
            "A standalone list of a patient's current/home medications, not "
            "itself a new prescription."
        ],
    },
    {
        "category": "specialist_consultation",
        "criteria": [
            "A specialist outpatient consultation note documenting a visit to "
            "a specific medical specialty with findings and recommendations."
        ],
    },
    {
        "category": "emergency_department_note",
        "criteria": [
            "An emergency department / camera de garda visit note."
        ],
    },
    {
        "category": "hospital_admission_note",
        "criteria": [
            "An admission note / foaie de internare documenting the reason "
            "for admission at the start of a hospital stay (not the "
            "discharge)."
        ],
    },
    {
        "category": "procedure_report",
        "criteria": [
            "A report of a non-surgical procedure (endoscopy, colonoscopy, "
            "catheterization) that is not itself an operative or imaging "
            "report."
        ],
    },
    {
        "category": "referral",
        "criteria": [
            "A referral letter (bilet de trimitere) directing the patient to "
            "another provider or specialty."
        ],
    },
    {
        "category": "vaccination_record",
        "criteria": [
            "A vaccination/immunization record."
        ],
    },
    {
        "category": "medical_certificate",
        "criteria": [
            "A medical certificate or sick note (concediu medical) certifying "
            "fitness/unfitness for work or school."
        ],
    },
    {
        "category": "insurance_or_administrative",
        "criteria": [
            "An insurance, billing, or other administrative document with no "
            "clinical findings."
        ],
    },
    {
        "category": "other",
        "criteria": [
            "Does not clearly match any other category, or is a generic "
            "clinical note without a clear structured type."
        ],
    },
]

# Ambiguity thresholds — derived from the live test above, not invented in
# the abstract: a genuine content collision produces two categories at
# confidence 1.0 (or both "high" on their defining criterion). A single
# category at 1.0 with everything else at 0.0 is the unambiguous case.
# Anything where the runner-up is within this margin of the winner (and
# non-trivial) is treated as real ambiguity, not classifier noise.
NEEDS_CONFIRMATION_RUNNER_UP_MIN_CONFIDENCE = 0.5
NEEDS_CONFIRMATION_MAX_MARGIN = 0.25
# The winner itself must clear this bar to auto-accept even with no
# runner-up close behind (a low-confidence lone winner is "we don't know",
# not "we're confident") — routed to `other` rather than blocking on a
# confirmation dialog, matching the spec's "no meaningful signal" bucket.
MIN_CONFIDENT_WINNER_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# Extraction: laboratory_results -> feeds the existing Analize/LabResult
# pipeline. Field names mirror what process_upload_job already expects in
# a `labs` list entry (see reducto_extraction.map_lab_extraction_to_labs).
# ---------------------------------------------------------------------------

LAB_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "patient_full_name": {"type": "string", "description": "Patient's full name exactly as printed."},
        "patient_cnp": {"type": "string", "description": "Romanian CNP (13-digit personal numeric code), if present."},
        "date_of_birth": {"type": "string", "description": "Patient date of birth exactly as printed."},
        "collection_date": {"type": "string", "description": "Specimen collection date exactly as printed."},
        "reported_date": {"type": "string", "description": "Report validation/issue date exactly as printed."},
        "institution": {"type": "string", "description": "Laboratory or institution name."},
        "referring_doctor": {"type": "string"},
        "results": {
            "type": "array",
            "description": "Every individual laboratory determination on the document.",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {
                        "type": "string",
                        "description": "Raw test name exactly as printed, in its original language — do not translate or normalize.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Result value exactly as printed, including decimal commas if present (e.g. '13,2').",
                    },
                    "unit": {"type": "string", "description": "Unit of measure exactly as printed (e.g. 'g/dL', 'mii/uL')."},
                    "reference_range": {"type": "string", "description": "Reference/normal interval exactly as printed."},
                    "flag": {
                        "type": "string",
                        "description": "Abnormal flag if present, e.g. 'crescut', 'scazut', 'H', 'L'. Null if not flagged.",
                    },
                    "section": {
                        "type": "string",
                        "description": "The panel/section heading this result appears under, e.g. 'HEMOLEUCOGRAMA COMPLETA', 'BIOCHIMIE'.",
                    },
                },
            },
        },
    },
}

IDENTITY_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "patient_full_name": {"type": "string"},
        "patient_cnp": {"type": "string", "description": "Romanian CNP (13-digit personal numeric code) if present."},
        "date_of_birth": {"type": "string"},
        "patient_identifier": {"type": "string", "description": "Any other patient/medical record identifier if present."},
    },
}


def _reader_schema_for(document_type: str) -> dict[str, Any]:
    """Builds an Extract schema from the same SECTION_KEYS the existing
    OpenAI-based structured_reader_service uses, so results land in the
    identical `structured_sections` shape the Reader UI already renders —
    swapping the provider, not the contract."""
    keys = SECTION_KEYS.get(document_type, [])
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "string",
                "description": f"The '{key.replace('_', ' ')}' section, verbatim as printed. Null if not present — never invent it.",
            }
            for key in keys
        },
    }


# One schema per narrative type already known to structured_reader_service.
READER_EXTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    document_type: _reader_schema_for(document_type) for document_type in SECTION_KEYS
}
