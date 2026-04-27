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

type UploadedBy = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
};

type DocumentCard = {
  id: number;
  filename: string;
  report_name?: string | null;
  report_type?: string | null;
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
};

type PatientEvent = {
  id: number;
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
  events: PatientEvent[];
};

type TimelineKind = "all" | "records" | "notes" | "events" | "abnormal";

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

function sectionLabel(section: string) {
  if (section === "bloodwork") return "Bloodwork";
  if (section === "scans") return "Scan";
  if (section === "medications") return "Medication";
  if (section === "hospitalizations") return "Hospitalization";
  if (section === "notes") return "Clinical note";
  return "Record";
}

export default function FullTimelinePage() {
  const params = useParams();
  const router = useRouter();
  const { language } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [filter, setFilter] = useState<TimelineKind>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        title: "Timeline complet",
        back: "Înapoi la fișă",
        all: "Toate",
        records: "Documente",
        notes: "Note",
        events: "Evenimente",
        abnormal: "Anormale",
        noItems: "Nu există elemente în timeline.",
        noDate: "Fără dată",
        open: "Deschide",
        loading: "Se încarcă timeline-ul...",
        failedLoad: "Nu s-a putut încărca timeline-ul.",
      };
    }

    return {
      title: "Full timeline",
      back: "Back to chart",
      all: "All",
      records: "Records",
      notes: "Notes",
      events: "Events",
      abnormal: "Abnormal",
      noItems: "No timeline items found.",
      noDate: "No date",
      open: "Open",
      loading: "Loading timeline...",
      failedLoad: "Could not load timeline.",
    };
  }, [language]);

  async function fetchData() {
    const [meResponse, profileResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
    ]);

    setCurrentUser(meResponse.data);
    setProfile(profileResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, labels.failedLoad));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return [
      ...profile.sections.notes,
      ...profile.sections.bloodwork,
      ...profile.sections.medications,
      ...profile.sections.scans,
      ...profile.sections.hospitalizations,
      ...profile.sections.other,
    ];
  }, [profile]);

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
          doc.is_verified ? "Verified" : "Unverified"
        } · Uploaded by ${valueOrDash(doc.uploaded_by?.full_name)}`,
        kind: isUnreviewedAbnormal ? "abnormal" : doc.section === "notes" ? "note" : "record",
        documentId: doc.id,
        isUnreviewedAbnormal,
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

    return [...documentItems, ...eventItems].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  }, [profile, allDocuments]);

  const filteredTimeline = useMemo(() => {
    return timeline.filter((item) => {
      if (filter === "all") return true;
      if (filter === "records") return item.kind === "record" || item.kind === "abnormal";
      if (filter === "notes") return item.kind === "note";
      if (filter === "events") return item.kind === "event";
      if (filter === "abnormal") return item.kind === "abnormal";
      return true;
    });
  }, [timeline, filter]);

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
          <span className="muted-text">{labels.loading}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={labels.title}
      subtitle={`${profile.patient.full_name} · CNP ${valueOrDash(profile.patient.cnp)} · ID ${valueOrDash(
        profile.patient.patient_identifier
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          {labels.back}
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

      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
          {[
            ["all", labels.all],
            ["records", labels.records],
            ["notes", labels.notes],
            ["events", labels.events],
            ["abnormal", labels.abnormal],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filter === value ? "primary-btn" : "secondary-btn"}
              onClick={() => setFilter(value as TimelineKind)}
            >
              {label}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {filteredTimeline.map((item) => (
            <div
              key={item.id}
              className="soft-card-tight"
              style={{
                padding: 16,
                borderColor: item.isUnreviewedAbnormal ? "var(--danger-border)" : "var(--border)",
                background: item.isUnreviewedAbnormal ? "var(--danger-bg)" : undefined,
              }}
            >
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "120px minmax(0, 1fr) auto",
                  gap: 16,
                  alignItems: "start",
                }}
              >
                <div className="muted-text" style={{ fontWeight: 850, fontSize: 13 }}>
                  {formatTimelineDate(item.date, labels.noDate)}
                </div>

                <div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
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
                      }}
                    />

                    <div style={{ fontWeight: 950, fontSize: 17 }}>{item.title}</div>
                  </div>

                  <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                    {item.subtitle}
                  </div>
                </div>

                {item.documentId ? (
                  <button className="primary-btn" onClick={() => router.push(`/documents/${item.documentId}`)}>
                    {labels.open}
                  </button>
                ) : (
                  <span />
                )}
              </div>
            </div>
          ))}

          {!filteredTimeline.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div className="muted-text">{labels.noItems}</div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}