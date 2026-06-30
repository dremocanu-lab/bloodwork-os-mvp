"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import EmergencyShell from "@/components/emergency-shell";
import { useLanguage } from "@/lib/i18n";
import {
  emergencyApi,
  getErrorMessage,
  EMERGENCY_STORAGE_KEYS,
  clearEmergencySession,
  getEmergencyUser,
} from "@/lib/emergency-api";

// ── Types ─────────────────────────────────────────────────────────────────────

type Lab = {
  name: string | null;
  value: string | null;
  unit: string | null;
  flag: string | null;
  reference_range: string | null;
};

type LatestBloodwork = {
  document_id: number;
  filename: string;
  test_date: string | null;
  lab_name: string | null;
  labs: Lab[];
};

type Document = {
  id: number;
  section: string;
  filename: string;
  test_date: string | null;
  lab_name: string | null;
  report_name: string | null;
  is_verified: boolean;
  created_at: string | null;
};

type Medication = {
  id: number;
  name: string;
  dose_strength: string | null;
  frequency: string | null;
  status: string;
  route_form: string | null;
  is_uncertain: boolean;
};

type PatientData = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth: string | null;
    age: string | null;
    sex: string | null;
    bragi_code: string | null;
  };
  session: {
    id: number;
    expires_at: string;
    reason: string;
  };
  medications: Medication[];
  documents: Document[];
  latest_bloodwork: LatestBloodwork | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const ABNORMAL_FLAGS = new Set(["high", "low", "abnormal", "critical", "borderline", "elevated", "h", "l"]);

function isAbnormalFlag(flag: string | null): boolean {
  return !!flag && ABNORMAL_FLAGS.has(flag.toLowerCase());
}

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso.slice(0, 10)).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

const SECTION_LABELS: Record<string, string> = {
  bloodwork: "Bloodwork",
  discharge_summary: "Discharge summary",
  notes: "Clinical note",
  medications: "Medications",
  scans: "Scan / imaging",
  hospitalizations: "Hospitalization",
  other: "Document",
};

// ── Section card ──────────────────────────────────────────────────────────────

function SectionCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="soft-card"
      style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 14 }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 900,
          textTransform: "uppercase",
          letterSpacing: "0.07em",
          color: "var(--muted)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EmergencyPatientPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = Number(params.id);

  const [user, setUser] = useState<ReturnType<typeof getEmergencyUser>>(null);
  const [data, setData] = useState<PatientData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Timer from stored expires_at
  const startTimer = useCallback((expiresAt: string) => {
    if (timerRef.current) clearInterval(timerRef.current);
    const expiresMs = new Date(expiresAt).getTime();
    const tick = () => {
      const left = Math.max(0, Math.floor((expiresMs - Date.now()) / 1000));
      setSecondsLeft(left);
      if (left === 0 && timerRef.current) clearInterval(timerRef.current);
    };
    tick();
    timerRef.current = setInterval(tick, 1000);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    const u = getEmergencyUser();
    if (!u || (u.role !== "emergency_worker" && u.role !== "admin")) {
      router.replace("/emergency/login");
      return;
    }
    setUser(u);

    const sessionId = localStorage.getItem(EMERGENCY_STORAGE_KEYS.sessionId);
    const expiresAt = localStorage.getItem(EMERGENCY_STORAGE_KEYS.expiresAt);

    if (!sessionId || !expiresAt) {
      router.replace("/emergency/search");
      return;
    }

    // Start the frontend timer immediately from stored expires_at
    startTimer(expiresAt);

    const sid = Number(sessionId);
    emergencyApi
      .get(`/emergency/patients/${patientId}`, { params: { session_id: sid } })
      .then((res) => {
        const pd = res.data as PatientData;
        setData(pd);
        // Sync timer to server-reported expires_at (authoritative)
        startTimer(pd.session.expires_at);
      })
      .catch((err) => {
        const msg = getErrorMessage(err, "Failed to load patient data.");
        if (err?.response?.status === 403) {
          setError(t("emergencyExpired"));
        } else {
          setError(msg);
        }
      })
      .finally(() => setLoading(false));
  }, [patientId, router, startTimer, t]);

  function handleLogout() {
    clearEmergencySession();
    router.push("/emergency/login");
  }

  function handleReturnToSearch() {
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.sessionId);
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.expiresAt);
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.patientId);
    router.push("/emergency/search");
  }

  const expired = secondsLeft !== null && secondsLeft <= 0;
  const warningZone = secondsLeft !== null && secondsLeft > 0 && secondsLeft <= 300;

  // ── Timer banner ───────────────────────────────────────────────────────────

  const timerBanner = secondsLeft !== null && (
    <div
      style={{
        padding: "10px 20px",
        borderRadius: 10,
        marginBottom: 24,
        display: "flex",
        alignItems: "center",
        gap: 12,
        background: expired
          ? "rgba(220,38,38,0.10)"
          : warningZone
          ? "rgba(217,119,6,0.10)"
          : "rgba(22,163,74,0.08)",
        border: `1px solid ${
          expired
            ? "rgba(220,38,38,0.25)"
            : warningZone
            ? "rgba(217,119,6,0.25)"
            : "rgba(22,163,74,0.20)"
        }`,
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          flexShrink: 0,
          background: expired ? "#dc2626" : warningZone ? "#d97706" : "#16a34a",
          display: "inline-block",
        }}
      />
      <span
        style={{
          fontSize: 12,
          fontWeight: 700,
          color: expired ? "#dc2626" : warningZone ? "#d97706" : "#16a34a",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          flexShrink: 0,
        }}
      >
        {expired
          ? t("emergencyExpired")
          : warningZone
          ? t("emergencyWarningUnder5Min")
          : t("emergencyActiveSession")}
      </span>
      {!expired && (
        <>
          <span className="muted-text" style={{ fontSize: 12 }}>·</span>
          <span className="muted-text" style={{ fontSize: 12 }}>{t("emergencyExpiresIn")}</span>
          <span
            style={{
              fontFamily: "monospace",
              fontWeight: 800,
              fontSize: 16,
              letterSpacing: "0.05em",
              color: warningZone ? "#d97706" : "var(--foreground)",
            }}
          >
            {formatTime(secondsLeft!)}
          </span>
        </>
      )}
    </div>
  );

  // ── Expired state ──────────────────────────────────────────────────────────

  if (expired) {
    return (
      <EmergencyShell user={user} onLogout={handleLogout}>
        {timerBanner}
        <div
          className="soft-card"
          style={{ padding: "40px 32px", textAlign: "center", maxWidth: 480, margin: "0 auto" }}
        >
          <div style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
          <h2 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 10px 0" }}>
            {t("emergencyExpired")}
          </h2>
          <p className="muted-text" style={{ fontSize: 14, lineHeight: 1.6, marginBottom: 28 }}>
            {t("emergencyExpiredBody")}
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <button type="button" className="primary-btn" onClick={handleReturnToSearch}>
              {t("emergencyReturnToSearch")}
            </button>
          </div>
        </div>
      </EmergencyShell>
    );
  }

  // ── Loading / error ────────────────────────────────────────────────────────

  if (loading) {
    return (
      <EmergencyShell user={user} onLogout={handleLogout}>
        {timerBanner}
        <p className="muted-text" style={{ fontSize: 14 }}>Loading patient data…</p>
      </EmergencyShell>
    );
  }

  if (error || !data) {
    return (
      <EmergencyShell user={user} onLogout={handleLogout}>
        {timerBanner}
        <div className="soft-card" style={{ padding: "28px 24px", textAlign: "center" }}>
          <p style={{ color: "var(--danger-text)", fontSize: 14, marginBottom: 16 }}>
            {error || "Could not load patient data."}
          </p>
          <button type="button" className="secondary-btn" onClick={handleReturnToSearch}>
            {t("emergencyReturnToSearch")}
          </button>
        </div>
      </EmergencyShell>
    );
  }

  const { patient, medications, documents, latest_bloodwork } = data;
  const activeMeds = medications.filter((m) => m.status === "active");
  const otherMeds = medications.filter((m) => m.status !== "active");

  const docsBySection = documents.reduce<Record<string, Document[]>>((acc, doc) => {
    const sec = doc.section || "other";
    (acc[sec] = acc[sec] || []).push(doc);
    return acc;
  }, {});

  return (
    <EmergencyShell user={user} onLogout={handleLogout}>
      {/* Timer banner */}
      {timerBanner}

      {/* Patient header */}
      <div className="soft-card" style={{ padding: "20px 24px", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "0.07em",
                color: "#dc2626",
                marginBottom: 6,
              }}
            >
              {t("emergencyPatientIdentity")}
            </div>
            <div style={{ fontSize: 24, fontWeight: 900, letterSpacing: "-0.02em" }}>
              {patient.full_name}
            </div>
            <div
              className="muted-text"
              style={{ fontSize: 13, marginTop: 5, display: "flex", gap: 14, flexWrap: "wrap" }}
            >
              {patient.date_of_birth && <span>DOB: {formatDate(patient.date_of_birth)}</span>}
              {patient.age && <span>Age: {patient.age}</span>}
              {patient.sex && <span>Sex: {patient.sex}</span>}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
            {patient.bragi_code && (
              <div
                style={{
                  padding: "5px 12px",
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontFamily: "monospace",
                  fontSize: 13,
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                }}
              >
                {patient.bragi_code}
              </div>
            )}
            <div
              style={{
                padding: "4px 10px",
                background: "rgba(220,38,38,0.08)",
                border: "1px solid rgba(220,38,38,0.20)",
                borderRadius: 6,
                fontSize: 10,
                fontWeight: 800,
                color: "#dc2626",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              {t("emergencyReadOnly")}
            </div>
          </div>
        </div>
      </div>

      {/* Main grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
          gap: 16,
          marginBottom: 20,
        }}
      >
        {/* Medications */}
        <SectionCard title={t("emergencyMedications")}>
          {medications.length === 0 ? (
            <p className="muted-text" style={{ fontSize: 13 }}>{t("emergencyNoMedications")}</p>
          ) : (
            <>
              {activeMeds.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {activeMeds.map((m) => (
                    <div
                      key={m.id}
                      style={{
                        padding: "10px 12px",
                        background: "var(--panel-2)",
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{m.name}</div>
                      <div className="muted-text" style={{ fontSize: 12, marginTop: 3 }}>
                        {[m.dose_strength, m.frequency, m.route_form]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </div>
                      {m.is_uncertain && (
                        <div
                          style={{
                            marginTop: 5,
                            fontSize: 10,
                            fontWeight: 700,
                            color: "var(--warn-text)",
                            textTransform: "uppercase",
                          }}
                        >
                          {t("emergencySourceRequiresVerification")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {otherMeds.length > 0 && (
                <details style={{ marginTop: activeMeds.length ? 8 : 0 }}>
                  <summary
                    className="muted-text"
                    style={{ fontSize: 12, cursor: "pointer", marginBottom: 6 }}
                  >
                    {otherMeds.length} other medication{otherMeds.length !== 1 ? "s" : ""} (stopped / unknown)
                  </summary>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                    {otherMeds.map((m) => (
                      <div
                        key={m.id}
                        style={{
                          padding: "8px 12px",
                          background: "var(--panel-2)",
                          borderRadius: 8,
                          opacity: 0.7,
                        }}
                      >
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{m.name}</div>
                        <div className="muted-text" style={{ fontSize: 11 }}>{m.status}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
              <p
                className="muted-text"
                style={{ fontSize: 11, marginTop: 4 }}
              >
                {t("emergencyPatientEntered")} · {t("emergencySourceLinkedRecords")}
              </p>
            </>
          )}
        </SectionCard>

        {/* Latest bloodwork */}
        {latest_bloodwork ? (
          <SectionCard title={t("emergencyLatestBloodwork")}>
            <div className="muted-text" style={{ fontSize: 12 }}>
              {latest_bloodwork.lab_name && <span>{latest_bloodwork.lab_name} · </span>}
              {latest_bloodwork.test_date ? formatDate(latest_bloodwork.test_date) : "Date unknown"}
            </div>
            {latest_bloodwork.labs.length === 0 ? (
              <p className="muted-text" style={{ fontSize: 13 }}>No lab values extracted.</p>
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "6px 12px",
                  maxHeight: 320,
                  overflowY: "auto",
                }}
              >
                {latest_bloodwork.labs.map((lab, i) => {
                  const abnormal = isAbnormalFlag(lab.flag);
                  return (
                    <div
                      key={i}
                      style={{
                        padding: "6px 8px",
                        borderRadius: 6,
                        background: abnormal ? "rgba(220,38,38,0.07)" : "var(--panel-2)",
                        border: `1px solid ${abnormal ? "rgba(220,38,38,0.18)" : "var(--border)"}`,
                      }}
                    >
                      <div
                        className="muted-text"
                        style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", marginBottom: 2 }}
                      >
                        {lab.name || "—"}
                      </div>
                      <div
                        style={{
                          fontSize: 13,
                          fontWeight: 700,
                          color: abnormal ? "var(--danger-text)" : "var(--foreground)",
                        }}
                      >
                        {lab.value || "—"}{lab.unit ? ` ${lab.unit}` : ""}
                      </div>
                      {lab.reference_range && (
                        <div className="muted-text" style={{ fontSize: 9, marginTop: 1 }}>
                          ref: {lab.reference_range}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <p className="muted-text" style={{ fontSize: 11 }}>
              {t("emergencySourceLinkedRecords")} · {t("emergencyNotADiagnosis")}
            </p>
          </SectionCard>
        ) : (
          <SectionCard title={t("emergencyLatestBloodwork")}>
            <p className="muted-text" style={{ fontSize: 13 }}>
              No bloodwork documents found.
            </p>
          </SectionCard>
        )}
      </div>

      {/* Recent documents by section */}
      <SectionCard title={t("emergencyRecentDocuments")}>
        {documents.length === 0 ? (
          <p className="muted-text" style={{ fontSize: 13 }}>{t("emergencyNoDocuments")}</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {Object.entries(docsBySection).map(([section, docs]) => (
              <div key={section}>
                <div
                  className="muted-text"
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    marginBottom: 6,
                    marginTop: 4,
                  }}
                >
                  {SECTION_LABELS[section] || section}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {docs.map((doc) => (
                    <div
                      key={doc.id}
                      style={{
                        padding: "9px 12px",
                        background: "var(--panel-2)",
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: 600,
                            fontSize: 13,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {doc.report_name || doc.filename}
                        </div>
                        <div className="muted-text" style={{ fontSize: 11, marginTop: 2 }}>
                          {doc.lab_name ? `${doc.lab_name} · ` : ""}
                          {doc.test_date ? formatDate(doc.test_date) : formatDate(doc.created_at)}
                        </div>
                      </div>
                      {doc.is_verified ? (
                        <span
                          style={{
                            fontSize: 10,
                            fontWeight: 700,
                            color: "var(--success-text)",
                            background: "var(--success-bg)",
                            padding: "2px 7px",
                            borderRadius: 4,
                            flexShrink: 0,
                          }}
                        >
                          {t("emergencyVerified")}
                        </span>
                      ) : (
                        <span
                          className="muted-text"
                          style={{ fontSize: 10, flexShrink: 0 }}
                        >
                          {t("emergencyUnverified")}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Footer disclaimer */}
      <div
        className="muted-text"
        style={{
          marginTop: 28,
          fontSize: 11,
          lineHeight: 1.65,
          padding: "14px 18px",
          background: "var(--panel-2)",
          borderRadius: 10,
          border: "1px solid var(--border)",
        }}
      >
        {t("emergencyNotADiagnosis")} · {t("emergencyReadOnly")} · {t("emergencyAuditedAccess")}
      </div>

      {/* Return to search */}
      <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-start" }}>
        <button
          type="button"
          className="secondary-btn"
          style={{ fontSize: 13 }}
          onClick={handleReturnToSearch}
        >
          {t("emergencyBackToSearch")}
        </button>
      </div>
    </EmergencyShell>
  );
}
