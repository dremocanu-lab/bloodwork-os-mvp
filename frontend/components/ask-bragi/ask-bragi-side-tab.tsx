"use client";

/**
 * The small "Ask Bragi" entry point placed near the top of a structured
 * clinical page (lab document, discharge/imaging/pathology/consultation
 * reader). Compact, attached to the workspace — not a floating chat
 * bubble, not a centered modal trigger. Opens the shared contextual
 * panel (ask-bragi-panel-context.tsx), which the root shell renders
 * coexisting with the PDF source viewer when both are open.
 */

import { IconChat } from "@/components/ui/icon";
import { AskBragiPanelTarget, useAskBragiPanelOptional } from "./ask-bragi-panel-context";

export function AskBragiSideTab({ target }: { target: AskBragiPanelTarget }) {
  const panel = useAskBragiPanelOptional();
  if (!panel) return null;

  return (
    <button
      type="button"
      className="b-btn b-btn-secondary ask-bragi-side-tab"
      aria-label="Ask Bragi about this record"
      onClick={() => {
        // Deliberately NOT captureVisualAnchor() here: this button lives
        // in the page's own sticky top header (AppShell's rightContent
        // row), not in the flowing content whose reflow the visual-anchor
        // correction exists to compensate for (see
        // app-shell-with-source-viewer.tsx's useLayoutEffect). A sticky
        // element's on-screen position doesn't track real document depth
        // the way a table row or lab result button does, and measuring it
        // as an anchor produced a large, spurious "delta" that snapped the
        // structured page's scroll to the very top on close — exactly the
        // jump this whole mechanism exists to prevent. Passing `null`
        // (not `undefined`, which would re-capture the same button) skips
        // that correction and leaves only the plain scrollY/scrollTop
        // transfer, which is already correct for a header-anchored open.
        panel.open(target, null);
      }}
    >
      <IconChat size={14} />
      Ask Bragi
      <style jsx>{`
        .ask-bragi-side-tab {
          border-color: var(--primary-soft-border);
          color: var(--primary);
          background: var(--primary-soft);
          gap: 6px;
        }
      `}</style>
    </button>
  );
}
