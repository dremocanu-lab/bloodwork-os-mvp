"use client";

/**
 * Doctor home - the care list.
 *
 * Redesigned from a stack of 68px rows with right-aligned red badge clusters
 * (which collided with the patient's name on any phone) into a real clinical
 * table: sortable columns, aligned figures, a status dot for care context and
 * a quiet abnormal-lab preview. Below 900px the same rows become list items
 * so nothing overflows and nothing is lost.
 *
 * Pattern reference: Deel / Attio person tables - avatar, name over a
 * secondary line, dot status, right-aligned counts, hover row actions.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import type { AppLanguage } from "@/lib/i18n";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";
import {
  CellPrimary,
  Column,
  DataTable,
  EmptyState,
  ErrorNote,
  FilterChip,
  LabValue,
  Metric,
  Metrics,
  Status,
  TableSkeleton,
  Toolbar,
} from "@/components/ui";
import {
  IconChevronRight,
  IconSearch,
  IconUsers,
} from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

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

/**
 * Care context drives the status dot, so the state reads without colour
 * fills. Only an active admission earns colour - routine outpatient care is
 * the common case and should stay neutral, or every row shouts.
 */
function careTone(item: PatientCard) {
  if (item.care_context === "active_admission") return "ok" as const;
  return "muted" as const;
}

function buildLabels(language: AppLanguage) {
  if (language === "ro") {
    return {
      newRecords: "documente noi",
      searchPlaceholder: "Caută după nume, CNP sau ID…",
      searchAllPatients: "Caută toți pacienții",
      totalUnderCare: "În grijă",
      patientsWithNewRecords: "Cu documente noi",
      activeAdmissions: "Internări active",
      abnormalAttention: "Cu rezultate anormale",
      all: "Toți",
      active: "Internați",
      new: "Noi",
      abnormal: "Anormale",
      inactive: "Fără internare",
      colPatient: "Pacient",
      colContext: "Context",
      colNew: "Noi",
      colAbnormal: "Rezultate anormale",
      colAdmission: "Episod",
      patients: "pacienți",
      helper:
        "Documentele noi sunt specifice medicului: în internare doar din episodul curent, în ambulatoriu documentele nerevizuite ale pacienților alocați.",
    };
  }
  return {
    newRecords: "new",
    searchPlaceholder: "Search by name, CNP, or patient ID…",
    searchAllPatients: "Search all patients",
    totalUnderCare: "Under care",
    patientsWithNewRecords: "With new records",
    activeAdmissions: "Active admissions",
    abnormalAttention: "With abnormal results",
    all: "All",
    active: "Active",
    new: "New",
    abnormal: "Abnormal",
    inactive: "No active stay",
    colPatient: "Patient",
    colContext: "Context",
    colNew: "New",
    colAbnormal: "Abnormal results",
    colAdmission: "Episode",
    patients: "patients",
    helper:
      "New records are doctor-specific: during an admission only the current stay, in outpatient care the unreviewed records of assigned patients.",
  };
}

export default function MyPatientsPage() {
  const router = useRouter();
  const { t, language } = useLanguage();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [patients, setPatients] = useState<PatientCard[]>([]);
  const [query, setQuery] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const labels = useMemo(() => buildLabels(language), [language]);

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const [meResponse, patientsResponse] = await Promise.all([
          api.get<NavUser>("/auth/me"),
          api.get<PatientCard[]>("/my-patients"),
        ]);

        if (meResponse.data.role !== "doctor") {
          router.push(getHomeByRole(meResponse.data.role));
          return;
        }

        setCurrentUser(meResponse.data);
        setPatients(patientsResponse.data);
      } catch {
        localStorage.removeItem("access_token");
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const stats = useMemo(() => {
    const active = patients.filter((item) => item.active_event).length;
    const withNewRecords = patients.filter((item) => (item.new_records_count ?? 0) > 0).length;
    const abnormalPatients = patients.filter((item) => (item.abnormal_count ?? 0) > 0).length;
    return { total: patients.length, active, withNewRecords, abnormalPatients };
  }, [patients]);

  const counts = useMemo(
    () => ({
      all: patients.length,
      active: patients.filter((p) => p.active_event).length,
      new: patients.filter((p) => (p.new_records_count ?? 0) > 0).length,
      abnormal: patients.filter((p) => (p.abnormal_count ?? 0) > 0).length,
      inactive: patients.filter((p) => !p.active_event).length,
    }),
    [patients]
  );

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
        // Clinical urgency first: active stays, then abnormal, then new.
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

  const columns: Column<PatientCard>[] = useMemo(
    () => [
      {
        key: "patient",
        header: labels.colPatient,
        sortable: true,
        sortValue: (row) => row.patient.full_name,
        render: (row) => (
          <CellPrimary
            avatar={getInitials(row.patient.full_name)}
            title={row.patient.full_name}
            sub={
              <>
                {formatPatientAge(row.patient.date_of_birth, language)}
                {row.patient.sex ? ` · ${row.patient.sex}` : ""}
                {row.patient.cnp ? ` · ${row.patient.cnp}` : ""}
              </>
            }
          />
        ),
      },
      {
        key: "context",
        header: labels.colContext,
        width: 150,
        sortable: true,
        sortValue: (row) => getCareLabel(row),
        hideBelow: 900,
        render: (row) => <Status tone={careTone(row)}>{getCareLabel(row)}</Status>,
      },
      {
        key: "episode",
        header: labels.colAdmission,
        hideBelow: 1100,
        render: (row) =>
          row.active_event?.title ? (
            <span className="b-cell-sub" style={{ color: "var(--text-2)" }}>
              {row.active_event.title}
            </span>
          ) : (
            <span className="b-range">—</span>
          ),
      },
      {
        key: "new",
        header: labels.colNew,
        numeric: true,
        width: 64,
        sortable: true,
        sortValue: (row) => row.new_records_count ?? 0,
        render: (row) => {
          const count = row.new_records_count ?? 0;
          return count > 0 ? (
            <span style={{ color: "var(--primary)", fontWeight: 600 }}>{count}</span>
          ) : (
            <span className="b-range">—</span>
          );
        },
      },
      {
        key: "abnormal",
        header: labels.colAbnormal,
        width: 300,
        sortable: true,
        sortValue: (row) => row.abnormal_count ?? 0,
        hideBelow: 900,
        render: (row) => {
          const total = row.abnormal_count ?? 0;
          const labs = row.latest_abnormal_labs ?? [];
          if (!total) return <span className="b-range">—</span>;

          return (
            <div className="b-strip" style={{ alignItems: "center", gap: "var(--s3)" }}>
              {labs.slice(0, 2).map((lab, index) => (
                <span
                  key={`${lab.display_name}-${index}`}
                  style={{ display: "inline-flex", alignItems: "baseline", gap: 4, minWidth: 0 }}
                >
                  <span className="b-cell-sub" style={{ maxWidth: 110 }}>
                    {lab.display_name ?? "—"}
                  </span>
                  <LabValue value={lab.value ?? "—"} unit={lab.unit} flag={lab.flag} />
                </span>
              ))}
              {total > 2 ? <span className="b-range">+{total - 2}</span> : null}
            </div>
          );
        },
      },
      {
        key: "go",
        header: <span className="sr-only">Open</span>,
        width: 32,
        center: true,
        render: () => <IconChevronRight size={14} className="b-list-chevron" />,
      },
    ],
    [labels, language]
  );

  const filters = (
    <>
      {(["all", "active", "new", "abnormal", "inactive"] as FilterMode[]).map((mode) => (
        <FilterChip
          key={mode}
          label={labels[mode]}
          count={counts[mode]}
          active={filterMode === mode}
          onClick={() => setFilterMode(mode)}
        />
      ))}
    </>
  );

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={6} columns={4} />
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
        <button
          type="button"
          className="b-btn b-btn-secondary"
          onClick={() => router.push("/patients/search")}
        >
          <IconSearch size={14} />
          {labels.searchAllPatients}
        </button>
      }
    >
      <div className="b-stack">
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        <Metrics>
          <Metric label={labels.totalUnderCare} value={stats.total} />
          <Metric label={labels.patientsWithNewRecords} value={stats.withNewRecords} />
          <Metric label={labels.activeAdmissions} value={stats.active} />
          <Metric
            label={labels.abnormalAttention}
            value={stats.abnormalPatients}
            tone={stats.abnormalPatients > 0 ? "alert" : undefined}
          />
        </Metrics>

        <section className="b-surface">
          <Toolbar
            search={query}
            onSearch={setQuery}
            searchPlaceholder={labels.searchPlaceholder}
            filters={filters}
            count={filteredPatients.length}
            countLabel={labels.patients}
          />

          {/* Desktop: the clinical table. */}
          <div className="only-desktop">
            <DataTable
              rows={filteredPatients}
              columns={columns}
              rowKey={(row) => row.patient.id}
              onRowClick={(row) => router.push(`/patients/${row.patient.id}`)}
              caption={t("patientList")}
              rowClassName={(row) =>
                (row.abnormal_count ?? 0) > 0
                  ? "row-alert"
                  : row.care_context === "active_admission"
                  ? "row-warn"
                  : (row.new_records_count ?? 0) > 0
                  ? "row-new"
                  : undefined
              }
              emptyState={
                <EmptyState
                  icon={<IconUsers size={17} />}
                  title={t("noPatientsMatch")}
                  description={t("noPatientsMatchDesc")}
                  actions={
                    <button
                      type="button"
                      className="b-btn b-btn-secondary"
                      onClick={() => router.push("/patients/search")}
                    >
                      {labels.searchAllPatients}
                    </button>
                  }
                />
              }
            />
          </div>

          {/* Phones: stacked rows. The abnormal preview becomes a scrollable
              strip under the name so it can never push the name out of view. */}
          <div className="only-mobile b-list">
            {filteredPatients.map((row) => {
              const abnormal = row.abnormal_count ?? 0;
              const fresh = row.new_records_count ?? 0;

              return (
                <button
                  key={row.patient.id}
                  type="button"
                  className="b-list-row"
                  onClick={() => router.push(`/patients/${row.patient.id}`)}
                >
                  <span className="b-avatar" aria-hidden="true">
                    {getInitials(row.patient.full_name)}
                  </span>

                  <span className="b-list-main">
                    <span className="b-list-title">{row.patient.full_name}</span>
                    <span className="b-list-sub">
                      {formatPatientAge(row.patient.date_of_birth, language)}
                      {row.patient.sex ? ` · ${row.patient.sex}` : ""}
                    </span>
                    <span className="b-list-sub">
                      <Status tone={careTone(row)}>{getCareLabel(row)}</Status>
                    </span>
                    {abnormal > 0 ? (
                      <span className="b-strip" style={{ marginTop: 2 }}>
                        {(row.latest_abnormal_labs ?? []).slice(0, 3).map((lab, index) => (
                          <span
                            key={`${lab.display_name}-${index}`}
                            className="b-chip b-chip-danger"
                          >
                            {lab.display_name} {lab.value}
                          </span>
                        ))}
                        {abnormal > 3 ? <span className="b-chip">+{abnormal - 3}</span> : null}
                      </span>
                    ) : null}
                  </span>

                  <span className="b-list-trail">
                    {fresh > 0 ? (
                      <span className="b-chip b-chip-brand">
                        {fresh} {labels.newRecords}
                      </span>
                    ) : null}
                    <IconChevronRight size={14} className="b-list-chevron" />
                  </span>
                </button>
              );
            })}

            {!filteredPatients.length ? (
              <EmptyState
                icon={<IconUsers size={17} />}
                title={t("noPatientsMatch")}
                description={t("noPatientsMatchDesc")}
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary"
                    onClick={() => router.push("/patients/search")}
                  >
                    {labels.searchAllPatients}
                  </button>
                }
              />
            ) : null}
          </div>
        </section>

        <p className="b-meta" style={{ maxWidth: "78ch" }}>
          {labels.helper}
        </p>
      </div>
    </AppShell>
  );
}
