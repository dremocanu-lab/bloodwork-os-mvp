"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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

type UploadedBy = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type DocumentCard = {
  id: number;
  filename: string;
  report_name?: string | null;
  report_type?: string | null;
  lab_name?: string | null;
  sample_type?: string | null;
  referring_doctor?: string | null;
  test_date?: string | null;
  section: string;
  is_verified: boolean;
  uploaded_by?: UploadedBy | null;
};

type DoctorAccess = {
  doctor_user_id: number;
  doctor_name: string;
  doctor_email: string;
  department?: string | null;
  hospital_name?: string | null;
  granted_at: string;
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

type AccessRequest = {
  id: number;
  doctor_user_id: number;
  doctor_name?: string | null;
  doctor_email?: string | null;
  doctor_department?: string | null;
  doctor_hospital_name?: string | null;
  status: string;
  requested_at: string;
  responded_at?: string | null;
};

type MyProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  sections: {
    bloodwork: DocumentCard[];
    medications: DocumentCard[];
    scans: DocumentCard[];
    hospitalizations: DocumentCard[];
    other: DocumentCard[];
  };
  doctor_access: DoctorAccess[];
  events: PatientEvent[];
};

const SECTION_ORDER: Array<keyof MyProfileResponse["sections"]> = [
  "bloodwork",
  "medications",
  "scans",
  "hospitalizations",
  "other",
];

const SECTION_LABELS: Record<string, string> = {
  bloodwork: "Bloodwork",
  medications: "Medications",
  scans: "Scans",
  hospitalizations: "Hospitalizations",
  other: "Other",
};

export default function MyRecordsPage() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [activeSection, setActiveSection] =
    useState<keyof MyProfileResponse["sections"]>("bloodwork");

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

  const fetchProfile = async () => {
    try {
      setError("");
      const response = await api.get<MyProfileResponse>("/my/profile");
      setProfile(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load your records."));
    }
  };

  const fetchRequests = async () => {
    try {
      const response = await api.get<AccessRequest[]>("/my/access-requests");
      setRequests(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load access requests."));
    }
  };

  const respondToRequest = async (requestId: number, status: "approved" | "denied") => {
    try {
      setError("");
      await api.post(`/access-requests/${requestId}/respond`, { status });
      await Promise.all([fetchProfile(), fetchRequests()]);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to respond to request."));
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;
      if (me.role !== "patient") {
        router.push("/");
        return;
      }
      await Promise.all([fetchProfile(), fetchRequests()]);
      setLoading(false);
    };
    init();
  }, []);

  const recordsByDoctor = useMemo(() => {
    if (!profile) return [];

    const docs = SECTION_ORDER.flatMap((section) => profile.sections[section]);
    const groups = new Map<string, { label: string; docs: DocumentCard[] }>();

    docs.forEach((doc) => {
      const uploader = doc.uploaded_by;
      const key = uploader?.id ? `user-${uploader.id}` : "unknown";
      const label = uploader
        ? `${uploader.full_name}${uploader.department ? ` · ${uploader.department}` : ""}${
            uploader.hospital_name ? ` · ${uploader.hospital_name}` : ""
          }`
        : "Unknown uploader";

      if (!groups.has(key)) {
        groups.set(key, { label, docs: [] });
      }

      groups.get(key)!.docs.push(doc);
    });

    return Array.from(groups.values()).sort((a, b) => b.docs.length - a.docs.length);
  }, [profile]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading your records...</p>
      </main>
    );
  }

  const docsForSection = profile.sections[activeSection];

  return (
    <AppShell
      user={currentUser}
      title="My Records"
      subtitle={`DOB ${valueOrDash(profile.patient.date_of_birth)} · Age ${valueOrDash(
        profile.patient.age
      )} · Sex ${valueOrDash(profile.patient.sex)}`}
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
          gridTemplateColumns: "1.1fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            My Doctors
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {profile.doctor_access.map((doctor) => (
              <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 800 }}>{doctor.doctor_name}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>
                  {doctor.doctor_email}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                </div>
              </div>
            ))}

            {!profile.doctor_access.length && (
              <div className="muted-text">No doctors currently assigned.</div>
            )}
          </div>
        </div>

        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Doctor Access Requests
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {requests.map((request) => (
              <div key={request.id} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 800 }}>{valueOrDash(request.doctor_name)}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>
                  {valueOrDash(request.doctor_email)}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  {valueOrDash(request.doctor_department)} ·{" "}
                  {valueOrDash(request.doctor_hospital_name)}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  Status: {request.status}
                </div>

                {request.status === "pending" && (
                  <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                    <button
                      className="primary-btn"
                      onClick={() => respondToRequest(request.id, "approved")}
                    >
                      Approve
                    </button>
                    <button
                      className="secondary-btn"
                      onClick={() => respondToRequest(request.id, "denied")}
                    >
                      Deny
                    </button>
                  </div>
                )}
              </div>
            ))}

            {!requests.length && (
              <div className="muted-text">No doctor access requests yet.</div>
            )}
          </div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          Hospitalization Timeline
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {profile.events.map((event) => (
            <div key={event.id} className="soft-card-tight" style={{ padding: 16 }}>
              <div style={{ fontWeight: 800 }}>{event.title}</div>
              <div className="muted-text" style={{ marginTop: 4 }}>
                {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)}
              </div>
              <div className="muted-text" style={{ marginTop: 4 }}>
                {event.status === "active" ? "Active" : "Discharged"} · Doctor{" "}
                {valueOrDash(event.doctor_name)}
              </div>
              {event.description && <div style={{ marginTop: 8 }}>{event.description}</div>}
            </div>
          ))}

          {!profile.events.length && (
            <div className="muted-text">No hospitalization events recorded.</div>
          )}
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          {SECTION_ORDER.map((section) => {
            const active = activeSection === section;
            return (
              <button
                key={section}
                className={active ? "primary-btn" : "secondary-btn"}
                onClick={() => setActiveSection(section)}
              >
                {SECTION_LABELS[section]} ({profile.sections[section].length})
              </button>
            );
          })}
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {docsForSection.map((doc) => (
            <div key={doc.id} className="soft-card-tight" style={{ padding: 16 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.3fr 1fr auto",
                  gap: 16,
                  alignItems: "start",
                }}
              >
                <div>
                  <div style={{ fontWeight: 800 }}>
                    {valueOrDash(doc.report_name || doc.filename)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)}
                  </div>
                </div>

                <div>
                  <div className="muted-text" style={{ fontSize: 13 }}>
                    Uploaded by
                  </div>
                  <div style={{ marginTop: 6, fontWeight: 700 }}>
                    {valueOrDash(doc.uploaded_by?.full_name)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {valueOrDash(doc.uploaded_by?.department)} ·{" "}
                    {valueOrDash(doc.uploaded_by?.hospital_name)}
                  </div>
                </div>

                <div>
                  <div
                    style={{
                      display: "inline-flex",
                      padding: "6px 10px",
                      borderRadius: 999,
                      background: doc.is_verified ? "#ecfdf5" : "#fff7ed",
                      color: doc.is_verified ? "#047857" : "#c2410c",
                      fontSize: 12,
                      fontWeight: 800,
                    }}
                  >
                    {doc.is_verified ? "Verified" : "Unverified"}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {!docsForSection.length && (
            <div className="muted-text">No records in this section yet.</div>
          )}
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          Records Grouped By Doctor / Uploader
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {recordsByDoctor.map((group) => (
            <div key={group.label} className="soft-card-tight" style={{ padding: 18 }}>
              <div style={{ fontWeight: 800, marginBottom: 10 }}>
                {group.label} ({group.docs.length})
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                {group.docs.map((doc) => (
                  <div
                    key={doc.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 16,
                      padding: "10px 0",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700 }}>
                        {valueOrDash(doc.report_name || doc.filename)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        {SECTION_LABELS[doc.section] || doc.section} · {valueOrDash(doc.test_date)}
                      </div>
                    </div>
                    <div className="muted-text">{valueOrDash(doc.lab_name)}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {!recordsByDoctor.length && (
            <div className="muted-text">No uploaded records yet.</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}