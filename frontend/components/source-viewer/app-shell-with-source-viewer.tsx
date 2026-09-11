"use client";

/**
 * Composes the root layout with the shared source viewer AND the Ask
 * Bragi contextual panel: desktop gets a real split view (main content +
 * a right-hand workspace, side by side, no overlay/no backdrop — see
 * .b-app-split in globals.css); tablet/mobile get a full-screen local
 * viewer surface (nothing left to dim behind it, since it covers the
 * screen itself). The right-hand workspace shows the PDF source viewer,
 * the Ask Bragi panel, or — when both happen to be open at once — a
 * small tab switcher between the two (see RightWorkspace below); each is
 * still exactly one mounted instance, never rendered twice.
 *
 * This file is deliberately a thin composition layer: the scroll/anchor
 * preservation math below is unchanged from before Ask Bragi existed
 * (see BRAGI_REDUCTO_PLAN.md §14/§15 for how hard-won it was) — it only
 * ever cares about a single `showSplit` boolean and a single "what to
 * anchor to" value, which now can come from either panel's own context
 * instead of only the source viewer's.
 */

import { useLayoutEffect, useEffect, useRef, useState } from "react";
import { SourceViewerProvider, useSourceViewer } from "./source-viewer-context";
import { AskBragiPanelProvider, useAskBragiPanelOptional } from "@/components/ask-bragi/ask-bragi-panel-context";
import { RightWorkspace } from "@/components/ask-bragi/right-workspace";

const DESKTOP_BREAKPOINT = "(min-width: 1025px)";

function Shell({ children }: { children: React.ReactNode }) {
  const { isOpen: sourceOpen, visualAnchorRef: sourceAnchorRef } = useSourceViewer();
  // Optional: this provider is always mounted (see AppShellWithSourceViewer
  // below), but the hook stays defensive/optional to match this file's
  // existing convention for anything outside the guaranteed root tree.
  const askBragiPanel = useAskBragiPanelOptional();
  const askBragiOpen = askBragiPanel?.isOpen ?? false;
  const askBragiAnchorRef = askBragiPanel?.visualAnchorRef;

  const [isDesktop, setIsDesktop] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);
  // Tracks whether the split layout was active on the PREVIOUS render, so
  // the layout effect below can tell "just turned on" / "just turned off"
  // apart from "no change" without re-deriving it from isOpen/isDesktop
  // (which can each change independently, e.g. a window resize while the
  // viewer is already open).
  const wasSplitRef = useRef(false);
  // Remembers which panel was actually open at the moment the split was
  // last active, so a CLOSING transition (where, by the time this effect
  // reruns, both isOpen flags may already read false) still knows which
  // context's anchor to read — see the closing branch below.
  const wasSourceOpenRef = useRef(false);

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_BREAKPOINT);
    // Reading the real viewport synchronously on mount (not derivable from
    // props/prior state — this IS external-system synchronization, the
    // effect's actual job), same convention used elsewhere in this codebase.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsDesktop(mql.matches);
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const anyOpen = sourceOpen || askBragiOpen;
  const showSplit = anyOpen && isDesktop;
  const showSheet = anyOpen && !isDesktop;

  // Continuously mirrors mainRef's scrollTop while it's the active scroll
  // container. This exists because by the time the closing branch of the
  // layout effect below runs, React has ALREADY committed the DOM change
  // that flips this div to `display: contents` — which has no box, and
  // therefore no scrollTop, of its own — so reading mainRef.current.
  // scrollTop fresh at that point would read a meaningless value. This ref
  // holds the last real value from just before that happened instead.
  const lastMainScrollTopRef = useRef(0);

  useEffect(() => {
    if (!showSplit) return;
    const el = mainRef.current;
    if (!el) return;
    function onScroll() {
      lastMainScrollTopRef.current = el!.scrollTop;
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [showSplit]);

  // `children` (the structured Bragi page) must stay mounted under the
  // SAME DOM ancestor at all times — see the two wrapper divs below, which
  // always exist and only ever change className, never disappear/reappear
  // — otherwise React tears down and remounts the entire subtree the
  // instant the split turns on, discarding React's own scroll-restoration
  // along with it (this was the actual cause of the structured pane
  // "jumping": before this fix, the split branch returned a completely
  // different top-level element (a real div tree instead of a bare
  // Fragment), so React unmounted `children` from the closed layout and
  // remounted it fresh inside the open one — landing at scrollTop 0 in
  // whatever scroll container it woke up in, which reads as "jumped to
  // the top"). `display: contents` when inactive makes the wrapper
  // invisible to layout, so closed behavior is pixel-identical to before
  // this round ever existed.
  //
  // That alone stops the remount, but TWO more independent things still
  // need handling, or the jump still happens one layer up even with the
  // DOM now stable:
  //
  // 1. Before the split is active, `children` scrolls via the ambient
  //    page scroll (window/html); `.b-app-split-main` becomes ITS OWN
  //    scrollable box once active (a real, separate scroll position,
  //    starting at 0) — the numeric offset needs to transfer explicitly,
  //    in both directions.
  //
  // 2. Numeric transfer ALONE is still not enough — real-browser testing
  //    proved this (see BRAGI_REDUCTO_PLAN.md): the left pane gets
  //    narrower once the split is active, so its content reflows (test
  //    names wrap onto more lines, etc.), which changes how much content
  //    sits above any given row independent of scrollTop. The clicked
  //    row can end up several hundred pixels away from where it was even
  //    with a numerically "correct" scroll transfer. Fixed with a real
  //    visual anchor (see source-viewer-context.tsx's captureVisualAnchor):
  //    re-measure the SAME element that was clicked, before and after the
  //    reflow, and nudge the scroll position by exactly the difference.
  //
  // Both run inside useLayoutEffect so they apply before the browser
  // paints the new layout — no visible jump-then-snap-back flicker.
  useLayoutEffect(() => {
    if (showSplit && !wasSplitRef.current) {
      // Opening: window is still the live scroll container at this point
      // (nothing has reset it yet), so reading window.scrollY here is
      // accurate — unlike the closing branch below, this doesn't need the
      // tracked-ref workaround.
      const y = window.scrollY;
      lastMainScrollTopRef.current = y;
      if (mainRef.current) mainRef.current.scrollTop = y;
      window.scrollTo(0, 0);

      // Whichever panel is newly open this render owns the anchor — see
      // this file's top docstring for why this can now be either context.
      const anchor = sourceOpen ? sourceAnchorRef.current : askBragiAnchorRef?.current ?? null;
      if (anchor?.el.isConnected && mainRef.current) {
        const newTop = anchor.el.getBoundingClientRect().top;
        const delta = newTop - anchor.top;
        if (Math.abs(delta) > 0.5) {
          mainRef.current.scrollTop += delta;
          lastMainScrollTopRef.current = mainRef.current.scrollTop;
        }
      }
    } else if (!showSplit && wasSplitRef.current) {
      // Closing: mainRef's own box (and scrollTop) is already gone by now
      // — use the last value the scroll listener recorded instead of
      // reading a stale/zeroed one directly off the element.
      window.scrollTo(0, lastMainScrollTopRef.current);

      // Both contexts' own isOpen flags may already read false by now (the
      // close that triggered this already flipped them) — wasSourceOpenRef
      // (captured at the end of the PREVIOUS run, i.e. while still open)
      // is what tells us which context's anchor is the relevant one.
      // Each context's own close() re-measures anchor.top right before
      // this fires, against the split layout that's just about to go
      // away — so this is comparing that "last known split-layout
      // position" against the same element's position in the new,
      // full-width layout now committed.
      const anchor = wasSourceOpenRef.current ? sourceAnchorRef.current : askBragiAnchorRef?.current ?? null;
      if (anchor?.el.isConnected) {
        const newTop = anchor.el.getBoundingClientRect().top;
        const delta = newTop - anchor.top;
        if (Math.abs(delta) > 0.5) {
          window.scrollTo(0, window.scrollY + delta);
        }
      }
    }
    wasSplitRef.current = showSplit;
    wasSourceOpenRef.current = sourceOpen;
  }, [showSplit, sourceOpen, sourceAnchorRef, askBragiAnchorRef]);

  return (
    <>
      <div className={showSplit ? "b-app-split" : "b-app-split-passthrough"}>
        <div ref={mainRef} className={showSplit ? "b-app-split-main" : "b-app-split-passthrough"}>
          {children}
        </div>
        {showSplit ? (
          <div className="b-app-split-viewer">
            <RightWorkspace sourceOpen={sourceOpen} askBragiOpen={askBragiOpen} variant="split" />
          </div>
        ) : null}
      </div>
      {showSheet ? <RightWorkspace sourceOpen={sourceOpen} askBragiOpen={askBragiOpen} variant="sheet" /> : null}
    </>
  );
}

export function AppShellWithSourceViewer({ children }: { children: React.ReactNode }) {
  return (
    <AskBragiPanelProvider>
      <SourceViewerProvider>
        <Shell>{children}</Shell>
      </SourceViewerProvider>
    </AskBragiPanelProvider>
  );
}
