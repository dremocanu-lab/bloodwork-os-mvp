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
  can_edit_note?: boolean;
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
  date?: string | null;
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

function isAbnormalDoc(doc: DocumentCard) {
  return Boolean(doc.has_abnormal || doc.has_abnormal_labs);
}

function isUnreviewedAbnormalDoc(doc: DocumentCard) {
  return isAbnormalDoc(doc) && !doc.reviewed_by_current_doctor;
}

function bestDocumentDate(doc: DocumentCard) {
  return (
    doc.test_date ||
    doc.collected_on ||
    doc.reported_on ||
    doc.generated_on ||
    doc.registered_on ||
    doc.created_at ||
    ""
  );
}

function formatTimelineDate(value?: string | null, fallback = "No date") {
  if (!value) return fallback;

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 24);
  }

  return parsed.toLocaleDateString(undefined, {
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

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("all_documents");

  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [dischargingId, setDischargingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const sectionLabels: Record<SectionKey, string> = {
    all_documents: t("allRecords") || "All Records",
    bloodwork: t("bloodwork") || "Bloodwork",
    scans: t("scans") || "Scans",
    medications: t("medications") || "Medications",
    notes: t("notes") || "Notes",
    hospitalizations: t("hospitalizations") || "Hospitalizations",
    other: t("other") || "Other",
  };

  function sectionLabel(section: string) {
    if (section === "bloodwork") return t("bloodwork") || "Bloodwork";
    if (section === "scans") return t("scan") || "Scan";
    if (section === "medications") return t("medication") || "Medication";
    if (section === "hospitalizations") return t("hospitalization") || "Hospitalization";
    if (section === "notes") return t("note") || "Note";
    return t("record") || "Record";
  }

  async function fetchMe() {
    const response = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(response.data);
    return response.data;
  }

  async function fetchProfile() {
    const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
    setProfile(response.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const user = await fetchMe();

        if (user.role === "patient") {
          router.push("/my-records");
          return;
        }

        await fetchProfile();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient chart."));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [patientId]);

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return [
      ...profile.sections.notes,
      ...profile.sections.bloodwork,
      ...profile.sections.scans,
      ...profile.sections.medications,
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
    return allDocuments.filter(isUnreviewedAbnormalDoc);
  }, [allDocuments]);

  const activeEvents = useMemo(() => {
    return (profile?.events || []).filter((event) => event.status === "active");
  }, [profile]);

  const recentEvents = useMemo(() => {
    return (profile?.events || []).slice(0, 3);
  }, [profile]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        records: 0,
        bloodwork: 0,
        scans: 0,
        notes: 0,
        needsReview: 0,
      };
    }

    return {
      records: allDocuments.length,
      bloodwork: profile.sections.bloodwork.length,
      scans: profile.sections.scans.length,
      notes: profile.sections.notes.length,
      needsReview: unreviewedAbnormalDocuments.length,
    };
  }, [profile, allDocuments, unreviewedAbnormalDocuments]);

  const timeline = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => {
      const unreviewedAbnormal = isUnreviewedAbnormalDoc(doc);

      return {
        id: `doc-${doc.id}`,
        date: bestDocumentDate(doc),
        title: valueOrDash(doc.report_name || doc.filename),
        subtitle: `${sectionLabel(doc.section)} · ${valueOrDash(doc.report_type)} · ${
          doc.is_verified ? "Verified" : "Unverified"
        }`,
        kind: unreviewedAbnormal ? "abnormal" : doc.section === "notes" ? "note" : "record",
        documentId: doc.id,
        isUnreviewedAbnormal: unreviewedAbnormal,
      };
    });

    const eventItems: TimelineItem[] = profile.events.map((event) => ({
      id: `event-${event.id}`,
      date: event.discharged_at || event.admitted_at,
      title: event.title,
      subtitle: `${event.status === "active" ? "Active admission" : "Discharged"} · ${valueOrDash(
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
  }, [profile, allDocuments]);

  function getSectionCount(section: SectionKey) {
    if (!profile) return 0;

    if (section === "all_documents") return allDocuments.length;
    return profile.sections[section]?.length || 0;
  }

  async function openOriginal(documentId: number) {
    try {
      setOpeningId(documentId);
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
      setError(getErrorMessage(err, "Could not open original file."));
    } finally {
      setOpeningId(null);
    }
  }

  async function dischargeEvent(eventId: number) {
    try {
      setDischargingId(eventId);
      setError("");

      await api.post(`/patient-events/${eventId}/discharge`);
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Could not discharge patient."));
    } finally {
      setDischargingId(null);
    }
  }

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">Loading patient chart...</span>
        </div>
      </main>
    );
  }

  const canDoctorActions = currentUser.role === "doctor";
  const hasActiveAdmission = activeEvents.length > 0;

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
        className="soft-card"
        style={{
          padding: 24,
          marginBottom: 24,
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) auto",
            gap: 20,
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              {hasActiveAdmission ? (
                <span
                  style={{
                    display: "inline-flex",
                    padding: "7px 11px",
                    borderRadius: 999,
                    background: "var(--success-bg)",
                    color: "var(--success-text)",
                    border: "1px solid var(--success-border)",
                    fontWeight: 900,
                    fontSize: 12,
                  }}
                >
                  Active admission
                </span>
              ) : (
                <span
                  style={{
                    display: "inline-flex",
                    padding: "7px 11px",
                    borderRadius: 999,
                    background: "var(--panel-2)",
                    color: "var(--muted)",
                    border: "1px solid var(--border)",
                    fontWeight: 900,
                    fontSize: 12,
                  }}
                >
                  No active stay
                </span>
              )}

              {stats.needsReview > 0 && (
                <span
                  style={{
                    display: "inline-flex",
                    padding: "7px 11px",
                    borderRadius: 999,
                    background: "var(--danger-bg)",
                    color: "var(--danger-text)",
                    border: "1px solid var(--danger-border)",
                    fontWeight: 900,
                    fontSize: 12,
                  }}
                >
                  {stats.needsReview} need review
                </span>
              )}
            </div>

            <div style={{ fontSize: 34, fontWeight: 950, letterSpacing: "-0.06em" }}>
              {profile.patient.full_name}
            </div>

            <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
              Patient ID {valueOrDash(profile.patient.patient_identifier)} · CNP {valueOrDash(profile.patient.cnp)}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {canDoctorActions && (
              <>
                <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/upload`)}>
                  Upload document
                </button>

                <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/notes/new`)}>
                  New clinical note
                </button>
              </>
            )}

            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
              Full timeline
            </button>
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">Total records</div>
          <div className="stat-card-value">{stats.records}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">Bloodwork</div>
          <div className="stat-card-value">{stats.bloodwork}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">Scans</div>
          <div className="stat-card-value">{stats.scans}</div>
        </div>

        <div className="stat-card stat-card-accent-orange">
          <div className="stat-card-label">Notes</div>
          <div className="stat-card-value">{stats.notes}</div>
        </div>

        <div className="stat-card stat-card-accent-red">
          <div className="stat-card-label">Needs review</div>
          <div className="stat-card-value">{stats.needsReview}</div>
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
              Abnormal records need review
            </div>
          </div>

          <div className="muted-text" style={{ marginTop: 8 }}>
            Opening each structured record marks it reviewed for your doctor account.
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
              <div className="section-title">Records</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Organized documents, notes, and uploaded clinical files.
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
            {SECTION_ORDER.map((section) => (
              <button
                key={section}
                type="button"
                className={activeSection === section ? "primary-btn" : "secondary-btn"}
                onClick={() => setActiveSection(section)}
              >
                {sectionLabels[section]} ({getSectionCount(section)})
              </button>
            ))}
          </div>

          <div style={{ display: "grid", gap: 14 }}>
            {sectionDocuments.map((doc) => {
              const isNote = doc.section === "notes";
              const hasAbnormal = isAbnormalDoc(doc);
              const unreviewedAbnormal = isUnreviewedAbnormalDoc(doc);

              return (
                <div
                  key={doc.id}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    borderColor: unreviewedAbnormal ? "var(--danger-border)" : "var(--border)",
                    background: unreviewedAbnormal ? "var(--danger-bg)" : undefined,
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
                              background: unreviewedAbnormal ? "var(--danger-text)" : "var(--muted)",
                              display: "inline-flex",
                            }}
                          />
                        )}

                        <div style={{ fontWeight: 950, fontSize: 18 }}>
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
                          {doc.is_verified ? "Verified" : "Unverified"}
                        </span>
                      </div>

                      {hasAbnormal && (
                        <div style={{ marginTop: 8 }}>
                          <span
                            style={{
                              display: "inline-flex",
                              padding: "5px 10px",
                              borderRadius: 999,
                              background: unreviewedAbnormal ? "var(--danger-bg)" : "var(--panel-2)",
                              color: unreviewedAbnormal ? "var(--danger-text)" : "var(--muted)",
                              border: `1px solid ${unreviewedAbnormal ? "var(--danger-border)" : "var(--border)"}`,
                              fontSize: 12,
                              fontWeight: 900,
                            }}
                          >
                            {unreviewedAbnormal ? "Abnormal results need review" : "Abnormal results reviewed"}
                          </span>
                        </div>
                      )}

                      <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.6 }}>
                        {valueOrDash(doc.report_type)} · {valueOrDash(bestDocumentDate(doc))}
                      </div>

                      {isNote ? (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.note_preview)}
                        </div>
                      ) : (
                        <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                          {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)} · Uploaded by{" "}
                          {valueOrDash(doc.uploaded_by?.full_name)}
                        </div>
                      )}
                    </div>

                    <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                      {!isNote && !!doc.content_type && !!doc.filename && (
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => openOriginal(doc.id)}
                          disabled={openingId === doc.id}
                        >
                          {openingId === doc.id ? "Opening..." : "Open Original"}
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
              <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 900 }}>No items in this section.</div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  Upload a document or create a note to add to this chart.
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="soft-card" style={{ padding: 24 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <div>
              <div className="section-title">Timeline</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Recent activity
              </div>
            </div>

            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
              View all
            </button>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {timeline.slice(0, 6).map((item) => (
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
                      {formatTimelineDate(item.date, "No date")} · {item.subtitle}
                    </div>

                    {item.documentId && (
                      <button
                        type="button"
                        className="secondary-btn"
                        style={{ marginTop: 10 }}
                        onClick={() => router.push(`/documents/${item.documentId}`)}
                      >
                        Open
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {!timeline.length && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div className="muted-text">No timeline activity yet.</div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Assigned doctors
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {profile.doctor_access.map((doctor) => (
              <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 900 }}>{doctor.doctor_name}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>
                  {doctor.doctor_email}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                </div>
              </div>
            ))}

            {!profile.doctor_access.length && <div className="muted-text">No doctors assigned.</div>}
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
            <div>
              <div className="section-title">Hospitalizations</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Recent stays
              </div>
            </div>

            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/hospitalizations`)}>
              View all
            </button>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {recentEvents.map((event) => (
              <div key={event.id} className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
                  <div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <div style={{ fontWeight: 900 }}>{event.title}</div>

                      <span
                        style={{
                          display: "inline-flex",
                          padding: "5px 9px",
                          borderRadius: 999,
                          background: event.status === "active" ? "var(--success-bg)" : "var(--panel-2)",
                          color: event.status === "active" ? "var(--success-text)" : "var(--muted)",
                          border: "1px solid var(--border)",
                          fontWeight: 900,
                          fontSize: 12,
                        }}
                      >
                        {event.status === "active" ? "Active" : "Discharged"}
                      </span>
                    </div>

                    <div className="muted-text" style={{ marginTop: 6 }}>
                      {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4 }}>
                      Doctor {valueOrDash(event.doctor_name)} · Admitted {formatTimelineDate(event.admitted_at)}
                    </div>

                    {event.description && <div style={{ marginTop: 8, lineHeight: 1.6 }}>{event.description}</div>}
                  </div>

                  {canDoctorActions && event.status === "active" && event.doctor_user_id === currentUser.id && (
                    <button
                      className="secondary-btn"
                      onClick={() => dischargeEvent(event.id)}
                      disabled={dischargingId === event.id}
                    >
                      {dischargingId === event.id ? "Discharging..." : "Discharge"}
                    </button>
                  )}
                </div>
              </div>
            ))}

            {!recentEvents.length && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel)" }}>
                <div className="muted-text">No hospitalizations recorded.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}