"use client";

/**
 * Conversation-history sidebar for the dedicated Ask Bragi pages
 * (patient /ask-bragi, doctor /patients/[id]/ask-bragi). Narrower than
 * the main conversation column, "+ New chat" at the top, conversations
 * grouped Today / Previous 7 days / Older, newest first — reuses the
 * conversation list the backend already returns (title is a plain
 * truncation of the first message, set server-side; see main.py's
 * send_ask_bragi_message — no extra model call just to title a chat).
 *
 * Delete is a real, supported action (DELETE /ask-bragi/conversations/
 * {id}) — a small inline confirm replaces the row instead of a centered
 * dark modal, matching this app's existing no-backdrop-popup convention.
 */

import { useState } from "react";
import { IconArchive, IconCheck, IconClose, IconPlus } from "@/components/ui/icon";
import type { AskBragiConversation } from "@/lib/ask-bragi-api";
import { parseDateTime } from "@/lib/analytics/transform";

type Group = { label: string; conversations: AskBragiConversation[] };

function groupConversations(conversations: AskBragiConversation[]): Group[] {
  const now = Date.now();
  const oneDay = 24 * 60 * 60 * 1000;
  const today: AskBragiConversation[] = [];
  const last7: AskBragiConversation[] = [];
  const older: AskBragiConversation[] = [];
  for (const c of conversations) {
    const t = parseDateTime(c.updated_at || c.created_at);
    const ageMs = now - t;
    if (t && ageMs < oneDay) today.push(c);
    else if (t && ageMs < oneDay * 7) last7.push(c);
    else older.push(c);
  }
  return [
    { label: "Today", conversations: today },
    { label: "Previous 7 days", conversations: last7 },
    { label: "Older", conversations: older },
  ].filter((g) => g.conversations.length > 0);
}

export function AskBragiHistorySidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewChat,
  onDelete,
  loading,
}: {
  conversations: AskBragiConversation[];
  activeConversationId: number | null;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  onDelete: (id: number) => void;
  loading?: boolean;
}) {
  const groups = groupConversations(conversations);

  return (
    <nav className="ask-bragi-history" aria-label="Ask Bragi conversation history">
      <button type="button" className="b-btn b-btn-secondary ask-bragi-send-btn" onClick={onNewChat} style={{ width: "100%" }}>
        <IconPlus size={13} /> New chat
      </button>

      {loading ? (
        <p className="muted-text" style={{ padding: "var(--s3) 0" }}>
          Loading…
        </p>
      ) : conversations.length === 0 ? (
        <p className="muted-text" style={{ padding: "var(--s3) 0" }}>
          No conversations yet.
        </p>
      ) : (
        groups.map((group) => (
          <div key={group.label} style={{ marginTop: "var(--s3)" }}>
            <p className="muted-text ask-bragi-history-group-label">{group.label}</p>
            <div className="b-list">
              {group.conversations.map((c) => (
                <HistoryRow
                  key={c.id}
                  conversation={c}
                  active={c.id === activeConversationId}
                  onSelect={() => onSelect(c.id)}
                  onDelete={() => onDelete(c.id)}
                />
              ))}
            </div>
          </div>
        ))
      )}
    </nav>
  );
}

function HistoryRow({
  conversation,
  active,
  onSelect,
  onDelete,
}: {
  conversation: AskBragiConversation;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const title = conversation.title || "New conversation";

  if (confirming) {
    return (
      <div className="b-list-row ask-bragi-history-row" style={{ gap: 6 }}>
        <span className="b-list-main" style={{ minWidth: 0 }}>
          <span className="b-list-title muted-text">Delete this conversation?</span>
        </span>
        <button
          type="button"
          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
          aria-label="Confirm delete"
          onClick={onDelete}
        >
          <IconCheck size={13} />
        </button>
        <button
          type="button"
          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
          aria-label="Cancel"
          onClick={() => setConfirming(false)}
        >
          <IconClose size={13} />
        </button>
      </div>
    );
  }

  return (
    <div className={`b-list-row ask-bragi-history-row${active ? " ask-bragi-history-row-active" : ""}`}>
      <button type="button" className="ask-bragi-history-row-select" onClick={onSelect} aria-current={active || undefined}>
        <span className="b-list-title">{title}</span>
      </button>
      <button
        type="button"
        className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
        aria-label="Delete conversation"
        onClick={() => setConfirming(true)}
      >
        <IconArchive size={13} />
      </button>
    </div>
  );
}
