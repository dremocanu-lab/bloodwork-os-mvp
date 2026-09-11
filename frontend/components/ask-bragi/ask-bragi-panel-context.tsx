"use client";

/**
 * Shared Ask Bragi contextual-panel system — mirrors
 * `source-viewer/source-viewer-context.tsx`'s shape deliberately (same
 * open/close/anchor pattern) so the root shell
 * (`app-shell-with-source-viewer.tsx`) can drive the same split-layout/
 * scroll-preservation mechanism for EITHER panel, or both at once,
 * without that mechanism needing to know which one is open — it only
 * ever cares about a single `showSplit` boolean and a single visual
 * anchor.
 *
 * This file intentionally does NOT touch source-viewer-context.tsx —
 * that component's scroll/anchor math is delicate, already hard-won
 * (see BRAGI_REDUCTO_PLAN.md §14/§15), and works purely off `isOpen`
 * booleans it's handed; adding a second, independent open/close system
 * alongside it is lower-risk than modifying it.
 */

import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";
import { captureVisualAnchor, VisualAnchor } from "@/components/source-viewer/source-viewer-context";

export type AskBragiPanelScope = "patient_record" | "document";

export type AskBragiPanelTarget = {
  audience: "patient" | "doctor";
  patientId?: number;
  documentId?: number;
  /** Initial scope the panel opens in — see BRAGI_ASK_BRAGI_PLAN.md's
   * scope-default rules (document pages default to "document", Analize/
   * Timeline/Overview default to "patient_record"). */
  initialScope: AskBragiPanelScope;
  suggestions?: string[];
};

type AskBragiPanelContextValue = {
  isOpen: boolean;
  target: AskBragiPanelTarget | null;
  open: (target: AskBragiPanelTarget, preCapturedAnchor?: VisualAnchor | null) => void;
  close: () => void;
  visualAnchorRef: { current: VisualAnchor | null };
};

const AskBragiPanelContext = createContext<AskBragiPanelContextValue | null>(null);

export function useAskBragiPanel(): AskBragiPanelContextValue {
  const ctx = useContext(AskBragiPanelContext);
  if (!ctx) throw new Error("useAskBragiPanel must be used within an AskBragiPanelProvider");
  return ctx;
}

/** Non-throwing variant for the root shell, which must render correctly
 * even before/without this provider mounted (defensive, matches
 * useSourceViewerOptional's own convention). */
export function useAskBragiPanelOptional(): AskBragiPanelContextValue | null {
  return useContext(AskBragiPanelContext);
}

export function AskBragiPanelProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [target, setTarget] = useState<AskBragiPanelTarget | null>(null);
  const visualAnchorRef = useRef<VisualAnchor | null>(null);

  const open = useCallback((newTarget: AskBragiPanelTarget, preCapturedAnchor?: VisualAnchor | null) => {
    visualAnchorRef.current = preCapturedAnchor !== undefined ? preCapturedAnchor : captureVisualAnchor();
    setTarget(newTarget);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    if (visualAnchorRef.current?.el.isConnected) {
      visualAnchorRef.current = {
        el: visualAnchorRef.current.el,
        top: visualAnchorRef.current.el.getBoundingClientRect().top,
      };
    }
    setIsOpen(false);
  }, []);

  return (
    <AskBragiPanelContext.Provider value={{ isOpen, target, open, close, visualAnchorRef }}>
      {children}
    </AskBragiPanelContext.Provider>
  );
}
