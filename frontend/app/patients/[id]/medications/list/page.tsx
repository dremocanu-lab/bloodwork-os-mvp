"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type PatientMedication = {
  id: number;
  name: string;
  status: string;
  dose_strength?: string | null;
  frequency?: string | null;
  reason?: string | null;
  is_uncertain: boolean;
  official_match_status?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
};

const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  as_needed: "As needed",
  paused: "Paused",
  stopped: "Stopped",
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--success-bg)", text: "var(--success-text)" },
  as_needed: { bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", text: "var(--primary)" },
  paused: { bg: "var(--warn-bg)", text: "var(--warn-text)" },
  stopped: { bg: "var(--panel-2)", text: "var(--muted)" },
};

export default function DoctorMedicationsListPage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [medications, setMedications] = useState<PatientMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") { router.replace("/my-records/medications"); return; }
        const res = await api.get<PatientMedication[]>(`/patients/${patientId}/medications`);
        setMedications(Array.isArray(res.data) ? res.data : []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load medications."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [patientId, router]);

  const filtered = statusFilter ? medications.filter((m) => m.status === statusFilter) : medications;

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading medications…</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser!}
      title="Patient Medications"
      subtitle="View only — patient-entered records"
      rightContent={
        <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          Back to chart
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      <div className="soft-card-tight" style={{ marginBottom: 20, padding: 14, background: "var(--panel-2)" }}>
        <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 3 }}>Patient-entered records — view only</div>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
          These records are entered by the patient and are not clinically verified. Dose not verified · Frequency not verified · Review with the patient directly.
        </div>
      </div>

      {/* Filter row */}
      {medications.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          {["", "active", "as_needed", "paused", "stopped"].map((s) => (
            <button
              key={s}
              type="button"
              className={statusFilter === s ? "primary-btn" : "secondary-btn"}
              style={{ borderRadius: 999, padding: "7px 14px", fontSize: 13 }}
              onClick={() => setStatusFilter(s)}
            >
              {s === "" ? `All (${medications.length})` : `${STATUS_LABELS[s]} (${medications.filter((m) => m.status === s).length})`}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gap: 12 }}>
        {filtered.map((med) => {
          const statusStyle = STATUS_COLORS[med.status] || STATUS_COLORS.stopped;
          return (
            <button
              key={med.id}
              type="button"
              onClick={() => router.push(`/patients/${patientId}/medications/${med.id}`)}
              className="soft-card-tight"
              style={{ padding: 18, textAlign: "left", display: "block", width: "100%", cursor: "pointer" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                    <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: statusStyle.bg, color: statusStyle.text }}>
                      {STATUS_LABELS[med.status] || med.status}
                    </span>
                    {med.is_uncertain && (
                      <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                        Dose not verified
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em" }}>{med.name}</div>
                  <div className="muted-text" style={{ marginTop: 5, fontSize: 13 }}>
                    {[med.dose_strength, med.frequency].filter(Boolean).join(" · ") || "No dose or frequency recorded"}
                  </div>
                  {med.reason && (
                    <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>Recorded reason: {med.reason}</div>
                  )}
                </div>

                {(med.start_date || med.stop_date) && (
                  <div style={{ flexShrink: 0, textAlign: "right" }}>
                    {med.start_date && <div className="muted-text" style={{ fontSize: 11 }}>Since {med.start_date}</div>}
                    {med.stop_date && <div className="muted-text" style={{ fontSize: 11 }}>Stopped {med.stop_date}</div>}
                  </div>
                )}
              </div>
            </button>
          );
        })}

        {filtered.length === 0 && (
          <div className="muted-text" style={{ padding: "12px 0" }}>
            {medications.length === 0 ? "This patient has not recorded any medications." : "No medications match this filter."}
          </div>
        )}
      </div>
    </AppShell>
  );
}
