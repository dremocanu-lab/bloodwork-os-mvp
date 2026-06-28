"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";
import type { BloodworkTrend, TrendPoint } from "@/lib/analytes/types";
import { enrichBloodworkTrend } from "@/lib/analytes/match";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORY_ORDER = [
  "Hematologie",
  "Citomorfologie Manuala",
  "Coagulare",
  "Biochimie generala",
  "Endocrinologie",
  "Imunologie",
  "Markeri tumorali",
  "Biologie moleculara generala",
  "Microbiologie",
];

const SECTION_COLORS: Record<string, string> = {
  bloodwork: "#7c3aed",
  discharge_summary: "#0284c7",
  scans: "#0891b2",
  notes: "#16a34a",
  hospitalizations: "#dc2626",
  other: "#6b7280",
};

const SECTION_LABELS: Record<string, string> = {
  bloodwork: "Bloodwork",
  discharge_summary: "Discharge Summaries",
  scans: "Scans",
  notes: "Clinical Notes",
  hospitalizations: "Hospitalizations",
  other: "Other",
};

// Cell status: 0=missing, 1=normal, 2=abnormal, 4=no-ref-range
const HEAT_COLORS: Record<number, string> = {
  0: "#1e293b",
  1: "#16a34a",
  2: "#dc2626",
  4: "#d97706",
};

const ABNORMAL_FLAGS = new Set(["high", "low", "abnormal", "critical", "borderline", "elevated", "h", "l"]);

function isAbnormal(point: TrendPoint): boolean {
  return !!point.flag && ABNORMAL_FLAGS.has(point.flag.toLowerCase());
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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

function formatShortDate(value?: string | null) {
  if (!value) return "—";
  const t = parseDateTime(value);
  if (!t) return value;
  return new Date(t).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function getDocumentDate(doc: DocumentCard): string {
  return doc.collected_on || doc.test_date || doc.reported_on || doc.registered_on || doc.generated_on || doc.created_at || "";
}

function trendStatus(point: TrendPoint): number {
  if (isAbnormal(point)) return 2;
  if (point.reference_range) return 1;
  return 4;
}

function getTrendDirection(trend: BloodworkTrend): "increased" | "decreased" | "stable" | "insufficient" {
  if (trend.points.length < 2) return "insufficient";
  const sorted = [...trend.points].sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date));
  const last = sorted[sorted.length - 1];
  const prev = sorted[sorted.length - 2];
  const lv = parseFloat(last.value_display || "");
  const pv = parseFloat(prev.value_display || "");
  if (Number.isNaN(lv) || Number.isNaN(pv)) return "stable";
  if (lv > pv * 1.05) return "increased";
  if (lv < pv * 0.95) return "decreased";
  return "stable";
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function PatientAnalyticsPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [trends, setTrends] = useState<BloodworkTrend[]>([]);
  const [medications, setMedications] = useState<PatientMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters
  const [categoryFilter, setCategoryFilter] = useState("");
  const [markerSearch, setMarkerSearch] = useState("");
  const [outOfRangeOnly, setOutOfRangeOnly] = useState(false);

  // Selected marker for deep-dive
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  // Drilldown drawer
  const [drawerPoint, setDrawerPoint] = useState<{ trend: BloodworkTrend; point: TrendPoint } | null>(null);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") { router.replace("/my-records"); return; }

        const [profileRes, trendsRes, medsRes] = await Promise.all([
          api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
          api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`),
          api.get<PatientMedication[]>(`/patients/${patientId}/medications`),
        ]);
        setProfile(profileRes.data);
        const raw = Array.isArray(trendsRes.data) ? trendsRes.data : [];
        setTrends(raw.map((t) => enrichBloodworkTrend(t)));
        setMedications(Array.isArray(medsRes.data) ? medsRes.data : []);
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load analytics."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [patientId, router]);

  // ── Derived data ──────────────────────────────────────────────────────────

  const allDocuments = useMemo(() => {
    if (!profile) return [];
    return Object.values(profile.sections).flat().filter(Boolean) as DocumentCard[];
  }, [profile]);

  const categories = useMemo(() => {
    const seen = new Set<string>();
    for (const t of trends) if (t.category) seen.add(t.category);
    return CATEGORY_ORDER.filter((c) => seen.has(c)).concat([...seen].filter((c) => !CATEGORY_ORDER.includes(c)));
  }, [trends]);

  const filteredTrends = useMemo(() => {
    let result = trends;
    if (categoryFilter) result = result.filter((t) => t.category === categoryFilter);
    if (outOfRangeOnly) result = result.filter((t) => t.points.some((p) => isAbnormal(p)));
    if (markerSearch.trim()) {
      const term = markerSearch.trim().toLowerCase();
      result = result.filter((t) => (t.display_name || t.test_key).toLowerCase().includes(term));
    }
    return result;
  }, [trends, categoryFilter, outOfRangeOnly, markerSearch]);

  const selectedTrend = useMemo(
    () => filteredTrends.find((t) => t.test_key === selectedKey) || filteredTrends[0] || null,
    [filteredTrends, selectedKey]
  );

  // ── Heatmap data ──────────────────────────────────────────────────────────

  const heatmapData = useMemo(() => {
    const markers = filteredTrends.map((t) => t.display_name || t.test_key);
    const dateSet = new Set<string>();
    for (const t of filteredTrends) for (const p of t.points) if (p.date) dateSet.add(p.date);
    const dates = [...dateSet].sort((a, b) => parseDateTime(a) - parseDateTime(b));

    const data: [number, number, number][] = [];
    for (let mi = 0; mi < filteredTrends.length; mi++) {
      const t = filteredTrends[mi];
      const pointMap = new Map(t.points.map((p) => [p.date, p]));
      for (let di = 0; di < dates.length; di++) {
        const p = pointMap.get(dates[di]);
        data.push([di, mi, p ? trendStatus(p) : 0]);
      }
    }
    return { markers, dates, data };
  }, [filteredTrends]);

  // ── Line chart for selected marker ───────────────────────────────────────

  const lineChartOption = useMemo(() => {
    if (!selectedTrend) return null;
    const sorted = [...selectedTrend.points].sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date));
    const xData = sorted.map((p) => p.date || "");
    const yData = sorted.map((p) => parseFloat(p.value_display || "") || null);

    // Reference range from first point that has one
    const refPoint = sorted.find((p) => p.reference_range);
    let markArea: Record<string, unknown> | undefined;
    if (refPoint?.reference_range) {
      const match = refPoint.reference_range.match(/([0-9.,-]+)\s*[-–]\s*([0-9.,-]+)/);
      if (match) {
        const lo = parseFloat(match[1].replace(",", "."));
        const hi = parseFloat(match[2].replace(",", "."));
        if (!Number.isNaN(lo) && !Number.isNaN(hi)) {
          markArea = {
            silent: true,
            data: [[{ yAxis: lo }, { yAxis: hi }]],
            itemStyle: { color: "rgba(22,163,74,0.08)", borderColor: "rgba(22,163,74,0.3)", borderWidth: 1 },
            label: { show: true, position: "insideTopRight", formatter: `Ref: ${refPoint.reference_range}`, fontSize: 10, color: "rgba(22,163,74,0.7)" },
          };
        }
      }
    }

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: (params: { dataIndex: number }[]) => {
          const idx = params[0]?.dataIndex;
          const p = sorted[idx];
          if (!p) return "";
          const abnStr = isAbnormal(p) ? ' <span style="color:#f87171">⚑ Out-of-range</span>' : "";
          return `<div style="font-size:12px"><b>${p.date}</b>${abnStr}<br/>${selectedTrend.display_name}: <b>${p.value_display || "—"} ${selectedTrend.unit || ""}</b></div>`;
        },
      },
      grid: { left: 48, right: 20, top: 24, bottom: 40 },
      xAxis: { type: "category", data: xData, axisLabel: { fontSize: 10, color: "#94a3b8" }, axisLine: { lineStyle: { color: "#334155" } } },
      yAxis: { type: "value", axisLabel: { fontSize: 10, color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } }, axisLine: { lineStyle: { color: "#334155" } } },
      series: [{
        type: "line",
        data: yData,
        smooth: true,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { color: "#7c3aed", width: 2 },
        itemStyle: {
          color: (params: { dataIndex: number }) => {
            const p = sorted[params.dataIndex];
            return p && isAbnormal(p) ? "#dc2626" : "#7c3aed";
          },
        },
        markArea: markArea ? markArea : undefined,
      }],
    };
  }, [selectedTrend]);

  // ── Category bar chart ────────────────────────────────────────────────────

  const categoryBarOption = useMemo(() => {
    const catMap = new Map<string, { normal: number; abnormal: number; noRef: number }>();
    for (const t of filteredTrends) {
      const cat = t.category || "Other";
      if (!catMap.has(cat)) catMap.set(cat, { normal: 0, abnormal: 0, noRef: 0 });
      const entry = catMap.get(cat)!;
      for (const p of t.points) {
        if (isAbnormal(p)) entry.abnormal++;
        else if (p.reference_range) entry.normal++;
        else entry.noRef++;
      }
    }
    const cats = [...catMap.keys()];
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["Normal", "Out-of-range", "No ref. range"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 140, right: 20, top: 30, bottom: 20 },
      xAxis: { type: "value", axisLabel: { color: "#94a3b8", fontSize: 10 }, splitLine: { lineStyle: { color: "#1e293b" } } },
      yAxis: { type: "category", data: cats, axisLabel: { color: "#94a3b8", fontSize: 10 } },
      series: [
        { name: "Normal", type: "bar", stack: "total", data: cats.map((c) => catMap.get(c)!.normal), itemStyle: { color: "#16a34a" } },
        { name: "Out-of-range", type: "bar", stack: "total", data: cats.map((c) => catMap.get(c)!.abnormal), itemStyle: { color: "#dc2626" } },
        { name: "No ref. range", type: "bar", stack: "total", data: cats.map((c) => catMap.get(c)!.noRef), itemStyle: { color: "#d97706" } },
      ],
    };
  }, [filteredTrends]);

  // ── Document timeline chart ───────────────────────────────────────────────

  const docTimelineOption = useMemo(() => {
    const monthMap = new Map<string, Record<string, number>>();
    for (const doc of allDocuments) {
      const d = getDocumentDate(doc);
      const t = parseDateTime(d);
      if (!t) continue;
      const mo = new Date(t).toLocaleDateString("en-US", { month: "short", year: "numeric" });
      if (!monthMap.has(mo)) monthMap.set(mo, {});
      const m = monthMap.get(mo)!;
      m[doc.section] = (m[doc.section] || 0) + 1;
    }
    const months = [...monthMap.keys()].sort((a, b) => new Date(a).getTime() - new Date(b).getTime());
    const sections = Object.keys(SECTION_COLORS);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: sections.map((s) => SECTION_LABELS[s] || s), textStyle: { color: "#94a3b8", fontSize: 10 }, top: 0 },
      grid: { left: 40, right: 20, top: 36, bottom: 50 },
      xAxis: { type: "category", data: months, axisLabel: { color: "#94a3b8", fontSize: 9, rotate: 35 }, axisLine: { lineStyle: { color: "#334155" } } },
      yAxis: { type: "value", axisLabel: { color: "#94a3b8", fontSize: 10 }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: sections.map((sec) => ({
        name: SECTION_LABELS[sec] || sec,
        type: "bar",
        stack: "docs",
        data: months.map((mo) => monthMap.get(mo)?.[sec] || 0),
        itemStyle: { color: SECTION_COLORS[sec] },
      })),
    };
  }, [allDocuments]);

  // ── Heatmap ECharts option ────────────────────────────────────────────────

  const heatmapOption = useMemo(() => {
    const { markers, dates, data } = heatmapData;
    if (!markers.length || !dates.length) return null;

    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params: { data: [number, number, number] }) => {
          const [di, mi, status] = params.data;
          const label = status === 0 ? "No data" : status === 1 ? "Normal" : status === 2 ? "Out-of-range value present" : "No reference range";
          return `<div style="font-size:11px"><b>${markers[mi]}</b><br/>${dates[di]}<br/>${label}</div>`;
        },
      },
      grid: { left: 180, right: 80, top: 10, bottom: 50 },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: { color: "#94a3b8", fontSize: 9, rotate: 40, interval: Math.max(0, Math.floor(dates.length / 10)) },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: markers,
        axisLabel: { color: "#cbd5e1", fontSize: 10 },
        splitArea: { show: false },
      },
      visualMap: {
        type: "piecewise",
        show: true,
        right: 0,
        top: "middle",
        pieces: [
          { min: -0.5, max: 0.5, label: "No data", color: HEAT_COLORS[0] },
          { min: 0.5, max: 1.5, label: "Normal", color: HEAT_COLORS[1] },
          { min: 1.5, max: 2.5, label: "Out-of-range", color: HEAT_COLORS[2] },
          { min: 3.5, max: 4.5, label: "No ref. range", color: HEAT_COLORS[4] },
        ],
        textStyle: { color: "#94a3b8", fontSize: 10 },
      },
      series: [{
        type: "heatmap",
        data,
        label: { show: false },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,0.4)" } },
      }],
    };
  }, [heatmapData]);

  // ── Stats ────────────────────────────────────────────────────────────────

  const overviewStats = useMemo(() => {
    const abnormalTrends = filteredTrends.filter((t) => t.points.some((p) => isAbnormal(p))).length;
    const activeMeds = medications.filter((m) => m.status === "active").length;
    const uncertainMeds = medications.filter((m) => m.is_uncertain).length;
    return {
      totalDocs: allDocuments.length,
      labMarkers: filteredTrends.length,
      abnormalTrends,
      activeMeds,
      uncertainMeds,
    };
  }, [allDocuments, filteredTrends, medications]);

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading analytics…</p>
      </main>
    );
  }

  const patientName = profile?.patient.full_name || "Patient";
  const patientAge = formatPatientAge(profile?.patient.date_of_birth);

  return (
    <AppShell
      user={currentUser!}
      title={t("analyticsTitle")}
      subtitle={t("analyticsSubtitle")}
      rightContent={
        <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          ← Back to chart
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 14, background: "var(--danger-bg)", borderColor: "var(--danger-border)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Patient context */}
      <div className="soft-card" style={{ padding: "16px 20px", marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }}>{patientName}</div>
          <div className="muted-text" style={{ fontSize: 13, marginTop: 3 }}>
            {[patientAge, profile?.patient.sex, profile?.patient.patient_identifier].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/medications/list`)}>
            Medications
          </button>
          <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/timeline`)}>
            Timeline
          </button>
        </div>
      </div>

      {/* Overview stat strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginBottom: 24 }}>
        {[
          { label: "Documents", value: overviewStats.totalDocs },
          { label: "Lab markers", value: overviewStats.labMarkers },
          { label: "Out-of-range markers", value: overviewStats.abnormalTrends, accent: overviewStats.abnormalTrends > 0 ? "var(--danger-text)" : undefined },
          { label: "Active medications", value: overviewStats.activeMeds },
          { label: t("uncertainMeds"), value: overviewStats.uncertainMeds, accent: overviewStats.uncertainMeds > 0 ? "var(--warn-text)" : undefined },
        ].map(({ label, value, accent }) => (
          <div key={label} className="soft-card" style={{ padding: "14px 16px" }}>
            <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{label}</div>
            <div style={{ fontWeight: 800, fontSize: 22, letterSpacing: "-0.03em", color: accent || "var(--foreground)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Disclaimer */}
      <div className="soft-card-tight" style={{ padding: "10px 14px", marginBottom: 24, background: "var(--panel-2)", borderRadius: 10 }}>
        <span className="muted-text" style={{ fontSize: 11 }}>
          {t("analyticsDisclaimer")} · {t("analyticsLinkNote")}
        </span>
      </div>

      {/* Global filter bar */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 20 }}>
        <input
          className="text-input"
          placeholder="Search markers…"
          value={markerSearch}
          onChange={(e) => setMarkerSearch(e.target.value)}
          style={{ flex: "1 1 180px", maxWidth: 260 }}
        />
        <select
          className="text-input"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{ flex: "1 1 160px", maxWidth: 220, borderRadius: 12, padding: "10px 36px 10px 12px" }}
        >
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button
          type="button"
          className={outOfRangeOnly ? "primary-btn" : "secondary-btn"}
          onClick={() => setOutOfRangeOnly(!outOfRangeOnly)}
          style={{ borderRadius: 999, padding: "9px 16px", fontSize: 13 }}
        >
          {t("outOfRangeLabs")} only
        </button>
        {(categoryFilter || markerSearch || outOfRangeOnly) && (
          <button type="button" className="secondary-btn" onClick={() => { setCategoryFilter(""); setMarkerSearch(""); setOutOfRangeOnly(false); }}>
            Clear filters
          </button>
        )}
      </div>

      {/* ── Lab Matrix Heatmap ────────────────────────────────────────────── */}
      {heatmapOption && heatmapData.markers.length > 0 ? (
        <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
          <div style={{ marginBottom: 14 }}>
            <div className="section-title">Lab Matrix</div>
            <div className="muted-text" style={{ fontSize: 13, marginTop: 4 }}>
              {heatmapData.markers.length} markers × {heatmapData.dates.length} dates · Click a row to deep-dive
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <div style={{ minWidth: Math.max(600, heatmapData.dates.length * 28 + 260) }}>
              <ReactECharts
                option={heatmapOption}
                style={{ height: Math.max(280, heatmapData.markers.length * 28 + 80) }}
                onEvents={{
                  click: (params: { componentType: string; dataIndex: number; data: [number, number, number] }) => {
                    if (params.componentType === "series") {
                      const mi = params.data[1];
                      const trend = filteredTrends[mi];
                      if (trend) setSelectedKey(trend.test_key);
                    }
                  },
                }}
              />
            </div>
          </div>
        </div>
      ) : (
        <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 8 }}>Lab Matrix</div>
          <div className="muted-text">{t("insufficientData")}</div>
        </div>
      )}

      {/* ── Two-column: Deep Dive + Category Overview ─────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: 20, marginBottom: 24, alignItems: "start" }}>

        {/* Selected Marker Deep Dive */}
        <div className="soft-card" style={{ padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <div>
              <div className="section-title">Selected Marker Deep Dive</div>
              {selectedTrend && (
                <div className="muted-text" style={{ fontSize: 13, marginTop: 4 }}>
                  {selectedTrend.display_name} · {selectedTrend.category || "Lab result"} · {selectedTrend.unit || "—"}
                </div>
              )}
            </div>
            {filteredTrends.length > 1 && (
              <select
                className="text-input"
                value={selectedTrend?.test_key || ""}
                onChange={(e) => setSelectedKey(e.target.value)}
                style={{ borderRadius: 12, padding: "8px 32px 8px 12px", fontSize: 13, minWidth: 160 }}
              >
                {filteredTrends.map((t) => (
                  <option key={t.test_key} value={t.test_key}>{t.display_name || t.test_key}</option>
                ))}
              </select>
            )}
          </div>
          {selectedTrend && lineChartOption ? (
            <>
              <ReactECharts option={lineChartOption} style={{ height: 240 }} onEvents={{
                click: (params: { dataIndex: number }) => {
                  const sorted = [...selectedTrend.points].sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date));
                  const p = sorted[params.dataIndex];
                  if (p) setDrawerPoint({ trend: selectedTrend, point: p });
                },
              }} />
              {/* Trend direction */}
              {(() => {
                const dir = getTrendDirection(selectedTrend);
                const cfg = {
                  increased: { label: t("trendIncreased"), color: "var(--warn-text)", bg: "var(--warn-bg)" },
                  decreased: { label: t("trendDecreased"), color: "var(--primary)", bg: "color-mix(in srgb, var(--primary) 10%, var(--panel-2))" },
                  stable: { label: t("trendStable"), color: "var(--success-text)", bg: "var(--success-bg)" },
                  insufficient: { label: t("insufficientData"), color: "var(--muted)", bg: "var(--panel-2)" },
                };
                const c = cfg[dir];
                return (
                  <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: c.bg, color: c.color }}>{c.label}</span>
                    {selectedTrend.points.some((p) => isAbnormal(p)) && (
                      <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: "var(--danger-bg)", color: "var(--danger-text)" }}>
                        {t("outOfRangePresent")}
                      </span>
                    )}
                    <span className="muted-text" style={{ fontSize: 11 }}>{selectedTrend.points.length} data point{selectedTrend.points.length !== 1 ? "s" : ""}</span>
                  </div>
                );
              })()}
            </>
          ) : (
            <div className="muted-text">{t("insufficientData")}</div>
          )}
        </div>

        {/* Category Overview */}
        <div className="soft-card" style={{ padding: 20 }}>
          <div className="section-title" style={{ marginBottom: 14 }}>Category Overview</div>
          {filteredTrends.length > 0 ? (
            <ReactECharts
              option={categoryBarOption}
              style={{ height: Math.max(240, categories.length * 32 + 60) }}
            />
          ) : (
            <div className="muted-text">{t("insufficientData")}</div>
          )}
        </div>
      </div>

      {/* ── Document Timeline ─────────────────────────────────────────────── */}
      <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <div className="section-title">{t("documentBreakdown")}</div>
          <div className="muted-text" style={{ fontSize: 13, marginTop: 4 }}>Documents by month and section</div>
        </div>
        {allDocuments.length > 0 ? (
          <ReactECharts option={docTimelineOption} style={{ height: 220 }} />
        ) : (
          <div className="muted-text">{t("insufficientData")}</div>
        )}
      </div>

      {/* ── Source Data Table ─────────────────────────────────────────────── */}
      <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div className="section-title">Source Data Table</div>
          <span className="muted-text" style={{ fontSize: 12 }}>{filteredTrends.length} markers shown</span>
        </div>
        {filteredTrends.length === 0 ? (
          <div className="muted-text">{t("insufficientData")}</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Marker", "Category", "Points", "Latest", "Unit", "Status"].map((h) => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 700, color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredTrends.map((trend) => {
                  const hasAbnormal = trend.points.some((p) => isAbnormal(p));
                  const dir = getTrendDirection(trend);
                  const isSelected = trend.test_key === selectedTrend?.test_key;
                  return (
                    <tr
                      key={trend.test_key}
                      onClick={() => setSelectedKey(trend.test_key)}
                      style={{
                        borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        background: isSelected ? "color-mix(in srgb, var(--primary) 8%, transparent)" : "transparent",
                        transition: "background 140ms",
                      }}
                    >
                      <td style={{ padding: "10px 12px", fontWeight: 700 }}>{trend.display_name || trend.test_key}</td>
                      <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{trend.category || "—"}</td>
                      <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{trend.points.length}</td>
                      <td style={{ padding: "10px 12px", fontWeight: 600 }}>{trend.latest?.value_display || "—"}</td>
                      <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{trend.unit || "—"}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                          {hasAbnormal && (
                            <span style={{ padding: "2px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--danger-bg)", color: "var(--danger-text)" }}>
                              {t("outOfRangePresent")}
                            </span>
                          )}
                          {dir !== "insufficient" && (
                            <span style={{ padding: "2px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
                              {dir === "increased" ? "↑" : dir === "decreased" ? "↓" : "→"}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Medication Context ────────────────────────────────────────────── */}
      {medications.length > 0 && (
        <div className="soft-card" style={{ padding: 20, marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div>
              <div className="section-title">{t("medSummaryTitle")}</div>
              <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>{t("patientEnteredLabel")} · View only</div>
            </div>
            <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}/medications/list`)}>
              {t("viewMedications")}
            </button>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {medications.slice(0, 6).map((med) => (
              <div key={med.id} className="soft-card-tight" style={{ padding: "12px 14px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{med.name}</div>
                  <div className="muted-text" style={{ fontSize: 12, marginTop: 2 }}>
                    {[med.dose_strength, med.frequency].filter(Boolean).join(" · ") || "No dose/frequency recorded"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  {med.is_uncertain && (
                    <span style={{ padding: "2px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                      {t("sourceRequiresVerification")}
                    </span>
                  )}
                  <span style={{ padding: "2px 7px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
                    {med.status}
                  </span>
                </div>
              </div>
            ))}
            {medications.length > 6 && (
              <button type="button" className="secondary-btn" style={{ marginTop: 4 }} onClick={() => router.push(`/patients/${patientId}/medications/list`)}>
                View all {medications.length} medications
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Drilldown Drawer ──────────────────────────────────────────────── */}
      {drawerPoint && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(0,0,0,0.55)",
            display: "flex", justifyContent: "flex-end",
          }}
          onClick={() => setDrawerPoint(null)}
        >
          <div
            style={{
              width: "min(420px, 100vw)",
              background: "var(--panel)",
              borderLeft: "1px solid var(--border)",
              padding: 28,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }}>{drawerPoint.trend.display_name}</div>
                <div className="muted-text" style={{ fontSize: 13, marginTop: 4 }}>{drawerPoint.point.date}</div>
              </div>
              <button type="button" className="secondary-btn" onClick={() => setDrawerPoint(null)}>Close</button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {[
                { label: "Value", value: `${drawerPoint.point.value_display || "—"} ${drawerPoint.trend.unit || ""}` },
                { label: "Reference range", value: drawerPoint.point.reference_range || "Not recorded" },
                { label: "Category", value: drawerPoint.trend.category || "—" },
                { label: "Status", value: isAbnormal(drawerPoint.point) ? "Out-of-range value present" : "Within reference range" },
              ].map(({ label, value }) => (
                <div key={label} className="soft-card-tight" style={{ padding: "12px 14px" }}>
                  <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}>{label}</div>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{value}</div>
                </div>
              ))}
            </div>

            {isAbnormal(drawerPoint.point) && (
              <div style={{ padding: "12px 14px", background: "var(--danger-bg)", borderRadius: 10, borderLeft: "3px solid var(--danger-text)" }}>
                <div style={{ fontWeight: 700, color: "var(--danger-text)", fontSize: 13, marginBottom: 4 }}>{t("outOfRangePresent")}</div>
                <div className="muted-text" style={{ fontSize: 12 }}>
                  Out-of-range labels reflect reference ranges recorded in source documents only. This is not a diagnosis.
                </div>
              </div>
            )}

            {drawerPoint.trend.points.length > 1 && (
              <div>
                <div className="muted-text" style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>All recorded values</div>
                <div style={{ display: "grid", gap: 6 }}>
                  {[...drawerPoint.trend.points]
                    .sort((a, b) => parseDateTime(b.date) - parseDateTime(a.date))
                    .map((p, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "var(--panel-2)", borderRadius: 8 }}>
                        <span style={{ fontSize: 13, color: "var(--muted)" }}>{p.date}</span>
                        <span style={{ fontWeight: 700, fontSize: 13, color: isAbnormal(p) ? "var(--danger-text)" : "var(--foreground)" }}>
                          {p.value_display || "—"} {drawerPoint.trend.unit || ""}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            <div className="muted-text" style={{ fontSize: 11, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              {t("analyticsLinkNote")}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
