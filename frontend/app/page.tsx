"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import StatCard from "@/components/stat-card";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type PatientSearchResult = {
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

type DoctorUser = {
  id: number;
  email: string;
  full_name: string;
  role: "doctor";
  department?: string | null;
  hospital_name?: string | null;
};

type Assignment = {
  id: number;
  doctor_user_id: number;
  doctor_name: string | null;
  doctor_email: string | null;
  doctor_department?: string | null;
  doctor_hospital_name?: string | null;
  patient_id: number;
  patient_name: string | null;
  granted_at: string;
};

type MyPatientSummary = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  document_count: number;
  bloodwork_count: number;
  active_event?: {
    id: number;
    patient_id: number;
    doctor_user_id: number;
    event_type: string;
    status: string;
    title: string;
    description?: string | null;
    hospital_name?: string | null;
    department?: string | null;
    admitted_at: string;
    discharged_at?: string | null;
    doctor_name?: string | null;
  } | null;
  latest_document?: {
    id: number;
    filename: string;
    content_type?: string | null;
    report_name?: string | null;
    report_type?: string | null;
    lab_name?: string | null;
    sample_type?: string | null;
    referring_doctor?: string | null;
    test_date?: string | null;
    section: string;
    is_verified: boolean;
  } | null;
};

type TrendPoint = {
  document_id: number;
  date: string;
  value: number;
  value_display: string;
  flag?: string | null;
  report_name?: string | null;
  reference_range?: string | null;
};

type BloodworkTrend = {
  test_key: string;
  display_name: string;
  canonical_name?: string | null;
  category?: string | null;
  unit?: string | null;
  latest: TrendPoint;
  previous?: TrendPoint | null;
  delta?: number | null;
  points: TrendPoint[];
};

function parseFlexibleDate(value?: string | null): Date | null {
  if (!value) return null;

  const trimmed = value.trim();

  const direct = new Date(trimmed);
  if (!Number.isNaN(direct.getTime())) return direct;

  const isoMatch = trimmed.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    const [, year, month, day] = isoMatch;
    const d = new Date(Number(year), Number(month) - 1, Number(day));
    if (!Number.isNaN(d.getTime())) return d;
  }

  const euroMatch = trimmed.match(/(\d{2})[\/.-](\d{2})[\/.-](\d{4})/);
  if (euroMatch) {
    const [, day, month, year] = euroMatch;
    const d = new Date(Number(year), Number(month) - 1, Number(day));
    if (!Number.isNaN(d.getTime())) return d;
  }

  return null;
}

function isWithinLastDays(value?: string | null, days = 7): boolean {
  const date = parseFlexibleDate(value);
  if (!date) return false;

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  return diffDays >= 0 && diffDays <= days;
}

export default function DashboardPage() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [patientSearch, setPatientSearch] = useState("");
  const [patientResults, setPatientResults] = useState<PatientSearchResult[]>([]);
  const [hasSearchedPatients, setHasSearchedPatients] = useState(false);
  const [searchingPatients, setSearchingPatients] = useState(false);

  const [doctorSearch, setDoctorSearch] = useState("");
  const [doctorResults, setDoctorResults] = useState<DoctorUser[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);

  const [selectedDoctorId, setSelectedDoctorId] = useState<number | null>(null);
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [assigning, setAssigning] = useState(false);

  const [doctorPatients, setDoctorPatients] = useState<MyPatientSummary[]>([]);
  const [doctorMetricsLoading, setDoctorMetricsLoading] = useState(false);
  const [patientsWithNewResults, setPatientsWithNewResults] = useState(0);
  const [abnormalResultsToReview, setAbnormalResultsToReview] = useState(0);

  const fetchMe = async () => {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  };

  const searchPatients = async (query = "") => {
    try {
      setSearchingPatients(true);
      setError("");
      const response = await api.get<PatientSearchResult[]>("/patients/search", {
        params: { q: query },
      });
      setPatientResults(response.data);
      setHasSearchedPatients(true);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to search patients."));
    } finally {
      setSearchingPatients(false);
    }
  };

  const searchDoctors = async (query = "") => {
    try {
      setError("");
      const response = await api.get<DoctorUser[]>("/users/doctors/search", {
        params: { q: query },
      });
      setDoctorResults(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to search doctors."));
    }
  };

  const fetchAssignments = async () => {
    try {
      setError("");
      const response = await api.get<Assignment[]>("/assignments");
      setAssignments(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load assignments."));
    }
  };

  const requestAccess = async (patientId: number) => {
    try {
      setError("");
      await api.post("/access-requests", { patient_id: patientId });
      await searchPatients(patientSearch.trim());
    } catch (err) {
      setError(getErrorMessage(err, "Failed to request access."));
    }
  };

  const fetchDoctorDashboardData = async () => {
    try {
      setDoctorMetricsLoading(true);
      setError("");

      const patientResponse = await api.get<MyPatientSummary[]>("/my-patients", {
        params: { admitted_only: false },
      });

      const myPatients = patientResponse.data;
      setDoctorPatients(myPatients);

      const newResultsCount = myPatients.filter((entry) =>
        isWithinLastDays(entry.latest_document?.test_date, 7)
      ).length;
      setPatientsWithNewResults(newResultsCount);

      const abnormalFlagsByPatient = await Promise.all(
        myPatients.map(async (entry) => {
          try {
            const trendResponse = await api.get<BloodworkTrend[]>(
              `/patients/${entry.patient.id}/bloodwork-trends`
            );

            const hasAbnormalLatest = trendResponse.data.some((trend) => {
              const flag = String(trend.latest?.flag || "").toLowerCase();
              return flag === "high" || flag === "low";
            });

            return hasAbnormalLatest;
          } catch {
            return false;
          }
        })
      );

      setAbnormalResultsToReview(abnormalFlagsByPatient.filter(Boolean).length);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load doctor dashboard data."));
    } finally {
      setDoctorMetricsLoading(false);
    }
  };

  const createAssignment = async () => {
    if (!selectedDoctorId || !selectedPatientId) {
      setError("Select one doctor and one patient first.");
      return;
    }

    try {
      setAssigning(true);
      setError("");
      await api.post("/assignments", {
        doctor_user_id: selectedDoctorId,
        patient_id: selectedPatientId,
      });

      await Promise.all([
        fetchAssignments(),
        searchDoctors(doctorSearch.trim()),
        searchPatients(patientSearch.trim()),
      ]);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create assignment."));
    } finally {
      setAssigning(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");

        if (me.role === "patient") {
          router.push("/my-records");
          return;
        }

        if (me.role === "doctor") {
          setPatientResults([]);
          setHasSearchedPatients(false);
          await fetchDoctorDashboardData();
        }

        if (me.role === "admin") {
          setPatientResults([]);
          setHasSearchedPatients(false);
          await Promise.all([searchDoctors(""), fetchAssignments()]);
        }
      } finally {
        setLoading(false);
      }
    };

    init();
  }, []);

  const selectedDoctor = useMemo(
    () => doctorResults.find((doctor) => doctor.id === selectedDoctorId) || null,
    [doctorResults, selectedDoctorId]
  );

  const selectedPatient = useMemo(
    () => patientResults.find((patient) => patient.id === selectedPatientId) || null,
    [patientResults, selectedPatientId]
  );

  const doctorMetricCards = useMemo(() => {
    const totalPatients = doctorPatients.length;
    const admittedNow = doctorPatients.filter((entry) => !!entry.active_event).length;

    return [
      {
        label: "My Patients",
        value: doctorMetricsLoading ? "..." : totalPatients,
        accent: "violet" as const,
      },
      {
        label: "Admitted Now",
        value: doctorMetricsLoading ? "..." : admittedNow,
        accent: "blue" as const,
      },
      {
        label: "Patients With New Results",
        value: doctorMetricsLoading ? "..." : patientsWithNewResults,
        accent: "green" as const,
      },
      {
        label: "Abnormal Results To Review",
        value: doctorMetricsLoading ? "..." : abnormalResultsToReview,
        accent: "orange" as const,
      },
    ];
  }, [doctorPatients, doctorMetricsLoading, patientsWithNewResults, abnormalResultsToReview]);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading workspace...</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="Dashboard"
      subtitle={
        currentUser.role === "doctor"
          ? `${valueOrDash(currentUser.department)} · ${valueOrDash(currentUser.hospital_name)}`
          : "Clinical operations overview"
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

      {currentUser.role === "doctor" && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 16,
              marginBottom: 24,
            }}
          >
            {doctorMetricCards.map((card) => (
              <StatCard
                key={card.label}
                label={card.label}
                value={card.value}
                accent={card.accent}
              />
            ))}
          </div>

          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>Find patients</div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto",
                gap: 12,
                alignItems: "center",
              }}
            >
              <input
                className="text-input"
                value={patientSearch}
                onChange={(e) => setPatientSearch(e.target.value)}
                placeholder="Search by patient name, CNP, or patient ID"
              />

              <button
                className="primary-btn"
                onClick={() => searchPatients(patientSearch.trim())}
                disabled={searchingPatients}
              >
                {searchingPatients ? "Searching..." : "Search"}
              </button>

              <button className="secondary-btn" onClick={() => router.push("/my-patients")}>
                Open My Patients
              </button>
            </div>
          </div>

          {hasSearchedPatients && (
            <div style={{ display: "grid", gap: 16 }}>
              {patientResults.map((patient) => (
                <div key={patient.id} className="soft-card" style={{ padding: 24 }}>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.4fr auto",
                      gap: 20,
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 20, fontWeight: 800 }}>{patient.full_name}</div>
                      <div className="muted-text" style={{ marginTop: 8 }}>
                        ID {valueOrDash(patient.patient_identifier)} · DOB{" "}
                        {valueOrDash(patient.date_of_birth)} · Age {valueOrDash(patient.age)} · Sex{" "}
                        {valueOrDash(patient.sex)}
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 10 }}>
                      {patient.has_access ? (
                        <button
                          className="primary-btn"
                          onClick={() => router.push(`/patients/${patient.id}`)}
                        >
                          Open Chart
                        </button>
                      ) : patient.pending_request ? (
                        <button className="secondary-btn" disabled>
                          Request Pending
                        </button>
                      ) : (
                        <button
                          className="secondary-btn"
                          onClick={() => requestAccess(patient.id)}
                        >
                          Request Access
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {!patientResults.length && (
                <div className="soft-card" style={{ padding: 24 }}>
                  <div className="muted-text">No patients found.</div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {currentUser.role === "admin" && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 16,
              marginBottom: 24,
            }}
          >
            <StatCard label="Doctors Found" value={doctorResults.length} accent="blue" />
            <StatCard label="Assignments" value={assignments.length} accent="violet" />
            <StatCard label="Selected Doctor" value={selectedDoctor ? 1 : 0} accent="green" />
            <StatCard label="Selected Patient" value={selectedPatient ? 1 : 0} accent="orange" />
          </div>

          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>Assignment workspace</div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr auto",
                gap: 12,
                alignItems: "center",
                marginBottom: 16,
              }}
            >
              <input
                className="text-input"
                value={doctorSearch}
                onChange={(e) => setDoctorSearch(e.target.value)}
                placeholder="Search doctors by name, email, department, or hospital"
              />

              <input
                className="text-input"
                value={patientSearch}
                onChange={(e) => setPatientSearch(e.target.value)}
                placeholder="Search patients by name, CNP, or patient ID"
              />

              <button
                className="secondary-btn"
                onClick={() =>
                  Promise.all([
                    searchDoctors(doctorSearch.trim()),
                    searchPatients(patientSearch.trim()),
                    fetchAssignments(),
                  ])
                }
              >
                Refresh
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 18,
                marginBottom: 18,
              }}
            >
              <div>
                <div className="muted-text" style={{ marginBottom: 10, fontWeight: 700 }}>
                  Doctors
                </div>
                <div style={{ display: "grid", gap: 10, maxHeight: 320, overflowY: "auto" }}>
                  {doctorResults.map((doctor) => (
                    <button
                      key={doctor.id}
                      className="soft-card-tight"
                      onClick={() => setSelectedDoctorId(doctor.id)}
                      style={{
                        padding: 14,
                        textAlign: "left",
                        border:
                          selectedDoctorId === doctor.id
                            ? "2px solid #6d5dfc"
                            : "1px solid var(--border)",
                        background:
                          selectedDoctorId === doctor.id
                            ? "var(--primary-soft)"
                            : "var(--panel)",
                      }}
                    >
                      <div style={{ fontWeight: 800 }}>{doctor.full_name}</div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        {doctor.email}
                      </div>
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="muted-text" style={{ marginBottom: 10, fontWeight: 700 }}>
                  Patients
                </div>
                <div style={{ display: "grid", gap: 10, maxHeight: 320, overflowY: "auto" }}>
                  {patientResults.map((patient) => (
                    <button
                      key={patient.id}
                      className="soft-card-tight"
                      onClick={() => setSelectedPatientId(patient.id)}
                      style={{
                        padding: 14,
                        textAlign: "left",
                        border:
                          selectedPatientId === patient.id
                            ? "2px solid #6d5dfc"
                            : "1px solid var(--border)",
                        background:
                          selectedPatientId === patient.id
                            ? "var(--primary-soft)"
                            : "var(--panel)",
                      }}
                    >
                      <div style={{ fontWeight: 800 }}>{patient.full_name}</div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        ID {valueOrDash(patient.patient_identifier)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        DOB {valueOrDash(patient.date_of_birth)} · Age {valueOrDash(patient.age)} · Sex{" "}
                        {valueOrDash(patient.sex)}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div
              className="soft-card-tight"
              style={{ padding: 16, marginBottom: 16, background: "var(--panel)" }}
            >
              <div style={{ fontWeight: 700 }}>Selected pairing</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Doctor: {selectedDoctor ? selectedDoctor.full_name : "—"} | Patient:{" "}
                {selectedPatient ? selectedPatient.full_name : "—"}
              </div>
            </div>

            <button className="primary-btn" onClick={createAssignment} disabled={assigning}>
              {assigning ? "Assigning..." : "Assign Doctor to Patient"}
            </button>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>Current assignments</div>

            <div style={{ display: "grid", gap: 12 }}>
              {assignments.map((assignment) => (
                <div key={assignment.id} className="soft-card-tight" style={{ padding: 16 }}>
                  <div style={{ fontWeight: 800 }}>
                    {valueOrDash(assignment.doctor_name)} → {valueOrDash(assignment.patient_name)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    {valueOrDash(assignment.doctor_department)} ·{" "}
                    {valueOrDash(assignment.doctor_hospital_name)}
                  </div>
                </div>
              ))}

              {!assignments.length && (
                <div className="muted-text">No assignments yet.</div>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}