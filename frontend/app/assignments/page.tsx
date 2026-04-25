"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type Doctor = {
  id: number;
  email: string;
  full_name: string;
  role: "doctor";
  department?: string | null;
  hospital_name?: string | null;
};

type LabInsight = {
  display_name?: string | null;
  value?: string | null;
  unit?: string | null;
  flag?: string | null;
};

type TrendPreview = {
  display_name?: string | null;
  latest_value?: string | null;
  previous_value?: string | null;
  unit?: string | null;
  direction?: "up" | "down" | "stable";
};

type AssignmentRow = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  doctors: Doctor[];
  active_event?: {
    id: number;
    title: string;
    status: string;
  } | null;
  is_unassigned: boolean;
  abnormal_count?: number;
  latest_abnormal_labs?: LabInsight[];
  trend_preview?: TrendPreview[];
};

type FilterMode = "all" | "active" | "abnormal";

function TrendArrow({ direction }: { direction?: "up" | "down" | "stable" }) {
  if (direction === "up") return <span>↑</span>;
  if (direction === "down") return <span>↓</span>;
  return <span>→</span>;
}

export default function AssignmentsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [rows, setRows] = useState<AssignmentRow[]>([]);
  const [query, setQuery] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function loadData() {
    const meResponse = await api.get<CurrentUser>("/auth/me");

    if (meResponse.data.role !== "admin") {
      router.push(meResponse.data.role === "doctor" ? "/my-patients" : "/my-records");
      return;
    }

    setCurrentUser(meResponse.data);

    const assignmentsResponse = await api.get<AssignmentRow[]>("/admin/scoped-patient-assignments");
    setRows(assignmentsResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await loadData();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadAssignments")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, []);

  async function unassign(patientId: number, doctorId: number) {
    try {
      setActionLoading(`unassign-${patientId}-${doctorId}`);
      setError("");

      await api.post("/admin/scoped-unassign-doctor", {
        patient_id: patientId,
        doctor_user_id: doctorId,
      });

      await loadData();
    } catch (err) {
      setError(getErrorMessage(err, t("failedUnassignDoctor")));
    } finally {
      setActionLoading(null);
    }
  }

  async function discharge(patientId: number) {
    try {
      setActionLoading(`discharge-${patientId}`);
      setError("");

      await api.post(`/admin/scoped-discharge/${patientId}`);
      await loadData();
    } catch (err) {
      setError(getErrorMessage(err, t("failedDischargePatient")));
    } finally {
      setActionLoading(null);
    }
  }

  const stats = useMemo(() => {
    return {
      total: rows.length,
      assigned: rows.filter((row) => row.doctors.length > 0).length,
      active: rows.filter((row) => row.active_event).length,
      abnormal: rows.filter((row) => (row.abnormal_count ?? 0) > 0).length,
    };
  }, [rows]);

  const filteredRows = useMemo(() => {
    const term = query.trim().toLowerCase();

    return rows
      .filter((row) => {
        if (filterMode === "active" && !row.active_event) return false;
        if (filterMode === "abnormal" && !(row.abnormal_count && row.abnormal_count > 0)) return false;

        if (!term) return true;

        const doctors = row.doctors.map((doctor) => doctor.full_name).join(" ");
        const abnormal = (row.latest_abnormal_labs ?? []).map((lab) => lab.display_name).join(" ");

        return [
          row.patient.full_name,
          row.patient.cnp,
          row.patient.patient_identifier,
          row.patient.date_of_birth,
          doctors,
          abnormal,
          row.active_event?.title,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(term);
      })
      .sort((a, b) => {
        if (a.active_event && !b.active_event) return -1;
        if (!a.active_event && b.active_event) return 1;

        const aAbnormal = a.abnormal_count ?? 0;
        const bAbnormal = b.abnormal_count ?? 0;

        if (aAbnormal > 0 && bAbnormal === 0) return -1;
        if (aAbnormal === 0 && bAbnormal > 0) return 1;

        return a.patient.full_name.localeCompare(b.patient.full_name);
      });
  }, [rows, query, filterMode]);

  function getFilterLabel(mode: FilterMode) {
    if (mode === "all") return t("all");
    if (mode === "active") return t("active");
    return t("abnormal");
  }

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingAssignments")}</p>
      </main>
    );
  }

  if (!currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <div className="soft-card-tight" style={{ padding: 16 }}>
          {t("couldNotLoadAdminUser")}
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("assignments")}
      subtitle={`${t("assignmentsSubtitlePrefix")} ${valueOrDash(currentUser.department)} ${t(
        "assignmentsSubtitleMiddle"
      )} ${valueOrDash(currentUser.hospital_name)}.`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/patients/search")}>
          {t("searchPatients")}
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
          <div className="stat-card-label">{t("scopedPatients")}</div>
          <div className="stat-card-value">{stats.total}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">{t("assigned")}</div>
          <div className="stat-card-value">{stats.assigned}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">{t("activeAdmissions")}</div>
          <div className="stat-card-value">{stats.active}</div>
        </div>

        <div className="stat-card stat-card-accent-orange">
          <div className="stat-card-label">{t("withAbnormalLabs")}</div>
          <div className="stat-card-value">{stats.abnormal}</div>
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
            <div className="section-title">{t("currentAssignments")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("currentAssignmentsDesc")}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {(["all", "active", "abnormal"] as FilterMode[]).map((mode) => (
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

        <div style={{ marginBottom: 18 }}>
          <input
            className="text-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchAssignmentsPlaceholder")}
          />
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {filteredRows.map((row) => {
            const abnormalCount = row.abnormal_count ?? 0;
            const abnormalLabs = row.latest_abnormal_labs ?? [];
            const trends = row.trend_preview ?? [];

            return (
              <div
                key={row.patient.id}
                className="soft-card-tight"
                style={{
                  padding: 18,
                  borderColor: abnormalCount > 0 ? "var(--danger-border)" : "var(--border)",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 16,
                    alignItems: "start",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                      {abnormalCount > 0 && (
                        <span
                          style={{
                            width: 12,
                            height: 12,
                            borderRadius: 999,
                            background: "var(--danger-text)",
                          }}
                        />
                      )}

                      <div style={{ fontWeight: 900, fontSize: 20 }}>{row.patient.full_name}</div>

                      {row.active_event && (
                        <span
                          style={{
                            display: "inline-flex",
                            padding: "6px 10px",
                            borderRadius: 999,
                            background: "var(--success-bg)",
                            color: "var(--success-text)",
                            fontWeight: 800,
                            fontSize: 12,
                          }}
                        >
                          {t("activeAdmission")}
                        </span>
                      )}

                      {abnormalCount > 0 && (
                        <span
                          style={{
                            display: "inline-flex",
                            padding: "6px 10px",
                            borderRadius: 999,
                            background: "var(--danger-bg)",
                            color: "var(--danger-text)",
                            border: "1px solid var(--danger-border)",
                            fontWeight: 900,
                            fontSize: 12,
                          }}
                        >
                          {abnormalCount} {t("abnormalCountLabel")}
                        </span>
                      )}
                    </div>

                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
                      {t("dob")} {valueOrDash(row.patient.date_of_birth)} · {t("age")}{" "}
                      {valueOrDash(row.patient.age)} · {t("sex")} {valueOrDash(row.patient.sex)}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {t("patientId")} {valueOrDash(row.patient.patient_identifier)} · {t("cnp")}{" "}
                      {valueOrDash(row.patient.cnp)}
                    </div>

                    <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
                      {row.doctors.map((doctor) => (
                        <div
                          key={doctor.id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 12,
                            padding: 12,
                            borderRadius: 16,
                            background: "var(--panel-2)",
                            border: "1px solid var(--border)",
                            flexWrap: "wrap",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 800 }}>{doctor.full_name}</div>
                            <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>
                              {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                            </div>
                          </div>

                          <button
                            className="secondary-btn"
                            onClick={() => unassign(row.patient.id, doctor.id)}
                            disabled={actionLoading === `unassign-${row.patient.id}-${doctor.id}`}
                          >
                            {actionLoading === `unassign-${row.patient.id}-${doctor.id}`
                              ? t("unassigning")
                              : t("unassign")}
                          </button>
                        </div>
                      ))}
                    </div>

                    {abnormalLabs.length > 0 && (
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14 }}>
                        {abnormalLabs.map((lab, index) => (
                          <span
                            key={`${lab.display_name}-${index}`}
                            style={{
                              display: "inline-flex",
                              padding: "7px 10px",
                              borderRadius: 999,
                              background: "var(--danger-bg)",
                              color: "var(--danger-text)",
                              border: "1px solid var(--danger-border)",
                              fontWeight: 800,
                              fontSize: 12,
                            }}
                          >
                            {valueOrDash(lab.display_name)} {valueOrDash(lab.value)}
                            {lab.unit ? ` ${lab.unit}` : ""} · {valueOrDash(lab.flag)}
                          </span>
                        ))}
                      </div>
                    )}

                    {trends.length > 0 && (
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                          gap: 10,
                          marginTop: 14,
                        }}
                      >
                        {trends.map((trend, index) => (
                          <div
                            key={`${trend.display_name}-${index}`}
                            style={{
                              padding: 12,
                              borderRadius: 16,
                              background: "var(--panel-2)",
                              border: "1px solid var(--border)",
                            }}
                          >
                            <div className="muted-text" style={{ fontSize: 12, fontWeight: 800 }}>
                              {valueOrDash(trend.display_name)}
                            </div>
                            <div style={{ marginTop: 5, fontWeight: 900 }}>
                              <TrendArrow direction={trend.direction} /> {valueOrDash(trend.latest_value)}
                              {trend.unit ? ` ${trend.unit}` : ""}
                            </div>
                            <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
                              {t("previousLabel")} {valueOrDash(trend.previous_value)}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {row.active_event && (
                      <div
                        style={{
                          marginTop: 14,
                          padding: 12,
                          borderRadius: 16,
                          background: "var(--success-bg)",
                          color: "var(--success-text)",
                          fontWeight: 800,
                        }}
                      >
                        {row.active_event.title}
                      </div>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <button
                      className="primary-btn"
                      onClick={() => router.push(`/patients/${row.patient.id}/assign`)}
                    >
                      {t("reassign")}
                    </button>

                    {row.active_event && (
                      <button
                        className="secondary-btn"
                        onClick={() => discharge(row.patient.id)}
                        disabled={actionLoading === `discharge-${row.patient.id}`}
                      >
                        {actionLoading === `discharge-${row.patient.id}` ? t("discharging") : t("discharge")}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {!filteredRows.length && !error && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{t("noAssignmentsMatch")}</div>
              <div className="muted-text" style={{ marginTop: 8 }}>
                {t("noAssignmentsMatchDesc")}
              </div>
              <button
                type="button"
                className="primary-btn"
                style={{ marginTop: 16 }}
                onClick={() => router.push("/patients/search")}
              >
                {t("searchPatients")}
              </button>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}