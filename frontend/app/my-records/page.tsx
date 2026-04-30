"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { useUploadManager } from "@/components/upload-provider";
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

type AccessRequest = {
  id: number;
  doctor_user_id: number;
  doctor_name?: string | null;
  doctor_email?: string | null;
  doctor_department?: string | null;
  doctor_hospital_name?: string | null;
  status: string;
  requested_at: string;
  responded_at?: string | null;
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
};

const SECTION_ORDER: Array<keyof MyProfileResponse["sections"]> = [
  "bloodwork",
  "medications",
  "scans",
  "hospitalizations",
  "other",
];

const PAGE_SIZE = 10;

const TREND_PRIORITY_WORDS = [
  "rbc",
  "red blood",
  "hemoglobin",
  "hgb",
  "hematocrit",
  "hct",
  "mcv",
  "mch",
  "mchc",
  "rdw",
  "wbc",
  "white blood",
  "neut",
  "lymph",
  "mono",
  "eosin",
  "baso",
  "platelet",
  "plt",
  "mpv",
  "glucose",
  "creatinine",
  "creatinina",
  "urea",
  "alt",
  "ast",
  "bilirubin",
  "cholesterol",
  "triglyceride",
  "tsh",
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

function compareDatesAscending(a: string, b: string) {
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

function formatAxisDate(value?: string | null) {
  const time = parseDateTime(value);

  if (!time) return value || "€”";

  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function formatAxisNumber(value: number) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  if (Math.abs(value) >= 1) return value.toFixed(2).replace(/\.?0+$/, "");
  return value.toFixed(3).replace(/\.?0+$/, "");
}

function calculateAgeFromDob(dateOfBirth?: string | null) {
  if (!dateOfBirth) return "€”";

  const dob = new Date(dateOfBirth);
  if (Number.isNaN(dob.getTime())) return "€”";

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

  if (years < 0) return "€”";

  if (years === 0) {
    return `${months} ${months === 1 ? "month" : "months"}`;
  }

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
    ""
  );
}

function getDocumentDateLabel(doc: DocumentCard) {
  const clinicalDate = getDocumentClinicalDate(doc);

  if (!clinicalDate) return "No date";

  if (doc.collected_on) return `Collected ${doc.collected_on}`;
  if (doc.test_date) return `Test date ${doc.test_date}`;
  if (doc.reported_on) return `Reported ${doc.reported_on}`;
  if (doc.registered_on) return `Registered ${doc.registered_on}`;
  if (doc.generated_on) return `Generated ${doc.generated_on}`;

  return clinicalDate;
}

function getEventDate(event: PatientEvent) {
  return event.discharged_at || event.admitted_at || "";
}

function uploaderSubtitle(doc: DocumentCard) {
  const uploader = doc.uploaded_by;

  if (!uploader) return "Uploaded by unknown user";

  const details = [uploader.full_name, uploader.department, uploader.hospital_name].filter(Boolean);

  return `Uploaded by ${details.join(" · ")}`;
}

function getTrendPriority(trend: BloodworkTrend) {
  const name = `${trend.test_key || ""} ${trend.display_name || ""} ${trend.canonical_name || ""} ${
    trend.category || ""
  }`.toLowerCase();

  const index = TREND_PRIORITY_WORDS.findIndex((word) => name.includes(word));

  if (index === -1) return 999;

  return index;
}

function getSortedTrendPoints(points: TrendPoint[]) {
  return [...points].sort((a, b) => compareDatesAscending(a.date, b.date));
}

function getMostRecentTrendPoints(points: TrendPoint[], count = 5) {
  return getSortedTrendPoints(points)
    .slice(-count)
    .sort((a, b) => compareDatesAscending(a.date, b.date));
}

function buildYAxisTicks(values: number[]) {
  if (!values.length) return [0, 1];

  const min = Math.min(...values);
  const max = Math.max(...values);

  if (min === max) {
    const spread = Math.abs(min) < 1 ? 0.5 : Math.abs(min) * 0.15;
    return [min - spread, min, min + spread];
  }

  const rawPadding = (max - min) * 0.18;
  const paddedMin = min - rawPadding;
  const paddedMax = max + rawPadding;
  const step = (paddedMax - paddedMin) / 4;

  return [0, 1, 2, 3, 4].map((index) => paddedMin + step * index);
}

function TrendChart({
  points,
  highlightedDocumentId,
  expanded = false,
  unit,
}: {
  points: TrendPoint[];
  highlightedDocumentId?: number | null;
  expanded?: boolean;
  unit?: string | null;
}) {
  if (!points.length) return null;

  const sortedPoints = getSortedTrendPoints(points);

  const width = 1000;
  const height = expanded ? 360 : 150;

  const margin = expanded
    ? { top: 58, right: 36, bottom: 64, left: 82 }
    : { top: 24, right: 24, bottom: 24, left: 24 };

  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const values = sortedPoints.map((point) => point.value);
  const yTicks = buildYAxisTicks(values);
  const yMin = Math.min(...yTicks);
  const yMax = Math.max(...yTicks);
  const yRange = yMax - yMin || 1;

  const coords = sortedPoints.map((point, index) => {
    const x = margin.left + (index * plotWidth) / Math.max(sortedPoints.length - 1, 1);
    const y = margin.top + plotHeight - ((point.value - yMin) / yRange) * plotHeight;

    return { x, y, point };
  });

  const highlightedCoord =
    coords.find((coord) => coord.point.document_id === highlightedDocumentId) || null;

  const tooltipWidth = expanded ? 196 : 154;
  const tooltipHeight = expanded ? 52 : 42;

  let tooltipX = highlightedCoord ? highlightedCoord.x - tooltipWidth / 2 : 0;
  if (tooltipX < 10) tooltipX = 10;
  if (tooltipX + tooltipWidth > width - 10) tooltipX = width - tooltipWidth - 10;

  const tooltipY = highlightedCoord
    ? Math.max(8, highlightedCoord.y - tooltipHeight - 16)
    : 0;

  const linePoints = coords.map((coord) => `${coord.x},${coord.y}`).join(" ");

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        overflow: "visible",
      }}
    >
      {expanded && (
        <>
          <text x={margin.left} y={24} fill="var(--muted)" fontSize="13" fontWeight="850">
            Value {unit ? `(${unit})` : ""}
          </text>

          <text
            x={width - margin.right}
            y={height - 12}
            textAnchor="end"
            fill="var(--muted)"
            fontSize="13"
            fontWeight="850"
          >
            Collection date
          </text>

          {yTicks.map((tick, index) => {
            const y = margin.top + plotHeight - ((tick - yMin) / yRange) * plotHeight;

            return (
              <g key={`y-tick-${index}`}>
                <line
                  x1={margin.left}
                  y1={y}
                  x2={width - margin.right}
                  y2={y}
                  stroke="var(--border)"
                  strokeWidth="1"
                  opacity={index === 0 ? 0.9 : 0.55}
                />

                <text
                  x={margin.left - 12}
                  y={y + 4}
                  textAnchor="end"
                  fill="var(--muted)"
                  fontSize="12"
                  fontWeight="800"
                >
                  {formatAxisNumber(tick)}
                </text>
              </g>
            );
          })}

          <line
            x1={margin.left}
            y1={margin.top}
            x2={margin.left}
            y2={margin.top + plotHeight}
            stroke="var(--border)"
            strokeWidth="1.25"
          />

          <line
            x1={margin.left}
            y1={margin.top + plotHeight}
            x2={width - margin.right}
            y2={margin.top + plotHeight}
            stroke="var(--border)"
            strokeWidth="1.25"
          />

          {coords.map((coord, index) => (
            <g key={`x-tick-${coord.point.document_id}-${index}`}>
              <line
                x1={coord.x}
                y1={margin.top + plotHeight}
                x2={coord.x}
                y2={margin.top + plotHeight + 6}
                stroke="var(--border)"
                strokeWidth="1"
              />

              <text
                x={coord.x}
                y={margin.top + plotHeight + 28}
                textAnchor="middle"
                fill="var(--muted)"
                fontSize="12"
                fontWeight="800"
              >
                {formatAxisDate(coord.point.date)}
              </text>
            </g>
          ))}
        </>
      )}

      {!expanded && (
        <>
          <line
            x1={margin.left}
            y1={margin.top + plotHeight}
            x2={width - margin.right}
            y2={margin.top + plotHeight}
            stroke="var(--border)"
            strokeWidth="1"
            opacity="0.65"
          />

          <line
            x1={margin.left}
            y1={margin.top + plotHeight / 2}
            x2={width - margin.right}
            y2={margin.top + plotHeight / 2}
            stroke="var(--border)"
            strokeWidth="1"
            opacity="0.35"
          />
        </>
      )}

      <polyline
        fill="none"
        stroke="var(--primary)"
        strokeWidth={expanded ? 4 : 4.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={linePoints}
      />

      {coords.map((coord, index) => {
        const highlighted = highlightedDocumentId === coord.point.document_id;

        return (
          <circle
            key={`trend-point-${coord.point.document_id}-${index}`}
            cx={coord.x}
            cy={coord.y}
            r={highlighted ? (expanded ? 10 : 8) : expanded ? 5.5 : 5}
            fill={highlighted ? "#f97316" : "var(--primary)"}
            stroke={highlighted ? "#fed7aa" : "var(--panel)"}
            strokeWidth={highlighted ? 6 : 3}
            style={{
              transition:
                "r 180ms ease, fill 180ms ease, stroke-width 180ms ease, transform 180ms ease",
            }}
          />
        );
      })}

      {highlightedCoord && (
        <g style={{ pointerEvents: "none" }}>
          <line
            x1={highlightedCoord.x}
            y1={highlightedCoord.y - 2}
            x2={highlightedCoord.x}
            y2={tooltipY + tooltipHeight}
            stroke="#f97316"
            strokeWidth="1.5"
            strokeDasharray="4 4"
            opacity="0.9"
          />

          <rect
            x={tooltipX}
            y={tooltipY}
            width={tooltipWidth}
            height={tooltipHeight}
            rx={expanded ? 15 : 12}
            fill="#ffffff"
            stroke="#f97316"
            strokeWidth="1.6"
            filter="drop-shadow(0px 14px 28px rgba(0, 0, 0, 0.35))"
          />

          <text
            x={tooltipX + 13}
            y={tooltipY + (expanded ? 21 : 17)}
            fill="#0f172a"
            fontSize={expanded ? 14 : 12}
            fontWeight="900"
          >
            {highlightedCoord.point.value_display} {unit || ""}
          </text>

          <text
            x={tooltipX + 13}
            y={tooltipY + (expanded ? 40 : 33)}
            fill="#475569"
            fontSize={expanded ? 12 : 10.5}
            fontWeight="800"
          >
            {formatAxisDate(highlightedCoord.point.date)}
          </text>
        </g>
      )}
    </svg>
  );
}

function SelectFilter({
  label,
  value,
  options,
  onChange,
  calendarLike,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  calendarLike?: boolean;
}) {
  return (
    <label style={{ display: "grid", gap: 6, minWidth: 180 }}>
      <span className="muted-text" style={{ fontSize: 12, fontWeight: 850 }}>
        {label}
      </span>

      <div style={{ position: "relative" }}>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="text-input"
          style={{
            appearance: "none",
            width: "100%",
            paddingRight: 40,
            borderRadius: 16,
            background: calendarLike
              ? "linear-gradient(135deg, color-mix(in srgb, var(--primary) 8%, var(--panel)), var(--panel))"
              : "var(--panel)",
            fontWeight: 850,
            cursor: "pointer",
          }}
        >
          <option value="">All</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {calendarLike ? `📅 ${option}` : option}
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
            color: "var(--muted)",
            fontWeight: 950,
          }}
        >
          ▼
        </span>
      </div>
    </label>
  );
}

export default function MyRecordsPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const { activeCount, refreshUploadJobs } = useUploadManager();

  const sectionLabels: Record<string, string> = {
    bloodwork: t("bloodwork"),
    medications: "Medications",
    scans: t("scans"),
    hospitalizations: "Hospitalizations",
    other: "Other",
  };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [activeSection, setActiveSection] = useState<keyof MyProfileResponse["sections"]>("bloodwork");

  const [departmentFilter, setDepartmentFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [expandedTrendKey, setExpandedTrendKey] = useState<string | null>(null);
  const [hoveredTrendPoint, setHoveredTrendPoint] = useState<Record<string, number | null>>({});

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
    const response = await api.get<MyProfileResponse>("/my/profile");
    setProfile(response.data);
    return response.data;
  }

  async function fetchRequests() {
    const response = await api.get<AccessRequest[]>("/my/access-requests");
    setRequests(response.data);
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

      await Promise.all([
        fetchRequests(),
        fetchTrends(profileResponse.patient.id),
        refreshUploadJobs(),
      ]);
    } catch {
      // Silent refresh should never break the page.
    }
  }

  async function respondToRequest(requestId: number, status: "approved" | "denied") {
    try {
      setError("");
      await api.post(`/access-requests/${requestId}/respond`, { status });

      const updatedProfile = await fetchProfile();
      await Promise.all([fetchRequests(), fetchTrends(updatedProfile.patient.id)]);
    } catch (err) {
      setError(getErrorMessage(err, t("failedRespondRequest")));
    }
  }

  async function openOriginal(documentId: number) {
    try {
      setError("");

      const response = await api.get(`/documents/${documentId}/file`, {
        responseType: "blob",
      });

      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string" ? rawContentType : "application/octet-stream";

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

  useEffect(() => {
    async function init() {
      const me = await fetchMe();
      if (!me) return;

      if (me.role !== "patient") {
        router.push(me.role === "doctor" ? "/my-patients" : "/assignments");
        return;
      }

      try {
        setError("");

        const profileResponse = await fetchProfile();
        await Promise.all([fetchRequests(), fetchTrends(profileResponse.patient.id)]);
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadRecords")));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function handleUploadComplete() {
      void refreshRecordsSilently();
    }

    window.addEventListener("bloodwork-upload-complete", handleUploadComplete);

    return () => {
      window.removeEventListener("bloodwork-upload-complete", handleUploadComplete);
    };
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

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return SECTION_ORDER.flatMap((section) => profile.sections[section]).sort((a, b) =>
      compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b))
    );
  }, [profile]);

  const docsForActiveSection = useMemo(() => {
    if (!profile) return [];

    return [...profile.sections[activeSection]].sort((a, b) =>
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
    return docsForActiveSection.filter((doc) => {
      const departmentMatches = !departmentFilter || doc.uploaded_by?.department === departmentFilter;
      const hospitalMatches = !hospitalFilter || doc.uploaded_by?.hospital_name === hospitalFilter;
      const yearMatches = !yearFilter || getYearFromDate(getDocumentClinicalDate(doc)) === yearFilter;

      return departmentMatches && hospitalMatches && yearMatches;
    });
  }, [docsForActiveSection, departmentFilter, hospitalFilter, yearFilter]);

  const visibleDocsForSection = filteredDocsForSection.slice(0, visibleCount);

  const myTimeline = useMemo<TimelineItem[]>(() => {
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
    }));

    const eventItems: TimelineItem[] = profile.events.map((event) => ({
      id: `event-${event.id}`,
      type: "event",
      date: getEventDate(event),
      title: event.title,
      subtitle: `${event.status === "active" ? t("activeHospitalization") : t("dischargedHospitalization")} · ${t(
        "doctor"
      )} ${valueOrDash(event.doctor_name)}`,
      eventId: event.id,
    }));

    return [...documentItems, ...eventItems].sort((a, b) => compareDatesDescending(a.date, b.date));
  }, [profile, allDocuments, t]);

  const sortedTrends = useMemo(() => {
    return [...trends]
      .map((trend) => {
        const sortedPoints = getSortedTrendPoints(trend.points || []);
        const latest = sortedPoints[sortedPoints.length - 1] || trend.latest;
        const previous = sortedPoints[sortedPoints.length - 2] || trend.previous || null;

        return {
          ...trend,
          points: sortedPoints,
          latest,
          previous,
          delta: latest && previous ? Number((latest.value - previous.value).toFixed(2)) : trend.delta,
        };
      })
      .sort((a, b) => {
        const priorityDifference = getTrendPriority(a) - getTrendPriority(b);

        if (priorityDifference !== 0) return priorityDifference;

        const abnormalA = a.latest?.flag && a.latest.flag !== "Normal" ? 1 : 0;
        const abnormalB = b.latest?.flag && b.latest.flag !== "Normal" ? 1 : 0;

        if (abnormalA !== abnormalB) return abnormalB - abnormalA;

        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        records: 0,
        bloodwork: 0,
        scans: 0,
        doctors: 0,
      };
    }

    return {
      records: allDocuments.length,
      bloodwork: profile.sections.bloodwork.length,
      scans: profile.sections.scans.length,
      doctors: profile.doctor_access.length,
    };
  }, [profile, allDocuments]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingYourRecords")}</p>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);

  return (
    <AppShell
      user={currentUser}
      title={t("myRecords")}
      subtitle={`${t("dob")} ${valueOrDash(profile.patient.date_of_birth)} · ${t("age")} ${calculatedAge} · ${t(
        "sex"
      )} ${valueOrDash(profile.patient.sex)}`}
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
          <div className="stat-card-label">{t("doctorsWithAccess")}</div>
          <div className="stat-card-value">{stats.doctors}</div>
        </div>
      </div>

      <div
        className="soft-card"
        style={{
          padding: 28,
          marginBottom: 24,
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) auto",
          gap: 18,
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ fontWeight: 950, fontSize: 28, letterSpacing: "-0.055em" }}>
            {t("uploadMedicalDocuments")}
          </div>
          <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.6 }}>
            {t("uploadMedicalDocumentsDesc")}
          </div>
        </div>

        <button
          type="button"
          className="primary-btn"
          style={{
            padding: "15px 22px",
            borderRadius: 18,
            fontSize: 15,
            fontWeight: 950,
            whiteSpace: "nowrap",
          }}
          onClick={() => router.push("/my-records/upload")}
        >
          {t("uploadDocuments")}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 20, marginBottom: 24 }}>
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("myDoctors")}
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
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("doctorAccessRequests")}
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {requests.map((request) => (
              <div key={request.id} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 800 }}>{valueOrDash(request.doctor_name)}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>
                  {valueOrDash(request.doctor_email)}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  {valueOrDash(request.doctor_department)} · {valueOrDash(request.doctor_hospital_name)}
                </div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  {t("status")}: {request.status}
                </div>

                {request.status === "pending" && (
                  <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                    <button className="primary-btn" onClick={() => respondToRequest(request.id, "approved")}>
                      {t("approve")}
                    </button>
                    <button className="secondary-btn" onClick={() => respondToRequest(request.id, "denied")}>
                      {t("deny")}
                    </button>
                  </div>
                )}
              </div>
            ))}

            {!requests.length && <div className="muted-text">{t("noDoctorAccessRequests")}</div>}
          </div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            marginBottom: 18,
          }}
        >
          <div>
            <div className="section-title" style={{ marginBottom: 8 }}>
              {t("myTimeline")}
            </div>

            <div className="muted-text" style={{ lineHeight: 1.6 }}>
              Recent records and care events, sorted by collected/test date when available.
            </div>
          </div>
        </div>

        <ClinicalTimeline
          items={myTimeline}
          maxItems={10}
          onOpenDocument={(documentId) => router.push(`/documents/${documentId}`)}
          onSeeFullTimeline={() => router.push("/my-records/timeline")}
          showSeeFullTimeline
          emptyText={t("noTimelineActivity")}
        />
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
          {SECTION_ORDER.map((section) => (
            <button
              key={section}
              className={activeSection === section ? "primary-btn" : "secondary-btn"}
              onClick={() => setActiveSection(section)}
            >
              {sectionLabels[section]} ({profile.sections[section].length})
            </button>
          ))}
        </div>

        <div
          className="soft-card-tight"
          style={{
            padding: 16,
            marginBottom: 18,
            background: "var(--panel-2)",
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "end",
          }}
        >
          <SelectFilter
            label="Department"
            value={departmentFilter}
            options={filterOptions.departments}
            onChange={(value) => {
              setDepartmentFilter(value);
              setVisibleCount(PAGE_SIZE);
            }}
          />

          <SelectFilter
            label="Hospital"
            value={hospitalFilter}
            options={filterOptions.hospitals}
            onChange={(value) => {
              setHospitalFilter(value);
              setVisibleCount(PAGE_SIZE);
            }}
          />

          <SelectFilter
            label="Year"
            value={yearFilter}
            options={filterOptions.years}
            calendarLike
            onChange={(value) => {
              setYearFilter(value);
              setVisibleCount(PAGE_SIZE);
            }}
          />

          {(departmentFilter || hospitalFilter || yearFilter) && (
            <button
              className="secondary-btn"
              onClick={() => {
                setDepartmentFilter("");
                setHospitalFilter("");
                setYearFilter("");
                setVisibleCount(PAGE_SIZE);
              }}
            >
              Clear filters
            </button>
          )}
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {visibleDocsForSection.map((doc) => (
            <div key={doc.id} className="soft-card-tight" style={{ padding: 18 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.25fr 1fr auto",
                  gap: 18,
                  alignItems: "start",
                }}
              >
                <div>
                  <div style={{ fontWeight: 800, fontSize: 18 }}>
                    {valueOrDash(doc.report_name || doc.filename)}
                  </div>

                  <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.5 }}>
                    {uploaderSubtitle(doc)}
                  </div>

                  <div style={{ marginTop: 10 }}>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "5px 10px",
                        borderRadius: 999,
                        background: doc.is_verified ? "var(--success-bg)" : "var(--warn-bg)",
                        color: doc.is_verified ? "var(--success-text)" : "var(--warn-text)",
                        fontSize: 12,
                        fontWeight: 800,
                      }}
                    >
                      {doc.is_verified ? t("verified") : t("unverified")}
                    </span>
                  </div>

                  <div className="muted-text" style={{ marginTop: 10 }}>
                    {valueOrDash(doc.report_type)} · {getDocumentDateLabel(doc)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)}
                  </div>
                </div>

                <div>
                  <div className="muted-text" style={{ fontSize: 13 }}>
                    Source
                  </div>
                  <div style={{ marginTop: 6, fontWeight: 700 }}>{sectionLabels[doc.section] || doc.section}</div>
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {valueOrDash(doc.referring_doctor)}
                  </div>
                </div>

                <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                  <button className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                    {t("openOriginal")}
                  </button>
                  <button className="primary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                    {t("structuredView")}
                  </button>
                </div>
              </div>
            </div>
          ))}

          {!filteredDocsForSection.length && <div className="muted-text">{t("noRecordsInSection")}</div>}

          {visibleCount < filteredDocsForSection.length && (
            <button
              className="secondary-btn"
              style={{
                justifySelf: "center",
                marginTop: 6,
                padding: "13px 18px",
                borderRadius: 16,
                fontWeight: 950,
              }}
              onClick={() => setVisibleCount((current) => current + PAGE_SIZE)}
            >
              Show More
            </button>
          )}
        </div>
      </div>

      {activeSection === "bloodwork" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 8 }}>
            {t("bloodworkTrends")}
          </div>

          <div className="muted-text" style={{ marginBottom: 16 }}>
            Trends are sorted by clinical importance. Graphs show the most recent 5 collections by collected/test date.
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            {sortedTrends.map((trend) => {
              const expanded = expandedTrendKey === trend.test_key;
              const graphPoints = getMostRecentTrendPoints(trend.points, 5);
              const allReportPoints = [...trend.points].sort((a, b) => compareDatesDescending(a.date, b.date));
              const highlightedDocumentId = hoveredTrendPoint[trend.test_key] ?? null;

              return (
                <div
                  key={trend.test_key}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: expanded ? "minmax(0, 1fr) auto" : "minmax(0, 1fr) 420px auto",
                      gap: 18,
                      alignItems: "center",
                      transition: "grid-template-columns 300ms cubic-bezier(0.22, 1, 0.36, 1)",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 800, fontSize: 18 }}>{trend.display_name}</div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        {valueOrDash(trend.category)} · {t("unit")} {valueOrDash(trend.unit)}
                      </div>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                          gap: 12,
                          marginTop: 14,
                        }}
                      >
                        <div>
                          <div className="muted-text" style={{ fontSize: 12 }}>
                            {t("latest")}
                          </div>
                          <div style={{ fontWeight: 800, fontSize: 24 }}>
                            {valueOrDash(trend.latest?.value_display)}
                          </div>
                        </div>

                        <div>
                          <div className="muted-text" style={{ fontSize: 12 }}>
                            {t("previous")}
                          </div>
                          <div style={{ fontWeight: 800, fontSize: 24 }}>
                            {trend.previous ? valueOrDash(trend.previous.value_display) : "€”"}
                          </div>
                        </div>

                        <div>
                          <div className="muted-text" style={{ fontSize: 12 }}>
                            {t("delta")}
                          </div>
                          <div style={{ fontWeight: 800, fontSize: 24 }}>
                            {trend.delta === null || trend.delta === undefined
                              ? "€”"
                              : trend.delta > 0
                              ? `+${trend.delta}`
                              : `${trend.delta}`}
                          </div>
                        </div>
                      </div>

                      <div className="muted-text" style={{ marginTop: 10 }}>
                        {t("latestSample")}: {valueOrDash(trend.latest?.date)} · {t("ref")}{" "}
                        {valueOrDash(trend.latest?.reference_range)}
                      </div>
                    </div>

                    {!expanded && (
                      <div
                        style={{
                          width: "100%",
                          height: 150,
                          justifySelf: "stretch",
                          opacity: expanded ? 0 : 1,
                          transform: expanded ? "scale(0.96) translateY(6px)" : "scale(1) translateY(0)",
                          transformOrigin: "center",
                          transition: "opacity 220ms ease, transform 300ms cubic-bezier(0.22, 1, 0.36, 1)",
                        }}
                      >
                        <TrendChart
                          points={graphPoints}
                          highlightedDocumentId={highlightedDocumentId}
                          unit={trend.unit}
                        />
                      </div>
                    )}

                    <button className="secondary-btn" onClick={() => setExpandedTrendKey(expanded ? null : trend.test_key)}>
                      {expanded ? "Collapse" : "Expand"}
                    </button>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateRows: expanded ? "1fr" : "0fr",
                      opacity: expanded ? 1 : 0,
                      transform: expanded ? "scale(1) translateY(0)" : "scale(0.985) translateY(-10px)",
                      transformOrigin: "top center",
                      transition:
                        "grid-template-rows 380ms cubic-bezier(0.22, 1, 0.36, 1), opacity 260ms ease, transform 380ms cubic-bezier(0.22, 1, 0.36, 1)",
                    }}
                  >
                    <div style={{ overflow: "hidden" }}>
                      <div
                        style={{
                          marginTop: 18,
                          padding: 20,
                          borderRadius: 22,
                          border: "1px solid var(--border)",
                          background: "linear-gradient(180deg, var(--panel), var(--panel-2))",
                          width: "100%",
                          height: 410,
                          boxSizing: "border-box",
                        }}
                      >
                        <TrendChart
                          points={graphPoints}
                          highlightedDocumentId={highlightedDocumentId}
                          expanded
                          unit={trend.unit}
                        />
                      </div>
                    </div>
                  </div>

                  {expanded && (
                    <div
                      style={{
                        marginTop: 18,
                        paddingTop: 16,
                        borderTop: "1px solid var(--border)",
                        display: "grid",
                        gap: 10,
                      }}
                    >
                      <div style={{ fontWeight: 900 }}>Reports used in this trend</div>

                      {allReportPoints.map((point, index) => {
                        const isHighlighted = highlightedDocumentId === point.document_id;

                        return (
                          <button
                            key={`${trend.test_key}-${point.document_id}-${point.date}-${index}`}
                            onMouseEnter={() =>
                              setHoveredTrendPoint((prev) => ({
                                ...prev,
                                [trend.test_key]: point.document_id,
                              }))
                            }
                            onMouseLeave={() =>
                              setHoveredTrendPoint((prev) => ({
                                ...prev,
                                [trend.test_key]: null,
                              }))
                            }
                            onClick={() => router.push(`/documents/${point.document_id}`)}
                            style={{
                              border: `1px solid ${isHighlighted ? "var(--primary)" : "var(--border)"}`,
                              background: isHighlighted
                                ? "color-mix(in srgb, var(--primary) 8%, var(--panel))"
                                : "var(--panel)",
                              borderRadius: 16,
                              padding: 14,
                              textAlign: "left",
                              cursor: "pointer",
                              display: "grid",
                              gridTemplateColumns: "1fr auto",
                              gap: 12,
                              alignItems: "center",
                              transition: "all 150ms ease",
                            }}
                          >
                            <div>
                              <div style={{ fontWeight: 850 }}>
                                {valueOrDash(point.report_name || `Report ${point.document_id}`)}
                              </div>
                              <div className="muted-text" style={{ marginTop: 4 }}>
                                {valueOrDash(point.date)} · Ref {valueOrDash(point.reference_range)}
                              </div>
                            </div>

                            <div style={{ fontWeight: 950 }}>
                              {valueOrDash(point.value_display)} {trend.unit || ""}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {!sortedTrends.length && <div className="muted-text">{t("noNumericTrends")}</div>}
          </div>
        </div>
      )}
    </AppShell>
  );
}


