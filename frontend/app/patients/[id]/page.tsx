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
  note_preview?: string | null;
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
    notes: DocumentCard[];
    bloodwork: DocumentCard[];
    medications: DocumentCard[];
    scans: DocumentCard[];
    hospitalizations: DocumentCard[];
    other: DocumentCard[];
  };
  doctor_access: DoctorAccess[];
  events: PatientEvent[];
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

const SECTION_ORDER = [
  "notes",
  "bloodwork",
  "medications",
  "scans",
  "hospitalizations",
  "other",
  "all_documents",
] as const;

type SectionKey = (typeof SECTION_ORDER)[number];

const SECTION_LABELS: Record<SectionKey, string> = {
  notes: "Notes",
  bloodwork: "Bloodwork",
  medications: "Medications",
  scans: "Scans",
  hospitalizations: "Hospitalizations",
  other: "Other",
  all_documents: "All Documents",
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";

function TrendSparkline({ points }: { points: TrendPoint[] }) {
  if (!points.length) return null;

  const width = 720;
  const height = 260;
  const paddingLeft = 70;
  const paddingRight = 30;
  const paddingTop = 24;
  const paddingBottom = 54;

  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;

  const values = points.map((p) => p.value);
  const minRaw = Math.min(...values);
  const maxRaw = Math.max(...values);
  const paddingValue = Math.max((maxRaw - minRaw) * 0.15, 1);
  const min = minRaw - paddingValue;
  const max = maxRaw + paddingValue;
  const range = max - min || 1;

  const xFor = (index: number) =>
    paddingLeft + (index * plotWidth) / Math.max(points.length - 1, 1);

  const yFor = (value: number) =>
    paddingTop + (1 - (value - min) / range) * plotHeight;

  const polyline = points.map((p, index) => `${xFor(index)},${yFor(p.value)}`).join(" ");

  const yTicks = 4;
  const xTicks = points.map((p, index) => ({
    x: xFor(index),
    label: String(p.date).slice(0, 10),
  }));

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <line x1={paddingLeft} y1={paddingTop} x2={paddingLeft} y2={paddingTop + plotHeight} stroke="currentColor" opacity="0.25" />
      <line
        x1={paddingLeft}
        y1={paddingTop + plotHeight}
        x2={paddingLeft + plotWidth}
        y2={paddingTop + plotHeight}
        stroke="currentColor"
        opacity="0.25"
      />

      {Array.from({ length: yTicks + 1 }).map((_, i) => {
        const value = min + ((max - min) * (yTicks - i)) / yTicks;
        const y = paddingTop + (plotHeight * i) / yTicks;
        return (
          <g key={i}>
            <line
              x1={paddingLeft}
              y1={y}
              x2={paddingLeft + plotWidth}
              y2={y}
              stroke="currentColor"
              opacity="0.08"
            />
            <text x={paddingLeft - 12} y={y + 4} textAnchor="end" fontSize="12" fill="currentColor" opacity="0.7">
              {Number(value).toFixed(1)}
            </text>
          </g>
        );
      })}

      {xTicks.map((tick, i) => (
        <g key={i}>
          <line
            x1={tick.x}
            y1={paddingTop + plotHeight}
            x2={tick.x}
            y2={paddingTop + plotHeight + 6}
            stroke="currentColor"
            opacity="0.25"
          />
          <text x={tick.x} y={paddingTop + plotHeight + 22} textAnchor="middle" fontSize="12" fill="currentColor" opacity="0.7">
            {tick.label}
          </text>
        </g>
      ))}

      <text x={paddingLeft + plotWidth / 2} y={height - 10} textAnchor="middle" fontSize="13" fill="currentColor" opacity="0.8">
        Date
      </text>

      <text
        x={18}
        y={paddingTop + plotHeight / 2}
        textAnchor="middle"
        fontSize="13"
        fill="currentColor"
        opacity="0.8"
        transform={`rotate(-90 18 ${paddingTop + plotHeight / 2})`}
      >
        Value
      </text>

      <polyline
        fill="none"
        stroke="var(--primary)"
        strokeWidth="4"
        points={polyline}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {points.map((point, index) => (
        <circle key={index} cx={xFor(index)} cy={yFor(point.value)} r="5" fill="var(--primary)" />
      ))}
    </svg>
  );
}

function TrendCard({ trend }: { trend: BloodworkTrend }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="soft-card-tight trend-card">
      <div className="trend-header">
        <div>
          <div className="trend-title">{trend.display_name}</div>
          <div className="trend-subtitle">
            {valueOrDash(trend.category)} · Unit {valueOrDash(trend.unit)}
          </div>
        </div>
      </div>

      <div className="trend-layout">
        <div>
          <div className="trend-metrics">
            <div className="trend-metric-card">
              <div className="trend-metric-label">Latest</div>
              <div className="trend-metric-value">{valueOrDash(trend.latest.value_display)}</div>
            </div>

            <div className="trend-metric-card">
              <div className="trend-metric-label">Previous</div>
              <div className="trend-metric-value">
                {trend.previous ? valueOrDash(trend.previous.value_display) : "—"}
              </div>
            </div>

            <div className="trend-metric-card">
              <div className="trend-metric-label">Delta</div>
              <div className="trend-metric-value">
                {trend.delta === null || trend.delta === undefined
                  ? "—"
                  : trend.delta > 0
                  ? `+${trend.delta}`
                  : `${trend.delta}`}
              </div>
            </div>
          </div>

          <div className="trend-meta-line">
            Latest sample: {valueOrDash(trend.latest.date)} · Ref {valueOrDash(trend.latest.reference_range)}
          </div>
        </div>

        <div className="trend-chart-wrap">
          <TrendSparkline points={trend.points} />
        </div>
      </div>

      <button type="button" className="trend-expand-btn" onClick={() => setExpanded((prev) => !prev)}>
        {expanded ? "Hide details" : "Show details"}
        <span className={expanded ? "trend-expand-arrow open" : "trend-expand-arrow"}>▼</span>
      </button>

      {expanded && (
        <div className="trend-details">
          {trend.points.map((point, index) => (
            <div key={`${trend.test_key}-${index}`} className="trend-detail-row">
              <div>
                <div className="trend-detail-label">Date</div>
                <div>{valueOrDash(point.date)}</div>
              </div>
              <div>
                <div className="trend-detail-label">Value</div>
                <div>{valueOrDash(point.value_display)}</div>
              </div>
              <div>
                <div className="trend-detail-label">Reference</div>
                <div>{valueOrDash(point.reference_range)}</div>
              </div>
              <div>
                <div className="trend-detail-label">Report</div>
                <div>{valueOrDash(point.report_name)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [activeSection, setActiveSection] = useState<SectionKey>("notes");

  const [eventTitle, setEventTitle] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [creatingEvent, setCreatingEvent] = useState(false);

  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [creatingNote, setCreatingNote] = useState(false);

  const [uploadSection, setUploadSection] = useState<string>("bloodwork");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);
  const tabSectionRef = useRef<HTMLDivElement | null>(null);

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
    const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
    setProfile(response.data);
  };

  const fetchTrends = async () => {
    const response = await api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`);
    setTrends(response.data);
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await Promise.all([fetchProfile(), fetchTrends()]);
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load patient chart."));
      } finally {
        setLoading(false);
      }
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

  const createNote = async () => {
    if (!noteTitle.trim()) {
      setError("Note title is required.");
      return;
    }
    if (!noteBody.trim()) {
      setError("Note body is required.");
      return;
    }

    try {
      setCreatingNote(true);
      setError("");
      await api.post(`/patients/${patientId}/notes`, {
        title: noteTitle,
        content: noteBody,
        is_verified: true,
      });
      setNoteTitle("");
      setNoteBody("");
      setActiveSection("notes");
      await fetchProfile();
      requestAnimationFrame(() => {
        tabSectionRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
      });
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create note."));
    } finally {
      setCreatingNote(false);
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
      await Promise.all([fetchProfile(), fetchTrends()]);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to upload document."));
    } finally {
      setUploading(false);
    }
  };

  const openOriginal = (documentId: number) => {
    window.open(`${API_URL}/documents/${documentId}/file`, "_blank");
  };

  const changeSection = (section: SectionKey) => {
    setActiveSection(section);
    requestAnimationFrame(() => {
      tabSectionRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
    });
  };

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return [
      ...profile.sections.notes,
      ...profile.sections.bloodwork,
      ...profile.sections.medications,
      ...profile.sections.scans,
      ...profile.sections.hospitalizations,
      ...profile.sections.other,
    ].sort((a, b) => {
      const aDate = a.test_date || "";
      const bDate = b.test_date || "";
      return bDate.localeCompare(aDate);
    });
  }, [profile]);

  const sectionDocuments = useMemo(() => {
    if (!profile) return [];

    if (activeSection === "all_documents") return allDocuments;
    if (activeSection === "notes") return profile.sections.notes;
    if (activeSection === "bloodwork") return profile.sections.bloodwork;
    if (activeSection === "medications") return profile.sections.medications;
    if (activeSection === "scans") return profile.sections.scans;
    if (activeSection === "hospitalizations") return profile.sections.hospitalizations;
    if (activeSection === "other") return profile.sections.other;

    return [];
  }, [profile, activeSection, allDocuments]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading patient chart...</p>
      </main>
    );
  }

  const canUpload = currentUser.role === "doctor" || currentUser.role === "admin";
  const canManageEvents = currentUser.role === "doctor";
  const canWriteNotes = currentUser.role === "doctor";
  const recentHospitalizations = profile.events.slice(0, 2);

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
          gridTemplateColumns: "1.2fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>Assigned Doctors</div>

          <div style={{ display: "grid", gap: 12 }}>
            {profile.doctor_access.map((doctor) => (
              <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 800 }}>{doctor.doctor_name}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>{doctor.doctor_email}</div>
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
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 16,
              gap: 12,
            }}
          >
            <div className="section-title">Hospitalizations</div>
            <button
              className="secondary-btn"
              onClick={() => router.push(`/patients/${patientId}/hospitalizations`)}
            >
              View All →
            </button>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {recentHospitalizations.map((event) => (
              <div key={event.id} className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
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
                      {event.status === "active" ? "Admitted" : "Discharged"} · Doctor {valueOrDash(event.doctor_name)}
                    </div>
                    {event.description && <div style={{ marginTop: 8 }}>{event.description}</div>}
                  </div>

                  {canManageEvents && event.status === "active" && (
                    <button className="secondary-btn" onClick={() => dischargeEvent(event.id)}>
                      Discharge
                    </button>
                  )}
                </div>
              </div>
            ))}

            {!recentHospitalizations.length && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
                <div className="muted-text">No hospitalizations recorded yet.</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {canManageEvents && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>Add Hospitalization Event</div>

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

      {canWriteNotes && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>Create Clinical Note</div>

          <div style={{ display: "grid", gap: 12 }}>
            <input
              className="text-input"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              placeholder="Note title"
            />
            <textarea
              className="text-input"
              value={noteBody}
              onChange={(e) => setNoteBody(e.target.value)}
              placeholder="Write your note here"
              rows={6}
            />
            <div>
              <button className="primary-btn" onClick={createNote} disabled={creatingNote}>
                {creatingNote ? "Saving..." : "Save Note"}
              </button>
            </div>
          </div>
        </div>
      )}

      {canUpload && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>Upload Record</div>

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
              onChange={(e) => setUploadSection(e.target.value)}
            >
              {["bloodwork", "medications", "scans", "hospitalizations", "other"].map((section) => (
                <option key={section} value={section}>
                  {section === "bloodwork"
                    ? "Bloodwork"
                    : section === "medications"
                    ? "Medications"
                    : section === "scans"
                    ? "Scans"
                    : section === "hospitalizations"
                    ? "Hospitalizations"
                    : "Other"}
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
                background: "var(--panel)",
                minHeight: 58,
              }}
            >
              <input
                ref={hiddenFileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
              <button type="button" className="secondary-btn" onClick={() => hiddenFileInputRef.current?.click()}>
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

      <div ref={tabSectionRef} className="soft-card" style={{ padding: 24, marginBottom: 24, scrollMarginTop: 24 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
          {SECTION_ORDER.map((section) => {
            const count =
              section === "all_documents"
                ? allDocuments.length
                : section === "notes"
                ? profile.sections.notes.length
                : section === "bloodwork"
                ? profile.sections.bloodwork.length
                : section === "medications"
                ? profile.sections.medications.length
                : section === "scans"
                ? profile.sections.scans.length
                : section === "hospitalizations"
                ? profile.sections.hospitalizations.length
                : profile.sections.other.length;

            return (
              <button
                key={section}
                type="button"
                className={activeSection === section ? "primary-btn" : "secondary-btn"}
                onClick={() => changeSection(section)}
              >
                {SECTION_LABELS[section]} ({count})
              </button>
            );
          })}
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {sectionDocuments.map((doc) => {
            const isNote = doc.section === "notes";

            return (
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
                          background: doc.is_verified ? "var(--success-bg)" : "var(--warn-bg)",
                          color: doc.is_verified ? "var(--success-text)" : "var(--warn-text)",
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

                    {isNote ? (
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        {valueOrDash(doc.note_preview)}
                      </div>
                    ) : (
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="muted-text" style={{ fontSize: 13 }}>Created / Uploaded by</div>
                    <div style={{ marginTop: 6, fontWeight: 700 }}>{valueOrDash(doc.uploaded_by?.full_name)}</div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {valueOrDash(doc.uploaded_by?.department)} · {valueOrDash(doc.uploaded_by?.hospital_name)}
                    </div>
                  </div>

                  <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                    {!isNote && !!doc.content_type && !!doc.filename && (
                      <button type="button" className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                        Open File
                      </button>
                    )}
                    <button type="button" className="primary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                      {isNote ? "Open Note" : "Structured View"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {!sectionDocuments.length && (
            <div className="muted-text">No items in this section yet.</div>
          )}
        </div>
      </div>

      {activeSection === "bloodwork" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>Bloodwork Trends</div>

          <div style={{ display: "grid", gap: 16 }}>
            {trends.map((trend) => (
              <TrendCard key={trend.test_key} trend={trend} />
            ))}

            {!trends.length && (
              <div className="muted-text">No numeric bloodwork trends available yet.</div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}