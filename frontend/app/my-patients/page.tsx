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

type PatientRow = {
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
  active_event: {
    id: number;
    title: string;
    status: string;
    admitted_at: string;
    discharged_at?: string | null;
    description?: string | null;
    department?: string | null;
    hospital_name?: string | null;
  } | null;
  latest_document?: {
    id: number;
    filename: string;
    report_name?: string | null;
    test_date?: string | null;
  } | null;
};

export default function MyPatientsPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [patients, setPatients] = useState<PatientRow[]>([]);
  const [search, setSearch] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const fetchPatients = async (admittedOnly = false) => {
    try {
      setError("");
      const response = await api.get<PatientRow[]>("/my-patients", {
        params: { admitted_only: admittedOnly },
      });
      setPatients(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load patients."));
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;
      if (me.role !== "doctor") {
        router.push("/");
        return;
      }
      await fetchPatients(activeOnly);
      setLoading(false);
    };
    init();
  }, []);

  useEffect(() => {
    if (!currentUser || currentUser.role !== "doctor") return;
    fetchPatients(activeOnly);
  }, [activeOnly]);

  const filteredPatients = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return patients;
    return patients.filter((row) => {
      const haystack = [
        row.patient.full_name,
        row.patient.patient_identifier,
        row.patient.cnp,
        row.active_event?.title,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(term);
    });
  }, [patients, search]);

  const activeCount = useMemo(
    () => patients.filter((row) => row.active_event).length,
    [patients]
  );

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading patients...</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="My Patients"
      subtitle={`${valueOrDash(currentUser.department)} · ${valueOrDash(
        currentUser.hospital_name
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/")}>
          Back to Dashboard
        </button>
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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <StatCard label="Assigned Patients" value={patients.length} accent="violet" />
        <StatCard label="Currently Under Care" value={activeCount} accent="orange" />
        <StatCard label="Department" value={valueOrDash(currentUser.department)} accent="blue" />
        <StatCard label="Hospital" value={valueOrDash(currentUser.hospital_name)} accent="green" />
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.4fr auto auto",
            gap: 12,
            alignItems: "center",
          }}
        >
          <input
            className="text-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by patient, ID, CNP, or event title"
          />
          <button
            className="secondary-btn"
            onClick={() => setActiveOnly((prev) => !prev)}
          >
            {activeOnly ? "Show All Assigned" : "Show Under Care Only"}
          </button>
          <button className="secondary-btn" onClick={() => fetchPatients(activeOnly)}>
            Refresh
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gap: 18 }}>
        {filteredPatients.map((row) => (
          <div key={row.patient.id} className="soft-card" style={{ padding: 24 }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1.5fr 1fr auto",
                gap: 20,
                alignItems: "start",
              }}
            >
              <div>
                <div style={{ fontSize: 20, fontWeight: 800 }}>{row.patient.full_name}</div>
                <div className="muted-text" style={{ marginTop: 8 }}>
                  ID {valueOrDash(row.patient.patient_identifier)} · DOB{" "}
                  {valueOrDash(row.patient.date_of_birth)} · Age {valueOrDash(row.patient.age)} ·{" "}
                  Sex {valueOrDash(row.patient.sex)}
                </div>

                {row.active_event ? (
                  <div
                    style={{
                      marginTop: 14,
                      borderRadius: 16,
                      padding: 14,
                      background: "#fff7ed",
                      border: "1px solid #fed7aa",
                    }}
                  >
                    <div style={{ fontWeight: 800, color: "#9a3412" }}>
                      Active hospitalization
                    </div>
                    <div style={{ marginTop: 6, fontWeight: 700 }}>
                      {row.active_event.title}
                    </div>
                    <div className="muted-text" style={{ marginTop: 6 }}>
                      {valueOrDash(row.active_event.department)} ·{" "}
                      {valueOrDash(row.active_event.hospital_name)}
                    </div>
                    <div className="muted-text" style={{ marginTop: 6 }}>
                      Admitted {new Date(row.active_event.admitted_at).toLocaleString()}
                    </div>
                    {row.active_event.description && (
                      <div style={{ marginTop: 8 }}>{row.active_event.description}</div>
                    )}
                  </div>
                ) : (
                  <div
                    style={{
                      marginTop: 14,
                      borderRadius: 16,
                      padding: 14,
                      background: "#f9fafb",
                      border: "1px solid #e5e7eb",
                    }}
                  >
                    <div style={{ fontWeight: 700 }}>No active hospitalization under your care</div>
                  </div>
                )}
              </div>

              <div>
                <div className="muted-text" style={{ fontSize: 13 }}>Documents</div>
                <div style={{ marginTop: 8, fontWeight: 800, fontSize: 28 }}>
                  {row.document_count}
                </div>

                <div className="muted-text" style={{ fontSize: 13, marginTop: 16 }}>
                  Bloodwork
                </div>
                <div style={{ marginTop: 8, fontWeight: 800, fontSize: 28 }}>
                  {row.bloodwork_count}
                </div>

                {row.latest_document && (
                  <div style={{ marginTop: 18 }}>
                    <div className="muted-text" style={{ fontSize: 13 }}>Latest document</div>
                    <div style={{ marginTop: 6, fontWeight: 700 }}>
                      {valueOrDash(row.latest_document.report_name || row.latest_document.filename)}
                    </div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {valueOrDash(row.latest_document.test_date)}
                    </div>
                  </div>
                )}
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <button
                  className="primary-btn"
                  onClick={() => router.push(`/patients/${row.patient.id}`)}
                >
                  Open Chart
                </button>
              </div>
            </div>
          </div>
        ))}

        {!filteredPatients.length && (
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="muted-text">No patients matched your filters.</div>
          </div>
        )}
      </div>
    </AppShell>
  );
}