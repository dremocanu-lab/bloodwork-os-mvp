"use client";

/**
 * The patient's dedicated Ask Bragi workspace: a conversation-history
 * sidebar (desktop/tablet) or drawer (mobile) alongside the full chat —
 * see components/ask-bragi/ask-bragi-history-sidebar.tsx. The Overview
 * card's own compact Ask Bragi links here (`?c={id}`) to continue the
 * SAME conversation, never a fresh one.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import AppShell from "@/components/app-shell";
import AskBragiChat from "@/components/ask-bragi/ask-bragi-chat";
import { AskBragiHistorySidebar } from "@/components/ask-bragi/ask-bragi-history-sidebar";
import { IconMenu } from "@/components/ui/icon";
import { api } from "@/lib/api";
import { AskBragiConversation, askBragiApi } from "@/lib/ask-bragi-api";
import { getHomeByRole } from "@/lib/routing";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

const SUGGESTIONS = [
  "Show my latest labs",
  "How has my hemoglobin changed?",
  "What medications are in my record?",
  "What did my latest discharge summary say?",
];

export default function AskBragiPage() {
  return (
    <Suspense
      fallback={
        <main className="app-page-bg" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
          <span className="b-spinner" />
        </main>
      }
    >
      <AskBragiPageInner />
    </Suspense>
  );
}

function AskBragiPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [conversations, setConversations] = useState<AskBragiConversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (cancelled) return;
        if (me.data.role !== "patient") {
          router.push(getHomeByRole(me.data.role));
          return;
        }
        setCurrentUser(me.data);
        const initialId = searchParams.get("c");
        if (initialId && !Number.isNaN(Number(initialId))) setActiveId(Number(initialId));
      } catch {
        if (!cancelled) router.push("/login");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    init();
    return () => {
      cancelled = true;
    };
    // Only ever read the URL's own initial ?c= once, on mount — later
    // navigation within this page is state-driven (New chat/select),
    // not URL-driven, so re-running this on every searchParams identity
    // change would fight the user's own in-page selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const refreshConversations = useCallback(async () => {
    try {
      const res = await askBragiApi.listConversations();
      setConversations(res.data);
    } catch {
      // Non-critical — the history sidebar just stays empty/stale; the
      // active conversation itself doesn't depend on this list.
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    async function run() {
      if (currentUser) await refreshConversations();
    }
    run();
  }, [currentUser, refreshConversations]);

  function handleConversationStarted(conversation: AskBragiConversation) {
    setActiveId(conversation.id);
    refreshConversations();
  }

  function handleNewChat() {
    setActiveId(null);
    setMobileHistoryOpen(false);
  }

  function handleSelect(id: number) {
    setActiveId(id);
    setMobileHistoryOpen(false);
  }

  async function handleDelete(id: number) {
    try {
      await askBragiApi.deleteConversation(id);
    } catch {
      // If it's already gone, still drop it from the visible list below.
    }
    if (id === activeId) setActiveId(null);
    refreshConversations();
  }

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <span className="b-spinner" />
      </main>
    );
  }

  const historySidebar = (
    <AskBragiHistorySidebar
      conversations={conversations}
      activeConversationId={activeId}
      onSelect={handleSelect}
      onNewChat={handleNewChat}
      onDelete={handleDelete}
      loading={conversationsLoading}
    />
  );

  return (
    <AppShell
      user={currentUser}
      title="Ask Bragi"
      subtitle="Ask about your medical record — every answer shows its source."
      rightContent={
        <button
          type="button"
          className="b-btn b-btn-secondary ask-bragi-history-toggle"
          onClick={() => setMobileHistoryOpen(true)}
          aria-label="Conversation history"
        >
          <IconMenu size={14} /> History
        </button>
      }
    >
      <div className="ask-bragi-workspace">
        <div className="ask-bragi-history-desktop-only">{historySidebar}</div>
        <AskBragiChat
          audience="patient"
          suggestions={SUGGESTIONS}
          conversationId={activeId ?? undefined}
          onConversationStarted={handleConversationStarted}
        />
      </div>

      {mobileHistoryOpen ? (
        <div className="ask-bragi-history-drawer-overlay" onClick={() => setMobileHistoryOpen(false)}>
          <div
            className="ask-bragi-history-drawer b-surface"
            role="dialog"
            aria-modal="true"
            aria-label="Conversation history"
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--s3)" }}>
              <strong>History</strong>
              <button
                type="button"
                className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
                onClick={() => setMobileHistoryOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            {historySidebar}
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
