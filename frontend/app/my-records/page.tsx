"use client";

/**
 * Patient home - my record.
 *
 * Before: a 14,500px scroll (and 36,000px once the trend panels stopped
 * collapsing) - a 40px hero figure, a featured chart, a pinned column, then
 * every one of ~50 analytes as its own card with two charts mounted at once.
 *
 * After: the same workspace structure the clinician sees, tuned for a
 * patient: Overview / Timeline / Labs / Documents, comfortable density,
 * plainer language, and explanations where a clinician would just get a
 * number. Every capability is preserved - featured trend, pinning (max 3),
 * per-analyte expansion with source reports, section browsing with
 * department/hospital/year filters, pagination, original-file opening,
 * background-upload refresh.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { useUploadManager } from "@/components/upload-provider";
import ClinicalTimeline from "@/components/clinical-timeline";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";
import { hasReferenceBand, Sparkline, TrendChart } from "@/components/ui/trend";
import {
  CellPrimary,
  Column,
  DataTable,
  Dialog,
  EmptyState,
  ErrorNote,
  FilterChip,
  LabValue,
  Menu,
  MenuItem,
  Metric,
  Metrics,
  Notice,
  SectionHead,
  Status,
  TableSkeleton,
  Tabs,
  Toolbar,
} from "@/components/ui";
import {
  IconChevronDown,
  IconChevronRight,
  IconDocument,
  IconExternal,
  IconLab,
  IconPill,
  IconPlus,
  IconUpload,
} from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

/* ── Types ──────────────────────────────────────────────────────────────── */

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
    discharge_summary: DocumentCard[];
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

type AdmissionParent = TimelineItem & {
  admissionStart?: string | null;
  admissionEnd?: string | null;
  parentRank: number;
};

type Medication = {
  id: number;
  name: string;
  status: string;
  dose_strength?: string | null;
  frequency?: string | null;
};

type RecordTab = "overview" | "timeline" | "labs" | "documents";

const SECTION_ORDER: Array<keyof MyProfileResponse["sections"]> = [
  "bloodwork",
  "discharge_summary",
  "scans",
  "hospitalizations",
  "other",
];

const PAGE_SIZE = 20;
const TREND_POINTS = 8;
const MAX_PINNED = 3;

/** Analytes a patient is most likely to be looking for, listed first. */
const TREND_PRIORITY_WORDS = [
  "rbc", "red blood", "hemoglobin", "hgb", "hematocrit", "hct", "mcv", "mch",
  "mchc", "rdw", "wbc", "white blood", "neut", "lymph", "mono", "eosin",
  "baso", "platelet", "plt", "mpv", "glucose", "creatinine", "creatinina",
  "urea", "alt", "ast", "bilirubin", "cholesterol", "triglyceride", "tsh",
];

/* ── Helpers (behaviour unchanged) ──────────────────────────────────────── */

function parseDateTime(value?: string | null) {
  if (!value) return 0;
  const normalized = value.trim();
  const direct = new Date(normalized).getTime();
  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (!match) return 0;

  const day = Number(match[1]);
  const month = Number(match[2]);
  const yearRaw = Number(match[3]);
  const year = yearRaw < 100 ? 2000 + yearRaw : yearRaw;
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

function getYearFromDate(value?: string | null) {
  const time = parseDateTime(value);
  if (!time) return "";
  return String(new Date(time).getFullYear());
}

function formatShortDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function formatLongDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
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
    doctor_access: profile.doctor_access || [],
    events: profile.events || [],
  };
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

function uploaderSubtitle(doc: DocumentCard) {
  const uploader = doc.uploaded_by;
  if (!uploader) return "Unknown source";
  return [uploader.full_name, uploader.department, uploader.hospital_name]
    .filter(Boolean)
    .join(" · ");
}

function isDischargeDocument(doc: DocumentCard | TimelineItem) {
  return (
    doc.section === "discharge_summary" ||
    doc.section === "hospitalizations" ||
    ("report_type" in doc &&
      (doc.report_type === "Discharge summary" || doc.report_type === "discharge_summary"))
  );
}

function getStructuredDocumentPath(doc: DocumentCard | TimelineItem, documentId: number) {
  if (isDischargeDocument(doc)) return `/documents/${documentId}/discharge`;
  return `/documents/${documentId}`;
}

function isInsideDateRange(date?: string | null, start?: string | null, end?: string | null) {
  const dateTime = parseDateTime(date);
  const startTime = parseDateTime(start);
  const endTime = parseDateTime(end);
  if (!dateTime || !startTime) return false;
  if (!endTime) return dateTime >= startTime;
  return dateTime >= startTime && dateTime <= endTime;
}

function getTrendPriority(trend: BloodworkTrend) {
  const name = `${trend.test_key || ""} ${trend.display_name || ""} ${
    trend.canonical_name || ""
  } ${trend.category || ""}`.toLowerCase();
  const index = TREND_PRIORITY_WORDS.findIndex((word) => name.includes(word));
  return index === -1 ? 999 : index;
}

function isFlagAbnormal(flag?: string | null) {
  const value = (flag || "").toLowerCase().trim();
  return Boolean(value) && !["normal", "null", "none", "ok", ""].includes(value);
}

function recentPoints(points: TrendPoint[], limit = TREND_POINTS) {
  return [...points].sort((a, b) => compareDatesAscending(a.date, b.date)).slice(-limit);
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export default function MyRecordsPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const { activeCount, refreshUploadJobs } = useUploadManager();

  const sectionLabels: Record<string, string> = {
    bloodwork: t("bloodwork"),
    discharge_summary: "Discharge summaries",
    scans: t("scans"),
    hospitalizations: "Hospital stays",
    other: "Other",
  };

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [medications, setMedications] = useState<Medication[]>([]);

  const [tab, setTab] = useState<RecordTab>("overview");

  const [activeSection, setActiveSection] =
    useState<keyof MyProfileResponse["sections"]>("bloodwork");
  const [docQuery, setDocQuery] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [labQuery, setLabQuery] = useState("");
  const [labAbnormalOnly, setLabAbnormalOnly] = useState(false);
  const [expandedTrendKey, setExpandedTrendKey] = useState<string | null>(null);
  const [pinnedTrendKeys, setPinnedTrendKeys] = useState<string[]>([]);
  const [pinsLoaded, setPinsLoaded] = useState(false);
  const [featuredPickerOpen, setFeaturedPickerOpen] = useState(false);
  const [featuredOverride, setFeaturedOverride] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function togglePin(testKey: string) {
    setPinnedTrendKeys((prev) => {
      if (prev.includes(testKey)) return prev.filter((key) => key !== testKey);
      if (prev.length >= MAX_PINNED) return prev;
      return [...prev, testKey];
    });
  }

  /* --- Data ------------------------------------------------------------ */

  async function fetchProfile() {
    const response = await api.get<MyProfileResponse>("/my/profile");
    const normalized = normalizeProfile(response.data);
    setProfile(normalized);
    return normalized;
  }

  async function fetchTrends(patientId: number) {
    try {
      const response = await api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`);
      setTrends(Array.isArray(response.data) ? response.data : []);
    } catch {
      setTrends([]);
    }
  }

  async function refreshRecordsSilently() {
    try {
      const profileResponse = await fetchProfile();
      await Promise.all([fetchTrends(profileResponse.patient.id), refreshUploadJobs()]);
    } catch {
      // A silent refresh must never break the page.
    }
  }

  useEffect(() => {
    async function init() {
      let me: NavUser | null = null;
      try {
        const response = await api.get<NavUser>("/auth/me");
        me = response.data;
        setCurrentUser(response.data);
      } catch {
        localStorage.removeItem("access_token");
        router.push("/login");
        return;
      }

      if (me.role !== "patient") {
        router.push(getHomeByRole(me.role));
        return;
      }

      try {
        setError("");
        const profileResponse = await fetchProfile();
        await fetchTrends(profileResponse.patient.id);
        try {
          const medResponse = await api.get<Medication[]>("/my/medications");
          setMedications(medResponse.data);
        } catch {
          // Medications are non-critical - the record still loads.
        }
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadRecords")));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A finished background upload should appear without a manual reload.
  useEffect(() => {
    function handleUploadComplete() {
      void refreshRecordsSilently();
    }
    window.addEventListener("bloodwork-upload-complete", handleUploadComplete);
    return () => window.removeEventListener("bloodwork-upload-complete", handleUploadComplete);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeCount <= 0) return;
    const interval = window.setInterval(() => {
      void refreshRecordsSilently();
    }, 4000);
    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCount]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    setDepartmentFilter("");
    setHospitalFilter("");
    setYearFilter("");
  }, [activeSection]);

  useEffect(() => {
    if (!currentUser || pinsLoaded) return;
    try {
      const stored = localStorage.getItem(`pinned_trends_patient_${currentUser.id}`);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) setPinnedTrendKeys(parsed);
      }
    } catch {
      // ignore corrupt storage
    }
    setPinsLoaded(true);
  }, [currentUser, pinsLoaded]);

  useEffect(() => {
    if (!currentUser || !pinsLoaded) return;
    try {
      localStorage.setItem(
        `pinned_trends_patient_${currentUser.id}`,
        JSON.stringify(pinnedTrendKeys)
      );
    } catch {
      // ignore storage errors
    }
  }, [pinnedTrendKeys, currentUser, pinsLoaded]);

  /* --- Derived --------------------------------------------------------- */

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return SECTION_ORDER.flatMap((section) => profile.sections[section] || []).sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile]);

  const docsForActiveSection = useMemo(() => {
    if (!profile) return [];
    return [...(profile.sections[activeSection] || [])].sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile, activeSection]);

  const filterOptions = useMemo(() => {
    const departments = new Set<string>();
    const hospitals = new Set<string>();
    const years = new Set<string>();

    docsForActiveSection.forEach((doc) => {
      if (doc.uploaded_by?.department) departments.add(doc.uploaded_by.department);
      if (doc.uploaded_by?.hospital_name) hospitals.add(doc.uploaded_by.hospital_name);
      const year = getYearFromDate(getDocumentClinicalDate(doc));
      if (year) years.add(year);
    });

    return {
      departments: Array.from(departments).sort(),
      hospitals: Array.from(hospitals).sort(),
      years: Array.from(years).sort((a, b) => Number(b) - Number(a)),
    };
  }, [docsForActiveSection]);

  const filteredDocsForSection = useMemo(() => {
    const term = docQuery.trim().toLowerCase();
    return docsForActiveSection.filter((doc) => {
      if (departmentFilter && doc.uploaded_by?.department !== departmentFilter) return false;
      if (hospitalFilter && doc.uploaded_by?.hospital_name !== hospitalFilter) return false;
      if (yearFilter && getYearFromDate(getDocumentClinicalDate(doc)) !== yearFilter) return false;
      if (!term) return true;
      return [doc.report_name, doc.filename, doc.lab_name, uploaderSubtitle(doc)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term);
    });
  }, [docsForActiveSection, docQuery, departmentFilter, hospitalFilter, yearFilter]);

  const visibleDocsForSection = filteredDocsForSection.slice(0, visibleCount);

  const myTimeline = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const sortedDocuments = [...allDocuments].sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
    const usedDocumentIds = new Set<number>();

    const dischargeParents: AdmissionParent[] = sortedDocuments
      .filter((doc) => isDischargeDocument(doc))
      .map((doc) => ({
        id: `discharge-${doc.id}`,
        type: "document",
        date: doc.reported_on || doc.collected_on || getDocumentClinicalDate(doc),
        title: valueOrDash(doc.report_name || "Discharge summary"),
        subtitle: `${
          doc.collected_on ? `Admitted ${doc.collected_on}` : "Admission date unknown"
        }${doc.reported_on ? ` · Discharged ${doc.reported_on}` : ""} · ${uploaderSubtitle(doc)}`,
        documentId: doc.id,
        section: doc.section,
        children: [],
        admissionStart: doc.collected_on,
        admissionEnd: doc.reported_on,
        parentRank: 1,
      }));

    const eventParents: AdmissionParent[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`,
      type: "event",
      date: getEventDate(event),
      title: event.title || "Hospital stay",
      subtitle: `${
        event.status === "active" ? t("activeHospitalization") : t("dischargedHospitalization")
      } · ${t("doctor")} ${valueOrDash(event.doctor_name)} · ${valueOrDash(
        event.hospital_name
      )}`,
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
        const difference = compareDatesDescending(a.date, b.date);
        return difference !== 0 ? difference : a.parentRank - b.parentRank;
      });

    const documentToTimelineItem = (doc: DocumentCard): TimelineItem => ({
      id: `doc-${doc.id}`,
      type: "document",
      date: getDocumentClinicalDate(doc),
      title: valueOrDash(doc.report_name || doc.filename),
      // Category is rendered by the timeline row, so it is not repeated here.
      subtitle: `${getDocumentDateLabel(doc)} · ${uploaderSubtitle(doc)}`,
      documentId: doc.id,
      section: doc.section,
    });

    for (const parent of admissionParents) {
      parent.children = sortedDocuments
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
    }

    const parentDocumentIds = new Set(
      admissionParents.map((parent) => parent.documentId).filter((id): id is number => Boolean(id))
    );

    const standaloneDocuments = sortedDocuments
      .filter((doc) => !usedDocumentIds.has(doc.id) && !parentDocumentIds.has(doc.id))
      .map(documentToTimelineItem);

    return [...admissionParents, ...standaloneDocuments].sort((a, b) =>
      compareDatesDescending(a.date, b.date)
    );
  }, [profile, allDocuments, t]);

  const sortedTrends = useMemo(() => {
    return [...trends]
      .map((trend) => {
        const points = recentPoints(trend.points || []);
        const latest = points[points.length - 1] || trend.latest;
        const previous = points[points.length - 2] || trend.previous || null;
        return {
          ...trend,
          points,
          latest,
          previous,
          delta:
            latest && previous ? Number((latest.value - previous.value).toFixed(2)) : trend.delta,
        };
      })
      .sort((a, b) => {
        const priority = getTrendPriority(a) - getTrendPriority(b);
        if (priority !== 0) return priority;
        const abnormalA = isFlagAbnormal(a.latest?.flag) ? 1 : 0;
        const abnormalB = isFlagAbnormal(b.latest?.flag) ? 1 : 0;
        if (abnormalA !== abnormalB) return abnormalB - abnormalA;
        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const visibleTrends = useMemo(() => {
    const term = labQuery.trim().toLowerCase();
    return sortedTrends.filter((trend) => {
      if (labAbnormalOnly && !isFlagAbnormal(trend.latest?.flag)) return false;
      if (!term) return true;
      return [trend.display_name, trend.category, trend.unit]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term);
    });
  }, [sortedTrends, labQuery, labAbnormalOnly]);

  const abnormalCount = useMemo(
    () => sortedTrends.filter((trend) => isFlagAbnormal(trend.latest?.flag)).length,
    [sortedTrends]
  );

  /**
   * Featured: the abnormal result that moved most in percentage terms since
   * the previous reading - the thing a patient most likely wants to see.
   */
  const featuredTrend = useMemo(() => {
    if (!sortedTrends.length) return null;
    if (featuredOverride) {
      return sortedTrends.find((trend) => trend.test_key === featuredOverride) ?? sortedTrends[0];
    }

    const candidates = sortedTrends.filter(
      (trend) =>
        isFlagAbnormal(trend.latest?.flag) &&
        trend.delta != null &&
        trend.points.length > 1 &&
        trend.previous?.value != null &&
        trend.previous.value !== 0
    );

    if (!candidates.length) return null;

    return candidates.reduce((max, trend) => {
      const pct = Math.abs(trend.delta! / trend.previous!.value);
      const maxPct = Math.abs(max.delta! / max.previous!.value);
      return pct > maxPct ? trend : max;
    });
  }, [sortedTrends, featuredOverride]);

  const pinnedTrends = useMemo(
    () =>
      pinnedTrendKeys
        .map((key) => sortedTrends.find((trend) => trend.test_key === key))
        .filter((trend): trend is (typeof sortedTrends)[0] => Boolean(trend)),
    [pinnedTrendKeys, sortedTrends]
  );

  const activeMeds = medications.filter(
    (med) => med.status === "active" || med.status === "as_needed"
  );

  /* --- Actions --------------------------------------------------------- */

  async function openOriginal(documentId: number) {
    try {
      setError("");
      const response = await api.get(`/documents/${documentId}/file`, { responseType: "blob" });
      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string" ? rawContentType : "application/octet-stream";
      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);
      window.open(fileUrl, "_blank", "noopener,noreferrer");
      setTimeout(() => window.URL.revokeObjectURL(fileUrl), 60_000);
    } catch (err) {
      setError(getErrorMessage(err, t("failedOpenOriginal")));
    }
  }

  function openStructuredDocument(doc: DocumentCard) {
    router.push(getStructuredDocumentPath(doc, doc.id));
  }

  function openTimelineDocument(documentId: number) {
    const found = allDocuments.find((doc) => doc.id === documentId);
    router.push(found ? getStructuredDocumentPath(found, documentId) : `/documents/${documentId}`);
  }

  /* --- Columns --------------------------------------------------------- */

  const documentColumns: Column<DocumentCard>[] = useMemo(
    () => [
      {
        key: "doc",
        header: "Document",
        sortable: true,
        sortValue: (row) => row.report_name || row.filename,
        render: (row) => (
          <CellPrimary
            title={valueOrDash(row.report_name || row.filename)}
            sub={
              <>
                {sectionLabels[row.section] || row.section}
                {row.lab_name ? ` · ${row.lab_name}` : ""}
                {row.referring_doctor ? ` · Dr. ${row.referring_doctor}` : ""}
              </>
            }
          />
        ),
      },
      {
        key: "date",
        header: "Date",
        width: 110,
        sortable: true,
        sortValue: (row) => parseDateTime(getDocumentClinicalDate(row)),
        render: (row) => (
          <span
            className="tnum"
            style={{ color: "var(--text-2)" }}
            title={getDocumentDateLabel(row)}
          >
            {formatShortDate(getDocumentClinicalDate(row))}
          </span>
        ),
      },
      {
        key: "source",
        header: "From",
        hideBelow: 1100,
        render: (row) => <span className="b-cell-sub">{uploaderSubtitle(row)}</span>,
      },
      {
        key: "status",
        header: "Status",
        width: 120,
        hideBelow: 640,
        render: (row) =>
          row.is_verified ? (
            <Status tone="ok">{t("verified")}</Status>
          ) : (
            <Status tone="muted">{t("unverified")}</Status>
          ),
      },
      {
        key: "actions",
        header: <span className="sr-only">Actions</span>,
        width: 104,
        render: (row) => (
          <div className="b-row-actions">
            <button
              type="button"
              className="b-btn b-btn-secondary b-btn-sm"
              onClick={(event) => {
                event.stopPropagation();
                openStructuredDocument(row);
              }}
            >
              {t("open")}
            </button>
            <Menu label="More actions">
              <MenuItem icon={<IconExternal size={13} />} onClick={() => openOriginal(row.id)}>
                {t("openOriginal")}
              </MenuItem>
            </Menu>
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t]
  );

  /* --- Render ---------------------------------------------------------- */

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={7} columns={4} />
        </div>
      </main>
    );
  }

  const tabs = [
    { key: "overview", label: t("navOverview") },
    { key: "timeline", label: t("navTimeline"), count: myTimeline.length || undefined },
    { key: "labs", label: t("navLabs"), count: sortedTrends.length || undefined },
    { key: "documents", label: t("navDocuments"), count: allDocuments.length || undefined },
  ];

  const pinnedStrip = pinnedTrends.length ? (
    <section className="b-surface">
      <SectionHead
        title={t("pinnedTrends")}
        actions={
          <span className="b-range">
            {pinnedTrends.length}/{MAX_PINNED}
          </span>
        }
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 1,
          background: "var(--border)",
          borderTop: "1px solid var(--border)",
        }}
      >
        {pinnedTrends.map((trend) => (
          <div key={trend.test_key} style={{ background: "var(--surface)", padding: "12px 14px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span className="b-cell-title" style={{ flex: 1 }}>
                {trend.display_name}
              </span>
              <button
                type="button"
                className="b-btn b-btn-ghost b-btn-sm"
                onClick={() => togglePin(trend.test_key)}
              >
                {t("unpin")}
              </button>
            </div>
            <div style={{ marginTop: 3, fontSize: 17, fontWeight: 600 }}>
              <LabValue
                value={valueOrDash(trend.latest?.value_display)}
                unit={trend.unit}
                flag={trend.latest?.flag}
              />
            </div>
            <div className="b-range">{formatShortDate(trend.latest?.date)}</div>
            <div style={{ marginTop: 6 }}>
              <Sparkline
                points={trend.points}
                tone={isFlagAbnormal(trend.latest?.flag) ? "danger" : "brand"}
                height={24}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  ) : null;

  const featuredPanel = featuredTrend ? (
    <section className="b-surface">
      <SectionHead
        title={featuredTrend.display_name}
        description={t("featuredLabTrendLabel")}
        actions={
          <>
            <button
              type="button"
              className="b-btn b-btn-secondary b-btn-sm"
              onClick={() => setFeaturedPickerOpen(true)}
            >
              {t("navChange")}
              <IconChevronDown size={12} />
            </button>
            <button
              type="button"
              className="b-btn b-btn-secondary b-btn-sm"
              onClick={() => togglePin(featuredTrend.test_key)}
              disabled={
                !pinnedTrendKeys.includes(featuredTrend.test_key) &&
                pinnedTrendKeys.length >= MAX_PINNED
              }
            >
              {pinnedTrendKeys.includes(featuredTrend.test_key) ? t("unpin") : t("pin")}
            </button>
          </>
        }
      />

      <div className="b-section-body">
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "var(--s6)",
            flexWrap: "wrap",
            marginBottom: "var(--s3)",
          }}
        >
          <div>
            <div className="b-label">{t("latest")}</div>
            <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.025em" }}>
              <LabValue
                value={valueOrDash(featuredTrend.latest?.value_display)}
                unit={featuredTrend.unit}
                flag={featuredTrend.latest?.flag}
              />
            </div>
            <div className="b-range">{formatLongDate(featuredTrend.latest?.date)}</div>
          </div>

          <div>
            <div className="b-label">{t("previous")}</div>
            <div className="tnum" style={{ fontSize: 15, color: "var(--text-2)" }}>
              {valueOrDash(featuredTrend.previous?.value_display)}
            </div>
          </div>

          <div>
            <div className="b-label">{t("delta")}</div>
            <div
              className="tnum"
              style={{
                fontSize: 15,
                fontWeight: 600,
                color:
                  featuredTrend.delta == null
                    ? "var(--muted)"
                    : featuredTrend.delta > 0
                    ? "var(--danger)"
                    : "var(--info)",
              }}
            >
              {featuredTrend.delta == null
                ? "—"
                : `${featuredTrend.delta > 0 ? "+" : ""}${featuredTrend.delta}`}
            </div>
          </div>

          {featuredTrend.latest?.reference_range ? (
            <div>
              <div className="b-label">{t("ref")}</div>
              <div className="tnum" style={{ fontSize: 15, color: "var(--text-2)" }}>
                {featuredTrend.latest.reference_range}
              </div>
            </div>
          ) : null}
        </div>

        <TrendChart
          points={featuredTrend.points}
          unit={featuredTrend.unit}
          referenceRange={featuredTrend.latest?.reference_range}
          height={210}
          formatDate={formatShortDate}
          onPointClick={(documentId) => router.push(`/documents/${documentId}`)}
        />

        {/* Patients get the plain-language explanation a clinician does not
            need: the shaded band is the normal range for this test. */}
        {hasReferenceBand(featuredTrend.latest?.reference_range) ? (
          <p className="b-meta" style={{ marginTop: "var(--s2)" }}>
            The shaded band shows the normal range for this test. A result outside it is not
            necessarily a problem — discuss it with your doctor.
          </p>
        ) : null}
      </div>
    </section>
  ) : null;

  return (
    <AppShell
      user={currentUser}
      title={t("myRecords")}
      subtitle={profile.patient.full_name}
      density="comfortable"
      banner={
        <div className="b-ctx">
          <div className="b-ctx-tabs">
            <Tabs
              tabs={tabs}
              activeTab={tab}
              onChange={(key) => setTab(key as RecordTab)}
              ariaLabel={t("myRecords")}
            />
          </div>
        </div>
      }
      rightContent={
        <button
          type="button"
          className="b-btn b-btn-primary"
          onClick={() => router.push("/my-records/upload")}
        >
          <IconUpload size={14} />
          {t("uploadDocuments")}
        </button>
      }
    >
      <div className="b-stack b-view-enter" key={tab}>
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        {activeCount > 0 ? (
          <Notice>
            <span className="b-status b-status-processing" />
            {activeCount === 1
              ? "1 document is being processed. It will appear here automatically."
              : `${activeCount} documents are being processed. They will appear here automatically.`}
          </Notice>
        ) : null}

        {/* ── Overview ──────────────────────────────────────────────────── */}
        {tab === "overview" ? (
          <>
            <Metrics>
              <Metric label={t("records")} value={allDocuments.length} />
              <Metric label={t("bloodwork")} value={profile.sections.bloodwork.length} />
              <Metric
                label="Results outside range"
                value={abnormalCount}
                tone={abnormalCount > 0 ? "alert" : undefined}
              />
              <Metric label="Hospital stays" value={profile.sections.discharge_summary.length} />
              <Metric label={t("myMedications")} value={activeMeds.length} />
            </Metrics>

            {pinnedStrip}

            {featuredPanel ?? (
              <section className="b-surface">
                <EmptyState
                  icon={<IconLab size={17} />}
                  title={t("noBloodworkDataYet")}
                  description={t("featuredLabTrendEmpty")}
                  actions={
                    <button
                      type="button"
                      className="b-btn b-btn-primary"
                      onClick={() => router.push("/my-records/upload")}
                    >
                      <IconUpload size={14} />
                      {t("uploadFirstDocument")}
                    </button>
                  }
                />
              </section>
            )}

            <section className="b-surface">
              <SectionHead
                title={t("myMedications")}
                count={activeMeds.length}
                description={t("medCardSubtitle")}
                actions={
                  <>
                    <button
                      type="button"
                      className="b-btn b-btn-secondary b-btn-sm"
                      onClick={() => router.push("/my-records/medications")}
                    >
                      {t("viewAll").replace(" →", "")}
                    </button>
                    <button
                      type="button"
                      className="b-btn b-btn-secondary b-btn-sm"
                      onClick={() => router.push("/my-records/medications/new")}
                    >
                      <IconPlus size={13} />
                      {t("add")}
                    </button>
                  </>
                }
              />
              <div className="b-section-body b-section-body-flush">
                {activeMeds.length ? (
                  <div className="b-list">
                    {activeMeds.slice(0, 5).map((med) => (
                      <button
                        key={med.id}
                        type="button"
                        className="b-list-row"
                        onClick={() => router.push(`/my-records/medications/${med.id}`)}
                      >
                        <span className="b-list-main">
                          <span className="b-list-title">{med.name}</span>
                          <span className="b-list-sub">
                            {[med.dose_strength, med.frequency].filter(Boolean).join(" · ") ||
                              t("medNoDoseFrequency")}
                          </span>
                        </span>
                        <span className="b-list-trail">
                          <Status tone={med.status === "active" ? "ok" : "info"}>
                            {med.status === "active" ? t("active") : t("medStatusAsNeeded")}
                          </Status>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={<IconPill size={17} />}
                    title={t("noMedicationsYet")}
                    actions={
                      <button
                        type="button"
                        className="b-btn b-btn-secondary"
                        onClick={() => router.push("/my-records/medications/new")}
                      >
                        <IconPlus size={14} />
                        {t("add")}
                      </button>
                    }
                  />
                )}
              </div>
            </section>

            <section className="b-surface">
              <SectionHead
                title={t("myTimeline")}
                description={t("timelineCardDesc")}
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => setTab("timeline")}
                  >
                    {t("viewAll").replace(" →", "")}
                    <IconChevronRight size={12} />
                  </button>
                }
              />
              <div className="b-section-body b-section-body-flush">
                <ClinicalTimeline
                  items={myTimeline}
                  maxItems={6}
                  onOpenDocument={openTimelineDocument}
                  emptyText={t("noTimelineActivity")}
                />
              </div>
            </section>

            <section className="b-surface">
              <SectionHead
                title="Who can see my record"
                count={profile.doctor_access.length}
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => router.push("/my-records/access")}
                  >
                    {t("myAccess")}
                    <IconChevronRight size={12} />
                  </button>
                }
              />
              <div className="b-section-body b-section-body-flush">
                {profile.doctor_access.length ? (
                  <div className="b-list">
                    {profile.doctor_access.slice(0, 5).map((doctor) => (
                      <div
                        key={doctor.doctor_user_id}
                        className="b-list-row"
                        style={{ cursor: "default" }}
                      >
                        <span className="b-list-main">
                          <span className="b-list-title">{doctor.doctor_name}</span>
                          <span className="b-list-sub">
                            {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                          </span>
                        </span>
                        <span className="b-list-trail">
                          <Status tone="ok">Access granted</Status>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title="No one else has access"
                    description="Only you can see this record right now."
                  />
                )}
              </div>
            </section>
          </>
        ) : null}

        {/* ── Timeline ──────────────────────────────────────────────────── */}
        {tab === "timeline" ? (
          <section className="b-surface">
            <SectionHead
              title={t("myTimeline")}
              count={myTimeline.length}
              description={t("timelineCardDesc")}
              actions={
                <button
                  type="button"
                  className="b-btn b-btn-secondary b-btn-sm"
                  onClick={() => router.push("/my-records/timeline")}
                >
                  {t("seeFullTimeline")}
                  <IconExternal size={12} />
                </button>
              }
            />
            <div className="b-section-body b-section-body-flush">
              <ClinicalTimeline
                items={myTimeline}
                maxItems={50}
                onOpenDocument={openTimelineDocument}
                onSeeFullTimeline={() => router.push("/my-records/timeline")}
                showSeeFullTimeline
                emptyText={t("noTimelineActivity")}
              />
            </div>
          </section>
        ) : null}

        {/* ── Labs ──────────────────────────────────────────────────────── */}
        {tab === "labs" ? (
          <>
            {pinnedStrip}
            {featuredPanel}

            <section className="b-surface">
              <SectionHead
                title={t("bloodworkTrends")}
                count={sortedTrends.length}
                description={t("pinSortedHint")}
              />

              <Toolbar
                search={labQuery}
                onSearch={setLabQuery}
                searchPlaceholder="Search results…"
                filters={
                  <FilterChip
                    label="Outside range"
                    count={abnormalCount}
                    active={labAbnormalOnly}
                    onClick={() => setLabAbnormalOnly((value) => !value)}
                  />
                }
                count={visibleTrends.length}
                countLabel="results"
              />

              {!visibleTrends.length ? (
                <EmptyState
                  icon={<IconLab size={17} />}
                  title={t("noNumericTrends")}
                  description={t("noBloodworkDataYet")}
                />
              ) : (
                <div>
                  <div
                    className="b-trend-row only-desktop"
                    style={{
                      minHeight: 32,
                      background: "var(--surface-2)",
                      color: "var(--muted)",
                      fontSize: "var(--fs-xs)",
                      cursor: "default",
                    }}
                  >
                    <span>Test</span>
                    <span style={{ textAlign: "right" }}>{t("latest")}</span>
                    <span style={{ textAlign: "right" }}>{t("delta")}</span>
                    <span>Over time</span>
                    <span style={{ textAlign: "right" }}>Date</span>
                    <span />
                  </div>

                  {visibleTrends.map((trend) => {
                    const abnormal = isFlagAbnormal(trend.latest?.flag);
                    const expanded = expandedTrendKey === trend.test_key;
                    const pinned = pinnedTrendKeys.includes(trend.test_key);

                    return (
                      <div key={trend.test_key}>
                        <button
                          type="button"
                          className="b-trend-row"
                          aria-expanded={expanded}
                          onClick={() => setExpandedTrendKey(expanded ? null : trend.test_key)}
                        >
                          <span style={{ minWidth: 0 }}>
                            <span className="b-cell-title" style={{ display: "block" }}>
                              {trend.display_name}
                            </span>
                            <span className="b-cell-sub" style={{ display: "block" }}>
                              {valueOrDash(trend.category)}
                              {trend.unit ? ` · ${trend.unit}` : ""}
                            </span>
                          </span>

                          <span style={{ textAlign: "right" }}>
                            <LabValue
                              value={valueOrDash(trend.latest?.value_display)}
                              flag={trend.latest?.flag}
                            />
                          </span>

                          <span
                            className="tnum"
                            style={{
                              textAlign: "right",
                              fontSize: "var(--fs-xs)",
                              color:
                                trend.delta == null || trend.delta === 0
                                  ? "var(--faint)"
                                  : trend.delta > 0
                                  ? "var(--danger)"
                                  : "var(--info)",
                            }}
                          >
                            {trend.delta == null
                              ? "—"
                              : trend.delta === 0
                              ? "0"
                              : `${trend.delta > 0 ? "+" : ""}${trend.delta}`}
                          </span>

                          <span className="b-trend-spark">
                            <Sparkline
                              points={trend.points}
                              tone={abnormal ? "danger" : "brand"}
                              height={26}
                            />
                          </span>

                          <span
                            className="b-range"
                            style={{ textAlign: "right", whiteSpace: "nowrap" }}
                          >
                            {formatShortDate(trend.latest?.date)}
                          </span>

                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                              color: "var(--faint)",
                            }}
                          >
                            {pinned ? (
                              <span className="b-chip b-chip-brand">{t("pinnedBadge")}</span>
                            ) : null}
                            <IconChevronDown
                              size={13}
                              style={{
                                transform: expanded ? "rotate(180deg)" : "none",
                                transition: "transform var(--dur-2) var(--ease)",
                              }}
                            />
                          </span>
                        </button>

                        {expanded ? (
                          <div
                            className="b-view-enter"
                            style={{
                              padding: "var(--s3) var(--s4) var(--s4)",
                              background: "var(--surface-2)",
                              borderBottom: "1px solid var(--border)",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                gap: "var(--s2)",
                                justifyContent: "flex-end",
                                marginBottom: "var(--s2)",
                              }}
                            >
                              <button
                                type="button"
                                className="b-btn b-btn-secondary b-btn-sm"
                                onClick={() => togglePin(trend.test_key)}
                                disabled={!pinned && pinnedTrendKeys.length >= MAX_PINNED}
                              >
                                {pinned ? t("unpin") : t("pin")}
                              </button>
                            </div>

                            <TrendChart
                              points={trend.points}
                              unit={trend.unit}
                              referenceRange={trend.latest?.reference_range}
                              height={190}
                              formatDate={formatShortDate}
                              onPointClick={(documentId) => router.push(`/documents/${documentId}`)}
                            />

                            <div className="b-label" style={{ marginTop: "var(--s4)" }}>
                              Where these results come from
                            </div>
                            <div className="b-list" style={{ marginTop: 4 }}>
                              {[...trend.points]
                                .sort((a, b) => compareDatesDescending(a.date, b.date))
                                .map((point, index) => (
                                  <button
                                    key={`${trend.test_key}-${point.document_id}-${index}`}
                                    type="button"
                                    className="b-list-row"
                                    style={{ paddingLeft: 0, paddingRight: 0 }}
                                    onClick={() => router.push(`/documents/${point.document_id}`)}
                                  >
                                    <span className="b-list-main">
                                      <span className="b-list-title">
                                        {valueOrDash(
                                          point.report_name || `Report ${point.document_id}`
                                        )}
                                      </span>
                                      <span className="b-list-sub">
                                        {formatLongDate(point.date)}
                                        {point.reference_range
                                          ? ` · ${t("ref")} ${point.reference_range}`
                                          : ""}
                                      </span>
                                    </span>
                                    <span className="b-list-trail">
                                      <LabValue
                                        value={valueOrDash(point.value_display)}
                                        unit={trend.unit}
                                        flag={point.flag}
                                      />
                                      <IconChevronRight size={13} className="b-list-chevron" />
                                    </span>
                                  </button>
                                ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </>
        ) : null}

        {/* ── Documents ─────────────────────────────────────────────────── */}
        {tab === "documents" ? (
          <section className="b-surface">
            <SectionHead
              title={t("navDocuments")}
              count={allDocuments.length}
              actions={
                <button
                  type="button"
                  className="b-btn b-btn-primary b-btn-sm"
                  onClick={() => router.push("/my-records/upload")}
                >
                  <IconUpload size={13} />
                  {t("uploadDocuments")}
                </button>
              }
            />

            <Toolbar
              search={docQuery}
              onSearch={setDocQuery}
              searchPlaceholder="Search documents…"
              filters={SECTION_ORDER.map((section) => (
                <FilterChip
                  key={section}
                  label={sectionLabels[section] || section}
                  count={profile.sections[section].length}
                  active={activeSection === section}
                  onClick={() => setActiveSection(section)}
                />
              ))}
              count={filteredDocsForSection.length}
              countLabel="documents"
            />

            {filterOptions.departments.length ||
            filterOptions.hospitals.length ||
            filterOptions.years.length ? (
              <div className="b-toolbar" style={{ minHeight: 42, background: "var(--surface-2)" }}>
                {filterOptions.hospitals.length ? (
                  <select
                    className="b-input"
                    value={hospitalFilter}
                    onChange={(event) => setHospitalFilter(event.target.value)}
                    aria-label="Hospital"
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 140 }}
                  >
                    <option value="">All hospitals</option>
                    {filterOptions.hospitals.map((hospital) => (
                      <option key={hospital} value={hospital}>
                        {hospital}
                      </option>
                    ))}
                  </select>
                ) : null}

                {filterOptions.departments.length ? (
                  <select
                    className="b-input"
                    value={departmentFilter}
                    onChange={(event) => setDepartmentFilter(event.target.value)}
                    aria-label="Department"
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 140 }}
                  >
                    <option value="">All departments</option>
                    {filterOptions.departments.map((department) => (
                      <option key={department} value={department}>
                        {department}
                      </option>
                    ))}
                  </select>
                ) : null}

                {filterOptions.years.length ? (
                  <select
                    className="b-input"
                    value={yearFilter}
                    onChange={(event) => setYearFilter(event.target.value)}
                    aria-label="Year"
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 110 }}
                  >
                    <option value="">All years</option>
                    {filterOptions.years.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))}
                  </select>
                ) : null}

                {departmentFilter || hospitalFilter || yearFilter ? (
                  <button
                    type="button"
                    className="b-btn b-btn-ghost b-btn-sm"
                    onClick={() => {
                      setDepartmentFilter("");
                      setHospitalFilter("");
                      setYearFilter("");
                    }}
                  >
                    {t("navClear")}
                  </button>
                ) : null}
              </div>
            ) : null}

            <DataTable
              rows={visibleDocsForSection}
              columns={documentColumns}
              rowKey={(row) => row.id}
              onRowClick={openStructuredDocument}
              caption={`${sectionLabels[activeSection]} documents`}
              emptyState={
                <EmptyState
                  icon={<IconDocument size={17} />}
                  title={t("noRecordsInSection")}
                  actions={
                    <button
                      type="button"
                      className="b-btn b-btn-secondary"
                      onClick={() => router.push("/my-records/upload")}
                    >
                      <IconUpload size={14} />
                      {t("uploadDocuments")}
                    </button>
                  }
                />
              }
            />

            {visibleCount < filteredDocsForSection.length ? (
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  padding: "var(--s3)",
                  borderTop: "1px solid var(--border)",
                }}
              >
                <button
                  type="button"
                  className="b-btn b-btn-secondary b-btn-sm"
                  onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                >
                  {t("showMore")}
                </button>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>

      <Dialog
        open={featuredPickerOpen}
        onClose={() => setFeaturedPickerOpen(false)}
        title={t("featuredLabTrendLabel")}
      >
        <div className="b-list">
          {sortedTrends.map((trend) => (
            <button
              key={trend.test_key}
              type="button"
              className="b-list-row"
              aria-current={trend.test_key === featuredTrend?.test_key ? "page" : undefined}
              onClick={() => {
                setFeaturedOverride(trend.test_key);
                setFeaturedPickerOpen(false);
              }}
            >
              <span className="b-list-main">
                <span className="b-list-title">{trend.display_name}</span>
                <span className="b-list-sub">
                  {valueOrDash(trend.category)}
                  {trend.unit ? ` · ${trend.unit}` : ""}
                </span>
              </span>
              <span className="b-list-trail">
                <LabValue
                  value={valueOrDash(trend.latest?.value_display)}
                  flag={trend.latest?.flag}
                />
              </span>
            </button>
          ))}
        </div>
      </Dialog>
    </AppShell>
  );
}
