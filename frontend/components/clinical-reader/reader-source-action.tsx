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

import { useState } from "react";
import { captureVisualAnchor, useSourceViewer } from "@/components/source-viewer/source-viewer-context";
import { IconChevronLeft, IconChevronRight, IconExternal } from "@/components/ui/icon";
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

/**
 * Source Intelligence + Provenance V2, Part 33 — a multi-source AI
 * summary (e.g. a treatment era grouping several dated events) never
 * gets one fake "exact" source; this renders "View sources (N)" and, once
 * open, a "previous / N of M / next" cycler that re-opens the SAME
 * shared viewer at each real evidence id in turn — never a second
 * source-viewing surface. Degrades to the plain single `ReaderSourceAction`
 * when there's only one evidence id, so callers can pass either kind of
 * item through this ONE component without branching themselves.
 */
export function MultiSourceAction({
  sourceEvidenceIds,
  documentContentType,
}: {
  sourceEvidenceIds: number[];
  documentContentType?: string | null;
}) {
  const { language } = useLanguage();
  const { openSourceEvidence } = useSourceViewer();
  const [index, setIndex] = useState(0);
  const [cycling, setCycling] = useState(false);

  const copy =
    language === "ro"
      ? {
          viewSources: (n: number) => `Vezi sursele (${n})`,
          of: (i: number, n: number) => `${i} din ${n}`,
          prev: "Sursa anterioară",
          next: "Sursa următoare",
        }
      : {
          viewSources: (n: number) => `View sources (${n})`,
          of: (i: number, n: number) => `${i} of ${n}`,
          prev: "Previous source",
          next: "Next source",
        };

  if (sourceEvidenceIds.length === 0) {
    return <ReaderSourceAction sourceEvidenceId={null} documentContentType={documentContentType} />;
  }
  if (sourceEvidenceIds.length === 1) {
    return <ReaderSourceAction sourceEvidenceId={sourceEvidenceIds[0]} documentContentType={documentContentType} />;
  }

  if (!isPdfContentType(documentContentType)) {
    return (
      <span className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
        {language === "ro" ? "Sursă text" : "Source text"}
      </span>
    );
  }

  function open(i: number) {
    const clamped = Math.max(0, Math.min(sourceEvidenceIds.length - 1, i));
    setIndex(clamped);
    const anchor = captureVisualAnchor();
    openSourceEvidence(sourceEvidenceIds[clamped], anchor);
  }

  if (!cycling) {
    return (
      <button
        type="button"
        className="b-btn b-btn-ghost b-btn-sm b-source-action"
        onClick={() => {
          setCycling(true);
          open(0);
        }}
      >
        <IconExternal size={12} />
        {copy.viewSources(sourceEvidenceIds.length)}
      </button>
    );
  }

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button
        type="button"
        className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
        onClick={() => open(index - 1)}
        disabled={index <= 0}
        aria-label={copy.prev}
        title={copy.prev}
      >
        <IconChevronLeft size={13} />
      </button>
      <span className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
        {copy.of(index + 1, sourceEvidenceIds.length)}
      </span>
      <button
        type="button"
        className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
        onClick={() => open(index + 1)}
        disabled={index >= sourceEvidenceIds.length - 1}
        aria-label={copy.next}
        title={copy.next}
      >
        <IconChevronRight size={13} />
      </button>
    </div>
  );
}
