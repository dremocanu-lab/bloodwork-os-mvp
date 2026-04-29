"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import ClinicalTimeline from "@/components/clinical-timeline";
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
    medications?: DocumentCard[];
    scans?: DocumentCard[];
    hospitalizations?: DocumentCard[];
    other?: DocumentCard[];
  };
  doctor_access?: unknown[];
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
};

const SECTION_ORDER: Array<keyof NonNullable<PatientProfileResponse["sections"]>> = [
  "bloodwork",
  "medications",
  "scans",
  "hospitalizations",
  "notes",
  "other",
];

const REPORT_TYPE_OPTIONS: Array<{
  key: keyof NonNullable<PatientProfileResponse["sections"]> | "events";
  label: string;
}> = [
  { key: "bloodwork", label: "Bloodwork" },
  { key: "scans", label: "Scans" },
  { key: "medications", label: "Medications" },
  { key: "hospitalizations", label: "Hospitalizations" },
  { key: "notes", label: "Clinical notes" },
  { key: "other", label: "Other" },
  { key: "events", label: "Care events" },
];

function parseDateTime(value?: string | null) {
  if (!value) return 0;

  const normalized = value.trim();
  const direct = new Date(normalized).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);

  if (match) {
    const day = Number(match[1]);
    const month = Number(match[2]);
    const yearRaw = Number(match[3]);
    const year = yearRaw < 100 ? 2000 + yearRaw : yearRaw;
    const parsed = new Date(year, month - 1, day).getTime();

    if (!Number.isNaN(parsed)) return parsed;
  }

  return 0;
}

function compareDatesDescending(a: string, b: string) {
  const aTime = parseDateTime(a);
  const bTime = parseDateTime(b);

  if (aTime || bTime) return bTime - aTime;

  return (b || "").localeCompare(a || "");
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

  return `${years} ${years === 1 ? "year" : "years"} ${months} ${
    months === 1 ? "month" : "months"
  }`;
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

function getEventDate(event: PatientEvent) {
  return event.discharged_at || event.admitted_at || "";
}

function getYearFromDate(value?: string | null) {
  const time = parseDateTime(value);
  if (!time) return "";

  return String(new Date(time).getFullYear());
}

function uploaderSubtitle(doc: DocumentCard) {
  const uploader = doc.uploaded_by;

  if (!uploader) return "Uploaded by unknown user";

  const details = [uploader.full_name, uploader.department, uploader.hospital_name].filter(Boolean);

  return `Uploaded by ${details.join(" · ")}`;
}

function normalizeProfile(profile: PatientProfileResponse): PatientProfileResponse {
  return {
    ...profile,
    sections: {
      bloodwork: profile.sections.bloodwork || [],
      medications: profile.sections.medications || [],
      scans: profile.sections.scans || [],
      hospitalizations: profile.sections.hospitalizations || [],
      notes: profile.sections.notes || [],
      other: profile.sections.other || [],
    },
    events: profile.events || [],
    doctor_access: profile.doctor_access || [],
  };
}

function YearDropdown({
  value,
  years,
  onChange,
}: {
  value: string;
  years: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label style={{ display: "grid", gap: 8, minWidth: 210 }}>
      <span className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
        Year
      </span>

      <div style={{ position: "relative" }}>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="text-input"
          style={{
            appearance: "none",
            width: "100%",
            borderRadius: 18,
            padding: "14px 44px 14px 16px",
            fontWeight: 950,
            letterSpacing: "-0.02em",
            cursor: "pointer",
            background:
              "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
            border: "1px solid color-mix(in srgb, var(--primary) 24%, var(--border))",
            color: "var(--foreground)",
            boxShadow: "0 14px 34px rgba(15, 23, 42, 0.08)",
          }}
        >
          <option value="">All years</option>
          {years.map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </select>

        <span
          style={{
            position: "absolute",
            right: 14,
            top: "50%",
            transform: "translateY(-50%)",
            pointerEvents: "none",
            width: 28,
            height: 28,
            borderRadius: 10,
            display: "grid",
            placeItems: "center",
            background: "color-mix(in srgb, var(--primary) 12%, transparent)",
            color: "var(--primary)",
            fontWeight: 950,
          }}
        >
          ▾
        </span>
      </div>
    </label>
  );
}

function ReportTypeMultiFilter({
  selectedTypes,
  onToggle,
  onClear,
}: {
  selectedTypes: string[];
  onToggle: (type: string) => void;
  onClear: () => void;
}) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
        Report types
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {REPORT_TYPE_OPTIONS.map((option) => {
          const active = selectedTypes.includes(option.key);

          return (
            <button
              key={option.key}
              type="button"
              onClick={() => onToggle(option.key)}
              className={active ? "primary-btn" : "secondary-btn"}
              style={{
                borderRadius: 999,
                padding: "10px 13px",
                fontWeight: 900,
                fontSize: 13,
              }}
            >
              {active ? "✓ " : ""}
              {option.label}
            </button>
          );
        })}

        {selectedTypes.length > 0 && (
          <button
            type="button"
            className="secondary-btn"
            onClick={onClear}
            style={{
              borderRadius: 999,
              padding: "10px 13px",
              fontWeight: 900,
              fontSize: 13,
            }}
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

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

export default function PatientFullTimelinePage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;

  const sectionLabels: Record<string, string> = {
    bloodwork: t("bloodwork"),
    medications: "Medications",
    scans: t("scans"),
    hospitalizations: "Hospitalizations",
    notes: "Clinical notes",
    other: "Other",
  };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [selectedYear, setSelectedYear] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");
        const me = meResponse.data;

        setCurrentUser(me);

        if (me.role === "patient") {
          router.push("/my-records");
          return;
        }

        const profileResponse = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
        setProfile(normalizeProfile(profileResponse.data));
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load timeline."));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [router, patientId]);

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return SECTION_ORDER.flatMap((section) => profile.sections[section] || []).sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile]);

  const timelineItems = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => ({
      id: `doc-${doc.id}`,
      type: "document",
      date: getDocumentClinicalDate(doc),
      title: valueOrDash(doc.report_name || doc.filename),
      subtitle: `${getDocumentDateLabel(doc)} · ${sectionLabels[doc.section] || doc.section} · ${uploaderSubtitle(
        doc
      )} · ${doc.is_verified ? t("verified") : t("unverified")}`,
      documentId: doc.id,
      section: doc.section,
    }));

    const eventItems: TimelineItem[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`,
      type: "event",
      date: getEventDate(event),
      title: event.title,
      subtitle: `${event.status === "active" ? t("activeHospitalization") : t("dischargedHospitalization")} · ${t(
        "doctor"
      )} ${valueOrDash(event.doctor_name)}`,
      eventId: event.id,
      section: "events",
    }));

    return [...documentItems, ...eventItems].sort((a, b) => compareDatesDescending(a.date, b.date));
  }, [profile, allDocuments, t]);

  const availableYears = useMemo(() => {
    const years = new Set<string>();

    timelineItems.forEach((item) => {
      const year = getYearFromDate(item.date);
      if (year) years.add(year);
    });

    return Array.from(years).sort((a, b) => Number(b) - Number(a));
  }, [timelineItems]);

  const filteredTimelineItems = useMemo(() => {
    return timelineItems.filter((item) => {
      const typeMatches = selectedTypes.length === 0 || selectedTypes.includes(item.section || "");
      const yearMatches = !selectedYear || getYearFromDate(item.date) === selectedYear;

      return typeMatches && yearMatches;
    });
  }, [timelineItems, selectedTypes, selectedYear]);

  function toggleReportType(type: string) {
    setSelectedTypes((current) => {
      if (current.includes(type)) {
        return current.filter((item) => item !== type);
      }

      return [...current, type];
    });
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
        <div
          className="soft-card-tight"
          style={{
            padding: 22,
            display: "flex",
            gap: 12,
            alignItems: "center",
          }}
        >
          <Spinner size={20} />
          <span className="muted-text">Loading full timeline...</span>
        </div>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);

  return (
    <AppShell
      user={currentUser}
      title="Full Timeline"
      subtitle={`${valueOrDash(profile.patient.full_name)} · DOB ${valueOrDash(
        profile.patient.date_of_birth
      )} · Age ${calculatedAge} · Sex ${valueOrDash(profile.patient.sex)}`}
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
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            marginBottom: 22,
          }}
        >
          <div>
            <div className="section-title" style={{ marginBottom: 8 }}>
              Complete Patient Timeline
            </div>

            <div className="muted-text" style={{ lineHeight: 1.6 }}>
              All documents and care events sorted by collected/test date when available.
            </div>
          </div>

          <button
            type="button"
            className="secondary-btn"
            onClick={() => router.push(`/patients/${patientId}`)}
            style={{
              whiteSpace: "nowrap",
            }}
          >
            Back to chart
          </button>
        </div>

        <div
          className="soft-card-tight"
          style={{
            padding: 18,
            marginBottom: 20,
            background: "var(--panel-2)",
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) auto",
            gap: 18,
            alignItems: "end",
          }}
        >
          <ReportTypeMultiFilter
            selectedTypes={selectedTypes}
            onToggle={toggleReportType}
            onClear={() => setSelectedTypes([])}
          />

          <YearDropdown value={selectedYear} years={availableYears} onChange={setSelectedYear} />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            alignItems: "center",
            marginBottom: 14,
          }}
        >
          <div className="muted-text" style={{ fontWeight: 850 }}>
            Showing {filteredTimelineItems.length} of {timelineItems.length} timeline items
          </div>

          {(selectedTypes.length > 0 || selectedYear) && (
            <button
              type="button"
              className="secondary-btn"
              onClick={() => {
                setSelectedTypes([]);
                setSelectedYear("");
              }}
            >
              Reset filters
            </button>
          )}
        </div>

        <ClinicalTimeline
          items={filteredTimelineItems}
          onOpenDocument={(documentId) => router.push(`/documents/${documentId}`)}
          emptyText="No timeline activity matches these filters."
          scrollable
          maxHeight={780}
        />
      </div>
    </AppShell>
  );
}