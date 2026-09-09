"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { EmptyState as SharedEmptyState } from "@/components/ui";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

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
  route_form?: string | null;
  prescriber?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
  is_uncertain: boolean;
  official_match_status?: string | null;
};

export default function DoctorMedicationsListPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [medications, setMedications] = useState<PatientMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [officialFilter, setOfficialFilter] = useState("");

  const STATUS_LABELS: Record<string, string> = {
    active: t("active"),
    as_needed: t("medStatusAsNeeded"),
    paused: t("medStatusPaused"),
    stopped: t("medStatusStopped"),
  };

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") { router.replace("/my-records/medications"); return; }
        const res = await api.get<PatientMedication[]>(`/patients/${patientId}/medications`);
        setMedications(Array.isArray(res.data) ? res.data : []);
      } catch (err) {
        setError(getErrorMessage(err, t("medLoadError")));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [patientId, router]);

  const stats = useMemo(() => {
    const active = medications.filter((m) => m.status === "active").length;
    const asNeeded = medications.filter((m) => m.status === "as_needed").length;
    const pausedStopped = medications.filter((m) => m.status === "paused" || m.status === "stopped").length;
    const uncertain = medications.filter((m) => m.is_uncertain).length;
    const matched = medications.filter((m) => m.official_match_status === "matched").length;
    const needsVerification = medications.filter((m) =>
      m.official_match_status === "vague" || m.official_match_status === "multiple" || m.official_match_status === "not_matched"
    ).length;
    return { total: medications.length, active, asNeeded, pausedStopped, uncertain, matched, needsVerification };
  }, [medications]);

  // Active first, then as-needed, paused, stopped. The API's creation order
  // could surface a stopped drug above a current one.
  const STATUS_RANK: Record<string, number> = {
    active: 0,
    as_needed: 1,
    paused: 2,
    stopped: 3,
  };

  const filtered = useMemo(() => {
    let result = medications;
    if (statusFilter === "uncertain") {
      result = result.filter((m) => m.is_uncertain);
    } else if (statusFilter === "official_matched") {
      result = result.filter((m) => m.official_match_status === "matched");
    } else if (statusFilter === "official_unmatched") {
      result = result.filter((m) =>
        m.official_match_status === "vague" || m.official_match_status === "multiple" || m.official_match_status === "not_matched"
      );
    } else if (statusFilter) {
      result = result.filter((m) => m.status === statusFilter);
    }

    if (officialFilter) {
      result = result.filter((m) => m.official_match_status === officialFilter);
    }

    const term = searchQuery.trim().toLowerCase();
    if (term) {
      result = result.filter((m) =>
        [m.name, m.dose_strength, m.frequency, m.reason, m.prescriber, m.route_form]
          .filter(Boolean).join(" ").toLowerCase().includes(term)
      );
    }
    return result.slice().sort((a, b) => {
      const rank = (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
      return rank !== 0 ? rank : a.name.localeCompare(b.name);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [medications, statusFilter, officialFilter, searchQuery]);

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingMedications")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser!}
      title={t("patientMedications")}
      subtitle="Patient-entered medication records. Dose and frequency are not clinician-verified."
      rightContent={
        <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          {t("backToChart")}
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Safety notice */}
      <div className="soft-card-tight" style={{ marginBottom: 20, padding: 14, background: "var(--panel-2)" }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>{t("medDoctorViewOnlyTitle")}</div>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
          {t("medDoctorViewOnlyDesc")}
        </div>
      </div>

      {/* Summary stats */}
      {medications.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginBottom: 20 }}>
          {[
            { label: t("medStatsTotal"), value: stats.total },
            { label: t("active"), value: stats.active, accent: stats.active > 0 ? "var(--success-text)" : undefined },
            { label: t("medStatusAsNeeded"), value: stats.asNeeded },
            { label: t("medStatsPausedStopped"), value: stats.pausedStopped },
            { label: t("medDoseNotVerified"), value: stats.uncertain, accent: stats.uncertain > 0 ? "var(--warn-text)" : undefined },
            { label: t("officialInfoMatched"), value: stats.matched, accent: stats.matched > 0 ? "var(--primary)" : undefined },
          ].map(({ label, value, accent }) => (
            <div key={label} className="soft-card" style={{ padding: "14px 16px" }}>
              <div className="muted-text" style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{label}</div>
              <div style={{ fontWeight: 600, fontSize: 22, letterSpacing: "-0.03em", color: accent || "var(--text)" }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Search */}
      <div style={{ marginBottom: 14 }}>
        <input
          className="text-input"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t("searchMedications")}
        />
      </div>

      {/* Filter row */}
      {medications.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          {[
            { key: "", label: `${t("all")} (${medications.length})` },
            { key: "active", label: `${STATUS_LABELS.active} (${stats.active})` },
            { key: "as_needed", label: `${STATUS_LABELS.as_needed} (${stats.asNeeded})` },
            { key: "paused", label: `${t("medStatusPaused")} (${medications.filter((m) => m.status === "paused").length})` },
            { key: "stopped", label: `${t("medStatusStopped")} (${medications.filter((m) => m.status === "stopped").length})` },
            { key: "uncertain", label: `${t("medDoseNotVerified")} (${stats.uncertain})` },
            { key: "official_matched", label: `${t("officialInfoMatched")} (${stats.matched})` },
            { key: "official_unmatched", label: `Needs verification (${stats.needsVerification})` },
          ].map((f) => (
            <button
              key={f.key}
              type="button"
              className="b-filter"
              aria-pressed={statusFilter === f.key}
              onClick={() => setStatusFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      {/* Medication table.
          This is a clinical review surface, so it is a table: name, dose,
          frequency, route, prescriber, dates and state in aligned columns.
          Previously each medication was a 150px card whose first line was a
          row of status pills, with the drug name third - a doctor scanning
          eight medications had to read past 24 pills to find them. */}
      <section className="b-surface">
        <div className="b-table-wrap" tabIndex={0} role="region" aria-label={t("medications")}>
          <table className="b-table b-table-hover b-table-clickable">
            <thead>
              <tr>
                <th scope="col">{t("medications")}</th>
                <th scope="col">{t("dose")}</th>
                <th scope="col" className="hide-below-900">{t("frequency")}</th>
                <th scope="col" className="hide-below-1100">{t("medPrescribedBy")}</th>
                <th scope="col" className="num hide-below-640">{t("medSince")}</th>
                <th scope="col" style={{ width: 150 }}>Status</th>
              </tr>
            </thead>

            <tbody>
              {filtered.map((med) => (
                <tr
                  key={med.id}
                  tabIndex={0}
                  className={med.is_uncertain ? "row-warn" : undefined}
                  onClick={() => router.push(`/patients/${patientId}/medications/${med.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/patients/${patientId}/medications/${med.id}`);
                    }
                  }}
                >
                  <td>
                    <span className="b-cell-stack">
                      <span className="b-cell-title">{med.name}</span>
                      {med.reason ? (
                        <span className="b-cell-sub">{med.reason}</span>
                      ) : null}
                    </span>
                  </td>

                  <td>
                    <span className="tnum">{med.dose_strength || "—"}</span>
                    {med.route_form ? <span className="b-unit">{med.route_form}</span> : null}
                  </td>

                  <td className="hide-below-900">
                    <span style={{ color: "var(--text-2)" }}>{med.frequency || "—"}</span>
                  </td>

                  <td className="hide-below-1100">
                    <span className="b-cell-sub">{med.prescriber || "—"}</span>
                  </td>

                  <td className="num hide-below-640">
                    <span className="b-range">{med.start_date || "—"}</span>
                  </td>

                  <td>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "var(--s2)",
                        flexWrap: "wrap",
                      }}
                    >
                      <span
                        className={`b-status ${
                          med.status === "active"
                            ? "b-status-ok"
                            : med.status === "as_needed"
                            ? "b-status-info"
                            : med.status === "paused"
                            ? "b-status-warn"
                            : "b-status-muted"
                        }`}
                      >
                        {STATUS_LABELS[med.status] || med.status}
                      </span>
                      {med.is_uncertain ? (
                        <span className="b-chip b-chip-warn">{t("medDoseNotVerified")}</span>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 ? (
          <SharedEmptyState
            title={
              medications.length === 0
                ? t("medPatientNone")
                : searchQuery
                ? "No medications match this search"
                : t("noMedicationsFilter")
            }
          />
        ) : null}
      </section>

    </AppShell>
  );
}
