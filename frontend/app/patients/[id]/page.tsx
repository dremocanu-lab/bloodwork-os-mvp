"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

type DoctorAccess = {
  doctor_user_id: number;
  doctor_name: string;
  doctor_email: string;
  department?: string | null;
  hospital_name?: string | null;
  granted_at: string;
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
  content_type?: string | null;
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

const SECTION_ORDER: Array<keyof PatientProfileResponse["sections"]> = [
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

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [activeSection, setActiveSection] =
    useState<keyof PatientProfileResponse["sections"]>("bloodwork");

  const [eventTitle, setEventTitle] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [creatingEvent, setCreatingEvent] = useState(false);

  const [uploadSection, setUploadSection] =
    useState<keyof PatientProfileResponse["sections"]>("bloodwork");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);

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
      const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
      setProfile(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load patient chart."));
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;
      await fetchProfile();
      setLoading(false);
    };
    init();
  }, [patientId]);

  const createEvent = async () => {
    if (!eventTitle.trim()) {
      setError("Event title is required.");
      return;
    }

    try {
      setCreatingEvent(true);
      setError("");
      await api.post(`/patients/${patientId}/events`, {
        event_type: "hospitalization",
        title: eventTitle,
        description: eventDescription || null,
      });
      setEventTitle("");
      setEventDescription("");
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create event."));
    } finally {
      setCreatingEvent(false);
    }
  };

  const dischargeEvent = async (eventId: number) => {
    try {
      setError("");
      await api.post(`/patient-events/${eventId}/discharge`);
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to discharge event."));
    }
  };

  const uploadDocument = async () => {
    if (!uploadFile) {
      setError("Choose a file first.");
      return;
    }

    try {
      setUploading(true);
      setError("");

      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("patient_id", String(patientId));
      formData.append("section", uploadSection);

      await api.post("/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadFile(null);
      if (hiddenFileInputRef.current) hiddenFileInputRef.current.value = "";
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to upload document."));
    } finally {
      setUploading(false);
    }
  };

  const openOriginal = (documentId: number) => {
    window.open(`${API_URL}/documents/${documentId}/file`, "_blank");
  };

  const doctorDocumentGroups = useMemo(() => {
    if (!profile) return [];

    const allDocs = SECTION_ORDER.flatMap((section) => profile.sections[section]);
    const groups = new Map<string, { label: string; docs: DocumentCard[] }>();

    allDocs.forEach((doc) => {
      const uploader = doc.uploaded_by;
      const key = uploader?.id ? `user-${uploader.id}` : "unknown";

      const label = uploader
        ? `${uploader.full_name}${uploader.department ? ` · ${uploader.department}` : ""}${
            uploader.hospital_name ? ` · ${uploader.hospital_name}` : ""
          }`
        : "Unknown uploader";

      if (!groups.has(key)) groups.set(key, { label, docs: [] });
      groups.get(key)!.docs.push(doc);
    });

    return Array.from(groups.values()).sort((a, b) => b.docs.length - a.docs.length);
  }, [profile]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading patient chart...</p>
      </main>
    );
  }

  const docsForSection = profile.sections[activeSection];
  const canUpload = currentUser.role === "doctor" || currentUser.role === "admin";
  const canManageEvents = currentUser.role === "doctor";

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`ID ${valueOrDash(profile.patient.patient_identifier)} · DOB ${valueOrDash(
        profile.patient.date_of_birth
      )} · Age ${valueOrDash(profile.patient.age)} · Sex ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.back()}>
          Back
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
          gridTemplateColumns: "1.2fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Assigned Doctors
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
            Hospitalization Events
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {profile.events.map((event) => (
              <div key={event.id} className="soft-card-tight" style={{ padding: 16 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    alignItems: "start",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 800 }}>{event.title}</div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)}
                    </div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {event.status === "active" ? "Admitted" : "Discharged"} · Doctor{" "}
                      {valueOrDash(event.doctor_name)}
                    </div>
                    {event.description && <div style={{ marginTop: 8 }}>{event.description}</div>}
                  </div>

                  {canManageEvents && event.status === "active" && (
                    <button
                      className="secondary-btn"
                      onClick={() => dischargeEvent(event.id)}
                    >
                      Discharge
                    </button>
                  )}
                </div>
              </div>
            ))}

            {!profile.events.length && (
              <div className="muted-text">No events recorded yet.</div>
            )}
          </div>
        </div>
      </div>

      {canManageEvents && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Add Hospitalization Event
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            <input
              className="text-input"
              value={eventTitle}
              onChange={(e) => setEventTitle(e.target.value)}
              placeholder="Title, for example: Post-op monitoring"
            />
            <textarea
              className="text-input"
              value={eventDescription}
              onChange={(e) => setEventDescription(e.target.value)}
              placeholder="Description / care notes"
              rows={4}
            />
            <div>
              <button className="primary-btn" onClick={createEvent} disabled={creatingEvent}>
                {creatingEvent ? "Creating..." : "Create Event"}
              </button>
            </div>
          </div>
        </div>
      )}

      {canUpload && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Upload Record
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "220px 1fr auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <select
              className="text-input"
              value={uploadSection}
              onChange={(e) =>
                setUploadSection(e.target.value as keyof PatientProfileResponse["sections"])
              }
            >
              {SECTION_ORDER.map((section) => (
                <option key={section} value={section}>
                  {SECTION_LABELS[section]}
                </option>
              ))}
            </select>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                border: "1px solid var(--border)",
                borderRadius: 18,
                padding: "12px 14px",
                background: "white",
                minHeight: 58,
              }}
            >
              <input
                ref={hiddenFileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
              <button
                type="button"
                className="secondary-btn"
                onClick={() => hiddenFileInputRef.current?.click()}
              >
                Choose File
              </button>
              <div
                className="muted-text"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {uploadFile ? uploadFile.name : "No file selected"}
              </div>
            </div>

            <button className="primary-btn" onClick={uploadDocument} disabled={uploading}>
              {uploading ? "Uploading..." : "Upload"}
            </button>
          </div>
        </div>
      )}

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
            <div key={doc.id} className="soft-card-tight" style={{ padding: 18 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.25fr 1fr auto",
                  gap: 18,
                  alignItems: "start",
                }}
              >
                <div>
                  <div style={{ fontWeight: 800, fontSize: 18 }}>
                    {valueOrDash(doc.report_name || doc.filename)}
                  </div>

                  <div style={{ marginTop: 8 }}>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "5px 10px",
                        borderRadius: 999,
                        background: doc.is_verified ? "#ecfdf5" : "#fff7ed",
                        color: doc.is_verified ? "#047857" : "#c2410c",
                        fontSize: 12,
                        fontWeight: 800,
                      }}
                    >
                      {doc.is_verified ? "Verified" : "Unverified"}
                    </span>
                  </div>

                  <div className="muted-text" style={{ marginTop: 10 }}>
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

                <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                  <button className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                    Open File
                  </button>
                  <button
                    className="primary-btn"
                    onClick={() => router.push(`/documents/${doc.id}`)}
                  >
                    Structured View
                  </button>
                </div>
              </div>
            </div>
          ))}

          {!docsForSection.length && (
            <div className="muted-text">No documents in this section yet.</div>
          )}
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          Records By Uploader
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {doctorDocumentGroups.map((group) => (
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
                    <button className="secondary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                      View Structured Data
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {!doctorDocumentGroups.length && (
            <div className="muted-text">No uploaded records yet.</div>
          )}
        </div>
      </div>
    </AppShell>
  );
}