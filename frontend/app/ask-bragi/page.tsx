"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import AskBragiChat from "@/components/ask-bragi/ask-bragi-chat";
import { api } from "@/lib/api";
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
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (me.data.role !== "patient") {
          router.push(getHomeByRole(me.data.role));
          return;
        }
        setCurrentUser(me.data);
      } catch {
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <span className="b-spinner" />
      </main>
    );
  }

  return (
    <AppShell user={currentUser} title="Ask Bragi" subtitle="Ask about your medical record — every answer shows its source.">
      <AskBragiChat audience="patient" suggestions={SUGGESTIONS} />
    </AppShell>
  );
}
