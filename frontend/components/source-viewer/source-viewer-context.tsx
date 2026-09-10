"use client";

/**
 * Shared Bragi source-verification system — the single reusable way any
 * part of the app opens the original document a structured fact came
 * from, navigates to the exact page, and highlights the exact bbox.
 *
 * Call `openSourceEvidence(sourceEvidenceId)` from anywhere (Analize row,
 * chart point, Reader, Timeline, Documents, future Ask Bragi citation) —
 * the backend resolves and authorizes everything else. No PDF URL,
 * patient ID, page, or bbox is ever passed around by callers.
 *
 * Mounted once at the root layout (see app/layout.tsx), which also lays
 * out the desktop split view: main content + this panel side by side
 * when open, so "Analize + Original coexist" works for ANY page that
 * calls openSourceEvidence, not just ones that specifically build a
 * split layout.
 */

import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { api, getErrorMessage } from "@/lib/api";
import { ensurePdfWorkerConfigured, pdfjsLib } from "./pdf-worker";

export type SourcePrecision = "exact_bbox" | "page_only" | "text_only" | "document_only";

export type SourceEvidenceView = {
  source_evidence_id: number;
  document_id: number;
  document_filename: string;
  document_type: string | null;
  report_name: string | null;
  page_number: number | null;
  bbox_x: number | null;
  bbox_y: number | null;
  bbox_width: number | null;
  bbox_height: number | null;
  source_text: string | null;
  provider: string | null;
  precision: SourcePrecision;
};

type SourceViewerContextValue = {
  isOpen: boolean;
  loading: boolean;
  error: string;
  data: SourceEvidenceView | null;
  pdfDoc: PDFDocumentProxy | null;
  currentPage: number;
  setCurrentPage: (page: number) => void;
  openSourceEvidence: (sourceEvidenceId: number) => void;
  close: () => void;
  retry: () => void;
};

const SourceViewerContext = createContext<SourceViewerContextValue | null>(null);

export function useSourceViewer(): SourceViewerContextValue {
  const ctx = useContext(SourceViewerContext);
  if (!ctx) {
    throw new Error("useSourceViewer must be used within a SourceViewerProvider");
  }
  return ctx;
}

/** Non-throwing variant for components that render fine whether or not a
 * viewer happens to be mounted above them (defensive — the provider is
 * always mounted at root, but this avoids a hard crash if that ever
 * changes for one isolated surface). */
export function useSourceViewerOptional(): SourceViewerContextValue | null {
  return useContext(SourceViewerContext);
}

export function SourceViewerProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<SourceEvidenceView | null>(null);
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  // Same-document reuse (spec: don't reload the PDF unnecessarily when two
  // rows point at the same source file).
  const loadedDocumentIdRef = useRef<number | null>(null);
  const loadedPdfRef = useRef<PDFDocumentProxy | null>(null);
  const lastRequestedIdRef = useRef<number | null>(null);

  const loadEvidence = useCallback(async (sourceEvidenceId: number) => {
    lastRequestedIdRef.current = sourceEvidenceId;
    setIsOpen(true);
    setLoading(true);
    setError("");

    try {
      const response = await api.get<SourceEvidenceView>(`/source-evidence/${sourceEvidenceId}/view`);
      // A later open() call already superseded this one — drop the stale response.
      if (lastRequestedIdRef.current !== sourceEvidenceId) return;

      const view = response.data;
      setData(view);
      setCurrentPage(view.page_number || 1);

      if (loadedDocumentIdRef.current === view.document_id && loadedPdfRef.current) {
        setPdfDoc(loadedPdfRef.current);
        setLoading(false);
        return;
      }

      ensurePdfWorkerConfigured();
      const fileResponse = await api.get<ArrayBuffer>(`/documents/${view.document_id}/file`, {
        responseType: "arraybuffer",
      });
      if (lastRequestedIdRef.current !== sourceEvidenceId) return;

      const loadingTask = pdfjsLib.getDocument({ data: fileResponse.data });
      const doc = await loadingTask.promise;
      if (lastRequestedIdRef.current !== sourceEvidenceId) return;

      loadedDocumentIdRef.current = view.document_id;
      loadedPdfRef.current = doc;
      setPdfDoc(doc);
    } catch (err) {
      if (lastRequestedIdRef.current !== sourceEvidenceId) return;
      setError(getErrorMessage(err, "Could not open the original document."));
      setData((prev) => prev); // keep whatever metadata we got, if any
    } finally {
      if (lastRequestedIdRef.current === sourceEvidenceId) setLoading(false);
    }
  }, []);

  const openSourceEvidence = useCallback(
    (sourceEvidenceId: number) => {
      void loadEvidence(sourceEvidenceId);
    },
    [loadEvidence]
  );

  const retry = useCallback(() => {
    if (lastRequestedIdRef.current != null) void loadEvidence(lastRequestedIdRef.current);
  }, [loadEvidence]);

  const close = useCallback(() => {
    setIsOpen(false);
    lastRequestedIdRef.current = null;
    // Intentionally keep loadedPdfRef/loadedDocumentIdRef cached so
    // reopening the same document (a very common next action) is instant.
  }, []);

  const value = useMemo<SourceViewerContextValue>(
    () => ({
      isOpen,
      loading,
      error,
      data,
      pdfDoc,
      currentPage,
      setCurrentPage,
      openSourceEvidence,
      close,
      retry,
    }),
    [isOpen, loading, error, data, pdfDoc, currentPage, openSourceEvidence, close, retry]
  );

  return <SourceViewerContext.Provider value={value}>{children}</SourceViewerContext.Provider>;
}
