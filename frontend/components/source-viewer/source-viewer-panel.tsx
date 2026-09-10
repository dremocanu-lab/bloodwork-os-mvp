"use client";

/**
 * The actual rendering surface for the shared Bragi source viewer:
 * PDF.js page canvas + bbox highlight overlay + restrained controls.
 * Used both in the desktop split layout and the mobile/tablet full-screen
 * sheet (see app/layout.tsx for how each is composed) — one
 * implementation, reused, not two PDF viewers.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { PDFPageProxy, RenderTask } from "pdfjs-dist";
import {
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconFitWidth,
  IconZoomIn,
  IconZoomOut,
} from "@/components/ui/icon";
import { useLanguage } from "@/lib/i18n";
import { useSourceViewer } from "./source-viewer-context";

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;

export function SourceViewerPanel({ variant }: { variant: "split" | "sheet" }) {
  const { language } = useLanguage();
  const { data, pdfDoc, loading, error, currentPage, setCurrentPage, close, retry } = useSourceViewer();

  const containerRef = useRef<HTMLDivElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);

  const [fitWidthScale, setFitWidthScale] = useState(1);
  const [zoomOverride, setZoomOverride] = useState<number | null>(null);
  const [pageRendering, setPageRendering] = useState(false);
  const [renderError, setRenderError] = useState("");
  const [renderRetryKey, setRenderRetryKey] = useState(0);

  const scale = zoomOverride ?? fitWidthScale;
  const numPages = pdfDoc?.numPages ?? 0;

  const labels = useMemo(
    () =>
      language === "ro"
        ? {
            close: "Închide",
            prevPage: "Pagina anterioară",
            nextPage: "Pagina următoare",
            zoomIn: "Mărește",
            zoomOut: "Micșorează",
            fitWidth: "Potrivește lățimea",
            loading: "Se încarcă documentul original...",
            renderingPage: "Se randează pagina...",
            pageOf: (p: number, n: number) => `Pagina ${p} din ${n}`,
            noExactLocation: "Locația exactă nu este disponibilă — se afișează documentul.",
            pageOnly: "Pagina exactă este cunoscută; poziția precisă nu este disponibilă.",
            openError: "Documentul original nu a putut fi deschis.",
            retry: "Încearcă din nou",
            sourceText: "Text sursă",
          }
        : {
            close: "Close",
            prevPage: "Previous page",
            nextPage: "Next page",
            zoomIn: "Zoom in",
            zoomOut: "Zoom out",
            fitWidth: "Fit width",
            loading: "Loading original document...",
            renderingPage: "Rendering page...",
            pageOf: (p: number, n: number) => `Page ${p} of ${n}`,
            noExactLocation: "Exact location isn't available — showing the document.",
            pageOnly: "The exact page is known; precise position isn't available.",
            openError: "The original document couldn't be opened.",
            retry: "Try again",
            sourceText: "Source text",
          },
    [language]
  );

  // Keep "fit width" scale current as the container resizes (split ratio
  // change, browser resize, orientation change) — bbox alignment survives
  // because the highlight is positioned in percentages of the canvas
  // wrapper, which resizes together with the canvas itself.
  useEffect(() => {
    if (!containerRef.current || !pdfDoc) return;
    let cancelled = false;

    async function computeFitWidth() {
      const page = await pdfDoc!.getPage(currentPage);
      if (cancelled || !containerRef.current) return;
      const baseViewport = page.getViewport({ scale: 1 });
      const available = containerRef.current.clientWidth - 32; // panel padding
      // The split pane can report a near-zero/negative clientWidth for a
      // frame or two right after it first mounts (before the flex layout
      // has actually resolved) — committing that would fit-scale the page
      // down to MIN_SCALE and, combined with nothing giving the canvas
      // wrapper a floor size (see .b-source-viewer-canvas-wrap's
      // min-height/min-width in globals.css), collapse the whole viewer to
      // a sliver. Skip a degenerate measurement rather than commit it; the
      // ResizeObserver below fires again once the container has real
      // layout and recomputes correctly.
      if (available < 80) return;
      setFitWidthScale(Math.max(MIN_SCALE, Math.min(MAX_SCALE, available / baseViewport.width)));
    }

    computeFitWidth();

    const observer = new ResizeObserver(() => computeFitWidth());
    observer.observe(containerRef.current);
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [pdfDoc, currentPage]);

  // Reset manual zoom when the page or document changes — each page gets
  // a fresh "fit width" default rather than carrying over a stale zoom.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setZoomOverride(null);
  }, [currentPage, pdfDoc]);

  // Render the current page at the current scale, then position/scroll to
  // the bbox highlight once rendering completes.
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;
    setRenderError("");

    async function renderPage() {
      setPageRendering(true);
      let page: PDFPageProxy;
      try {
        page = await pdfDoc!.getPage(currentPage);
      } catch {
        if (!cancelled) {
          setRenderError("Could not load this page.");
          setPageRendering(false);
        }
        return;
      }
      if (cancelled) return;

      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      if (!canvas) return;
      const context = canvas.getContext("2d");
      if (!context) return;

      // High-DPI rendering: the canvas BUFFER is sized up by the device
      // pixel ratio so text/lines stay crisp on Retina/HiDPI displays,
      // while the canvas's own CSS box (and the wrapper the bbox
      // highlight positions itself against, in percentages) stays at the
      // un-scaled viewport size — so this only affects sharpness, never
      // highlight alignment. Capped at 2x: real quality gain beyond that
      // is imperceptible for document text and not worth the extra memory
      // on a 3x+ device for a page that might already be large.
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(viewport.width * dpr);
      canvas.height = Math.round(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      if (canvasWrapRef.current) {
        canvasWrapRef.current.style.width = `${viewport.width}px`;
        canvasWrapRef.current.style.height = `${viewport.height}px`;
      }

      renderTaskRef.current?.cancel();
      const task = page.render({
        canvasContext: context,
        viewport,
        canvas,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      });
      renderTaskRef.current = task;

      try {
        await task.promise;
      } catch (err) {
        if (err instanceof Error && err.name === "RenderingCancelledException") return;
        if (!cancelled) setRenderError("Could not render this page.");
      } finally {
        if (!cancelled) setPageRendering(false);
      }

      if (!cancelled && highlightRef.current && data?.precision === "exact_bbox") {
        // Center the highlighted evidence in the visible area — the core
        // "user should not have to find it manually" requirement.
        highlightRef.current.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
          block: "center",
          inline: "center",
        });
      }
    }

    renderPage();

    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [pdfDoc, currentPage, scale, data?.precision, renderRetryKey]);

  const canZoomIn = scale < MAX_SCALE;
  const canZoomOut = scale > MIN_SCALE;

  // Prefer the derived "whole row" presentation region for lab evidence —
  // it's the same real geometry unioned + padded server-side (see
  // BRAGI_REDUCTO_PLAN.md), never a separate guess. Falls back to the raw
  // single-field bbox (still provenance-accurate, just narrower) when a row
  // region wasn't available — e.g. non-lab evidence, or a row with fewer
  // than two field citations to union.
  const hasRowBbox =
    data?.row_bbox_x != null &&
    data?.row_bbox_y != null &&
    data?.row_bbox_width != null &&
    data?.row_bbox_height != null;

  const highlightBox = hasRowBbox
    ? {
        x: data!.row_bbox_x as number,
        y: data!.row_bbox_y as number,
        width: data!.row_bbox_width as number,
        height: data!.row_bbox_height as number,
      }
    : data?.bbox_x != null && data?.bbox_y != null && data?.bbox_width != null && data?.bbox_height != null
    ? { x: data.bbox_x, y: data.bbox_y, width: data.bbox_width, height: data.bbox_height }
    : null;

  const showBbox = data?.precision === "exact_bbox" && highlightBox != null;

  return (
    <div
      className={`b-source-viewer b-source-viewer-${variant}`}
      role="dialog"
      aria-modal={variant === "sheet" ? true : undefined}
      aria-label={data?.document_filename || labels.loading}
    >
      <div className="b-source-viewer-head">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="b-source-viewer-title" title={data?.document_filename}>
            {data?.report_name || data?.document_filename || " "}
          </div>
          {numPages > 0 ? (
            <div className="b-meta">{labels.pageOf(currentPage, numPages)}</div>
          ) : null}
        </div>

        <div className="b-source-viewer-controls">
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage <= 1 || !pdfDoc}
            aria-label={labels.prevPage}
            title={labels.prevPage}
          >
            <IconChevronLeft size={15} />
          </button>
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={() => setCurrentPage(Math.min(numPages, currentPage + 1))}
            disabled={currentPage >= numPages || !pdfDoc}
            aria-label={labels.nextPage}
            title={labels.nextPage}
          >
            <IconChevronRight size={15} />
          </button>
          <div className="b-source-viewer-sep" />
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={() => setZoomOverride(Math.max(MIN_SCALE, scale - 0.25))}
            disabled={!canZoomOut}
            aria-label={labels.zoomOut}
            title={labels.zoomOut}
          >
            <IconZoomOut size={15} />
          </button>
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={() => setZoomOverride(Math.min(MAX_SCALE, scale + 0.25))}
            disabled={!canZoomIn}
            aria-label={labels.zoomIn}
            title={labels.zoomIn}
          >
            <IconZoomIn size={15} />
          </button>
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={() => setZoomOverride(null)}
            aria-label={labels.fitWidth}
            title={labels.fitWidth}
          >
            <IconFitWidth size={15} />
          </button>
          <div className="b-source-viewer-sep" />
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={close}
            aria-label={labels.close}
            title={labels.close}
          >
            <IconClose size={15} />
          </button>
        </div>
      </div>

      {data?.precision === "page_only" ? (
        <div className="b-source-viewer-notice">{labels.pageOnly}</div>
      ) : data?.precision === "text_only" || data?.precision === "document_only" ? (
        <div className="b-source-viewer-notice">{labels.noExactLocation}</div>
      ) : null}

      <div className="b-source-viewer-body" ref={containerRef}>
        {loading ? (
          <div className="b-source-viewer-state">
            <span className="b-spinner" />
            <span>{labels.loading}</span>
          </div>
        ) : error ? (
          <div className="b-source-viewer-state">
            <span style={{ color: "var(--danger)" }}>{labels.openError}</span>
            <span className="muted-text" style={{ fontSize: "var(--fs-sm)" }}>
              {error}
            </span>
            <button type="button" className="b-btn b-btn-secondary b-btn-sm" onClick={retry}>
              {labels.retry}
            </button>
          </div>
        ) : (
          <div className="b-source-viewer-canvas-scroll">
            <div className="b-source-viewer-canvas-wrap" ref={canvasWrapRef}>
              <canvas ref={canvasRef} />
              {showBbox && highlightBox ? (
                <div
                  ref={highlightRef}
                  className="b-source-highlight"
                  style={{
                    left: `${highlightBox.x * 100}%`,
                    top: `${highlightBox.y * 100}%`,
                    width: `${highlightBox.width * 100}%`,
                    height: `${highlightBox.height * 100}%`,
                  }}
                />
              ) : null}
              {pageRendering ? (
                <div className="b-source-viewer-page-loading">
                  <span className="b-spinner" />
                  <span>{labels.renderingPage}</span>
                </div>
              ) : null}
              {renderError ? (
                <div className="b-source-viewer-page-error">
                  <span>{renderError}</span>
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => setRenderRetryKey((k) => k + 1)}
                  >
                    {labels.retry}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
