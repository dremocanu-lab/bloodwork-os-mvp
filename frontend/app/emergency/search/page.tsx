"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import EmergencyShell from "@/components/emergency-shell";
import { useLanguage } from "@/lib/i18n";
import {
  emergencyApi,
  getErrorMessage,
  EMERGENCY_STORAGE_KEYS,
  clearEmergencySession,
  getEmergencyUser,
} from "@/lib/emergency-api";

type SearchType = "code" | "cnp" | "name";

type SearchResult = {
  id: number;
  full_name: string;
  age: string | null;
  sex: string | null;
  bragi_code: string | null;
  masked_identifier: string | null;
};

type ConfirmState = {
  patientId: number;
  patientName: string;
};

const REASON_OPTIONS = [
  "Emergency care",
  "Ambulance response",
  "ER triage",
  "Patient unable to provide history",
  "Other",
];

export default function EmergencySearchPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [user, setUser] = useState<ReturnType<typeof getEmergencyUser>>(null);
  const [searchType, setSearchType] = useState<SearchType>("code");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [reason, setReason] = useState(REASON_OPTIONS[0]);
  const [reasonNote, setReasonNote] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const u = getEmergencyUser();
    if (!u || (u.role !== "emergency_worker" && u.role !== "admin")) {
      router.replace("/emergency/login");
      return;
    }
    setUser(u);
    // Clear any previous session state
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.sessionId);
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.expiresAt);
    localStorage.removeItem(EMERGENCY_STORAGE_KEYS.patientId);
    inputRef.current?.focus();
  }, [router]);

  function handleLogout() {
    clearEmergencySession();
    router.push("/emergency/login");
  }

  function handleTypeChange(type: SearchType) {
    setSearchType(type);
    setResults([]);
    setSearched(false);
    setSearchError("");
    setQuery("");
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchError("");
    setResults([]);
    setSearched(false);
    try {
      const res = await emergencyApi.get("/emergency/search", {
        params: { type: searchType, q },
      });
      const data = res.data as SearchResult[];
      setResults(data);
      setSearched(true);
      if (!data.length) setSearchError(t("emergencyNoResults"));
    } catch (err) {
      setSearchError(getErrorMessage(err, t("emergencySearchFailed")));
      setSearched(true);
    } finally {
      setSearching(false);
    }
  }

  async function handleStartSession() {
    if (!confirm) return;
    setStarting(true);
    setStartError("");
    try {
      const res = await emergencyApi.post("/emergency/access-sessions", {
        patient_id: confirm.patientId,
        reason,
        reason_note: reason === "Other" ? reasonNote || undefined : undefined,
      });
      const session = res.data as { id: number; patient_id: number; expires_at: string };
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.sessionId, String(session.id));
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.expiresAt, session.expires_at);
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.patientId, String(session.patient_id));
      router.push(`/emergency/patients/${session.patient_id}`);
    } catch (err) {
      setStartError(getErrorMessage(err, t("emergencySessionFailed")));
    } finally {
      setStarting(false);
    }
  }

  const searchTypeTabs: { key: SearchType; label: string }[] = [
    { key: "code", label: t("emergencySearchByCode") },
    { key: "cnp", label: t("emergencySearchByCNP") },
    { key: "name", label: t("emergencySearchByName") },
  ];

  const placeholders: Record<SearchType, string> = {
    code: t("emergencyCodePlaceholder"),
    cnp: t("emergencyCNPPlaceholder"),
    name: t("emergencyNamePlaceholder"),
  };

  return (
    <EmergencyShell user={user} onLogout={handleLogout}>
      <div style={{ maxWidth: 680, margin: "0 auto" }}>
        {/* Page heading */}
        <div style={{ marginBottom: 28 }}>
          <h1
            style={{
              fontSize: 26,
              fontWeight: 900,
              letterSpacing: "-0.025em",
              margin: "0 0 8px 0",
            }}
          >
            {t("emergencySearchPatient")}
          </h1>
          <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.55 }}>
            {t("emergencySearchSubtitle")}
          </p>
        </div>

        {/* Search type tabs */}
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          {searchTypeTabs.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={searchType === key ? "primary-btn" : "secondary-btn"}
              style={{ fontSize: 13, padding: "7px 16px" }}
              onClick={() => handleTypeChange(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Search form */}
        <form onSubmit={handleSearch} style={{ display: "flex", gap: 10, marginBottom: 28 }}>
          <input
            ref={inputRef}
            type="text"
            className="text-input"
            placeholder={placeholders[searchType]}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            style={{ flex: 1, fontSize: 16, padding: "13px 16px" }}
          />
          <button
            type="submit"
            className="primary-btn"
            disabled={searching || !query.trim()}
            style={{ padding: "13px 26px", fontSize: 14, whiteSpace: "nowrap" }}
          >
            {searching ? "…" : t("emergencySearch")}
          </button>
        </form>

        {/* Search error / no results */}
        {searchError && searched && (
          <p className="muted-text" style={{ fontSize: 13, marginBottom: 16 }}>
            {searchError}
          </p>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {results.map((r) => (
              <div
                key={r.id}
                className="soft-card"
                style={{
                  padding: "16px 20px",
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>{r.full_name}</div>
                  <div
                    className="muted-text"
                    style={{ fontSize: 13, marginTop: 4, display: "flex", gap: 12, flexWrap: "wrap" }}
                  >
                    {r.age && <span>{r.age}</span>}
                    {r.sex && <span>{r.sex}</span>}
                    {r.bragi_code && (
                      <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{r.bragi_code}</span>
                    )}
                    {r.masked_identifier && <span>ID: {r.masked_identifier}</span>}
                  </div>
                </div>
                <button
                  type="button"
                  className="primary-btn"
                  style={{ fontSize: 13, whiteSpace: "nowrap", flexShrink: 0 }}
                  onClick={() =>
                    setConfirm({ patientId: r.id, patientName: r.full_name })
                  }
                >
                  {t("emergencySelectPatient")}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Confirm session modal */}
      {confirm && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 200,
            padding: 24,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget && !starting) setConfirm(null);
          }}
        >
          <div
            className="soft-card"
            style={{ maxWidth: 440, width: "100%", padding: "28px 28px" }}
          >
            <h2 style={{ fontSize: 18, fontWeight: 800, margin: "0 0 10px 0" }}>
              {t("emergencyStartSession")}
            </h2>
            <p className="muted-text" style={{ fontSize: 13, marginBottom: 22, lineHeight: 1.6 }}>
              {t("emergencyStartSessionBody").replace("{name}", confirm.patientName)}
            </p>

            {/* Reason selector */}
            <div style={{ marginBottom: 14 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--muted)",
                  marginBottom: 6,
                }}
              >
                {t("emergencyReason")}
              </label>
              <select
                className="text-input"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={{ width: "100%", fontSize: 14, padding: "10px 12px" }}
              >
                {REASON_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>

            {reason === "Other" && (
              <div style={{ marginBottom: 14 }}>
                <textarea
                  className="text-input"
                  placeholder="Please describe the reason for emergency access…"
                  value={reasonNote}
                  onChange={(e) => setReasonNote(e.target.value)}
                  style={{ width: "100%", minHeight: 80, fontSize: 13, resize: "vertical" }}
                />
              </div>
            )}

            {startError && (
              <p style={{ color: "var(--danger-text)", fontSize: 12, marginBottom: 12 }}>
                {startError}
              </p>
            )}

            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                className="primary-btn"
                style={{ flex: 1, fontSize: 14, padding: "11px" }}
                onClick={handleStartSession}
                disabled={starting}
              >
                {starting ? "Starting…" : t("emergencyStartAccess")}
              </button>
              <button
                type="button"
                className="secondary-btn"
                style={{ fontSize: 14, padding: "11px 18px" }}
                onClick={() => setConfirm(null)}
                disabled={starting}
              >
                {t("emergencyCancel")}
              </button>
            </div>

            <p className="muted-text" style={{ fontSize: 11, marginTop: 16, textAlign: "center" }}>
              {t("emergencyAccessNote")}
            </p>
          </div>
        </div>
      )}
    </EmergencyShell>
  );
}
