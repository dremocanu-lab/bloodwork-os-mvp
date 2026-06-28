"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import ClinicalTimeline from "@/components/clinical-timeline";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";
import type { BloodworkTrend, TrendPoint } from "@/lib/analytes/types";
import { enrichBloodworkTrend } from "@/lib/analytes/match";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

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
  children?: TimelineItem[];
};

type AdmissionTimelineItem = TimelineItem & {
  admissionStart?: string | null;
  admissionEnd?: string | null;
  parentRank: number;
};

const PAGE_SIZE = 10;
const TREND_POINT_LIMIT = 5;
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin { to { transform: rotate(360deg); } }
        .bloodwork-spinner {
          width: ${size}px; height: ${size}px;
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
  return new Date(time).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
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
  if (section === "discharge_summary") return "Discharge summaries";
  if (section === "medications") return "Medications";
  if (section === "scans") return "Scans";
  if (section === "hospitalizations") return "Hospitalizations";
  if (section === "notes") return "Clinical notes";
  return "Other";
}

function getDocumentClinicalDate(doc: DocumentCard) {
  if (doc.section === "discharge_summary") {
    return doc.reported_on || doc.collected_on || doc.generated_on || doc.created_at || "";
  }
  return doc.collected_on || doc.test_date || doc.reported_on || doc.registered_on || doc.generated_on || doc.created_at || "";
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
  if (!doc.uploaded_by) return "Uploaded by unknown user";
  const details = [doc.uploaded_by.full_name, doc.uploaded_by.department, doc.uploaded_by.hospital_name].filter(Boolean);
  return `Uploaded by ${details.join(" · ")}`;
}

function isDischargeDocument(doc: DocumentCard | TimelineItem) {
  return (
    doc.section === "discharge_summary" ||
    ("section" in doc && doc.section === "hospitalizations") ||
    ("report_type" in doc && (doc.report_type === "Discharge summary" || doc.report_type === "discharge_summary"))
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
  return [...points].sort((a, b) => compareDatesAscending(a.date, b.date)).slice(-TREND_POINT_LIMIT);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionPill({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={active ? "primary-btn" : "secondary-btn"}
      style={{ borderRadius: 999, padding: "8px 14px", fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 7 }}
    >
      <span>{label}</span>
      <span style={{
        minWidth: 20, height: 20, padding: "0 6px", borderRadius: 999,
        display: "grid", placeItems: "center",
        background: active ? "rgba(255,255,255,0.18)" : "var(--panel-2)",
        border: active ? "1px solid rgba(255,255,255,0.22)" : "1px solid var(--border)",
        fontSize: 11, lineHeight: 1,
      }}>{count}</span>
    </button>
  );
}

function FilterSelect({ label, value, onChange, children }: { label: string; value: string; onChange: (next: string) => void; children: React.ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 6, minWidth: 160 }}>
      <span className="muted-text" style={{ fontSize: 12, fontWeight: 700 }}>{label}</span>
      <select
        className="text-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ borderRadius: 12, padding: "10px 38px 10px 12px", fontWeight: 600, cursor: "pointer" }}
      >{children}</select>
    </label>
  );
}

function MiniTimeline({ items, patientId, onOpenDocument }: { items: TimelineItem[]; patientId: string; onOpenDocument: (id: number) => void }) {
  const router = useRouter();
  return (
    <ClinicalTimeline
      items={items}
      maxItems={8}
      onOpenDocument={onOpenDocument}
      onSeeFullTimeline={() => router.push(`/patients/${patientId}/timeline`)}
      showSeeFullTimeline
      emptyText="No timeline activity yet."
    />
  );
}

function TrendChart({ points, unit, expanded, highlightedDocumentId }: { points: TrendPoint[]; unit?: string | null; expanded?: boolean; highlightedDocumentId?: number | null }) {
  const sorted = getRecentTrendPoints(points);
  if (!sorted.length) return null;

  const svgTextColor = "var(--foreground, #f8fafc)";
  const svgMutedTextColor = "var(--muted, #cbd5e1)";
  const svgTooltipBg = "var(--panel, #0f172a)";
  const svgTooltipBorder = "var(--primary, #8b5cf6)";
  const width = expanded ? 860 : 560;
  const height = expanded ? 300 : 150;
  const margin = expanded ? { top: 34, right: 42, bottom: 56, left: 66 } : { top: 18, right: 22, bottom: 30, left: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = sorted.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.25, 1);
  const yMin = min - spread * 0.22;
  const yMax = max + spread * 0.22;
  const yRange = yMax - yMin || 1;
  const coords = sorted.map((point, index) => ({
    x: margin.left + (index * plotWidth) / Math.max(sorted.length - 1, 1),
    y: margin.top + plotHeight - ((point.value - yMin) / yRange) * plotHeight,
    point,
  }));
  const line = coords.map((c) => `${c.x},${c.y}`).join(" ");
  const hoveredCoord =
    highlightedDocumentId == null ? null :
    coords.find((c) => c.point.document_id === highlightedDocumentId) || null;

  return (
    <div style={{
      width: "100%", height: expanded ? 340 : 165,
      borderRadius: expanded ? 18 : 0,
      background: expanded ? "var(--panel-2)" : "transparent",
      border: expanded ? "1px solid var(--border)" : "0",
      padding: expanded ? 14 : 0,
      overflow: "hidden",
      transition: "height 260ms ease, padding 260ms ease",
    }}>
      <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" style={{ display: "block", width: "100%", height: "100%", overflow: "visible" }}>
        {expanded && (
          <>
            <text x={margin.left} y={18} fill={svgTextColor} fontSize="13" fontWeight="900">Value {unit ? `(${unit})` : ""}</text>
            <text x={width - margin.right} y={height - 12} textAnchor="end" fill={svgTextColor} fontSize="12" fontWeight="900">Collection date</text>
          </>
        )}
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = margin.top + plotHeight * tick;
          const value = yMax - yRange * tick;
          return (
            <g key={tick}>
              <line x1={margin.left} y1={y} x2={width - margin.right} y2={y} stroke="var(--border)" strokeWidth="1" opacity={tick === 1 ? 1 : 0.65} />
              {expanded && <text x={margin.left - 12} y={y + 4} textAnchor="end" fill={svgMutedTextColor} fontSize="11" fontWeight="800">{Number(value.toFixed(2))}</text>}
            </g>
          );
        })}
        {expanded && coords.map((c, i) => (
          <text key={`${c.point.document_id}-date-${i}`} x={c.x} y={height - 32} textAnchor="middle" fill={svgTextColor} fontSize="11" fontWeight="800">
            {formatDate(c.point.date).replace(",", "")}
          </text>
        ))}
        <polyline fill="none" stroke="var(--primary)" strokeWidth={expanded ? "4" : "3.5"} strokeLinecap="round" strokeLinejoin="round" points={line} style={{ transition: "all 260ms ease" }} />
        {coords.map((c, i) => {
          const isHl = c.point.document_id === highlightedDocumentId;
          return (
            <circle key={`${c.point.document_id}-${i}`} cx={c.x} cy={c.y} r={isHl ? 7 : 5}
              fill={isHl ? "var(--warn-text)" : "var(--primary)"} stroke="var(--panel)" strokeWidth={isHl ? 4 : 3}
              style={{ transition: "r 160ms ease, fill 160ms ease" }} />
          );
        })}
        {expanded && hoveredCoord && (
          <g>
            <line x1={hoveredCoord.x} x2={hoveredCoord.x} y1={margin.top} y2={margin.top + plotHeight} stroke="var(--border)" strokeDasharray="4 4" opacity="0.8" />
            <rect x={Math.min(hoveredCoord.x + 12, width - 210)} y={Math.max(hoveredCoord.y - 34, margin.top)} width="178" height="54" rx="13" fill={svgTooltipBg} stroke={svgTooltipBorder} strokeWidth="1.5" opacity="0.98" />
            <text x={Math.min(hoveredCoord.x + 28, width - 194)} y={Math.max(hoveredCoord.y - 12, margin.top + 22)} fill={svgTextColor} fontSize="13" fontWeight="950">{hoveredCoord.point.value_display} {unit || ""}</text>
            <text x={Math.min(hoveredCoord.x + 28, width - 194)} y={Math.max(hoveredCoord.y + 8, margin.top + 42)} fill={svgMutedTextColor} fontSize="11" fontWeight="850">{formatDate(hoveredCoord.point.date)}</text>
          </g>
        )}
        {!expanded && coords.length > 0 && (
          <text x={width - margin.right} y={22} textAnchor="end" fill={svgTextColor} fontSize="12" fontWeight="950">
            {coords[coords.length - 1].point.value_display} {unit || ""}
          </text>
        )}
      </svg>
    </div>
  );
}

type DocCardProps = {
  doc: DocumentCard;
  patientId: string;
  isDoctor: boolean;
  currentUserId?: number;
  openingId: number | null;
  onOpenOriginal: (id: number) => void;
  onOpenStructured: (doc: DocumentCard) => void;
  router: ReturnType<typeof useRouter>;
};

function DocCard({ doc, patientId, isDoctor, currentUserId, openingId, onOpenOriginal, onOpenStructured, router }: DocCardProps) {
  const isNote = doc.section === "notes";
  const isDischargeSummary = doc.section === "discharge_summary";
  const reviewNeeded = needsDoctorReview(doc);
  const editableNote = isDoctor && doc.section === "notes" && (doc.can_edit_note || doc.uploaded_by?.id === currentUserId);

  return (
    <div
      className="soft-card-tight"
      style={{
        padding: 0,
        overflow: "hidden",
        marginBottom: 12,
        borderColor: reviewNeeded ? "var(--danger-border)" : "var(--border)",
        background: reviewNeeded ? "color-mix(in srgb, var(--danger-bg) 40%, var(--panel))" : "var(--panel)",
      }}
    >
      <div style={{
        height: 3,
        background: reviewNeeded ? "var(--danger-text)" : doc.is_verified ? "var(--success-text)" : "var(--border)",
      }} />

      <div style={{ padding: "16px 18px" }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          <span style={{
            padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 700,
            background: "var(--panel-2)", color: "var(--muted)", border: "1px solid var(--border)",
          }}>
            {sectionLabel(doc.section)}
          </span>
          {doc.is_verified && (
            <span style={{
              padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 700,
              background: "var(--success-bg)", color: "var(--success-text)",
              border: "1px solid color-mix(in srgb, var(--success-text) 24%, transparent)",
            }}>
              Verified
            </span>
          )}
          {reviewNeeded && (
            <span style={{
              padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 700,
              background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)",
            }}>
              Needs review
            </span>
          )}
        </div>

        <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: "-0.02em", marginBottom: 6 }}>
          {getDocumentTitle(doc)}
        </div>

        <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.65 }}>
          {getDocumentDateLabel(doc)}
          {doc.lab_name && !isDischargeSummary && ` · ${doc.lab_name}`}
          {doc.sample_type && !isDischargeSummary && ` · ${doc.sample_type}`}
          {doc.referring_doctor && ` · Dr. ${doc.referring_doctor}`}
          {isDischargeSummary && ` · Discharge record`}
        </div>
        <div className="muted-text" style={{ fontSize: 12, marginTop: 3 }}>
          {getUploaderText(doc)}
          {isNote && doc.note_preview && (
            <span style={{ fontStyle: "italic", opacity: 0.75 }}>
              {` · "${doc.note_preview.slice(0, 80)}${doc.note_preview.length > 80 ? "…" : ""}"`}
            </span>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
          {!isNote && (
            <button type="button" className="secondary-btn" onClick={() => onOpenOriginal(doc.id)} disabled={openingId === doc.id}>
              {openingId === doc.id ? "Opening…" : "Original"}
            </button>
          )}
          <button type="button" className="primary-btn" onClick={() => onOpenStructured(doc)}>
            {isNote ? "Open Note" : isDischargeSummary ? "Discharge" : "Structured"}
          </button>
          {editableNote && (
            <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/notes/${doc.id}/edit`)}>
              Edit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const { language } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);

  const [activeSection, setActiveSection] = useState<SectionKey>("bloodwork");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [expandedTrend, setExpandedTrend] = useState<string | null>(null);
  const [hoveredTrendDocumentId, setHoveredTrendDocumentId] = useState<number | null>(null);
  const [pinnedTrendKeys, setPinnedTrendKeys] = useState<string[]>([]);
  const [pinsLoaded, setPinsLoaded] = useState(false);
  const [featuredTrendKey, setFeaturedTrendKey] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [medications, setMedications] = useState<Array<{
    id: number; name: string; status: string;
    dose_strength?: string | null; frequency?: string | null;
    reason?: string | null; is_uncertain: boolean;
    official_match_status?: string | null;
    route_form?: string | null;
  }>>([]);

  const isDoctor = currentUser?.role === "doctor";
  const isAdmin = currentUser?.role === "admin";
  const canDoctorActions = isDoctor;

  const fetchMe = useCallback(async () => {
    const response = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(response.data);
    return response.data;
  }, []);

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
      setTrends(raw.map((t) => enrichBloodworkTrend(t)));
    } catch {
      setTrends([]);
    }
  }, [patientId]);

  async function refreshPage() {
    try {
      setRefreshing(true);
      setError("");
      await Promise.all([fetchProfile(), fetchTrends()]);
    } catch (err) {
      setError(getErrorMessage(err, "Could not refresh patient chart."));
    } finally {
      setRefreshing(false);
    }
  }

  const fetchMedications = useCallback(async () => {
    try {
      const res = await api.get<Array<{
        id: number; name: string; status: string;
        dose_strength?: string | null; frequency?: string | null;
        reason?: string | null; is_uncertain: boolean;
        official_match_status?: string | null;
      }>>(`/patients/${patientId}/medications`);
      setMedications(Array.isArray(res.data) ? res.data : []);
    } catch {
      setMedications([]);
    }
  }, [patientId]);

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const user = await fetchMe();
        if (user.role === "patient") { router.replace("/my-records"); return; }
        await Promise.all([fetchProfile(), fetchTrends(), fetchMedications()]);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient chart."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [fetchMe, fetchProfile, fetchTrends, fetchMedications, router]);

  useEffect(() => {
    setDepartmentFilter("");
    setHospitalFilter("");
    setYearFilter("");
    setVisibleCount(PAGE_SIZE);
    setExpandedTrend(null);
    setHoveredTrendDocumentId(null);
  }, [activeSection]);

  useEffect(() => {
    if (!currentUser || pinsLoaded) return;
    const storageKey = `pinned_trends_${currentUser.id}_patient_${patientId}`;
    try {
      const stored = localStorage.getItem(storageKey);
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
    const storageKey = `pinned_trends_${currentUser.id}_patient_${patientId}`;
    try {
      localStorage.setItem(storageKey, JSON.stringify(pinnedTrendKeys));
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

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return SECTION_ORDER.flatMap((s) => getSectionDocuments(profile, s)).sort((a, b) =>
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
    return documentsForSection.filter((doc) => {
      const deptOk = !departmentFilter || doc.uploaded_by?.department === departmentFilter;
      const hospOk = !hospitalFilter || doc.uploaded_by?.hospital_name === hospitalFilter;
      const yearOk = !yearFilter || getYear(getDocumentClinicalDate(doc)) === yearFilter;
      return deptOk && hospOk && yearOk;
    });
  }, [documentsForSection, departmentFilter, hospitalFilter, yearFilter]);

  const visibleDocuments = filteredDocuments.slice(0, visibleCount);

  const documentById = useMemo(() => {
    const lookup = new Map<number, DocumentCard>();
    for (const doc of allDocuments) lookup.set(doc.id, doc);
    return lookup;
  }, [allDocuments]);

  function openStructuredDocument(doc: DocumentCard) {
    router.push(getStructuredDocumentPath(doc, doc.id));
  }

  function openTimelineDocument(documentId: number) {
    const doc = documentById.get(documentId);
    if (doc) { router.push(getStructuredDocumentPath(doc, documentId)); return; }
    router.push(`/documents/${documentId}`);
  }

  const timelineItems = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];
    const sortedDocuments = [...allDocuments].sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
    const usedDocumentIds = new Set<number>();

    const dischargeParents: AdmissionTimelineItem[] = sortedDocuments
      .filter((doc) => isDischargeDocument(doc))
      .map((doc) => ({
        id: `discharge-${doc.id}`, type: "document" as const,
        date: doc.reported_on || doc.collected_on || getDocumentClinicalDate(doc),
        title: getDocumentTitle(doc),
        subtitle: `${doc.collected_on ? `Admitted ${doc.collected_on}` : "Admission date unknown"}${doc.reported_on ? ` · Discharged ${doc.reported_on}` : ""} · ${sectionLabel(doc.section)} · ${getUploaderText(doc)} · ${doc.is_verified ? "Verified" : "Unverified"}`,
        documentId: doc.id, section: doc.section, children: [],
        admissionStart: doc.collected_on, admissionEnd: doc.reported_on, parentRank: 1,
      }));

    const eventParents: AdmissionTimelineItem[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`, type: "event" as const,
      date: event.discharged_at || event.admitted_at || "",
      title: event.title || "Hospitalization",
      subtitle: `${event.status === "active" ? "Active admission" : "Discharged"} · Doctor ${valueOrDash(event.doctor_name)} · ${valueOrDash(event.department)} · ${valueOrDash(event.hospital_name)}`,
      eventId: event.id, section: "care_events", children: [],
      admissionStart: event.admitted_at, admissionEnd: event.discharged_at, parentRank: 2,
    }));

    const admissionParents = [...dischargeParents, ...eventParents]
      .filter((p) => p.admissionStart || p.admissionEnd)
      .sort((a, b) => {
        const diff = compareDatesDescending(a.date, b.date);
        return diff !== 0 ? diff : a.parentRank - b.parentRank;
      });

    const documentToTimelineItem = (doc: DocumentCard): TimelineItem => ({
      id: `doc-${doc.id}`, type: "document",
      date: getDocumentClinicalDate(doc),
      title: getDocumentTitle(doc),
      subtitle: `${sectionLabel(doc.section)} · ${doc.is_verified ? "Verified" : "Unverified"} · ${getUploaderText(doc)}`,
      documentId: doc.id, section: doc.section,
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

    const parentDocumentIds = new Set(admissionParents.map((p) => p.documentId).filter((id): id is number => Boolean(id)));
    const standaloneDocuments = sortedDocuments
      .filter((doc) => !usedDocumentIds.has(doc.id) && !parentDocumentIds.has(doc.id))
      .map(documentToTimelineItem);

    return [...admissionParents, ...standaloneDocuments].sort((a, b) => compareDatesDescending(a.date, b.date));
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
        const abnA = a.latest?.flag && String(a.latest.flag).toLowerCase() !== "normal" ? 1 : 0;
        const abnB = b.latest?.flag && String(b.latest.flag).toLowerCase() !== "normal" ? 1 : 0;
        if (abnA !== abnB) return abnB - abnA;
        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const featuredTrend = useMemo(() => {
    if (!sortedTrends.length) return null;
    if (featuredTrendKey) {
      return sortedTrends.find((t) => t.test_key === featuredTrendKey) || sortedTrends[0];
    }
    const abnormals = sortedTrends.filter(
      (t) => t.latest?.flag && String(t.latest.flag).toLowerCase() !== "normal"
    );
    const pool = abnormals.length ? abnormals : sortedTrends;
    return pool.reduce((best, t) => {
      return Math.abs(t.delta || 0) > Math.abs(best.delta || 0) ? t : best;
    }, pool[0]);
  }, [sortedTrends, featuredTrendKey]);

  const stats = useMemo(() => {
    if (!profile) return { total: 0, bloodwork: 0, hospitalizations: 0, needsReview: 0 };
    const hospitalCount =
      getSectionDocuments(profile, "discharge_summary").length +
      getSectionDocuments(profile, "hospitalizations").length +
      (profile.events || []).length;
    return {
      total: allDocuments.length,
      bloodwork: getSectionDocuments(profile, "bloodwork").length,
      hospitalizations: hospitalCount,
      needsReview: allDocuments.filter(needsDoctorReview).length,
    };
  }, [profile, allDocuments]);

  const activeEvents = useMemo(() => (profile?.events || []).filter((e) => e.status === "active"), [profile]);

  async function openOriginal(documentId: number) {
    try {
      setOpeningId(documentId);
      setError("");
      const response = await api.get(`/documents/${documentId}/file`, { responseType: "blob" });
      const rawContentType = response.headers["content-type"];
      const contentType = typeof rawContentType === "string" ? rawContentType : "application/octet-stream";
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

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">Loading patient chart…</span>
        </div>
      </main>
    );
  }

  const hasActiveAdmission = activeEvents.length > 0;
  const hasPins = pinnedTrendKeys.length > 0;

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`ID ${valueOrDash(profile.patient.patient_identifier)} · DOB ${valueOrDash(profile.patient.date_of_birth)} · ${formatPatientAge(profile.patient.date_of_birth, language)} · ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button className="secondary-btn" onClick={refreshPage}>{refreshing ? "Refreshing…" : "Refresh"}</button>
          <button className="secondary-btn" onClick={() => router.push(isAdmin ? "/assignments" : "/my-patients")}>Back</button>
        </div>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 20, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Patient header */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 20, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <span style={{
                padding: "5px 10px", borderRadius: 6, fontSize: 12, fontWeight: 700,
                background: hasActiveAdmission ? "var(--success-bg)" : "var(--panel-2)",
                color: hasActiveAdmission ? "var(--success-text)" : "var(--muted)",
                border: `1px solid ${hasActiveAdmission ? "color-mix(in srgb, var(--success-text) 24%, transparent)" : "var(--border)"}`,
              }}>
                {hasActiveAdmission ? "Active admission" : "No active stay"}
              </span>
              {stats.needsReview > 0 && (
                <span style={{ padding: "5px 10px", borderRadius: 6, fontSize: 12, fontWeight: 700, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)" }}>
                  {stats.needsReview} need{stats.needsReview === 1 ? "s" : ""} review
                </span>
              )}
            </div>
            <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.04em" }}>{profile.patient.full_name}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              Patient ID {valueOrDash(profile.patient.patient_identifier)} · CNP {valueOrDash(profile.patient.cnp)}
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {canDoctorActions && (
              <>
                <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/upload`)}>Upload</button>
                <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/notes/new`)}>New note</button>
              </>
            )}
            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>Timeline</button>
            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/medications/list`)}>Medications</button>
            <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/analytics`)}>Analytics</button>
          </div>
        </div>
      </div>

      {/* Review alert */}
      {stats.needsReview > 0 && (
        <div className="soft-card" style={{ padding: 16, marginBottom: 24, borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 10, height: 10, borderRadius: 999, background: "var(--danger-text)", flexShrink: 0 }} />
            <span style={{ fontWeight: 700, color: "var(--danger-text)" }}>Abnormal records need review</span>
          </div>
          <div className="muted-text" style={{ marginTop: 6, fontSize: 13 }}>
            Opening each structured record marks it reviewed for your account.
          </div>
        </div>
      )}

      {/* Featured trend */}
      {featuredTrend && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
            <div>
              <div className="section-title">Featured Trend</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {featuredTrend.display_name} · {featuredTrend.category || "Lab result"} · {featuredTrend.unit || "—"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {sortedTrends.length > 1 && (
                <select
                  className="text-input"
                  value={featuredTrendKey || featuredTrend.test_key}
                  onChange={(e) => setFeaturedTrendKey(e.target.value)}
                  style={{ borderRadius: 12, padding: "8px 32px 8px 12px", fontWeight: 600, fontSize: 13, cursor: "pointer", minWidth: 180 }}
                >
                  {sortedTrends.map((t) => (
                    <option key={t.test_key} value={t.test_key}>{t.display_name}</option>
                  ))}
                </select>
              )}
              <button
                type="button"
                className={pinnedTrendKeys.includes(featuredTrend.test_key) ? "primary-btn" : "secondary-btn"}
                onClick={() => togglePin(featuredTrend.test_key)}
                disabled={!pinnedTrendKeys.includes(featuredTrend.test_key) && pinnedTrendKeys.length >= MAX_PINNED}
              >
                {pinnedTrendKeys.includes(featuredTrend.test_key) ? "Unpin" : "Pin"}
              </button>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 16 }}>
            {[
              { label: "Latest", value: featuredTrend.latest?.value_display || "—" },
              { label: "Previous", value: featuredTrend.previous?.value_display || "—" },
              { label: "Delta", value: featuredTrend.delta == null ? "—" : `${featuredTrend.delta > 0 ? "+" : ""}${featuredTrend.delta}` },
            ].map(({ label, value }) => (
              <div key={label} className="soft-card-tight" style={{ padding: "12px 16px" }}>
                <div className="muted-text" style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
                <div style={{ fontWeight: 800, fontSize: 22, marginTop: 4, letterSpacing: "-0.03em" }}>{value}</div>
              </div>
            ))}
          </div>

          <TrendChart
            points={getRecentTrendPoints(featuredTrend.points)}
            unit={featuredTrend.unit}
            expanded
            highlightedDocumentId={null}
          />

          {featuredTrend.latest && (
            <div className="muted-text" style={{ marginTop: 10, fontSize: 12 }}>
              Latest: {featuredTrend.latest.date} · Reference {featuredTrend.latest.reference_range || "—"}
            </div>
          )}
        </div>
      )}

      {/* 2-column layout: main content + pinned sidebar */}
      <div style={{
        display: "grid",
        gridTemplateColumns: hasPins ? "minmax(0, 1fr) 300px" : "minmax(0, 1fr)",
        gap: 24,
        alignItems: "start",
      }}>
        {/* Main column */}
        <div>
          {/* Timeline */}
          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap", marginBottom: 18 }}>
              <div>
                <div className="section-title">Timeline</div>
                <div className="muted-text" style={{ marginTop: 6 }}>Recent records and admissions, grouped by hospitalization period when possible.</div>
              </div>
              <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>View full timeline</button>
            </div>
            <MiniTimeline items={timelineItems} patientId={patientId} onOpenDocument={openTimelineDocument} />
          </div>

          {/* Medications */}
          {(() => {
            const activeMeds = medications.filter((m) => m.status === "active");
            const asNeededMeds = medications.filter((m) => m.status === "as_needed");
            const pausedStopped = medications.filter((m) => m.status === "paused" || m.status === "stopped");
            const uncertainMeds = medications.filter((m) => m.is_uncertain);
            const officialMatched = medications.filter((m) => m.official_match_status === "matched");
            const displayMeds = [...activeMeds, ...asNeededMeds].slice(0, 6);
            return (
              <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap", marginBottom: 16 }}>
                  <div>
                    <div className="section-title">Medications</div>
                    <div className="muted-text" style={{ marginTop: 6, fontSize: 13 }}>Patient-entered records — view only. Dose and frequency not verified.</div>
                  </div>
                  <button className="secondary-btn" style={{ fontSize: 13 }} onClick={() => router.push(`/patients/${patientId}/medications/list`)}>View all</button>
                </div>

                {medications.length > 0 && (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 10, marginBottom: 16 }}>
                    {[
                      { label: "Total", value: medications.length },
                      { label: "Active", value: activeMeds.length, accent: activeMeds.length > 0 ? "var(--success-text)" : undefined },
                      { label: "As needed", value: asNeededMeds.length },
                      { label: "Paused / stopped", value: pausedStopped.length },
                      { label: "Dose not verified", value: uncertainMeds.length, accent: uncertainMeds.length > 0 ? "var(--warn-text)" : undefined },
                      { label: "Official info", value: officialMatched.length },
                    ].map(({ label, value, accent }) => (
                      <div key={label} className="soft-card-tight" style={{ padding: "10px 12px" }}>
                        <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
                        <div style={{ fontWeight: 800, fontSize: 20, marginTop: 3, color: accent || "var(--foreground)" }}>{value}</div>
                      </div>
                    ))}
                  </div>
                )}

                {medications.length === 0 ? (
                  <div className="muted-text" style={{ fontSize: 13 }}>No medications recorded by this patient.</div>
                ) : (
                  <div style={{ display: "grid", gap: 8 }}>
                    {displayMeds.map((m) => {
                      const active = m.status === "active";
                      const asNeeded = m.status === "as_needed";
                      const statusBg = active ? "var(--success-bg)" : asNeeded ? "color-mix(in srgb, var(--primary) 12%, var(--panel-2))" : "var(--panel-2)";
                      const statusColor = active ? "var(--success-text)" : asNeeded ? "var(--primary)" : "var(--muted)";
                      const statusLabel = active ? "Active" : asNeeded ? "As needed" : m.status === "paused" ? "Paused" : "Stopped";
                      const matchBadge =
                        m.official_match_status === "matched" ? { label: "Official info matched", bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)" } :
                        m.official_match_status === "not_matched" ? { label: "No official match", bg: "var(--panel-2)", color: "var(--muted)" } :
                        null;
                      return (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => router.push(`/patients/${patientId}/medications/${m.id}`)}
                          className="soft-card-tight"
                          style={{ padding: "12px 14px", textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, cursor: "pointer", width: "100%" }}
                        >
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                              <span style={{ fontWeight: 800, fontSize: 15 }}>{m.name}</span>
                              {m.is_uncertain && (
                                <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                                  Dose not verified
                                </span>
                              )}
                              {matchBadge && (
                                <span style={{ padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: matchBadge.bg, color: matchBadge.color }}>
                                  {matchBadge.label}
                                </span>
                              )}
                            </div>
                            <div className="muted-text" style={{ fontSize: 12 }}>
                              {[m.dose_strength, m.frequency, m.route_form].filter(Boolean).join(" · ") || "No dose recorded"}
                              {m.reason ? ` · Reason: ${m.reason}` : ""}
                            </div>
                          </div>
                          <span style={{ flexShrink: 0, padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: statusBg, color: statusColor }}>
                            {statusLabel}
                          </span>
                        </button>
                      );
                    })}
                    {medications.length > 6 && (
                      <button
                        type="button"
                        className="secondary-btn"
                        style={{ fontSize: 13 }}
                        onClick={() => router.push(`/patients/${patientId}/medications/list`)}
                      >
                        View all {medications.length} medications →
                      </button>
                    )}
                  </div>
                )}

                <div className="soft-card-tight" style={{ padding: 10, marginTop: 14, background: "var(--panel-2)", fontSize: 11 }}>
                  <span className="muted-text">
                    Patient-entered medication records are not verified by a clinician. Dose not verified · Frequency not verified · Review with the patient directly.
                  </span>
                </div>
              </div>
            );
          })()}

          {/* Documents */}
          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 18 }}>
              <div>
                <div className="section-title">Documents</div>
                <div className="muted-text" style={{ marginTop: 6 }}>Organized by category, date, department, and source.</div>
              </div>
              {canDoctorActions && (
                <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/upload`)}>Upload</button>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              {SECTION_ORDER.map((section) => (
                <SectionPill key={section} active={activeSection === section} label={sectionLabel(section)} count={getSectionDocuments(profile, section).length} onClick={() => setActiveSection(section)} />
              ))}
            </div>

            <div className="soft-card-tight" style={{ padding: 14, marginBottom: 16, background: "var(--panel-2)", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
              <FilterSelect label="Department" value={departmentFilter} onChange={setDepartmentFilter}>
                <option value="">All</option>
                {filterOptions.departments.map((d) => <option key={d} value={d}>{d}</option>)}
              </FilterSelect>
              <FilterSelect label="Hospital" value={hospitalFilter} onChange={setHospitalFilter}>
                <option value="">All</option>
                {filterOptions.hospitals.map((h) => <option key={h} value={h}>{h}</option>)}
              </FilterSelect>
              <FilterSelect label="Year" value={yearFilter} onChange={setYearFilter}>
                <option value="">All</option>
                {filterOptions.years.map((y) => <option key={y} value={y}>{y}</option>)}
              </FilterSelect>
            </div>

            <div>
              {visibleDocuments.map((doc) => (
                <DocCard
                  key={doc.id}
                  doc={doc}
                  patientId={patientId}
                  isDoctor={isDoctor}
                  currentUserId={currentUser?.id}
                  openingId={openingId}
                  onOpenOriginal={openOriginal}
                  onOpenStructured={openStructuredDocument}
                  router={router}
                />
              ))}
              {!visibleDocuments.length && (
                <div style={{ padding: "28px 0", textAlign: "center" }}>
                  <div style={{ fontWeight: 700, color: "var(--text)", marginBottom: 6 }}>No documents in this section yet.</div>
                  <div className="muted-text">Upload a document or choose another section.</div>
                </div>
              )}
            </div>

            {visibleCount < filteredDocuments.length && (
              <div style={{ display: "flex", justifyContent: "center", marginTop: 16 }}>
                <button type="button" className="secondary-btn" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>Show more</button>
              </div>
            )}
          </div>

          {/* Bloodwork trends */}
          {activeSection === "bloodwork" && (
            <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
              <div style={{ marginBottom: 18 }}>
                <div className="section-title">Bloodwork Trends</div>
                <div className="muted-text" style={{ marginTop: 6 }}>Sorted by clinical importance. Graphs use the most recent 5 collections.</div>
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {sortedTrends.map((trend) => {
                  const abnormal = trend.latest?.flag && String(trend.latest.flag).trim().toLowerCase() !== "normal";
                  const expanded = expandedTrend === trend.test_key;
                  const pinned = pinnedTrendKeys.includes(trend.test_key);
                  const trendPoints = getRecentTrendPoints(trend.points);

                  return (
                    <div key={trend.test_key} className="soft-card-tight" style={{ padding: 16, borderColor: abnormal ? "var(--danger-border)" : "var(--border)", transition: "border-color 220ms ease" }}>
                      <div style={{ display: "grid", gridTemplateColumns: expanded ? "minmax(0, 1fr) auto" : "minmax(200px, 0.42fr) minmax(240px, 1fr) auto", gap: 16, alignItems: "center" }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{trend.display_name}</div>
                          <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>{trend.category || "Lab result"} · {trend.unit || "—"}</div>
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 12 }}>
                            {[
                              { label: "Latest", value: trend.latest?.value_display || "—" },
                              { label: "Previous", value: trend.previous?.value_display || "—" },
                              { label: "Delta", value: trend.delta == null ? "—" : `${trend.delta > 0 ? "+" : ""}${trend.delta}` },
                            ].map(({ label, value }) => (
                              <div key={label}>
                                <div className="muted-text" style={{ fontSize: 11, fontWeight: 700 }}>{label}</div>
                                <div style={{ fontWeight: 700, marginTop: 3 }}>{value}</div>
                              </div>
                            ))}
                          </div>
                          <div className="muted-text" style={{ marginTop: 8, fontSize: 12 }}>
                            Latest: {trend.latest ? `${trend.latest.date} · Ref ${trend.latest.reference_range || "—"}` : "—"}
                          </div>
                        </div>

                        {!expanded && <TrendChart points={trendPoints} unit={trend.unit} highlightedDocumentId={null} />}

                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          <button
                            type="button"
                            className="secondary-btn"
                            onClick={() => { setExpandedTrend(expanded ? null : trend.test_key); setHoveredTrendDocumentId(null); }}
                          >
                            {expanded ? "Collapse" : "Expand"}
                          </button>
                          <button
                            type="button"
                            className={pinned ? "primary-btn" : "secondary-btn"}
                            onClick={() => togglePin(trend.test_key)}
                            disabled={!pinned && pinnedTrendKeys.length >= MAX_PINNED}
                          >
                            {pinned ? "Unpin" : "Pin"}
                          </button>
                        </div>
                      </div>

                      <div style={{ display: "grid", gridTemplateRows: expanded ? "1fr" : "0fr", transition: "grid-template-rows 320ms cubic-bezier(0.22, 1, 0.36, 1), opacity 240ms ease, margin-top 260ms ease", opacity: expanded ? 1 : 0, marginTop: expanded ? 16 : 0, overflow: "hidden" }}>
                        <div style={{ minHeight: 0, overflow: "hidden" }}>
                          <TrendChart points={trendPoints} unit={trend.unit} expanded highlightedDocumentId={hoveredTrendDocumentId} />

                          <div style={{ marginTop: 16, fontWeight: 700 }}>Reports used in this trend</div>
                          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                            {[...trendPoints].sort((a, b) => compareDatesDescending(a.date, b.date)).map((point, index) => {
                              const highlighted = hoveredTrendDocumentId === point.document_id;
                              return (
                                <button
                                  key={`${trend.test_key}-${point.document_id}-${index}`}
                                  type="button"
                                  className="soft-card-tight"
                                  onMouseEnter={() => setHoveredTrendDocumentId(point.document_id)}
                                  onMouseLeave={() => setHoveredTrendDocumentId(null)}
                                  onFocus={() => setHoveredTrendDocumentId(point.document_id)}
                                  onBlur={() => setHoveredTrendDocumentId(null)}
                                  onClick={() => router.push(`/documents/${point.document_id}`)}
                                  style={{
                                    padding: 12, display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: 12, alignItems: "center", textAlign: "left", cursor: "pointer",
                                    transition: "background 180ms ease, border-color 180ms ease, transform 180ms ease",
                                    transform: highlighted ? "translateX(3px)" : "translateX(0)",
                                    background: highlighted ? "color-mix(in srgb, var(--primary) 9%, var(--panel))" : "var(--panel-2)",
                                    borderColor: highlighted ? "color-mix(in srgb, var(--primary) 35%, var(--border))" : "var(--border)",
                                  }}
                                >
                                  <div style={{ minWidth: 0 }}>
                                    <div style={{ fontWeight: 700 }}>{point.report_name || `Document ${point.document_id}`}</div>
                                    <div className="muted-text" style={{ marginTop: 3, fontSize: 12 }}>{point.date || "No date"} · Ref {point.reference_range || "—"}</div>
                                  </div>
                                  <div style={{ fontWeight: 700 }}>{point.value_display} {trend.unit || ""}</div>
                                  <span className="secondary-btn" style={{ pointerEvents: "none" }}>Open</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}

                {!sortedTrends.length && (
                  <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                    <div style={{ fontWeight: 700 }}>No bloodwork trends yet.</div>
                    <div className="muted-text" style={{ marginTop: 6 }}>Upload structured bloodwork reports to generate graphs.</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Assigned doctors */}
          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="section-title" style={{ marginBottom: 14 }}>Assigned doctors</div>
            <div style={{ display: "grid", gap: 10 }}>
              {(profile.doctor_access || []).map((doctor) => (
                <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 14, display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{doctor.doctor_name}</div>
                    <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>
                      {doctor.doctor_email} · {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                    </div>
                  </div>
                </div>
              ))}
              {!(profile.doctor_access || []).length && <div className="muted-text">No doctors assigned.</div>}
            </div>
          </div>
        </div>

        {/* Pinned trends sidebar */}
        {hasPins && (
          <div style={{ position: "sticky", top: 24 }}>
            <div className="soft-card" style={{ padding: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <div className="section-title" style={{ margin: 0 }}>Pinned Trends</div>
                <span className="muted-text" style={{ fontSize: 12 }}>{pinnedTrendKeys.length}/{MAX_PINNED}</span>
              </div>
              <div style={{ display: "grid", gap: 14 }}>
                {pinnedTrendKeys.map((key) => {
                  const trend = sortedTrends.find((t) => t.test_key === key);
                  if (!trend) return null;
                  const pts = getRecentTrendPoints(trend.points);
                  const abnormal = trend.latest?.flag && String(trend.latest.flag).trim().toLowerCase() !== "normal";

                  return (
                    <div
                      key={key}
                      className="soft-card-tight"
                      style={{ padding: 14, borderColor: abnormal ? "var(--danger-border)" : "var(--border)" }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 10 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {trend.display_name}
                          </div>
                          <div className="muted-text" style={{ fontSize: 12, marginTop: 2 }}>
                            {trend.latest?.value_display || "—"} {trend.unit || ""}
                            {trend.delta != null && (
                              <span style={{ marginLeft: 6, color: trend.delta > 0 ? "var(--danger-text)" : trend.delta < 0 ? "var(--primary)" : "var(--muted)" }}>
                                {trend.delta > 0 ? "▲" : trend.delta < 0 ? "▼" : ""}
                                {Math.abs(trend.delta)}
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => togglePin(key)}
                          style={{ padding: "4px 10px", fontSize: 12, flexShrink: 0 }}
                        >
                          Unpin
                        </button>
                      </div>
                      <TrendChart points={pts} unit={trend.unit} highlightedDocumentId={null} />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
