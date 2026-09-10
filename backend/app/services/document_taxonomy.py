"""Bragi document taxonomy.

Defines the canonical set of medical document types Bragi can recognize,
independent of the legacy `Document.section` bucket that drives today's
UI grouping and processing branch (bloodwork / discharge_summary / other).

`document_type` is the new, granular classification produced by
`document_classifier` (or, later, Reducto Classify). It is stored
alongside the legacy `section` rather than replacing it, so every
existing route, page, and query that filters on `section` keeps working
unchanged. `LEGACY_SECTION_BY_DOCUMENT_TYPE` is the one place that maps
a taxonomy value to the legacy bucket used for routing and grouping
today; as document-type-specific readers/pipelines are added (Phase 3+),
entries here can point at new dedicated sections without touching the
taxonomy itself.
"""

from __future__ import annotations

from enum import Enum


class DocumentType(str, Enum):
    LABORATORY_RESULTS = "laboratory_results"
    DISCHARGE_SUMMARY = "discharge_summary"
    IMAGING_REPORT = "imaging_report"
    OPERATIVE_REPORT = "operative_report"
    PATHOLOGY_REPORT = "pathology_report"
    PRESCRIPTION = "prescription"
    MEDICATION_LIST = "medication_list"
    SPECIALIST_CONSULTATION = "specialist_consultation"
    EMERGENCY_DEPARTMENT_NOTE = "emergency_department_note"
    HOSPITAL_ADMISSION_NOTE = "hospital_admission_note"
    PROCEDURE_REPORT = "procedure_report"
    REFERRAL = "referral"
    VACCINATION_RECORD = "vaccination_record"
    MEDICAL_CERTIFICATE = "medical_certificate"
    INSURANCE_OR_ADMINISTRATIVE = "insurance_or_administrative"
    OTHER = "other"


# User-facing labels. Keep in sync with any frontend copy of this list
# (frontend/lib currently has no equivalent yet — Phase 1 introduces the
# confirmation UI against this same value set via /document-types).
DOCUMENT_TYPE_LABELS: dict[DocumentType, dict[str, str]] = {
    DocumentType.LABORATORY_RESULTS: {"en": "Laboratory Results", "ro": "Analize"},
    DocumentType.DISCHARGE_SUMMARY: {"en": "Discharge Summary", "ro": "Fișă de externare"},
    DocumentType.IMAGING_REPORT: {"en": "Imaging Report", "ro": "Raport imagistic"},
    DocumentType.OPERATIVE_REPORT: {"en": "Operative Report", "ro": "Protocol operator"},
    DocumentType.PATHOLOGY_REPORT: {"en": "Pathology Report", "ro": "Examen anatomopatologic"},
    DocumentType.PRESCRIPTION: {"en": "Prescription", "ro": "Rețetă"},
    DocumentType.MEDICATION_LIST: {"en": "Medication List", "ro": "Listă medicație"},
    DocumentType.SPECIALIST_CONSULTATION: {"en": "Specialist Consultation", "ro": "Consultație de specialitate"},
    DocumentType.EMERGENCY_DEPARTMENT_NOTE: {"en": "Emergency Department Note", "ro": "Notă camera de gardă"},
    DocumentType.HOSPITAL_ADMISSION_NOTE: {"en": "Hospital Admission Note", "ro": "Foaie de internare"},
    DocumentType.PROCEDURE_REPORT: {"en": "Procedure Report", "ro": "Raport procedură"},
    DocumentType.REFERRAL: {"en": "Referral", "ro": "Bilet de trimitere"},
    DocumentType.VACCINATION_RECORD: {"en": "Vaccination Record", "ro": "Fișă de vaccinare"},
    DocumentType.MEDICAL_CERTIFICATE: {"en": "Medical Certificate", "ro": "Certificat medical"},
    DocumentType.INSURANCE_OR_ADMINISTRATIVE: {"en": "Insurance / Administrative", "ro": "Documente administrative"},
    DocumentType.OTHER: {"en": "Other", "ro": "Altele"},
}

# The legacy `section` values that already exist on Document/UploadJob
# and drive current processing + grouping. Every document_type maps to
# exactly one of these so nothing downstream breaks.
LEGACY_SECTIONS = {
    "notes",
    "bloodwork",
    "discharge_summary",
    "medications",
    "scans",
    "hospitalizations",
    "other",
}

LEGACY_SECTION_BY_DOCUMENT_TYPE: dict[DocumentType, str] = {
    DocumentType.LABORATORY_RESULTS: "bloodwork",
    DocumentType.DISCHARGE_SUMMARY: "discharge_summary",
    DocumentType.IMAGING_REPORT: "scans",
    DocumentType.OPERATIVE_REPORT: "hospitalizations",
    DocumentType.PATHOLOGY_REPORT: "scans",
    DocumentType.PRESCRIPTION: "medications",
    DocumentType.MEDICATION_LIST: "medications",
    DocumentType.SPECIALIST_CONSULTATION: "other",
    DocumentType.EMERGENCY_DEPARTMENT_NOTE: "hospitalizations",
    DocumentType.HOSPITAL_ADMISSION_NOTE: "hospitalizations",
    DocumentType.PROCEDURE_REPORT: "scans",
    DocumentType.REFERRAL: "other",
    DocumentType.VACCINATION_RECORD: "other",
    DocumentType.MEDICAL_CERTIFICATE: "other",
    DocumentType.INSURANCE_OR_ADMINISTRATIVE: "other",
    DocumentType.OTHER: "other",
}

# Sentinel `section` value used on a newly-created UploadJob to mean
# "not yet classified — classify from content before routing". Never a
# member of LEGACY_SECTIONS/ALLOWED_SECTIONS so it can't leak into
# existing filters that check `section in ALLOWED_SECTIONS`.
AUTO_CLASSIFY_SECTION = "__pending_classification__"


def document_type_choices() -> list[dict[str, str]]:
    """Serializable list for the /document-types endpoint and confirmation UI."""
    return [
        {
            "value": doc_type.value,
            "label_en": labels["en"],
            "label_ro": labels["ro"],
        }
        for doc_type, labels in DOCUMENT_TYPE_LABELS.items()
    ]


def is_valid_document_type(value: str | None) -> bool:
    if not value:
        return False
    try:
        DocumentType(value)
        return True
    except ValueError:
        return False


def legacy_section_for(document_type: str | DocumentType) -> str:
    doc_type = document_type if isinstance(document_type, DocumentType) else DocumentType(document_type)
    return LEGACY_SECTION_BY_DOCUMENT_TYPE[doc_type]
