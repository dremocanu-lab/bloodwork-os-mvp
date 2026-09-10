// Phase 4 clinical readers — section labels for the conservative,
// source-grounded structured extraction in
// backend/app/services/structured_reader_service.py. Keys must match
// that module's SECTION_KEYS exactly.

export const READER_DOCUMENT_TYPES = [
  "imaging_report",
  "operative_report",
  "pathology_report",
  "prescription",
  "medication_list",
  "specialist_consultation",
] as const;

export type ReaderDocumentType = (typeof READER_DOCUMENT_TYPES)[number];

export function isReaderDocumentType(value?: string | null): value is ReaderDocumentType {
  return Boolean(value) && (READER_DOCUMENT_TYPES as readonly string[]).includes(value as string);
}

type SectionLabels = Record<string, { en: string; ro: string }>;

const SHARED: SectionLabels = {
  date: { en: "Date", ro: "Dată" },
  instructions: { en: "Instructions", ro: "Instrucțiuni" },
};

export const READER_SECTION_LABELS: Record<ReaderDocumentType, SectionLabels> = {
  imaging_report: {
    modality: { en: "Modality", ro: "Modalitate" },
    body_region: { en: "Body region", ro: "Regiune examinată" },
    exam_date: { en: "Exam date", ro: "Data examinării" },
    indication: { en: "Indication", ro: "Indicație" },
    technique: { en: "Technique", ro: "Tehnică" },
    comparison: { en: "Comparison", ro: "Comparație" },
    findings: { en: "Findings", ro: "Descriere" },
    impression: { en: "Impression", ro: "Concluzie" },
    recommendations: { en: "Recommendations", ro: "Recomandări" },
    incidental_findings: { en: "Incidental findings", ro: "Constatări incidentale" },
  },
  operative_report: {
    procedure: { en: "Procedure", ro: "Procedură" },
    ...SHARED,
    indication: { en: "Indication", ro: "Indicație" },
    surgeon: { en: "Surgeon", ro: "Chirurg" },
    assistants: { en: "Assistants", ro: "Asistenți" },
    anesthesia: { en: "Anesthesia", ro: "Anestezie" },
    findings: { en: "Findings", ro: "Constatări" },
    procedural_steps: { en: "Procedural steps", ro: "Etapele intervenției" },
    complications: { en: "Complications", ro: "Complicații" },
    blood_loss: { en: "Blood loss", ro: "Pierdere sangvină" },
    specimens: { en: "Specimens", ro: "Specimene" },
    postoperative_plan: { en: "Postoperative plan", ro: "Plan postoperator" },
  },
  pathology_report: {
    specimen: { en: "Specimen", ro: "Specimen" },
    gross_description: { en: "Gross description", ro: "Descriere macroscopică" },
    microscopic_description: { en: "Microscopic description", ro: "Descriere microscopică" },
    final_diagnosis: { en: "Final diagnosis", ro: "Diagnostic final" },
    histologic_grade: { en: "Histologic grade", ro: "Grad histologic" },
    margins: { en: "Margins", ro: "Margini" },
    biomarkers: { en: "Biomarkers", ro: "Biomarkeri" },
    comments: { en: "Comments", ro: "Comentarii" },
  },
  prescription: {
    medications: { en: "Medications", ro: "Medicație" },
    prescriber: { en: "Prescriber", ro: "Medic prescriptor" },
    ...SHARED,
  },
  medication_list: {
    medications: { en: "Medications", ro: "Medicație" },
    instructions: SHARED.instructions,
  },
  specialist_consultation: {
    specialty: { en: "Specialty", ro: "Specialitate" },
    clinician: { en: "Clinician", ro: "Medic" },
    date: SHARED.date,
    reason: { en: "Reason", ro: "Motivul consultației" },
    history: { en: "History", ro: "Anamneză" },
    exam: { en: "Exam", ro: "Examen clinic" },
    assessment: { en: "Assessment", ro: "Evaluare" },
    diagnoses: { en: "Diagnoses", ro: "Diagnostice" },
    investigations: { en: "Investigations", ro: "Investigații" },
    plan: { en: "Plan", ro: "Plan" },
    recommendations: { en: "Recommendations", ro: "Recomandări" },
    follow_up: { en: "Follow-up", ro: "Control ulterior" },
  },
};

export const READER_DOCUMENT_TYPE_LABELS: Record<ReaderDocumentType, { en: string; ro: string }> = {
  imaging_report: { en: "Imaging Report", ro: "Raport imagistic" },
  operative_report: { en: "Operative Report", ro: "Protocol operator" },
  pathology_report: { en: "Pathology Report", ro: "Examen anatomopatologic" },
  prescription: { en: "Prescription", ro: "Rețetă" },
  medication_list: { en: "Medication List", ro: "Listă medicație" },
  specialist_consultation: { en: "Specialist Consultation", ro: "Consultație de specialitate" },
};

export function sectionLabel(docType: ReaderDocumentType, key: string, language: string): string {
  const entry = READER_SECTION_LABELS[docType]?.[key];
  if (!entry) return key.replace(/_/g, " ");
  return language === "ro" ? entry.ro : entry.en;
}
