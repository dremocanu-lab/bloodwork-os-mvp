"use client";

/**
 * The right-hand workspace slot the root shell renders when the PDF
 * source viewer and/or the Ask Bragi contextual panel is open. Renders
 * whichever ONE is open directly; when BOTH happen to be open at once,
 * shows a small tab switcher above them instead of squeezing three
 * columns onto the screen (see BRAGI_ASK_BRAGI_PLAN.md's "PDF
 * integration" section) — both stay mounted (never unmounted while
 * open), so switching tabs never loses PDF page/zoom or the Ask Bragi
 * conversation, only toggles which one is visible.
 *
 * Deliberately does NOT touch SourceViewerPanel's internals — visibility
 * is toggled with the `hidden` attribute on a wrapping div, never a prop
 * into that component.
 */

import type { CSSProperties } from "react";
import { useState } from "react";
import { SourceViewerPanel } from "@/components/source-viewer/source-viewer-panel";
import { AskBragiPanel } from "./ask-bragi-panel";

type Tab = "source" | "askBragi";

export function RightWorkspace({
  sourceOpen,
  askBragiOpen,
  variant,
}: {
  sourceOpen: boolean;
  askBragiOpen: boolean;
  variant: "split" | "sheet";
}) {
  const [activeTab, setActiveTab] = useState<Tab>(askBragiOpen ? "askBragi" : "source");
  // React's own "adjusting state when a prop changes" pattern (storing
  // the previous values alongside, comparing during render) — NOT a
  // useEffect, so this can safely call setState mid-render without
  // tripping react-hooks/set-state-in-effect, and without an extra
  // render's lag before the tab switch is visible.
  const [prevOpen, setPrevOpen] = useState({ sourceOpen, askBragiOpen });
  if (prevOpen.sourceOpen !== sourceOpen || prevOpen.askBragiOpen !== askBragiOpen) {
    // A panel that just opened becomes the visible one; failing that, if
    // the currently-visible tab's own panel just closed while the other
    // remains open, show the one that's still open rather than a blank pane.
    if (sourceOpen && !prevOpen.sourceOpen) setActiveTab("source");
    else if (askBragiOpen && !prevOpen.askBragiOpen) setActiveTab("askBragi");
    else if (activeTab === "source" && !sourceOpen && askBragiOpen) setActiveTab("askBragi");
    else if (activeTab === "askBragi" && !askBragiOpen && sourceOpen) setActiveTab("source");
    setPrevOpen({ sourceOpen, askBragiOpen });
  }

  if (!sourceOpen && !askBragiOpen) return null;

  const showTabs = sourceOpen && askBragiOpen;

  // Sheet variant only: SourceViewerPanel and AskBragiPanel each apply
  // their OWN `position: fixed; inset: 0` full-viewport styling (see
  // .b-source-viewer-sheet / .b-ask-bragi-sheet) — correct when only one
  // is ever open, which is all either panel was ever built to expect on
  // its own. With both open, that fixed styling would cover this tab bar
  // too (a `position: fixed` descendant paints above in-flow siblings
  // regardless of DOM order, per normal CSS stacking rules), leaving no
  // way to switch back. `transform` here doesn't move anything (identity
  // transform) — it exists purely to make THIS div a new containing block
  // for `position: fixed` descendants, so their `inset: 0` resolves
  // against this wrapper (already the full viewport) instead of the true
  // viewport, and a higher z-index on the tab bar can then out-rank them
  // within that same local stacking context.
  const sheetBothOpenStyle: CSSProperties = showTabs
    ? { position: "fixed", inset: 0, zIndex: 100, transform: "translateZ(0)" }
    : {};

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        ...(variant === "sheet" ? sheetBothOpenStyle : {}),
      }}
    >
      {showTabs ? (
        <div
          className="b-segmented"
          role="tablist"
          aria-label="Workspace panel"
          style={{
            flexShrink: 0,
            margin: "var(--s2) var(--s2) 0",
            ...(variant === "sheet" ? { position: "relative", zIndex: 101 } : {}),
          }}
        >
          <button type="button" role="tab" aria-selected={activeTab === "source"} onClick={() => setActiveTab("source")}>
            Original
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "askBragi"}
            onClick={() => setActiveTab("askBragi")}
          >
            Ask Bragi
          </button>
        </div>
      ) : null}

      <div style={{ flex: 1, minHeight: 0 }} hidden={showTabs && activeTab !== "source"}>
        {sourceOpen ? <SourceViewerPanel variant={variant} /> : null}
      </div>
      <div style={{ flex: 1, minHeight: 0 }} hidden={showTabs && activeTab !== "askBragi"}>
        {askBragiOpen ? <AskBragiPanel variant={variant} /> : null}
      </div>
    </div>
  );
}
