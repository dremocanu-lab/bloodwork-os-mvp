"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
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

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--success-bg)", text: "var(--success-text)" },
  as_needed: { bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", text: "var(--primary)" },
  paused: { bg: "var(--warn-bg)", text: "var(--warn-text)" },
  stopped: { bg: "var(--panel-2)", text: "var(--muted)" },
};

function OfficialBadge({ status }: { status?: string | null }) {
  if (!status || status === "pending") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
      Looking up…
    </span>
  );
  if (status === "matched") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)" }}>
      Official info matched
    </span>
  );
  if (status === "not_matched") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
      No official match
    </span>
  );
  if (status === "vague") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
      Name too vague
    </span>
  );
  if (status === "multiple") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
      Multiple matches
    </span>
  );
  if (status === "error") return (
    <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
      Lookup error
    </span>
  );
  return null;
}

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
    return result;
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
        <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 3 }}>{t("medDoctorViewOnlyTitle")}</div>
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
              <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{label}</div>
              <div style={{ fontWeight: 800, fontSize: 22, letterSpacing: "-0.03em", color: accent || "var(--foreground)" }}>{value}</div>
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
              className={statusFilter === f.key ? "primary-btn" : "secondary-btn"}
              style={{ borderRadius: 999, padding: "7px 14px", fontSize: 12 }}
              onClick={() => setStatusFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
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
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 7 }}>
                    <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: statusStyle.bg, color: statusStyle.text }}>
                      {STATUS_LABELS[med.status] || med.status}
                    </span>
                    {med.is_uncertain && (
                      <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                        {t("medDoseNotVerified")}
                      </span>
                    )}
                    <OfficialBadge status={med.official_match_status} />
                  </div>
                  <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em", marginBottom: 5 }}>{med.name}</div>
                  <div className="muted-text" style={{ fontSize: 13 }}>
                    {[med.dose_strength, med.frequency, med.route_form].filter(Boolean).join(" · ") || t("medNoDoseFrequency")}
                  </div>
                  {med.reason && (
                    <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>
                      {t("medRecordedReasonLabel")} {med.reason}
                    </div>
                  )}
                  {med.prescriber && (
                    <div className="muted-text" style={{ marginTop: 2, fontSize: 12 }}>
                      {t("medPrescribedBy")}: {med.prescriber}
                    </div>
                  )}
                </div>

                <div style={{ flexShrink: 0, textAlign: "right" }}>
                  {med.start_date && <div className="muted-text" style={{ fontSize: 11 }}>{t("medSince")} {med.start_date}</div>}
                  {med.stop_date && <div className="muted-text" style={{ fontSize: 11 }}>{t("medStatusStopped")} {med.stop_date}</div>}
                </div>
              </div>
            </button>
          );
        })}

        {filtered.length === 0 && (
          <div className="muted-text" style={{ padding: "24px 0", textAlign: "center" }}>
            {medications.length === 0
              ? t("medPatientNone")
              : searchQuery
              ? "No medications match this search."
              : t("noMedicationsFilter")}
          </div>
        )}
      </div>
    </AppShell>
  );
}
