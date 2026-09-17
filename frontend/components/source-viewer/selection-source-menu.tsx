"use client";

/**
 * Pre-Phase-11 exact provenance session: select-source-text → contextual
 * menu → "Show in original", using the SAME `openSourceEvidence` engine
 * as every existing "View source" button (source-viewer-context.tsx) —
 * never a second source-resolution path.
 *
 * Mounted once at the root layout (see app-shell-with-source-viewer.tsx),
 * so it works on any page without per-page wiring — but it only ever
 * activates for a selection whose nearest tagged ancestor carries
 * `data-source-evidence-id` (see structured-lab-report.tsx /
 * medication-list.tsx for where that attribute is applied, and why it's
 * deliberately scoped to spans that hold the document's own extracted
 * text, never a Bragi-generated caption/label/status).
 *
 * Anchoring strategy: the browser's own Selection/Range API, read on
 * every `selectionchange` — never a custom text-offset model, and never
 * a global `document.contains(selectedText)` search (which would be
 * ambiguous for text repeated elsewhere on the page). A selection must
 * start and end inside the SAME tagged element to resolve at all; a
 * selection spanning two different evidence ids (or leaving the tagged
 * region entirely) resolves to nothing rather than guessing which one
 * the user meant.
 *
 * This is intentionally the smallest honest version of "select text →
 * show in original": it resolves to the same page/bbox precision the
 * tagged element's own `source_evidence_id` already has (exact per-field
 * rects for a lab row, once persisted — see reducto_extraction.py's
 * `_field_rects`), it does not attempt word-level anchoring WITHIN a
 * multi-sentence narrative paragraph, because no such paragraph carries
 * any source_evidence_id today (see the V3 handoff's "Pre-Phase-11 Exact
 * Provenance" section for why: Reducto's reader/section extraction runs
 * with `citations=False`, and `SourceSegment` is not persisted with a
 * page number at all — a real upstream gap, not a UI shortcut).
 */

import { useEffect, useRef, useState } from "react";
import { captureVisualAnchor, useSourceViewer } from "./source-viewer-context";
import { IconExternal } from "@/components/ui/icon";
import { useLanguage } from "@/lib/i18n";

const SOURCE_ATTR = "data-source-evidence-id";
const MENU_WIDTH = 176;

function elementFor(node: Node | null): Element | null {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
}

/** Resolves a live Selection to the single source_evidence_id it belongs
 * to, or null when the selection is empty, spans outside any tagged
 * element, or spans two different tagged elements (ambiguous — never
 * arbitrarily picks one). */
function resolveSourceEvidenceId(selection: Selection): number | null {
  if (selection.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!range.toString().trim()) return null;

  const startEl = elementFor(range.startContainer)?.closest(`[${SOURCE_ATTR}]`);
  const endEl = elementFor(range.endContainer)?.closest(`[${SOURCE_ATTR}]`);
  if (!startEl || !endEl || startEl !== endEl) return null;

  const raw = startEl.getAttribute(SOURCE_ATTR);
  const id = raw ? Number(raw) : NaN;
  return Number.isFinite(id) ? id : null;
}

type MenuState = { sourceEvidenceId: number; top: number; left: number };

export function SelectionSourceMenu() {
  const { language } = useLanguage();
  const { openSourceEvidence } = useSourceViewer();
  const [state, setState] = useState<MenuState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleSelectionChange() {
      const selection = window.getSelection();
      const sourceEvidenceId = selection ? resolveSourceEvidenceId(selection) : null;
      if (sourceEvidenceId == null || !selection) {
        setState(null);
        return;
      }

      const rect = selection.getRangeAt(0).getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        setState(null);
        return;
      }

      const left = Math.min(
        Math.max(8, rect.left + rect.width / 2 - MENU_WIDTH / 2),
        window.innerWidth - MENU_WIDTH - 8
      );
      const top = Math.min(rect.bottom + 8, window.innerHeight - 48);

      setState({ sourceEvidenceId, top, left });
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      window.getSelection()?.removeAllRanges();
      setState(null);
    }

    document.addEventListener("selectionchange", handleSelectionChange);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("selectionchange", handleSelectionChange);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  if (!state) return null;

  const copy = language === "ro" ? "Arată în original" : "Show in original";

  function handleClick() {
    if (!state) return;
    const anchor = captureVisualAnchor();
    openSourceEvidence(state.sourceEvidenceId, anchor);
    window.getSelection()?.removeAllRanges();
    setState(null);
  }

  return (
    <div
      ref={menuRef}
      className="b-menu b-selection-source-menu"
      role="menu"
      style={{ position: "fixed", top: state.top, left: state.left, width: "max-content", minWidth: 0, padding: 4 }}
    >
      <button
        type="button"
        className="b-menu-item"
        // Prevent this click from itself collapsing the text selection
        // before onClick runs (a mousedown outside the selected range
        // would otherwise clear it first).
        onMouseDown={(event) => event.preventDefault()}
        onClick={handleClick}
      >
        <IconExternal size={12} />
        {copy}
      </button>
    </div>
  );
}
