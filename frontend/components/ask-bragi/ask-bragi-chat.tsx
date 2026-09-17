"use client";

/**
 * Ask Bragi chat — a Bragi-native workspace, not a generic chatbot UI.
 * Reuses this app's own design system (b-* classes, existing UI
 * primitives, the shared source viewer) rather than introducing a
 * parallel visual language or a second PDF/citation viewer. See
 * BRAGI_ASK_BRAGI_PLAN.md's "UI architecture" section.
 *
 * Real streaming: the answer grows progressively as the model writes it
 * (see lib/ask-bragi-api.ts's streamAskBragiMessage) instead of waiting
 * for a complete response. The final citations/chart/follow_ups/status
 * are ALWAYS taken from the server's "completed" event, never inferred
 * from the streamed text — streaming only changes how the answer is
 * shown while it's in progress, never what gets validated.
 */

import { useEffect, useRef, useState } from "react";
import { EmptyState, ErrorNote } from "@/components/ui";
import { IconAlert, IconArrowUp, IconChevronRight, IconInbox, IconStop } from "@/components/ui/icon";
import { useSourceViewerOptional, captureVisualAnchor } from "@/components/source-viewer/source-viewer-context";
import { getErrorMessage } from "@/lib/api";
import {
  AskBragiChart,
  AskBragiCitation,
  AskBragiConversation,
  AskBragiMessage,
  AskBragiScope,
  askBragiApi,
  streamAskBragiMessage,
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
  /** Denser visual treatment for a smaller surface (narrower max-width,
   * tighter padding) — see ask-bragi-panel.tsx and the Overview card.
   * Controls density only; it does NOT by itself cap how tall the
   * message list renders — see `fillHeight` for that. */
  compact?: boolean;
  /** This chat's own root becomes a full-height flex column, and the
   * message list flexes to fill whatever height its parent actually
   * gives it (instead of a fixed max-height) — for any surface that
   * already establishes a real height for this component to fill (the
   * contextual right-hand panel; the dedicated /ask-bragi page). Omit
   * (default) for a surface with no such height of its own — e.g. the
   * Overview card, which sits inline in a normally-scrolling page and
   * needs its message list to stay within a fixed, modest cap instead. */
  fillHeight?: boolean;
  /** Which scope pill starts selected — see BRAGI_ASK_BRAGI_PLAN.md's
   * per-surface scope defaults (a document reader defaults to "document";
   * Analize/Timeline/Overview default to "patient_record" even when a
   * documentId happens to be available for reference). Defaults to
   * "document" when a documentId is present, "patient_record" otherwise. */
  initialScope?: AskBragiScope;
  /** Resume an existing conversation (its full message history is loaded)
   * instead of starting a new one — how a history sidebar's "continue"
   * action and Overview's "Continue in Ask Bragi" escalation both work.
   * Takes precedence over patientId/documentId/initialScope for THIS
   * mount; changing it (like changing patientId/documentId) starts a
   * fresh load, same patient/document-switch safety as before. */
  conversationId?: number;
  /** Fired once a conversation is available — newly created OR resumed —
   * so a parent (history sidebar, Overview) learns its id without owning
   * conversation-creation/loading itself. */
  onConversationStarted?: (conversation: AskBragiConversation) => void;
  /** Cap how many messages render inline before showing a "Continue in
   * Ask Bragi" link instead of the rest — Overview's compact card uses
   * this so it can never grow into a full conversation-history surface.
   * Omit for the full, uncapped experience. */
  maxVisibleMessages?: number;
  /** Where the "Continue in Ask Bragi" link goes — only rendered when
   * maxVisibleMessages is set and exceeded, or the latest message has a
   * chart (BRAGI product spec: prefer the full workspace for charts). */
  onEscalate?: () => void;
};

function isScrolledNearBottom(container: HTMLElement): boolean {
  return container.scrollHeight - container.scrollTop - container.clientHeight < 48;
}

function scrollToBottom(container: HTMLElement | null | undefined): void {
  if (!container) return;
  container.scrollTop = container.scrollHeight;
}

const THINKING_LABEL: Record<"patient" | "doctor", string> = {
  patient: "Checking your record…",
  doctor: "Checking the record…",
};

export default function AskBragiChat({
  patientId,
  documentId,
  audience,
  suggestions,
  compact,
  fillHeight,
  initialScope,
  conversationId,
  onConversationStarted,
  maxVisibleMessages,
  onEscalate,
}: Props) {
  const sourceViewer = useSourceViewerOptional();
  const [conversation, setConversation] = useState<AskBragiConversation | null>(null);
  const [messages, setMessages] = useState<AskBragiMessage[]>([]);
  const [input, setInput] = useState("");
  const [starting, setStarting] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  // The in-progress assistant turn's own state, shown as a separate
  // "still generating" bubble below the settled `messages` list —
  // folded into `messages` (with real citations/chart/follow_ups) only
  // once the server's "completed" event validates it.
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [streamingStatus, setStreamingStatus] = useState("");
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const listEndRef = useRef<HTMLDivElement>(null);
  // Stable, monotonically-decreasing ids for optimistic (not-yet-
  // server-confirmed) messages — real assistant/user rows always carry
  // the server's own positive id. A ref counter (not Date.now(), which
  // react-hooks/purity flags as an impure render-path call) keeps this a
  // pure, predictable component.
  const localIdRef = useRef(0);
  // Bumped every time a new conversation starts (see the effect below) so
  // an in-flight send() from a conversation the user has since navigated
  // away from can recognize its own response as stale and discard it —
  // otherwise a slow response about Patient A could still land in Patient
  // B's message list after a doctor switches patients mid-request. See
  // BRAGI_ASK_BRAGI_PLAN.md's "Patient switch safety" section.
  const conversationTokenRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Set the instant send()'s lazy-creation path persists a brand-new
  // conversation row, to the id of that conversation — see the init
  // effect below for why this exists. Read once and cleared by that
  // effect; a real subsequent conversationId change (history select,
  // "New chat") is never affected by it.
  const justCreatedConversationIdRef = useRef<number | null>(null);

  // Scope UI — only meaningful when this conversation actually has a
  // document to be scoped to. `userSetScope` is undefined until the user
  // explicitly clicks a pill; while undefined, requested_scope is never
  // sent, leaving the server's own keyword-based intent detection free
  // to broaden a turn on its own (see BRAGI_ASK_BRAGI_PLAN.md). Once the
  // user (or a broadened server response) settles on a scope, the pill
  // reflects it — this is the visible "scope transition" the product
  // spec requires; the server decision is never silent.
  const hasDocumentScope = documentId !== undefined || conversation?.document_id != null;
  const defaultScope: AskBragiScope = initialScope ?? (hasDocumentScope ? "document" : "patient_record");
  const [displayedScope, setDisplayedScope] = useState<AskBragiScope>(defaultScope);
  const [userSetScope, setUserSetScope] = useState<AskBragiScope | null>(
    initialScope && hasDocumentScope && initialScope !== "document" ? initialScope : null
  );

  useEffect(() => {
    let cancelled = false;
    async function start() {
      // OWNERSHIP GUARD: send()'s lazy-creation path (below) persists a
      // brand-new conversation and immediately calls
      // onConversationStarted(newConversation) so a parent can learn its
      // id (history sidebar, URL state, etc.) — see e.g.
      // app/ask-bragi/page.tsx's handleConversationStarted. If that
      // parent stores the id in state and passes it straight back down
      // as this same component's own `conversationId` prop (a completely
      // reasonable, common pattern), THIS effect would otherwise re-run
      // for what is really just an echo of a conversation this exact
      // component instance already knows about and may still be
      // mid-stream on — not a genuine "switch to a different
      // conversation" (history select / "New chat"). Re-running the full
      // reset-and-reload logic below in that case would abort the
      // in-flight stream (whose AbortController this same effect clears),
      // wipe the optimistic user bubble send() just added, and re-fetch a
      // conversation that (being brand new) still has zero messages on
      // the server — reproduced as the dedicated Ask Bragi page
      // appearing to "reset" on a first submit. Recognizing that specific
      // echo and treating it as a no-op is the fix; a real conversationId
      // change (a different id, or the same id arriving through any path
      // OTHER than this component's own just-completed creation) still
      // takes the normal reload path below exactly as before.
      if (conversationId != null && conversationId === justCreatedConversationIdRef.current) {
        justCreatedConversationIdRef.current = null;
        return;
      }

      // Invalidates any send()/stream already in flight for the PREVIOUS
      // conversation (see conversationTokenRef's own comment) and clears
      // whatever leftover generating state that request left behind —
      // both must happen here, not only inside send()'s own guard, or a
      // preempted request could leave the new conversation stuck showing
      // a thinking indicator that will never resolve.
      conversationTokenRef.current += 1;
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
      setGenerating(false);
      setStreamingAnswer("");
      setStreamingStatus("");
      setError("");

      if (conversationId == null) {
        // LAZY CREATION: opening Ask Bragi (or clicking "New chat") must
        // never persist a conversation row on its own — only a real,
        // submitted first message does (see send() below). Until then
        // this is purely local/ephemeral state: no network call, no DB
        // row, nothing to clean up if the user just closes the panel or
        // navigates away without typing anything.
        setConversation(null);
        setMessages([]);
        setDisplayedScope(initialScope ?? (documentId != null ? "document" : "patient_record"));
        setUserSetScope(initialScope && documentId != null && initialScope !== "document" ? initialScope : null);
        setStarting(false);
        return;
      }

      setStarting(true);
      try {
        const res = await askBragiApi.getConversation(conversationId);
        if (cancelled) return;
        const convData = res.data;
        const loadedMessages = res.data.messages;
        setConversation(convData);
        onConversationStarted?.(convData);
        const lastScopeUsed = [...loadedMessages].reverse().find((m) => m.scope_used)?.scope_used;
        setDisplayedScope(lastScopeUsed ?? (initialScope ?? (convData.document_id ? "document" : "patient_record")));
        setUserSetScope(
          initialScope && convData.scope === "document" && initialScope !== "document" ? initialScope : null
        );
        setMessages(loadedMessages);
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, "Ask Bragi is unavailable right now."));
      } finally {
        if (!cancelled) setStarting(false);
      }
    }
    start();
    // Patient-switch / document-switch / conversation-switch safety:
    // starting fresh whenever any of these change means an old patient's
    // (or old conversation's) content can never linger under a new one —
    // see BRAGI_ASK_BRAGI_PLAN.md's "Patient switch safety" section.
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId, documentId, initialScope, defaultScope, conversationId]);

  // Auto-follow the conversation's OWN scrollable container as new
  // content arrives — never `scrollIntoView()`, which can escape this
  // container and drag an ANCESTOR (the whole page, on Overview) into
  // view instead. That was a real, reproduced bug: a fresh conversation
  // starts with `messages = []`, which still changes this effect's own
  // dependency (a new empty-array reference) once `start()` resolves,
  // and `scrollIntoView()`'s default `block: "start"` alignment then
  // pulled the ENTIRE PAGE down to align the (empty, near-the-top)
  // message list with the viewport top. Setting the immediate parent's
  // own `scrollTop` instead can only ever affect that one element.
  // Only auto-follows while already scrolled near the bottom (or on new
  // messages/generation start) — never yanks the view back down if the
  // user has deliberately scrolled up to reread something while a long
  // answer is still streaming in.
  const wasNearBottomRef = useRef(true);
  useEffect(() => {
    const container = listEndRef.current?.parentElement;
    if (!container) return;
    function onScroll() {
      wasNearBottomRef.current = isScrolledNearBottom(container!);
    }
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (messages.length === 0 && !streamingAnswer) return;
    if (!wasNearBottomRef.current) return;
    scrollToBottom(listEndRef.current?.parentElement);
  }, [messages, streamingAnswer, generating]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || generating) return;
    const tokenAtSend = conversationTokenRef.current;
    setGenerating(true);
    setError("");
    setStreamingAnswer("");
    setStreamingStatus(THINKING_LABEL[audience]);
    setLiveAnnouncement("Bragi is responding.");
    wasNearBottomRef.current = true;

    // LAZY CREATION: this is the one and only place a conversation row is
    // ever persisted — the FIRST real submitted message. `conversation`
    // is still null here for a brand-new chat (see the effect above); if
    // so, create it now, before doing anything else that would need its
    // id. Once created it's reused for every later send() in this
    // component instance.
    let activeConversation = conversation;
    if (!activeConversation) {
      try {
        const res = await askBragiApi.createConversation({ patient_id: patientId, document_id: documentId });
        if (tokenAtSend !== conversationTokenRef.current) return; // superseded before creation finished
        activeConversation = res.data;
        // Recorded BEFORE onConversationStarted fires: if the parent it
        // notifies turns around and feeds this same id straight back in
        // as our own `conversationId` prop, the init effect above needs
        // this already set by the time that prop change lands (see its
        // "OWNERSHIP GUARD" comment).
        justCreatedConversationIdRef.current = activeConversation.id;
        setConversation(activeConversation);
        onConversationStarted?.(activeConversation);
      } catch (err) {
        if (tokenAtSend !== conversationTokenRef.current) return;
        setGenerating(false);
        setStreamingStatus("");
        setError(getErrorMessage(err, "Ask Bragi is unavailable right now."));
        return;
      }
    }

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
    // Only the message actually submitted is cleared — anything the user
    // types WHILE Bragi answers accumulates in `input` untouched and is
    // never wiped out from under them when the response completes.
    setInput((prev) => (prev.trim() === trimmed ? "" : prev));

    const controller = new AbortController();
    abortControllerRef.current = controller;
    let liveAnswer = "";

    try {
      await streamAskBragiMessage(
        activeConversation.id,
        trimmed,
        userSetScope ?? undefined,
        (evt) => {
          if (tokenAtSend !== conversationTokenRef.current) return; // stale — conversation switched mid-stream
          if (evt.event === "status") {
            setStreamingStatus((evt.data.label as string) || THINKING_LABEL[audience]);
          } else if (evt.event === "text_delta") {
            liveAnswer += (evt.data.delta as string) || "";
            setStreamingAnswer(liveAnswer);
          } else if (evt.event === "completed") {
            const data = evt.data as {
              answer: string;
              citations: AskBragiCitation[];
              chart: AskBragiChart | null;
              follow_ups: string[];
              status: string;
              scope_used: AskBragiScope;
            };
            localIdRef.current -= 1;
            setMessages((prev) => [
              ...prev,
              {
                id: localIdRef.current,
                role: "assistant",
                content: data.answer,
                citations: data.citations,
                chart: data.chart,
                follow_ups: data.follow_ups,
                status: data.status,
                scope_used: data.scope_used,
                created_at: new Date().toISOString(),
              },
            ]);
            if (data.scope_used) setDisplayedScope(data.scope_used);
            setLiveAnnouncement("Bragi's response is ready.");
          } else if (evt.event === "saved") {
            // Reconcile the just-added assistant message with its real,
            // persisted id (citation clicks/React keys want the real one).
            const saved = evt.data.message as AskBragiMessage;
            setMessages((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].role === "assistant" && next[i].id < 0) {
                  next[i] = saved;
                  break;
                }
              }
              return next;
            });
          } else if (evt.event === "error") {
            setError((evt.data.message as string) || "Ask Bragi could not answer that. Please try again.");
          }
        },
        controller.signal
      );
    } catch (err) {
      if (tokenAtSend !== conversationTokenRef.current) return;
      if (err instanceof DOMException && err.name === "AbortError") {
        // User-initiated Stop: keep whatever text had already arrived,
        // clearly marked incomplete — never silently discarded, never
        // treated as a validated/citable answer (see stopGenerating).
        if (liveAnswer.trim()) {
          localIdRef.current -= 1;
          setMessages((prev) => [
            ...prev,
            {
              id: localIdRef.current,
              role: "assistant",
              content: liveAnswer,
              citations: [],
              chart: null,
              follow_ups: [],
              status: "stopped",
              created_at: new Date().toISOString(),
            },
          ]);
        }
      } else {
        setError(getErrorMessage(err, "Ask Bragi could not answer that. Please try again."));
      }
    } finally {
      if (tokenAtSend === conversationTokenRef.current) {
        setGenerating(false);
        setStreamingAnswer("");
        setStreamingStatus("");
        abortControllerRef.current = null;
      }
    }
  }

  function stopGenerating() {
    abortControllerRef.current?.abort();
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

  const capped = maxVisibleMessages != null && messages.length > maxVisibleMessages;
  const visibleMessages = capped ? messages.slice(-maxVisibleMessages) : messages;
  const hiddenCount = messages.length - visibleMessages.length;
  const latestHasChart = messages.length > 0 && messages[messages.length - 1].chart != null;
  const showEscalateLink = Boolean(onEscalate) && (hiddenCount > 0 || (latestHasChart && compact));

  return (
    <div
      className="b-stack"
      style={{
        // `width: 100%` (not just `maxWidth`) is required here — `.b-stack`
        // has `min-width: 0`, and a flex/grid item with `width: auto` plus
        // horizontal `margin: auto` is sized by CSS shrink-to-fit (its
        // max-content width, clamped by maxWidth), not by its available
        // track. That content-dependent width was the real cause of the
        // Ask Bragi width-collapse bug (Part P): the idle EmptyState's
        // long description text has a wide max-content width (so
        // shrink-to-fit hit the 760px cap and LOOKED stable), but the
        // pending state's only content is the short "Checking your
        // record…" label, whose tiny max-content width made this whole
        // container shrink to it — no bubble-level alignment fix (see
        // ask-bragi-bubble-assistant below) can compensate for its own
        // container shrinking first. An explicit `width` makes this box's
        // size independent of its children's content entirely: exactly
        // `min(760px, its grid track)`, centered by the auto margins,
        // identical before/pending/streaming/completed.
        width: compact ? undefined : "100%",
        maxWidth,
        margin: compact ? undefined : "0 auto",
        minWidth: 0,
        ...(fillHeight ? { height: "100%", minHeight: 0 } : {}),
      }}
    >
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

      <span className="sr-only" aria-live="polite">
        {liveAnnouncement}
      </span>

      {hiddenCount > 0 ? (
        <button
          type="button"
          className="b-btn b-btn-ghost b-btn-sm"
          onClick={onEscalate}
          style={{ alignSelf: "flex-start" }}
        >
          {hiddenCount} earlier message{hiddenCount === 1 ? "" : "s"} in this conversation
          <IconChevronRight size={12} />
        </button>
      ) : null}

      <div
        className="b-surface ask-bragi-messages ask-bragi-surface"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--s3)",
          overflowY: "auto",
          padding: "var(--s4)",
          ...(fillHeight
            ? { flex: 1, minHeight: 0 }
            : { minHeight: compact ? 180 : 320, maxHeight: compact ? 320 : "60vh" }),
        }}
      >
        {visibleMessages.length === 0 && !generating ? (
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
          visibleMessages.map((m, i) => {
            const prevScope = i > 0 ? visibleMessages[i - 1].scope_used : conversation?.scope;
            const scopeChanged = m.role === "assistant" && m.scope_used && prevScope && m.scope_used !== prevScope;
            return (
              <div key={m.id}>
                {scopeChanged ? (
                  <p
                    className="muted-text"
                    style={{ fontSize: 12, margin: "0 0 6px", display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <IconAlert size={12} /> Searching full record
                  </p>
                ) : null}
                <AskBragiMessageBubble message={m} onCitationClick={handleCitationClick} onFollowUpClick={send} />
              </div>
            );
          })
        )}
        {generating ? (
          <div className="ask-bragi-bubble ask-bragi-bubble-assistant" style={{ alignSelf: "stretch" }}>
            {streamingAnswer ? (
              <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{streamingAnswer}</p>
            ) : (
              <AskBragiThinkingIndicator label={streamingStatus || THINKING_LABEL[audience]} />
            )}
          </div>
        ) : null}
        <div ref={listEndRef} />
      </div>

      {showEscalateLink && !hiddenCount ? (
        <button
          type="button"
          className="b-btn b-btn-ghost b-btn-sm"
          onClick={onEscalate}
          style={{ alignSelf: "flex-start" }}
        >
          Continue in Ask Bragi
          <IconChevronRight size={12} />
        </button>
      ) : null}

      {error && conversation ? <ErrorNote>{error}</ErrorNote> : null}

      {messages.length === 0 && !generating && suggestions && suggestions.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)" }}>
          {suggestions.map((s) => (
            <button key={s} type="button" className="b-chip b-chip-brand ask-bragi-chip" style={{ cursor: "pointer" }} onClick={() => send(s)}>
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
          className="b-input ask-bragi-composer"
          style={{ flex: 1, fontSize: 16 }}
          placeholder={audience === "patient" ? "Ask about your record…" : "Ask about this patient…"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={starting}
          autoComplete="off"
        />
        {generating ? (
          <button type="button" className="b-btn b-btn-secondary ask-bragi-send-btn" onClick={stopGenerating} aria-label="Stop generating">
            <IconStop size={14} />
          </button>
        ) : (
          <button type="submit" className="b-btn b-btn-primary ask-bragi-send-btn" disabled={!input.trim() || starting} aria-label="Send">
            <IconArrowUp size={16} />
          </button>
        )}
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
      className={active ? "b-chip b-chip-brand ask-bragi-chip" : "b-chip ask-bragi-chip"}
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
  onFollowUpClick,
}: {
  message: AskBragiMessage;
  onCitationClick: (sourceEvidenceId: number) => void;
  onFollowUpClick: (text: string) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div
      className={`ask-bragi-bubble ${isUser ? "ask-bragi-bubble-user" : "ask-bragi-bubble-assistant"}`}
      style={
        isUser
          ? { alignSelf: "flex-end", maxWidth: "88%" }
          : // Assistant bubble stretches to the full message-column width in
            // every state (pending "Checking your record…" and completed
            // answer alike) — see the pending bubble above. Before this,
            // alignSelf:"flex-start" made both shrink-to-fit their own
            // content, which was invisible for a long completed answer but
            // collapsed the pending bubble (a few words) into a narrow
            // floating card that then visibly re-expanded once real content
            // arrived.
            { alignSelf: "stretch" }
      }
    >
      <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{message.content}</p>

      {message.status === "insufficient_data" ? (
        <p className="muted-text" style={{ display: "flex", gap: 6, alignItems: "center", marginTop: "var(--s2)" }}>
          <IconAlert size={13} /> Your record doesn&rsquo;t appear to contain this information.
        </p>
      ) : null}

      {message.status === "stopped" ? (
        <p className="muted-text" style={{ display: "flex", gap: 6, alignItems: "center", marginTop: "var(--s2)" }}>
          <IconAlert size={13} /> Stopped — this answer may be incomplete.
        </p>
      ) : null}

      {message.citations.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)", marginTop: "var(--s3)" }}>
          {message.citations.map((c) => (
            <button
              key={c.source_evidence_id}
              type="button"
              className="b-chip ask-bragi-chip"
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
            <button
              key={f}
              type="button"
              className="b-chip ask-bragi-chip"
              style={{ cursor: "pointer" }}
              onClick={() => onFollowUpClick(f)}
            >
              {f}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
