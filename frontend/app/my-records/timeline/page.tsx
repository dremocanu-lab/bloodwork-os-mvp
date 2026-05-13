"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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

type PatientEvent = {
  id: number;
  status: string;
  title: string;
  hospital_name?: string | null;
  department?: string | null;
  admitted_at: string;
  discharged_at?: string | null;
  doctor_name?: string | null;
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
    bloodwork?: DocumentCard[];
    discharge_summary?: DocumentCard[];
    medications?: DocumentCard[];
    scans?: DocumentCard[];
    hospitalizations?: DocumentCard[];
    other?: DocumentCard[];
  };
  events?: PatientEvent[];
  doctor_access?: unknown[];
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
  "other",
] as const;

const SECTION_FILTERS = [
  { value: "all", label: "All" },
  { value: "bloodwork", label: "Bloodwork" },
  { value: "discharge_summary", label: "Discharge" },
  { value: "scans", label: "Scans" },
  { value: "medications", label: "Medications" },
  { value: "other", label: "Other" },
] as const;

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "verified", label: "Verified" },
  { value: "unverified", label: "Unverified" },
] as const;

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
  if (today.getDate() < dob.getDate()) months -= 1;
  if (months < 0) { years -= 1; months += 12; }
  if (years < 0) return "—";
  return `${years}y ${months}m`;
}

function normalizeProfile(profile: MyProfileResponse): MyProfileResponse {
  return {
    ...profile,
    sections: {
      bloodwork: profile.sections.bloodwork || [],
      discharge_summary: profile.sections.discharge_summary || [],
      medications: profile.sections.medications || [],
      scans: profile.sections.scans || [],
      hospitalizations: profile.sections.hospitalizations || [],
      other: profile.sections.other || [],
    },
    events: profile.events || [],
    doctor_access: profile.doctor_access || [],
  };
}

function sectionLabel(section: string) {
  if (section === "bloodwork") return "Bloodwork";
  if (section === "discharge_summary") return "Discharge summary";
  if (section === "medications") return "Medications";
  if (section === "scans") return "Scans";
  if (section === "hospitalizations") return "Hospitalization";
  return "Other";
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
  const details = [doc.uploaded_by.full_name, doc.uploaded_by.department, doc.uploaded_by.hospital_name].filter(Boolean);
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

function buildTimelineItems(
  documents: DocumentCard[],
  events: PatientEvent[],
  t: (key: string) => string
): TimelineItem[] {
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
        doc.is_verified ? t("verified") : t("unverified")
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
    subtitle: `${event.status === "active" ? t("activeHospitalization") : t("dischargedHospitalization")} · ${
      event.doctor_name ? `Doctor ${event.doctor_name}` : "Doctor unknown"
    } · ${valueOrDash(event.department)} · ${valueOrDash(event.hospital_name)}`,
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
      const diff = compareDatesDescending(a.date, b.date);
      return diff !== 0 ? diff : a.parentRank - b.parentRank;
    });
  const documentToTimelineItem = (doc: DocumentCard): TimelineItem => ({
    id: `doc-${doc.id}`,
    type: "document",
    date: getDocumentClinicalDate(doc),
    title: getDocumentTitle(doc),
    subtitle: `${getDocumentDateLabel(doc)} · ${sectionLabel(doc.section)} · ${getUploaderText(doc)} · ${
      doc.is_verified ? t("verified") : t("unverified")
    }`,
    documentId: doc.id,
    section: doc.section,
  });
  for (const parent of admissionParents) {
    const children = sortedDocuments
      .filter((doc) => {
        if (usedDocumentIds.has(doc.id)) return false;
        if (isDischargeDocument(doc)) return false;
        const belongs = isInsideDateRange(getDocumentClinicalDate(doc), parent.admissionStart, parent.admissionEnd);
        if (belongs) usedDocumentIds.add(doc.id);
        return belongs;
      })
      .map(documentToTimelineItem)
      .sort((a, b) => compareDatesAscending(a.date, b.date));
    parent.children = children;
  }
  const parentDocumentIds = new Set(
    admissionParents.map((p) => p.documentId).filter((id): id is number => Boolean(id))
  );
  const standaloneDocuments = sortedDocuments
    .filter((doc) => !usedDocumentIds.has(doc.id))
    .filter((doc) => !parentDocumentIds.has(doc.id))
    .map(documentToTimelineItem);
  return [...admissionParents, ...standaloneDocuments].sort((a, b) =>
    compareDatesDescending(a.date, b.date)
  );
}

function sectionPillStyle(value: string, active: boolean) {
  if (!active) {
    return {
      background: "transparent",
      color: "var(--muted)",
      border: "1px solid var(--border)",
    };
  }
  if (value === "all") return { background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))", color: "var(--primary)", border: "1px solid color-mix(in srgb, var(--primary) 30%, transparent)" };
  if (value === "bloodwork") return { background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)" };
  if (value === "discharge_summary") return { background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))", color: "var(--primary)", border: "1px solid color-mix(in srgb, var(--primary) 30%, transparent)" };
  if (value === "scans") return { background: "var(--warn-bg)", color: "var(--warn-text)", border: "1px solid var(--warn-border)" };
  if (value === "medications") return { background: "var(--success-bg)", color: "var(--success-text)", border: "1px solid var(--success-border)" };
  return { background: "var(--panel-2)", color: "var(--muted)", border: "1px solid var(--border)" };
}

function statusPillStyle(value: string, active: boolean) {
  if (!active) return { background: "transparent", color: "var(--muted)", border: "1px solid var(--border)" };
  if (value === "verified") return { background: "var(--success-bg)", color: "var(--success-text)", border: "1px solid var(--success-border)" };
  if (value === "unverified") return { background: "var(--warn-bg)", color: "var(--warn-text)", border: "1px solid var(--warn-border)" };
  return { background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))", color: "var(--primary)", border: "1px solid color-mix(in srgb, var(--primary) 30%, transparent)" };
}

function StatBadge({ count, label, color = "var(--foreground)" }: { count: number; label: string; color?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
      <span style={{ fontSize: 22, fontWeight: 950, letterSpacing: "-0.05em", lineHeight: 1, color }}>{count}</span>
      <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--muted)", lineHeight: 1 }}>{label}</span>
    </div>
  );
}

export default function MyRecordsTimelinePage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [searchQuery, setSearchQuery] = useState("");
  const [sectionFilter, setSectionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [yearFilter, setYearFilter] = useState("all");

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const [meResponse, profileResponse] = await Promise.all([
          api.get<CurrentUser>("/auth/me"),
          api.get<MyProfileResponse>("/my/profile"),
        ]);
        if (meResponse.data.role !== "patient") {
          router.replace(meResponse.data.role === "doctor" ? "/my-patients" : "/assignments");
          return;
        }
        setCurrentUser(meResponse.data);
        setProfile(normalizeProfile(profileResponse.data));
      } catch (err) {
        setError(getErrorMessage(err, "Could not load timeline."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return SECTION_ORDER.flatMap((section) => profile.sections[section] || []);
  }, [profile]);

  const documentById = useMemo(() => {
    const lookup = new Map<number, DocumentCard>();
    for (const doc of allDocuments) lookup.set(doc.id, doc);
    return lookup;
  }, [allDocuments]);

  const availableYears = useMemo(() => {
    const years = new Set<string>();
    for (const doc of allDocuments) {
      const ts = parseDateTime(getDocumentClinicalDate(doc));
      if (ts) {
        const y = new Date(ts).getFullYear();
        if (y > 1900) years.add(String(y));
      }
    }
    return Array.from(years).sort((a, b) => Number(b) - Number(a));
  }, [allDocuments]);

  const stats = useMemo(() => ({
    total: allDocuments.length,
    admissions: allDocuments.filter(isDischargeDocument).length,
    bloodwork: allDocuments.filter((d) => d.section === "bloodwork").length,
    unverified: allDocuments.filter((d) => !d.is_verified).length,
  }), [allDocuments]);

  const filteredDocuments = useMemo(() => {
    return allDocuments.filter((doc) => {
      if (sectionFilter !== "all" && doc.section !== sectionFilter) return false;
      if (statusFilter === "verified" && !doc.is_verified) return false;
      if (statusFilter === "unverified" && doc.is_verified) return false;
      if (yearFilter !== "all") {
        const ts = parseDateTime(getDocumentClinicalDate(doc));
        if (!ts || String(new Date(ts).getFullYear()) !== yearFilter) return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const haystack = [
          getDocumentTitle(doc),
          doc.lab_name || "",
          doc.section,
          doc.report_type || "",
        ].join(" ").toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [allDocuments, sectionFilter, statusFilter, yearFilter, searchQuery]);

  const filteredTimelineItems = useMemo(() => {
    if (!profile) return [];
    return buildTimelineItems(filteredDocuments, profile.events || [], t);
  }, [profile, filteredDocuments, t]);

  const hasActiveFilters = sectionFilter !== "all" || statusFilter !== "all" || yearFilter !== "all" || searchQuery.trim() !== "";

  function clearFilters() {
    setSectionFilter("all");
    setStatusFilter("all");
    setYearFilter("all");
    setSearchQuery("");
  }

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
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22 }}>
          <p className="muted-text">Loading timeline...</p>
        </div>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);

  return (
    <AppShell
      user={currentUser}
      title="Full timeline"
      subtitle={`${valueOrDash(profile.patient.full_name)} · DOB ${valueOrDash(profile.patient.date_of_birth)} · Age ${calculatedAge} · Sex ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/my-records")}>
          Back to records
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      <div className="soft-card" style={{ padding: 0, overflow: "hidden" }}>

        {/* Header: title + stat badges */}
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid var(--border)",
            background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 7%, var(--panel)), var(--panel))",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 20,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 19, fontWeight: 950, letterSpacing: "-0.04em" }}>Clinical timeline</div>
            <div className="muted-text" style={{ marginTop: 5, fontSize: 13, lineHeight: 1.5, maxWidth: 520 }}>
              Discharge summaries create admission episodes. Bloodwork, scans, and other records group inside admissions by date.
            </div>
          </div>
          <div style={{ display: "flex", gap: 20, alignItems: "center", flexShrink: 0 }}>
            <StatBadge count={stats.total} label="records" />
            <div style={{ width: 1, height: 28, background: "var(--border)" }} />
            <StatBadge count={stats.admissions} label="admissions" color="var(--primary)" />
            <div style={{ width: 1, height: 28, background: "var(--border)" }} />
            <StatBadge count={stats.bloodwork} label="bloodwork" color="var(--danger-text)" />
            {stats.unverified > 0 && (
              <>
                <div style={{ width: 1, height: 28, background: "var(--border)" }} />
                <StatBadge count={stats.unverified} label="unverified" color="var(--warn-text)" />
              </>
            )}
          </div>
        </div>

        {/* Filter bar */}
        <div style={{ padding: "14px 24px", borderBottom: "1px solid var(--border)", background: "var(--panel-2)", display: "flex", flexDirection: "column", gap: 11 }}>

          {/* Search + year + count */}
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ position: "relative", flex: "1 1 200px", minWidth: 0 }}>
              <span style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)", color: "var(--muted)", fontSize: 15, pointerEvents: "none", lineHeight: 1 }}>
                ⌕
              </span>
              <input
                type="text"
                className="text-input"
                placeholder="Search records..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: 36, fontSize: 13, height: 36 }}
              />
            </div>

            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(e.target.value)}
              className="text-input"
              style={{ fontSize: 13, minWidth: 120, flex: "0 0 auto", height: 36 }}
            >
              <option value="all">All years</option>
              {availableYears.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <span className="muted-text" style={{ fontSize: 12, fontWeight: 900, whiteSpace: "nowrap" }}>
              {hasActiveFilters
                ? `${filteredDocuments.length} of ${allDocuments.length} records`
                : `${allDocuments.length} records`}
            </span>

            {hasActiveFilters && (
              <button
                type="button"
                onClick={clearFilters}
                style={{
                  padding: "5px 12px",
                  borderRadius: 999,
                  border: "1px solid var(--border)",
                  background: "transparent",
                  color: "var(--muted)",
                  fontSize: 12,
                  fontWeight: 900,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                Clear
              </button>
            )}
          </div>

          {/* Section + status pills */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {SECTION_FILTERS.map(({ value, label }) => {
                const s = sectionPillStyle(value, sectionFilter === value);
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSectionFilter(value)}
                    style={{
                      padding: "5px 13px",
                      borderRadius: 999,
                      border: s.border,
                      background: s.background,
                      color: s.color,
                      fontSize: 12,
                      fontWeight: 900,
                      cursor: "pointer",
                      transition: "background 130ms ease, color 130ms ease, border-color 130ms ease",
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {STATUS_FILTERS.map(({ value, label }) => {
                const s = statusPillStyle(value, statusFilter === value);
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setStatusFilter(value)}
                    style={{
                      padding: "5px 13px",
                      borderRadius: 999,
                      border: s.border,
                      background: s.background,
                      color: s.color,
                      fontSize: 12,
                      fontWeight: 900,
                      cursor: "pointer",
                      transition: "background 130ms ease, color 130ms ease, border-color 130ms ease",
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Timeline */}
        <div style={{ padding: 24 }}>
          <ClinicalTimeline
            items={filteredTimelineItems}
            onOpenDocument={openTimelineDocument}
            emptyText={
              hasActiveFilters
                ? "No records match your filters. Try adjusting or clearing them."
                : "No timeline activity yet."
            }
          />
        </div>
      </div>
    </AppShell>
  );
}
