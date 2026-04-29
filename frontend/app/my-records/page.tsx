"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { useUploadManager } from "@/components/upload-provider";
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
  has_abnormal?: boolean;
  has_abnormal_labs?: boolean;
  uploaded_by?: UploadedBy | null;
  note_preview?: string | null;
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
    notes?: DocumentCard[];
    bloodwork: DocumentCard[];
    medications: DocumentCard[];
    scans: DocumentCard[];
    hospitalizations: DocumentCard[];
    other: DocumentCard[];
  };
  doctor_access: DoctorAccess[];
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
  isAbnormal?: boolean;
};

const PAGE_SIZE = 8;

const SECTION_ORDER = ["bloodwork", "scans", "medications", "hospitalizations", "notes", "other"] as const;

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

  const cleaned = value.trim();
  const direct = new Date(cleaned).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = cleaned.match(/(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);

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
  if (!value) return "—";

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
  if (doc.created_at) return `Uploaded ${formatDate(doc.created_at)}`;
  return "No date";
}

function hasAbnormal(doc: DocumentCard) {
  return Boolean(doc.has_abnormal || doc.has_abnormal_labs);
}

function getDocumentTitle(doc: DocumentCard) {
  return doc.report_name || doc.filename || `Document ${doc.id}`;
}

function getUploaderText(doc: DocumentCard) {
  if (!doc.uploaded_by) return "Uploaded by unknown user";

  const parts = [
    doc.uploaded_by.full_name,
    doc.uploaded_by.department,
    doc.uploaded_by.hospital_name,
  ].filter(Boolean);

  return `Uploaded by ${parts.join(" · ")}`;
}

function getSectionDocuments(profile: MyProfileResponse | null, section: SectionKey) {
  if (!profile) return [];

  if (section === "notes") {
    return profile.sections.notes || [];
  }

  return profile.sections[section] || [];
}

function SmallTrendChart({
  points,
  unit,
}: {
  points: TrendPoint[];
  unit?: string | null;
}) {
  const sorted = [...points].sort((a, b) => compareDatesAscending(a.date, b.date)).slice(-8);

  if (!sorted.length) return null;

  const width = 620;
  const height = 150;
  const margin = { top: 18, right: 20, bottom: 26, left: 40 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const values = sorted.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.2, 1);
  const yMin = min - spread * 0.18;
  const yMax = max + spread * 0.18;
  const yRange = yMax - yMin || 1;

  const coords = sorted.map((point, index) => {
    const x = margin.left + (index * plotWidth) / Math.max(sorted.length - 1, 1);
    const y = margin.top + plotHeight - ((point.value - yMin) / yRange) * plotHeight;
    return { x, y, point };
  });

  const line = coords.map((coord) => `${coord.x},${coord.y}`).join(" ");

  return (
    <div style={{ height: 150 }}>
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ display: "block", width: "100%", height: "100%" }}
      >
        <line
          x1={margin.left}
          y1={margin.top + plotHeight}
          x2={width - margin.right}
          y2={margin.top + plotHeight}
          stroke="var(--border)"
          strokeWidth="1"
        />
        <line
          x1={margin.left}
          y1={margin.top + plotHeight / 2}
          x2={width - margin.right}
          y2={margin.top + plotHeight / 2}
          stroke="var(--border)"
          strokeWidth="1"
          opacity="0.6"
        />
        <polyline
          fill="none"
          stroke="var(--primary)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={line}
        />
        {coords.map((coord, index) => (
          <circle
            key={`${coord.point.document_id}-${index}`}
            cx={coord.x}
            cy={coord.y}
            r="5"
            fill="var(--primary)"
            stroke="var(--panel)"
            strokeWidth="3"
          />
        ))}
        {coords.length > 0 && (
          <text x={width - margin.right} y={22} textAnchor="end" fill="var(--muted)" fontSize="12" fontWeight="850">
            {coords[coords.length - 1].point.value_display} {unit || ""}
          </text>
        )}
      </svg>
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

function StatCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string | number;
  note?: string;
}) {
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

export default function MyRecordsPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const { activeCount, refreshUploadJobs } = useUploadManager();

  const sectionLabels: Record<SectionKey, string> = {
    bloodwork: "Bloodwork",
    scans: "Scans",
    medications: "Medications",
    hospitalizations: "Hospitalizations",
    notes: "Clinical notes",
    other: "Other",
  };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [activeSection, setActiveSection] = useState<SectionKey>("bloodwork");

  const [departmentFilter, setDepartmentFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const fetchMe = useCallback(async () => {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  }, [router]);

  const fetchProfile = useCallback(async () => {
    const response = await api.get<MyProfileResponse>("/my/profile");
    setProfile({
      ...response.data,
      sections: {
        notes: response.data.sections.notes || [],
        bloodwork: response.data.sections.bloodwork || [],
        medications: response.data.sections.medications || [],
        scans: response.data.sections.scans || [],
        hospitalizations: response.data.sections.hospitalizations || [],
        other: response.data.sections.other || [],
      },
      events: response.data.events || [],
    });
    return response.data;
  }, []);

  const fetchRequests = useCallback(async () => {
    try {
      const response = await api.get<AccessRequest[]>("/my/access-requests");
      setRequests(Array.isArray(response.data) ? response.data : []);
    } catch {
      setRequests([]);
    }
  }, []);

  const fetchTrends = useCallback(async (patientId: number) => {
    try {
      const response = await api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`);
      setTrends(Array.isArray(response.data) ? response.data : []);
    } catch {
      setTrends([]);
    }
  }, []);

  const refreshRecordsSilently = useCallback(async () => {
    try {
      setRefreshing(true);
      const profileResponse = await fetchProfile();
      await Promise.all([fetchRequests(), fetchTrends(profileResponse.patient.id), refreshUploadJobs()]);
    } catch {
      // Silent refresh should not replace the page with an error.
    } finally {
      setRefreshing(false);
    }
  }, [fetchProfile, fetchRequests, fetchTrends, refreshUploadJobs]);

  async function fullRefresh() {
    try {
      setError("");
      await refreshRecordsSilently();
    } catch (err) {
      setError(getErrorMessage(err, "Could not refresh records."));
    }
  }

  async function respondToRequest(requestId: number, status: "approved" | "denied") {
    try {
      setError("");
      await api.post(`/access-requests/${requestId}/respond`, { status });
      await refreshRecordsSilently();
    } catch (err) {
      setError(getErrorMessage(err, "Could not respond to access request."));
    }
  }

  async function openOriginal(documentId: number) {
    try {
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
        await Promise.all([fetchRequests(), fetchTrends(profileResponse.patient.id), refreshUploadJobs()]);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load your records."));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [fetchMe, fetchProfile, fetchRequests, fetchTrends, refreshUploadJobs, router]);

  useEffect(() => {
    function handleUploadComplete() {
      void refreshRecordsSilently();
    }

    window.addEventListener("bloodwork-upload-complete", handleUploadComplete);

    return () => {
      window.removeEventListener("bloodwork-upload-complete", handleUploadComplete);
    };
  }, [refreshRecordsSilently]);

  useEffect(() => {
    if (activeCount <= 0) return;

    const interval = window.setInterval(() => {
      void refreshRecordsSilently();
    }, 4000);

    return () => window.clearInterval(interval);
  }, [activeCount, refreshRecordsSilently]);

  useEffect(() => {
    setDepartmentFilter("");
    setHospitalFilter("");
    setYearFilter("");
    setVisibleCount(PAGE_SIZE);
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

  const pendingRequests = useMemo(
    () => requests.filter((request) => request.status === "pending"),
    [requests]
  );

  const timelineItems = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => ({
      id: `doc-${doc.id}`,
      type: "document",
      date: getDocumentClinicalDate(doc),
      title: getDocumentTitle(doc),
      subtitle: `${getDocumentDateLabel(doc)} · ${sectionLabels[(doc.section as SectionKey) || "other"] || doc.section} · ${
        doc.is_verified ? "Verified" : "Unverified"
      }`,
      documentId: doc.id,
      isAbnormal: hasAbnormal(doc),
    }));

    const eventItems: TimelineItem[] = (profile.events || []).map((event) => ({
      id: `event-${event.id}`,
      type: "event",
      date: event.discharged_at || event.admitted_at || "",
      title: event.title,
      subtitle: `${event.status === "active" ? "Active hospitalization" : "Discharged"} · ${
        event.doctor_name || "Unknown doctor"
      }`,
      eventId: event.id,
    }));

    return [...documentItems, ...eventItems]
      .filter((item) => item.date || item.title)
      .sort((a, b) => compareDatesDescending(a.date, b.date))
      .slice(0, 8);
  }, [profile, allDocuments]);

  const sortedTrends = useMemo(() => {
    return [...trends]
      .filter((trend) => trend.points?.length)
      .map((trend) => {
        const sortedPoints = [...trend.points].sort((a, b) => compareDatesAscending(a.date, b.date));
        const latest = sortedPoints[sortedPoints.length - 1] || trend.latest;
        const previous = sortedPoints[sortedPoints.length - 2] || trend.previous || null;
        const delta = latest && previous ? Number((latest.value - previous.value).toFixed(2)) : null;

        return {
          ...trend,
          points: sortedPoints,
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
      })
      .slice(0, 6);
  }, [trends]);

  const stats = useMemo(() => {
    if (!profile) {
      return {
        total: 0,
        bloodwork: 0,
        scans: 0,
        abnormal: 0,
        doctors: 0,
      };
    }

    return {
      total: allDocuments.length,
      bloodwork: getSectionDocuments(profile, "bloodwork").length,
      scans: getSectionDocuments(profile, "scans").length,
      abnormal: allDocuments.filter(hasAbnormal).length,
      doctors: profile.doctor_access.length,
    };
  }, [profile, allDocuments]);

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
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", alignItems: "center", gap: 12 }}>
          <Spinner size={20} />
          <span className="muted-text">Loading your records...</span>
        </div>
      </main>
    );
  }

  const calculatedAge = calculateAgeFromDob(profile.patient.date_of_birth);

  return (
    <AppShell
      user={currentUser}
      title="My Records"
      subtitle={`DOB ${valueOrDash(profile.patient.date_of_birth)} · Age ${calculatedAge} · Sex ${valueOrDash(
        profile.patient.sex
      )}`}
      rightContent={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button type="button" className="secondary-btn" onClick={fullRefresh}>
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
          <button type="button" className="primary-btn" onClick={() => router.push("/my-records/upload")}>
            Upload
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

      {activeCount > 0 && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            display: "flex",
            alignItems: "center",
            gap: 12,
            background: "var(--panel-2)",
          }}
        >
          <Spinner size={18} />
          <div>
            <div style={{ fontWeight: 900 }}>
              {activeCount} upload{activeCount === 1 ? "" : "s"} processing
            </div>
            <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
              This page will refresh automatically when processing finishes.
            </div>
          </div>
        </div>
      )}

      {pendingRequests.length > 0 && (
        <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
          <div style={{ fontWeight: 950, fontSize: 20, letterSpacing: "-0.04em", marginBottom: 12 }}>
            Doctor access requests
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {pendingRequests.map((request) => (
              <div
                key={request.id}
                className="soft-card-tight"
                style={{
                  padding: 14,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 14,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <div style={{ fontWeight: 900 }}>
                    Dr. {request.doctor_name || "Unknown doctor"} requested access to your profile
                  </div>
                  <div className="muted-text" style={{ marginTop: 5, fontSize: 12 }}>
                    {request.doctor_department || "Department not set"} ·{" "}
                    {request.doctor_hospital_name || "Hospital not set"} · Requested{" "}
                    {formatDate(request.requested_at)}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => respondToRequest(request.id, "denied")}
                  >
                    Deny
                  </button>
                  <button
                    type="button"
                    className="primary-btn"
                    onClick={() => respondToRequest(request.id, "approved")}
                  >
                    Approve
                  </button>
                </div>
              </div>
            ))}
          </div>
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
        <StatCard label="Total records" value={stats.total} note="All uploaded records" />
        <StatCard label="Bloodwork" value={stats.bloodwork} note="Structured lab reports" />
        <StatCard label="Scans" value={stats.scans} note="Imaging and scans" />
        <StatCard label="Abnormal flags" value={stats.abnormal} note="Results marked outside range" />
        <StatCard label="Doctors with access" value={stats.doctors} note="Approved profile access" />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.25fr) minmax(320px, 0.75fr)",
          gap: 24,
          alignItems: "start",
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 22 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 16,
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: 16,
            }}
          >
            <div>
              <div style={{ fontWeight: 950, fontSize: 22, letterSpacing: "-0.05em" }}>Clinical timeline</div>
              <div className="muted-text" style={{ marginTop: 5 }}>
                Recent documents and clinical events.
              </div>
            </div>

            <button type="button" className="secondary-btn" onClick={() => router.push("/my-records/timeline")}>
              Full timeline
            </button>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {timelineItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className="soft-card-tight"
                onClick={() => item.documentId && router.push(`/documents/${item.documentId}`)}
                style={{
                  padding: 14,
                  textAlign: "left",
                  display: "grid",
                  gridTemplateColumns: "auto minmax(0, 1fr) auto",
                  gap: 12,
                  alignItems: "center",
                  cursor: item.documentId ? "pointer" : "default",
                  borderColor: item.isAbnormal ? "var(--danger-border)" : "var(--border)",
                }}
              >
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 999,
                    background: item.isAbnormal ? "var(--danger-text)" : "var(--primary)",
                  }}
                />

                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 900,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {item.title}
                  </div>
                  <div className="muted-text" style={{ marginTop: 5, fontSize: 12, lineHeight: 1.45 }}>
                    {item.subtitle}
                  </div>
                </div>

                <div className="muted-text" style={{ fontSize: 12, fontWeight: 850 }}>
                  {formatDate(item.date)}
                </div>
              </button>
            ))}

            {!timelineItems.length && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 850 }}>No timeline items yet</div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  Upload a document to start building your medical timeline.
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="soft-card" style={{ padding: 22 }}>
          <div style={{ fontWeight: 950, fontSize: 22, letterSpacing: "-0.05em" }}>Profile</div>
          <div className="muted-text" style={{ marginTop: 5, marginBottom: 16 }}>
            Patient identity and approved access.
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            {[
              ["Name", profile.patient.full_name],
              ["DOB", profile.patient.date_of_birth],
              ["Age", calculatedAge],
              ["Sex", profile.patient.sex],
              ["CNP", profile.patient.cnp],
              ["Patient ID", profile.patient.patient_identifier],
            ].map(([label, value]) => (
              <div key={label} className="soft-card-tight" style={{ padding: 12 }}>
                <div className="muted-text" style={{ fontSize: 11, fontWeight: 850 }}>
                  {label}
                </div>
                <div style={{ fontWeight: 900, marginTop: 4 }}>{valueOrDash(value)}</div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 18 }}>
            <div style={{ fontWeight: 900, marginBottom: 10 }}>Approved doctors</div>

            <div style={{ display: "grid", gap: 10 }}>
              {profile.doctor_access.map((doctor) => (
                <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 12 }}>
                  <div style={{ fontWeight: 900 }}>{doctor.doctor_name || doctor.doctor_email}</div>
                  <div className="muted-text" style={{ marginTop: 5, fontSize: 12, lineHeight: 1.45 }}>
                    {[doctor.department, doctor.hospital_name].filter(Boolean).join(" · ") || "No department set"}
                  </div>
                </div>
              ))}

              {!profile.doctor_access.length && (
                <div className="soft-card-tight" style={{ padding: 12, background: "var(--panel-2)" }}>
                  <div className="muted-text">No doctors currently have access.</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {sortedTrends.length > 0 && (
        <div className="soft-card" style={{ padding: 22, marginBottom: 24 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 16,
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: 16,
            }}
          >
            <div>
              <div style={{ fontWeight: 950, fontSize: 22, letterSpacing: "-0.05em" }}>
                Bloodwork trends
              </div>
              <div className="muted-text" style={{ marginTop: 5 }}>
                Latest structured values from your lab reports.
              </div>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: 14,
            }}
          >
            {sortedTrends.map((trend) => {
              const abnormal =
                trend.latest?.flag && String(trend.latest.flag).trim().toLowerCase() !== "normal";

              return (
                <button
                  key={trend.test_key}
                  type="button"
                  className="soft-card-tight"
                  onClick={() => trend.latest?.document_id && router.push(`/documents/${trend.latest.document_id}`)}
                  style={{
                    padding: 16,
                    textAlign: "left",
                    cursor: "pointer",
                    borderColor: abnormal ? "var(--danger-border)" : "var(--border)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
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
                        {trend.category || "Lab result"}
                      </div>
                    </div>

                    <div style={{ textAlign: "right", flex: "0 0 auto" }}>
                      <div style={{ fontWeight: 950 }}>
                        {trend.latest?.value_display} {trend.unit || ""}
                      </div>
                      {trend.delta !== null && trend.delta !== undefined && (
                        <div className="muted-text" style={{ fontSize: 12, marginTop: 5 }}>
                          {trend.delta > 0 ? "+" : ""}
                          {trend.delta}
                        </div>
                      )}
                    </div>
                  </div>

                  <div style={{ marginTop: 10 }}>
                    <SmallTrendChart points={trend.points} unit={trend.unit} />
                  </div>

                  {abnormal && (
                    <div
                      style={{
                        display: "inline-flex",
                        marginTop: 10,
                        borderRadius: 999,
                        padding: "5px 9px",
                        background: "var(--danger-bg)",
                        color: "var(--danger-text)",
                        border: "1px solid var(--danger-border)",
                        fontSize: 12,
                        fontWeight: 900,
                      }}
                    >
                      {trend.latest.flag}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="soft-card" style={{ padding: 22 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
            marginBottom: 16,
          }}
        >
          <div>
            <div style={{ fontWeight: 950, fontSize: 22, letterSpacing: "-0.05em" }}>Documents</div>
            <div className="muted-text" style={{ marginTop: 5 }}>
              Organized by category, date, and source.
            </div>
          </div>

          <button type="button" className="primary-btn" onClick={() => router.push("/my-records/upload")}>
            Upload
          </button>
        </div>

        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          {SECTION_ORDER.map((section) => (
            <SectionPill
              key={section}
              active={activeSection === section}
              label={sectionLabels[section]}
              count={getSectionDocuments(profile, section).length}
              onClick={() => setActiveSection(section)}
            />
          ))}
        </div>

        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            marginBottom: 18,
          }}
        >
          <select
            className="text-input"
            value={departmentFilter}
            onChange={(event) => setDepartmentFilter(event.target.value)}
            style={{ minWidth: 190 }}
          >
            <option value="">All departments</option>
            {filterOptions.departments.map((department) => (
              <option key={department} value={department}>
                {department}
              </option>
            ))}
          </select>

          <select
            className="text-input"
            value={hospitalFilter}
            onChange={(event) => setHospitalFilter(event.target.value)}
            style={{ minWidth: 190 }}
          >
            <option value="">All hospitals</option>
            {filterOptions.hospitals.map((hospital) => (
              <option key={hospital} value={hospital}>
                {hospital}
              </option>
            ))}
          </select>

          <select
            className="text-input"
            value={yearFilter}
            onChange={(event) => setYearFilter(event.target.value)}
            style={{ minWidth: 160 }}
          >
            <option value="">All years</option>
            {filterOptions.years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {visibleDocuments.map((doc) => (
            <div
              key={doc.id}
              className="soft-card-tight"
              style={{
                padding: 16,
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 14,
                alignItems: "center",
                borderColor: hasAbnormal(doc) ? "var(--danger-border)" : "var(--border)",
              }}
            >
              <button
                type="button"
                onClick={() => router.push(`/documents/${doc.id}`)}
                style={{
                  padding: 0,
                  border: "none",
                  background: "transparent",
                  textAlign: "left",
                  minWidth: 0,
                  cursor: "pointer",
                  color: "inherit",
                }}
              >
                <div style={{ display: "flex", gap: 10, alignItems: "center", minWidth: 0 }}>
                  {hasAbnormal(doc) && (
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 999,
                        background: "var(--danger-text)",
                        flex: "0 0 auto",
                      }}
                    />
                  )}

                  <div
                    style={{
                      fontWeight: 950,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {getDocumentTitle(doc)}
                  </div>
                </div>

                <div className="muted-text" style={{ marginTop: 7, fontSize: 12, lineHeight: 1.5 }}>
                  {getDocumentDateLabel(doc)} · {getUploaderText(doc)} ·{" "}
                  {doc.is_verified ? "Verified" : "Unverified"}
                </div>

                {doc.note_preview && (
                  <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.5 }}>
                    {doc.note_preview}
                  </div>
                )}
              </button>

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <button type="button" className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                  Original
                </button>
                <button type="button" className="primary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                  View
                </button>
              </div>
            </div>
          ))}

          {!visibleDocuments.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>No documents in this section yet</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                Upload a document or choose another section.
              </div>
            </div>
          )}
        </div>

        {visibleCount < filteredDocuments.length && (
          <div style={{ display: "flex", justifyContent: "center", marginTop: 18 }}>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Show more
            </button>
          </div>
        )}
      </div>
    </AppShell>
  );
}