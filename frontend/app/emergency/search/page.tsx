"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import EmergencyShell from "@/components/emergency-shell";
import { useLanguage } from "@/lib/i18n";
import {
  Dialog,
  EmptyState,
  ErrorNote,
  SectionHead,
  TableSkeleton,
} from "@/components/ui";
import { IconAlert, IconSearch } from "@/components/ui/icon";
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
      // POST with a JSON body — a CNP lookup must never travel in a URL
      // query string (browser history / server access logs / proxy
      // logging). Used for every search type, not just CNP, so there's
      // one code path instead of a CNP-only special case.
      const res = await emergencyApi.post("/emergency/search", {
        type: searchType,
        q,
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
      router.push(`/emergency/workspace?tab=${session.id}`);
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
      <div style={{ maxWidth: 660, margin: "0 auto", minWidth: 0 }}>
        <header style={{ marginBottom: "var(--s5)" }}>
          <h1 className="app-shell-title" style={{ fontSize: "var(--fs-display)" }}>
            {t("emergencySearchPatient")}
          </h1>
          <p className="app-shell-subtitle">{t("emergencySearchSubtitle")}</p>
        </header>

        {/* Identity field selector: a segmented control, because these are
            three mutually exclusive ways to search the same thing. */}
        <form onSubmit={handleSearch} className="b-stack-tight" style={{ marginBottom: "var(--s5)" }}>
          <div className="b-segmented" role="group" aria-label={t("emergencySearchPatient")}>
            {searchTypeTabs.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                aria-pressed={searchType === key}
                onClick={() => handleTypeChange(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div style={{ display: "flex", gap: "var(--s2)", minWidth: 0 }}>
            <div className="b-search" style={{ flex: 1, minWidth: 0 }}>
              <IconSearch size={14} className="b-search-icon" />
              <input
                ref={inputRef}
                type="search"
                className="b-input"
                placeholder={placeholders[searchType]}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                aria-label={placeholders[searchType]}
                /* 16px prevents iOS zooming the viewport on focus. */
                style={{ fontSize: 16 }}
              />
            </div>
            <button
              type="submit"
              className="b-btn b-btn-primary b-btn-lg"
              disabled={searching || !query.trim()}
              style={{ flexShrink: 0 }}
            >
              {searching ? <span className="b-spinner" /> : null}
              {t("emergencySearch")}
            </button>
          </div>
        </form>

        {searching ? (
          <section className="b-surface">
            <TableSkeleton rows={3} columns={2} />
          </section>
        ) : searchError && searched ? (
          <section className="b-surface">
            <EmptyState
              icon={<IconSearch size={17} />}
              title={searchError}
              description="Check the identifier and try another field."
            />
          </section>
        ) : results.length > 0 ? (
          <section className="b-surface">
            <SectionHead title={t("navResults")} count={results.length} />
            <div className="b-list">
              {results.map((result) => (
                <button
                  key={result.id}
                  type="button"
                  className="b-list-row"
                  onClick={() => setConfirm({ patientId: result.id, patientName: result.full_name })}
                >
                  <span className="b-list-main">
                    <span className="b-list-title">{result.full_name}</span>
                    <span className="b-list-sub">
                      {[
                        result.age,
                        result.sex,
                        result.bragi_code,
                        result.masked_identifier ? `ID ${result.masked_identifier}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <span className="b-list-trail">
                    <span className="b-chip b-chip-brand">{t("emergencySelectPatient")}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null}
      </div>

      {/* DELIBERATE EXCEPTION to the "no centered dialogs" rule (see
          BRAGI_REDUCTO_PLAN.md §12): starting a session grants read access
          to a real patient's record and is written to the audit log — a
          genuine blocking/critical workflow, not routine, and the trigger
          can be any row in a search result list (no single stable anchor
          point). No dark backdrop (the shared Dialog no longer has one),
          but the surface itself stays centered so the reason/note form has
          a stable, predictable location during a time-pressured workflow. */}
      <Dialog
        open={confirm !== null}
        onClose={() => {
          if (!starting) setConfirm(null);
        }}
        title={t("emergencyStartSession")}
        description={
          confirm ? t("emergencyStartSessionBody").replace("{name}", confirm.patientName) : undefined
        }
        footer={
          <>
            <button
              type="button"
              className="b-btn b-btn-secondary"
              onClick={() => setConfirm(null)}
              disabled={starting}
            >
              {t("emergencyCancel")}
            </button>
            <button
              type="button"
              className="b-btn b-btn-primary"
              onClick={handleStartSession}
              disabled={starting}
            >
              {starting ? <span className="b-spinner" /> : null}
              {t("emergencyStartAccess")}
            </button>
          </>
        }
      >
        <div className="b-stack-tight">
          <label className="b-field">
            <span className="b-field-label">{t("emergencyReason")}</span>
            <select
              className="b-input"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            >
              {REASON_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          {reason === "Other" ? (
            <label className="b-field">
              <span className="b-field-label">Describe the reason</span>
              <textarea
                className="b-input"
                placeholder="Why is emergency access needed?"
                value={reasonNote}
                onChange={(event) => setReasonNote(event.target.value)}
              />
            </label>
          ) : null}

          {startError ? <ErrorNote>{startError}</ErrorNote> : null}

          <div className="b-danger-note">
            <IconAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{t("emergencyAccessNote")}</span>
          </div>
        </div>
      </Dialog>
    </EmergencyShell>
  );
}
