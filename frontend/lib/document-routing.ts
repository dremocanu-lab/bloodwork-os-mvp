/**
 * Clinical Document Intelligence V3 — canonical document routing.
 *
 * ONE shared resolver for "which reader should this document open in" —
 * previously duplicated, inconsistently, across 5 separate frontend
 * files (some missing the derived-artifact check entirely; only one of
 * the five ever consulted `document_type` at all). See docs/
 * clinical_document_v3/ROUTER_AUDIT.md for the full audit this
 * consolidation is based on.
 *
 * Routing priority (never replaces the legacy fallback — see the real
 * root-cause finding below):
 *   1. `derived_artifact_kind === "lab_report"` → the standalone lab
 *      report reader (Phase 9). Always checked first: a derived
 *      artifact also has `parent_document_id` set like an ordinary
 *      Reducto Split child, but never has a matching `section`/
 *      `report_type`, so it would otherwise silently fall through.
 *   2. A discharge-shaped document → the Phase 8 canonical reader.
 *      Checked via document_type === "discharge_summary" OR'd with the
 *      pre-existing legacy signals (section === "discharge_summary",
 *      report_type === "Discharge summary"/"discharge_summary") — never
 *      REPLACING them. `document_type` is not reliably populated on
 *      every upload path today (only the patient self-upload auto-
 *      classify path sets it; a doctor/care-partner upload that picks
 *      "Discharge Summary" from the section picklist leaves
 *      `document_type` null but `section` correct) — using it as the
 *      SOLE authority would break MORE documents than it fixes.
 *   3. Otherwise the generic reader.
 *
 * Real root cause found during the Phase 10→11 integration audit,
 * worth knowing before extending this further: `LEGACY_SECTION_BY_
 * DOCUMENT_TYPE` (backend/app/services/document_taxonomy.py) maps
 * `HOSPITAL_ADMISSION_NOTE`/`EMERGENCY_DEPARTMENT_NOTE`/
 * `OPERATIVE_REPORT` to the legacy section `"hospitalizations"`, not
 * `"discharge_summary"` — a real hospital discharge letter the
 * classifier tags as one of those NEVER matches the legacy `section ===
 * "discharge_summary"` check, regardless of any frontend routing fix.
 * This resolver does not attempt to second-guess that classification
 * (whether an admission note should open the SAME reader as a discharge
 * summary is a genuine product decision, not a routing bug) — it is
 * recorded here, and in the router audit doc, as a known, deliberately
 * out-of-scope observation for a future session to decide.
 */

export type RoutableDocument = {
  derived_artifact_kind?: string | null;
  document_type?: string | null;
  section?: string | null;
  report_type?: string | null;
};

export function isDischargeShapedDocument(doc: RoutableDocument): boolean {
  return (
    doc.document_type === "discharge_summary" ||
    doc.section === "discharge_summary" ||
    doc.report_type === "Discharge summary" ||
    doc.report_type === "discharge_summary"
  );
}

export function isDerivedLabReportDocument(doc: RoutableDocument): boolean {
  return doc.derived_artifact_kind === "lab_report";
}

/** The one function every "open this document" call site should use.
 * `documentId` accepts a string OR number since some call sites have a
 * route param (string) and others have an already-numeric id. */
export function resolveDocumentRoute(doc: RoutableDocument, documentId: number | string): string {
  if (isDerivedLabReportDocument(doc)) return `/documents/${documentId}/lab-report`;
  if (isDischargeShapedDocument(doc)) return `/documents/${documentId}/discharge`;
  return `/documents/${documentId}`;
}
