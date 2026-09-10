"use client";

/**
 * Composes the root layout with the shared source viewer: desktop gets a
 * real split view (main content + viewer, side by side, no overlay/no
 * backdrop — see .b-app-split in globals.css); tablet/mobile get a
 * full-screen local viewer surface (nothing left to dim behind it, since
 * it covers the screen itself). One SourceViewerPanel instance either
 * way — never two PDF renders at once.
 */

import { useEffect, useState } from "react";
import { SourceViewerProvider, useSourceViewer } from "./source-viewer-context";
import { SourceViewerPanel } from "./source-viewer-panel";

const DESKTOP_BREAKPOINT = "(min-width: 1025px)";

function Shell({ children }: { children: React.ReactNode }) {
  const { isOpen } = useSourceViewer();
  const [isDesktop, setIsDesktop] = useState(false);

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

  if (!isOpen) return <>{children}</>;

  if (isDesktop) {
    return (
      <div className="b-app-split">
        <div className="b-app-split-main">{children}</div>
        <div className="b-app-split-viewer">
          <SourceViewerPanel variant="split" />
        </div>
      </div>
    );
  }

  return (
    <>
      {children}
      <SourceViewerPanel variant="sheet" />
    </>
  );
}

export function AppShellWithSourceViewer({ children }: { children: React.ReactNode }) {
  return (
    <SourceViewerProvider>
      <Shell>{children}</Shell>
    </SourceViewerProvider>
  );
}
