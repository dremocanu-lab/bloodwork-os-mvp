"use client";

/**
 * Compact, restrained clinical document header (Phase 8D). No hero
 * card, no gradients — a document type/title/institution/date line
 * plus two small header actions.
 */

import { useState } from "react";
import { IconAlert } from "@/components/ui/icon";
import { Status } from "@/components/ui";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import type { ClinicalDocumentMetadata, ExtractionCoverage, ReaderDocumentMeta } from "@/lib/clinical-document-schema";
import { isPdfContentType, ReaderSourceAction } from "./reader-source-action";

type Props = {
  document: ReaderDocumentMeta;
  metadata?: ClinicalDocumentMetadata | null;
  /** Source Intelligence + Provenance V2, Part 5 — when present and
   * incomplete, this must be surfaced honestly rather than letting the
   * reader imply the whole document was processed. `undefined`/`null`
   * (no coverage information at all — every document extracted before
   * this field existed) renders nothing, same as before this existed. */
  extractionCoverage?: ExtractionCoverage | null;
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function DocumentHeader({ document, metadata, extractionCoverage }: Props) {
  const { language } = useLanguage();
  const [opening, setOpening] = useState(false);
  const isPdf = isPdfContentType(document.content_type);

  const copy =
    language === "ro"
      ? {
          verified: "Verificat",
          unverified: "Neverificat",
          openFile: "Deschide fișierul original",
          incompleteExtraction: (successful: number, total: number) =>
            `Doar ${successful} din ${total} pagini au putut fi extrase din documentul original — restul pot conține informații clinice care nu apar în această fișă.`,
        }
      : {
          verified: "Verified",
          unverified: "Unverified",
          openFile: "Open original file",
          incompleteExtraction: (successful: number, total: number) =>
            `Only ${successful} of ${total} pages could be extracted from the original document — the rest may contain clinical information not reflected here.`,
        };

  async function handleOpenOriginalFile() {
    if (opening) return;
    setOpening(true);
    try {
      const response = await api.get(`/documents/${document.id}/file`, { responseType: "blob" });
      const blob = new Blob([response.data], { type: document.content_type || undefined });
      const fileUrl = window.URL.createObjectURL(blob);
      window.open(fileUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => window.URL.revokeObjectURL(fileUrl), 60_000);
    } catch {
      // A failed open here is non-critical — the reader itself keeps
      // working; nothing else on the page depends on this succeeding.
    } finally {
      setOpening(false);
    }
  }

  const metaLine = [
    metadata?.hospital_name,
    document.test_date ? formatDate(document.test_date) : null,
    metadata?.admission_date || metadata?.discharge_date
      ? `${metadata?.admission_date || "—"} → ${metadata?.discharge_date || "—"}`
      : null,
  ].filter(Boolean);

  const showIncompleteExtractionWarning =
    extractionCoverage != null && extractionCoverage.extraction_complete === false && extractionCoverage.total_pages != null;

  return (
    <>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "flex-start",
          paddingBottom: "var(--s3)",
          borderBottom: "1px solid var(--border)",
          marginBottom: showIncompleteExtractionWarning ? 0 : "var(--s4)",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: "var(--fs-h2, 20px)", fontWeight: 700, margin: 0, lineHeight: 1.3 }}>
            {document.report_name || document.filename}
          </h1>
          {metaLine.length > 0 ? (
            <div className="b-meta" style={{ fontSize: "var(--fs-caption)", marginTop: 4, display: "flex", gap: 10, flexWrap: "wrap" }}>
              {metaLine.map((item, i) => (
                <span key={i}>{item}</span>
              ))}
            </div>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <Status tone={document.is_verified ? "ok" : "muted"}>{document.is_verified ? copy.verified : copy.unverified}</Status>
          {isPdf ? (
            <ReaderSourceAction sourceEvidenceId={document.document_level_source_evidence_id} documentContentType={document.content_type} />
          ) : (
            <button type="button" className="b-btn b-btn-ghost b-btn-sm" onClick={handleOpenOriginalFile} disabled={opening}>
              {copy.openFile}
            </button>
          )}
        </div>
      </header>
      {showIncompleteExtractionWarning ? (
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
            padding: "10px 12px",
            marginBottom: "var(--s4)",
            borderRadius: "var(--r-md)",
            background: "var(--warn-bg, rgba(176, 137, 0, 0.08))",
            border: "1px solid var(--warn, #b08900)",
            fontSize: "var(--fs-caption)",
          }}
        >
          <IconAlert size={14} />
          <span>{copy.incompleteExtraction(extractionCoverage!.successful_pages, extractionCoverage!.total_pages!)}</span>
        </div>
      ) : null}
    </>
  );
}
