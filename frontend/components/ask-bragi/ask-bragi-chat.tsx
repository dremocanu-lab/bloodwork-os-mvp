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
  AskBragiScope,
  askBragiApi,
} from "@/lib/ask-bragi-api";
import { AskBragiChartView } from "./ask-bragi-chart";
import { AskBragiThinkingIndicator } from "./ask-bragi-thinking-indicator";

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
  /** Compact mode for the contextual side panel (narrower max-width,
   * denser padding) — see ask-bragi-panel.tsx. */
  compact?: boolean;
  /** Which scope pill starts selected — see BRAGI_ASK_BRAGI_PLAN.md's
   * per-surface scope defaults (a document reader defaults to "document";
   * Analize/Timeline/Overview default to "patient_record" even when a
   * documentId happens to be available for reference). Defaults to
   * "document" when a documentId is present, "patient_record" otherwise. */
  initialScope?: AskBragiScope;
};

const THINKING_LABEL: Record<"patient" | "doctor", string> = {
  patient: "Bragi is reviewing your record…",
  doctor: "Reviewing the record…",
};

export default function AskBragiChat({ patientId, documentId, audience, suggestions, compact, initialScope }: Props) {
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
  // Bumped every time a new conversation starts (see the effect below) so
  // an in-flight send() from a conversation the user has since navigated
  // away from can recognize its own response as stale and discard it —
  // otherwise a slow response about Patient A could still land in Patient
  // B's message list after a doctor switches patients mid-request. See
  // BRAGI_ASK_BRAGI_PLAN.md's "Patient switch safety" section.
  const conversationTokenRef = useRef(0);

  // Scope UI — only meaningful when this conversation actually has a
  // document to be scoped to. `userSetScope` is undefined until the user
  // explicitly clicks a pill; while undefined, requested_scope is never
  // sent, leaving the server's own keyword-based intent detection free
  // to broaden a turn on its own (see BRAGI_ASK_BRAGI_PLAN.md). Once the
  // user (or a broadened server response) settles on a scope, the pill
  // reflects it — this is the visible "scope transition" the product
  // spec requires; the server decision is never silent.
  const hasDocumentScope = documentId !== undefined;
  const defaultScope: AskBragiScope = initialScope ?? (hasDocumentScope ? "document" : "patient_record");
  const [displayedScope, setDisplayedScope] = useState<AskBragiScope>(defaultScope);
  // Pre-seeded (not null) when a caller explicitly names a non-default
  // initial scope (e.g. a Timeline entry point tied to a document but
  // defaulting to "patient_record") — the very first message should
  // already carry that as requested_scope, not rely on keyword detection.
  const [userSetScope, setUserSetScope] = useState<AskBragiScope | null>(
    initialScope && hasDocumentScope && initialScope !== "document" ? initialScope : null
  );

  useEffect(() => {
    let cancelled = false;
    async function start() {
      // Invalidates any send() already in flight for the PREVIOUS
      // conversation (see conversationTokenRef's own comment) and clears
      // whatever leftover "sending" state that request left behind — both
      // must happen here, not only inside send()'s own guard, or a
      // preempted request could leave the new conversation stuck showing
      // a thinking indicator that will never resolve.
      conversationTokenRef.current += 1;
      setSending(false);
      setStarting(true);
      setError("");
      try {
        const res = await askBragiApi.createConversation({
          patient_id: patientId,
          document_id: documentId,
        });
        if (cancelled) return;
        setConversation(res.data);
        setDisplayedScope(defaultScope);
        setUserSetScope(
          initialScope && res.data.scope === "document" && initialScope !== "document" ? initialScope : null
        );
        setMessages([]);
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
  }, [patientId, documentId, initialScope, defaultScope]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !conversation || sending) return;
    const tokenAtSend = conversationTokenRef.current;
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
      const res = await askBragiApi.sendMessage(conversation.id, trimmed, userSetScope ?? undefined);
      // Stale if the user has since switched patient/document/conversation
      // — the response belongs to a context this component no longer
      // shows. See conversationTokenRef's own comment.
      if (tokenAtSend !== conversationTokenRef.current) return;
      setMessages((prev) => [...prev, res.data]);
      if (res.data.scope_used) setDisplayedScope(res.data.scope_used);
    } catch (err) {
      if (tokenAtSend !== conversationTokenRef.current) return;
      setError(getErrorMessage(err, "Ask Bragi could not answer that. Please try again."));
    } finally {
      if (tokenAtSend === conversationTokenRef.current) setSending(false);
    }
  }

  function handleCitationClick(sourceEvidenceId: number) {
    const anchor = captureVisualAnchor();
    sourceViewer?.openSourceEvidence(sourceEvidenceId, anchor);
  }

  function selectScope(scope: AskBragiScope) {
    setUserSetScope(scope);
    setDisplayedScope(scope);
  }

  const maxWidth = compact ? undefined : 760;

  if (starting) {
    return (
      <div className="b-surface" style={{ padding: "var(--s5)", textAlign: "center" }}>
        <AskBragiThinkingIndicator label="Starting Ask Bragi…" showLabel />
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
    <div className="b-stack" style={{ maxWidth, margin: compact ? undefined : "0 auto", minWidth: 0 }}>
      {hasDocumentScope ? (
        <div role="group" aria-label="Ask Bragi scope" style={{ display: "flex", gap: 6, alignSelf: "flex-start" }}>
          <ScopePill active={displayedScope === "document"} onClick={() => selectScope("document")}>
            This document
          </ScopePill>
          <ScopePill active={displayedScope === "patient_record"} onClick={() => selectScope("patient_record")}>
            Full record
          </ScopePill>
        </div>
      ) : null}

      <div
        className="b-surface"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--s3)",
          minHeight: compact ? 220 : 320,
          maxHeight: compact ? "calc(100vh - 320px)" : "60vh",
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
          messages.map((m, i) => {
            const prevScope = i > 0 ? messages[i - 1].scope_used : conversation?.scope;
            const scopeChanged =
              m.role === "assistant" && m.scope_used && prevScope && m.scope_used !== prevScope;
            return (
              <div key={m.id}>
                {scopeChanged ? (
                  <p className="muted-text" style={{ fontSize: 12, margin: "0 0 6px", display: "flex", alignItems: "center", gap: 6 }}>
                    <IconAlert size={12} /> Searching full record
                  </p>
                ) : null}
                <AskBragiMessageBubble message={m} onCitationClick={handleCitationClick} />
              </div>
            );
          })
        )}
        {sending ? (
          <div className="b-list-row" style={{ alignSelf: "flex-start" }}>
            <AskBragiThinkingIndicator label={THINKING_LABEL[audience]} />
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

function ScopePill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={active ? "b-chip b-chip-brand" : "b-chip"}
      style={{ cursor: "pointer" }}
      aria-pressed={active}
      onClick={onClick}
    >
      {children}
    </button>
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
