"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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

function TrendSparkline({ points }: { points: TrendPoint[] }) {
  if (!points.length) return null;

  const width = 180;
  const height = 52;
  const padding = 6;

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const coords = points.map((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(points.length - 1, 1);
    const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  });

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline fill="none" stroke="var(--primary)" strokeWidth="2.5" points={coords.join(" ")} />
      {coords.map((coord, idx) => {
        const [x, y] = coord.split(",");
        return <circle key={idx} cx={x} cy={y} r="2.8" fill="var(--primary)" />;
      })}
    </svg>
  );
}

function getDocumentDate(doc: DocumentCard) {
  return doc.test_date || "";
}

function getEventDate(event: PatientEvent) {
  return event.discharged_at || event.admitted_at || "";
}

export default function MyRecordsPage() {
  const router = useRouter();
  const { t } = useLanguage();

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
    const response = await api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`);
    setTrends(response.data);
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
  }, []);

  const allDocuments = useMemo(() => {
    if (!profile) return [];

    return SECTION_ORDER.flatMap((section) => profile.sections[section]).sort((a, b) =>
      getDocumentDate(b).localeCompare(getDocumentDate(a))
    );
  }, [profile]);

  const recordsByDoctor = useMemo(() => {
    if (!profile) return [];

    const groups = new Map<string, { label: string; docs: DocumentCard[] }>();

    allDocuments.forEach((doc) => {
      const uploader = doc.uploaded_by;
      const key = uploader?.id ? `user-${uploader.id}` : "unknown";
      const label = uploader
        ? `${uploader.full_name}${uploader.department ? ` · ${uploader.department}` : ""}${
            uploader.hospital_name ? ` · ${uploader.hospital_name}` : ""
          }`
        : t("unknownUploader");

      if (!groups.has(key)) groups.set(key, { label, docs: [] });
      groups.get(key)!.docs.push(doc);
    });

    return Array.from(groups.values()).sort((a, b) => b.docs.length - a.docs.length);
  }, [profile, allDocuments, t]);

  const myTimeline = useMemo<TimelineItem[]>(() => {
    if (!profile) return [];

    const documentItems: TimelineItem[] = allDocuments.map((doc) => ({
      id: `doc-${doc.id}`,
      type: "document",
      date: getDocumentDate(doc),
      title: valueOrDash(doc.report_name || doc.filename),
      subtitle: `${sectionLabels[doc.section] || doc.section} · ${valueOrDash(doc.report_type)} · ${
        doc.is_verified ? t("verified") : t("unverified")
      }`,
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

    return [...documentItems, ...eventItems].sort((a, b) => {
      const aDate = a.date || "";
      const bDate = b.date || "";
      return bDate.localeCompare(aDate);
    });
  }, [profile, allDocuments, t]);

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

  const docsForSection = profile.sections[activeSection];

  return (
    <AppShell
      user={currentUser}
      title={t("myRecords")}
      subtitle={`${t("dob")} ${valueOrDash(profile.patient.date_of_birth)} · ${t("age")} ${valueOrDash(
        profile.patient.age
      )} · ${t("sex")} ${valueOrDash(profile.patient.sex)}`}
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

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, marginBottom: 24 }}>
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
        <div className="section-title" style={{ marginBottom: 8 }}>
          {t("myTimeline")}
        </div>

        <div className="muted-text" style={{ marginBottom: 18, lineHeight: 1.6 }}>
          {t("myTimelineDesc")}
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {myTimeline.map((item) => (
            <div key={item.id} className="soft-card-tight" style={{ padding: 16 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 999,
                    background: item.type === "event" ? "var(--primary)" : "var(--muted)",
                    display: "inline-flex",
                    marginTop: 6,
                    flex: "0 0 auto",
                  }}
                />

                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 850 }}>{item.title}</div>
                  <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
                    {valueOrDash(item.date)} · {item.subtitle}
                  </div>
                </div>

                {item.documentId && (
                  <button type="button" className="secondary-btn" onClick={() => router.push(`/documents/${item.documentId}`)}>
                    {t("open")}
                  </button>
                )}
              </div>
            </div>
          ))}

          {!myTimeline.length && (
            <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noTimelineActivity")}</div>
            </div>
          )}
        </div>
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

        <div style={{ display: "grid", gap: 14 }}>
          {docsForSection.map((doc) => (
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

                  <div style={{ marginTop: 8 }}>
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
                    {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                  </div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    {valueOrDash(doc.lab_name)} · {valueOrDash(doc.sample_type)}
                  </div>
                </div>

                <div>
                  <div className="muted-text" style={{ fontSize: 13 }}>
                    {t("uploadedBy")}
                  </div>
                  <div style={{ marginTop: 6, fontWeight: 700 }}>{valueOrDash(doc.uploaded_by?.full_name)}</div>
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {valueOrDash(doc.uploaded_by?.department)} · {valueOrDash(doc.uploaded_by?.hospital_name)}
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

          {!docsForSection.length && <div className="muted-text">{t("noRecordsInSection")}</div>}
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          {t("recordsGroupedByUploader")}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {recordsByDoctor.map((group) => (
            <div key={group.label} className="soft-card-tight" style={{ padding: 18 }}>
              <div style={{ fontWeight: 800, marginBottom: 10 }}>
                {group.label} ({group.docs.length})
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                {group.docs.map((doc) => (
                  <div
                    key={doc.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 16,
                      padding: "10px 0",
                      borderTop: "1px solid var(--border)",
                      flexWrap: "wrap",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700 }}>{valueOrDash(doc.report_name || doc.filename)}</div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        {sectionLabels[doc.section] || doc.section} · {valueOrDash(doc.test_date)}
                      </div>
                    </div>
                    <button className="secondary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                      {t("viewStructuredData")}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {!recordsByDoctor.length && <div className="muted-text">{t("noUploadedRecords")}</div>}
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          {t("bloodworkTrends")}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {trends.map((trend) => (
            <div key={trend.test_key} className="soft-card-tight" style={{ padding: 18 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.1fr 220px",
                  gap: 18,
                  alignItems: "center",
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
                        {valueOrDash(trend.latest.value_display)}
                      </div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>
                        {t("previous")}
                      </div>
                      <div style={{ fontWeight: 800, fontSize: 24 }}>
                        {trend.previous ? valueOrDash(trend.previous.value_display) : "—"}
                      </div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>
                        {t("delta")}
                      </div>
                      <div style={{ fontWeight: 800, fontSize: 24 }}>
                        {trend.delta === null || trend.delta === undefined
                          ? "—"
                          : trend.delta > 0
                          ? `+${trend.delta}`
                          : `${trend.delta}`}
                      </div>
                    </div>
                  </div>

                  <div className="muted-text" style={{ marginTop: 10 }}>
                    {t("latestSample")}: {valueOrDash(trend.latest.date)} · {t("ref")}{" "}
                    {valueOrDash(trend.latest.reference_range)}
                  </div>
                </div>

                <div style={{ justifySelf: "end" }}>
                  <TrendSparkline points={trend.points} />
                </div>
              </div>
            </div>
          ))}

          {!trends.length && <div className="muted-text">{t("noNumericTrends")}</div>}
        </div>
      </div>
    </AppShell>
  );
}
