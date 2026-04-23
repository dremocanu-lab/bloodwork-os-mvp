"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type PatientEvent = {
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
};

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
};

export default function PatientHospitalizationsPage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [patient, setPatient] = useState<PatientProfileResponse["patient"] | null>(null);
  const [events, setEvents] = useState<PatientEvent[]>([]);
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

  const fetchData = async () => {
    const [profileResponse, eventsResponse] = await Promise.all([
      api.get(`/patients/${patientId}/profile`),
      api.get<PatientEvent[]>(`/patients/${patientId}/events`),
    ]);

    setPatient(profileResponse.data.patient);
    setEvents(eventsResponse.data);
  };

  const dischargeEvent = async (eventId: number) => {
    try {
      setError("");
      await api.post(`/patient-events/${eventId}/discharge`);
      await fetchData();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to discharge patient."));
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load hospitalizations."));
      } finally {
        setLoading(false);
      }
    };

    init();
  }, [patientId]);

  if (loading || !currentUser || !patient) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading hospitalizations...</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="All Hospitalizations"
      subtitle={`${patient.full_name} · ID ${valueOrDash(patient.patient_identifier)}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          Back to Chart
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

      <div style={{ display: "grid", gap: 16 }}>
        {events.map((event) => (
          <div key={event.id} className="soft-card" style={{ padding: 24 }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1.25fr auto",
                gap: 18,
                alignItems: "start",
              }}
            >
              <div>
                <div style={{ fontWeight: 800, fontSize: 20 }}>{event.title}</div>

                <div className="muted-text" style={{ marginTop: 8 }}>
                  {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)}
                </div>

                <div className="muted-text" style={{ marginTop: 6 }}>
                  Status: {event.status === "active" ? "Admitted" : "Discharged"} · Doctor{" "}
                  {valueOrDash(event.doctor_name)}
                </div>

                <div className="muted-text" style={{ marginTop: 6 }}>
                  Admitted: {valueOrDash(event.admitted_at)}
                </div>

                {event.discharged_at && (
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    Discharged: {valueOrDash(event.discharged_at)}
                  </div>
                )}

                {event.description && <div style={{ marginTop: 12 }}>{event.description}</div>}
              </div>

              {currentUser.role === "doctor" && event.status === "active" && (
                <button className="secondary-btn" onClick={() => dischargeEvent(event.id)}>
                  Discharge
                </button>
              )}
            </div>
          </div>
        ))}

        {!events.length && (
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="muted-text">No hospitalizations recorded for this patient yet.</div>
          </div>
        )}
      </div>
    </AppShell>
  );
}