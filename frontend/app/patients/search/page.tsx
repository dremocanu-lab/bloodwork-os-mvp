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

function PatientIdentityBlock({ patient, labels }: { patient: SearchPatient; labels: Record<string, string> }) {
  return (
    <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.65 }}>
      <span style={{ fontWeight: 850, color: "var(--foreground)" }}>{labels.cnp}</span>{" "}
      {valueOrDash(patient.cnp)}
      <br />
      <span style={{ fontWeight: 850, color: "var(--foreground)" }}>{labels.patientId}</span>{" "}
      {valueOrDash(patient.patient_identifier)}
    </div>
  );
}

export default function SearchPatientsPage() {
  const router = useRouter();
  const { t, language } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [query, setQuery] = useState("");
  const [searchedQuery, setSearchedQuery] = useState("");
  const [patients, setPatients] = useState<SearchPatient[]>([]);
  const [adminAssignments, setAdminAssignments] = useState<AdminAssignmentRow[]>([]);

  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [requestingId, setRequestingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        search: "Caută",
        searching: "Se caută...",
        findPatient: "Caută pacient",
        findPatientDesc:
          "Caută după nume, CNP, dată de naștere sau ID pacient. Rezultatele apar ca listă pentru scanare rapidă.",
        searchPlaceholder: "Nume, CNP, dată naștere sau ID pacient...",
        results: "Rezultate",
        startWithSearch: "Începe cu o căutare",
        noPatientsShownUntilSearch: "Introdu un nume, CNP, dată de naștere sau ID pacient pentru rezultate.",
        noMatchingPatients: "Nu am găsit pacienți",
        tryAnotherPatientSearch: "Încearcă alt nume, CNP, dată de naștere sau ID.",
        onePatientFound: "1 pacient găsit",
        patientsFound: "pacienți găsiți",
        searchByNameCnpId: "Caută după nume, CNP sau ID",
        openChart: "Deschide fișa",
        requestAccess: "Cere acces",
        requesting: "Se trimite...",
        pending: "În așteptare",
        assign: "Alocă",
        reassign: "Realocă",
        patient: "Pacient",
        identifiers: "Identificatori",
        demographics: "Date pacient",
        access: "Acces",
        actions: "Acțiuni",
        cnp: "CNP",
        patientId: "ID pacient",
        accessApproved: "Acces aprobat",
        requestPending: "Cerere în așteptare",
        noAccessYet: "Fără acces",
        assignedTo: "Alocat către",
        noDoctorAssignedDepartment: "Fără medic alocat în departamentul tău",
        activeAdmissionColon: "Internare activă:",
        adminSubtitle: "Caută pacienți și gestionează alocările din spitalul și departamentul tău.",
        doctorSubtitle: "Caută pacienți, vezi CNP-ul, deschide fișele la care ai acces sau cere acces.",
        backToMyPatients: "Înapoi la pacienții mei",
      };
    }

    return {
      search: "Search",
      searching: "Searching...",
      findPatient: "Find patient",
      findPatientDesc:
        "Search by name, CNP, date of birth, or patient ID. Results are shown as a compact list for fast scanning.",
      searchPlaceholder: "Name, CNP, date of birth, or patient ID...",
      results: "Results",
      startWithSearch: "Start with a search",
      noPatientsShownUntilSearch: "Enter a name, CNP, date of birth, or patient ID to show matching patients.",
      noMatchingPatients: "No matching patients",
      tryAnotherPatientSearch: "Try another name, CNP, date of birth, or patient ID.",
      onePatientFound: "1 patient found",
      patientsFound: "patients found",
      searchByNameCnpId: "Search by name, CNP, or ID",
      openChart: "Open chart",
      requestAccess: "Request access",
      requesting: "Requesting...",
      pending: "Pending",
      assign: "Assign",
      reassign: "Reassign",
      patient: "Patient",
      identifiers: "Identifiers",
      demographics: "Demographics",
      access: "Access",
      actions: "Actions",
      cnp: "CNP",
      patientId: "Patient ID",
      accessApproved: "Access approved",
      requestPending: "Request pending",
      noAccessYet: "No access yet",
      assignedTo: "Assigned to",
      noDoctorAssignedDepartment: "No doctor assigned in your department",
      activeAdmissionColon: "Active admission:",
      adminSubtitle: "Search patients and manage assignments within your hospital and department.",
      doctorSubtitle: "Search patients, see CNP, open charts you can access, or request access.",
      backToMyPatients: "Back to my patients",
    };
  }, [language]);

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

    try {
      const response = await api.get<AdminAssignmentRow[]>("/admin/scoped-patient-assignments");
      setAdminAssignments(response.data);
    } catch {
      setAdminAssignments([]);
    }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    searchPatients(query);
  }

  async function requestAccess(patientId: number) {
    try {
      setRequestingId(patientId);
      setError("");

      await api.post("/access-requests", { patient_id: patientId });

      setPatients((current) =>
        current.map((patient) => {
          if (patient.id !== patientId) return patient;
          return { ...patient, pending_request: true };
        })
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
    if (!searchedQuery) return labels.searchByNameCnpId;
    if (patients.length === 1) return labels.onePatientFound;
    return `${patients.length} ${labels.patientsFound}`;
  }, [searchedQuery, patients.length, labels]);

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
          <span className="muted-text">{t("loadingSearch")}</span>
        </div>
      </main>
    );
  }

  const subtitle = currentUser.role === "admin" ? labels.adminSubtitle : labels.doctorSubtitle;

  return (
    <AppShell
      user={currentUser}
      title={t("searchPatients")}
      subtitle={subtitle}
      rightContent={
        currentUser.role === "doctor" ? (
          <button className="secondary-btn" onClick={() => router.push("/my-patients")}>
            {labels.backToMyPatients}
          </button>
        ) : null
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

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
          <div>
            <div className="section-title">{labels.findPatient}</div>
            <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.6 }}>
              {labels.findPatientDesc}
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
              onChange={(event) => setQuery(event.target.value)}
              placeholder={labels.searchPlaceholder}
            />

            <button
              type="submit"
              className="primary-btn"
              disabled={searching}
              style={{
                minWidth: 130,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 9,
              }}
            >
              {searching && <Spinner size={16} />}
              {searching ? labels.searching : labels.search}
            </button>
          </div>
        </form>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-end",
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          <div>
            <div className="section-title">{labels.results}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {resultLabel}
            </div>
          </div>
        </div>

        {!searchedQuery && (
          <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 900 }}>{labels.startWithSearch}</div>
            <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
              {labels.noPatientsShownUntilSearch}
            </div>
          </div>
        )}

        {searchedQuery && patients.length === 0 && (
          <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 900 }}>{labels.noMatchingPatients}</div>
            <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
              {labels.tryAnotherPatientSearch}
            </div>
          </div>
        )}

        {searchedQuery && patients.length > 0 && (
          <div
            style={{
              border: "1px solid var(--border)",
              borderRadius: 24,
              overflow: "hidden",
              background: "var(--panel)",
            }}
          >
            <div
              className="muted-text"
              style={{
                display: "grid",
                gridTemplateColumns:
                  currentUser.role === "admin"
                    ? "minmax(220px, 1.2fr) minmax(190px, 0.9fr) minmax(170px, 0.8fr) minmax(240px, 1fr) auto"
                    : "minmax(220px, 1.2fr) minmax(190px, 0.9fr) minmax(170px, 0.8fr) minmax(160px, 0.7fr) auto",
                gap: 14,
                padding: "13px 16px",
                borderBottom: "1px solid var(--border)",
                background: "var(--panel-2)",
                fontSize: 12,
                fontWeight: 950,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              <div>{labels.patient}</div>
              <div>{labels.identifiers}</div>
              <div>{labels.demographics}</div>
              <div>{labels.access}</div>
              <div style={{ textAlign: "right" }}>{labels.actions}</div>
            </div>

            <div style={{ display: "grid" }}>
              {patients.map((patient, index) => {
                const adminAssignment = adminAssignmentByPatientId.get(patient.id);
                const assignedDoctors = adminAssignment?.doctors ?? [];
                const hasScopedAssignment = assignedDoctors.length > 0;
                const activeEvent = adminAssignment?.active_event;

                return (
                  <div
                    key={patient.id}
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        currentUser.role === "admin"
                          ? "minmax(220px, 1.2fr) minmax(190px, 0.9fr) minmax(170px, 0.8fr) minmax(240px, 1fr) auto"
                          : "minmax(220px, 1.2fr) minmax(190px, 0.9fr) minmax(170px, 0.8fr) minmax(160px, 0.7fr) auto",
                      gap: 14,
                      alignItems: "center",
                      padding: 16,
                      borderBottom: index === patients.length - 1 ? "none" : "1px solid var(--border)",
                    }}
                  >
                    <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
                      <div
                        style={{
                          width: 46,
                          height: 46,
                          borderRadius: 16,
                          display: "grid",
                          placeItems: "center",
                          background: "color-mix(in srgb, var(--primary) 18%, var(--panel-2))",
                          color: "var(--primary)",
                          border: "1px solid color-mix(in srgb, var(--primary) 34%, var(--border))",
                          fontWeight: 950,
                          letterSpacing: "-0.06em",
                          flex: "0 0 auto",
                        }}
                      >
                        {getInitials(patient.full_name)}
                      </div>

                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: 950,
                            fontSize: 16,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {patient.full_name}
                        </div>

                        <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
                          {labels.patientId} {valueOrDash(patient.patient_identifier)}
                        </div>
                      </div>
                    </div>

                    <PatientIdentityBlock patient={patient} labels={labels} />

                    <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.65 }}>
                      {t("dob")} {valueOrDash(patient.date_of_birth)}
                      <br />
                      {t("age")} {valueOrDash(patient.age)} · {t("sex")} {valueOrDash(patient.sex)}
                    </div>

                    <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                      {currentUser.role === "admin" ? (
                        <>
                          {hasScopedAssignment ? (
                            assignedDoctors.slice(0, 2).map((doctor) => (
                              <span
                                key={doctor.id}
                                style={{
                                  display: "inline-flex",
                                  width: "fit-content",
                                  padding: "6px 10px",
                                  borderRadius: 999,
                                  background: "var(--success-bg)",
                                  color: "var(--success-text)",
                                  border: "1px solid var(--success-border)",
                                  fontWeight: 850,
                                  fontSize: 12,
                                }}
                              >
                                {labels.assignedTo} {doctor.full_name}
                              </span>
                            ))
                          ) : (
                            <span
                              style={{
                                display: "inline-flex",
                                width: "fit-content",
                                padding: "6px 10px",
                                borderRadius: 999,
                                background: "var(--warn-bg)",
                                color: "var(--warn-text)",
                                border: "1px solid var(--warn-border)",
                                fontWeight: 850,
                                fontSize: 12,
                              }}
                            >
                              {labels.noDoctorAssignedDepartment}
                            </span>
                          )}

                          {activeEvent && (
                            <span
                              style={{
                                display: "inline-flex",
                                width: "fit-content",
                                padding: "6px 10px",
                                borderRadius: 999,
                                background: "var(--success-bg)",
                                color: "var(--success-text)",
                                border: "1px solid var(--success-border)",
                                fontWeight: 850,
                                fontSize: 12,
                              }}
                            >
                              {labels.activeAdmissionColon} {activeEvent.title}
                            </span>
                          )}
                        </>
                      ) : (
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
                            border: patient.has_access
                              ? "1px solid var(--success-border)"
                              : patient.pending_request
                              ? "1px solid var(--warn-border)"
                              : "1px solid var(--border)",
                            fontWeight: 850,
                            fontSize: 12,
                          }}
                        >
                          {patient.has_access
                            ? labels.accessApproved
                            : patient.pending_request
                            ? labels.requestPending
                            : labels.noAccessYet}
                        </span>
                      )}
                    </div>

                    <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
                      {currentUser.role === "admin" && (
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={() => router.push(`/patients/${patient.id}/assign`)}
                        >
                          {hasScopedAssignment ? labels.reassign : labels.assign}
                        </button>
                      )}

                      {currentUser.role === "doctor" && patient.has_access && (
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={() => router.push(`/patients/${patient.id}`)}
                        >
                          {labels.openChart}
                        </button>
                      )}

                      {currentUser.role === "doctor" && !patient.has_access && !patient.pending_request && (
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => requestAccess(patient.id)}
                          disabled={requestingId === patient.id}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          {requestingId === patient.id && <Spinner size={14} />}
                          {requestingId === patient.id ? labels.requesting : labels.requestAccess}
                        </button>
                      )}

                      {currentUser.role === "doctor" && !patient.has_access && patient.pending_request && (
                        <button type="button" className="secondary-btn" disabled>
                          {labels.pending}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}