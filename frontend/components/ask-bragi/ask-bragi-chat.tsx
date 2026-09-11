"use client";

/**
 * Ask Bragi chat — a Bragi-native workspace, not a generic chatbot UI.
 * Reuses this app's own design system (b-* classes, existing UI
 * primitives, the shared source viewer) rather than introducing a
 * parallel visual language or a second PDF/citation viewer. See
 * BRAGI_ASK_BRAGI_PLAN.md's "UI architecture" section.
 *
 * V1 is synchronous (request -> full response), not streamed — see the
 * plan doc's "Streaming" section for why that's an honest, deliberate
 * V1 scope decision rather than an oversight.
 */

import { useEffect, useRef, useState } from "react";
import { EmptyState, ErrorNote } from "@/components/ui";
import { IconAlert, IconArrowUp, IconInbox } from "@/components/ui/icon";
import { useSourceViewerOptional, captureVisualAnchor } from "@/components/source-viewer/source-viewer-context";
import { getErrorMessage } from "@/lib/api";
import {
  AskBragiConversation,
  AskBragiMessage,
  askBragiApi,
} from "@/lib/ask-bragi-api";
import { AskBragiChartView } from "./ask-bragi-chart";

type Props = {
  /** Doctor mode: which patient this conversation is about. Omit for a
   * patient chatting about their own record — the server resolves that
   * automatically; there is no client-suppliable patient id otherwise. */
  patientId?: number;
  /** Scope this conversation to a single document instead of the whole
   * record (see BRAGI_ASK_BRAGI_PLAN.md's scope model). */
  documentId?: number;
  audience: "patient" | "doctor";
  suggestions?: string[];
};

export default function AskBragiChat({ patientId, documentId, audience, suggestions }: Props) {
  const sourceViewer = useSourceViewerOptional();
  const [conversation, setConversation] = useState<AskBragiConversation | null>(null);
  const [messages, setMessages] = useState<AskBragiMessage[]>([]);
  const [input, setInput] = useState("");
  const [starting, setStarting] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const listEndRef = useRef<HTMLDivElement>(null);
  // Stable, monotonically-decreasing ids for optimistic (not-yet-
  // server-confirmed) user messages — real assistant/user rows always
  // carry the server's own positive id. A ref counter (not Date.now(),
  // which react-hooks/purity flags as an impure render-path call) keeps
  // this a pure, predictable component.
  const localIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      setStarting(true);
      setError("");
      try {
        const res = await askBragiApi.createConversation({
          patient_id: patientId,
          document_id: documentId,
        });
        if (cancelled) return;
        setConversation(res.data);
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, "Ask Bragi is unavailable right now."));
      } finally {
        if (!cancelled) setStarting(false);
      }
    }
    start();
    // Patient-switch / document-switch safety: starting a brand new
    // conversation whenever the scope changes means an old patient's
    // answer can never linger under a new patient's context — see
    // BRAGI_ASK_BRAGI_PLAN.md's "Patient switch safety" section.
    return () => {
      cancelled = true;
    };
  }, [patientId, documentId]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !conversation || sending) return;
    setSending(true);
    setError("");
    localIdRef.current -= 1;
    const userMessage: AskBragiMessage = {
      id: localIdRef.current,
      role: "user",
      content: trimmed,
      citations: [],
      chart: null,
      follow_ups: [],
      status: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    try {
      const res = await askBragiApi.sendMessage(conversation.id, trimmed);
      setMessages((prev) => [...prev, res.data]);
    } catch (err) {
      setError(getErrorMessage(err, "Ask Bragi could not answer that. Please try again."));
    } finally {
      setSending(false);
    }
  }

  function handleCitationClick(sourceEvidenceId: number) {
    const anchor = captureVisualAnchor();
    sourceViewer?.openSourceEvidence(sourceEvidenceId, anchor);
  }

  if (starting) {
    return (
      <div className="b-surface" style={{ padding: "var(--s5)", textAlign: "center" }}>
        <span className="b-spinner" />
        <p className="muted-text" style={{ marginTop: "var(--s2)" }}>Starting Ask Bragi…</p>
      </div>
    );
  }

  if (error && !conversation) {
    return (
      <div className="b-surface" style={{ padding: "var(--s5)" }}>
        <ErrorNote>{error}</ErrorNote>
      </div>
    );
  }

  return (
    <div className="b-stack" style={{ maxWidth: 760, margin: "0 auto", minWidth: 0 }}>
      {documentId ? (
        <div className="b-chip" style={{ alignSelf: "flex-start" }}>
          Scoped to this document
        </div>
      ) : null}

      <div
        className="b-surface"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--s3)",
          minHeight: 320,
          maxHeight: "60vh",
          overflowY: "auto",
          padding: "var(--s4)",
        }}
      >
        {messages.length === 0 ? (
          <EmptyState
            icon={<IconInbox size={18} />}
            title="Ask Bragi about this record"
            description={
              audience === "patient"
                ? "Ask about your labs, medications, timeline, or a specific document — every answer shows its source."
                : "Ask about this patient's labs, medications, timeline, or a specific document — every answer shows its source."
            }
          />
        ) : (
          messages.map((m) => (
            <AskBragiMessageBubble key={m.id} message={m} onCitationClick={handleCitationClick} />
          ))
        )}
        {sending ? (
          <div className="b-list-row" style={{ alignSelf: "flex-start" }}>
            <span className="b-spinner" />
          </div>
        ) : null}
        <div ref={listEndRef} />
      </div>

      {error && conversation ? <ErrorNote>{error}</ErrorNote> : null}

      {messages.length === 0 && suggestions && suggestions.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)" }}>
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              className="b-chip b-chip-brand"
              style={{ cursor: "pointer" }}
              onClick={() => send(s)}
              disabled={sending}
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        style={{ display: "flex", gap: "var(--s2)" }}
      >
        <input
          className="b-input"
          style={{ flex: 1, fontSize: 16 }}
          placeholder={audience === "patient" ? "Ask about your record…" : "Ask about this patient…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending || !conversation}
          autoComplete="off"
        />
        <button
          type="submit"
          className="b-btn b-btn-primary"
          disabled={sending || !input.trim() || !conversation}
          aria-label="Send"
        >
          <IconArrowUp size={16} />
        </button>
      </form>
    </div>
  );
}

function AskBragiMessageBubble({
  message,
  onCitationClick,
}: {
  message: AskBragiMessage;
  onCitationClick: (sourceEvidenceId: number) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div
      className={isUser ? "b-list-row" : "b-surface"}
      style={{
        alignSelf: isUser ? "flex-end" : "flex-start",
        maxWidth: "88%",
        background: isUser ? "var(--primary-soft)" : undefined,
        border: isUser ? "1px solid var(--primary-soft-border)" : undefined,
        padding: "var(--s3)",
      }}
    >
      <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{message.content}</p>

      {message.status === "insufficient_data" ? (
        <p className="muted-text" style={{ display: "flex", gap: 6, alignItems: "center", marginTop: "var(--s2)" }}>
          <IconAlert size={13} /> Your record doesn&rsquo;t appear to contain this information.
        </p>
      ) : null}

      {message.citations.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)", marginTop: "var(--s3)" }}>
          {message.citations.map((c) => (
            <button
              key={c.source_evidence_id}
              type="button"
              className="b-chip"
              style={{ cursor: "pointer" }}
              onClick={() => onCitationClick(c.source_evidence_id)}
            >
              {c.label}
            </button>
          ))}
        </div>
      ) : null}

      {message.chart ? (
        <div style={{ marginTop: "var(--s3)" }}>
          <AskBragiChartView chart={message.chart} onPointClick={onCitationClick} />
        </div>
      ) : null}

      {message.follow_ups.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)", marginTop: "var(--s3)" }}>
          {message.follow_ups.map((f) => (
            <span key={f} className="b-chip" style={{ opacity: 0.75 }}>
              {f}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
