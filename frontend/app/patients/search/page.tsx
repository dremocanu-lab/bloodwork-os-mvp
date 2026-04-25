"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
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

type SearchPatient = {
  id: number;
  full_name: string;
  date_of_birth?: string | null;
  age?: string | null;
  sex?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
  has_access: boolean;
  pending_request: boolean;
};

type AdminDoctor = {
  id: number;
  email: string;
  full_name: string;
  role: "doctor";
  department?: string | null;
  hospital_name?: string | null;
};

type AdminAssignmentRow = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  doctors: AdminDoctor[];
  active_event?: {
    id: number;
    title: string;
    status: string;
    department?: string | null;
    hospital_name?: string | null;
  } | null;
  is_unassigned: boolean;
};

export default function SearchPatientsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [query, setQuery] = useState("");
  const [searchedQuery, setSearchedQuery] = useState("");
  const [patients, setPatients] = useState<SearchPatient[]>([]);
  const [adminAssignments, setAdminAssignments] = useState<AdminAssignmentRow[]>([]);

  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [requestingId, setRequestingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function fetchMe() {
    const response = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(response.data);

    if (response.data.role === "patient") {
      router.push("/my-records");
    }

    return response.data;
  }

  async function fetchAdminAssignments(user: CurrentUser) {
    if (user.role !== "admin") return;

    const response = await api.get<AdminAssignmentRow[]>("/admin/scoped-patient-assignments");
    setAdminAssignments(response.data);
  }

  async function searchPatients(nextQuery: string) {
    setSearching(true);
    setError("");

    try {
      const response = await api.get<SearchPatient[]>("/patients/search", {
        params: { q: nextQuery.trim() },
      });

      setPatients(response.data);
      setSearchedQuery(nextQuery.trim());
    } catch (err) {
      setError(getErrorMessage(err, t("failedSearchPatients")));
    } finally {
      setSearching(false);
    }
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const user = await fetchMe();
        await fetchAdminAssignments(user);
      } catch {
        localStorage.removeItem("access_token");
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }

    init();
  }, []);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    searchPatients(query);
  }

  async function requestAccess(patientId: number) {
    try {
      setRequestingId(patientId);
      setError("");

      await api.post("/access-requests", { patient_id: patientId });

      setPatients((prev) =>
        prev.map((patient) =>
          patient.id === patientId ? { ...patient, pending_request: true } : patient
        )
      );
    } catch (err) {
      setError(getErrorMessage(err, t("failedRequestPatientAccess")));
    } finally {
      setRequestingId(null);
    }
  }

  const adminAssignmentByPatientId = useMemo(() => {
    const map = new Map<number, AdminAssignmentRow>();

    for (const row of adminAssignments) {
      map.set(row.patient.id, row);
    }

    return map;
  }, [adminAssignments]);

  const resultLabel = useMemo(() => {
    if (!searchedQuery) return t("searchByNameCnpId");
    if (patients.length === 1) return t("onePatientFound");
    return `${patients.length} ${t("patientsFound")}`;
  }, [searchedQuery, patients.length, t]);

  const subtitle =
    currentUser?.role === "admin"
      ? t("searchPatientsAdminSubtitle")
      : t("searchPatientsDoctorSubtitle");

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingSearch")}</p>
      </main>
    );
  }

  return (
    <AppShell user={currentUser} title={t("searchPatients")} subtitle={subtitle}>
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

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <form onSubmit={onSubmit} style={{ display: "grid", gap: 14 }}>
          <div>
            <div className="section-title">{t("findPatient")}</div>
            <div className="muted-text" style={{ marginTop: 8 }}>
              {t("findPatientDesc")}
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <input
              className="text-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("searchPatientsPlaceholder")}
            />

            <button type="submit" className="primary-btn" disabled={searching}>
              {searching ? t("searching") : t("search")}
            </button>
          </div>
        </form>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ marginBottom: 18 }}>
          <div className="section-title">{t("results")}</div>
          <div className="muted-text" style={{ marginTop: 6 }}>
            {resultLabel}
          </div>
        </div>

        {!searchedQuery && (
          <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 800 }}>{t("startWithSearch")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("noPatientsShownUntilSearch")}
            </div>
          </div>
        )}

        {searchedQuery && patients.length === 0 && (
          <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 800 }}>{t("noMatchingPatients")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("tryAnotherPatientSearch")}
            </div>
          </div>
        )}

        <div style={{ display: "grid", gap: 14 }}>
          {patients.map((patient) => {
            const adminAssignment = adminAssignmentByPatientId.get(patient.id);
            const assignedDoctors = adminAssignment?.doctors ?? [];
            const hasScopedAssignment = assignedDoctors.length > 0;
            const activeEvent = adminAssignment?.active_event;

            return (
              <div key={patient.id} className="soft-card-tight" style={{ padding: 18 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 16,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 900, fontSize: 20 }}>{patient.full_name}</div>

                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
                      {t("dob")} {valueOrDash(patient.date_of_birth)} · {t("age")}{" "}
                      {valueOrDash(patient.age)} · {t("sex")} {valueOrDash(patient.sex)}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4, lineHeight: 1.7 }}>
                      {t("patientId")} {valueOrDash(patient.patient_identifier)}
                      {currentUser.role === "admin" || patient.has_access
                        ? ` · ${t("cnp")} ${valueOrDash(patient.cnp)}`
                        : ""}
                    </div>

                    {currentUser.role === "admin" && (
                      <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
                        {hasScopedAssignment ? (
                          assignedDoctors.map((doctor) => (
                            <div
                              key={doctor.id}
                              style={{
                                display: "inline-flex",
                                width: "fit-content",
                                padding: "6px 10px",
                                borderRadius: 999,
                                background: "var(--success-bg)",
                                color: "var(--success-text)",
                                fontWeight: 800,
                                fontSize: 12,
                              }}
                            >
                              {t("assignedTo")} {doctor.full_name}
                            </div>
                          ))
                        ) : (
                          <div
                            style={{
                              display: "inline-flex",
                              width: "fit-content",
                              padding: "6px 10px",
                              borderRadius: 999,
                              background: "var(--warn-bg)",
                              color: "var(--warn-text)",
                              fontWeight: 800,
                              fontSize: 12,
                            }}
                          >
                            {t("noDoctorAssignedDepartment")}
                          </div>
                        )}

                        {activeEvent && (
                          <div
                            style={{
                              display: "inline-flex",
                              width: "fit-content",
                              padding: "6px 10px",
                              borderRadius: 999,
                              background: "var(--success-bg)",
                              color: "var(--success-text)",
                              fontWeight: 800,
                              fontSize: 12,
                            }}
                          >
                            {t("activeAdmissionColon")} {activeEvent.title}
                          </div>
                        )}
                      </div>
                    )}

                    {currentUser.role === "doctor" && (
                      <div style={{ marginTop: 12 }}>
                        <span
                          style={{
                            display: "inline-flex",
                            padding: "6px 10px",
                            borderRadius: 999,
                            background: patient.has_access
                              ? "var(--success-bg)"
                              : patient.pending_request
                              ? "var(--warn-bg)"
                              : "var(--panel-2)",
                            color: patient.has_access
                              ? "var(--success-text)"
                              : patient.pending_request
                              ? "var(--warn-text)"
                              : "var(--muted)",
                            fontWeight: 800,
                            fontSize: 12,
                          }}
                        >
                          {patient.has_access
                            ? t("accessApproved")
                            : patient.pending_request
                            ? t("requestPending")
                            : t("noAccessYet")}
                        </span>
                      </div>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    {currentUser.role === "admin" && (
                      <button
                        type="button"
                        className="primary-btn"
                        onClick={() => router.push(`/patients/${patient.id}/assign`)}
                      >
                        {hasScopedAssignment ? t("reassign") : t("assign")}
                      </button>
                    )}

                    {currentUser.role === "doctor" && patient.has_access && (
                      <button
                        type="button"
                        className="primary-btn"
                        onClick={() => router.push(`/patients/${patient.id}`)}
                      >
                        {t("openChart")}
                      </button>
                    )}

                    {currentUser.role === "doctor" && !patient.has_access && !patient.pending_request && (
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() => requestAccess(patient.id)}
                        disabled={requestingId === patient.id}
                      >
                        {requestingId === patient.id ? t("requesting") : t("requestAccess")}
                      </button>
                    )}

                    {currentUser.role === "doctor" && !patient.has_access && patient.pending_request && (
                      <button type="button" className="secondary-btn" disabled>
                        {t("pending")}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}