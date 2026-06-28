"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: string;
};

type PatientMedication = {
  id: number;
  name: string;
  dose_strength?: string | null;
  frequency?: string | null;
  reason?: string | null;
  status: string;
  route_form?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
  prescriber?: string | null;
  is_uncertain: boolean;
  official_match_status?: string | null;
  official_source_name?: string | null;
  created_at: string;
  updated_at?: string | null;
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

const MATCH_LABELS: Record<string, string> = {
  pending: "Looking up…",
  matched: "Matched",
  not_matched: "No official match",
  multiple: "Multiple candidates",
  vague: "Name too vague",
  error: "Lookup error",
};

export default function MedicationsListPage() {
  const router = useRouter();
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
        if (me.data.role !== "patient") {
          router.push(getHomeByRole(me.data.role));
          return;
        }
        const meds = await api.get<PatientMedication[]>("/my/medications");
        setMedications(meds.data);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load medications."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const filtered = statusFilter
    ? medications.filter((m) => m.status === statusFilter)
    : medications;

  const active = medications.filter((m) => m.status === "active").length;
  const asNeeded = medications.filter((m) => m.status === "as_needed").length;

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
      title="My Medications"
      rightContent={
        <button
          type="button"
          className="primary-btn"
          onClick={() => router.push("/my-records/medications/new")}
        >
          Add medication
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}
        >
          {error}
        </div>
      )}

      {/* Safety notice */}
      <div
        className="soft-card-tight"
        style={{ marginBottom: 20, padding: 14, background: "color-mix(in srgb, var(--primary) 8%, var(--panel))", borderColor: "color-mix(in srgb, var(--primary) 22%, transparent)" }}
      >
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--primary)", marginBottom: 4 }}>
          Patient-entered medication records
        </div>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
          These records are entered by you and are not verified by a clinician. Do not start, stop, or change any medication without speaking to a licensed clinician. Official label information is shown for reference only and does not replace medical advice.
        </div>
      </div>

      {/* Summary row */}
      {medications.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 20 }}>
          {[
            { label: "Total", value: medications.length, onClick: () => setStatusFilter("") },
            { label: "Active", value: active, onClick: () => setStatusFilter("active") },
            { label: "As needed", value: asNeeded, onClick: () => setStatusFilter("as_needed") },
          ].map(({ label, value, onClick }) => (
            <div
              key={label}
              className="soft-card"
              style={{ padding: "14px 18px", cursor: "pointer" }}
              onClick={onClick}
            >
              <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
              <div style={{ fontSize: 34, fontWeight: 950, letterSpacing: "-0.04em", lineHeight: 1, marginTop: 6 }}>{value}</div>
            </div>
          ))}
        </div>
      )}

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
              {s === "" ? "All" : STATUS_LABELS[s]}
            </button>
          ))}
        </div>
      )}

      {/* Medication cards */}
      <div style={{ display: "grid", gap: 12 }}>
        {filtered.map((med) => {
          const statusStyle = STATUS_COLORS[med.status] || STATUS_COLORS.stopped;
          return (
            <button
              key={med.id}
              type="button"
              onClick={() => router.push(`/my-records/medications/${med.id}`)}
              className="soft-card-tight"
              style={{
                padding: 18,
                textAlign: "left",
                display: "block",
                width: "100%",
                cursor: "pointer",
                transition: "border-color 140ms ease",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                    <span style={{
                      padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800,
                      background: statusStyle.bg, color: statusStyle.text,
                    }}>
                      {STATUS_LABELS[med.status] || med.status}
                    </span>
                    {med.is_uncertain && (
                      <span style={{
                        padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800,
                        background: "var(--warn-bg)", color: "var(--warn-text)",
                      }}>
                        Dose not verified
                      </span>
                    )}
                    {med.official_match_status === "matched" && (
                      <span style={{
                        padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800,
                        background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)",
                      }}>
                        Official info available
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>{med.name}</div>
                  <div className="muted-text" style={{ marginTop: 5, fontSize: 13, lineHeight: 1.6 }}>
                    {[med.dose_strength, med.route_form, med.frequency].filter(Boolean).join(" · ") || "No dose or frequency recorded"}
                  </div>
                  {med.reason && (
                    <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>
                      Recorded reason: {med.reason}
                    </div>
                  )}
                </div>

                <div style={{ flexShrink: 0, textAlign: "right" }}>
                  <div className="muted-text" style={{ fontSize: 11 }}>
                    {MATCH_LABELS[med.official_match_status || ""] || "Not looked up"}
                  </div>
                  {med.start_date && (
                    <div className="muted-text" style={{ fontSize: 11, marginTop: 4 }}>
                      Since {med.start_date}
                    </div>
                  )}
                </div>
              </div>
            </button>
          );
        })}

        {filtered.length === 0 && medications.length === 0 && (
          <div className="soft-card" style={{ padding: 32, textAlign: "center" }}>
            <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 10 }}>No medications recorded yet</div>
            <div className="muted-text" style={{ marginBottom: 20, lineHeight: 1.65 }}>
              Keep a record of your current medications here. This information is shared with doctors who have access to your chart.
            </div>
            <button type="button" className="primary-btn" onClick={() => router.push("/my-records/medications/new")}>
              Add first medication
            </button>
          </div>
        )}

        {filtered.length === 0 && medications.length > 0 && (
          <div className="muted-text">No medications match this filter.</div>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <button type="button" className="secondary-btn" onClick={() => router.push("/my-records")}>
          Back to my records
        </button>
      </div>
    </AppShell>
  );
}
