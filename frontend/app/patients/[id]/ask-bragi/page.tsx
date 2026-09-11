"use client";

/**
 * Doctor's dedicated Ask Bragi workspace for ONE patient. History is
 * PATIENT-SCOPED (GET /ask-bragi/conversations?patient_id=...) — a
 * doctor never sees Patient B's conversations while looking at Patient
 * A, and switching the URL's patient id resets the active conversation
 * (see the render-time reset below) so a stale conversation for the
 * previous patient can never linger. The "Asking about" card keeps the
 * patient identity always visible next to the history list.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import AskBragiChat from "@/components/ask-bragi/ask-bragi-chat";
import { AskBragiHistorySidebar } from "@/components/ask-bragi/ask-bragi-history-sidebar";
import { ErrorNote } from "@/components/ui";
import { IconMenu, IconUsers } from "@/components/ui/icon";
import { api, getErrorMessage } from "@/lib/api";
import { AskBragiConversation, askBragiApi } from "@/lib/ask-bragi-api";
import { getHomeByRole } from "@/lib/routing";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type PatientProfileResponse = {
  patient: { id: number; full_name: string; date_of_birth?: string | null; sex?: string | null };
};

const SUGGESTIONS = [
  "Summarize recent changes",
  "Compare the latest labs to the previous ones",
  "What medications are recorded?",
  "When was the last admission?",
];

export default function PatientAskBragiPage() {
  const params = useParams();
  const router = useRouter();
  const patientId = Number(params.id);

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [patientName, setPatientName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [conversations, setConversations] = useState<AskBragiConversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);

  // Patient-switch safety: reset the active conversation the instant the
  // URL's patient id changes, in the SAME render as the change (not a
  // later effect) — no frame where a stale conversation for the
  // PREVIOUS patient could still be passed into AskBragiChat. The
  // backend would reject it anyway (a conversation belongs to one
  // patient), but resetting here means the UI never even shows that
  // confusing transition — it goes straight to "no conversation
  // selected yet for this patient".
  const [prevPatientId, setPrevPatientId] = useState(patientId);
  if (prevPatientId !== patientId) {
    setPrevPatientId(patientId);
    setActiveId(null);
  }

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (cancelled) return;
        if (me.data.role !== "doctor" && me.data.role !== "admin") {
          router.push(getHomeByRole(me.data.role));
          return;
        }
        setCurrentUser(me.data);
        const profile = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
        if (cancelled) return;
        setPatientName(profile.data.patient.full_name);
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, "Could not load this patient."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [patientId, router]);

  const refreshConversations = useCallback(async () => {
    try {
      const res = await askBragiApi.listConversations(patientId);
      setConversations(res.data);
    } catch {
      // Non-critical — the history sidebar just stays empty/stale.
    } finally {
      setConversationsLoading(false);
    }
  }, [patientId]);

  useEffect(() => {
    async function run() {
      if (currentUser) await refreshConversations();
    }
    run();
  }, [currentUser, patientId, refreshConversations]);

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
    <>
      <AskBragiHistorySidebar
        conversations={conversations}
        activeConversationId={activeId}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
        onDelete={handleDelete}
        loading={conversationsLoading}
      />
      {/* Compact patient anchor — the doctor should always be able to see
       * who Ask Bragi is discussing, even scrolled deep into a long
       * history list. No CNP, no demographic detail beyond a name — see
       * BRAGI_ASK_BRAGI_PLAN.md's minimization posture. */}
      <div className="b-surface ask-bragi-patient-card">
        <p className="muted-text" style={{ margin: "0 0 2px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Asking about
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <IconUsers size={15} />
          <strong>{patientName || "Patient"}</strong>
        </div>
      </div>
    </>
  );

  return (
    <AppShell
      user={currentUser}
      title="Ask Bragi"
      subtitle={patientName ? `About ${patientName}'s record` : undefined}
      breadcrumbs={[
        { label: patientName || "Patient", href: `/patients/${patientId}` },
        { label: "Ask Bragi" },
      ]}
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
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : (
        <div className="ask-bragi-workspace">
          <div className="ask-bragi-history-desktop-only">{historySidebar}</div>
          <AskBragiChat
            audience="doctor"
            patientId={patientId}
            suggestions={SUGGESTIONS}
            conversationId={activeId ?? undefined}
            onConversationStarted={handleConversationStarted}
          />
        </div>
      )}

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
