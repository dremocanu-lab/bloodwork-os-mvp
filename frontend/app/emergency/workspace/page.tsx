"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import LanguageToggle from "@/components/language-toggle";
import ThemeToggle from "@/components/theme-toggle";
import { useLanguage } from "@/lib/i18n";
import {
  emergencyApi,
  getErrorMessage,
  clearEmergencySession,
  getEmergencyUser,
  getActiveTab,
  setActiveTab,
} from "@/lib/emergency-api";

// ── Types ─────────────────────────────────────────────────────────────────────

type TabSession = {
  sessionId: number;
  patientId: number;
  patientName: string;
  bragiCode: string | null;
  expiresAt: string;
  startedAt: string;
  reason: string;
};

type Lab = {
  name: string | null;
  value: string | null;
  unit: string | null;
  flag: string | null;
  reference_range: string | null;
};

type EDoc = {
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
    started_at: string;
    expires_at: string;
    reason: string;
  };
  medications: Medication[];
  documents: EDoc[];
  latest_bloodwork: {
    document_id: number;
    filename: string;
    test_date: string | null;
    lab_name: string | null;
    labs: Lab[];
  } | null;
};

// ── Constants ─────────────────────────────────────────────────────────────────

const MAX_SESSIONS = 8;
const WARNING_SECS = 300;

const SECTION_TYPE_LABELS: Record<string, string> = {
  bloodwork: "Lab panel",
  discharge_summary: "Discharge summary",
  scans: "Imaging report",
  notes: "Clinical note",
  medications: "Medication document",
  hospitalizations: "Hospitalization record",
  procedure: "Procedure report",
  pathology: "Pathology report",
  prescription: "Prescription / medication document",
  other: "Other source record",
};

const ABNORMAL_FLAGS = new Set(["high", "low", "abnormal", "critical", "borderline", "elevated", "h", "l"]);

const REASON_OPTIONS = [
  "Emergency care",
  "Ambulance response",
  "ER triage",
  "Patient unable to provide history",
  "Other",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(secs: number): string {
  const m = Math.floor(Math.max(0, secs) / 60);
  const s = Math.max(0, secs) % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatDate(iso: string | null | undefined): string {
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

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

function isAbnormal(flag: string | null): boolean {
  return !!flag && ABNORMAL_FLAGS.has(flag.toLowerCase());
}

function sectionLabel(section: string): string {
  return SECTION_TYPE_LABELS[section] || "Document";
}

function timerColor(secs: number): "green" | "amber" | "red" {
  if (secs <= 0) return "red";
  if (secs <= WARNING_SECS) return "amber";
  return "green";
}

const COLOR_MAP = {
  green: { dot: "#16a34a", text: "#16a34a", bg: "rgba(22,163,74,0.08)", border: "rgba(22,163,74,0.20)" },
  amber: { dot: "#d97706", text: "#d97706", bg: "rgba(217,119,6,0.08)", border: "rgba(217,119,6,0.22)" },
  red: { dot: "#dc2626", text: "#dc2626", bg: "rgba(220,38,38,0.09)", border: "rgba(220,38,38,0.22)" },
};

// ── Small shared pieces ───────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 900,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: "var(--muted)",
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="soft-card" style={{ padding: "18px 20px", ...style }}>
      {children}
    </div>
  );
}

function EmptyState({ icon, text }: { icon?: string; text: string }) {
  return (
    <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.6, fontStyle: "italic", margin: 0 }}>
      {icon && <span style={{ marginRight: 6 }}>{icon}</span>}
      {text}
    </p>
  );
}

// ── Workspace top bar ─────────────────────────────────────────────────────────

function WorkspaceTopBar({
  user,
  onLogout,
}: {
  user: ReturnType<typeof getEmergencyUser>;
  onLogout: () => void;
}) {
  const { t } = useLanguage();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "9px 20px",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <Link
        href="/emergency"
        style={{ display: "flex", alignItems: "center", gap: 9, textDecoration: "none", color: "inherit" }}
      >
        <BragiLogo height={28} showText={false} />
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: "-0.01em" }}>{t("emergencyWorkspace")}</div>
          <div className="muted-text" style={{ fontSize: 10 }}>Bragi Health</div>
        </div>
      </Link>
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <ThemeToggle compact />
        <LanguageToggle />
        {user && (
          <>
            <span className="muted-text" style={{ fontSize: 12 }}>{user.full_name}</span>
            <button type="button" className="secondary-btn" style={{ fontSize: 12, padding: "4px 10px" }} onClick={onLogout}>
              {t("emergencySignOut")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function WorkspaceStatusBar() {
  const { t } = useLanguage();
  return (
    <div
      style={{
        background: "rgba(220,38,38,0.05)",
        borderBottom: "1px solid rgba(220,38,38,0.13)",
        padding: "5px 20px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexWrap: "wrap",
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: 999, background: "#dc2626", display: "inline-block", flexShrink: 0 }} />
      <span style={{ fontSize: 9, fontWeight: 900, color: "#dc2626", textTransform: "uppercase", letterSpacing: "0.07em" }}>
        {t("emergencyAuditedAccess")}
      </span>
      {[t("emergencyReadOnly"), t("emergencyTimeLimitedAccess"), t("emergencyUseOnlyForEmergency")].map((s) => (
        <span key={s} className="muted-text" style={{ fontSize: 10 }}>· {s}</span>
      ))}
    </div>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabItem({
  session,
  secs,
  isActive,
  onSelect,
  onClose,
}: {
  session: TabSession;
  secs: number;
  isActive: boolean;
  onSelect: () => void;
  onClose: () => void;
}) {
  const { t } = useLanguage();
  const expired = secs <= 0;
  const c = COLOR_MAP[timerColor(secs)];
  const initStr = initials(session.patientName);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 10px",
        minWidth: 160,
        maxWidth: 200,
        flexShrink: 0,
        cursor: "pointer",
        background: isActive ? "var(--panel-2)" : "transparent",
        borderBottom: isActive ? "2px solid var(--primary)" : "2px solid transparent",
        borderRight: "1px solid var(--border)",
        transition: "background 0.15s",
        position: "relative",
      }}
      onClick={onSelect}
    >
      {/* Avatar circle */}
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 999,
          background: expired ? "rgba(220,38,38,0.12)" : "rgba(124,58,237,0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10,
          fontWeight: 800,
          color: expired ? "#dc2626" : "var(--primary)",
          flexShrink: 0,
        }}
      >
        {initStr}
      </div>
      {/* Name + timer */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            color: expired ? "var(--muted)" : "var(--foreground)",
          }}
        >
          {session.patientName.split(" ")[0]}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
          <span style={{ width: 5, height: 5, borderRadius: 999, background: c.dot, flexShrink: 0, display: "inline-block" }} />
          {expired ? (
            <span style={{ fontSize: 10, fontWeight: 700, color: "#dc2626" }}>{t("emergencyTabExpired")}</span>
          ) : (
            <span style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 700, color: c.text }}>{formatTime(secs)}</span>
          )}
        </div>
      </div>
      {/* Close button */}
      <button
        type="button"
        title={t("emergencyCloseTab")}
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--muted)",
          padding: "2px 3px",
          borderRadius: 4,
          lineHeight: 1,
          fontSize: 14,
          flexShrink: 0,
        }}
      >
        ×
      </button>
    </div>
  );
}

function WorkspaceTabBar({
  sessions,
  timers,
  activeId,
  onSelect,
  onClose,
  onAdd,
  maxReached,
}: {
  sessions: TabSession[];
  timers: Record<number, number>;
  activeId: number | null;
  onSelect: (id: number) => void;
  onClose: (id: number) => void;
  onAdd: () => void;
  maxReached: boolean;
}) {
  const { t } = useLanguage();

  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        overflowX: "auto",
        borderBottom: "1px solid var(--border)",
        background: "var(--panel)",
        scrollbarWidth: "none",
      }}
    >
      {sessions.map((s) => (
        <TabItem
          key={s.sessionId}
          session={s}
          secs={timers[s.sessionId] ?? 1800}
          isActive={s.sessionId === activeId}
          onSelect={() => onSelect(s.sessionId)}
          onClose={() => onClose(s.sessionId)}
        />
      ))}
      {/* Add patient button */}
      <button
        type="button"
        onClick={onAdd}
        disabled={maxReached}
        title={maxReached ? t("emergencyMaxPatients") : t("emergencyAddPatient")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "7px 14px",
          background: "none",
          border: "none",
          borderRight: "1px solid var(--border)",
          cursor: maxReached ? "not-allowed" : "pointer",
          color: maxReached ? "var(--muted)" : "var(--primary)",
          fontWeight: 700,
          fontSize: 12,
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
        {t("emergencyAddPatient")}
      </button>
      {/* Session count */}
      <div style={{ display: "flex", alignItems: "center", padding: "0 14px", marginLeft: "auto", flexShrink: 0 }}>
        <span className="muted-text" style={{ fontSize: 10, whiteSpace: "nowrap" }}>
          {sessions.length}/{MAX_SESSIONS} {t("emergencyActivePatients")}
        </span>
      </div>
    </div>
  );
}

// ── Add Patient Modal ─────────────────────────────────────────────────────────

type SearchResult = {
  id: number;
  full_name: string;
  age: string | null;
  sex: string | null;
  bragi_code: string | null;
  masked_identifier: string | null;
};

function AddPatientModal({
  onCreated,
  onClose,
  activePatientIds,
  sessionsCount,
}: {
  onCreated: (s: TabSession) => void;
  onClose: () => void;
  activePatientIds: number[];
  sessionsCount: number;
}) {
  const { t } = useLanguage();
  type SearchType = "code" | "cnp" | "name";
  const [searchType, setSearchType] = useState<SearchType>("code");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState("");
  const [confirm, setConfirm] = useState<SearchResult | null>(null);
  const [reason, setReason] = useState(REASON_OPTIONS[0]);
  const [reasonNote, setReasonNote] = useState("");
  const [starting, setStarting] = useState(false);
  const [startErr, setStartErr] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setTimeout(() => inputRef.current?.focus(), 60); }, []);

  const maxReached = sessionsCount >= MAX_SESSIONS;

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (!q || maxReached) return;
    setSearching(true);
    setSearchErr("");
    setResults([]);
    setSearched(false);
    try {
      const res = await emergencyApi.get("/emergency/search", { params: { type: searchType, q } });
      const data = res.data as SearchResult[];
      setResults(data);
      setSearched(true);
      if (!data.length) setSearchErr(t("emergencyNoResults"));
    } catch (err) {
      setSearchErr(getErrorMessage(err, t("emergencySearchFailed")));
      setSearched(true);
    } finally {
      setSearching(false);
    }
  }

  async function handleStart() {
    if (!confirm || maxReached) return;
    setStarting(true);
    setStartErr("");
    try {
      const res = await emergencyApi.post("/emergency/access-sessions", {
        patient_id: confirm.id,
        reason,
        reason_note: reason === "Other" ? reasonNote || undefined : undefined,
      });
      const d = res.data as {
        id: number; patient_id: number; patient_name: string;
        bragi_code: string | null; expires_at: string; started_at: string;
        reason: string; existing: boolean;
      };
      onCreated({
        sessionId: d.id,
        patientId: d.patient_id,
        patientName: d.patient_name,
        bragiCode: d.bragi_code,
        expiresAt: d.expires_at,
        startedAt: d.started_at,
        reason: d.reason,
      });
    } catch (err) {
      const msg = getErrorMessage(err, t("emergencySessionFailed"));
      setStartErr(msg);
    } finally {
      setStarting(false);
    }
  }

  const placeholders: Record<SearchType, string> = {
    code: t("emergencyCodePlaceholder"),
    cnp: t("emergencyCNPPlaceholder"),
    name: t("emergencyNamePlaceholder"),
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        zIndex: 200, padding: "80px 24px 24px", overflowY: "auto",
      }}
      onClick={(e) => { if (e.target === e.currentTarget && !starting) onClose(); }}
    >
      <div className="soft-card" style={{ maxWidth: 520, width: "100%", padding: "26px 28px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>{t("emergencyAddPatient")}</h2>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 20, lineHeight: 1 }}>×</button>
        </div>

        {maxReached ? (
          <div style={{ padding: "16px", background: "rgba(220,38,38,0.07)", border: "1px solid rgba(220,38,38,0.18)", borderRadius: 8, fontSize: 13, color: "#dc2626" }}>
            {t("emergencyMaxPatients")}
          </div>
        ) : confirm ? (
          /* Confirm step */
          <div>
            <div style={{ marginBottom: 16, padding: "12px 14px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)" }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{confirm.full_name}</div>
              <div className="muted-text" style={{ fontSize: 12, marginTop: 3, display: "flex", gap: 10, flexWrap: "wrap" }}>
                {confirm.age && <span>{confirm.age}</span>}
                {confirm.sex && <span>{confirm.sex}</span>}
                {confirm.bragi_code && <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{confirm.bragi_code}</span>}
              </div>
            </div>

            {activePatientIds.includes(confirm.id) ? (
              <div style={{ marginBottom: 16, padding: "12px 14px", background: "rgba(217,119,6,0.08)", border: "1px solid rgba(217,119,6,0.22)", borderRadius: 8, fontSize: 13, color: "#d97706" }}>
                {t("emergencyPatientAlreadyActive")}
              </div>
            ) : (
              <>
                <div style={{ marginBottom: 14 }}>
                  <label style={{ display: "block", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", marginBottom: 6 }}>
                    {t("emergencyReason")}
                  </label>
                  <select className="text-input" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: "100%", fontSize: 14, padding: "9px 12px" }}>
                    {REASON_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
                {reason === "Other" && (
                  <div style={{ marginBottom: 14 }}>
                    <textarea className="text-input" placeholder="Describe the reason…" value={reasonNote} onChange={(e) => setReasonNote(e.target.value)} style={{ width: "100%", minHeight: 72, fontSize: 13, resize: "vertical" }} />
                  </div>
                )}
                {startErr && <p style={{ color: "var(--danger-text)", fontSize: 12, marginBottom: 12 }}>{startErr}</p>}
                <div style={{ display: "flex", gap: 10 }}>
                  <button type="button" className="primary-btn" style={{ flex: 1, fontSize: 14, padding: "11px" }} onClick={handleStart} disabled={starting}>
                    {starting ? "Starting…" : t("emergencyStartAccess")}
                  </button>
                  <button type="button" className="secondary-btn" style={{ fontSize: 14, padding: "11px 18px" }} onClick={() => setConfirm(null)} disabled={starting}>
                    {t("emergencyCancel")}
                  </button>
                </div>
              </>
            )}

            {activePatientIds.includes(confirm.id) && (
              <button type="button" className="secondary-btn" style={{ marginTop: 10, width: "100%", fontSize: 14, padding: "10px" }} onClick={onClose}>
                {t("emergencyOpenExistingTab")}
              </button>
            )}

            {!activePatientIds.includes(confirm.id) && (
              <p className="muted-text" style={{ fontSize: 11, marginTop: 14, textAlign: "center" }}>
                {t("emergencyAccessNote")}
              </p>
            )}
          </div>
        ) : (
          /* Search step */
          <>
            <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
              {(["code", "cnp", "name"] as SearchType[]).map((k) => (
                <button key={k} type="button"
                  className={searchType === k ? "primary-btn" : "secondary-btn"}
                  style={{ fontSize: 12, padding: "6px 14px" }}
                  onClick={() => { setSearchType(k); setResults([]); setSearched(false); setSearchErr(""); setQuery(""); }}>
                  {k === "code" ? t("emergencySearchByCode") : k === "cnp" ? t("emergencySearchByCNP") : t("emergencySearchByName")}
                </button>
              ))}
            </div>
            <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              <input ref={inputRef} type="text" className="text-input" placeholder={placeholders[searchType]}
                value={query} onChange={(e) => setQuery(e.target.value)}
                autoComplete="off" spellCheck={false}
                style={{ flex: 1, fontSize: 15, padding: "10px 13px" }} />
              <button type="submit" className="primary-btn" disabled={searching || !query.trim()} style={{ padding: "10px 20px", fontSize: 14 }}>
                {searching ? "…" : t("emergencySearch")}
              </button>
            </form>
            {searchErr && searched && <p className="muted-text" style={{ fontSize: 13, marginBottom: 10 }}>{searchErr}</p>}
            {results.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {results.map((r) => {
                  const alreadyActive = activePatientIds.includes(r.id);
                  return (
                    <div key={r.id} style={{ padding: "12px 14px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 14 }}>{r.full_name}</div>
                        <div className="muted-text" style={{ fontSize: 12, marginTop: 2, display: "flex", gap: 10, flexWrap: "wrap" }}>
                          {r.age && <span>{r.age}</span>}
                          {r.sex && <span>{r.sex}</span>}
                          {r.bragi_code && <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{r.bragi_code}</span>}
                          {r.masked_identifier && <span>ID: {r.masked_identifier}</span>}
                        </div>
                      </div>
                      <button type="button"
                        className={alreadyActive ? "secondary-btn" : "primary-btn"}
                        style={{ fontSize: 12, whiteSpace: "nowrap", flexShrink: 0, padding: "6px 12px" }}
                        onClick={() => setConfirm(r)}>
                        {alreadyActive ? t("emergencyOpenExistingTab") : t("emergencySelectPatient")}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Patient profile sections ───────────────────────────────────────────────────

function IdentitySection({ data, session }: { data: PatientData; session: TabSession }) {
  const { t } = useLanguage();
  const p = data.patient;
  return (
    <Card>
      <SectionLabel>{t("emergencyIdentity")}</SectionLabel>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 26, fontWeight: 900, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{p.full_name}</div>
          <div className="muted-text" style={{ fontSize: 13, marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap" }}>
            {p.date_of_birth && <span>DOB: {formatDate(p.date_of_birth)}</span>}
            {p.age && <span>Age: {p.age}</span>}
            {p.sex && <span>Sex: {p.sex}</span>}
          </div>
          <div className="muted-text" style={{ fontSize: 11, marginTop: 10, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <span>{t("emergencyStartedAt")}: {formatDateTime(session.startedAt)}</span>
            <span>{t("emergencyExpiresAtLabel")}: {formatDateTime(session.expiresAt)}</span>
          </div>
          <div className="muted-text" style={{ fontSize: 11, marginTop: 4 }}>
            Reason: {session.reason}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          {p.bragi_code && (
            <div style={{ padding: "5px 12px", background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8, fontFamily: "monospace", fontSize: 13, fontWeight: 700, letterSpacing: "0.05em" }}>
              {p.bragi_code}
            </div>
          )}
          <div style={{ padding: "3px 9px", background: "rgba(220,38,38,0.08)", border: "1px solid rgba(220,38,38,0.18)", borderRadius: 5, fontSize: 9, fontWeight: 800, color: "#dc2626", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {t("emergencyReadOnly")}
          </div>
          <div style={{ padding: "3px 9px", background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 5, fontSize: 9, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {t("emergencySourceLinkedRecords")}
          </div>
        </div>
      </div>
    </Card>
  );
}

function AllergiesSection() {
  const { t } = useLanguage();
  return (
    <Card>
      <SectionLabel>{t("emergencyAllergies")}</SectionLabel>
      <EmptyState text={t("emergencyNoAllergies")} />
    </Card>
  );
}

function ContactsSection() {
  const { t } = useLanguage();
  return (
    <Card>
      <SectionLabel>{t("emergencyEmergencyContacts")}</SectionLabel>
      <EmptyState text={t("emergencyNoContacts")} />
    </Card>
  );
}

function MedicationsSection({ medications }: { medications: Medication[] }) {
  const { t } = useLanguage();
  const active = medications.filter((m) => m.status === "active");
  const other = medications.filter((m) => m.status !== "active");

  return (
    <Card>
      <SectionLabel>{t("emergencyMedications")}</SectionLabel>
      {medications.length === 0 ? (
        <EmptyState text={t("emergencyNoMedications")} />
      ) : (
        <>
          {active.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: other.length ? 10 : 0 }}>
              {active.map((m) => (
                <div key={m.id} style={{ padding: "9px 11px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)" }}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{m.name}</div>
                  <div className="muted-text" style={{ fontSize: 12, marginTop: 2 }}>
                    {[m.dose_strength, m.frequency, m.route_form].filter(Boolean).join(" · ") || "—"}
                  </div>
                  {m.is_uncertain && (
                    <div style={{ marginTop: 4, fontSize: 10, fontWeight: 700, color: "#d97706", textTransform: "uppercase" }}>
                      {t("emergencySourceRequiresVerification")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {other.length > 0 && (
            <details>
              <summary className="muted-text" style={{ fontSize: 12, cursor: "pointer", marginBottom: 6 }}>
                {other.length} stopped/other medication{other.length !== 1 ? "s" : ""}
              </summary>
              <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 6 }}>
                {other.map((m) => (
                  <div key={m.id} style={{ padding: "7px 10px", background: "var(--panel-2)", borderRadius: 7, opacity: 0.65 }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{m.name}</div>
                    <div className="muted-text" style={{ fontSize: 11 }}>{m.status}</div>
                  </div>
                ))}
              </div>
            </details>
          )}
          <p className="muted-text" style={{ fontSize: 11, marginTop: 8 }}>
            {t("emergencyPatientEntered")} · {t("emergencyReviewWithPatient")}
          </p>
        </>
      )}
    </Card>
  );
}

function LatestLabsSection({ bloodwork }: { bloodwork: PatientData["latest_bloodwork"] }) {
  const { t } = useLanguage();
  if (!bloodwork) {
    return (
      <Card>
        <SectionLabel>{t("emergencyLatestBloodwork")}</SectionLabel>
        <EmptyState text={t("emergencyNoLabs")} />
      </Card>
    );
  }
  return (
    <Card>
      <SectionLabel>{t("emergencyLatestBloodwork")}</SectionLabel>
      <div className="muted-text" style={{ fontSize: 12, marginBottom: 10 }}>
        {bloodwork.lab_name && <span>{bloodwork.lab_name} · </span>}
        {bloodwork.test_date ? formatDate(bloodwork.test_date) : "Date unknown"}
      </div>
      {bloodwork.labs.length === 0 ? (
        <EmptyState text="No lab values extracted from this document." />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "6px 10px", maxHeight: 340, overflowY: "auto" }}>
          {bloodwork.labs.map((lab, i) => {
            const abnormal = isAbnormal(lab.flag);
            return (
              <div key={i} style={{ padding: "6px 8px", borderRadius: 6, background: abnormal ? "rgba(220,38,38,0.07)" : "var(--panel-2)", border: `1px solid ${abnormal ? "rgba(220,38,38,0.18)" : "var(--border)"}` }}>
                <div className="muted-text" style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", marginBottom: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {lab.name || "—"}
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: abnormal ? "var(--danger-text)" : "var(--foreground)" }}>
                  {lab.value || "—"}{lab.unit ? ` ${lab.unit}` : ""}
                </div>
                {lab.reference_range && (
                  <div className="muted-text" style={{ fontSize: 9, marginTop: 1 }}>ref: {lab.reference_range}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="muted-text" style={{ fontSize: 10, marginTop: 8 }}>
        {t("emergencyOutOfRange")} · {t("emergencyRefRange")} · {t("emergencyNotADiagnosis")}
      </p>
    </Card>
  );
}

function DocListSection({
  title,
  docs,
  emptyText,
  collapsed,
}: {
  title: string;
  docs: EDoc[];
  emptyText: string;
  collapsed?: boolean;
}) {
  const { t } = useLanguage();
  const inner = docs.length === 0 ? (
    <EmptyState text={emptyText} />
  ) : (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {docs.map((doc) => (
        <div key={doc.id} style={{ padding: "9px 12px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {doc.report_name || doc.filename}
            </div>
            <div className="muted-text" style={{ fontSize: 11, marginTop: 2 }}>
              {sectionLabel(doc.section)}{doc.lab_name ? ` · ${doc.lab_name}` : ""} · {doc.test_date ? formatDate(doc.test_date) : formatDate(doc.created_at)}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
            {doc.is_verified ? (
              <span style={{ fontSize: 9, fontWeight: 700, color: "var(--success-text, #16a34a)", background: "rgba(22,163,74,0.08)", padding: "2px 7px", borderRadius: 4, textTransform: "uppercase" }}>
                {t("emergencyVerified")}
              </span>
            ) : (
              <span className="muted-text" style={{ fontSize: 9 }}>{t("emergencyUnverified")}</span>
            )}
            <Link
              href={`/documents/${doc.id}`}
              target="_blank"
              style={{ fontSize: 11, color: "var(--primary)", fontWeight: 600, textDecoration: "none", padding: "3px 8px", border: "1px solid var(--primary)", borderRadius: 5, whiteSpace: "nowrap" }}
            >
              {t("emergencyOpenStructured")}
            </Link>
          </div>
        </div>
      ))}
    </div>
  );

  if (collapsed) {
    return (
      <details>
        <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 700, padding: "10px 0", display: "flex", alignItems: "center", gap: 8, userSelect: "none" }}>
          {title}
          {docs.length > 0 && (
            <span style={{ fontSize: 10, fontWeight: 700, background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 999, padding: "1px 7px", color: "var(--muted)" }}>
              {docs.length}
            </span>
          )}
        </summary>
        <div style={{ paddingTop: 10 }}>{inner}</div>
      </details>
    );
  }

  return (
    <Card>
      <SectionLabel>{title}</SectionLabel>
      {inner}
    </Card>
  );
}

function RecentDocsSection({ documents }: { documents: EDoc[] }) {
  const { t } = useLanguage();
  const recent = documents.slice(0, 8);
  return (
    <Card>
      <SectionLabel>{t("emergencyRecentDocuments")}</SectionLabel>
      {recent.length === 0 ? (
        <EmptyState text={t("emergencyNoDocuments")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {recent.map((doc) => (
            <div key={doc.id} style={{ padding: "9px 12px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {doc.report_name || doc.filename}
                </div>
                <div className="muted-text" style={{ fontSize: 11, marginTop: 2 }}>
                  {sectionLabel(doc.section)}{doc.lab_name ? ` · ${doc.lab_name}` : ""} · {doc.test_date ? formatDate(doc.test_date) : formatDate(doc.created_at)}
                </div>
              </div>
              <Link href={`/documents/${doc.id}`} target="_blank"
                style={{ fontSize: 11, color: "var(--primary)", fontWeight: 600, textDecoration: "none", padding: "3px 8px", border: "1px solid var(--primary)", borderRadius: 5, whiteSpace: "nowrap", flexShrink: 0 }}>
                {t("emergencyOpenStructured")}
              </Link>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

type LibFilter = "all" | "bloodwork" | "discharge_summary" | "scans" | "notes" | "other";

function DocumentLibrarySection({ documents }: { documents: EDoc[] }) {
  const { t } = useLanguage();
  const [filter, setFilter] = useState<LibFilter>("all");
  const [search, setSearch] = useState("");

  const filtered = documents.filter((d) => {
    if (filter === "bloodwork" && d.section !== "bloodwork") return false;
    if (filter === "discharge_summary" && d.section !== "discharge_summary") return false;
    if (filter === "scans" && d.section !== "scans") return false;
    if (filter === "notes" && d.section !== "notes") return false;
    if (filter === "other" && ["bloodwork", "discharge_summary", "scans", "notes"].includes(d.section)) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      if (!(d.report_name || d.filename || "").toLowerCase().includes(q) &&
        !sectionLabel(d.section).toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const filterTabs: { key: LibFilter; label: string }[] = [
    { key: "all", label: t("emergencyDocAll") },
    { key: "bloodwork", label: t("emergencyDocLabs") },
    { key: "discharge_summary", label: t("emergencyDocDischarge") },
    { key: "scans", label: t("emergencyDocImaging") },
    { key: "notes", label: t("emergencyDocNotes") },
    { key: "other", label: t("emergencyDocOther") },
  ];

  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 700, padding: "10px 0", userSelect: "none", display: "flex", alignItems: "center", gap: 8 }}>
        {t("emergencyDocumentLibrary")}
        <span style={{ fontSize: 10, fontWeight: 700, background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 999, padding: "1px 7px", color: "var(--muted)" }}>
          {documents.length}
        </span>
      </summary>
      <div style={{ paddingTop: 12 }}>
        {/* Filter tabs */}
        <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          {filterTabs.map(({ key, label }) => (
            <button key={key} type="button"
              className={filter === key ? "primary-btn" : "secondary-btn"}
              style={{ fontSize: 11, padding: "5px 12px" }}
              onClick={() => setFilter(key)}>
              {label}
            </button>
          ))}
        </div>
        {/* Search */}
        <input type="text" className="text-input" placeholder="Search documents…" value={search}
          onChange={(e) => setSearch(e.target.value)} style={{ width: "100%", fontSize: 13, padding: "8px 12px", marginBottom: 12 }} />
        {/* List */}
        {filtered.length === 0 ? (
          <EmptyState text="No documents match the current filter." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {filtered.map((doc) => (
              <div key={doc.id} style={{ padding: "8px 12px", background: "var(--panel-2)", borderRadius: 8, border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {doc.report_name || doc.filename}
                  </div>
                  <div className="muted-text" style={{ fontSize: 11, marginTop: 1 }}>
                    {sectionLabel(doc.section)} · {doc.test_date ? formatDate(doc.test_date) : formatDate(doc.created_at)}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 5, flexShrink: 0, alignItems: "center" }}>
                  {doc.is_verified
                    ? <span style={{ fontSize: 9, fontWeight: 700, color: "var(--success-text, #16a34a)", background: "rgba(22,163,74,0.08)", padding: "1px 6px", borderRadius: 4, textTransform: "uppercase" }}>{t("emergencyVerified")}</span>
                    : <span className="muted-text" style={{ fontSize: 9 }}>{t("emergencyUnverified")}</span>}
                  <Link href={`/documents/${doc.id}`} target="_blank"
                    style={{ fontSize: 11, color: "var(--primary)", fontWeight: 600, textDecoration: "none", padding: "3px 8px", border: "1px solid var(--primary)", borderRadius: 5, whiteSpace: "nowrap" }}>
                    {t("emergencyOpenSource")}
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}

// ── Full patient profile ───────────────────────────────────────────────────────

function EmergencyPatientProfile({ session, data }: { session: TabSession; data: PatientData }) {
  const { t } = useLanguage();
  const docs = data.documents;
  const dischargeDocs = docs.filter((d) => d.section === "discharge_summary");
  const imagingDocs = docs.filter((d) => d.section === "scans");
  const notesDocs = docs.filter((d) => d.section === "notes");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <IdentitySection data={data} session={session} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
        <AllergiesSection />
        <ContactsSection />
      </div>
      <MedicationsSection medications={data.medications} />
      <LatestLabsSection bloodwork={data.latest_bloodwork} />
      <RecentDocsSection documents={docs} />

      {/* Collapsible lower sections */}
      <div className="soft-card" style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 0 }}>
        <div style={{ paddingBottom: 10, borderBottom: "1px solid var(--border)", marginBottom: 10 }}>
          <DocListSection title={t("emergencyDischargeSummaries")} docs={dischargeDocs} emptyText={t("emergencyNoDischarge")} collapsed />
        </div>
        <div style={{ paddingBottom: 10, borderBottom: "1px solid var(--border)", marginBottom: 10 }}>
          <DocListSection title={t("emergencyImagingReports")} docs={imagingDocs} emptyText={t("emergencyNoImaging")} collapsed />
        </div>
        <div style={{ paddingBottom: 10, borderBottom: "1px solid var(--border)", marginBottom: 10 }}>
          <DocListSection title={t("emergencyClinicalNotes")} docs={notesDocs} emptyText={t("emergencyNoClinicalNotes")} collapsed />
        </div>
        <DocumentLibrarySection documents={docs} />
      </div>

      <p className="muted-text" style={{ fontSize: 11, textAlign: "center", paddingBottom: 20 }}>
        {t("emergencyNotADiagnosis")} · {t("emergencyReadOnly")} · {t("emergencyAuditedAccess")}
      </p>
    </div>
  );
}

// ── Workspace states ───────────────────────────────────────────────────────────

function EmptyWorkspaceState({ onAdd }: { onAdd: () => void }) {
  const { t } = useLanguage();
  return (
    <div style={{ textAlign: "center", padding: "80px 24px" }}>
      <div style={{ fontSize: 48, marginBottom: 20 }}>🔒</div>
      <h2 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 10px" }}>{t("emergencyNoActiveSessions")}</h2>
      <p className="muted-text" style={{ fontSize: 14, lineHeight: 1.6, maxWidth: 360, margin: "0 auto 28px" }}>
        {t("emergencyStartFirstSession")}
      </p>
      <button type="button" className="primary-btn" style={{ fontSize: 15, padding: "13px 36px" }} onClick={onAdd}>
        {t("emergencyAddPatient")}
      </button>
    </div>
  );
}

function ExpiredTabState({
  session,
  onClose,
  onReturnToSearch,
  onNewSession,
}: {
  session: TabSession;
  onClose: () => void;
  onReturnToSearch: () => void;
  onNewSession: () => void;
}) {
  const { t } = useLanguage();
  return (
    <div style={{ textAlign: "center", padding: "60px 24px" }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
      <h2 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 10px" }}>{t("emergencyExpired")}</h2>
      <p className="muted-text" style={{ fontSize: 14, lineHeight: 1.6, marginBottom: 10 }}>
        {t("emergencyExpiredBody")}
      </p>
      <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 28 }}>{session.patientName}</p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        <button type="button" className="primary-btn" onClick={onNewSession}>{t("emergencyNewSession")}</button>
        <button type="button" className="secondary-btn" onClick={onReturnToSearch}>{t("emergencyReturnToSearch")}</button>
        <button type="button" className="secondary-btn" onClick={onClose}>{t("emergencyCloseTab")}</button>
      </div>
    </div>
  );
}

// ── Main workspace ─────────────────────────────────────────────────────────────

function WorkspacePage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [user, setUser] = useState<ReturnType<typeof getEmergencyUser>>(null);
  const [sessions, setSessions] = useState<TabSession[]>([]);
  const [activeId, setActiveIdState] = useState<number | null>(null);
  const [timers, setTimers] = useState<Record<number, number>>({});
  const [patientCache, setPatientCache] = useState<Record<number, PatientData | null>>({});
  const [loadingCache, setLoadingCache] = useState<Record<number, boolean>>({});
  const [loadingInit, setLoadingInit] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function setActiveId(id: number | null) {
    setActiveIdState(id);
    setActiveTab(id);
  }

  // Timer — single interval for all sessions
  const sessionsRef = useRef<TabSession[]>([]);
  sessionsRef.current = sessions;

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const next: Record<number, number> = {};
      sessionsRef.current.forEach((s) => {
        next[s.sessionId] = Math.max(0, Math.floor((new Date(s.expiresAt).getTime() - now) / 1000));
      });
      setTimers(next);
    };
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // Auth + load active sessions
  useEffect(() => {
    const u = getEmergencyUser();
    if (!u || (u.role !== "emergency_worker" && u.role !== "admin")) {
      router.replace("/emergency/login");
      return;
    }
    setUser(u);

    emergencyApi
      .get("/emergency/access-sessions/active")
      .then((res) => {
        const data = res.data as {
          id: number; patient_id: number; patient_name: string;
          bragi_code: string | null; expires_at: string; started_at: string;
          seconds_remaining: number; reason: string;
        }[];

        const tabs: TabSession[] = data.map((s) => ({
          sessionId: s.id,
          patientId: s.patient_id,
          patientName: s.patient_name,
          bragiCode: s.bragi_code,
          expiresAt: s.expires_at,
          startedAt: s.started_at,
          reason: s.reason,
        }));
        setSessions(tabs);

        // Pre-select from URL ?tab= param, then localStorage, then first
        const tabParam = searchParams.get("tab");
        const storedTab = getActiveTab();
        let selected: number | null = null;
        if (tabParam && tabs.find((t) => t.sessionId === Number(tabParam))) {
          selected = Number(tabParam);
        } else if (storedTab && tabs.find((t) => t.sessionId === storedTab)) {
          selected = storedTab;
        } else {
          selected = tabs[0]?.sessionId ?? null;
        }
        setActiveId(selected);
      })
      .catch(() => {})
      .finally(() => setLoadingInit(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  // Load patient data when active tab changes
  const loadPatientData = useCallback(
    (sessionId: number) => {
      if (patientCache[sessionId] !== undefined) return;
      const session = sessionsRef.current.find((s) => s.sessionId === sessionId);
      if (!session) return;
      setLoadingCache((prev) => ({ ...prev, [sessionId]: true }));
      emergencyApi
        .get(`/emergency/patients/${session.patientId}`, { params: { session_id: sessionId } })
        .then((res) => setPatientCache((prev) => ({ ...prev, [sessionId]: res.data as PatientData })))
        .catch(() => setPatientCache((prev) => ({ ...prev, [sessionId]: null })))
        .finally(() => setLoadingCache((prev) => ({ ...prev, [sessionId]: false })));
    },
    [patientCache]
  );

  useEffect(() => {
    if (activeId != null) loadPatientData(activeId);
  }, [activeId, loadPatientData]);

  function handleCloseTab(sessionId: number) {
    emergencyApi.post(`/emergency/access-sessions/${sessionId}/close`).catch(() => {});
    setSessions((prev) => prev.filter((s) => s.sessionId !== sessionId));
    setPatientCache((prev) => { const n = { ...prev }; delete n[sessionId]; return n; });
    if (activeId === sessionId) {
      const remaining = sessionsRef.current.filter((s) => s.sessionId !== sessionId);
      setActiveId(remaining[0]?.sessionId ?? null);
    }
  }

  function handleSessionCreated(newTab: TabSession) {
    setSessions((prev) => {
      if (prev.find((s) => s.sessionId === newTab.sessionId)) return prev;
      return [...prev, newTab];
    });
    setActiveId(newTab.sessionId);
    setShowAddModal(false);
  }

  function handleLogout() {
    clearEmergencySession();
    router.push("/emergency/login");
  }

  const activeSession = sessions.find((s) => s.sessionId === activeId) ?? null;
  const activeData = activeId != null ? patientCache[activeId] : undefined;
  const isLoadingData = activeId != null ? (loadingCache[activeId] ?? false) : false;
  const activeSecondsLeft = activeId != null ? (timers[activeId] ?? 1800) : 0;
  const isExpired = activeId != null && activeSecondsLeft === 0;

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--app-bg)" }}>
      {/* Sticky combined header */}
      <div style={{ position: "sticky", top: 0, zIndex: 40, background: "var(--panel)" }}>
        <WorkspaceTopBar user={user} onLogout={handleLogout} />
        <WorkspaceStatusBar />
        {!loadingInit && (
          <WorkspaceTabBar
            sessions={sessions}
            timers={timers}
            activeId={activeId}
            onSelect={(id) => setActiveId(id)}
            onClose={handleCloseTab}
            onAdd={() => setShowAddModal(true)}
            maxReached={sessions.length >= MAX_SESSIONS}
          />
        )}
      </div>

      {/* Content */}
      <div style={{ flex: 1, maxWidth: 960, margin: "0 auto", width: "100%", padding: "28px 22px 60px" }}>
        {loadingInit ? (
          <p className="muted-text" style={{ fontSize: 14 }}>Loading sessions…</p>
        ) : sessions.length === 0 ? (
          <EmptyWorkspaceState onAdd={() => setShowAddModal(true)} />
        ) : !activeSession ? (
          <p className="muted-text" style={{ fontSize: 14, textAlign: "center", padding: "60px 0" }}>
            Select a patient tab above.
          </p>
        ) : isExpired ? (
          <ExpiredTabState
            session={activeSession}
            onClose={() => handleCloseTab(activeSession.sessionId)}
            onReturnToSearch={() => router.push("/emergency/search")}
            onNewSession={() => { handleCloseTab(activeSession.sessionId); setShowAddModal(true); }}
          />
        ) : isLoadingData ? (
          <p className="muted-text" style={{ fontSize: 14 }}>Loading patient data…</p>
        ) : activeData == null ? (
          <div className="soft-card" style={{ padding: "28px 24px", textAlign: "center" }}>
            <p style={{ color: "var(--danger-text)", fontSize: 14 }}>Could not load patient data. The session may have expired.</p>
            <button type="button" className="secondary-btn" style={{ marginTop: 16 }} onClick={() => handleCloseTab(activeSession.sessionId)}>
              Close tab
            </button>
          </div>
        ) : (
          <EmergencyPatientProfile session={activeSession} data={activeData} />
        )}
      </div>

      {showAddModal && (
        <AddPatientModal
          onCreated={handleSessionCreated}
          onClose={() => setShowAddModal(false)}
          activePatientIds={sessions.map((s) => s.patientId)}
          sessionsCount={sessions.length}
        />
      )}
    </div>
  );
}

// Suspense wrapper required for useSearchParams in Next.js App Router
export default function EmergencyWorkspacePage() {
  return (
    <Suspense fallback={null}>
      <WorkspacePage />
    </Suspense>
  );
}
