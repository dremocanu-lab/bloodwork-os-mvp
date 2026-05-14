"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type DoctorDetail = {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
  hospital_name?: string | null;
  current_patient_count: number;
  historical_assignment_count: number;
};

type CurrentPatient = {
  assignment_id: number;
  patient_id: number;
  full_name: string;
  date_of_birth?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
  assigned_at: string;
};

type HistoryEntry = {
  assignment_id: number;
  patient_id: number;
  full_name: string;
  date_of_birth?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
  assigned_at: string;
  ended_at?: string | null;
  is_active: boolean;
};

function maskCnp(cnp?: string | null): string {
  if (!cnp) return "—";
  if (cnp.length <= 4) return cnp;
  return "•".repeat(cnp.length - 4) + cnp.slice(-4);
}

function formatDate(v?: string | null) {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function DoctorDetailPage() {
  const router = useRouter();
  const params = useParams();
  const doctorId = params?.id as string;
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [doctor, setDoctor] = useState<DoctorDetail | null>(null);
  const [currentPatients, setCurrentPatients] = useState<CurrentPatient[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"current" | "history">("current");
  const [endingId, setEndingId] = useState<number | null>(null);
  const [endError, setEndError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (me.data.role !== "admin") { router.replace("/login"); return; }
        setCurrentUser(me.data);

        const [docRes, currentRes, histRes] = await Promise.all([
          api.get<DoctorDetail>(`/admin/doctors/${doctorId}`),
          api.get<CurrentPatient[]>(`/admin/doctors/${doctorId}/current-patients`),
          api.get<HistoryEntry[]>(`/admin/doctors/${doctorId}/patient-history`),
        ]);
        setDoctor(docRes.data);
        setCurrentPatients(currentRes.data || []);
        setHistory(histRes.data || []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load doctor details."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router, doctorId]);

  async function endAssignment(assignmentId: number) {
    setEndingId(assignmentId);
    setEndError("");
    try {
      await api.post(`/admin/assignments/${assignmentId}/end`, {});
      setCurrentPatients((prev) => prev.filter((p) => p.assignment_id !== assignmentId));
      setHistory((prev) =>
        prev.map((h) =>
          h.assignment_id === assignmentId
            ? { ...h, is_active: false, ended_at: new Date().toISOString() }
            : h
        )
      );
      if (doctor) {
        setDoctor({ ...doctor, current_patient_count: doctor.current_patient_count - 1 });
      }
    } catch (err) {
      setEndError(getErrorMessage(err, "Could not end assignment."));
    } finally {
      setEndingId(null);
    }
  }

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  if (!doctor) {
    return (
      <AppShell user={currentUser} title="Doctor not found">
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="muted-text">{error || "Doctor not found."}</div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={doctor.full_name}
      subtitle={[doctor.department, doctor.hospital_name].filter(Boolean).join(" · ")}
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{ marginBottom: 20, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}
        >
          {error}
        </div>
      )}

      {/* Doctor header card */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: 999,
              background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))",
              border: "1px solid color-mix(in srgb, var(--primary) 22%, transparent)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 950,
              fontSize: 20,
              color: "var(--primary)",
              flexShrink: 0,
            }}
          >
            {doctor.full_name.charAt(0).toUpperCase()}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 950, fontSize: 20, letterSpacing: "-0.04em", lineHeight: 1.15 }}>
              {doctor.full_name}
            </div>
            <div className="muted-text" style={{ marginTop: 4, fontSize: 14 }}>{doctor.email}</div>
            {(doctor.department || doctor.hospital_name) && (
              <div
                className="muted-text"
                style={{ marginTop: 4, fontSize: 12, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}
              >
                {[doctor.department, doctor.hospital_name].filter(Boolean).join(" · ")}
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 24, flexShrink: 0, alignItems: "flex-start" }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 950, letterSpacing: "-0.05em", color: "var(--primary)" }}>
                {doctor.current_patient_count}
              </div>
              <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {t("currentPatientsCount")}
              </div>
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 950, letterSpacing: "-0.05em" }}>
                {doctor.historical_assignment_count}
              </div>
              <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {t("historicalAssignmentsCount")}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {(["current", "history"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={activeTab === tab ? "primary-btn" : "secondary-btn"}
            onClick={() => setActiveTab(tab)}
            style={{ fontSize: 14 }}
          >
            {tab === "current" ? t("currentPatientsTab") : t("patientHistoryTab")}
          </button>
        ))}
      </div>

      {endError && (
        <div
          className="soft-card-tight"
          style={{ marginBottom: 16, padding: 14, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)", fontSize: 13 }}
        >
          {endError}
        </div>
      )}

      {/* Current Patients tab */}
      {activeTab === "current" && (
        <div className="soft-card" style={{ padding: 24 }}>
          {currentPatients.length === 0 ? (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noCurrentPatientsAdmin")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {currentPatients.map((p) => (
                <div
                  key={p.assignment_id}
                  className="soft-card-tight"
                  style={{
                    padding: "14px 18px",
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1fr) auto",
                    gap: 16,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 950, fontSize: 15, letterSpacing: "-0.02em" }}>{p.full_name}</div>
                    <div className="muted-text" style={{ marginTop: 5, fontSize: 12, display: "flex", gap: 14, flexWrap: "wrap" }}>
                      {p.date_of_birth && <span>DOB: {formatDate(p.date_of_birth)}</span>}
                      {p.cnp && <span>CNP: {maskCnp(p.cnp)}</span>}
                      <span>{t("assignedOn")}: {formatDate(p.assigned_at)}</span>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => endAssignment(p.assignment_id)}
                    disabled={endingId === p.assignment_id}
                    style={{ whiteSpace: "nowrap", fontSize: 13, color: "var(--danger-text)", borderColor: "var(--danger-border)" }}
                  >
                    {endingId === p.assignment_id ? t("endingAssignment") : t("endAssignment")}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Patient History tab */}
      {activeTab === "history" && (
        <div className="soft-card" style={{ padding: 24 }}>
          {history.length === 0 ? (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noPatientHistoryAdmin")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {history.map((h) => (
                <div
                  key={h.assignment_id}
                  className="soft-card-tight"
                  style={{
                    padding: "14px 18px",
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1fr) auto",
                    gap: 16,
                    alignItems: "center",
                    opacity: h.is_active ? 1 : 0.7,
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 950, fontSize: 15, letterSpacing: "-0.02em" }}>{h.full_name}</div>
                    <div className="muted-text" style={{ marginTop: 5, fontSize: 12, display: "flex", gap: 14, flexWrap: "wrap" }}>
                      {h.date_of_birth && <span>DOB: {formatDate(h.date_of_birth)}</span>}
                      {h.cnp && <span>CNP: {maskCnp(h.cnp)}</span>}
                      <span>{t("assignedOn")}: {formatDate(h.assigned_at)}</span>
                      {h.ended_at && <span>{t("endedOn")}: {formatDate(h.ended_at)}</span>}
                    </div>
                  </div>

                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 900,
                      padding: "4px 10px",
                      borderRadius: 999,
                      background: h.is_active
                        ? "color-mix(in srgb, var(--primary) 12%, var(--panel-2))"
                        : "var(--panel-2)",
                      color: h.is_active ? "var(--primary)" : "var(--muted)",
                      border: `1px solid ${h.is_active ? "color-mix(in srgb, var(--primary) 25%, transparent)" : "var(--border)"}`,
                      whiteSpace: "nowrap",
                      flexShrink: 0,
                    }}
                  >
                    {h.is_active ? t("assignmentStatusActive") : t("assignmentStatusEnded")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </AppShell>
  );
}
