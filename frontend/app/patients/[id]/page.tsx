"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
    medications?: DocumentCard[];
    scans?: DocumentCard[];
    hospitalizations?: DocumentCard[];
    other?: DocumentCard[];
  };
  doctor_access?: DoctorAccess[];
  events?: PatientEvent[];
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
};

const PAGE_SIZE = 10;
const TREND_POINT_LIMIT = 5;

const SECTION_ORDER = [
  "bloodwork",
  "medications",
  "scans",
  "hospitalizations",
  "notes",
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

function parseDateTime(value?: string | null) {
  if (!value) return 0;

  const normalized = value.trim();
  const direct = new Date(normalized).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);

  if (!match) return 0;

  const day = Number(match[1]);
  const month = Number(match[2]);
  const rawYear = Number(match[3]);
  const year = rawYear < 100 ? 2000 + rawYear : rawYear;
  const parsed = new Date(year, month - 1, day).getTime();

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
  if (!value) return "â€”";

  const time = parseDateTime(value);

  if (!time) return value;

  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function getYear(value?: string | null) {
  const time = parseDateTime(value);

  if (!time) return "";

  return String(new Date(time).getFullYear());
}

function calculateAgeFromDob(dateOfBirth?: string | null) {
  if (!dateOfBirth) return "â€”";

  const dob = new Date(dateOfBirth);

  if (Number.isNaN(dob.getTime())) return "â€”";

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

  if (years < 0) return "â€”";

  return `${years}y ${months}m`;
}

function normalizeProfile(profile: PatientProfileResponse): PatientProfileResponse {
  return {
    ...profile,
    sections: {
      notes: profile.sections.notes || [],
      bloodwork: profile.sections.bloodwork || [],
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
  if (section === "medications") return "Medications";
  if (section === "scans") return "Scans";
  if (section === "hospitalizations") return "Hospitalizations";
  if (section === "notes") return "Clinical notes";
  return "Other";
}

function getDocumentClinicalDate(doc: DocumentCard) {
  return (
    doc.collected_on ||
    doc.test_date ||
    doc.reported_on ||
    doc.registered_on ||
    doc.generated_on ||
    ""
  );
}

function getDocumentDateLabel(doc: DocumentCard) {
  if (doc.collected_on) return `Collected ${doc.collected_on}`;
  if (doc.test_date) return `Test date ${doc.test_date}`;
  if (doc.reported_on) return `Reported ${doc.reported_on}`;
  if (doc.registered_on) return `Registered ${doc.registered_on}`;
  if (doc.generated_on) return `Generated ${doc.generated_on}`;
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

  const details = [doc.uploaded_by.full_name, doc.uploaded_by.department, doc.uploaded_by.hospital_name].filter(
    Boolean
  );

  return `Uploaded by ${details.join(" Â· ")}`;
}

function getRecentTrendPoints(points: TrendPoint[]) {
  return [...points]
    .sort((a, b) => compareDatesAscending(a.date, b.date))
    .slice(-TREND_POINT_LIMIT);
}

function StatCard({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="soft-card-tight" style={{ padding: 18 }}>
      <div className="muted-text" style={{ fontSize: 12, fontWeight: 850 }}>
        {label}
      </div>

      <div
        style={{
          fontSize: 30,
          fontWeight: 950,
          letterSpacing: "-0.06em",
          marginTop: 8,
        }}
      >
        {value}
      </div>

      {note && (
        <div className="muted-text" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
          {note}
        </div>
      )}
    </div>
  );
}

function SectionPill({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={active ? "primary-btn" : "secondary-btn"}
      style={{
        borderRadius: 999,
        padding: "10px 14px",
        fontWeight: 900,
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <span>{label}</span>

      <span
        style={{
          minWidth: 22,
          height: 22,
          padding: "0 7px",
          borderRadius: 999,
          display: "grid",
          placeItems: "center",
          background: active ? "rgba(255,255,255,0.18)" : "var(--panel-2)",
          border: active ? "1px solid rgba(255,255,255,0.22)" : "1px solid var(--border)",
          fontSize: 12,
          lineHeight: 1,
        }}
      >
        {count}
      </span>
    </button>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "grid", gap: 8, minWidth: 170 }}>
      <span className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
        {label}
      </span>

      <select
        className="text-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          borderRadius: 18,
          padding: "13px 42px 13px 14px",
          fontWeight: 850,
          cursor: "pointer",
          background: "var(--panel)",
        }}
      >
        {children}
      </select>
    </label>
  );
}

function MiniTimeline({ items, patientId }: { items: TimelineItem[]; patientId: string }) {
  const router = useRouter();

  return (
    <ClinicalTimeline
      items={items}
      maxItems={8}
      onOpenDocument={(documentId) => router.push(`/documents/${documentId}`)}
      onSeeFullTimeline={() => router.push(`/patients/${patientId}/timeline`)}
      showSeeFullTimeline
      emptyText="No timeline activity yet."
    />
  );
}

function TrendChart({
  points,
  unit,
  expanded,
  highlightedDocumentId,
}: {
  points: TrendPoint[];
  unit?: string | null;
  expanded?: boolean;
  highlightedDocumentId?: number | null;
}) {
  const sorted = getRecentTrendPoints(points);

  if (!sorted.length) return null;

  const svgTextColor = "var(--foreground, #f8fafc)";
  const svgMutedTextColor = "var(--muted, #cbd5e1)";
  const svgTooltipBg = "var(--panel, #0f172a)";
  const svgTooltipBorder = "var(--primary, #8b5cf6)";

  const width = expanded ? 860 : 560;
  const height = expanded ? 300 : 150;

  const margin = expanded
    ? { top: 34, right: 42, bottom: 56, left: 66 }
    : { top: 18, right: 22, bottom: 30, left: 42 };

  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const values = sorted.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.25, 1);

  const yMin = min - spread * 0.22;
  const yMax = max + spread * 0.22;
  const yRange = yMax - yMin || 1;

  const coords = sorted.map((point, index) => {
    const x = margin.left + (index * plotWidth) / Math.max(sorted.length - 1, 1);
    const y = margin.top + plotHeight - ((point.value - yMin) / yRange) * plotHeight;

    return { x, y, point };
  });

  const line = coords.map((coord) => `${coord.x},${coord.y}`).join(" ");
  const hoveredCoord =
    highlightedDocumentId === null || highlightedDocumentId === undefined
      ? null
      : coords.find((coord) => coord.point.document_id === highlightedDocumentId) || null;

  return (
    <div
      style={{
        width: "100%",
        height: expanded ? 340 : 165,
        borderRadius: expanded ? 22 : 0,
        background: expanded ? "var(--panel-2)" : "transparent",
        border: expanded ? "1px solid var(--border)" : "0",
        padding: expanded ? 14 : 0,
        overflow: "hidden",
        transition:
          "height 260ms ease, padding 260ms ease, background 220ms ease, border-color 220ms ease, opacity 220ms ease",
      }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{
          display: "block",
          width: "100%",
          height: "100%",
          overflow: "visible",
        }}
      >
        {expanded && (
          <>
            <text x={margin.left} y={18} fill={svgTextColor} fontSize="13" fontWeight="900">
              Value {unit ? `(${unit})` : ""}
            </text>

            <text
              x={width - margin.right}
              y={height - 12}
              textAnchor="end"
              fill={svgTextColor}
              fontSize="12"
              fontWeight="900"
            >
              Collection date
            </text>
          </>
        )}

        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = margin.top + plotHeight * tick;
          const value = yMax - yRange * tick;

          return (
            <g key={tick}>
              <line
                x1={margin.left}
                y1={y}
                x2={width - margin.right}
                y2={y}
                stroke="var(--border)"
                strokeWidth="1"
                opacity={tick === 1 ? 1 : 0.65}
              />

              {expanded && (
                <text
                  x={margin.left - 12}
                  y={y + 4}
                  textAnchor="end"
                  fill={svgMutedTextColor}
                  fontSize="11"
                  fontWeight="800"
                >
                  {Number(value.toFixed(2))}
                </text>
              )}
            </g>
          );
        })}

        {expanded &&
          coords.map((coord, index) => (
            <text
              key={`${coord.point.document_id}-date-${index}`}
              x={coord.x}
              y={height - 32}
              textAnchor="middle"
              fill={svgTextColor}
              fontSize="11"
              fontWeight="800"
            >
              {formatDate(coord.point.date).replace(",", "")}
            </text>
          ))}

        <polyline
          fill="none"
          stroke="var(--primary)"
          strokeWidth={expanded ? "4" : "3.5"}
          strokeLinecap="round"
          strokeLinejoin="round"
          points={line}
          style={{
            transition: "all 260ms ease",
          }}
        />

        {coords.map((coord, index) => {
          const isHighlighted = coord.point.document_id === highlightedDocumentId;

          return (
            <circle
              key={`${coord.point.document_id}-${index}`}
              cx={coord.x}
              cy={coord.y}
              r={isHighlighted ? 7 : 5}
              fill={isHighlighted ? "var(--warn-text)" : "var(--primary)"}
              stroke="var(--panel)"
              strokeWidth={isHighlighted ? 4 : 3}
              style={{
                transition: "r 160ms ease, fill 160ms ease, stroke-width 160ms ease",
              }}
            />
          );
        })}

        {expanded && hoveredCoord && (
          <g style={{ transition: "opacity 180ms ease" }}>
            <line
              x1={hoveredCoord.x}
              x2={hoveredCoord.x}
              y1={margin.top}
              y2={margin.top + plotHeight}
              stroke="var(--border)"
              strokeDasharray="4 4"
              opacity="0.8"
            />

            <rect
              x={Math.min(hoveredCoord.x + 12, width - 210)}
              y={Math.max(hoveredCoord.y - 34, margin.top)}
              width="178"
              height="54"
              rx="13"
              fill={svgTooltipBg}
              stroke={svgTooltipBorder}
              strokeWidth="1.5"
              opacity="0.98"
            />

            <rect
              x={Math.min(hoveredCoord.x + 12, width - 210)}
              y={Math.max(hoveredCoord.y - 34, margin.top)}
              width="178"
              height="54"
              rx="13"
              fill="none"
              stroke="rgba(255,255,255,0.18)"
              strokeWidth="1"
            />

            <text
              x={Math.min(hoveredCoord.x + 28, width - 194)}
              y={Math.max(hoveredCoord.y - 12, margin.top + 22)}
              fill={svgTextColor}
              fontSize="13"
              fontWeight="950"
            >
              {hoveredCoord.point.value_display} {unit || ""}
            </text>

            <text
              x={Math.min(hoveredCoord.x + 28, width - 194)}
              y={Math.max(hoveredCoord.y + 8, margin.top + 42)}
              fill={svgMutedTextColor}
              fontSize="11"
              fontWeight="850"
            >
              {formatDate(hoveredCoord.point.date)}
            </text>
          </g>
        )}

        {!expanded && coords.length > 0 && (
          <text
            x={width - margin.right}
            y={22}
            textAnchor="end"
            fill={svgTextColor}
            fontSize="12"
            fontWeight="950"
          >
            {coords[coords.length - 1].point.value_display} {unit || ""}
          </text>
        )}
      </svg>
    </div>
  );
}

export default function PatientChartPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
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

  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

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
      setTrends(Array.isArray(response.data) ? response.data : []);
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

  useEffect(() => {
    async function init() {
      try {
        setError("");

        const user = await fetchMe();

        if (user.role === "patient") {
          router.replace("/my-records");
          return;
        }

        await Promise.all([fetchProfile(), fetchTrends()]);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient chart."));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [fetchMe, fetchProfile, fetchTrends, router]);

  useEffect(() => {
    setDepartmentFilter("");
    setHospitalFilter("");
    setYearFilter("");
    setVisibleCount(PAGE_SIZE);
    setExpandedTrend(null);
    setHoveredTrendDocumentId(null);
  }, [activeSection]);

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
    return documentsForSection.filter((doc) => {
      const departmentMatches = !departmentFilter || doc.uploaded_by?.department === departmentFilter;
      const hospitalMatches = !hospitalFilter || doc.uploaded_by?.hospital_name === hospitalFilter;
      const yearMatches = !yearFilter || getYear(getDocumentClinicalDate(doc)) === yearFilter;

      return departmentMatches && hospitalMatches && yearMatches;
    });
  }, [documentsForSection, departmentFilter, hospitalFilter, yearFilter]);

  const visibleDocuments = filteredDocuments.slice(0, visibleCount);

  const timelineItems = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => ({
      id: `doc-${doc.id}`,
      type: "document",
      date: getDocumentClinicalDate(doc),
      title: getDocumentTitle(doc),
      subtitle: `${sectionLabel(doc.section)} Â· ${doc.is_verified ? "Verified" : "Unverified"} Â· ${getUploaderText(doc)}`,
      documentId: doc.id,
      section: doc.section,
    }));

    const eventItems: TimelineItem[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`,
      type: "event",
      date: event.discharged_at || event.admitted_at || "",
      title: event.title,
      subtitle: `${event.status === "active" ? "Active admission" : "Discharged"} Â· Doctor ${valueOrDash(
        event.doctor_name
      )}`,
      eventId: event.id,
      section: "events",
    }));

    return [...documentItems, ...eventItems].sort((a, b) => compareDatesDescending(a.date, b.date));
  }, [profile, allDocuments]);

  const sortedTrends = useMemo(() => {
    return [...trends]
      .filter((trend) => trend.points?.length)
      .map((trend) => {
        const recentPoints = getRecentTrendPoints(trend.points);
        const latest = recentPoints[recentPoints.length - 1] || trend.latest;
        const previous = recentPoints[recentPoints.length - 2] || trend.previous || null;
        const delta = latest && previous ? Number((latest.value - previous.value).toFixed(2)) : null;

        return {
          ...trend,
          points: recentPoints,
          latest,
          previous,
          delta,
        };
      })
      .sort((a, b) => {
        const abnormalA = a.latest?.flag && String(a.latest.flag).toLowerCase() !== "normal" ? 1 : 0;
        const abnormalB = b.latest?.flag && String(b.latest.flag).toLowerCase() !== "normal" ? 1 : 0;

        if (abnormalA !== abnormalB) return abnormalB - abnormalA;

        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        total: 0,
        bloodwork: 0,
        scans: 0,
        notes: 0,
        needsReview: 0,
      };
    }

    return {
      total: allDocuments.length,
      bloodwork: getSectionDocuments(profile, "bloodwork").length,
      scans: getSectionDocuments(profile, "scans").length,
      notes: getSectionDocuments(profile, "notes").length,
      needsReview: allDocuments.filter(needsDoctorReview).length,
    };
  }, [profile, allDocuments]);

  const activeEvents = useMemo(() => {
    return (profile?.events || []).filter((event) => event.status === "active");
  }, [profile]);

  function getSectionCount(section: SectionKey) {
    return getSectionDocuments(profile, section).length;
  }

  function canEditNote(doc: DocumentCard) {
    if (!isDoctor) return false;
    if (doc.section !== "notes") return false;
    if (doc.can_edit_note) return true;
    return doc.uploaded_by?.id === currentUser?.id;
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

      window.setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(getErrorMessage(err, "Could not open original file."));
    } finally {
      setOpeningId(null);
    }
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
          <span className="muted-text">Loading patient chart...</span>
        </div>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);
  const hasActiveAdmission = activeEvents.length > 0;

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`ID ${valueOrDash(profile.patient.patient_identifier)} Â· DOB ${valueOrDash(
        profile.patient.date_of_birth
      )} Â· Age ${calculatedAge} Â· Sex ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button className="secondary-btn" onClick={refreshPage}>
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>

          <button className="secondary-btn" onClick={() => router.push(isAdmin ? "/assignments" : "/my-patients")}>
            Back
          </button>
        </div>
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
              Patient ID {valueOrDash(profile.patient.patient_identifier)} Â· CNP {valueOrDash(profile.patient.cnp)}
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
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <StatCard label="Total records" value={stats.total} note="All uploaded records" />
        <StatCard label="Bloodwork" value={stats.bloodwork} note="Structured lab reports" />
        <StatCard label="Scans" value={stats.scans} note="Imaging and scans" />
        <StatCard label="Clinical notes" value={stats.notes} note="Doctor-created notes" />
        <StatCard label="Needs review" value={stats.needsReview} note="Abnormal unreviewed records" />
      </div>

      {stats.needsReview > 0 && (
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

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          <div>
            <div className="section-title">My Timeline</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              Recent records and care events, sorted by collected/test date when available.
            </div>
          </div>

          <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
            View full timeline
          </button>
        </div>

        <MiniTimeline items={timelineItems} patientId={patientId} />
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          <div>
            <div className="section-title">Documents</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              Organized by category, date, department, and source.
            </div>
          </div>

          {canDoctorActions && (
            <button className="primary-btn" onClick={() => router.push(`/patients/${patientId}/upload`)}>
              Upload
            </button>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
          {SECTION_ORDER.map((section) => (
            <SectionPill
              key={section}
              active={activeSection === section}
              label={sectionLabel(section)}
              count={getSectionCount(section)}
              onClick={() => setActiveSection(section)}
            />
          ))}
        </div>

        <div
          className="soft-card-tight"
          style={{
            padding: 18,
            marginBottom: 18,
            background: "var(--panel-2)",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
            gap: 12,
          }}
        >
          <FilterSelect label="Department" value={departmentFilter} onChange={setDepartmentFilter}>
            <option value="">All</option>
            {filterOptions.departments.map((department) => (
              <option key={department} value={department}>
                {department}
              </option>
            ))}
          </FilterSelect>

          <FilterSelect label="Hospital" value={hospitalFilter} onChange={setHospitalFilter}>
            <option value="">All</option>
            {filterOptions.hospitals.map((hospital) => (
              <option key={hospital} value={hospital}>
                {hospital}
              </option>
            ))}
          </FilterSelect>

          <FilterSelect label="Year" value={yearFilter} onChange={setYearFilter}>
            <option value="">All</option>
            {filterOptions.years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </FilterSelect>
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {visibleDocuments.map((doc) => {
            const isNote = doc.section === "notes";
            const abnormal = hasAbnormal(doc);
            const reviewNeeded = needsDoctorReview(doc);
            const editableNote = canEditNote(doc);

            return (
              <div
                key={doc.id}
                className="soft-card-tight"
                style={{
                  padding: 18,
                  borderColor: reviewNeeded ? "var(--danger-border)" : "var(--border)",
                  background: reviewNeeded ? "var(--danger-bg)" : "var(--panel)",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) minmax(170px, 0.35fr) auto",
                    gap: 18,
                    alignItems: "center",
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      {abnormal && (
                        <span
                          style={{
                            width: 10,
                            height: 10,
                            borderRadius: 999,
                            background: reviewNeeded ? "var(--danger-text)" : "var(--muted)",
                            flex: "0 0 auto",
                          }}
                        />
                      )}

                      <div style={{ fontWeight: 950, fontSize: 18 }}>{getDocumentTitle(doc)}</div>

                      <span
                        style={{
                          display: "inline-flex",
                          padding: "5px 9px",
                          borderRadius: 999,
                          background: doc.is_verified ? "var(--success-bg)" : "var(--warn-bg)",
                          color: doc.is_verified ? "var(--success-text)" : "var(--warn-text)",
                          border: "1px solid var(--border)",
                          fontSize: 12,
                          fontWeight: 900,
                        }}
                      >
                        {doc.is_verified ? "Verified" : "Unverified"}
                      </span>

                      {reviewNeeded && (
                        <span
                          style={{
                            display: "inline-flex",
                            padding: "5px 9px",
                            borderRadius: 999,
                            background: "var(--danger-bg)",
                            color: "var(--danger-text)",
                            border: "1px solid var(--danger-border)",
                            fontSize: 12,
                            fontWeight: 900,
                          }}
                        >
                          Needs review
                        </span>
                      )}
                    </div>

                    <div className="muted-text" style={{ marginTop: 8 }}>
                      {getUploaderText(doc)}
                    </div>

                    {isNote ? (
                      <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.6 }}>
                        {valueOrDash(doc.note_preview)}
                      </div>
                    ) : (
                      <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.6 }}>
                        {sectionLabel(doc.section)} Â· {getDocumentDateLabel(doc)}
                        {doc.lab_name ? ` Â· ${doc.lab_name}` : ""}
                        {doc.sample_type ? ` Â· ${doc.sample_type}` : ""}
                      </div>
                    )}
                  </div>

                  <div style={{ minWidth: 0 }}>
                    <div className="muted-text" style={{ fontSize: 12, fontWeight: 850 }}>
                      Source
                    </div>
                    <div style={{ fontWeight: 950, marginTop: 5 }}>
                      {valueOrDash(doc.report_type || sectionLabel(doc.section))}
                    </div>
                    <div className="muted-text" style={{ marginTop: 5 }}>
                      {valueOrDash(doc.referring_doctor)}
                    </div>
                  </div>

                  <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                    {!isNote && (
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

                    {editableNote && (
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() => router.push(`/patients/${patientId}/notes/${doc.id}/edit`)}
                      >
                        Edit Note
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {!visibleDocuments.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>No documents in this section yet.</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Upload a document or choose another section.
              </div>
            </div>
          )}
        </div>

        {visibleCount < filteredDocuments.length && (
          <div style={{ display: "flex", justifyContent: "center", marginTop: 18 }}>
            <button type="button" className="secondary-btn" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
              Show More
            </button>
          </div>
        )}
      </div>

      {activeSection === "bloodwork" && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div className="section-title">Bloodwork Trends</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              Trends are sorted by clinical importance. Graphs use the most recent 5 collections by collected/test date.
            </div>
          </div>

          <div style={{ display: "grid", gap: 14 }}>
            {sortedTrends.map((trend) => {
              const abnormal = trend.latest?.flag && String(trend.latest.flag).trim().toLowerCase() !== "normal";
              const expanded = expandedTrend === trend.test_key;
              const trendPoints = getRecentTrendPoints(trend.points);

              return (
                <div
                  key={trend.test_key}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    borderColor: abnormal ? "var(--danger-border)" : "var(--border)",
                    background: "var(--panel)",
                    transition: "border-color 220ms ease, background 220ms ease, box-shadow 220ms ease",
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: expanded
                        ? "minmax(0, 1fr) auto"
                        : "minmax(220px, 0.42fr) minmax(260px, 1fr) auto",
                      gap: 18,
                      alignItems: "center",
                      transition: "grid-template-columns 260ms ease",
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: 950,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {trend.display_name}
                      </div>

                      <div className="muted-text" style={{ marginTop: 5, fontSize: 12 }}>
                        {trend.category || "Lab result"} Â· Unit {trend.unit || "â€”"}
                      </div>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                          gap: 10,
                          marginTop: 14,
                        }}
                      >
                        <div>
                          <div className="muted-text" style={{ fontSize: 11, fontWeight: 850 }}>
                            Latest
                          </div>
                          <div style={{ fontWeight: 950, marginTop: 4 }}>
                            {trend.latest?.value_display || "â€”"}
                          </div>
                        </div>

                        <div>
                          <div className="muted-text" style={{ fontSize: 11, fontWeight: 850 }}>
                            Previous
                          </div>
                          <div style={{ fontWeight: 950, marginTop: 4 }}>
                            {trend.previous?.value_display || "â€”"}
                          </div>
                        </div>

                        <div>
                          <div className="muted-text" style={{ fontSize: 11, fontWeight: 850 }}>
                            Delta
                          </div>
                          <div style={{ fontWeight: 950, marginTop: 4 }}>
                            {trend.delta === null || trend.delta === undefined
                              ? "â€”"
                              : `${trend.delta > 0 ? "+" : ""}${trend.delta}`}
                          </div>
                        </div>
                      </div>

                      <div className="muted-text" style={{ marginTop: 10, fontSize: 12 }}>
                        Latest sample:{" "}
                        {trend.latest ? `${trend.latest.date} Â· Ref ${trend.latest.reference_range || "â€”"}` : "â€”"}
                      </div>
                    </div>

                    {!expanded && (
                      <TrendChart
                        points={trendPoints}
                        unit={trend.unit}
                        highlightedDocumentId={null}
                      />
                    )}

                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => {
                        setExpandedTrend(expanded ? null : trend.test_key);
                        setHoveredTrendDocumentId(null);
                      }}
                    >
                      {expanded ? "Collapse" : "Expand"}
                    </button>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateRows: expanded ? "1fr" : "0fr",
                      transition:
                        "grid-template-rows 320ms cubic-bezier(0.22, 1, 0.36, 1), opacity 240ms ease, margin-top 260ms ease",
                      opacity: expanded ? 1 : 0,
                      marginTop: expanded ? 18 : 0,
                      overflow: "hidden",
                    }}
                  >
                    <div style={{ minHeight: 0, overflow: "hidden" }}>
                      <TrendChart
                        points={trendPoints}
                        unit={trend.unit}
                        expanded
                        highlightedDocumentId={hoveredTrendDocumentId}
                      />

                      <div style={{ marginTop: 18, fontWeight: 950 }}>Reports used in this trend</div>

                      <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                        {[...trendPoints]
                          .sort((a, b) => compareDatesDescending(a.date, b.date))
                          .map((point, index) => {
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
                                  padding: 14,
                                  display: "grid",
                                  gridTemplateColumns: "minmax(0, 1fr) auto auto",
                                  gap: 12,
                                  alignItems: "center",
                                  textAlign: "left",
                                  cursor: "pointer",
                                  transition:
                                    "background 180ms ease, border-color 180ms ease, transform 180ms ease",
                                  transform: highlighted ? "translateX(3px)" : "translateX(0)",
                                  background: highlighted
                                    ? "color-mix(in srgb, var(--primary) 9%, var(--panel))"
                                    : "var(--panel-2)",
                                  borderColor: highlighted
                                    ? "color-mix(in srgb, var(--primary) 35%, var(--border))"
                                    : "var(--border)",
                                }}
                              >
                                <div style={{ minWidth: 0 }}>
                                  <div style={{ fontWeight: 900 }}>
                                    {point.report_name || `Document ${point.document_id}`}
                                  </div>
                                  <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
                                    {point.date || "No date"} Â· Ref {point.reference_range || "â€”"}
                                  </div>
                                </div>

                                <div style={{ fontWeight: 950 }}>
                                  {point.value_display} {trend.unit || ""}
                                </div>

                                <span className="secondary-btn" style={{ pointerEvents: "none" }}>
                                  Open
                                </span>
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
              <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 900 }}>No bloodwork trends yet.</div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  Upload structured bloodwork reports to generate graphs.
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          Assigned doctors
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {(profile.doctor_access || []).map((doctor) => (
            <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 16 }}>
              <div style={{ fontWeight: 900 }}>{doctor.doctor_name}</div>
              <div className="muted-text" style={{ marginTop: 4 }}>
                {doctor.doctor_email}
              </div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {valueOrDash(doctor.department)} Â· {valueOrDash(doctor.hospital_name)}
              </div>
            </div>
          ))}

          {!(profile.doctor_access || []).length && <div className="muted-text">No doctors assigned.</div>}
        </div>
      </div>
    </AppShell>
  );
}
