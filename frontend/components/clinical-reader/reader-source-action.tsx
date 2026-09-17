"use client";

/**
 * Shared "View source" action for the Phase 8 clinical reader — every
 * lab row, medication row, and the document header itself resolves
 * provenance through this ONE component, reusing the existing
 * `openSourceEvidence`/RightWorkspace system (never a second source
 * viewer). The reader API already returns a `source_evidence_id`
 * per fact, so unlike the older per-lab-row pattern elsewhere in the
 * app, this never needs its own network round trip before opening the
 * viewer.
 *
 * Honesty rule (V3 contract, "DOCX/non-PDF sources"): the shared viewer
 * is PDF.js-only — it has no non-PDF rendering path at all. Rather than
 * handing it a file it cannot open, a non-PDF document's source action
 * degrades to an honest label instead of a broken/blank viewer.
 */

import { captureVisualAnchor, useSourceViewer } from "@/components/source-viewer/source-viewer-context";
import { IconExternal } from "@/components/ui/icon";
import { useLanguage } from "@/lib/i18n";

const PDF_CONTENT_TYPE = "application/pdf";

export function isPdfContentType(contentType?: string | null): boolean {
  // No content_type on record is treated as PDF (the app's overwhelming
  // default upload format, and today's discharge pipeline only reads
  // PDF pages) — never treated as a reason to hide the action entirely.
  return !contentType || contentType === PDF_CONTENT_TYPE;
}

export function ReaderSourceAction({
  sourceEvidenceId,
  documentContentType,
  label,
}: {
  sourceEvidenceId: number | null;
  documentContentType?: string | null;
  /** Override the default "View source" copy — e.g. a compact icon-only
   * context. */
  label?: string;
}) {
  const { language } = useLanguage();
  const { openSourceEvidence } = useSourceViewer();

  const copy =
    language === "ro"
      ? { view: label || "Vezi sursa", unavailable: "Sursă indisponibilă", nonPdf: "Sursă text" }
      : { view: label || "View source", unavailable: "Source unavailable", nonPdf: "Source text" };

  if (sourceEvidenceId == null) {
    return (
      <span className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
        {copy.unavailable}
      </span>
    );
  }

  if (!isPdfContentType(documentContentType)) {
    return (
      <span className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
        {copy.nonPdf}
      </span>
    );
  }

  function handleOpen() {
    const anchor = captureVisualAnchor();
    openSourceEvidence(sourceEvidenceId as number, anchor);
  }

  return (
    <button type="button" className="b-btn b-btn-ghost b-btn-sm b-source-action" onClick={handleOpen}>
      <IconExternal size={12} />
      {copy.view}
    </button>
  );
}
