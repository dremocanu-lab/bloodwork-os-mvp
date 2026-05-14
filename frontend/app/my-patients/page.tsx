"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
import type { AppLanguage } from "@/lib/i18n";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
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
          to { transform: rotate(360deg); }
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
  return parts.map((p) => p[0]?.toUpperCase()).join("");
}

function getCareLabel(item: PatientCard) {
  if (item.care_context_label) return item.care_context_label;
  if (item.care_context === "active_admission") return "Active admission";
  if (item.care_context === "past_admission") return "Past admission";
  return "Outpatient";
}

function rowAccent(item: PatientCard): string {
  if ((item.abnormal_count ?? 0) > 0) return "var(--danger-text)";
  if (item.care_context === "active_admission") return "var(--success-text)";
  return "var(--primary)";
}

function avatarColors(item: PatientCard): { bg: string; color: string } {
  if ((item.abnormal_count ?? 0) > 0)
    return { bg: "var(--danger-bg)", color: "var(--danger-text)" };
  if (item.care_context === "active_admission")
    return { bg: "var(--success-bg)", color: "var(--success-text)" };
  return { bg: "var(--primary-soft)", color: "var(--primary)" };
}

type PatientRowProps = {
  item: PatientCard;
  labels: ReturnType<typeof buildLabels>;
  language: AppLanguage;
  onClick: () => void;
};

function PatientRow({ item, labels, language, onClick }: PatientRowProps) {
  const abnormalCount = item.abnormal_count ?? 0;
  const newCount = item.new_records_count ?? 0;
  const labs = item.latest_abnormal_labs ?? [];
  const accent = rowAccent(item);
  const av = avatarColors(item);
  const careLabel = getCareLabel(item);
  const isActive = item.care_context === "active_admission";

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "grid",
        gridTemplateColumns: "4px 52px 1fr auto auto",
        alignItems: "center",
        gap: "0 14px",
        width: "100%",
        minHeight: 68,
        padding: "10px 16px 10px 0",
        background: "none",
        border: "none",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        textAlign: "left",
      }}
    >
      {/* Left accent bar */}
      <span
        style={{
          alignSelf: "stretch",
          width: 4,
          borderRadius: "0 2px 2px 0",
          background: accent,
          flexShrink: 0,
        }}
      />

      {/* Avatar */}
      <span
        style={{
          width: 40,
          height: 40,
          borderRadius: 12,
          display: "grid",
          placeItems: "center",
          background: av.bg,
          color: av.color,
          fontWeight: 800,
          fontSize: 14,
          letterSpacing: "-0.03em",
          flexShrink: 0,
          border: `1px solid color-mix(in srgb, ${av.color} 22%, transparent)`,
        }}
      >
        {getInitials(item.patient.full_name)}
      </span>

      {/* Name + meta */}
      <span style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
        <span
          style={{
            fontWeight: 700,
            fontSize: 14,
            color: "var(--text)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {item.patient.full_name}
        </span>
        <span
          style={{
            fontSize: 12,
            color: "var(--muted)",
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <span>{formatPatientAge(item.patient.date_of_birth, language)}</span>
          {item.patient.sex && (
            <>
              <span style={{ opacity: 0.4 }}>·</span>
              <span>{item.patient.sex}</span>
            </>
          )}
          <span style={{ opacity: 0.4 }}>·</span>
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 600,
              background: isActive ? "var(--success-bg)" : "var(--panel-2)",
              color: isActive ? "var(--success-text)" : "var(--muted)",
              border: `1px solid ${isActive ? "color-mix(in srgb, var(--success-text) 24%, transparent)" : "var(--border)"}`,
            }}
          >
            {careLabel}
          </span>
          {item.active_event && (
            <span style={{ opacity: 0.72, fontStyle: "italic" }}>{item.active_event.title}</span>
          )}
        </span>
      </span>

      {/* Badges: new records + abnormal labs */}
      <span
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          alignItems: "flex-end",
          flexShrink: 0,
        }}
      >
        {newCount > 0 && (
          <span
            style={{
              padding: "2px 8px",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 700,
              background: "var(--primary-soft)",
              color: "var(--primary)",
              border: "1px solid color-mix(in srgb, var(--primary) 28%, transparent)",
              whiteSpace: "nowrap",
            }}
          >
            {newCount} {newCount === 1 ? labels.newRecord : labels.newRecords}
          </span>
        )}
        {abnormalCount > 0 && (
          <span
            style={{
              display: "flex",
              gap: 4,
              alignItems: "center",
              flexWrap: "nowrap",
            }}
          >
            {labs.slice(0, 2).map((lab, i) => (
              <span
                key={`${lab.display_name}-${i}`}
                style={{
                  padding: "2px 7px",
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  border: "1px solid var(--danger-border)",
                  whiteSpace: "nowrap",
                }}
              >
                {lab.display_name ?? "?"}{lab.value ? ` ${lab.value}` : ""}
                {lab.unit ? ` ${lab.unit}` : ""}
              </span>
            ))}
            {abnormalCount > 2 && (
              <span
                style={{
                  padding: "2px 7px",
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 700,
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  border: "1px solid var(--danger-border)",
                  whiteSpace: "nowrap",
                }}
              >
                +{abnormalCount - 2}
              </span>
            )}
          </span>
        )}
      </span>

      {/* Chevron */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        style={{ flexShrink: 0, color: "var(--muted)", opacity: 0.5 }}
      >
        <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

function buildLabels(language: AppLanguage) {
  if (language === "ro") {
    return {
      newRecords: "Documente noi",
      newRecord: "Document nou",
      noNewRecords: "Fără documente noi",
      activeAdmission: "Internare activă",
      abnormalUnreviewed: "Rezultate anormale nerevizuite",
      searchPlaceholder: "Caută după nume, CNP sau ID pacient...",
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
    newRecords: "new records",
    newRecord: "new record",
    noNewRecords: "No new records",
    activeAdmission: "Active admission",
    abnormalUnreviewed: "Unreviewed abnormal results",
    searchPlaceholder: "Search by name, CNP, or patient ID...",
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

  const labels = useMemo(() => buildLabels(language), [language]);

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
    return { total: patients.length, active, withNewRecords, abnormalPatients };
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
        const haystack = [
          item.patient.full_name,
          item.patient.date_of_birth,
          item.patient.age,
          item.patient.sex,
          item.patient.cnp,
          item.patient.patient_identifier,
          item.active_event?.title,
          getCareLabel(item),
          ...(item.latest_abnormal_labs ?? []).map((l) => l.display_name),
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

  if (loading || !currentUser) {
    return (
      <main
        className="app-page-bg"
        style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}
      >
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", alignItems: "center", gap: 12 }}>
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

      {/* Stat strip */}
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

      {/* Patient list */}
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
            <div className="muted-text" style={{ marginTop: 6, maxWidth: 680, lineHeight: 1.6 }}>
              {labels.helper}
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(["all", "active", "new", "abnormal", "inactive"] as FilterMode[]).map((mode) => {
              const label =
                mode === "all" ? labels.all :
                mode === "active" ? labels.active :
                mode === "new" ? labels.new :
                mode === "abnormal" ? labels.abnormal :
                labels.inactive;
              return (
                <button
                  key={mode}
                  type="button"
                  className={filterMode === mode ? "primary-btn" : "secondary-btn"}
                  onClick={() => setFilterMode(mode)}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <input
            className="text-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={labels.searchPlaceholder}
          />
        </div>

        {/* Dense row list */}
        <div style={{ borderTop: "1px solid var(--border)" }}>
          {filteredPatients.map((item) => (
            <PatientRow
              key={item.patient.id}
              item={item}
              labels={labels}
              language={language}
              onClick={() => router.push(`/patients/${item.patient.id}`)}
            />
          ))}

          {!filteredPatients.length && (
            <div style={{ padding: "32px 0", textAlign: "center" }}>
              <div style={{ fontWeight: 700, color: "var(--text)", marginBottom: 8 }}>
                {t("noPatientsMatch")}
              </div>
              <div className="muted-text" style={{ marginBottom: 16 }}>
                {t("noPatientsMatchDesc")}
              </div>
              <button
                type="button"
                className="primary-btn"
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
