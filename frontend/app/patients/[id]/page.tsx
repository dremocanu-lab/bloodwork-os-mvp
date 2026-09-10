"use client";

/**
 * Doctor patient record - the clinical workspace.
 *
 * Before: one 16,000px scroll. Patient header card, quick-action cards,
 * review banner, featured trend, timeline, medications, documents and then
 * roughly forty individual lab-trend cards, each with its own chart, all
 * stacked on a single page. Finding anything meant scrolling past everything.
 *
 * After: a persistent patient workspace. Identity and actions live in a
 * sticky 52px context bar; the record is divided into Overview, Timeline,
 * Labs, Documents and Medications tabs. Every capability of the old page is
 * preserved - featured trend with its selector, trend pinning (max 3),
 * expandable per-analyte charts with their source reports, document section
 * filters, department/hospital/year filters, pagination, note editing,
 * original-file opening, assigned doctors, refresh - just reachable in two
 * clicks instead of two thousand pixels.
 *
 * The Labs tab is the biggest change: forty chart cards became one dense
 * sortable table with inline sparklines, expanding in place to the full
 * figure. That is what makes a long record reviewable.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import AppShell from "@/components/app-shell";
import PatientContext from "@/components/patient-context";
import ClinicalTimeline from "@/components/clinical-timeline";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";
import type { BloodworkTrend, TrendPoint } from "@/lib/analytes/types";
import { enrichBloodworkTrend } from "@/lib/analytes/match";
import { Sparkline, TrendChart } from "@/components/ui/trend";
import {
  CellPrimary,
  Chip,
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
  Toolbar,
} from "@/components/ui";
import {
  IconAlert,
  IconChart,
  IconChevronDown,
  IconChevronRight,
  IconClipboard,
  IconDocument,
  IconExternal,
  IconLab,
  IconPill,
  IconPlus,
  IconTimeline,
  IconUpload,
} from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

/* ── Types ──────────────────────────────────────────────────────────────── */

type UploadedBy = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
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
  document_type?: string | null;
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
  documentType?: string | null;
  children?: TimelineItem[];
};

type AdmissionTimelineItem = TimelineItem & {
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
  reason?: string | null;
  is_uncertain: boolean;
  official_match_status?: string | null;
  route_form?: string | null;
};

type WorkspaceTab = "overview" | "timeline" | "labs" | "documents" | "medications";

const PAGE_SIZE = 20;
const TREND_POINT_LIMIT = 8;
const MAX_PINNED = 3;

const SECTION_ORDER = [
  "bloodwork",
  "discharge_summary",
  "scans",
  "hospitalizations",
  "notes",
  "other",
] as const;

type SectionKey = (typeof SECTION_ORDER)[number];

/* ── Date + document helpers (unchanged behaviour) ──────────────────────── */

function parseDateTime(value?: string | null) {
  if (!value) return 0;
  const normalized = value.trim();
  const direct = new Date(normalized).getTime();
  if (!Number.isNaN(direct)) return direct;
  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);
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

function formatDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatShortDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "2-digit" });
}

function getYear(value?: string | null) {
  const time = parseDateTime(value);
  if (!time) return "";
  return String(new Date(time).getFullYear());
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

function getSectionDocuments(profile: PatientProfileResponse | null, section: SectionKey) {
  if (!profile) return [];
  return profile.sections[section] || [];
}

function sectionLabel(section: string) {
  if (section === "bloodwork") return "Bloodwork";
  if (section === "discharge_summary") return "Discharge";
  if (section === "medications") return "Medications";
  if (section === "scans") return "Scans";
  if (section === "hospitalizations") return "Admissions";
  if (section === "notes") return "Notes";
  return "Other";
}

function getDocumentClinicalDate(doc: DocumentCard) {
  if (doc.section === "discharge_summary") {
    return doc.reported_on || doc.collected_on || doc.generated_on || doc.created_at || "";
  }
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

function hasAbnormal(doc: DocumentCard) {
  return Boolean(doc.has_abnormal || doc.has_abnormal_labs);
}

function needsDoctorReview(doc: DocumentCard) {
  return hasAbnormal(doc) && !doc.reviewed_by_current_doctor;
}

function getDocumentTitle(doc: DocumentCard) {
  return doc.report_name || doc.filename || `Document ${doc.id}`;
}

function getUploaderText(doc: DocumentCard) {
  if (!doc.uploaded_by) return "Unknown source";
  const details = [
    doc.uploaded_by.full_name,
    doc.uploaded_by.department,
    doc.uploaded_by.hospital_name,
  ].filter(Boolean);
  return details.join(" · ");
}

function isDischargeDocument(doc: DocumentCard | TimelineItem) {
  return (
    doc.section === "discharge_summary" ||
    ("section" in doc && doc.section === "hospitalizations") ||
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

function getRecentTrendPoints(points: TrendPoint[]) {
  return [...points]
    .sort((a, b) => compareDatesAscending(a.date, b.date))
    .slice(-TREND_POINT_LIMIT);
}

function isTrendAbnormal(trend: BloodworkTrend) {
  const flag = trend.latest?.flag;
  return Boolean(flag && String(flag).trim().toLowerCase() !== "normal");
}

function medStatusLabel(status: string) {
  if (status === "active") return "Active";
  if (status === "as_needed") return "As needed";
  if (status === "paused") return "Paused";
  return "Stopped";
}

function medStatusTone(status: string) {
  if (status === "active") return "ok" as const;
  if (status === "as_needed") return "info" as const;
  return "muted" as const;
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { language, t } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [medications, setMedications] = useState<Medication[]>([]);

  const [tab, setTab] = useState<WorkspaceTab>("overview");

  const [activeSection, setActiveSection] = useState<SectionKey>("bloodwork");
  const [docQuery, setDocQuery] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [labQuery, setLabQuery] = useState("");
  const [labAbnormalOnly, setLabAbnormalOnly] = useState(false);
  const [expandedTrend, setExpandedTrend] = useState<string | null>(null);
  const [pinnedTrendKeys, setPinnedTrendKeys] = useState<string[]>([]);
  const [pinsLoaded, setPinsLoaded] = useState(false);
  const [featuredTrendKey, setFeaturedTrendKey] = useState<string | null>(null);
  const [featuredPickerOpen, setFeaturedPickerOpen] = useState(false);

  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const isDoctor = currentUser?.role === "doctor";
  const isAdmin = currentUser?.role === "admin";

  /* --- Data ------------------------------------------------------------- */

  const fetchProfile = useCallback(async () => {
    const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
    const normalized = normalizeProfile(response.data);
    setProfile(normalized);
    return normalized;
  }, [patientId]);

  const fetchTrends = useCallback(async () => {
    try {
      const response = await api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`);
      const raw = Array.isArray(response.data) ? response.data : [];
      setTrends(raw.map((trend) => enrichBloodworkTrend(trend)));
    } catch {
      setTrends([]);
    }
  }, [patientId]);

  const fetchMedications = useCallback(async () => {
    try {
      const response = await api.get<Medication[]>(`/patients/${patientId}/medications`);
      setMedications(Array.isArray(response.data) ? response.data : []);
    } catch {
      setMedications([]);
    }
  }, [patientId]);

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const me = await api.get<NavUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") {
          router.replace("/my-records");
          return;
        }
        await Promise.all([fetchProfile(), fetchTrends(), fetchMedications()]);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient chart."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [fetchProfile, fetchTrends, fetchMedications, router]);

  // Deep links from the workspace nav (?tab=labs) open the right section.
  useEffect(() => {
    const requested = searchParams?.get("tab");
    if (
      requested === "labs" ||
      requested === "documents" ||
      requested === "medications" ||
      requested === "timeline" ||
      requested === "overview"
    ) {
      setTab(requested);
    }
  }, [searchParams]);

  async function refreshPage() {
    try {
      setRefreshing(true);
      setError("");
      await Promise.all([fetchProfile(), fetchTrends(), fetchMedications()]);
    } catch (err) {
      setError(getErrorMessage(err, "Could not refresh patient chart."));
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    setDepartmentFilter("");
    setHospitalFilter("");
    setYearFilter("");
    setVisibleCount(PAGE_SIZE);
  }, [activeSection]);

  /* --- Pinned trends (per doctor, per patient) -------------------------- */

  useEffect(() => {
    if (!currentUser || pinsLoaded) return;
    try {
      const stored = localStorage.getItem(
        `pinned_trends_${currentUser.id}_patient_${patientId}`
      );
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) setPinnedTrendKeys(parsed);
      }
    } catch {
      // ignore corrupt storage
    }
    setPinsLoaded(true);
  }, [currentUser, patientId, pinsLoaded]);

  useEffect(() => {
    if (!currentUser || !pinsLoaded) return;
    try {
      localStorage.setItem(
        `pinned_trends_${currentUser.id}_patient_${patientId}`,
        JSON.stringify(pinnedTrendKeys)
      );
    } catch {
      // ignore storage errors
    }
  }, [pinnedTrendKeys, currentUser, patientId, pinsLoaded]);

  function togglePin(key: string) {
    setPinnedTrendKeys((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      if (prev.length >= MAX_PINNED) return prev;
      return [...prev, key];
    });
  }

  /* --- Derived --------------------------------------------------------- */

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return SECTION_ORDER.flatMap((section) => getSectionDocuments(profile, section)).sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile]);

  const documentsForSection = useMemo(() => {
    if (!profile) return [];
    return [...getSectionDocuments(profile, activeSection)].sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile, activeSection]);

  const filterOptions = useMemo(() => {
    const departments = new Set<string>();
    const hospitals = new Set<string>();
    const years = new Set<string>();
    documentsForSection.forEach((doc) => {
      if (doc.uploaded_by?.department) departments.add(doc.uploaded_by.department);
      if (doc.uploaded_by?.hospital_name) hospitals.add(doc.uploaded_by.hospital_name);
      const year = getYear(getDocumentClinicalDate(doc));
      if (year) years.add(year);
    });
    return {
      departments: Array.from(departments).sort(),
      hospitals: Array.from(hospitals).sort(),
      years: Array.from(years).sort((a, b) => Number(b) - Number(a)),
    };
  }, [documentsForSection]);

  const filteredDocuments = useMemo(() => {
    const term = docQuery.trim().toLowerCase();
    return documentsForSection.filter((doc) => {
      if (departmentFilter && doc.uploaded_by?.department !== departmentFilter) return false;
      if (hospitalFilter && doc.uploaded_by?.hospital_name !== hospitalFilter) return false;
      if (yearFilter && getYear(getDocumentClinicalDate(doc)) !== yearFilter) return false;
      if (!term) return true;
      return [getDocumentTitle(doc), doc.lab_name, doc.referring_doctor, getUploaderText(doc)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term);
    });
  }, [documentsForSection, docQuery, departmentFilter, hospitalFilter, yearFilter]);

  const visibleDocuments = filteredDocuments.slice(0, visibleCount);

  const documentById = useMemo(() => {
    const lookup = new Map<number, DocumentCard>();
    for (const doc of allDocuments) lookup.set(doc.id, doc);
    return lookup;
  }, [allDocuments]);

  const timelineItems = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];
    const sortedDocuments = [...allDocuments].sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
    const usedDocumentIds = new Set<number>();

    const dischargeParents: AdmissionTimelineItem[] = sortedDocuments
      .filter((doc) => isDischargeDocument(doc))
      .map((doc) => ({
        id: `discharge-${doc.id}`,
        type: "document" as const,
        date: doc.reported_on || doc.collected_on || getDocumentClinicalDate(doc),
        title: getDocumentTitle(doc),
        subtitle: `${
          doc.collected_on ? `Admitted ${doc.collected_on}` : "Admission date unknown"
        }${doc.reported_on ? ` · Discharged ${doc.reported_on}` : ""} · ${sectionLabel(
          doc.section
        )} · ${getUploaderText(doc)} · ${doc.is_verified ? "Verified" : "Unverified"}`,
        documentId: doc.id,
        section: doc.section,
        documentType: doc.document_type,
        children: [],
        admissionStart: doc.collected_on,
        admissionEnd: doc.reported_on,
        parentRank: 1,
      }));

    const eventParents: AdmissionTimelineItem[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`,
      type: "event" as const,
      date: event.discharged_at || event.admitted_at || "",
      title: event.title || "Hospitalization",
      subtitle: `${
        event.status === "active" ? "Active admission" : "Discharged"
      } · Doctor ${valueOrDash(event.doctor_name)} · ${valueOrDash(
        event.department
      )} · ${valueOrDash(event.hospital_name)}`,
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
      // The timeline row renders the category itself, so it is not repeated
      // here - the subtitle carries only verification state and source.
      subtitle: `${doc.is_verified ? "Verified" : "Unverified"} · ${getUploaderText(doc)}`,
      documentId: doc.id,
      section: doc.section,
      documentType: doc.document_type,
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
  }, [profile, allDocuments]);

  const sortedTrends = useMemo(() => {
    return [...trends]
      .filter((trend) => trend.points?.length)
      .map((trend) => {
        const recentPoints = getRecentTrendPoints(trend.points);
        const latest = recentPoints[recentPoints.length - 1] || trend.latest;
        const previous = recentPoints[recentPoints.length - 2] || trend.previous || null;
        const delta = latest && previous ? Number((latest.value - previous.value).toFixed(2)) : null;
        return { ...trend, points: recentPoints, latest, previous, delta };
      })
      .sort((a, b) => {
        const abnormalA = isTrendAbnormal(a) ? 1 : 0;
        const abnormalB = isTrendAbnormal(b) ? 1 : 0;
        if (abnormalA !== abnormalB) return abnormalB - abnormalA;
        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const visibleTrends = useMemo(() => {
    const term = labQuery.trim().toLowerCase();
    return sortedTrends.filter((trend) => {
      if (labAbnormalOnly && !isTrendAbnormal(trend)) return false;
      if (!term) return true;
      return [trend.display_name, trend.category, trend.unit]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term);
    });
  }, [sortedTrends, labQuery, labAbnormalOnly]);

  const featuredTrend = useMemo(() => {
    if (!sortedTrends.length) return null;
    if (featuredTrendKey) {
      return sortedTrends.find((trend) => trend.test_key === featuredTrendKey) || sortedTrends[0];
    }
    // Largest absolute change among abnormal results, matching prior behaviour.
    const abnormals = sortedTrends.filter(isTrendAbnormal);
    const pool = abnormals.length ? abnormals : sortedTrends;
    return pool.reduce(
      (best, trend) => (Math.abs(trend.delta || 0) > Math.abs(best.delta || 0) ? trend : best),
      pool[0]
    );
  }, [sortedTrends, featuredTrendKey]);

  const stats = useMemo(() => {
    if (!profile) return { total: 0, bloodwork: 0, hospitalizations: 0, needsReview: 0, abnormal: 0 };
    return {
      total: allDocuments.length,
      bloodwork: getSectionDocuments(profile, "bloodwork").length,
      hospitalizations:
        getSectionDocuments(profile, "discharge_summary").length +
        getSectionDocuments(profile, "hospitalizations").length +
        (profile.events || []).length,
      needsReview: allDocuments.filter(needsDoctorReview).length,
      abnormal: sortedTrends.filter(isTrendAbnormal).length,
    };
  }, [profile, allDocuments, sortedTrends]);

  const activeEvents = useMemo(
    () => (profile?.events || []).filter((event) => event.status === "active"),
    [profile]
  );

  const activeMeds = medications.filter((med) => med.status === "active");
  const asNeededMeds = medications.filter((med) => med.status === "as_needed");
  const pausedStopped = medications.filter(
    (med) => med.status === "paused" || med.status === "stopped"
  );
  const uncertainMeds = medications.filter((med) => med.is_uncertain);

  /* --- Actions --------------------------------------------------------- */

  function openStructuredDocument(doc: DocumentCard) {
    router.push(getStructuredDocumentPath(doc, doc.id));
  }

  function openTimelineDocument(documentId: number) {
    const doc = documentById.get(documentId);
    router.push(doc ? getStructuredDocumentPath(doc, documentId) : `/documents/${documentId}`);
  }

  async function openOriginal(documentId: number) {
    try {
      setOpeningId(documentId);
      setError("");
      const response = await api.get(`/documents/${documentId}/file`, { responseType: "blob" });
      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string" ? rawContentType : "application/octet-stream";
      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);
      window.open(fileUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => window.URL.revokeObjectURL(fileUrl), 60_000);
    } catch (err) {
      setError(getErrorMessage(err, "Could not open original file."));
    } finally {
      setOpeningId(null);
    }
  }

  /* --- Columns --------------------------------------------------------- */

  const documentColumns: Column<DocumentCard>[] = useMemo(
    () => [
      {
        key: "doc",
        header: "Document",
        sortable: true,
        sortValue: (row) => getDocumentTitle(row),
        render: (row) => (
          <CellPrimary
            title={getDocumentTitle(row)}
            sub={
              <>
                {sectionLabel(row.section)}
                {row.lab_name ? ` · ${row.lab_name}` : ""}
                {row.sample_type ? ` · ${row.sample_type}` : ""}
                {row.referring_doctor ? ` · Dr. ${row.referring_doctor}` : ""}
                {row.section === "notes" && row.note_preview
                  ? ` · "${row.note_preview.slice(0, 60)}${
                      row.note_preview.length > 60 ? "…" : ""
                    }"`
                  : ""}
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
          <span className="tnum" style={{ color: "var(--text-2)" }} title={getDocumentDateLabel(row)}>
            {formatShortDate(getDocumentClinicalDate(row))}
          </span>
        ),
      },
      {
        key: "source",
        header: "Source",
        hideBelow: 1100,
        render: (row) => <span className="b-cell-sub">{getUploaderText(row)}</span>,
      },
      {
        key: "status",
        header: "Status",
        width: 140,
        sortable: true,
        sortValue: (row) => (needsDoctorReview(row) ? 0 : row.is_verified ? 1 : 2),
        hideBelow: 640,
        render: (row) =>
          needsDoctorReview(row) ? (
            <Status tone="danger">Needs review</Status>
          ) : row.is_verified ? (
            <Status tone="ok">Verified</Status>
          ) : (
            <Status tone="muted">Unverified</Status>
          ),
      },
      {
        key: "actions",
        header: <span className="sr-only">Actions</span>,
        width: 108,
        render: (row) => {
          const isNote = row.section === "notes";
          const editableNote =
            isDoctor && isNote && (row.can_edit_note || row.uploaded_by?.id === currentUser?.id);

          return (
            <div className="b-row-actions">
              <button
                type="button"
                className="b-btn b-btn-secondary b-btn-sm"
                onClick={(event) => {
                  event.stopPropagation();
                  openStructuredDocument(row);
                }}
              >
                Open
              </button>

              <Menu label="More document actions">
                {!isNote ? (
                  <MenuItem
                    icon={<IconExternal size={13} />}
                    onClick={() => openOriginal(row.id)}
                  >
                    {openingId === row.id ? "Opening…" : "View original"}
                  </MenuItem>
                ) : null}
                {editableNote ? (
                  <MenuItem
                    onClick={() => router.push(`/patients/${patientId}/notes/${row.id}/edit`)}
                  >
                    Edit note
                  </MenuItem>
                ) : null}
              </Menu>
            </div>
          );
        },
      },
    ],
    [currentUser?.id, isDoctor, openingId, patientId, router]
  );

  /* --- Render ---------------------------------------------------------- */

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={8} columns={4} />
        </div>
      </main>
    );
  }

  const hasActiveAdmission = activeEvents.length > 0;
  const backHref = isAdmin ? "/assignments" : "/my-patients";

  const tabs = [
    { key: "overview", label: t("navOverview") },
    { key: "timeline", label: t("navTimeline"), count: timelineItems.length || undefined },
    { key: "labs", label: t("navLabs"), count: sortedTrends.length || undefined },
    { key: "documents", label: t("navDocuments"), count: allDocuments.length || undefined },
    { key: "medications", label: t("navMedications"), count: medications.length || undefined },
  ];

  /** Pinned trends: a compact strip rather than a 300px sidebar that
      re-flowed the whole page the moment a clinician pinned anything. */
  const pinnedStrip = pinnedTrendKeys.length ? (
    <section className="b-surface">
      <SectionHead
        title="Pinned"
        actions={
          <span className="b-range">
            {pinnedTrendKeys.length}/{MAX_PINNED}
          </span>
        }
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
          gap: 1,
          background: "var(--border)",
          borderTop: "1px solid var(--border)",
        }}
      >
        {pinnedTrendKeys.map((key) => {
          const trend = sortedTrends.find((item) => item.test_key === key);
          if (!trend) return null;

          return (
            <div key={key} style={{ background: "var(--surface)", padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
                <span className="b-cell-title" style={{ flex: 1 }}>
                  {trend.display_name}
                </span>
                <button
                  type="button"
                  className="b-btn b-btn-ghost b-btn-sm"
                  onClick={() => togglePin(key)}
                >
                  Unpin
                </button>
              </div>
              <div style={{ marginTop: 2 }}>
                <LabValue
                  value={trend.latest?.value_display ?? "—"}
                  unit={trend.unit}
                  flag={trend.latest?.flag}
                />
                {trend.delta != null && trend.delta !== 0 ? (
                  <span
                    className="b-flag"
                    style={{
                      marginLeft: 6,
                      color: trend.delta > 0 ? "var(--danger)" : "var(--info)",
                    }}
                  >
                    {trend.delta > 0 ? "↑" : "↓"}
                    {Math.abs(trend.delta)}
                  </span>
                ) : null}
              </div>
              <div style={{ marginTop: 4 }}>
                <Sparkline
                  points={trend.points}
                  tone={isTrendAbnormal(trend) ? "danger" : "brand"}
                  height={22}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  ) : null;

  const featuredPanel = featuredTrend ? (
    <section className="b-surface">
      <SectionHead
        title={featuredTrend.display_name}
        description={`${featuredTrend.category || "Lab result"}${
          featuredTrend.unit ? ` · ${featuredTrend.unit}` : ""
        }${
          featuredTrend.latest?.reference_range
            ? ` · ref ${featuredTrend.latest.reference_range}`
            : ""
        }`}
        actions={
          <>
            {sortedTrends.length > 1 ? (
              <button
                type="button"
                className="b-btn b-btn-secondary b-btn-sm"
                onClick={() => setFeaturedPickerOpen(true)}
              >
                Change
                <IconChevronDown size={12} />
              </button>
            ) : null}
            <button
              type="button"
              className={`b-btn b-btn-sm ${
                pinnedTrendKeys.includes(featuredTrend.test_key)
                  ? "b-btn-secondary"
                  : "b-btn-secondary"
              }`}
              onClick={() => togglePin(featuredTrend.test_key)}
              disabled={
                !pinnedTrendKeys.includes(featuredTrend.test_key) &&
                pinnedTrendKeys.length >= MAX_PINNED
              }
            >
              {pinnedTrendKeys.includes(featuredTrend.test_key) ? "Unpin" : "Pin"}
            </button>
          </>
        }
      />

      <div className="b-section-body">
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "var(--s5)",
            flexWrap: "wrap",
            marginBottom: "var(--s3)",
          }}
        >
          <div>
            <div className="b-label">Latest</div>
            <div style={{ fontSize: 21, fontWeight: 600, letterSpacing: "-0.025em" }}>
              <LabValue
                value={featuredTrend.latest?.value_display ?? "—"}
                unit={featuredTrend.unit}
                flag={featuredTrend.latest?.flag}
              />
            </div>
            <div className="b-range">{formatDate(featuredTrend.latest?.date)}</div>
          </div>

          <div>
            <div className="b-label">Previous</div>
            <div className="tnum" style={{ fontSize: 15, color: "var(--text-2)" }}>
              {featuredTrend.previous?.value_display ?? "—"}
            </div>
          </div>

          <div>
            <div className="b-label">Change</div>
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
                    : featuredTrend.delta < 0
                    ? "var(--info)"
                    : "var(--muted)",
              }}
            >
              {featuredTrend.delta == null
                ? "—"
                : `${featuredTrend.delta > 0 ? "+" : ""}${featuredTrend.delta}`}
            </div>
          </div>
        </div>

        <TrendChart
          points={featuredTrend.points}
          unit={featuredTrend.unit}
          referenceRange={featuredTrend.latest?.reference_range}
          height={200}
          formatDate={formatShortDate}
          onPointClick={(documentId, labResultId) =>
            router.push(labResultId ? `/documents/${documentId}?lab=${labResultId}` : `/documents/${documentId}`)
          }
        />
      </div>
    </section>
  ) : null;

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      hideHeader
      breadcrumbs={[{ label: t("navPatients"), href: backHref }]}
      banner={
        <PatientContext
          patient={profile.patient}
          ageLabel={formatPatientAge(profile.patient.date_of_birth, language)}
          backHref={backHref}
          backLabel={t("navAllPatients")}
          tabs={tabs}
          activeTab={tab}
          onTabChange={(key) => setTab(key as WorkspaceTab)}
          status={
            hasActiveAdmission ? (
              <Status tone="ok">Active admission</Status>
            ) : (
              <Status tone="muted">No active stay</Status>
            )
          }
          actions={
            <>
              {isDoctor ? (
                <button
                  type="button"
                  className="b-btn b-btn-primary b-btn-sm"
                  onClick={() => router.push(`/patients/${patientId}/upload`)}
                >
                  <IconUpload size={13} />
                  Upload
                </button>
              ) : null}

              <Menu label={t("navPatientActions")}>
                {isDoctor ? (
                  <MenuItem
                    icon={<IconPlus size={13} />}
                    onClick={() => router.push(`/patients/${patientId}/notes/new`)}
                  >
                    New note
                  </MenuItem>
                ) : null}
                <MenuItem
                  icon={<IconChart size={13} />}
                  onClick={() => router.push(`/patients/${patientId}/analytics`)}
                >
                  {t("navAnalytics")}
                </MenuItem>
                <MenuItem
                  icon={<IconTimeline size={13} />}
                  onClick={() => router.push(`/patients/${patientId}/timeline`)}
                >
                  Full timeline
                </MenuItem>
                <MenuItem
                  icon={<IconClipboard size={13} />}
                  onClick={() => router.push(`/patients/${patientId}/hospitalizations`)}
                >
                  {t("navAdmissions")}
                </MenuItem>
                <MenuItem onClick={() => router.push(`/patients/${patientId}/assign`)}>
                  Manage access
                </MenuItem>
                <div className="b-menu-sep" />
                <MenuItem onClick={refreshPage}>
                  {refreshing ? "Refreshing…" : "Refresh record"}
                </MenuItem>
              </Menu>
            </>
          }
        />
      }
    >
      <div className="b-stack b-view-enter" key={tab}>
        {error ? <ErrorNote onRetry={refreshPage}>{error}</ErrorNote> : null}

        {/* ── Overview ──────────────────────────────────────────────────── */}
        {tab === "overview" ? (
          <>
            {stats.needsReview > 0 ? (
              <Notice tone="warn">
                <IconAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
                <span>
                  <strong style={{ fontWeight: 600 }}>
                    {stats.needsReview} abnormal record
                    {stats.needsReview === 1 ? "" : "s"} awaiting your review.
                  </strong>{" "}
                  Opening a structured record marks it reviewed for your account.{" "}
                  <button
                    type="button"
                    className="b-btn b-btn-ghost b-btn-sm"
                    style={{ color: "inherit", textDecoration: "underline" }}
                    onClick={() => setTab("documents")}
                  >
                    Review documents
                  </button>
                </span>
              </Notice>
            ) : null}

            <Metrics>
              <Metric label="Documents" value={stats.total} />
              <Metric label="Bloodwork reports" value={stats.bloodwork} />
              <Metric
                label="Abnormal analytes"
                value={stats.abnormal}
                tone={stats.abnormal > 0 ? "alert" : undefined}
              />
              <Metric label="Admissions" value={stats.hospitalizations} />
              <Metric label="Active medications" value={activeMeds.length} />
            </Metrics>

            {pinnedStrip}
            {featuredPanel}

            {/* Recent activity, active medications and recent documents:
                three tight sections instead of twenty disconnected cards. */}
            <section className="b-surface">
              <SectionHead
                title={t("navTimeline")}
                description="Most recent records and admissions"
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => setTab("timeline")}
                  >
                    View all
                    <IconChevronRight size={12} />
                  </button>
                }
              />
              <div className="b-section-body b-section-body-flush">
                <ClinicalTimeline
                  items={timelineItems}
                  maxItems={6}
                  onOpenDocument={openTimelineDocument}
                  onSeeFullTimeline={() => setTab("timeline")}
                  showSeeFullTimeline={false}
                  emptyText="No timeline activity yet."
                />
              </div>
            </section>

            <section className="b-surface">
              <SectionHead
                title="Current medications"
                count={activeMeds.length + asNeededMeds.length}
                description="Patient-entered — dose and frequency not clinically verified"
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => setTab("medications")}
                  >
                    View all
                    <IconChevronRight size={12} />
                  </button>
                }
              />
              <div className="b-section-body b-section-body-flush">
                {activeMeds.length + asNeededMeds.length === 0 ? (
                  <EmptyState
                    icon={<IconPill size={17} />}
                    title="No medications recorded"
                    description="This patient has not recorded any medications."
                  />
                ) : (
                  <div className="b-list">
                    {[...activeMeds, ...asNeededMeds].slice(0, 6).map((med) => (
                      <button
                        key={med.id}
                        type="button"
                        className="b-list-row"
                        onClick={() =>
                          router.push(`/patients/${patientId}/medications/${med.id}`)
                        }
                      >
                        <span className="b-list-main">
                          <span className="b-list-title">{med.name}</span>
                          <span className="b-list-sub">
                            {[med.dose_strength, med.frequency, med.route_form]
                              .filter(Boolean)
                              .join(" · ") || "No dose recorded"}
                            {med.reason ? ` · ${med.reason}` : ""}
                          </span>
                        </span>
                        <span className="b-list-trail">
                          {med.is_uncertain ? <Chip tone="warn">Dose unverified</Chip> : null}
                          <Status tone={medStatusTone(med.status)}>
                            {medStatusLabel(med.status)}
                          </Status>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </section>

            <section className="b-surface">
              <SectionHead
                title="Recent documents"
                count={allDocuments.length}
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => setTab("documents")}
                  >
                    View all
                    <IconChevronRight size={12} />
                  </button>
                }
              />
              <DataTable
                rows={allDocuments.slice(0, 6)}
                columns={documentColumns}
                rowKey={(row) => row.id}
                onRowClick={openStructuredDocument}
                caption="Recent documents"
                emptyState={
                  <EmptyState
                    icon={<IconDocument size={17} />}
                    title="No documents yet"
                    description="Upload a report to start building this record."
                  />
                }
              />
            </section>

            <section className="b-surface">
              <SectionHead
                title="Assigned doctors"
                count={(profile.doctor_access || []).length}
                actions={
                  isDoctor ? (
                    <button
                      type="button"
                      className="b-btn b-btn-secondary b-btn-sm"
                      onClick={() => router.push(`/patients/${patientId}/assign`)}
                    >
                      Manage
                    </button>
                  ) : null
                }
              />
              <div className="b-section-body b-section-body-flush">
                {(profile.doctor_access || []).length ? (
                  <div className="b-list">
                    {(profile.doctor_access || []).map((doctor) => (
                      <div key={doctor.doctor_user_id} className="b-list-row" style={{ cursor: "default" }}>
                        <span className="b-list-main">
                          <span className="b-list-title">{doctor.doctor_name}</span>
                          <span className="b-list-sub">
                            {doctor.doctor_email} · {valueOrDash(doctor.department)} ·{" "}
                            {valueOrDash(doctor.hospital_name)}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No doctors assigned" />
                )}
              </div>
            </section>
          </>
        ) : null}

        {/* ── Timeline ──────────────────────────────────────────────────── */}
        {tab === "timeline" ? (
          <section className="b-surface">
            <SectionHead
              title={t("navTimeline")}
              count={timelineItems.length}
              description="Records and admissions, grouped by hospitalization period where possible"
              actions={
                <button
                  type="button"
                  className="b-btn b-btn-secondary b-btn-sm"
                  onClick={() => router.push(`/patients/${patientId}/timeline`)}
                >
                  Open full view
                  <IconExternal size={12} />
                </button>
              }
            />
            <div className="b-section-body b-section-body-flush">
              <ClinicalTimeline
                items={timelineItems}
                maxItems={60}
                onOpenDocument={openTimelineDocument}
                onSeeFullTimeline={() => router.push(`/patients/${patientId}/timeline`)}
                showSeeFullTimeline
                emptyText="No timeline activity yet."
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
                title="All analytes"
                count={sortedTrends.length}
                description={`Most recent ${TREND_POINT_LIMIT} collections per analyte. Abnormal results first.`}
              />

              <Toolbar
                search={labQuery}
                onSearch={setLabQuery}
                searchPlaceholder="Search analytes…"
                filters={
                  <FilterChip
                    label="Abnormal only"
                    count={stats.abnormal}
                    active={labAbnormalOnly}
                    onClick={() => setLabAbnormalOnly((value) => !value)}
                  />
                }
                count={visibleTrends.length}
                countLabel="analytes"
              />

              {!visibleTrends.length ? (
                <EmptyState
                  icon={<IconLab size={17} />}
                  title="No bloodwork trends yet"
                  description="Upload structured bloodwork reports to generate trends."
                />
              ) : (
                <div>
                  {/* Column header for the dense trend rows. */}
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
                    <span>Analyte</span>
                    <span style={{ textAlign: "right" }}>Latest</span>
                    <span style={{ textAlign: "right" }}>Change</span>
                    <span>Trend</span>
                    <span style={{ textAlign: "right" }}>Date</span>
                    <span />
                  </div>

                  {visibleTrends.map((trend) => {
                    const abnormal = isTrendAbnormal(trend);
                    const expanded = expandedTrend === trend.test_key;
                    const pinned = pinnedTrendKeys.includes(trend.test_key);

                    return (
                      <div key={trend.test_key}>
                        <button
                          type="button"
                          className="b-trend-row"
                          aria-expanded={expanded}
                          onClick={() => setExpandedTrend(expanded ? null : trend.test_key)}
                        >
                          <span style={{ minWidth: 0 }}>
                            <span className="b-cell-title" style={{ display: "block" }}>
                              {trend.display_name}
                            </span>
                            <span className="b-cell-sub" style={{ display: "block" }}>
                              {trend.category || "Lab result"}
                              {trend.unit ? ` · ${trend.unit}` : ""}
                            </span>
                          </span>

                          <span style={{ textAlign: "right" }}>
                            <LabValue
                              value={trend.latest?.value_display ?? "—"}
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
                            {pinned ? <span className="b-chip b-chip-brand">Pinned</span> : null}
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
                                onClick={() => setFeaturedTrendKey(trend.test_key)}
                              >
                                Feature
                              </button>
                              <button
                                type="button"
                                className="b-btn b-btn-secondary b-btn-sm"
                                onClick={() => togglePin(trend.test_key)}
                                disabled={!pinned && pinnedTrendKeys.length >= MAX_PINNED}
                              >
                                {pinned ? "Unpin" : "Pin"}
                              </button>
                            </div>

                            <TrendChart
                              points={trend.points}
                              unit={trend.unit}
                              referenceRange={trend.latest?.reference_range}
                              height={190}
                              formatDate={formatShortDate}
                              onPointClick={(documentId, labResultId) =>
            router.push(labResultId ? `/documents/${documentId}?lab=${labResultId}` : `/documents/${documentId}`)
          }
                            />

                            <div className="b-label" style={{ marginTop: "var(--s4)" }}>
                              Source reports
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
                                        {point.report_name || `Document ${point.document_id}`}
                                      </span>
                                      <span className="b-list-sub">
                                        {formatDate(point.date)}
                                        {point.reference_range
                                          ? ` · ref ${point.reference_range}`
                                          : ""}
                                      </span>
                                    </span>
                                    <span className="b-list-trail">
                                      <LabValue
                                        value={point.value_display}
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
                isDoctor ? (
                  <button
                    type="button"
                    className="b-btn b-btn-primary b-btn-sm"
                    onClick={() => router.push(`/patients/${patientId}/upload`)}
                  >
                    <IconUpload size={13} />
                    Upload
                  </button>
                ) : null
              }
            />

            <Toolbar
              search={docQuery}
              onSearch={setDocQuery}
              searchPlaceholder="Search documents…"
              filters={SECTION_ORDER.map((section) => (
                <FilterChip
                  key={section}
                  label={sectionLabel(section)}
                  count={getSectionDocuments(profile, section).length}
                  active={activeSection === section}
                  onClick={() => setActiveSection(section)}
                />
              ))}
              count={filteredDocuments.length}
              countLabel="documents"
            />

            {/* Secondary filters stay available but out of the primary row. */}
            {filterOptions.departments.length ||
            filterOptions.hospitals.length ||
            filterOptions.years.length ? (
              <div
                className="b-toolbar"
                style={{ minHeight: 42, background: "var(--surface-2)" }}
              >
                {filterOptions.departments.length ? (
                  <select
                    className="b-input"
                    value={departmentFilter}
                    onChange={(event) => setDepartmentFilter(event.target.value)}
                    aria-label="Department"
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 130 }}
                  >
                    <option value="">All departments</option>
                    {filterOptions.departments.map((department) => (
                      <option key={department} value={department}>
                        {department}
                      </option>
                    ))}
                  </select>
                ) : null}

                {filterOptions.hospitals.length ? (
                  <select
                    className="b-input"
                    value={hospitalFilter}
                    onChange={(event) => setHospitalFilter(event.target.value)}
                    aria-label="Hospital"
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 130 }}
                  >
                    <option value="">All hospitals</option>
                    {filterOptions.hospitals.map((hospital) => (
                      <option key={hospital} value={hospital}>
                        {hospital}
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
                    style={{ height: "var(--ctl-h)", width: "auto", minWidth: 100 }}
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
              rows={visibleDocuments}
              columns={documentColumns}
              rowKey={(row) => row.id}
              onRowClick={openStructuredDocument}
              caption={`${sectionLabel(activeSection)} documents`}
              rowClassName={(row) => (needsDoctorReview(row) ? "row-alert" : undefined)}
              emptyState={
                <EmptyState
                  icon={<IconDocument size={17} />}
                  title="No documents in this section"
                  description="Upload a document or choose another section."
                  actions={
                    isDoctor ? (
                      <button
                        type="button"
                        className="b-btn b-btn-secondary"
                        onClick={() => router.push(`/patients/${patientId}/upload`)}
                      >
                        <IconUpload size={14} />
                        Upload
                      </button>
                    ) : null
                  }
                />
              }
            />

            {visibleCount < filteredDocuments.length ? (
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
                  Show {Math.min(PAGE_SIZE, filteredDocuments.length - visibleCount)} more
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

        {/* ── Medications ───────────────────────────────────────────────── */}
        {tab === "medications" ? (
          <>
            <Metrics>
              <Metric label="Total" value={medications.length} />
              <Metric label="Active" value={activeMeds.length} />
              <Metric label="As needed" value={asNeededMeds.length} />
              <Metric label="Paused / stopped" value={pausedStopped.length} />
              <Metric
                label="Dose unverified"
                value={uncertainMeds.length}
                tone={uncertainMeds.length > 0 ? "warn" : undefined}
              />
            </Metrics>

            <Notice tone="warn">
              Patient-entered medication records are not verified by a clinician. Review dose and
              frequency with the patient directly.
            </Notice>

            <section className="b-surface">
              <SectionHead
                title={t("navMedications")}
                count={medications.length}
                actions={
                  <button
                    type="button"
                    className="b-btn b-btn-secondary b-btn-sm"
                    onClick={() => router.push(`/patients/${patientId}/medications/list`)}
                  >
                    Open full list
                    <IconExternal size={12} />
                  </button>
                }
              />

              {medications.length ? (
                <div className="b-list">
                  {medications.map((med) => (
                    <button
                      key={med.id}
                      type="button"
                      className="b-list-row"
                      onClick={() => router.push(`/patients/${patientId}/medications/${med.id}`)}
                    >
                      <span className="b-list-main">
                        <span className="b-list-title">{med.name}</span>
                        <span className="b-list-sub">
                          {[med.dose_strength, med.frequency, med.route_form]
                            .filter(Boolean)
                            .join(" · ") || "No dose recorded"}
                          {med.reason ? ` · ${med.reason}` : ""}
                        </span>
                      </span>
                      <span className="b-list-trail">
                        <span
                          className="b-strip"
                          style={{ justifyContent: "flex-end", gap: "var(--s1)" }}
                        >
                          {med.is_uncertain ? <Chip tone="warn">Dose unverified</Chip> : null}
                          {med.official_match_status === "matched" ? (
                            <Chip tone="info">Official info</Chip>
                          ) : null}
                        </span>
                        <Status tone={medStatusTone(med.status)}>
                          {medStatusLabel(med.status)}
                        </Status>
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={<IconPill size={17} />}
                  title="No medications recorded"
                  description="This patient has not recorded any medications."
                />
              )}
            </section>
          </>
        ) : null}
      </div>

      {/* Featured-analyte picker: a searchable dialog instead of a native
          <select> holding fifty options. */}
      <Dialog
        open={featuredPickerOpen}
        onClose={() => setFeaturedPickerOpen(false)}
        title="Featured analyte"
        description="Choose which trend appears at the top of Labs and Overview."
      >
        <div className="b-list">
          {sortedTrends.map((trend) => (
            <button
              key={trend.test_key}
              type="button"
              className="b-list-row"
              aria-current={trend.test_key === featuredTrend?.test_key ? "page" : undefined}
              onClick={() => {
                setFeaturedTrendKey(trend.test_key);
                setFeaturedPickerOpen(false);
              }}
            >
              <span className="b-list-main">
                <span className="b-list-title">{trend.display_name}</span>
                <span className="b-list-sub">
                  {trend.category || "Lab result"}
                  {trend.unit ? ` · ${trend.unit}` : ""}
                </span>
              </span>
              <span className="b-list-trail">
                <LabValue
                  value={trend.latest?.value_display ?? "—"}
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
