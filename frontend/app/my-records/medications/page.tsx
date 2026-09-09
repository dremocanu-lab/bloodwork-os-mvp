"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { EmptyState } from "@/components/ui";
import { api, getErrorMessage } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
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

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--success-bg)", text: "var(--success-text)" },
  as_needed: { bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", text: "var(--primary)" },
  paused: { bg: "var(--warn-bg)", text: "var(--warn-text)" },
  stopped: { bg: "var(--panel-2)", text: "var(--muted)" },
};

export default function MedicationsListPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [medications, setMedications] = useState<PatientMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const STATUS_LABELS: Record<string, string> = {
    active: t("active"),
    as_needed: t("medStatusAsNeeded"),
    paused: t("medStatusPaused"),
    stopped: t("medStatusStopped"),
  };

  const MATCH_LABELS: Record<string, string> = {
    pending: t("medMatchPending"),
    matched: t("medMatchMatched"),
    not_matched: t("medMatchNotMatched"),
    multiple: t("medMatchMultiple"),
    vague: t("medMatchVague"),
    error: t("medMatchError"),
  };

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
        setError(getErrorMessage(err, t("medLoadError")));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  // Clinical ordering: what the patient is currently taking comes first.
  // The API returns newest-created first, which put a stopped drug above a
  // current one - misleading in a medication list.
  const STATUS_RANK: Record<string, number> = {
    active: 0,
    as_needed: 1,
    paused: 2,
    stopped: 3,
  };

  const filtered = (
    statusFilter ? medications.filter((m) => m.status === statusFilter) : medications
  )
    .slice()
    .sort((a, b) => {
      const rank = (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
      return rank !== 0 ? rank : a.name.localeCompare(b.name);
    });

  const active = medications.filter((m) => m.status === "active").length;
  const asNeeded = medications.filter((m) => m.status === "as_needed").length;

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
      title={t("myMedications")}
      rightContent={
        <button
          type="button"
          className="primary-btn"
          onClick={() => router.push("/my-records/medications/new")}
        >
          {t("addMedication")}
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
      {/* These records are unverified, which is genuinely important, so the
          notice stays prominent - but as the product's notice pattern rather
          than a bespoke violet panel. */}
      <div className="b-notice b-notice-warn" style={{ marginBottom: "var(--s4)", display: "block" }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{t("medSafetyTitle")}</div>
        <div>{t("medSafetyDesc")}</div>
      </div>

      {/* Summary row */}
      {medications.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 20 }}>
          {[
            { label: t("total"), value: medications.length, onClick: () => setStatusFilter("") },
            { label: t("active"), value: active, onClick: () => setStatusFilter("active") },
            { label: t("medStatusAsNeeded"), value: asNeeded, onClick: () => setStatusFilter("as_needed") },
          ].map(({ label, value, onClick }) => (
            <div
              key={label}
              className="soft-card"
              style={{ padding: "14px 18px", cursor: "pointer" }}
              onClick={onClick}
            >
              <div className="muted-text" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
              <div style={{ fontSize: 21, fontWeight: 600, letterSpacing: "-0.04em", lineHeight: 1, marginTop: 6 }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter row */}
      {medications.length > 0 && (
        <div className="b-filters" style={{ marginBottom: "var(--s4)" }}>
          {["", "active", "as_needed", "paused", "stopped"].map((s) => (
            <button
              key={s}
              type="button"
              className="b-filter"
              aria-pressed={statusFilter === s}
              onClick={() => setStatusFilter(s)}
            >
              {s === "" ? t("all") : STATUS_LABELS[s]}
            </button>
          ))}
        </div>
      )}

      {/* Medication list.
          Was one 155px card per medication with three full-radius status
          pills stacked above the drug name - the name, which is what a
          reader scans for, came third. Now the name leads, dose/route/
          frequency is the secondary line, and state is a status dot on the
          right. */}
      <section className="b-surface">
        <div className="b-list">
          {filtered.map((med) => (
            <button
              key={med.id}
              type="button"
              className="b-list-row"
              onClick={() => router.push(`/my-records/medications/${med.id}`)}
            >
              <span className="b-list-main">
                <span className="b-list-title">{med.name}</span>
                <span className="b-list-sub">
                  {[med.dose_strength, med.route_form, med.frequency]
                    .filter(Boolean)
                    .join(" · ") || t("medNoDoseFrequency")}
                  {med.reason ? ` · ${med.reason}` : ""}
                </span>
                <span className="b-strip" style={{ marginTop: 2 }}>
                  {med.is_uncertain ? (
                    <span className="b-chip b-chip-warn">{t("medDoseNotVerified")}</span>
                  ) : null}
                  {med.official_match_status === "matched" ? (
                    <span className="b-chip">{t("medOfficialInfoAvailable")}</span>
                  ) : null}
                </span>
              </span>

              <span className="b-list-trail">
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
                {med.start_date ? (
                  <span className="b-range">
                    {t("medSince")} {med.start_date}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>

        {filtered.length === 0 && medications.length === 0 && (
          <div className="soft-card" style={{ padding: 32, textAlign: "center" }}>
            <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 10 }}>{t("noMedicationsYet")}</div>
            <div className="muted-text" style={{ marginBottom: 20, lineHeight: 1.65 }}>
              {t("noMedicationsYetDesc")}
            </div>
            <button type="button" className="b-btn b-btn-secondary" onClick={() => router.push("/my-records/medications/new")}>
              {t("addFirstMedication")}
            </button>
          </div>
        )}

        {filtered.length === 0 && medications.length > 0 ? (
          <EmptyState title={t("noMedicationsFilter")} />
        ) : null}
      </section>

    </AppShell>
  );
}
