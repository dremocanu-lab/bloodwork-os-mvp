"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import ClinicalTimeline from "@/components/clinical-timeline";
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
  test_date?: string | null;
  collected_on?: string | null;
  reported_on?: string | null;
  registered_on?: string | null;
  generated_on?: string | null;
  created_at?: string | null;
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
  patient_id?: number;
  doctor_user_id?: number;
  event_type?: string;
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
    notes?: DocumentCard[];
    bloodwork?: DocumentCard[];
    discharge_summary?: DocumentCard[];
    medications?: DocumentCard[];
    scans?: DocumentCard[];
    hospitalizations?: DocumentCard[];
    other?: DocumentCard[];
  };
  doctor_access?: DoctorAccess[];
  events?: PatientEvent[];
};

type TimelineItem = {
  id: string;
  type: "document" | "event";
  date: string;
  title: string;
  subtitle: string;
  documentId?: number;
  eventId?: number;
  section?: string;
  children?: TimelineItem[];
};

type AdmissionTimelineItem = TimelineItem & {
  admissionStart?: string | null;
  admissionEnd?: string | null;
  parentRank: number;
};

const SECTION_ORDER = [
  "bloodwork",
  "discharge_summary",
  "medications",
  "scans",
  "hospitalizations",
  "notes",
  "other",
] as const;

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

function parseDateTime(value?: string | null) {
  if (!value) return 0;

  const normalized = value.trim();
  const direct = new Date(normalized).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(
    /^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/
  );

  if (!match) return 0;

  const day = Number(match[1]);
  const month = Number(match[2]);
  const rawYear = Number(match[3]);
  const year = rawYear < 100 ? 2000 + rawYear : rawYear;
  const hour = match[4] ? Number(match[4]) : 0;
  const minute = match[5] ? Number(match[5]) : 0;

  const parsed = new Date(year, month - 1, day, hour, minute).getTime();

  return Number.isNaN(parsed) ? 0 : parsed;
}

function compareDatesDescending(a?: string | null, b?: string | null) {
  const aTime = parseDateTime(a);
  const bTime = parseDateTime(b);

  if (aTime || bTime) return bTime - aTime;

  return (b || "").localeCompare(a || "");
}

function compareDatesAscending(a?: string | null, b?: string | null) {
  const aTime = parseDateTime(a);
  const bTime = parseDateTime(b);

  if (aTime || bTime) return aTime - bTime;

  return (a || "").localeCompare(b || "");
}

function calculateAgeFromDob(dateOfBirth?: string | null) {
  if (!dateOfBirth) return "—";

  const dob = new Date(dateOfBirth);

  if (Number.isNaN(dob.getTime())) return "—";

  const today = new Date();

  let years = today.getFullYear() - dob.getFullYear();
  let months = today.getMonth() - dob.getMonth();

  if (today.getDate() < dob.getDate()) {
    months -= 1;
  }

  if (months < 0) {
    years -= 1;
    months += 12;
  }

  if (years < 0) return "—";

  return `${years}y ${months}m`;
}

function normalizeProfile(profile: PatientProfileResponse): PatientProfileResponse {
  return {
    ...profile,
    sections: {
      notes: profile.sections.notes || [],
      bloodwork: profile.sections.bloodwork || [],
      discharge_summary: profile.sections.discharge_summary || [],
      medications: profile.sections.medications || [],
      scans: profile.sections.scans || [],
      hospitalizations: profile.sections.hospitalizations || [],
      other: profile.sections.other || [],
    },
    doctor_access: profile.doctor_access || [],
    events: profile.events || [],
  };
}

function sectionLabel(section: string) {
  if (section === "bloodwork") return "Bloodwork";
  if (section === "discharge_summary") return "Discharge summary";
  if (section === "medications") return "Medications";
  if (section === "scans") return "Scans";
  if (section === "hospitalizations") return "Hospitalization";
  if (section === "notes") return "Clinical notes";
  return "Other";
}

function getSectionDocuments(profile: PatientProfileResponse | null, section: (typeof SECTION_ORDER)[number]) {
  if (!profile) return [];
  return profile.sections[section] || [];
}

function getDocumentClinicalDate(doc: DocumentCard) {
  return (
    doc.collected_on ||
    doc.test_date ||
    doc.reported_on ||
    doc.registered_on ||
    doc.generated_on ||
    doc.created_at ||
    ""
  );
}

function getDocumentDateLabel(doc: DocumentCard) {
  if (doc.collected_on) return `Collected ${doc.collected_on}`;
  if (doc.test_date) return `Test date ${doc.test_date}`;
  if (doc.reported_on) return `Reported ${doc.reported_on}`;
  if (doc.registered_on) return `Registered ${doc.registered_on}`;
  if (doc.generated_on) return `Generated ${doc.generated_on}`;
  if (doc.created_at) return `Uploaded ${doc.created_at}`;
  return "No date";
}

function getDocumentTitle(doc: DocumentCard) {
  return doc.report_name || doc.filename || `Document ${doc.id}`;
}

function getUploaderText(doc: DocumentCard) {
  if (!doc.uploaded_by) return "Uploaded by unknown user";

  const details = [doc.uploaded_by.full_name, doc.uploaded_by.department, doc.uploaded_by.hospital_name].filter(
    Boolean
  );

  return `Uploaded by ${details.join(" · ")}`;
}

function isDischargeDocument(doc: DocumentCard) {
  return (
    doc.section === "discharge_summary" ||
    doc.report_type === "Discharge summary" ||
    doc.report_type === "discharge_summary"
  );
}

function isInsideDateRange(date?: string | null, start?: string | null, end?: string | null) {
  const dateTime = parseDateTime(date);
  const startTime = parseDateTime(start);
  const endTime = parseDateTime(end);

  if (!dateTime || !startTime) return false;

  if (!endTime) return dateTime >= startTime;

  return dateTime >= startTime && dateTime <= endTime;
}

function buildTimelineItems(documents: DocumentCard[], events: PatientEvent[]): TimelineItem[] {
  const sortedDocuments = [...documents].sort((a, b) =>
    compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
  );

  const usedDocumentIds = new Set<number>();

  const dischargeParents: AdmissionTimelineItem[] = sortedDocuments
    .filter((doc) => isDischargeDocument(doc))
    .map((doc) => ({
      id: `discharge-${doc.id}`,
      type: "document",
      date: doc.reported_on || doc.collected_on || getDocumentClinicalDate(doc),
      title: getDocumentTitle(doc),
      subtitle: `${doc.collected_on ? `Admitted ${doc.collected_on}` : "Admission date unknown"}${
        doc.reported_on ? ` · Discharged ${doc.reported_on}` : ""
      } · ${sectionLabel(doc.section)} · ${getUploaderText(doc)} · ${
        doc.is_verified ? "Verified" : "Unverified"
      }`,
      documentId: doc.id,
      section: doc.section,
      children: [],
      admissionStart: doc.collected_on,
      admissionEnd: doc.reported_on,
      parentRank: 1,
    }));

  const eventParents: AdmissionTimelineItem[] = events.map((event) => ({
    id: `event-${event.id}`,
    type: "event",
    date: event.discharged_at || event.admitted_at || "",
    title: event.title || "Hospitalization",
    subtitle: `${event.status === "active" ? "Active admission" : "Discharged"} · Doctor ${valueOrDash(
      event.doctor_name
    )} · ${valueOrDash(event.department)} · ${valueOrDash(event.hospital_name)}`,
    eventId: event.id,
    section: "care_events",
    children: [],
    admissionStart: event.admitted_at,
    admissionEnd: event.discharged_at,
    parentRank: 2,
  }));

  const admissionParents = [...dischargeParents, ...eventParents]
    .filter((parent) => parent.admissionStart || parent.admissionEnd)
    .sort((a, b) => {
      const dateDifference = compareDatesDescending(a.date, b.date);
      if (dateDifference !== 0) return dateDifference;
      return a.parentRank - b.parentRank;
    });

  const documentToTimelineItem = (doc: DocumentCard): TimelineItem => ({
    id: `doc-${doc.id}`,
    type: "document",
    date: getDocumentClinicalDate(doc),
    title: getDocumentTitle(doc),
    subtitle: `${getDocumentDateLabel(doc)} · ${sectionLabel(doc.section)} · ${getUploaderText(doc)} · ${
      doc.is_verified ? "Verified" : "Unverified"
    }`,
    documentId: doc.id,
    section: doc.section,
  });

  for (const parent of admissionParents) {
    const children = sortedDocuments
      .filter((doc) => {
        if (usedDocumentIds.has(doc.id)) return false;
        if (isDischargeDocument(doc)) return false;

        const belongs = isInsideDateRange(
          getDocumentClinicalDate(doc),
          parent.admissionStart,
          parent.admissionEnd
        );

        if (belongs) usedDocumentIds.add(doc.id);

        return belongs;
      })
      .map(documentToTimelineItem)
      .sort((a, b) => compareDatesAscending(a.date, b.date));

    parent.children = children;
  }

  const parentDocumentIds = new Set(
    admissionParents.map((parent) => parent.documentId).filter((id): id is number => Boolean(id))
  );

  const standaloneDocuments = sortedDocuments
    .filter((doc) => !usedDocumentIds.has(doc.id))
    .filter((doc) => !parentDocumentIds.has(doc.id))
    .map(documentToTimelineItem);

  return [...admissionParents, ...standaloneDocuments].sort((a, b) =>
    compareDatesDescending(a.date, b.date)
  );
}

export default function PatientTimelinePage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    const [meResponse, profileResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
    ]);

    if (meResponse.data.role === "patient") {
      router.replace("/my-records");
      return;
    }

    setCurrentUser(meResponse.data);
    setProfile(normalizeProfile(profileResponse.data));
  }, [patientId, router]);

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient timeline."));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [fetchData]);

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return SECTION_ORDER.flatMap((section) => getSectionDocuments(profile, section));
  }, [profile]);

  const documentById = useMemo(() => {
    const lookup = new Map<number, DocumentCard>();

    for (const doc of allDocuments) {
      lookup.set(doc.id, doc);
    }

    return lookup;
  }, [allDocuments]);

  const timelineItems = useMemo(() => {
    if (!profile) return [];

    return buildTimelineItems(allDocuments, profile.events || []);
  }, [profile, allDocuments]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        total: 0,
        dischargeSummaries: 0,
        bloodwork: 0,
        scans: 0,
        events: 0,
      };
    }

    return {
      total: allDocuments.length,
      dischargeSummaries: getSectionDocuments(profile, "discharge_summary").length,
      bloodwork: getSectionDocuments(profile, "bloodwork").length,
      scans: getSectionDocuments(profile, "scans").length,
      events: profile.events?.length || 0,
    };
  }, [profile, allDocuments]);

  function openTimelineDocument(documentId: number) {
    const doc = documentById.get(documentId);

    if (doc && isDischargeDocument(doc)) {
      router.push(`/documents/${documentId}/discharge`);
      return;
    }

    router.push(`/documents/${documentId}`);
  }

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
          <span className="muted-text">Loading patient timeline...</span>
        </div>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);
  const backPath = currentUser.role === "admin" ? "/assignments" : `/patients/${patientId}`;

  return (
    <AppShell
      user={currentUser}
      title={`${profile.patient.full_name} timeline`}
      subtitle={`ID ${valueOrDash(profile.patient.patient_identifier)} · DOB ${valueOrDash(
        profile.patient.date_of_birth
      )} · Age ${calculatedAge} · Sex ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(backPath)}>
          Back to chart
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
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">Total records</div>
          <div className="stat-card-value">{stats.total}</div>
        </div>

        <div className="stat-card stat-card-accent-orange">
          <div className="stat-card-label">Discharges</div>
          <div className="stat-card-value">{stats.dischargeSummaries}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">Bloodwork</div>
          <div className="stat-card-value">{stats.bloodwork}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">Scans</div>
          <div className="stat-card-value">{stats.scans}</div>
        </div>

        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">Care events</div>
          <div className="stat-card-value">{stats.events}</div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ marginBottom: 18 }}>
          <div className="section-title">Clinical timeline</div>
          <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
            Discharge summaries create admission episodes. Bloodwork, scans, medications, notes, and other records are
            grouped underneath when their clinical date falls inside the admission period.
          </div>
        </div>

        <ClinicalTimeline
          items={timelineItems}
          onOpenDocument={openTimelineDocument}
          emptyText="No timeline activity yet."
        />
      </div>
    </AppShell>
  );
}