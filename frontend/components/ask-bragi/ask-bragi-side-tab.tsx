"use client";

/**
 * The small "Ask Bragi" entry point placed near the top of a structured
 * clinical page (lab document, discharge/imaging/pathology/consultation
 * reader). Compact, attached to the workspace — not a floating chat
 * bubble, not a centered modal trigger. Opens the shared contextual
 * panel (ask-bragi-panel-context.tsx), which the root shell renders
 * coexisting with the PDF source viewer when both are open.
 */

import { captureVisualAnchor } from "@/components/source-viewer/source-viewer-context";
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
        const anchor = captureVisualAnchor();
        panel.open(target, anchor);
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
