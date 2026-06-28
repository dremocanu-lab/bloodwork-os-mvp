"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
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

type PatientMedication = {
  id: number;
  name: string;
  status: string;
  dose_strength?: string | null;
  frequency?: string | null;
  is_uncertain: boolean;
  official_match_status?: string | null;
  reason?: string | null;
};

type DocumentCard = {
  id: number;
  filename: string;
  report_name?: string | null;
  section: string;
  is_verified: boolean;
  has_abnormal?: boolean;
  has_abnormal_labs?: boolean;
  reviewed_by_current_doctor?: boolean;
  collected_on?: string | null;
  test_date?: string | null;
  reported_on?: string | null;
  registered_on?: string | null;
  generated_on?: string | null;
  created_at?: string | null;
};

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    patient_identifier?: string | null;
  };
  sections: {
    notes?: DocumentCard[];
    bloodwork?: DocumentCard[];
    discharge_summary?: DocumentCard[];
    scans?: DocumentCard[];
    hospitalizations?: DocumentCard[];
    other?: DocumentCard[];
  };
};

// ── Helpers ───────────────────────────────────────────────────────────────────

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

function formatDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

function compareDatesAscending(a?: string | null, b?: string | null) {
  return parseDateTime(a) - parseDateTime(b);
}

function compareDatesDescending(a?: string | null, b?: string | null) {
  return parseDateTime(b) - parseDateTime(a);
}

function getDocumentClinicalDate(doc: DocumentCard) {
  return doc.collected_on || doc.test_date || doc.reported_on || doc.registered_on || doc.generated_on || doc.created_at || "";
}

function getDocumentTitle(doc: DocumentCard) {
  return doc.report_name || doc.filename || `Document ${doc.id}`;
}

function hasAbnormal(doc: DocumentCard) {
  return Boolean(doc.has_abnormal || doc.has_abnormal_labs);
}

function getRecentTrendPoints(points: TrendPoint[], limit = 5) {
  return [...points].sort((a, b) => compareDatesAscending(a.date, b.date)).slice(-limit);
}

// ── Mini SVG Trend Chart ──────────────────────────────────────────────────────

function MiniTrendChart({ points, unit, abnormal }: { points: TrendPoint[]; unit?: string | null; abnormal?: boolean }) {
  const sorted = getRecentTrendPoints(points, 5);
  if (sorted.length < 2) return null;

  const width = 160;
  const height = 56;
  const margin = { top: 6, right: 8, bottom: 6, left: 8 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = sorted.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.25, 1);
  const yMin = min - spread * 0.2;
  const yMax = max + spread * 0.2;
  const yRange = yMax - yMin || 1;
  const coords = sorted.map((point, index) => ({
    x: margin.left + (index * plotWidth) / Math.max(sorted.length - 1, 1),
    y: margin.top + plotHeight - ((point.value - yMin) / yRange) * plotHeight,
    point,
  }));
  const line = coords.map((c) => `${c.x},${c.y}`).join(" ");
  const strokeColor = abnormal ? "var(--danger-text)" : "var(--primary)";

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block", flexShrink: 0 }}>
      <polyline fill="none" stroke={strokeColor} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" points={line} />
      {coords.map((c, i) => (
        <circle key={i} cx={c.x} cy={c.y} r="3" fill={strokeColor} stroke="var(--panel)" strokeWidth="2" />
      ))}
    </svg>
  );
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

function StatCard({
  label, value, accent, onClick, subtitle,
}: {
  label: string;
  value: number | string;
  accent?: string;
  onClick?: () => void;
  subtitle?: string;
}) {
  return (
    <div
      className="soft-card"
      onClick={onClick}
      style={{
        padding: "18px 20px",
        cursor: onClick ? "pointer" : "default",
        transition: "border-color 180ms ease",
        borderColor: accent ? `color-mix(in srgb, ${accent} 40%, var(--border))` : "var(--border)",
      }}
    >
      <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-0.04em", lineHeight: 1, color: accent || "var(--foreground)" }}>
        {value}
      </div>
      {subtitle && <div className="muted-text" style={{ marginTop: 6, fontSize: 11 }}>{subtitle}</div>}
    </div>
  );
}

// ── Section breakdown card ────────────────────────────────────────────────────

const SECTION_LABELS: Record<string, string> = {
  bloodwork: "Bloodwork",
  discharge_summary: "Discharge summaries",
  scans: "Scans / imaging",
  hospitalizations: "Hospitalizations",
  notes: "Clinical notes",
  other: "Other",
};

function SectionCard({
  sectionKey, docs, patientId, router,
}: {
  sectionKey: string;
  docs: DocumentCard[];
  patientId: string;
  router: ReturnType<typeof useRouter>;
}) {
  if (!docs.length) return null;
  const abnormalCount = docs.filter(hasAbnormal).length;
  const unverifiedCount = docs.filter((d) => !d.is_verified).length;
  const needsReview = docs.filter((d) => hasAbnormal(d) && !d.reviewed_by_current_doctor).length;
  const latest = [...docs].sort((a, b) => compareDatesDescending(getDocumentClinicalDate(a), getDocumentClinicalDate(b)))[0];

  return (
    <div className="soft-card-tight" style={{ padding: 16, borderColor: needsReview > 0 ? "var(--danger-border)" : "var(--border)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
        <div style={{ fontWeight: 800, fontSize: 15 }}>{SECTION_LABELS[sectionKey] || sectionKey}</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {needsReview > 0 && (
            <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)" }}>
              {needsReview} need review
            </span>
          )}
          {abnormalCount > 0 && needsReview === 0 && (
            <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
              {abnormalCount} out-of-range
            </span>
          )}
          {unverifiedCount > 0 && (
            <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
              {unverifiedCount} unverified
            </span>
          )}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginBottom: 12 }}>
        <div>
          <div className="muted-text" style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}>Total</div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>{docs.length}</div>
        </div>
        <div>
          <div className="muted-text" style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}>Out-of-range</div>
          <div style={{ fontWeight: 800, fontSize: 18, color: abnormalCount > 0 ? "var(--danger-text)" : undefined }}>{abnormalCount}</div>
        </div>
        <div>
          <div className="muted-text" style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase" }}>Unverified</div>
          <div style={{ fontWeight: 800, fontSize: 18, color: unverifiedCount > 0 ? "var(--warn-text)" : undefined }}>{unverifiedCount}</div>
        </div>
      </div>
      {latest && (
        <div className="muted-text" style={{ fontSize: 12, marginBottom: 12 }}>
          Latest: {getDocumentTitle(latest)} · {formatDate(getDocumentClinicalDate(latest))}
        </div>
      )}
      <button
        type="button"
        className="secondary-btn"
        style={{ fontSize: 12, padding: "6px 14px" }}
        onClick={() => router.push(`/patients/${patientId}?section=${sectionKey}`)}
      >
        View in chart →
      </button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PatientAnalyticsPage() {
  const params = useParams();
  const router = useRouter();
  const { t, language } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [medications, setMedications] = useState<PatientMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [trendSearch, setTrendSearch] = useState("");
  const [abnormalOnly, setAbnormalOnly] = useState(false);

  const fetchAll = useCallback(async () => {
    const me = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(me.data);
    if (me.data.role === "patient") { router.replace("/my-records"); return; }

    const [profileRes, trendsRes, medsRes] = await Promise.allSettled([
      api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
      api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`),
      api.get<PatientMedication[]>(`/patients/${patientId}/medications`),
    ]);

    if (profileRes.status === "fulfilled") setProfile(profileRes.value.data);
    if (trendsRes.status === "fulfilled") {
      const raw = Array.isArray(trendsRes.value.data) ? trendsRes.value.data : [];
      setTrends(raw.map((t) => enrichBloodworkTrend(t)));
    }
    if (medsRes.status === "fulfilled") {
      setMedications(Array.isArray(medsRes.value.data) ? medsRes.value.data : []);
    }
  }, [patientId, router]);

  useEffect(() => {
    async function init() {
      try {
        await fetchAll();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load patient analytics."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [fetchAll]);

  // Compute stats
  const stats = useMemo(() => {
    if (!profile) return null;
    const s = profile.sections;
    const allDocs = [
      ...(s.bloodwork || []),
      ...(s.discharge_summary || []),
      ...(s.scans || []),
      ...(s.hospitalizations || []),
      ...(s.notes || []),
      ...(s.other || []),
    ];
    const totalDocs = allDocs.length;
    const bloodworkCount = (s.bloodwork || []).length;
    const outOfRange = allDocs.filter(hasAbnormal).length;
    const notesCount = (s.notes || []).length;
    const unverified = allDocs.filter((d) => !d.is_verified).length;
    const needsReview = allDocs.filter((d) => hasAbnormal(d) && !d.reviewed_by_current_doctor).length;
    return { totalDocs, bloodworkCount, outOfRange, notesCount, unverified, needsReview };
  }, [profile]);

  const medStats = useMemo(() => {
    const active = medications.filter((m) => m.status === "active").length;
    const asNeeded = medications.filter((m) => m.status === "as_needed").length;
    const uncertain = medications.filter((m) => m.is_uncertain).length;
    const matched = medications.filter((m) => m.official_match_status === "matched").length;
    return { total: medications.length, active, asNeeded, uncertain, matched };
  }, [medications]);

  const processedTrends = useMemo(() => {
    return [...trends]
      .filter((trend) => trend.points?.length)
      .map((trend) => {
        const recentPoints = getRecentTrendPoints(trend.points);
        const latest = recentPoints[recentPoints.length - 1] || trend.latest;
        const previous = recentPoints[recentPoints.length - 2] || trend.previous || null;
        const delta = latest && previous ? Number((latest.value - previous.value).toFixed(2)) : null;
        const abnormal = Boolean(latest?.flag && String(latest.flag).toLowerCase() !== "normal");
        return { ...trend, points: recentPoints, latest, previous, delta, abnormal };
      })
      .sort((a, b) => {
        if (a.abnormal && !b.abnormal) return -1;
        if (!a.abnormal && b.abnormal) return 1;
        return a.display_name.localeCompare(b.display_name);
      });
  }, [trends]);

  const filteredTrends = useMemo(() => {
    let result = processedTrends;
    if (abnormalOnly) result = result.filter((t) => t.abnormal);
    const term = trendSearch.trim().toLowerCase();
    if (term) {
      result = result.filter((t) =>
        t.display_name.toLowerCase().includes(term) ||
        (t.category || "").toLowerCase().includes(term)
      );
    }
    return result;
  }, [processedTrends, abnormalOnly, trendSearch]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22 }}>
          <span className="muted-text">Loading patient analytics…</span>
        </div>
      </main>
    );
  }

  const patient = profile.patient;
  const sections = profile.sections;

  return (
    <AppShell
      user={currentUser}
      title={t("analyticsTitle")}
      subtitle={t("analyticsSubtitle")}
      rightContent={
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/medications/list`)}>
            {t("viewMedications")}
          </button>
          <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
            {t("backToPatientChart")}
          </button>
          <button className="secondary-btn" onClick={() => router.push("/my-patients")}>
            {t("backToMyPatients")}
          </button>
        </div>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 20, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Patient context */}
      <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
          <div
            style={{
              width: 48, height: 48, borderRadius: 14, background: "var(--primary-soft)",
              color: "var(--primary)", display: "grid", placeItems: "center",
              fontWeight: 900, fontSize: 18, flexShrink: 0,
            }}
          >
            {patient.full_name.charAt(0).toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 20, letterSpacing: "-0.03em" }}>{patient.full_name}</div>
            <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>
              ID {valueOrDash(patient.patient_identifier)}
              {patient.date_of_birth ? ` · ${formatPatientAge(patient.date_of_birth, language)}` : ""}
              {patient.sex ? ` · ${patient.sex}` : ""}
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button className="secondary-btn" style={{ fontSize: 13 }} onClick={() => router.push(`/patients/${patientId}/timeline`)}>
              Timeline
            </button>
            <button className="primary-btn" style={{ fontSize: 13 }} onClick={() => router.push(`/patients/${patientId}`)}>
              Open chart
            </button>
          </div>
        </div>
      </div>

      {/* Overview stats */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14, marginBottom: 28 }}>
          <StatCard
            label="Total documents"
            value={stats.totalDocs}
            onClick={() => router.push(`/patients/${patientId}`)}
          />
          <StatCard
            label="Bloodwork panels"
            value={stats.bloodworkCount}
            onClick={() => router.push(`/patients/${patientId}`)}
          />
          <StatCard
            label={t("outOfRangeLabs")}
            value={stats.outOfRange}
            accent={stats.outOfRange > 0 ? "var(--danger-text)" : undefined}
            subtitle={stats.outOfRange > 0 ? "Out-of-range value present" : "All clear"}
          />
          <StatCard
            label="Needs review"
            value={stats.needsReview}
            accent={stats.needsReview > 0 ? "var(--danger-text)" : undefined}
            onClick={stats.needsReview > 0 ? () => router.push(`/patients/${patientId}`) : undefined}
          />
          <StatCard
            label="Clinical notes"
            value={stats.notesCount}
            onClick={() => router.push(`/patients/${patientId}`)}
          />
          <StatCard
            label="Unverified"
            value={stats.unverified}
            accent={stats.unverified > 0 ? "var(--warn-text)" : undefined}
            subtitle={stats.unverified > 0 ? "Source requires verification" : undefined}
          />
          <StatCard
            label="Medications"
            value={medStats.total}
            onClick={() => router.push(`/patients/${patientId}/medications/list`)}
            subtitle={`${medStats.active} active · ${medStats.asNeeded} as needed`}
          />
          <StatCard
            label={t("uncertainMeds")}
            value={medStats.uncertain}
            accent={medStats.uncertain > 0 ? "var(--warn-text)" : undefined}
            onClick={medStats.uncertain > 0 ? () => router.push(`/patients/${patientId}/medications/list`) : undefined}
            subtitle={medStats.uncertain > 0 ? "Dose not verified" : undefined}
          />
        </div>
      )}

      {/* Review alert */}
      {stats && stats.needsReview > 0 && (
        <div className="soft-card" style={{ padding: 16, marginBottom: 24, borderColor: "var(--danger-border)", background: "color-mix(in srgb, var(--danger-bg) 40%, var(--panel))" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ width: 10, height: 10, borderRadius: 999, background: "var(--danger-text)", flexShrink: 0 }} />
            <span style={{ fontWeight: 700, color: "var(--danger-text)" }}>
              {stats.needsReview} record{stats.needsReview === 1 ? "" : "s"} with out-of-range values need{stats.needsReview === 1 ? "s" : ""} review
            </span>
          </div>
          <div className="muted-text" style={{ marginTop: 6, fontSize: 13, marginLeft: 20 }}>
            Out-of-range value present · Recorded in source documents · Review suggested
          </div>
          <div style={{ marginLeft: 20, marginTop: 10 }}>
            <button className="secondary-btn" style={{ fontSize: 13 }} onClick={() => router.push(`/patients/${patientId}`)}>
              Open patient chart →
            </button>
          </div>
        </div>
      )}

      {/* Lab Trends */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 18 }}>
          <div>
            <div className="section-title">{t("allLabTrends")}</div>
            <div className="muted-text" style={{ marginTop: 6, fontSize: 13 }}>
              Extracted from uploaded bloodwork documents. Each data point links to its source report.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className={abnormalOnly ? "primary-btn" : "secondary-btn"}
              style={{ fontSize: 13, borderRadius: 999 }}
              onClick={() => setAbnormalOnly((v) => !v)}
            >
              {t("outOfRangeLabs")} only
            </button>
            <button
              type="button"
              className="secondary-btn"
              style={{ fontSize: 13 }}
              onClick={() => router.push(`/patients/${patientId}`)}
            >
              Full trend charts →
            </button>
          </div>
        </div>

        <div style={{ marginBottom: 14 }}>
          <input
            className="text-input"
            value={trendSearch}
            onChange={(e) => setTrendSearch(e.target.value)}
            placeholder="Search lab name or category…"
          />
        </div>

        {filteredTrends.length === 0 ? (
          <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", textAlign: "center" }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>
              {trends.length === 0 ? "No bloodwork trends yet." : "No trends match this filter."}
            </div>
            <div className="muted-text" style={{ fontSize: 13 }}>
              {trends.length === 0
                ? "Upload structured bloodwork reports to generate lab trend data."
                : "Try removing the filter or searching a different name."}
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {filteredTrends.map((trend) => {
              const trendDir =
                trend.delta == null ? null :
                trend.delta > 0 ? "increased" :
                trend.delta < 0 ? "decreased" :
                "stable";
              const latestPoint = trend.points[trend.points.length - 1];
              const prevPoint = trend.points[trend.points.length - 2] || null;

              return (
                <div
                  key={trend.test_key}
                  className="soft-card-tight"
                  style={{
                    padding: 16,
                    borderColor: trend.abnormal ? "var(--danger-border)" : "var(--border)",
                    background: trend.abnormal ? "color-mix(in srgb, var(--danger-bg) 20%, var(--panel))" : "var(--panel)",
                  }}
                >
                  <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 16, alignItems: "center" }}>
                    <div>
                      <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
                        <span style={{ fontWeight: 800, fontSize: 15 }}>{trend.display_name}</span>
                        {trend.abnormal && (
                          <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)" }}>
                            Out-of-range value present
                          </span>
                        )}
                        {trendDir && (
                          <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
                            Trend {trendDir}
                          </span>
                        )}
                      </div>
                      <div className="muted-text" style={{ fontSize: 12, marginBottom: 10 }}>
                        {trend.category || "Lab result"} · {trend.unit || "—"}
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                        {[
                          { label: "Latest", value: latestPoint?.value_display || "—", sub: latestPoint?.date ? formatDate(latestPoint.date) : undefined },
                          { label: "Previous", value: prevPoint?.value_display || "—", sub: prevPoint?.date ? formatDate(prevPoint.date) : undefined },
                          {
                            label: "Delta",
                            value: trend.delta == null ? "—" : `${trend.delta > 0 ? "+" : ""}${trend.delta}`,
                            accent: trend.delta == null ? undefined : trend.delta > 0 ? (trend.abnormal ? "var(--danger-text)" : "var(--success-text)") : "var(--primary)",
                          },
                        ].map(({ label, value, sub, accent }) => (
                          <div key={label} className="soft-card-tight" style={{ padding: "10px 12px" }}>
                            <div className="muted-text" style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
                            <div style={{ fontWeight: 800, fontSize: 16, color: accent || undefined }}>{value}</div>
                            {sub && <div className="muted-text" style={{ fontSize: 11, marginTop: 2 }}>{sub}</div>}
                          </div>
                        ))}
                      </div>
                      {latestPoint?.reference_range && (
                        <div className="muted-text" style={{ marginTop: 8, fontSize: 11 }}>
                          Reference range (from source document): {latestPoint.reference_range}
                        </div>
                      )}
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
                      <MiniTrendChart points={trend.points} unit={trend.unit} abnormal={trend.abnormal} />
                      <button
                        type="button"
                        className="secondary-btn"
                        style={{ fontSize: 12, padding: "5px 12px", borderRadius: 999 }}
                        onClick={() => router.push(`/patients/${patientId}`)}
                      >
                        Full chart →
                      </button>
                      {latestPoint?.document_id && (
                        <button
                          type="button"
                          className="secondary-btn"
                          style={{ fontSize: 12, padding: "5px 12px", borderRadius: 999 }}
                          onClick={() => router.push(`/documents/${latestPoint.document_id}`)}
                        >
                          Source doc
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Source reports */}
                  {trend.points.length > 0 && (
                    <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                      <div className="muted-text" style={{ fontSize: 11, fontWeight: 800, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                        Source documents ({trend.points.length})
                      </div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {[...trend.points]
                          .sort((a, b) => compareDatesDescending(a.date, b.date))
                          .map((point, i) => (
                            <button
                              key={`${point.document_id}-${i}`}
                              type="button"
                              className="secondary-btn"
                              style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999 }}
                              onClick={() => router.push(`/documents/${point.document_id}`)}
                            >
                              {point.value_display} {trend.unit} · {formatDate(point.date)}
                            </button>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Document Breakdown */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ marginBottom: 18 }}>
          <div className="section-title">{t("documentBreakdown")}</div>
          <div className="muted-text" style={{ marginTop: 6, fontSize: 13 }}>
            Documents organized by section. Out-of-range labels are extracted from source documents.
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
          {(["bloodwork", "discharge_summary", "scans", "hospitalizations", "notes", "other"] as const).map((key) => {
            const docs = sections[key] || [];
            return (
              <SectionCard
                key={key}
                sectionKey={key}
                docs={docs}
                patientId={patientId}
                router={router}
              />
            );
          })}
        </div>
        {Object.values(sections).every((arr) => !arr || arr.length === 0) && (
          <div className="muted-text" style={{ padding: "20px 0", textAlign: "center" }}>
            No documents uploaded yet. Upload documents from the patient chart.
          </div>
        )}
      </div>

      {/* Medication Summary */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
          <div>
            <div className="section-title">{t("medSummaryTitle")}</div>
            <div className="muted-text" style={{ marginTop: 6, fontSize: 13 }}>
              Patient-entered records — view only. Dose and frequency not clinician-verified.
            </div>
          </div>
          <button className="secondary-btn" style={{ fontSize: 13 }} onClick={() => router.push(`/patients/${patientId}/medications/list`)}>
            View all medications →
          </button>
        </div>

        {medications.length === 0 ? (
          <div className="muted-text" style={{ fontSize: 13 }}>No medications recorded by this patient.</div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginBottom: 16 }}>
              {[
                { label: "Total", value: medStats.total },
                { label: "Active", value: medStats.active, accent: medStats.active > 0 ? "var(--success-text)" : undefined },
                { label: "As needed", value: medStats.asNeeded },
                { label: t("uncertainMeds"), value: medStats.uncertain, accent: medStats.uncertain > 0 ? "var(--warn-text)" : undefined },
                { label: t("officialInfoMatched"), value: medStats.matched, accent: medStats.matched > 0 ? "var(--primary)" : undefined },
              ].map(({ label, value, accent }) => (
                <div key={label} className="soft-card-tight" style={{ padding: "10px 12px" }}>
                  <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>{label}</div>
                  <div style={{ fontWeight: 800, fontSize: 22, letterSpacing: "-0.03em", color: accent || "var(--foreground)" }}>{value}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gap: 8 }}>
              {medications
                .filter((m) => m.status === "active" || m.status === "as_needed")
                .slice(0, 5)
                .map((m) => {
                  const active = m.status === "active";
                  const asNeeded = m.status === "as_needed";
                  const statusBg = active ? "var(--success-bg)" : asNeeded ? "color-mix(in srgb, var(--primary) 12%, var(--panel-2))" : "var(--panel-2)";
                  const statusColor = active ? "var(--success-text)" : asNeeded ? "var(--primary)" : "var(--muted)";
                  const statusLabel = active ? "Active" : asNeeded ? "As needed" : m.status;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => router.push(`/patients/${patientId}/medications/${m.id}`)}
                      className="soft-card-tight"
                      style={{ padding: "11px 14px", textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, cursor: "pointer", width: "100%" }}
                    >
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 3 }}>
                          <span style={{ fontWeight: 800, fontSize: 14 }}>{m.name}</span>
                          {m.is_uncertain && (
                            <span style={{ padding: "1px 6px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                              Dose not verified
                            </span>
                          )}
                        </div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {[m.dose_strength, m.frequency].filter(Boolean).join(" · ") || "No dose recorded"}
                          {m.reason ? ` · ${m.reason}` : ""}
                        </div>
                      </div>
                      <span style={{ flexShrink: 0, padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: statusBg, color: statusColor }}>
                        {statusLabel}
                      </span>
                    </button>
                  );
                })}
              {medications.filter((m) => m.status === "active" || m.status === "as_needed").length > 5 && (
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
          </>
        )}

        <div className="soft-card-tight" style={{ padding: 10, marginTop: 14, background: "var(--panel-2)", fontSize: 11 }}>
          <span className="muted-text">
            Patient-entered records are not clinically verified. Dose not verified · Frequency not verified · Review with the patient directly.
          </span>
        </div>
      </div>

      {/* Analytics disclaimer */}
      <div className="soft-card-tight" style={{ padding: 14, marginBottom: 24, background: "var(--panel-2)" }}>
        <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.7 }}>
          {t("analyticsDisclaimer")}
        </div>
        <div className="muted-text" style={{ fontSize: 11, marginTop: 6, fontWeight: 700 }}>
          {t("analyticsLinkNote")}
        </div>
      </div>
    </AppShell>
  );
}
