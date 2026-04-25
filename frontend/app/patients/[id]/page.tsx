"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
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
  has_abnormal?: boolean;
  has_abnormal_labs?: boolean;
  reviewed_by_current_doctor?: boolean;
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

type TimelineItem = {
  id: string;
  date: string;
  title: string;
  subtitle: string;
  kind: "record" | "note" | "event" | "abnormal";
  documentId?: number;
  eventId?: number;
  isUnreviewedAbnormal?: boolean;
};

const SECTION_ORDER = [
  "all_documents",
  "bloodwork",
  "scans",
  "medications",
  "notes",
  "hospitalizations",
  "other",
] as const;

type SectionKey = (typeof SECTION_ORDER)[number];

function bestDocumentDate(doc: DocumentCard) {
  return doc.test_date || "";
}

function formatTimelineDate(value?: string | null, noDate = "No date") {
  if (!value) return noDate;

  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 16);

  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;

  const sectionLabels: Record<SectionKey, string> = {
    all_documents: t("allRecords"),
    bloodwork: t("bloodwork"),
    scans: t("scans"),
    medications: t("medications"),
    notes: t("notes"),
    hospitalizations: t("hospitalizations"),
    other: t("other"),
  };

  function sectionLabel(section: string) {
    if (section === "bloodwork") return t("bloodwork");
    if (section === "scans") return t("scan");
    if (section === "medications") return t("medication");
    if (section === "hospitalizations") return t("hospitalization");
    if (section === "notes") return t("note");
    return t("record");
  }

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("all_documents");

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
  const recordsRef = useRef<HTMLDivElement | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function fetchMe() {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  }

  async function fetchProfile() {
    const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
    setProfile(response.data);
  }

  useEffect(() => {
    async function init() {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await fetchProfile();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadPatientChart")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [patientId]);

  async function createEvent() {
    if (!eventTitle.trim()) {
      setError(t("eventTitleRequired"));
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
      setError(getErrorMessage(err, t("failedCreateEvent")));
    } finally {
      setCreatingEvent(false);
    }
  }

  async function dischargeEvent(eventId: number) {
    try {
      setError("");
      await api.post(`/patient-events/${eventId}/discharge`);
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, t("failedDischargeEvent")));
    }
  }

  async function createNote() {
    if (!noteTitle.trim()) {
      setError(t("noteTitleRequired"));
      return;
    }

    if (!noteBody.trim()) {
      setError(t("noteBodyRequired"));
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
        recordsRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
      });
    } catch (err) {
      setError(getErrorMessage(err, t("failedCreateNote")));
    } finally {
      setCreatingNote(false);
    }
  }

  async function uploadDocument() {
    if (!uploadFile) {
      setError(t("chooseFileFirst"));
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

      setActiveSection(uploadSection as SectionKey);
      await fetchProfile();

      requestAnimationFrame(() => {
        recordsRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
      });
    } catch (err) {
      setError(getErrorMessage(err, t("failedUploadDocument")));
    } finally {
      setUploading(false);
    }
  }

  async function openOriginal(documentId: number) {
    try {
      setError("");

      const response = await api.get(`/documents/${documentId}/file`, {
        responseType: "blob",
      });

      const contentType = response.headers["content-type"] || "application/octet-stream";
      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);

      window.open(fileUrl, "_blank", "noopener,noreferrer");

      setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(getErrorMessage(err, t("failedOpenOriginal")));
    }
  }

  function changeSection(section: SectionKey) {
    setActiveSection(section);
    requestAnimationFrame(() => {
      recordsRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
    });
  }

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return [
      ...profile.sections.notes,
      ...profile.sections.bloodwork,
      ...profile.sections.medications,
      ...profile.sections.scans,
      ...profile.sections.hospitalizations,
      ...profile.sections.other,
    ].sort((a, b) => bestDocumentDate(b).localeCompare(bestDocumentDate(a)));
  }, [profile]);

  const sectionDocuments = useMemo(() => {
    if (!profile) return [];

    if (activeSection === "all_documents") return allDocuments;
    return profile.sections[activeSection] || [];
  }, [profile, activeSection, allDocuments]);

  const unreviewedAbnormalDocuments = useMemo(() => {
    return allDocuments.filter((doc) => {
      const hasAbnormal = Boolean(doc.has_abnormal || doc.has_abnormal_labs);
      const isReviewed = Boolean(doc.reviewed_by_current_doctor);
      return hasAbnormal && !isReviewed;
    });
  }, [allDocuments]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        records: 0,
        bloodwork: 0,
        scans: 0,
        notes: 0,
        abnormal: 0,
      };
    }

    return {
      records: allDocuments.length,
      bloodwork: profile.sections.bloodwork.length,
      scans: profile.sections.scans.length,
      notes: profile.sections.notes.length,
      abnormal: unreviewedAbnormalDocuments.length,
    };
  }, [profile, allDocuments, unreviewedAbnormalDocuments]);

  const timeline = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => {
      const hasAbnormal = Boolean(doc.has_abnormal || doc.has_abnormal_labs);
      const isReviewed = Boolean(doc.reviewed_by_current_doctor);
      const isUnreviewedAbnormal = hasAbnormal && !isReviewed;

      return {
        id: `doc-${doc.id}`,
        date: bestDocumentDate(doc),
        title: valueOrDash(doc.report_name || doc.filename),
        subtitle: `${sectionLabel(doc.section)} · ${valueOrDash(doc.report_type)} · ${
          doc.is_verified ? t("verified") : t("unverified")
        }`,
        kind: isUnreviewedAbnormal ? "abnormal" : doc.section === "notes" ? "note" : "record",
        documentId: doc.id,
        isUnreviewedAbnormal,
      };
    });

    const eventItems: TimelineItem[] = profile.events.map((event) => ({
      id: `event-${event.id}`,
      date: event.discharged_at || event.admitted_at,
      title: event.title,
      subtitle: `${
        event.status === "active" ? t("activeAdmission") : t("discharged")
      } · ${valueOrDash(event.department)} · ${valueOrDash(event.doctor_name)}`,
      kind: "event",
      eventId: event.id,
    }));

    return [...documentItems, ...eventItems].sort((a, b) => {
      const aDate = a.date || "";
      const bDate = b.date || "";
      return bDate.localeCompare(aDate);
    });
  }, [profile, allDocuments, t]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingPatientChart")}</p>
      </main>
    );
  }

  const canUpload = true;
  const canManageEvents = currentUser.role === "doctor";
  const canWriteNotes = currentUser.role === "doctor";
  const recentHospitalizations = profile.events.slice(0, 2);

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`ID ${valueOrDash(profile.patient.patient_identifier)} · ${t("dob")} ${valueOrDash(
        profile.patient.date_of_birth
      )} · ${t("age")} ${valueOrDash(profile.patient.age)} · ${t("sex")} ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.back()}>
          {t("back")}
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
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">{t("totalRecords")}</div>
          <div className="stat-card-value">{stats.records}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">{t("bloodwork")}</div>
          <div className="stat-card-value">{stats.bloodwork}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">{t("scans")}</div>
          <div className="stat-card-value">{stats.scans}</div>
        </div>

        <div className="stat-card stat-card-accent-orange">
          <div className="stat-card-label">{t("notes")}</div>
          <div className="stat-card-value">{stats.notes}</div>
        </div>

        <div className="stat-card stat-card-accent-red">
          <div className="stat-card-label">{t("needsReview")}</div>
          <div className="stat-card-value">{stats.abnormal}</div>
        </div>
      </div>

      {unreviewedAbnormalDocuments.length > 0 && (
        <div
          className="soft-card"
          style={{
            padding: 20,
            marginBottom: 24,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: 999,
                background: "var(--danger-text)",
                display: "inline-flex",
              }}
            />
            <div style={{ fontWeight: 950, color: "var(--danger-text)", fontSize: 18 }}>
              {t("abnormalRecordsNeedReview")}
            </div>
          </div>

          <div className="muted-text" style={{ marginTop: 8 }}>
            {t("abnormalRecordsNeedReviewDesc")}
          </div>
        </div>
      )}

      {canUpload && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
            <div>
              <div className="section-title">{t("uploadRecord")}</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {t("uploadRecordDesc")}
              </div>
            </div>

            <button type="button" className="secondary-btn" onClick={() => hiddenFileInputRef.current?.click()}>
              {t("chooseFile")}
            </button>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "220px minmax(0, 1fr) auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <select className="text-input" value={uploadSection} onChange={(e) => setUploadSection(e.target.value)}>
              {["bloodwork", "medications", "scans", "hospitalizations", "other"].map((section) => (
                <option key={section} value={section}>
                  {sectionLabels[section as SectionKey] || section}
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
                minWidth: 0,
              }}
            >
              <input
                ref={hiddenFileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />

              <div
                className="muted-text"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  minWidth: 0,
                }}
              >
                {uploadFile ? uploadFile.name : t("noFileSelected")}
              </div>
            </div>

            <button className="primary-btn" onClick={uploadDocument} disabled={uploading}>
              {uploading ? t("fileUploading") : t("upload")}
            </button>
          </div>
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: canWriteNotes || canManageEvents ? "1fr 1fr" : "1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        {canWriteNotes && (
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>
              {t("createClinicalNote")}
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <input
                className="text-input"
                value={noteTitle}
                onChange={(e) => setNoteTitle(e.target.value)}
                placeholder={t("noteTitle")}
              />
              <textarea
                className="text-input"
                value={noteBody}
                onChange={(e) => setNoteBody(e.target.value)}
                placeholder={t("writeYourNoteHere")}
                rows={5}
              />
              <div>
                <button className="primary-btn" onClick={createNote} disabled={creatingNote}>
                  {creatingNote ? t("saving") : t("saveNote")}
                </button>
              </div>
            </div>
          </div>
        )}

        {canManageEvents && (
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>
              {t("addHospitalizationEvent")}
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <input
                className="text-input"
                value={eventTitle}
                onChange={(e) => setEventTitle(e.target.value)}
                placeholder={t("hospitalizationTitlePlaceholder")}
              />
              <textarea
                className="text-input"
                value={eventDescription}
                onChange={(e) => setEventDescription(e.target.value)}
                placeholder={t("careNotesPlaceholder")}
                rows={5}
              />
              <div>
                <button className="primary-btn" onClick={createEvent} disabled={creatingEvent}>
                  {creatingEvent ? t("creating") : t("createEvent")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.35fr) minmax(320px, 0.65fr)",
          gap: 20,
          alignItems: "start",
          marginBottom: 24,
        }}
      >
        <div ref={recordsRef} className="soft-card" style={{ padding: 24, scrollMarginTop: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 18 }}>
            <div>
              <div className="section-title">{t("records")}</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {t("recordsDesc")}
              </div>
            </div>
          </div>

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
                  {sectionLabels[section]} ({count})
                </button>
              );
            })}
          </div>

          <div style={{ display: "grid", gap: 14 }}>
            {sectionDocuments.map((doc) => {
              const isNote = doc.section === "notes";
              const hasAbnormal = Boolean(doc.has_abnormal || doc.has_abnormal_labs);
              const isReviewed = Boolean(doc.reviewed_by_current_doctor);
              const isUnreviewedAbnormal = hasAbnormal && !isReviewed;

              return (
                <div
                  key={doc.id}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    borderColor: isUnreviewedAbnormal ? "var(--danger-border)" : "var(--border)",
                    background: isUnreviewedAbnormal ? "var(--danger-bg)" : undefined,
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0, 1fr) auto",
                      gap: 18,
                      alignItems: "start",
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                        {hasAbnormal && (
                          <span
                            style={{
                              width: 12,
                              height: 12,
                              borderRadius: 999,
                              background: isUnreviewedAbnormal ? "var(--danger-text)" : "var(--muted)",
                              display: "inline-flex",
                            }}
                          />
                        )}

                        <div style={{ fontWeight: 900, fontSize: 18 }}>
                          {valueOrDash(doc.report_name || doc.filename)}
                        </div>

                        <span
                          style={{
                            display: "inline-flex",
                            padding: "5px 9px",
                            borderRadius: 999,
                            background: "var(--panel-2)",
                            color: "var(--muted)",
                            fontSize: 12,
                            fontWeight: 900,
                          }}
                        >
                          {sectionLabel(doc.section)}
                        </span>

                        <span
                          style={{
                            display: "inline-flex",
                            padding: "5px 9px",
                            borderRadius: 999,
                            background: doc.is_verified ? "var(--success-bg)" : "var(--warn-bg)",
                            color: doc.is_verified ? "var(--success-text)" : "var(--warn-text)",
                            fontSize: 12,
                            fontWeight: 900,
                          }}
                        >
                          {doc.is_verified ? t("verified") : t("unverified")}
                        </span>
                      </div>

                      {hasAbnormal && (
                        <div style={{ marginTop: 8 }}>
                          <span
                            style={{
                              display: "inline-flex",
                              padding: "5px 10px",
                              borderRadius: 999,
                              background: isUnreviewedAbnormal ? "var(--danger-bg)" : "var(--panel-2)",
                              color: isUnreviewedAbnormal ? "var(--danger-text)" : "var(--muted)",
                              border: `1px solid ${isUnreviewedAbnormal ? "var(--danger-border)" : "var(--border)"}`,
                              fontSize: 12,
                              fontWeight: 900,
                            }}
                          >
                            {isUnreviewedAbnormal ? t("abnormalResultsNeedReview") : t("abnormalResultsReviewed")}
                          </span>
                        </div>
                      )}

                      <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.6 }}>
                        {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                      </div>

                      {isNote ? (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.note_preview)}
                        </div>
                      ) : (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)} · {t("uploadedBy")}{" "}
                          {valueOrDash(doc.uploaded_by?.full_name)}
                        </div>
                      )}
                    </div>

                    <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                      {!isNote && !!doc.content_type && !!doc.filename && (
                        <button type="button" className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                          {t("openOriginal")}
                        </button>
                      )}

                      <button type="button" className="primary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                        {isNote ? t("openNote") : t("structuredView")}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}

            {!sectionDocuments.length && <div className="muted-text">{t("noItemsInSection")}</div>}
          </div>
        </div>

        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("timeline")}
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {timeline.slice(0, 12).map((item) => (
              <div
                key={item.id}
                className="soft-card-tight"
                style={{
                  padding: 14,
                  borderColor: item.isUnreviewedAbnormal ? "var(--danger-border)" : "var(--border)",
                  background: item.isUnreviewedAbnormal ? "var(--danger-bg)" : undefined,
                }}
              >
                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 999,
                      background:
                        item.kind === "abnormal"
                          ? "var(--danger-text)"
                          : item.kind === "event"
                          ? "var(--primary)"
                          : "var(--muted)",
                      display: "inline-flex",
                      marginTop: 5,
                      flex: "0 0 auto",
                    }}
                  />

                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 900 }}>{item.title}</div>
                    <div className="muted-text" style={{ marginTop: 4, fontSize: 13, lineHeight: 1.5 }}>
                      {formatTimelineDate(item.date, t("noDate"))} · {item.subtitle}
                    </div>

                    {item.documentId && (
                      <button
                        type="button"
                        className="secondary-btn"
                        style={{ marginTop: 10 }}
                        onClick={() => router.push(`/documents/${item.documentId}`)}
                      >
                        {t("open")}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {!timeline.length && <div className="muted-text">{t("noTimelineActivity")}</div>}
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("assignedDoctors")}
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

            {!profile.doctor_access.length && <div className="muted-text">{t("noDoctorsAssigned")}</div>}
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
            <div className="section-title">{t("hospitalizations")}</div>
            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/hospitalizations`)}>
              {t("viewAll")}
            </button>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {recentHospitalizations.map((event) => (
              <div key={event.id} className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
                  <div>
                    <div style={{ fontWeight: 800 }}>{event.title}</div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)}
                    </div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {event.status === "active" ? t("admittedCapital") : t("discharged")} · {t("doctor")}{" "}
                      {valueOrDash(event.doctor_name)}
                    </div>
                    {event.description && <div style={{ marginTop: 8 }}>{event.description}</div>}
                  </div>

                  {canManageEvents && event.status === "active" && (
                    <button className="secondary-btn" onClick={() => dischargeEvent(event.id)}>
                      {t("discharge")}
                    </button>
                  )}
                </div>
              </div>
            ))}

            {!recentHospitalizations.length && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
                <div className="muted-text">{t("noHospitalizationsRecorded")}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}