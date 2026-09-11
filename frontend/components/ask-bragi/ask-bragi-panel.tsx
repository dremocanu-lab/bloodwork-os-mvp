"use client";

/**
 * The contextual Ask Bragi panel body — rendered by the root shell
 * (app-shell-with-source-viewer.tsx) in the same right-hand workspace
 * slot the PDF source viewer uses, either alone or behind a small tab
 * switcher when both are open at once (see that file for the
 * coexistence logic). This file only renders the panel's own header +
 * <AskBragiChat>; it has no opinion on layout/coexistence.
 */

import { IconClose } from "@/components/ui/icon";
import AskBragiChat from "./ask-bragi-chat";
import { useAskBragiPanel } from "./ask-bragi-panel-context";

export function AskBragiPanel({ variant }: { variant: "split" | "sheet" }) {
  const { target, close } = useAskBragiPanel();

  if (!target) return null;

  return (
    <div
      className={`b-ask-bragi-${variant}`}
      role="dialog"
      aria-modal={variant === "sheet" ? true : undefined}
      aria-label="Ask Bragi"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "var(--s3) var(--s4)",
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600 }}>Ask Bragi</span>
        <button
          type="button"
          className="b-btn b-btn-icon"
          aria-label={variant === "sheet" ? "Close Ask Bragi" : "Close Ask Bragi panel"}
          onClick={close}
        >
          <IconClose size={15} />
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "var(--s3) var(--s4)" }}>
        <AskBragiChat
          key={`${target.patientId ?? "self"}-${target.documentId ?? "record"}`}
          audience={target.audience}
          patientId={target.patientId}
          documentId={target.documentId}
          suggestions={target.suggestions}
          initialScope={target.initialScope}
          compact
        />
      </div>
    </div>
  );
}
