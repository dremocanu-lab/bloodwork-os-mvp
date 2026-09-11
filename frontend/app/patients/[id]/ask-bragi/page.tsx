"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import AskBragiChat from "@/components/ask-bragi/ask-bragi-chat";
import { ErrorNote } from "@/components/ui";
import { api, getErrorMessage } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type PatientProfileResponse = {
  patient: { id: number; full_name: string };
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

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <span className="b-spinner" />
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="Ask Bragi"
      subtitle={patientName ? `About ${patientName}'s record` : undefined}
      breadcrumbs={[
        { label: patientName || "Patient", href: `/patients/${patientId}` },
        { label: "Ask Bragi" },
      ]}
    >
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : (
        <AskBragiChat audience="doctor" patientId={patientId} suggestions={SUGGESTIONS} />
      )}
    </AppShell>
  );
}
