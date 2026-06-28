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
  role: "patient" | "doctor" | "admin" | "care_partner";
};

const STATUS_OPTIONS = [
  { value: "active", label: "Active — currently taking" },
  { value: "as_needed", label: "As needed — only when required" },
  { value: "paused", label: "Paused — temporarily not taking" },
  { value: "stopped", label: "Stopped — no longer taking" },
];

export default function NewMedicationPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  const [name, setName] = useState("");
  const [doseStrength, setDoseStrength] = useState("");
  const [frequency, setFrequency] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("active");
  const [routeForm, setRouteForm] = useState("");
  const [startDate, setStartDate] = useState("");
  const [stopDate, setStopDate] = useState("");
  const [prescriber, setPrescriber] = useState("");
  const [extraInfo, setExtraInfo] = useState("");
  const [isUncertain, setIsUncertain] = useState(false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role !== "patient") {
          router.push(getHomeByRole(me.data.role));
        }
      } catch {
        router.push("/login");
      } finally {
        setAuthLoading(false);
      }
    }
    init();
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Medication name is required.");
      return;
    }
    try {
      setSaving(true);
      setError("");
      const response = await api.post<{ id: number }>("/my/medications", {
        name: name.trim(),
        dose_strength: doseStrength.trim() || null,
        frequency: frequency.trim() || null,
        reason: reason.trim() || null,
        status,
        route_form: routeForm.trim() || null,
        start_date: startDate || null,
        stop_date: stopDate || null,
        prescriber: prescriber.trim() || null,
        extra_info: extraInfo.trim() || null,
        is_uncertain: isUncertain,
      });
      router.push(`/my-records/medications/${response.data.id}`);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save medication."));
      setSaving(false);
    }
  }

  if (authLoading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading…</p>
      </main>
    );
  }

  return (
    <AppShell user={currentUser!} title="Add Medication">
      {/* Safety notice */}
      <div
        className="soft-card-tight"
        style={{ marginBottom: 24, padding: 14, background: "color-mix(in srgb, var(--primary) 8%, var(--panel))", borderColor: "color-mix(in srgb, var(--primary) 22%, transparent)" }}
      >
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--primary)", marginBottom: 4 }}>
          Patient-entered medication record
        </div>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
          Enter exactly what you take or have been prescribed. Do not start, stop, or change any medication without speaking to a licensed clinician. This record is not medical advice. Dose and frequency are not verified.
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>Medication details</div>

          {error && (
            <div style={{ marginBottom: 16, padding: "12px 16px", borderRadius: 12, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)", fontSize: 14 }}>
              {error}
            </div>
          )}

          {/* Name */}
          <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>
              Medication name <span style={{ color: "var(--danger-text)" }}>*</span>
            </span>
            <input
              className="text-input"
              type="text"
              placeholder="e.g. Lisinopril, Metformin, Aspirin…"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
          </label>

          {/* Status */}
          <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>Status</span>
            <select
              className="text-input"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              style={{ cursor: "pointer" }}
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          {/* Dose and frequency row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>Dose / strength</span>
              <input
                className="text-input"
                type="text"
                placeholder="e.g. 10 mg, 500 mg, 81 mg…"
                value={doseStrength}
                onChange={(e) => setDoseStrength(e.target.value)}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>Frequency</span>
              <input
                className="text-input"
                type="text"
                placeholder="e.g. Once daily, Twice a day…"
                value={frequency}
                onChange={(e) => setFrequency(e.target.value)}
              />
            </label>
          </div>

          {/* Route */}
          <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>Form / route</span>
            <input
              className="text-input"
              type="text"
              placeholder="e.g. Tablet, Capsule, Injection, Patch…"
              value={routeForm}
              onChange={(e) => setRouteForm(e.target.value)}
            />
          </label>

          {/* Uncertain checkbox */}
          <label style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 20, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={isUncertain}
              onChange={(e) => setIsUncertain(e.target.checked)}
              style={{ marginTop: 2, width: 16, height: 16, flexShrink: 0 }}
            />
            <div>
              <div style={{ fontSize: 13, fontWeight: 800 }}>Dose not verified</div>
              <div className="muted-text" style={{ fontSize: 12 }}>Check this if you are unsure of the exact dose or frequency</div>
            </div>
          </label>

          {/* Reason */}
          <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>Recorded reason</span>
            <textarea
              className="text-input"
              rows={2}
              placeholder="e.g. High blood pressure, Type 2 diabetes, Pain relief…"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ resize: "vertical" }}
            />
            <span className="muted-text" style={{ fontSize: 11 }}>
              This is the reason you recorded — not a diagnosis.
            </span>
          </label>
        </div>

        <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>Optional details</div>

          {/* Dates row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>Start date</span>
              <input
                className="text-input"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>Stop date</span>
              <input
                className="text-input"
                type="date"
                value={stopDate}
                onChange={(e) => setStopDate(e.target.value)}
              />
            </label>
          </div>

          {/* Prescriber */}
          <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>Prescribed by</span>
            <input
              className="text-input"
              type="text"
              placeholder="e.g. Dr. Smith, General practitioner…"
              value={prescriber}
              onChange={(e) => setPrescriber(e.target.value)}
            />
          </label>

          {/* Extra info */}
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>Additional notes</span>
            <textarea
              className="text-input"
              rows={3}
              placeholder="Any other information you want to record…"
              value={extraInfo}
              onChange={(e) => setExtraInfo(e.target.value)}
              style={{ resize: "vertical" }}
            />
          </label>
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <button type="submit" className="primary-btn" disabled={saving}>
            {saving ? "Saving…" : "Save medication"}
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => router.push("/my-records/medications")}
          >
            Cancel
          </button>
        </div>
      </form>
    </AppShell>
  );
}
