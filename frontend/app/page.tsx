"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import AppShell from "@/components/app-shell";
import PageTabs from "@/components/page-tabs";
import StatCard from "@/components/stat-card";

type UserRole = "patient" | "doctor" | "admin";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
};

type DoctorUser = {
  id: number;
  email: string;
  full_name: string;
  role: "doctor";
};

type Assignment = {
  id: number;
  doctor_user_id: number;
  doctor_name: string | null;
  doctor_email: string | null;
  patient_id: number;
  patient_name: string | null;
  granted_by_user_id: number | null;
  granted_by_name: string | null;
  granted_at: string;
};

type Patient = {
  id: number;
  full_name: string;
  date_of_birth?: string | null;
  age: string | null;
  sex: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
  has_access?: boolean;
  pending_request?: boolean;
};

type SavedDocument = {
  id: number;
  patient_id?: number;
  filename: string;
  patient_name: string | null;
  report_name: string | null;
  test_date: string | null;
  section?: string;
  is_verified?: boolean;
};

type AccessRequestResponse = {
  id: number;
  doctor_user_id: number;
  patient_id: number;
  status: string;
  requested_at: string;
};

export default function Home() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  const [savedDocuments, setSavedDocuments] = useState<SavedDocument[]>([]);
  const [loadingDocuments, setLoadingDocuments] = useState(false);

  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(false);

  const [doctors, setDoctors] = useState<DoctorUser[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loadingDoctors, setLoadingDoctors] = useState(false);
  const [loadingAssignments, setLoadingAssignments] = useState(false);
  const [creatingAssignment, setCreatingAssignment] = useState(false);
  const [requestingAccessForPatientId, setRequestingAccessForPatientId] =
    useState<number | null>(null);
  const [selectedDoctorId, setSelectedDoctorId] = useState("");
  const [selectedAssignmentPatientId, setSelectedAssignmentPatientId] = useState("");

  const [searchQuery, setSearchQuery] = useState("");
  const [searchingPatients, setSearchingPatients] = useState(false);
  const [searchResults, setSearchResults] = useState<Patient[]>([]);

  const [activeTab, setActiveTab] = useState("overview");
  const [error, setError] = useState("");

  const isAdmin = currentUser?.role === "admin";
  const isDoctor = currentUser?.role === "doctor";
  const isPatient = currentUser?.role === "patient";

  const unverifiedCount = useMemo(
    () => savedDocuments.filter((doc) => !doc.is_verified).length,
    [savedDocuments]
  );

  const recentDocuments = useMemo(() => savedDocuments.slice(0, 8), [savedDocuments]);

  const tabs = useMemo(() => {
    if (isAdmin) {
      return [
        { key: "overview", label: "Overview" },
        { key: "patients", label: "Patients" },
        { key: "assignments", label: "Assignments" },
        { key: "recent", label: "Recent Documents" },
      ];
    }

    return [
      { key: "overview", label: "Overview" },
      { key: "patients", label: "Patients" },
      { key: "recent", label: "Recent Documents" },
    ];
  }, [isAdmin]);

  const logout = () => {
    localStorage.removeItem("access_token");
    setCurrentUser(null);
    router.push("/login");
  };

  const fetchMe = async () => {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      setCurrentUser(null);
      router.push("/login");
      return null;
    } finally {
      setAuthLoading(false);
    }
  };

  const fetchDocuments = async () => {
    try {
      setLoadingDocuments(true);
      const response = await api.get<SavedDocument[]>("/documents");
      setSavedDocuments(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to fetch documents."));
    } finally {
      setLoadingDocuments(false);
    }
  };

  const fetchPatients = async () => {
    try {
      setLoadingPatients(true);
      const response = await api.get<Patient[]>("/patients");
      setPatients(response.data);
      setSearchResults(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to fetch patients."));
    } finally {
      setLoadingPatients(false);
    }
  };

  const fetchDoctors = async () => {
    if (!isAdmin) return;

    try {
      setLoadingDoctors(true);
      const response = await api.get<DoctorUser[]>("/users/doctors");
      setDoctors(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to fetch doctors."));
    } finally {
      setLoadingDoctors(false);
    }
  };

  const fetchAssignments = async () => {
    if (!isAdmin) return;

    try {
      setLoadingAssignments(true);
      const response = await api.get<Assignment[]>("/assignments");
      setAssignments(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to fetch assignments."));
    } finally {
      setLoadingAssignments(false);
    }
  };

  const createAssignment = async () => {
    if (!selectedDoctorId || !selectedAssignmentPatientId) {
      setError("Select both a doctor and a patient.");
      return;
    }

    try {
      setCreatingAssignment(true);
      setError("");

      await api.post("/assignments", {
        doctor_user_id: Number(selectedDoctorId),
        patient_id: Number(selectedAssignmentPatientId),
      });

      setSelectedDoctorId("");
      setSelectedAssignmentPatientId("");

      await fetchAssignments();
      await fetchPatients();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create assignment."));
    } finally {
      setCreatingAssignment(false);
    }
  };

  const searchPatients = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(patients);
      return;
    }

    try {
      setSearchingPatients(true);
      setError("");
      const response = await api.get<Patient[]>(
        `/patients/search?q=${encodeURIComponent(searchQuery.trim())}`
      );
      setSearchResults(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to search patients."));
    } finally {
      setSearchingPatients(false);
    }
  };

  const requestAccess = async (patientId: number) => {
    try {
      setRequestingAccessForPatientId(patientId);
      setError("");

      await api.post<AccessRequestResponse>("/access-requests", {
        patient_id: patientId,
      });

      setSearchResults((prev) =>
        prev.map((patient) =>
          patient.id === patientId
            ? { ...patient, pending_request: true, has_access: false }
            : patient
        )
      );

      alert("Access request sent.");
    } catch (err) {
      setError(getErrorMessage(err, "Failed to request access."));
    } finally {
      setRequestingAccessForPatientId(null);
    }
  };

  useEffect(() => {
    const init = async () => {
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("access_token")
          : null;

      if (!token) {
        setAuthLoading(false);
        router.push("/login");
        return;
      }

      const me = await fetchMe();
      if (!me) return;

      if (me.role === "patient") {
        router.push("/my-records");
        return;
      }

      await Promise.all([fetchDocuments(), fetchPatients()]);

      if (me.role === "admin") {
        await Promise.all([fetchDoctors(), fetchAssignments()]);
      }
    };

    init();
  }, []);

  if (authLoading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading dashboard...</p>
      </main>
    );
  }

  if (isPatient) {
    return null;
  }

  return (
    <AppShell
      user={currentUser}
      title="Clinical Dashboard"
      subtitle="Search patients, manage access, and review workflow activity."
      rightContent={
        <>
          <button className="primary-btn" onClick={() => router.push("/unverified")}>
            Open Unverified Queue
          </button>
          <button className="secondary-btn" onClick={logout}>
            Log out
          </button>
        </>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "#fecaca",
            background: "#fef2f2",
            color: "#b91c1c",
          }}
        >
          {error}
        </div>
      )}

      <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 24 }}>
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              Patient Search
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto",
                gap: 12,
                marginBottom: 20,
                alignItems: "end",
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
                  Search by name, CNP, or patient ID
                </div>
                <input
                  className="text-input"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search..."
                />
              </div>

              <button className="primary-btn" onClick={searchPatients} disabled={searchingPatients}>
                {searchingPatients ? "Searching..." : "Search"}
              </button>

              <button
                className="secondary-btn"
                onClick={() => {
                  setSearchQuery("");
                  setSearchResults(patients);
                }}
              >
                Clear
              </button>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>CNP</th>
                    <th>Patient ID</th>
                    {isDoctor && <th>Access</th>}
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(searchQuery.trim() ? searchResults : patients).map((patient) => {
                    const doctorHasAccess = patient.has_access ?? true;
                    const pendingRequest = patient.pending_request ?? false;

                    return (
                      <tr key={patient.id}>
                        <td>{patient.full_name}</td>
                        <td>{valueOrDash(patient.cnp)}</td>
                        <td>{valueOrDash(patient.patient_identifier)}</td>

                        {isDoctor && (
                          <td>
                            {doctorHasAccess
                              ? "Approved"
                              : pendingRequest
                              ? "Pending"
                              : "Not yet granted"}
                          </td>
                        )}

                        <td>
                          {isAdmin ? (
                            <button
                              className="secondary-btn"
                              onClick={() => router.push(`/patients/${patient.id}`)}
                            >
                              Open Profile
                            </button>
                          ) : doctorHasAccess ? (
                            <button
                              className="secondary-btn"
                              onClick={() => router.push(`/patients/${patient.id}`)}
                            >
                              Open Profile
                            </button>
                          ) : pendingRequest ? (
                            <button className="secondary-btn" disabled>
                              Request Pending
                            </button>
                          ) : (
                            <button
                              className="secondary-btn"
                              onClick={() => requestAccess(patient.id)}
                              disabled={requestingAccessForPatientId === patient.id}
                            >
                              {requestingAccessForPatientId === patient.id
                                ? "Requesting..."
                                : "Request Access"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {!loadingPatients &&
                (searchQuery.trim() ? searchResults.length === 0 : patients.length === 0) && (
                  <p className="muted-text" style={{ paddingTop: 14 }}>
                    No patients found.
                  </p>
                )}
            </div>
          </div>

          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
            <StatCard label="Patients" value={patients.length} accent="violet" />
            <StatCard label="Unverified Docs" value={unverifiedCount} accent="orange" />
            <StatCard label="Recent Documents" value={savedDocuments.length} accent="blue" />

            <div
              className="soft-card"
              style={{
                padding: 22,
                background: "linear-gradient(135deg, #6d5dfc 0%, #4f46e5 100%)",
                color: "white",
                border: "none",
              }}
            >
              <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 14 }}>
                Quick Actions
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <button
                  onClick={() => router.push("/unverified")}
                  style={{
                    border: "none",
                    background: "rgba(255,255,255,0.18)",
                    color: "white",
                    borderRadius: 16,
                    padding: "12px 14px",
                    textAlign: "left",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Review unverified queue
                </button>

                <button
                  onClick={fetchDocuments}
                  disabled={loadingDocuments}
                  style={{
                    border: "none",
                    background: "rgba(255,255,255,0.12)",
                    color: "white",
                    borderRadius: 16,
                    padding: "12px 14px",
                    textAlign: "left",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Refresh activity
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "patients" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Assigned Patient Panel
          </div>

          {loadingPatients ? (
            <p className="muted-text">Loading patients...</p>
          ) : patients.length === 0 ? (
            <p className="muted-text">No patients available.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>DOB</th>
                    <th>Age</th>
                    <th>Sex</th>
                    <th>CNP</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {patients.map((patient) => (
                    <tr key={patient.id}>
                      <td>{patient.id}</td>
                      <td>{patient.full_name}</td>
                      <td>{valueOrDash(patient.date_of_birth)}</td>
                      <td>{valueOrDash(patient.age)}</td>
                      <td>{valueOrDash(patient.sex)}</td>
                      <td>{valueOrDash(patient.cnp)}</td>
                      <td>
                        <button
                          className="secondary-btn"
                          onClick={() => router.push(`/patients/${patient.id}`)}
                        >
                          Open Profile
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === "assignments" && isAdmin && (
        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 24 }}>
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              Assign Doctor to Patient
            </div>

            <div style={{ display: "grid", gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Doctor</div>
                <select
                  className="select-input"
                  value={selectedDoctorId}
                  onChange={(e) => setSelectedDoctorId(e.target.value)}
                >
                  <option value="">Select doctor</option>
                  {doctors.map((doctor) => (
                    <option key={doctor.id} value={doctor.id}>
                      {doctor.full_name} ({doctor.email})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Patient</div>
                <select
                  className="select-input"
                  value={selectedAssignmentPatientId}
                  onChange={(e) => setSelectedAssignmentPatientId(e.target.value)}
                >
                  <option value="">Select patient</option>
                  {patients.map((patient) => (
                    <option key={patient.id} value={patient.id}>
                      {patient.full_name} (ID {patient.id})
                    </option>
                  ))}
                </select>
              </div>

              <button
                className="primary-btn"
                onClick={createAssignment}
                disabled={
                  creatingAssignment ||
                  !selectedDoctorId ||
                  !selectedAssignmentPatientId
                }
              >
                {creatingAssignment ? "Assigning..." : "Create Assignment"}
              </button>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              Current Assignments
            </div>

            {loadingAssignments ? (
              <p className="muted-text">Loading assignments...</p>
            ) : assignments.length === 0 ? (
              <p className="muted-text">No assignments yet.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Doctor</th>
                      <th>Patient</th>
                      <th>Granted By</th>
                      <th>Granted At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((assignment) => (
                      <tr key={assignment.id}>
                        <td>
                          <div>{valueOrDash(assignment.doctor_name)}</div>
                          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                            {valueOrDash(assignment.doctor_email)}
                          </div>
                        </td>
                        <td>{valueOrDash(assignment.patient_name)}</td>
                        <td>{valueOrDash(assignment.granted_by_name)}</td>
                        <td>{valueOrDash(assignment.granted_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "recent" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Recent Documents
          </div>

          {loadingDocuments ? (
            <p className="muted-text">Loading documents...</p>
          ) : recentDocuments.length === 0 ? (
            <p className="muted-text">No documents yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Patient</th>
                    <th>Filename</th>
                    <th>Section</th>
                    <th>Report</th>
                    <th>Verified</th>
                  </tr>
                </thead>
                <tbody>
                  {recentDocuments.map((doc) => (
                    <tr key={doc.id}>
                      <td>{valueOrDash(doc.patient_name)}</td>
                      <td>{doc.filename}</td>
                      <td>{valueOrDash(doc.section)}</td>
                      <td>{valueOrDash(doc.report_name)}</td>
                      <td>{doc.is_verified ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </AppShell>
  );
}