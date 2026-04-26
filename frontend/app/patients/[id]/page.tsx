"use client";

import { useEffect, useMemo, useState } from "react";
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
  collected_on?: string | null;
  reported_on?: string | null;
  registered_on?: string | null;
  generated_on?: string | null;
  created_at?: string | null;
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

function bestDocumentDate(doc: DocumentCard) {
  if (doc.section === "bloodwork") {
    return doc.collected_on || doc.test_date || doc.reported_on || doc.generated_on || doc.created_at || "";
  }

  if (doc.section === "scans") {
    return doc.test_date || doc.reported_on || doc.generated_on || doc.created_at || "";
  }

  if (doc.section === "notes") {
    return doc.created_at || doc.test_date || "";
  }

  return doc.test_date || doc.reported_on || doc.generated_on || doc.created_at || "";
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

function getSectionTone(section: string) {
  if (section === "bloodwork") return { bg: "var(--danger-bg)", text: "var(--danger-text)", border: "var(--danger-border)" };
  if (section === "scans") return { bg: "var(--success-bg)", text: "var(--success-text)", border: "var(--success-border)" };
  if (section === "notes") return { bg: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))", text: "var(--primary)", border: "color-mix(in srgb, var(--primary) 32%, var(--border))" };
  return { bg: "var(--panel-2)", text: "var(--muted)", border: "var(--border)" };
}

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const { t, language } = useLanguage();
  const patientId = params?.id as string;

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        uploadDocument: "Încarcă document",
        newClinicalNote: "Notă clinică nouă",
        viewFullTimeline: "Vezi timeline complet",
        recentTimeline: "Timeline recent",
        quickActions: "Acțiuni rapide",
        quickActionsDesc: "Încarcă documente, creează note clinice sau vezi activitatea completă a pacientului.",
        clinicalNotesVisibility: "Notele clinice sunt vizibile tuturor medicilor cu acces. Doar medicul autor poate edita nota.",
        recordsDesc: "Documentele pacientului sunt grupate pe tip. Rezultatele anormale nerevizuite sunt marcate cu roșu.",
        noRecentTimeline: "Nu există activitate recentă.",
        uploadedBy: "Încărcat de",
        noDate: "Fără dată",
        timelineHint: "Se afișează cele mai recente elemente. Folosește timeline-ul complet pentru istoricul complet.",
        patientDetails: "Detalii pacient",
        clinicalTeam: "Echipă medicală",
      };
    }

    return {
      uploadDocument: "Upload document",
      newClinicalNote: "New clinical note",
      viewFullTimeline: "View full timeline",
      recentTimeline: "Recent timeline",
      quickActions: "Quick actions",
      quickActionsDesc: "Upload documents, create clinical notes, or review the patient’s full activity timeline.",
      clinicalNotesVisibility: "Clinical notes are visible to all doctors with patient access. Only the authoring doctor can edit their own note.",
      recordsDesc: "Patient documents are grouped by type. Unreviewed abnormal records are marked in red.",
      noRecentTimeline: "No recent activity yet.",
      uploadedBy: "Uploaded by",
      noDate: "No date",
      timelineHint: "Showing only the latest items. Use the full timeline for the complete history.",
      patientDetails: "Patient details",
      clinicalTeam: "Clinical team",
    };
  }, [language]);

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

  async function openOriginal(documentId: number) {
    try {
      setError("");

      const response = await api.get(`/documents/${documentId}/file`, {
        responseType: "blob",
      });

      const rawContentType = response.headers["content-type"];
      const contentType = typeof rawContentType === "string" ? rawContentType : "application/octet-stream";
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
      subtitle: `${event.status === "active" ? t("activeAdmission") : t("discharged")} · ${valueOrDash(
        event.department
      )} · ${valueOrDash(event.doctor_name)}`,
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
      <main
        className="app-page-bg"
        style={{
          minHeight: "100vh",
          padding: 24,
          display: "grid",
          placeItems: "center",
        }}
      >
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">{t("loadingPatientChart")}</span>
        </div>
      </main>
    );
  }

  const canManageEvents = currentUser.role === "doctor";
  const canWriteNotes = currentUser.role === "doctor";
  const canUpload = currentUser.role === "doctor" || currentUser.role === "admin";
  const recentHospitalizations = profile.events.slice(0, 2);
  const recentTimeline = timeline.slice(0, 5);

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`CNP ${valueOrDash(profile.patient.cnp)} · ID ${valueOrDash(profile.patient.patient_identifier)} · ${t(
        "dob"
      )} ${valueOrDash(profile.patient.date_of_birth)} · ${t("age")} ${valueOrDash(profile.patient.age)} · ${t(
        "sex"
      )} ${valueOrDash(profile.patient.sex)}`}
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

      <div
        className="soft-card"
        style={{
          padding: 24,
          marginBottom: 24,
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div className="section-title">{labels.quickActions}</div>
            <div className="muted-text" style={{ marginTop: 6, maxWidth: 760, lineHeight: 1.6 }}>
              {labels.quickActionsDesc}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {canUpload && (
              <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/upload`)}>
                {labels.uploadDocument}
              </button>
            )}

            {canWriteNotes && (
              <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/notes/new`)}>
                {labels.newClinicalNote}
              </button>
            )}

            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
              {labels.viewFullTimeline}
            </button>
          </div>
        </div>

        {canWriteNotes && (
          <div
            className="soft-card-tight"
            style={{
              marginTop: 18,
              padding: 14,
              background: "var(--panel-2)",
            }}
          >
            <div className="muted-text" style={{ lineHeight: 1.6 }}>
              {labels.clinicalNotesVisibility}
            </div>
          </div>
        )}
      </div>

      {canManageEvents && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("addHospitalizationEvent")}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 0.8fr) minmax(0, 1fr) auto", gap: 12 }}>
            <input
              className="text-input"
              value={eventTitle}
              onChange={(e) => setEventTitle(e.target.value)}
              placeholder={t("hospitalizationTitlePlaceholder")}
            />
            <input
              className="text-input"
              value={eventDescription}
              onChange={(e) => setEventDescription(e.target.value)}
              placeholder={t("careNotesPlaceholder")}
            />
            <button className="primary-btn" onClick={createEvent} disabled={creatingEvent}>
              {creatingEvent ? t("creating") : t("createEvent")}
            </button>
          </div>
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.35fr) minmax(320px, 0.65fr)",
          gap: 20,
          alignItems: "start",
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 18 }}>
            <div>
              <div className="section-title">{t("records")}</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {labels.recordsDesc}
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
                  onClick={() => setActiveSection(section)}
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
              const tone = getSectionTone(doc.section);

              return (
                <div
                  key={doc.id}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    borderColor: isUnreviewedAbnormal ? "var(--danger-border)" : tone.border,
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
                            background: tone.bg,
                            color: tone.text,
                            border: `1px solid ${tone.border}`,
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
                        {valueOrDash(doc.report_type)} · {formatTimelineDate(bestDocumentDate(doc), labels.noDate)}
                      </div>

                      {isNote ? (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.note_preview)}
                        </div>
                      ) : (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)} · {labels.uploadedBy}{" "}
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
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div className="section-title">{labels.recentTimeline}</div>
            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
              →
            </button>
          </div>

          <div className="muted-text" style={{ marginBottom: 16, lineHeight: 1.5 }}>
            {labels.timelineHint}
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {recentTimeline.map((item) => (
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
                          : item.kind === "note"
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
                      {formatTimelineDate(item.date, labels.noDate)} · {item.subtitle}
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

            {!recentTimeline.length && <div className="muted-text">{labels.noRecentTimeline}</div>}
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
            {labels.clinicalTeam}
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