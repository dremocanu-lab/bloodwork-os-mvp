// Mirrors backend/app/services/document_taxonomy.py's DOCUMENT_TYPE_LABELS.
// Used to show Bragi's finer-grained document_type (Phase 1+) alongside
// or instead of the coarse legacy `section` bucket, for "automatic
// document organization by medical meaning" (Phase 5).

const DOCUMENT_TYPE_LABELS: Record<string, { en: string; ro: string }> = {
  laboratory_results: { en: "Laboratory Results", ro: "Analize" },
  discharge_summary: { en: "Discharge Summary", ro: "Fișă de externare" },
  imaging_report: { en: "Imaging Report", ro: "Raport imagistic" },
  operative_report: { en: "Operative Report", ro: "Protocol operator" },
  pathology_report: { en: "Pathology Report", ro: "Examen anatomopatologic" },
  prescription: { en: "Prescription", ro: "Rețetă" },
  medication_list: { en: "Medication List", ro: "Listă medicație" },
  specialist_consultation: { en: "Specialist Consultation", ro: "Consultație de specialitate" },
  emergency_department_note: { en: "Emergency Department Note", ro: "Notă camera de gardă" },
  hospital_admission_note: { en: "Hospital Admission Note", ro: "Foaie de internare" },
  procedure_report: { en: "Procedure Report", ro: "Raport procedură" },
  referral: { en: "Referral", ro: "Bilet de trimitere" },
  vaccination_record: { en: "Vaccination Record", ro: "Fișă de vaccinare" },
  medical_certificate: { en: "Medical Certificate", ro: "Certificat medical" },
  insurance_or_administrative: { en: "Insurance / Administrative", ro: "Documente administrative" },
  other: { en: "Other", ro: "Altele" },
};

/**
 * The finer-grained label when `document_type` is known (Phase 1+
 * uploads), falling back to the caller's coarse section label for
 * documents uploaded before automatic classification existed.
 */
export function documentTypeOrSectionLabel(
  documentType: string | null | undefined,
  sectionFallbackLabel: string,
  language: string
): string {
  if (documentType && DOCUMENT_TYPE_LABELS[documentType]) {
    const entry = DOCUMENT_TYPE_LABELS[documentType];
    return language === "ro" ? entry.ro : entry.en;
  }
  return sectionFallbackLabel;
}
