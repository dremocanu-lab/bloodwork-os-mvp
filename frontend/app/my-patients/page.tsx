"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type LabInsight = {
  id?: number;
  display_name?: string | null;
  value?: string | null;
  unit?: string | null;
  flag?: string | null;
  reference_range?: string | null;
};

type PatientCard = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  active_event?: {
    id: number;
    title: string;
    status: string;
    department?: string | null;
    hospital_name?: string | null;
    admitted_at?: string | null;
  } | null;
  care_context?: "active_admission" | "past_admission" | "outpatient";
  care_context_label?: string | null;
  new_records_count?: number;
  has_new_records?: boolean;
  abnormal_count?: number;
  latest_abnormal_labs?: LabInsight[];
};

type FilterMode = "all" | "active" | "new" | "abnormal" | "inactive";

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin {
          to {
            transform: rotate(360deg);
          }
        }

        .bloodwork-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: bloodworkSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="bloodwork-spinner" />
    </>
  );
}

function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean).slice(0, 2);
  if (!parts.length) return "P";
  return parts.map((part) => part[0]?.toUpperCase()).join("");
}

function getCareLabel(item: PatientCard) {
  if (item.care_context_label) return item.care_context_label;
  if (item.care_context === "active_admission") return "Active admission";
  if (item.care_context === "past_admission") return "Past admission";
  return "Outpatient follow-up";
}

function getCardTheme(item: PatientCard) {
  const abnormalCount = item.abnormal_count ?? 0;

  if (abnormalCount > 0) {
    return {
      band: "var(--danger-text)",
      badgeBg: "var(--danger-bg)",
      badgeText: "var(--danger-text)",
      badgeBorder: "var(--danger-border)",
      avatarBg: "linear-gradient(135deg, var(--danger-bg), var(--panel-2))",
      avatarText: "var(--danger-text)",
      border: "var(--danger-border)",
      buttonBg: "linear-gradient(135deg, var(--danger-text), #ef4444)",
      buttonText: "white",
      glow: "rgba(220, 38, 38, 0.22)",
      cardBg: "linear-gradient(180deg, var(--danger-bg) 0%, var(--panel) 42%)",
    };
  }

  if (item.care_context === "active_admission") {
    return {
      band: "var(--success-text)",
      badgeBg: "var(--success-bg)",
      badgeText: "var(--success-text)",
      badgeBorder: "var(--success-border)",
      avatarBg: "linear-gradient(135deg, var(--success-bg), var(--panel-2))",
      avatarText: "var(--success-text)",
      border: "var(--success-border)",
      buttonBg: "linear-gradient(135deg, var(--success-text), #22c55e)",
      buttonText: "white",
      glow: "rgba(22, 163, 74, 0.2)",
      cardBg: "linear-gradient(180deg, var(--success-bg) 0%, var(--panel) 42%)",
    };
  }

  return {
    band: "var(--primary)",
    badgeBg: "color-mix(in srgb, var(--primary) 16%, var(--panel-2))",
    badgeText: "var(--primary)",
    badgeBorder: "color-mix(in srgb, var(--primary) 38%, var(--border))",
    avatarBg: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 24%, var(--panel-2)), var(--panel-2))",
    avatarText: "var(--primary)",
    border: "color-mix(in srgb, var(--primary) 30%, var(--border))",
    buttonBg: "linear-gradient(135deg, var(--primary), color-mix(in srgb, var(--primary) 72%, #ffffff))",
    buttonText: "white",
    glow: "color-mix(in srgb, var(--primary) 24%, transparent)",
    cardBg: "linear-gradient(180deg, color-mix(in srgb, var(--primary) 14%, var(--panel)) 0%, var(--panel) 44%)",
  };
}

export default function MyPatientsPage() {
  const router = useRouter();
  const { t, language } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [patients, setPatients] = useState<PatientCard[]>([]);
  const [query, setQuery] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        newRecords: "Documente noi",
        newRecord: "Document nou",
        noNewRecords: "Fără documente noi",
        activeAdmission: "Internare activă",
        abnormalUnreviewed: "Rezultate anormale nerevizuite",
        searchPlaceholder: "Caută după nume, CNP sau ID pacient...",
        patientDetails: "Detalii pacient",
        openChart: "Deschide fișa",
        searchAllPatients: "Caută toți pacienții",
        totalUnderCare: "Pacienți în grijă",
        patientsWithNewRecords: "Cu documente noi",
        activeAdmissions: "Internări active",
        abnormalAttention: "Cu rezultate anormale",
        all: "Toți",
        active: "Internați",
        new: "Noi",
        abnormal: "Anormale",
        inactive: "Fără internare activă",
        helper:
          "Documentele noi sunt specifice medicului. În internare se afișează doar documentele noi din episodul curent; în ambulatoriu se afișează documentele nerevizuite ale pacienților alocați.",
      };
    }

    return {
      newRecords: "New records",
      newRecord: "New record",
      noNewRecords: "No new records",
      activeAdmission: "Active admission",
      abnormalUnreviewed: "Unreviewed abnormal results",
      searchPlaceholder: "Search by name, CNP, or patient ID...",
      patientDetails: "Patient details",
      openChart: "Open chart",
      searchAllPatients: "Search all patients",
      totalUnderCare: "Patients under care",
      patientsWithNewRecords: "With new records",
      activeAdmissions: "Active admissions",
      abnormalAttention: "With abnormal results",
      all: "All",
      active: "Active",
      new: "New",
      abnormal: "Abnormal",
      inactive: "No active stay",
      helper:
        "New records are doctor-specific. Active admission doctors only see new records from the current stay; outpatient doctors see unreviewed records for their assigned patients.",
    };
  }, [language]);

  async function fetchData() {
    const [meResponse, patientsResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<PatientCard[]>("/my-patients"),
    ]);

    if (meResponse.data.role !== "doctor") {
      router.push(meResponse.data.role === "patient" ? "/my-records" : "/assignments");
      return;
    }

    setCurrentUser(meResponse.data);
    setPatients(patientsResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch {
        localStorage.removeItem("access_token");
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }

    init();
  }, []);

  const stats = useMemo(() => {
    const active = patients.filter((item) => item.active_event).length;
    const withNewRecords = patients.filter((item) => (item.new_records_count ?? 0) > 0).length;
    const abnormalPatients = patients.filter((item) => (item.abnormal_count ?? 0) > 0).length;

    return {
      total: patients.length,
      active,
      withNewRecords,
      abnormalPatients,
    };
  }, [patients]);

  const filteredPatients = useMemo(() => {
    const term = query.trim().toLowerCase();

    return patients
      .filter((item) => {
        const newCount = item.new_records_count ?? 0;
        const abnormalCount = item.abnormal_count ?? 0;

        if (filterMode === "active" && !item.active_event) return false;
        if (filterMode === "inactive" && item.active_event) return false;
        if (filterMode === "new" && newCount <= 0) return false;
        if (filterMode === "abnormal" && abnormalCount <= 0) return false;

        if (!term) return true;

        const abnormalNames = (item.latest_abnormal_labs ?? [])
          .map((lab) => lab.display_name)
          .filter(Boolean)
          .join(" ");

        const haystack = [
          item.patient.full_name,
          item.patient.date_of_birth,
          item.patient.age,
          item.patient.sex,
          item.patient.cnp,
          item.patient.patient_identifier,
          item.active_event?.title,
          getCareLabel(item),
          abnormalNames,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();

        return haystack.includes(term);
      })
      .sort((a, b) => {
        const aAbnormal = a.abnormal_count ?? 0;
        const bAbnormal = b.abnormal_count ?? 0;
        const aNew = a.new_records_count ?? 0;
        const bNew = b.new_records_count ?? 0;

        if (a.active_event && !b.active_event) return -1;
        if (!a.active_event && b.active_event) return 1;
        if (aAbnormal > 0 && bAbnormal === 0) return -1;
        if (aAbnormal === 0 && bAbnormal > 0) return 1;
        if (aNew > 0 && bNew === 0) return -1;
        if (aNew === 0 && bNew > 0) return 1;

        return a.patient.full_name.localeCompare(b.patient.full_name);
      });
  }, [patients, query, filterMode]);

  function getFilterLabel(mode: FilterMode) {
    if (mode === "all") return labels.all;
    if (mode === "active") return labels.active;
    if (mode === "new") return labels.new;
    if (mode === "abnormal") return labels.abnormal;
    return labels.inactive;
  }

  if (loading || !currentUser) {
    return (
      <main
        className="app-page-bg"
        style={{
          minHeight: "100vh",
          padding: 24,
          display: "grid",
          placeItems: "center",
        }}
      >
        <div
          className="soft-card-tight"
          style={{
            padding: 22,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <Spinner size={20} />
          <span className="muted-text">{t("loadingPatients")}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("myCurrentPatients")}
      subtitle={t("myCurrentPatientsSubtitle")}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/patients/search")}>
          {labels.searchAllPatients}
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">{labels.totalUnderCare}</div>
          <div className="stat-card-value">{stats.total}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">{labels.patientsWithNewRecords}</div>
          <div className="stat-card-value">{stats.withNewRecords}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">{labels.activeAdmissions}</div>
          <div className="stat-card-value">{stats.active}</div>
        </div>

        <div className="stat-card stat-card-accent-orange">
          <div className="stat-card-label">{labels.abnormalAttention}</div>
          <div className="stat-card-value">{stats.abnormalPatients}</div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            marginBottom: 18,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div className="section-title">{t("patientList")}</div>
            <div className="muted-text" style={{ marginTop: 6, maxWidth: 740, lineHeight: 1.6 }}>
              {labels.helper}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {(["all", "active", "new", "abnormal", "inactive"] as FilterMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={filterMode === mode ? "primary-btn" : "secondary-btn"}
                onClick={() => setFilterMode(mode)}
              >
                {getFilterLabel(mode)}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 22 }}>
          <input
            className="text-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={labels.searchPlaceholder}
          />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))",
            gap: 20,
          }}
        >
          {filteredPatients.map((item) => {
            const abnormalCount = item.abnormal_count ?? 0;
            const newCount = item.new_records_count ?? 0;
            const latestAbnormalLabs = item.latest_abnormal_labs ?? [];
            const theme = getCardTheme(item);

            return (
              <article
                key={item.patient.id}
                className="soft-card-tight"
                style={{
                  padding: 0,
                  minHeight: 440,
                  borderRadius: 32,
                  borderColor: theme.border,
                  background: theme.cardBg,
                  display: "grid",
                  gridTemplateRows: "auto auto 1fr auto",
                  gap: 14,
                  position: "relative",
                  overflow: "hidden",
                  boxShadow: `0 22px 55px ${theme.glow}`,
                }}
              >
                <div style={{ height: 9, background: theme.band }} />

                {abnormalCount > 0 && (
                  <span
                    title={labels.abnormalUnreviewed}
                    style={{
                      position: "absolute",
                      top: 23,
                      right: 18,
                      width: 14,
                      height: 14,
                      borderRadius: 999,
                      background: "var(--danger-text)",
                      boxShadow: "0 0 0 6px var(--danger-bg)",
                    }}
                  />
                )}

                <div
                  style={{
                    padding: "12px 18px 0",
                    display: "grid",
                    gap: 14,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 10,
                      alignItems: "center",
                      paddingRight: abnormalCount > 0 ? 28 : 0,
                    }}
                  >
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "8px 11px",
                        borderRadius: 999,
                        background: theme.badgeBg,
                        color: theme.badgeText,
                        border: `1px solid ${theme.badgeBorder}`,
                        fontWeight: 950,
                        fontSize: 12,
                      }}
                    >
                      {getCareLabel(item)}
                    </span>

                    <span
                      style={{
                        display: "inline-flex",
                        padding: "8px 11px",
                        borderRadius: 999,
                        background: theme.badgeBg,
                        color: theme.badgeText,
                        border: `1px solid ${theme.badgeBorder}`,
                        fontWeight: 950,
                        fontSize: 12,
                      }}
                    >
                      {newCount > 0
                        ? `${newCount} ${newCount === 1 ? labels.newRecord : labels.newRecords}`
                        : labels.noNewRecords}
                    </span>
                  </div>

                  <div style={{ textAlign: "center", padding: "4px 6px 0" }}>
                    <div
                      style={{
                        width: 96,
                        height: 96,
                        borderRadius: 32,
                        margin: "0 auto 15px",
                        display: "grid",
                        placeItems: "center",
                        background: theme.avatarBg,
                        color: theme.avatarText,
                        border: `1px solid ${theme.badgeBorder}`,
                        fontSize: 30,
                        fontWeight: 950,
                        letterSpacing: "-0.08em",
                        boxShadow: `0 18px 38px ${theme.glow}, inset 0 1px 0 rgba(255,255,255,0.4)`,
                      }}
                    >
                      {getInitials(item.patient.full_name)}
                    </div>

                    <div
                      style={{
                        fontWeight: 950,
                        fontSize: 24,
                        letterSpacing: "-0.055em",
                        lineHeight: 1.05,
                      }}
                    >
                      {item.patient.full_name}
                    </div>

                    <div className="muted-text" style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6 }}>
                      {t("age")} {valueOrDash(item.patient.age)} · {t("sex")} {valueOrDash(item.patient.sex)}
                    </div>
                  </div>

                  <div style={{ display: "grid", gap: 10, alignContent: "start" }}>
                    <div
                      style={{
                        padding: 13,
                        borderRadius: 20,
                        background: "color-mix(in srgb, var(--panel-2) 88%, var(--primary))",
                        border: `1px solid ${theme.badgeBorder}`,
                      }}
                    >
                      <div
                        className="muted-text"
                        style={{
                          fontSize: 11,
                          fontWeight: 950,
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                        }}
                      >
                        {labels.patientDetails}
                      </div>

                      <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.75, fontSize: 13 }}>
                        {t("dob")} {valueOrDash(item.patient.date_of_birth)}
                        <br />
                        CNP {valueOrDash(item.patient.cnp)}
                        <br />
                        ID {valueOrDash(item.patient.patient_identifier)}
                      </div>
                    </div>

                    {item.active_event && (
                      <div
                        style={{
                          padding: 13,
                          borderRadius: 20,
                          background: "var(--success-bg)",
                          color: "var(--success-text)",
                          border: "1px solid var(--success-border)",
                        }}
                      >
                        <div
                          style={{
                            fontSize: 11,
                            fontWeight: 950,
                            textTransform: "uppercase",
                            letterSpacing: "0.05em",
                          }}
                        >
                          {labels.activeAdmission}
                        </div>
                        <div style={{ marginTop: 7, fontWeight: 900, lineHeight: 1.35 }}>
                          {item.active_event.title}
                        </div>
                        <div style={{ marginTop: 6, fontSize: 12, opacity: 0.82 }}>
                          {t("admitted")} {valueOrDash(item.active_event.admitted_at)}
                        </div>
                      </div>
                    )}

                    {latestAbnormalLabs.length > 0 && (
                      <div
                        style={{
                          padding: 13,
                          borderRadius: 20,
                          background: "var(--danger-bg)",
                          color: "var(--danger-text)",
                          border: "1px solid var(--danger-border)",
                        }}
                      >
                        <div
                          style={{
                            fontSize: 11,
                            fontWeight: 950,
                            textTransform: "uppercase",
                            letterSpacing: "0.05em",
                          }}
                        >
                          {labels.abnormalUnreviewed}
                        </div>

                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                          {latestAbnormalLabs.slice(0, 3).map((lab, index) => (
                            <span
                              key={`${lab.display_name}-${index}`}
                              style={{
                                display: "inline-flex",
                                padding: "6px 8px",
                                borderRadius: 999,
                                background: "var(--panel)",
                                color: "var(--danger-text)",
                                border: "1px solid var(--danger-border)",
                                fontWeight: 850,
                                fontSize: 11,
                              }}
                            >
                              {valueOrDash(lab.display_name)} {valueOrDash(lab.value)}
                              {lab.unit ? ` ${lab.unit}` : ""}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => router.push(`/patients/${item.patient.id}`)}
                  style={{
                    width: "calc(100% - 36px)",
                    margin: "0 18px 18px",
                    justifyContent: "center",
                    padding: "15px 16px",
                    borderRadius: 20,
                    fontWeight: 950,
                    border: "1px solid color-mix(in srgb, var(--primary) 65%, var(--border))",
                    background: theme.buttonBg,
                    color: theme.buttonText,
                    boxShadow: `0 16px 34px ${theme.glow}`,
                    cursor: "pointer",
                  }}
                >
                  {labels.openChart}
                </button>
              </article>
            );
          })}

          {!filteredPatients.length && (
            <div
              className="soft-card-tight"
              style={{
                padding: 22,
                background: "var(--panel-2)",
                gridColumn: "1 / -1",
              }}
            >
              <div style={{ fontWeight: 900 }}>{t("noPatientsMatch")}</div>
              <div className="muted-text" style={{ marginTop: 8 }}>
                {t("noPatientsMatchDesc")}
              </div>
              <button
                type="button"
                className="primary-btn"
                style={{ marginTop: 16 }}
                onClick={() => router.push("/patients/search")}
              >
                {labels.searchAllPatients}
              </button>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
