/**
 * TypeScript mirror of the backend's typed, versioned structured
 * clinical-document schema — Clinical Document Intelligence V3, Phase 3
 * (see `backend/app/services/clinical_document/schema.py`, the
 * authoritative definition; keep this file in sync with it by hand,
 * there is no codegen step for this yet).
 *
 * Consumed by the Phase 8 discharge/clinical-document reader
 * (`frontend/app/documents/[id]/discharge/page.tsx` and its
 * components) via `GET /documents/{id}/clinical-reader`'s
 * `ClinicalReaderResponse` shape, defined at the bottom of this file.
 */

export const CANONICAL_SECTION_KEYS = [
  "overview",
  "administrative_information",
  "encounter_details",
  "diagnoses",
  "medical_history",
  "examination",
  "clinical_course",
  "investigations",
  "laboratory_results",
  "imaging",
  "procedures",
  "treatment",
  "medications",
  "discharge_medications",
  "recommendations",
  "follow_up",
  "prescriptions",
  "signatures",
  "other",
] as const;

export type CanonicalSectionKey = (typeof CANONICAL_SECTION_KEYS)[number];

export type EventType =
  | "admission"
  | "follow_up"
  | "procedure"
  | "treatment_change"
  | "investigation"
  | "discharge"
  | "consultation"
  | "other";

export type ReviewState = "auto" | "needs_review" | "reviewed";

// ── Typed block forms — a discriminated union on `type`, mirroring the
// backend's Pydantic discriminated union exactly. A block that
// references labs/medications/dated-events carries IDs, never a copy of
// that data — see the backend schema's own docstring for why.

export interface ParagraphBlock {
  type: "paragraph";
  text: string;
}

export interface KeyValueItem {
  key: string;
  value: string;
}

export interface KeyValueBlock {
  type: "key_value";
  items: KeyValueItem[];
}

export interface BulletListBlock {
  type: "bullet_list";
  items: string[];
}

export interface TableBlock {
  type: "table";
  headers: string[];
  rows: string[][];
}

/** References StructuredClinicalDocument.dated_events[].source_event_id
 * — never a copy of an event's own data (Phase 5). */
export interface DatedEventGroupBlock {
  type: "dated_event_group";
  event_ids: string[];
}

/** References real LabResult ids (Phase 6) — a pointer into the
 * existing canonical lab table, never a second lab datastore. */
export interface LabReportReferenceBlock {
  type: "lab_report_reference";
  lab_result_ids: number[];
}

/** References real PatientMedication ids (Phase 7). */
export interface MedicationListBlock {
  type: "medication_list";
  medication_ids: number[];
}

export interface PrescriptionRow {
  drug_text: string;
  dose_text: string | null;
  /** Populated once Phase 7's extraction resolves this row against
   * PatientMedication — null until then, never fabricated. */
  medication_id: number | null;
}

export interface PrescriptionTableBlock {
  type: "prescription_table";
  rows: PrescriptionRow[];
}

/** An in-place flag for a suspicious/implausible source value (e.g. "AV
 * 1008 bpm") — the value itself stays exactly as written wherever it
 * actually appears; this block never holds a "corrected" value, only
 * the warning text and, where known, the SourceEvidence this concerns. */
export interface WarningBlock {
  type: "warning";
  message: string;
  source_evidence_ids: number[];
}

export type ClinicalBlock =
  | ParagraphBlock
  | KeyValueBlock
  | BulletListBlock
  | TableBlock
  | DatedEventGroupBlock
  | LabReportReferenceBlock
  | MedicationListBlock
  | PrescriptionTableBlock
  | WarningBlock;

/** Clinical Reader Intelligence V2 — whether a section/event belongs to
 * the CURRENT encounter being discharged, or to historical narrative
 * embedded in the same document. Set ONLY by the AI interpreter — never
 * guessed by a deterministic parser. `null`/absent means "the
 * interpreter never ran or couldn't confidently tell" — never rendered
 * as if it were "current". */
export type EncounterScope = "current" | "historical" | "unspecified";

export interface ClinicalSection {
  id: string;
  canonical_key: CanonicalSectionKey;
  display_title: string;
  source_headings: string[];
  order: number;
  blocks: ClinicalBlock[];
  /** Real SourceEvidence ids this section's content is grounded in. */
  source_evidence_ids: number[];
  confidence: number | null;
  review_state: ReviewState | null;
  encounter_scope: EncounterScope | null;
  /** Deterministic (non-AI) signal: this section's only real content is
   * a form template with no patient-specific values (e.g. "PRODUS /
   * CANTITATE" with nothing filled in). The intelligent-reader view
   * suppresses a section flagged this way — it remains visible in
   * Original/Full source narrative mode, never deleted. */
  is_template_only: boolean;
}

export interface ClinicalEvent {
  source_event_id: string;
  raw_date_text: string;
  normalized_date: string | null;
  date_confidence: number;
  event_type: EventType;
  raw_text: string;
  structured_observations: string[];
  medication_changes: string[];
  procedures: string[];
  source_evidence_ids: number[];
  warnings: string[];
  encounter_scope: EncounterScope | null;
  /** True when this event's raw_text was judged (conservatively) to be
   * a near-duplicate of another event already in this document —
   * PRESENTATION consolidation only; the event and its source
   * references are never deleted. */
  is_repeated_in_source: boolean;
}

/** A pointer to a derived artifact (Phase 6's derived lab report, today
 * the only kind) built FROM this document — never a second copy of that
 * artifact's data. */
export interface DerivedArtifactRef {
  artifact_type: "lab_report";
  document_id: number | null;
  source_section_id: string | null;
  lab_result_ids: number[];
  /** Phase 6's deterministic coherent-report identity — distinguishes
   * multiple derived artifacts sharing the same source_section_id. */
  group_key: string | null;
}

export interface ClinicalDocumentMetadata {
  patient_name: string | null;
  date_of_birth: string | null;
  sex: string | null;
  admission_date: string | null;
  discharge_date: string | null;
  hospital_name: string | null;
  department: string | null;
  referring_doctor: string | null;
}

// ── Clinical Reader Intelligence V2 — AI-derived, grounded semantic
// items. All additive on the backend; all optional-shaped defensively
// here too (a document produced before this existed simply omits them,
// which the backend already represents as empty arrays / null, never
// undefined — but TS consumers should still treat every array here as
// "may be empty", never assume length > 0).

export type DiagnosisRole = "principal" | "secondary" | "historical";

/** A real diagnosis concept, grounded in source — never an AI
 * translation of the source wording. A blank/placeholder diagnosis
 * field is never represented as a Diagnosis at all. */
export interface Diagnosis {
  id: string;
  code: string | null;
  text: string;
  role: DiagnosisRole;
  source_section_id: string | null;
  source_segment_ids: string[];
  source_evidence_ids: number[];
}

export type InvestigationType = "imaging" | "molecular" | "pathology" | "ecg" | "procedure" | "other";

/** A real investigation FINDING, whether from an explicit form field or
 * recognized inside narrative prose. `conclusion` is only ever populated
 * from what the source itself states. */
export interface Investigation {
  id: string;
  investigation_type: InvestigationType;
  title: string;
  findings: string | null;
  conclusion: string | null;
  source_section_id: string | null;
  source_segment_ids: string[];
  source_evidence_ids: number[];
}

export type AnomalyType =
  | "impossible_or_unusual_date"
  | "physiologically_implausible_value"
  | "conflicting_source_values"
  | "repeated_source_text"
  | "ocr_uncertain"
  | "demographic_context_mismatch"
  | "template_placeholder"
  | "chronology_uncertain";

/** A candidate source anomaly. `original_value` is ALWAYS the verbatim
 * source value — there is no field for a "corrected" value, ever. */
export interface AnomalyFlag {
  id: string;
  anomaly_type: AnomalyType;
  message: string;
  original_value: string | null;
  source_segment_ids: string[];
  source_evidence_ids: number[];
}

export type RecommendationCategory =
  | "activity"
  | "hydration"
  | "diet"
  | "precautions"
  | "follow_up"
  | "medication_recommendation"
  | "specialist_follow_up"
  | "other";

export interface RecommendationItem {
  id: string;
  category: RecommendationCategory;
  text: string;
  source_section_id: string | null;
  source_segment_ids: string[];
  source_evidence_ids: number[];
}

/** A semantic grouping of the longitudinal clinical course into a named
 * era — always grounded in real `dated_events` (`event_ids`), never a
 * hard-coded/invented date range. */
export interface TreatmentEra {
  id: string;
  label: string;
  start_date: string | null;
  end_date: string | null;
  description: string;
  event_ids: string[];
  /** Source Intelligence + Provenance V2 — the union of real
   * SourceEvidence ids already resolved for every event in `event_ids`.
   * A treatment era is a multi-source summary by definition, so this is
   * never one fake "exact" source — see the "View sources (N)" reader UI. */
  source_evidence_ids: number[];
}

/** A dedicated pointer to what makes up THIS encounter/hospitalization —
 * never a copy of section/event data, just the ids that belong to it. */
export interface CurrentEncounter {
  admission_date: string | null;
  discharge_date: string | null;
  section_ids: string[];
  event_ids: string[];
}

export type InterpretationStatus = "complete" | "partial" | "failed" | "unavailable";

/** Versioning/audit record for the AI Clinical Document Interpreter's
 * pass over this document. `null` on `StructuredClinicalDocument` means
 * the interpreter has never run — the reader should show the
 * deterministic-only view in that case, never imply enrichment happened. */
export interface InterpretationMetadata {
  schema_version: string;
  prompt_version: string;
  model: string;
  generated_at: string;
  status: InterpretationStatus;
  warnings: string[];
}

/** Source Intelligence + Provenance V2, Part 5 — honest page-coverage
 * bookkeeping. `null` on the document means "unknown", never "assumed
 * complete". */
export interface ExtractionCoverage {
  total_pages: number | null;
  attempted_pages: number;
  successful_pages: number;
  failed_pages: number[];
  warning_pages: number[];
  extraction_complete: boolean;
}

/** The root schema — mirrors backend `StructuredClinicalDocument`
 * exactly. `document_kind` reuses the same 16-value document-type
 * taxonomy the rest of the app already uses (see
 * `frontend/lib/document-taxonomy-labels.ts`), not a separate enum. */
export interface StructuredClinicalDocument {
  schema_version: string;
  parser_version: string;
  document_kind: string;
  source_language: string | null;
  metadata: ClinicalDocumentMetadata;
  sections: ClinicalSection[];
  dated_events: ClinicalEvent[];
  derived_artifacts: DerivedArtifactRef[];
  warnings: string[];
  diagnoses: Diagnosis[];
  investigations: Investigation[];
  anomalies: AnomalyFlag[];
  recommendations: RecommendationItem[];
  treatment_eras: TreatmentEra[];
  current_encounter: CurrentEncounter | null;
  interpretation: InterpretationMetadata | null;
  extraction_coverage: ExtractionCoverage | null;
}

// ── Outline labels (Phase 8E) — canonical navigation, never the raw
// source heading. "other" is deliberately included (a section can
// genuinely need it) but the reader only shows it in the outline when
// it actually has content, same rule as every other canonical key.
export const CANONICAL_SECTION_LABELS: Record<CanonicalSectionKey, string> = {
  overview: "Overview",
  administrative_information: "Administrative information",
  encounter_details: "Encounter",
  diagnoses: "Diagnoses",
  medical_history: "Medical history",
  examination: "Examination",
  clinical_course: "Clinical course",
  investigations: "Investigations",
  laboratory_results: "Laboratory results",
  imaging: "Imaging",
  procedures: "Procedures",
  treatment: "Treatment",
  medications: "Medications",
  discharge_medications: "Discharge medications",
  recommendations: "Recommendations",
  follow_up: "Follow-up",
  prescriptions: "Prescriptions",
  signatures: "Signatures",
  other: "Other",
};

// ── Phase 8 reader API contract — GET /documents/{id}/clinical-reader.
// See backend/app/api/routers/documents.py::get_clinical_reader_payload
// for the authoritative response shape this mirrors.

export interface ReaderLabResult {
  id: number;
  raw_test_name: string | null;
  canonical_name: string | null;
  display_name: string | null;
  category: string | null;
  source_section: string | null;
  value: string | null;
  flag: string | null;
  reference_range: string | null;
  unit: string | null;
  observation_datetime: string | null;
  verification_state: string | null;
  source_evidence_id: number | null;
}

export interface ReaderMedication {
  id: number;
  name: string;
  dose_strength: string | null;
  frequency: string | null;
  route_form: string | null;
  status: string;
  is_uncertain: boolean;
  start_date: string | null;
  stop_date: string | null;
  /** "explicit" | "derived" | "explicit_with_derived_conflict" | null —
   * see backend models.py's PatientMedication.stop_date_basis docstring.
   * NEVER render a "derived" stop_date as if the source wrote it. */
  stop_date_basis: string | null;
  extra_info: string | null;
  source_segment_id: string | null;
  source_evidence_id: number | null;
}

export interface ReaderDocumentMeta {
  id: number;
  public_id: string | null;
  /** Post-Phase-10 integration fix — the one field the discharge
   * reader's own Ask Bragi target needs and previously did not have
   * (it passed `document.id` in its place, a real bug: see
   * app-shell/documents.py commit history). Mirrors the generic
   * /documents/{id} payload's own `patient_id` field. */
  patient_id: number;
  filename: string;
  content_type: string | null;
  document_type: string | null;
  report_name: string | null;
  report_type: string | null;
  source_language: string | null;
  test_date: string | null;
  created_at: string | null;
  is_verified: boolean;
  /** Always present — a document-level SourceEvidence anchor for the
   * header's "View original" / "Open original file" action. Never a
   * fabricated PDF page/bbox; see ensure_document_level_evidence. For a
   * derived artifact this anchor points at the PARENT's real file, since
   * the derived artifact itself has no upload of its own. */
  document_level_source_evidence_id: number;
  /** Phase 9 — "lab_report" for a derived lab artifact, null for every
   * ordinary document (and for a Reducto Split child, which also uses
   * parent_document_id but never sets this marker). */
  derived_artifact_kind: string | null;
}

/** Phase 9 — present only when `document.derived_artifact_kind` is set.
 * Resolved server-side from the derived artifact's own note_body pointer
 * (group_key/source_section_id/lab_result_ids) plus its parent row — never
 * a copy of parent data, just enough to render "Derived from: X" and a
 * working parent-navigation link. */
export interface ReaderDerivedArtifact {
  kind: string;
  group_key: string | null;
  source_section_id: string | null;
  parent_document_id: number | null;
  parent_report_name: string | null;
  parent_filename: string | null;
  parent_document_type: string | null;
  /** The parent's real content_type — ReaderSourceAction's PDF-vs-non-PDF
   * check must gate on this, never the derived artifact's own (it has no
   * file of its own; "View source" always opens the parent's file). */
  parent_content_type: string | null;
}

export interface ClinicalReaderResponse {
  document: ReaderDocumentMeta;
  /** null only if note_body is empty/unparseable/genuinely not a
   * clinical document at all — the reader must show an honest "no
   * structured content" state, never crash. Always null for a derived
   * lab artifact (it has no StructuredClinicalDocument of its own). */
  structured_document: StructuredClinicalDocument | null;
  labs: ReaderLabResult[];
  medications: ReaderMedication[];
  derived_artifact: ReaderDerivedArtifact | null;
}
