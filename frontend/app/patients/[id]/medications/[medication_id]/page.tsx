"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type OfficialSection = {
  [sectionTitle: string]: string;
};

type OfficialInfo = {
  rxnorm_name?: string;
  rxcui?: string;
  label_title?: string;
  sections?: OfficialSection;
  candidates?: Array<{ rxcui: string; name: string }>;
};

type PatientMedication = {
  id: number;
  patient_id: number;
  name: string;
  dose_strength?: string | null;
  frequency?: string | null;
  reason?: string | null;
  status: string;
  route_form?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
  prescriber?: string | null;
  extra_info?: string | null;
  is_uncertain: boolean;
  created_at: string;
  updated_at?: string | null;
  created_by?: { id: number; full_name: string } | null;
  official_match_status?: string | null;
  official_source_name?: string | null;
  official_source_url?: string | null;
  rxnorm_rxcui?: string | null;
  official_info?: OfficialInfo | null;
  official_retrieved_at?: string | null;
  official_label_date?: string | null;
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--success-bg)", text: "var(--success-text)" },
  as_needed: { bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", text: "var(--primary)" },
  paused: { bg: "var(--warn-bg)", text: "var(--warn-text)" },
  stopped: { bg: "var(--panel-2)", text: "var(--muted)" },
};

export default function DoctorMedicationViewPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;
  const medicationId = params?.medication_id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [med, setMed] = useState<PatientMedication | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") {
          router.replace(`/my-records/medications/${medicationId}`);
          return;
        }
        const res = await api.get<PatientMedication>(`/patients/${patientId}/medications/${medicationId}`);
        setMed(res.data);
      } catch (err) {
        setError(getErrorMessage(err, t("medLoadError")));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [patientId, medicationId, router]);

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  if (!med || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{error || t("medLoadError")}</p>
      </main>
    );
  }

  const STATUS_LABELS: Record<string, string> = {
    active: t("active"),
    as_needed: t("medStatusAsNeeded"),
    paused: t("medStatusPaused"),
    stopped: t("medStatusStopped"),
  };

  const statusStyle = STATUS_COLORS[med.status] || STATUS_COLORS.stopped;
  const officialInfo = med.official_info;
  const sections = officialInfo?.sections || {};
  const hasSections = Object.keys(sections).length > 0;

  function Field({ label, value }: { label: string; value?: string | null }) {
    return (
      <div>
        <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
          {label}
        </div>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{valueOrDash(value)}</div>
      </div>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={med.name}
      subtitle={t("medPatientReadOnlySubtitle")}
      rightContent={
        <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          {t("backToPatientChart")}
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Read-only notice */}
      <div
        className="soft-card-tight"
        style={{ marginBottom: 20, padding: 14, background: "var(--panel-2)", borderColor: "var(--border)" }}
      >
        <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 3 }}>{t("medDoctorViewOnlySingleTitle")}</div>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
          {t("medDoctorViewOnlySingleDesc")}
        </div>
      </div>

      {/* Main info */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 800, background: statusStyle.bg, color: statusStyle.text }}>
            {STATUS_LABELS[med.status] || med.status}
          </span>
          {med.is_uncertain && (
            <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
              {t("medDoseNotVerified")}
            </span>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 18 }}>
          <Field label={t("medName")} value={med.name} />
          <Field label={t("medDoseStrength")} value={med.dose_strength} />
          <Field label={t("medRouteForm")} value={med.route_form} />
          <Field label={t("medFrequency")} value={med.frequency} />
          <Field label={t("medRecordedReason")} value={med.reason} />
          <Field label={t("medPrescribedBy")} value={med.prescriber} />
          <Field label={t("startDate")} value={med.start_date} />
          <Field label={t("stopDate")} value={med.stop_date} />
        </div>

        {med.extra_info && (
          <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              {t("medAdditionalNotes")}
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.7 }}>{med.extra_info}</div>
          </div>
        )}

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          <div className="muted-text" style={{ fontSize: 11 }}>
            {t("created")} {med.created_at}
            {med.updated_at ? ` · ${t("lastEdited")} ${med.updated_at}` : ""}
          </div>
        </div>
      </div>

      {/* Official information */}
      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ marginBottom: 16 }}>
          <div className="section-title" style={{ marginBottom: 4 }}>{t("medOfficialLabelInfo")}</div>
          <div className="muted-text" style={{ fontSize: 13 }}>
            {t("medOfficialRefClinical")}
          </div>
        </div>

        {(!med.official_match_status || med.official_match_status === "pending") && (
          <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialLookingUp")}</div>
        )}

        {med.official_match_status === "not_matched" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialNoMatchTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialNoMatchDoctorDesc")}</div>
          </div>
        )}

        {med.official_match_status === "vague" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialVagueTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialVagueDoctorDesc")}</div>
          </div>
        )}

        {med.official_match_status === "multiple" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialMultipleCandidates")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialMultipleDoctorDesc")}</div>
          </div>
        )}

        {med.official_match_status === "error" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialErrorTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialErrorDoctorDesc")}</div>
          </div>
        )}

        {med.official_match_status === "matched" && (
          <div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
              <span style={{
                padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800,
                background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)",
              }}>
                {t("medMatchMatched")}
              </span>
              <span className="muted-text" style={{ fontSize: 12 }}>
                {officialInfo?.rxnorm_name || med.name}
                {med.rxnorm_rxcui ? ` · RxCUI ${med.rxnorm_rxcui}` : ""}
              </span>
              {med.official_source_url && (
                <a
                  href={med.official_source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="secondary-btn"
                  style={{ fontSize: 12, padding: "4px 10px", borderRadius: 999 }}
                >
                  {t("medViewSource")}
                </a>
              )}
            </div>

            {med.official_source_name && (
              <div className="muted-text" style={{ fontSize: 12, marginBottom: 12 }}>
                Source: {med.official_source_name}
                {med.official_label_date ? ` · Label date: ${med.official_label_date}` : ""}
                {med.official_retrieved_at ? ` · ${t("retrieved")}: ${med.official_retrieved_at.slice(0, 10)}` : ""}
              </div>
            )}

            <div
              className="soft-card-tight"
              style={{ padding: 12, marginBottom: 16, background: "color-mix(in srgb, var(--warn-bg) 50%, var(--panel-2))", borderColor: "var(--warn-text)" }}
            >
              <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
                {t("medOfficialDisclaimerDoctor")}
              </div>
            </div>

            {hasSections ? (
              <div style={{ display: "grid", gap: 14 }}>
                {Object.entries(sections).map(([title, content]) => (
                  <div key={title} className="soft-card-tight" style={{ padding: 16 }}>
                    <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 8 }}>{title}</div>
                    <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
                      {content}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted-text" style={{ fontSize: 13 }}>
                {t("medOfficialNoSectionsDoctor")}
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
