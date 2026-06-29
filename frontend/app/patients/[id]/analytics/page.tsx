"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatPatientAge } from "@/lib/patient-age";
import type { BloodworkTrend } from "@/lib/analytes/types";
import { enrichBloodworkTrend } from "@/lib/analytes/match";
import type {
  AnalyticsDocument,
  AnalyticsLabStatus,
  AnalyticsLabValue,
  AnalyticsMedication,
} from "@/lib/analytics/types";
import {
  buildAnalyticsDocuments,
  buildAnalyticsLabValues,
  buildAnalyticsMedications,
  parseDateTime,
  type DocumentCardInput,
  type MedicationInput,
} from "@/lib/analytics/transform";
import EmptyStateCard from "@/components/analytics/empty-state-card";
import AnalyticsDrilldownDrawer, {
  type DrawerValue,
} from "@/components/analytics/analytics-drilldown-drawer";

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

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    patient_identifier?: string | null;
  };
  sections: Record<string, DocumentCardInput[] | undefined>;
};

type AnalyticsTab =
  | "overview"
  | "matrix"
  | "trends"
  | "categories"
  | "source"
  | "advanced";

type AdvancedView =
  | "panel"
  | "scatter"
  | "radar"
  | "boxplot"
  | "waterfall"
  | "calendar";

// ── Status presentation ───────────────────────────────────────────────────────

const STATUS_CELL: Record<AnalyticsLabStatus, { bg: string; dot: string }> = {
  in_range: { bg: "rgba(22,163,74,0.15)", dot: "#16a34a" },
  out_of_range: { bg: "rgba(220,38,38,0.12)", dot: "#dc2626" },
  no_reference_range: { bg: "rgba(217,119,6,0.12)", dot: "#d97706" },
  qualitative: { bg: "rgba(2,132,199,0.12)", dot: "#0284c7" },
  not_numeric: { bg: "rgba(148,163,184,0.06)", dot: "#94a3b8" },
};

const NOT_PRESENT_BG = "rgba(148,163,184,0.06)";

const SECTION_SERIES_COLORS = [
  "#7c3aed",
  "#0284c7",
  "#0891b2",
  "#16a34a",
  "#dc2626",
  "#6b7280",
];

const AXIS_COLOR = "#94a3b8";
const GRID_LINE = "color-mix(in srgb, var(--border) 60%, transparent)";

// ── Helpers ───────────────────────────────────────────────────────────────────

function uniqueSortedDates(values: AnalyticsLabValue[]): string[] {
  const set = new Set<string>();
  for (const v of values) if (v.date) set.add(v.date);
  return [...set].sort((a, b) => parseDateTime(a) - parseDateTime(b));
}

function latestByMarker(values: AnalyticsLabValue[]): Map<string, AnalyticsLabValue> {
  const map = new Map<string, AnalyticsLabValue>();
  for (const v of values) {
    const prev = map.get(v.marker_key);
    if (!prev || parseDateTime(v.date) >= parseDateTime(prev.date)) {
      map.set(v.marker_key, v);
    }
  }
  return map;
}

function tooltipBox(): Record<string, unknown> {
  return {
    backgroundColor: "var(--panel)",
    borderColor: "var(--border)",
    borderWidth: 1,
    textStyle: { color: "var(--foreground)", fontSize: 12 },
    extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.35);",
  };
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
  const [medications, setMedications] = useState<AnalyticsMedication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Navigation
  const [activeTab, setActiveTab] = useState<AnalyticsTab>("overview");
  const [advancedView, setAdvancedView] = useState<AdvancedView | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState("");
  const [subgroupFilter, setSubgroupFilter] = useState("");
  const [markerSearch, setMarkerSearch] = useState("");
  const [outOfRangeOnly, setOutOfRangeOnly] = useState(false);

  // Selections
  const [selectedMarker, setSelectedMarker] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<DrawerValue | null>(null);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role === "patient") {
          router.replace("/my-records");
          return;
        }

        const [profileRes, trendsRes, medsRes] = await Promise.all([
          api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
          api.get<BloodworkTrend[]>(`/patients/${patientId}/bloodwork-trends`),
          api.get<MedicationInput[]>(`/patients/${patientId}/medications`),
        ]);
        setProfile(profileRes.data);
        const raw = Array.isArray(trendsRes.data) ? trendsRes.data : [];
        setTrends(raw.map((trend) => enrichBloodworkTrend(trend)));
        const meds = Array.isArray(medsRes.data) ? medsRes.data : [];
        setMedications(buildAnalyticsMedications(meds, patientId));
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load analytics."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [patientId, router]);

  // ── Derived raw data ────────────────────────────────────────────────────────

  const rawDocuments = useMemo<DocumentCardInput[]>(() => {
    if (!profile) return [];
    return Object.values(profile.sections)
      .flat()
      .filter(Boolean) as DocumentCardInput[];
  }, [profile]);

  const allLabValues = useMemo(
    () => buildAnalyticsLabValues(trends, rawDocuments),
    [trends, rawDocuments],
  );

  const analyticsDocuments = useMemo(
    () => buildAnalyticsDocuments(rawDocuments, allLabValues),
    [rawDocuments, allLabValues],
  );

  const trendByKey = useMemo(() => {
    const map = new Map<string, BloodworkTrend>();
    for (const trend of trends) map.set(trend.test_key, trend);
    return map;
  }, [trends]);

  // ── Filter options ───────────────────────────────────────────────────────────

  const categories = useMemo(() => {
    const seen = new Map<string, string>();
    for (const v of allLabValues) if (!seen.has(v.category)) seen.set(v.category, v.category_display);
    return [...seen.entries()].map(([key, label]) => ({ key, label }));
  }, [allLabValues]);

  const subgroups = useMemo(() => {
    if (!categoryFilter) return [];
    const set = new Set<string>();
    for (const v of allLabValues) {
      if (v.category === categoryFilter && v.subgroup) set.add(v.subgroup);
    }
    return [...set];
  }, [allLabValues, categoryFilter]);

  // ── Filtered values (global) ─────────────────────────────────────────────────

  const filteredValues = useMemo(() => {
    let result = allLabValues;
    if (categoryFilter) result = result.filter((v) => v.category === categoryFilter);
    if (subgroupFilter) result = result.filter((v) => v.subgroup === subgroupFilter);
    if (markerSearch.trim()) {
      const term = markerSearch.trim().toLowerCase();
      result = result.filter((v) => v.marker_name.toLowerCase().includes(term));
    }
    if (outOfRangeOnly) {
      const outKeys = new Set(
        allLabValues.filter((v) => v.status === "out_of_range").map((v) => v.marker_key),
      );
      result = result.filter((v) => outKeys.has(v.marker_key));
    }
    return result;
  }, [allLabValues, categoryFilter, subgroupFilter, markerSearch, outOfRangeOnly]);

  const filtersActive = !!(categoryFilter || subgroupFilter || markerSearch || outOfRangeOnly);

  // ── Stats ────────────────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const markerKeys = new Set(allLabValues.map((v) => v.marker_key));
    const outOfRangeMarkers = new Set(
      allLabValues.filter((v) => v.status === "out_of_range").map((v) => v.marker_key),
    );
    const activeMeds = medications.filter((m) => m.status === "active").length;
    const uncertainMeds = medications.filter((m) => m.is_uncertain).length;
    return {
      documents: analyticsDocuments.length,
      markers: markerKeys.size,
      outOfRange: outOfRangeMarkers.size,
      activeMeds,
      uncertainMeds,
    };
  }, [allLabValues, analyticsDocuments, medications]);

  // ── Selected marker / trend ──────────────────────────────────────────────────

  const filteredMarkerLatest = useMemo(
    () => latestByMarker(filteredValues),
    [filteredValues],
  );

  const filteredMarkers = useMemo(
    () =>
      [...filteredMarkerLatest.values()].sort((a, b) =>
        a.marker_name.localeCompare(b.marker_name),
      ),
    [filteredMarkerLatest],
  );

  const activeMarkerKey = useMemo(() => {
    if (selectedMarker && filteredMarkerLatest.has(selectedMarker)) return selectedMarker;
    return filteredMarkers[0]?.marker_key ?? null;
  }, [selectedMarker, filteredMarkerLatest, filteredMarkers]);

  const selectedTrend = activeMarkerKey ? trendByKey.get(activeMarkerKey) ?? null : null;
  const selectedValues = useMemo(
    () =>
      activeMarkerKey
        ? allLabValues
            .filter((v) => v.marker_key === activeMarkerKey)
            .sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date))
        : [],
    [allLabValues, activeMarkerKey],
  );

  function openMarkerTrend(markerKey: string) {
    setSelectedMarker(markerKey);
    setActiveTab("trends");
  }

  function openDrawerForValue(v: AnalyticsLabValue) {
    setDrawer({ labValue: v, trend: trendByKey.get(v.marker_key) ?? undefined });
  }

  // ── Render guards ────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading…</p>
      </main>
    );
  }

  const patientName = profile?.patient.full_name || "Patient";
  const patientAge = formatPatientAge(profile?.patient.date_of_birth);

  const tabs: { key: AnalyticsTab; label: string }[] = [
    { key: "overview", label: t("tabOverview") },
    { key: "matrix", label: t("tabMatrix") },
    { key: "trends", label: t("tabTrends") },
    { key: "categories", label: t("tabCategories") },
    { key: "source", label: t("tabSourceRecords") },
    { key: "advanced", label: t("tabAdvanced") },
  ];

  return (
    <AppShell
      user={currentUser!}
      title={t("analyticsWorkspace")}
      subtitle={t("analyticsSubtitleFull")}
      rightContent={
        <button
          type="button"
          className="secondary-btn"
          onClick={() => router.push(`/patients/${patientId}`)}
        >
          ← {t("tabOverview")}
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 16,
            padding: 14,
            background: "var(--danger-bg)",
            borderColor: "var(--danger-border)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      {/* Patient context */}
      <div
        className="soft-card"
        style={{
          padding: "16px 20px",
          marginBottom: 20,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }}>{patientName}</div>
          <div className="muted-text" style={{ fontSize: 13, marginTop: 3 }}>
            {[patientAge, profile?.patient.sex, profile?.patient.patient_identifier]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => router.push(`/patients/${patientId}`)}
          >
            {t("tabOverview")}
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => router.push(`/patients/${patientId}/medications/list`)}
          >
            {t("viewMedications")}
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => router.push(`/patients/${patientId}/timeline`)}
          >
            {t("sourceRecordsTimeline")}
          </button>
        </div>
      </div>

      {/* Stat strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {[
          { label: t("uploadedDocuments"), value: stats.documents },
          { label: t("labMarkers"), value: stats.markers },
          {
            label: t("outOfRangeMarkers"),
            value: stats.outOfRange,
            accent: stats.outOfRange > 0 ? "var(--danger-text)" : undefined,
          },
          { label: t("activeMedications"), value: stats.activeMeds },
          {
            label: t("uncertainMeds"),
            value: stats.uncertainMeds,
            accent: stats.uncertainMeds > 0 ? "var(--warn-text)" : undefined,
          },
        ].map(({ label, value, accent }) => (
          <div key={label} className="soft-card" style={{ padding: "14px 16px" }}>
            <div
              className="muted-text"
              style={{
                fontSize: 10,
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                marginBottom: 6,
              }}
            >
              {label}
            </div>
            <div
              style={{
                fontWeight: 800,
                fontSize: 22,
                letterSpacing: "-0.03em",
                color: accent || "var(--foreground)",
              }}
            >
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Disclaimer */}
      <div
        className="soft-card-tight"
        style={{ padding: "10px 14px", marginBottom: 18, background: "var(--panel-2)", borderRadius: 10 }}
      >
        <span className="muted-text" style={{ fontSize: 11 }}>
          {t("dataInUploadedDocuments")} · {t("sourceLinked")} · {t("referenceOnly")} · {t("notADiagnosis")}
        </span>
      </div>

      {/* Filter bar */}
      {allLabValues.length > 0 && (
        <div style={{ marginBottom: 18, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className={!categoryFilter ? "primary-btn" : "secondary-btn"}
              style={{ borderRadius: 999, padding: "6px 14px", fontSize: 12 }}
              onClick={() => {
                setCategoryFilter("");
                setSubgroupFilter("");
              }}
            >
              {t("allCategories")}
            </button>
            {categories.map((c) => (
              <button
                key={c.key}
                type="button"
                className={categoryFilter === c.key ? "primary-btn" : "secondary-btn"}
                style={{ borderRadius: 999, padding: "6px 14px", fontSize: 12 }}
                onClick={() => {
                  setCategoryFilter(c.key);
                  setSubgroupFilter("");
                }}
              >
                {c.label}
              </button>
            ))}
          </div>

          {categoryFilter && subgroups.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button
                type="button"
                className={!subgroupFilter ? "primary-btn" : "secondary-btn"}
                style={{ borderRadius: 999, padding: "5px 12px", fontSize: 11 }}
                onClick={() => setSubgroupFilter("")}
              >
                {t("allSubgroups")}
              </button>
              {subgroups.map((sg) => (
                <button
                  key={sg}
                  type="button"
                  className={subgroupFilter === sg ? "primary-btn" : "secondary-btn"}
                  style={{ borderRadius: 999, padding: "5px 12px", fontSize: 11 }}
                  onClick={() => setSubgroupFilter(sg)}
                >
                  {sg}
                </button>
              ))}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input
              className="text-input"
              placeholder={t("searchMarkers")}
              value={markerSearch}
              onChange={(e) => setMarkerSearch(e.target.value)}
              style={{ flex: "1 1 180px", maxWidth: 260 }}
            />
            <button
              type="button"
              className={outOfRangeOnly ? "primary-btn" : "secondary-btn"}
              onClick={() => setOutOfRangeOnly((p) => !p)}
              style={{ borderRadius: 999, padding: "8px 16px", fontSize: 12 }}
            >
              {t("outOfRangeOnly")}
            </button>
            {filtersActive && (
              <button
                type="button"
                className="secondary-btn"
                onClick={() => {
                  setCategoryFilter("");
                  setSubgroupFilter("");
                  setMarkerSearch("");
                  setOutOfRangeOnly(false);
                }}
                style={{ fontSize: 12 }}
              >
                {t("clearFilters")}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? "primary-btn" : "secondary-btn"}
            style={{ borderRadius: 12, padding: "8px 16px", fontSize: 13 }}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* No data case */}
      {allLabValues.length === 0 ? (
        <EmptyStateCard title={t("noLabDataAvailable")} description={t("dataInUploadedDocuments")} icon="🧪" />
      ) : (
        <>
          {activeTab === "overview" && (
            <OverviewTab
              filteredValues={filteredValues}
              documents={analyticsDocuments}
              medications={medications}
              onViewMeds={() => router.push(`/patients/${patientId}/medications/list`)}
              t={t}
            />
          )}
          {activeTab === "matrix" && (
            <MatrixTab filteredValues={filteredValues} onCell={openDrawerForValue} t={t} />
          )}
          {activeTab === "trends" && (
            <TrendsTab
              markers={filteredMarkers}
              activeMarkerKey={activeMarkerKey}
              onSelectMarker={setSelectedMarker}
              selectedValues={selectedValues}
              selectedTrend={selectedTrend}
              onPointClick={openDrawerForValue}
              t={t}
            />
          )}
          {activeTab === "categories" && (
            <CategoriesTab
              filteredValues={filteredValues}
              onSelectCategory={(cat) => {
                setCategoryFilter(cat);
                setSubgroupFilter("");
              }}
              onOpenMarker={openMarkerTrend}
              t={t}
            />
          )}
          {activeTab === "source" && (
            <SourceTab
              documents={analyticsDocuments}
              markerLatest={filteredMarkers}
              onRowClick={openDrawerForValue}
              t={t}
            />
          )}
          {activeTab === "advanced" && (
            <AdvancedTab
              filteredValues={filteredValues}
              advancedView={advancedView}
              setAdvancedView={setAdvancedView}
              t={t}
            />
          )}
        </>
      )}

      <AnalyticsDrilldownDrawer value={drawer} onClose={() => setDrawer(null)} patientId={patientId} />
    </AppShell>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Shared chart-card wrapper
// ════════════════════════════════════════════════════════════════════════════

type Translate = (key: Parameters<ReturnType<typeof useLanguage>["t"]>[0]) => string;

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="soft-card" style={{ padding: 20, marginBottom: 20 }}>
      <div style={{ marginBottom: 14 }}>
        <div className="section-title">{title}</div>
        {subtitle && (
          <div className="muted-text" style={{ fontSize: 13, marginTop: 4 }}>
            {subtitle}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function StatusLegend({ t }: { t: Translate }) {
  const items: { label: string; status: AnalyticsLabStatus }[] = [
    { label: t("inRange"), status: "in_range" },
    { label: t("outOfRange"), status: "out_of_range" },
    { label: t("noReferenceRange"), status: "no_reference_range" },
  ];
  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
      {items.map((it) => (
        <span key={it.status} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)" }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: STATUS_CELL[it.status].dot,
              display: "inline-block",
            }}
          />
          {it.label}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)" }}>
        <span style={{ width: 8, height: 8, borderRadius: 999, background: NOT_PRESENT_BG, border: "1px solid var(--border)", display: "inline-block" }} />
        {t("notPresent")}
      </span>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// OVERVIEW TAB
// ════════════════════════════════════════════════════════════════════════════

function OverviewTab({
  filteredValues,
  documents,
  medications,
  onViewMeds,
  t,
}: {
  filteredValues: AnalyticsLabValue[];
  documents: AnalyticsDocument[];
  medications: AnalyticsMedication[];
  onViewMeds: () => void;
  t: Translate;
}) {
  const latest = useMemo(() => [...latestByMarker(filteredValues).values()], [filteredValues]);

  const statusOption = useMemo(() => {
    const counts = { in_range: 0, out_of_range: 0, no_reference_range: 0, not_numeric: 0 };
    for (const v of latest) {
      if (v.status === "qualitative") counts.not_numeric++;
      else counts[v.status]++;
    }
    const rows = [
      { label: t("inRange"), value: counts.in_range, color: "#16a34a" },
      { label: t("outOfRange"), value: counts.out_of_range, color: "#dc2626" },
      { label: t("noReferenceRange"), value: counts.no_reference_range, color: "#d97706" },
      { label: t("notPresent"), value: counts.not_numeric, color: "#6b7280" },
    ];
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipBox() },
      grid: { left: 110, right: 24, top: 10, bottom: 24 },
      xAxis: {
        type: "value",
        axisLabel: { color: AXIS_COLOR, fontSize: 10 },
        splitLine: { lineStyle: { color: GRID_LINE } },
      },
      yAxis: {
        type: "category",
        data: rows.map((r) => r.label),
        axisLabel: { color: AXIS_COLOR, fontSize: 11 },
        axisLine: { lineStyle: { color: GRID_LINE } },
      },
      series: [
        {
          type: "bar",
          data: rows.map((r) => ({ value: r.value, itemStyle: { color: r.color, borderRadius: [0, 6, 6, 0] } })),
          barWidth: 18,
        },
      ],
    };
  }, [latest, t]);

  const timelineOption = useMemo(() => buildTimelineOption(documents), [documents]);

  return (
    <>
      <ChartCard title={t("latestStatusVsSourceRange")} subtitle={t("clinicalLabMatrixDesc")}>
        {latest.length > 0 ? (
          <ReactECharts option={statusOption} style={{ height: 200 }} />
        ) : (
          <EmptyStateCard title={t("notEnoughData")} />
        )}
      </ChartCard>

      <ChartCard title={t("sourceRecordsTimeline")} subtitle={t("sourceRecordsTimelineDesc")}>
        {documents.length > 0 ? (
          <ReactECharts option={timelineOption} style={{ height: 240 }} />
        ) : (
          <EmptyStateCard title={t("notEnoughData")} />
        )}
      </ChartCard>

      <ChartCard title={t("medSummaryTitle")} subtitle={t("patientEnteredContextOnly")}>
        {medications.length === 0 ? (
          <EmptyStateCard title={t("noMedicationsRecorded")} icon="💊" />
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
              {medications.slice(0, 6).map((med) => (
                <div key={med.id} className="soft-card-tight" style={{ padding: "12px 14px" }}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{med.name}</div>
                  <div className="muted-text" style={{ fontSize: 12, marginTop: 2 }}>
                    {[med.dose_strength, med.frequency].filter(Boolean).join(" · ") || "—"}
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                    <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
                      {med.status}
                    </span>
                    {med.is_uncertain && (
                      <span style={{ padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
                        {t("sourceRequiresVerification")}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <button type="button" className="secondary-btn" style={{ marginTop: 12 }} onClick={onViewMeds}>
              {t("viewMedications")}
            </button>
          </>
        )}
      </ChartCard>
    </>
  );
}

function buildTimelineOption(documents: AnalyticsDocument[]): Record<string, unknown> {
  const monthMap = new Map<string, Map<string, number>>();
  const typeSet = new Set<string>();
  for (const doc of documents) {
    if (!doc.date) continue;
    const key = doc.month_label;
    if (!monthMap.has(key)) monthMap.set(key, new Map());
    const inner = monthMap.get(key)!;
    inner.set(doc.document_type_display, (inner.get(doc.document_type_display) || 0) + 1);
    typeSet.add(doc.document_type_display);
  }
  const months = [...monthMap.keys()].sort(
    (a, b) => new Date(a).getTime() - new Date(b).getTime(),
  );
  const types = [...typeSet];
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipBox() },
    legend: { data: types, textStyle: { color: AXIS_COLOR, fontSize: 10 }, top: 0 },
    grid: { left: 40, right: 20, top: 36, bottom: 50 },
    xAxis: {
      type: "category",
      data: months,
      axisLabel: { color: AXIS_COLOR, fontSize: 9, rotate: 35 },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: AXIS_COLOR, fontSize: 10 },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series: types.map((ty, i) => ({
      name: ty,
      type: "bar",
      stack: "docs",
      data: months.map((m) => monthMap.get(m)?.get(ty) || 0),
      itemStyle: { color: SECTION_SERIES_COLORS[i % SECTION_SERIES_COLORS.length] },
    })),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// MATRIX TAB (custom CSS/HTML)
// ════════════════════════════════════════════════════════════════════════════

function MatrixTab({
  filteredValues,
  onCell,
  t,
}: {
  filteredValues: AnalyticsLabValue[];
  onCell: (v: AnalyticsLabValue) => void;
  t: Translate;
}) {
  const { rows, dates } = useMemo(() => {
    const dateList = uniqueSortedDates(filteredValues);
    // marker_key -> { name, category_display, byDate }
    const markerMap = new Map<
      string,
      { name: string; categoryDisplay: string; byDate: Map<string, AnalyticsLabValue> }
    >();
    for (const v of filteredValues) {
      if (!markerMap.has(v.marker_key)) {
        markerMap.set(v.marker_key, {
          name: v.marker_name,
          categoryDisplay: v.category_display,
          byDate: new Map(),
        });
      }
      markerMap.get(v.marker_key)!.byDate.set(v.date, v);
    }
    // group by category
    const byCategory = new Map<string, { key: string; name: string; byDate: Map<string, AnalyticsLabValue> }[]>();
    for (const [key, info] of markerMap.entries()) {
      const list = byCategory.get(info.categoryDisplay) || [];
      list.push({ key, name: info.name, byDate: info.byDate });
      byCategory.set(info.categoryDisplay, list);
    }
    const grouped = [...byCategory.entries()].map(([cat, markers]) => ({
      category: cat,
      markers: markers.sort((a, b) => a.name.localeCompare(b.name)),
    }));
    return { rows: grouped, dates: dateList };
  }, [filteredValues]);

  if (!rows.length || !dates.length) {
    return <EmptyStateCard title={t("notEnoughData")} icon="▦" />;
  }

  const dateColWidth = 52;
  const markerColWidth = 160;

  return (
    <ChartCard title={t("clinicalLabMatrix")} subtitle={t("clinicalLabMatrixDesc")}>
      <div style={{ marginBottom: 14 }}>
        <StatusLegend t={t} />
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: markerColWidth + dates.length * dateColWidth }}>
          {/* Header */}
          <div style={{ display: "flex" }}>
            <div
              style={{
                position: "sticky",
                left: 0,
                zIndex: 2,
                width: markerColWidth,
                minWidth: markerColWidth,
                background: "var(--panel)",
                padding: "6px 10px",
                fontSize: 10,
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "var(--muted)",
              }}
            >
              {t("markerColumn")}
            </div>
            {dates.map((d) => (
              <div
                key={d}
                title={d}
                style={{
                  width: dateColWidth,
                  minWidth: dateColWidth,
                  textAlign: "center",
                  fontSize: 9,
                  color: "var(--muted)",
                  padding: "6px 2px",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {formatTinyDate(d)}
              </div>
            ))}
          </div>

          {/* Category groups */}
          {rows.map((group) => (
            <div key={group.category}>
              <div
                style={{
                  background: "var(--panel-2)",
                  padding: "5px 10px",
                  fontSize: 10,
                  fontWeight: 800,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "var(--muted)",
                  position: "sticky",
                  left: 0,
                }}
              >
                {group.category}
              </div>
              {group.markers.map((marker) => (
                <div key={marker.key} style={{ display: "flex", alignItems: "center" }}>
                  <div
                    title={marker.name}
                    style={{
                      position: "sticky",
                      left: 0,
                      zIndex: 1,
                      width: markerColWidth,
                      minWidth: markerColWidth,
                      maxWidth: markerColWidth,
                      background: "var(--panel)",
                      padding: "4px 10px",
                      fontSize: 12,
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    {marker.name}
                  </div>
                  {dates.map((d) => {
                    const cell = marker.byDate.get(d);
                    const bg = cell ? STATUS_CELL[cell.status].bg : NOT_PRESENT_BG;
                    const dot = cell ? STATUS_CELL[cell.status].dot : null;
                    return (
                      <div
                        key={d}
                        onClick={cell ? () => onCell(cell) : undefined}
                        title={
                          cell
                            ? `${marker.name} · ${cell.date_label} · ${cell.value_display} ${cell.unit || ""}`
                            : undefined
                        }
                        style={{
                          width: dateColWidth,
                          minWidth: dateColWidth,
                          height: 32,
                          padding: 4,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          borderTop: "1px solid var(--border)",
                          cursor: cell ? "pointer" : "default",
                        }}
                      >
                        <div
                          style={{
                            width: "100%",
                            height: "100%",
                            borderRadius: 6,
                            background: bg,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          {dot && (
                            <span style={{ width: 6, height: 6, borderRadius: 999, background: dot, display: "inline-block" }} />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </ChartCard>
  );
}

function formatTinyDate(value: string): string {
  const ms = parseDateTime(value);
  if (!ms) return value;
  return new Date(ms).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

// ════════════════════════════════════════════════════════════════════════════
// TRENDS TAB
// ════════════════════════════════════════════════════════════════════════════

function TrendsTab({
  markers,
  activeMarkerKey,
  onSelectMarker,
  selectedValues,
  selectedTrend,
  onPointClick,
  t,
}: {
  markers: AnalyticsLabValue[];
  activeMarkerKey: string | null;
  onSelectMarker: (key: string) => void;
  selectedValues: AnalyticsLabValue[];
  selectedTrend: BloodworkTrend | null;
  onPointClick: (v: AnalyticsLabValue) => void;
  t: Translate;
}) {
  const refRange = useMemo(() => {
    const withRef = selectedValues.find((v) => v.reference_low !== null && v.reference_high !== null);
    return withRef ? { low: withRef.reference_low!, high: withRef.reference_high!, text: withRef.reference_range } : null;
  }, [selectedValues]);

  const lineOption = useMemo(() => {
    if (selectedValues.length === 0) return null;
    const unit = selectedValues[0]?.unit || "";
    const markArea = refRange
      ? {
          silent: true,
          itemStyle: { color: "rgba(22,163,74,0.08)" },
          data: [[{ yAxis: refRange.low }, { yAxis: refRange.high }]],
        }
      : undefined;
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        ...tooltipBox(),
        formatter: (paramArr: { dataIndex: number }[]) => {
          const idx = paramArr[0]?.dataIndex;
          const v = selectedValues[idx];
          if (!v) return "";
          return `<div style="font-size:12px"><b>${v.date_label}</b><br/>${v.marker_name}: <b>${v.value_display} ${unit}</b><br/>${
            v.reference_range ? `Ref: ${v.reference_range}<br/>` : ""
          }${v.document_title}</div>`;
        },
      },
      grid: { left: 52, right: 20, top: 20, bottom: 48 },
      xAxis: {
        type: "category",
        data: selectedValues.map((v) => v.date_label),
        axisLabel: { color: AXIS_COLOR, fontSize: 10, rotate: 25 },
        axisLine: { lineStyle: { color: GRID_LINE } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: AXIS_COLOR, fontSize: 10 },
        splitLine: { lineStyle: { color: GRID_LINE } },
      },
      series: [
        {
          type: "line",
          smooth: true,
          symbolSize: 8,
          data: selectedValues.map((v) => v.value_numeric),
          lineStyle: { color: "#7c3aed", width: 2 },
          itemStyle: {
            color: (p: { dataIndex: number }) => {
              const v = selectedValues[p.dataIndex];
              if (!v) return "#7c3aed";
              if (v.status === "out_of_range") return "#dc2626";
              if (v.status === "no_reference_range") return "#d97706";
              return "#16a34a";
            },
          },
          markArea,
        },
      ],
    };
  }, [selectedValues, refRange]);

  const latest = selectedValues[selectedValues.length - 1];
  const previous = selectedValues.length > 1 ? selectedValues[selectedValues.length - 2] : null;
  const delta =
    latest?.value_numeric !== null && latest?.value_numeric !== undefined && previous?.value_numeric !== null && previous?.value_numeric !== undefined && previous
      ? latest.value_numeric - previous.value_numeric
      : null;

  return (
    <ChartCard title={t("selectedMarkerDeepDive")} subtitle={t("selectedMarkerDeepDiveDesc")}>
      <div style={{ marginBottom: 14, maxWidth: 320 }}>
        <select
          className="text-input"
          value={activeMarkerKey || ""}
          onChange={(e) => onSelectMarker(e.target.value)}
          style={{ borderRadius: 12, padding: "9px 32px 9px 12px", fontSize: 13, width: "100%" }}
        >
          {markers.map((m) => (
            <option key={m.marker_key} value={m.marker_key}>
              {m.marker_name}
            </option>
          ))}
        </select>
      </div>

      {selectedValues.length === 0 || !lineOption ? (
        <EmptyStateCard title={t("notEnoughData")} description={t("selectMarkerToExplore")} icon="📈" />
      ) : (
        <>
          <ReactECharts
            option={lineOption}
            style={{ height: 280 }}
            onEvents={{
              click: (p: { dataIndex: number }) => {
                const v = selectedValues[p.dataIndex];
                if (v) onPointClick(v);
              },
            }}
          />

          <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
            {refRange ? `${t("referenceRangeFromSource")}: ${refRange.text}` : t("referenceRangeNotFound")}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginTop: 14 }}>
            {[
              { label: t("latestValue"), value: latest ? `${latest.value_display} ${latest.unit || ""}` : "—" },
              { label: t("previousValue"), value: previous ? `${previous.value_display} ${previous.unit || ""}` : "—" },
              { label: "Δ", value: delta === null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(2)}` },
            ].map(({ label, value }) => (
              <div key={label} className="soft-card-tight" style={{ padding: "12px 14px" }}>
                <div className="muted-text" style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}>
                  {label}
                </div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <TrendBadge direction={latest?.trend} t={t} />
            <span className="muted-text" style={{ fontSize: 11 }}>
              {selectedTrend?.points.length ?? selectedValues.length} {t("dataPoints").toLowerCase()}
            </span>
          </div>
        </>
      )}
    </ChartCard>
  );
}

function TrendBadge({ direction, t }: { direction?: AnalyticsLabValue["trend"]; t: Translate }) {
  if (!direction || direction === "insufficient_data") {
    return (
      <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: "var(--panel-2)", color: "var(--muted)" }}>
        {t("notEnoughDataShort")}
      </span>
    );
  }
  const map = {
    increased: { sym: "↑", bg: "var(--warn-bg)", color: "var(--warn-text)" },
    decreased: { sym: "↓", bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)" },
    stable: { sym: "→", bg: "var(--success-bg)", color: "var(--success-text)" },
  } as const;
  const c = map[direction];
  return (
    <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800, background: c.bg, color: c.color }}>
      {c.sym} {t("trendColumn")}
    </span>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// CATEGORIES TAB
// ════════════════════════════════════════════════════════════════════════════

function CategoriesTab({
  filteredValues,
  onSelectCategory,
  onOpenMarker,
  t,
}: {
  filteredValues: AnalyticsLabValue[];
  onSelectCategory: (cat: string) => void;
  onOpenMarker: (markerKey: string) => void;
  t: Translate;
}) {
  const categoryData = useMemo(() => {
    const map = new Map<string, { catKey: string; in_range: number; out_of_range: number; no_ref: number; qualitative: number }>();
    for (const v of filteredValues) {
      if (!map.has(v.category_display)) {
        map.set(v.category_display, { catKey: v.category, in_range: 0, out_of_range: 0, no_ref: 0, qualitative: 0 });
      }
      const entry = map.get(v.category_display)!;
      if (v.status === "out_of_range") entry.out_of_range++;
      else if (v.status === "in_range") entry.in_range++;
      else if (v.status === "no_reference_range") entry.no_ref++;
      else entry.qualitative++;
    }
    return [...map.entries()].map(([display, vals]) => ({ display, ...vals }));
  }, [filteredValues]);

  const coverageOption = useMemo(() => {
    const cats = categoryData.map((c) => c.display);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipBox() },
      legend: {
        data: [t("inRange"), t("outOfRange"), t("noReferenceRange"), t("qualitativeResult")],
        textStyle: { color: AXIS_COLOR, fontSize: 10 },
        top: 0,
      },
      grid: { left: 130, right: 20, top: 32, bottom: 20 },
      xAxis: { type: "value", axisLabel: { color: AXIS_COLOR, fontSize: 10 }, splitLine: { lineStyle: { color: GRID_LINE } } },
      yAxis: { type: "category", data: cats, axisLabel: { color: AXIS_COLOR, fontSize: 10 } },
      series: [
        { name: t("inRange"), type: "bar", stack: "x", data: categoryData.map((c) => c.in_range), itemStyle: { color: "#16a34a" } },
        { name: t("outOfRange"), type: "bar", stack: "x", data: categoryData.map((c) => c.out_of_range), itemStyle: { color: "#dc2626" } },
        { name: t("noReferenceRange"), type: "bar", stack: "x", data: categoryData.map((c) => c.no_ref), itemStyle: { color: "#d97706" } },
        { name: t("qualitativeResult"), type: "bar", stack: "x", data: categoryData.map((c) => c.qualitative), itemStyle: { color: "#0284c7" } },
      ],
    };
  }, [categoryData, t]);

  const miniMarkers = useMemo(() => [...latestByMarker(filteredValues).values()], [filteredValues]);
  const valuesByMarker = useMemo(() => {
    const map = new Map<string, AnalyticsLabValue[]>();
    for (const v of filteredValues) {
      const list = map.get(v.marker_key) || [];
      list.push(v);
      map.set(v.marker_key, list);
    }
    for (const list of map.values()) list.sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date));
    return map;
  }, [filteredValues]);

  return (
    <>
      <ChartCard title={t("categoryOverview")} subtitle={t("categoryOverviewDesc")}>
        {categoryData.length === 0 ? (
          <EmptyStateCard title={t("notEnoughData")} />
        ) : categoryData.length === 1 ? (
          <div className="soft-card-tight" style={{ padding: 16 }}>
            <div style={{ fontWeight: 700 }}>{categoryData[0].display}</div>
            <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>
              {t("inRange")}: {categoryData[0].in_range} · {t("outOfRange")}: {categoryData[0].out_of_range} · {t("noReferenceRange")}: {categoryData[0].no_ref}
            </div>
          </div>
        ) : (
          <ReactECharts
            option={coverageOption}
            style={{ height: Math.max(220, categoryData.length * 38 + 60) }}
            onEvents={{
              click: (p: { name: string }) => {
                const cat = categoryData.find((c) => c.display === p.name);
                if (cat) onSelectCategory(cat.catKey);
              },
            }}
          />
        )}
      </ChartCard>

      <ChartCard title={t("smallMultiplesTrendGrid")} subtitle={t("smallMultiplesTrendGridDesc")}>
        {miniMarkers.length === 0 ? (
          <EmptyStateCard title={t("notEnoughData")} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {miniMarkers.map((m) => {
              const series = valuesByMarker.get(m.marker_key) || [];
              return (
                <button
                  key={m.marker_key}
                  type="button"
                  className="soft-card-tight"
                  onClick={() => onOpenMarker(m.marker_key)}
                  style={{ padding: 12, textAlign: "left", cursor: "pointer", display: "flex", flexDirection: "column", gap: 6, height: 140 }}
                >
                  <MiniSparkline values={series} status={m.status} />
                  <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={m.marker_name}>
                    {m.marker_name}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>
                      {m.value_display} {m.unit || ""}
                    </span>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <span style={{ fontSize: 13, color: "var(--muted)" }}>{trendArrow(m.trend)}</span>
                      <span style={{ width: 8, height: 8, borderRadius: 999, background: STATUS_CELL[m.status].dot, display: "inline-block" }} />
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </ChartCard>
    </>
  );
}

function trendArrow(direction?: AnalyticsLabValue["trend"]): string {
  if (direction === "increased") return "↑";
  if (direction === "decreased") return "↓";
  if (direction === "stable") return "→";
  return "·";
}

function MiniSparkline({ values, status }: { values: AnalyticsLabValue[]; status: AnalyticsLabStatus }) {
  const nums = values.map((v) => v.value_numeric).filter((n): n is number => n !== null);
  const color = STATUS_CELL[status].dot;
  const w = 100;
  const h = 48;
  if (nums.length === 0) {
    return <div style={{ height: h, background: "var(--panel-2)", borderRadius: 6 }} />;
  }
  if (nums.length === 1) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
        <circle cx={w / 2} cy={h / 2} r={4} fill={color} />
      </svg>
    );
  }
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const points = nums
    .map((n, i) => {
      const x = (i / (nums.length - 1)) * (w - 4) + 2;
      const y = h - 4 - ((n - min) / span) * (h - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// SOURCE RECORDS TAB
// ════════════════════════════════════════════════════════════════════════════

function SourceTab({
  documents,
  markerLatest,
  onRowClick,
  t,
}: {
  documents: AnalyticsDocument[];
  markerLatest: AnalyticsLabValue[];
  onRowClick: (v: AnalyticsLabValue) => void;
  t: Translate;
}) {
  const timelineOption = useMemo(() => buildTimelineOption(documents), [documents]);

  return (
    <>
      <ChartCard title={t("sourceRecordsTimeline")} subtitle={t("sourceRecordsTimelineDesc")}>
        {documents.length > 0 ? (
          <ReactECharts option={timelineOption} style={{ height: 240 }} />
        ) : (
          <EmptyStateCard title={t("notEnoughData")} />
        )}
      </ChartCard>

      <ChartCard title={t("allSourceValues")} subtitle={t("clinicalLabMatrixDesc")}>
        {markerLatest.length === 0 ? (
          <EmptyStateCard title={t("notEnoughData")} />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {[
                    t("markerColumn"),
                    t("categoryColumn"),
                    t("latestColumn"),
                    t("unitColumn"),
                    t("statusColumn"),
                    t("trendColumn"),
                    t("dateColumn"),
                    t("openColumn"),
                  ].map((h) => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 700, color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {markerLatest.map((v, idx) => (
                  <tr
                    key={v.marker_key}
                    onClick={() => onRowClick(v)}
                    style={{
                      borderBottom: "1px solid var(--border)",
                      cursor: "pointer",
                      background: idx % 2 === 0 ? "transparent" : "color-mix(in srgb, var(--panel-2) 50%, transparent)",
                    }}
                  >
                    <td style={{ padding: "9px 12px", fontWeight: 700 }}>{v.marker_name}</td>
                    <td style={{ padding: "9px 12px", color: "var(--muted)" }}>{v.category_display}</td>
                    <td style={{ padding: "9px 12px", fontWeight: 600 }}>{v.value_display}</td>
                    <td style={{ padding: "9px 12px", color: "var(--muted)" }}>{v.unit || "—"}</td>
                    <td style={{ padding: "9px 12px" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                        <span style={{ width: 8, height: 8, borderRadius: 999, background: STATUS_CELL[v.status].dot, display: "inline-block" }} />
                        <span style={{ fontSize: 12, color: "var(--muted)" }}>{statusShort(v.status, t)}</span>
                      </span>
                    </td>
                    <td style={{ padding: "9px 12px", color: "var(--muted)" }}>{trendArrow(v.trend)}</td>
                    <td style={{ padding: "9px 12px", color: "var(--muted)" }}>{v.date_label}</td>
                    <td style={{ padding: "9px 12px", color: "var(--primary)", fontWeight: 700 }}>→</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ChartCard>
    </>
  );
}

function statusShort(status: AnalyticsLabStatus, t: Translate): string {
  switch (status) {
    case "in_range":
      return t("inRange");
    case "out_of_range":
      return t("outOfRange");
    case "no_reference_range":
      return t("noReferenceRange");
    case "qualitative":
      return t("qualitativeResult");
    default:
      return t("notPresent");
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ADVANCED TAB
// ════════════════════════════════════════════════════════════════════════════

function AdvancedTab({
  filteredValues,
  advancedView,
  setAdvancedView,
  t,
}: {
  filteredValues: AnalyticsLabValue[];
  advancedView: AdvancedView | null;
  setAdvancedView: (v: AdvancedView | null) => void;
  t: Translate;
}) {
  const cards: { key: AdvancedView; title: string; desc: string }[] = [
    { key: "panel", title: t("panelCompletenessMap"), desc: t("panelCompletenessMapDesc") },
    { key: "scatter", title: t("markerRelationshipScatter"), desc: t("markerRelationshipScatterDesc") },
    { key: "radar", title: t("radarSnapshot"), desc: t("radarSnapshotDesc") },
    { key: "boxplot", title: t("boxplotDistribution"), desc: t("boxplotDistributionDesc") },
    { key: "waterfall", title: t("waterfallDelta"), desc: t("waterfallDeltaDesc") },
    { key: "calendar", title: t("calendarHeatmap"), desc: t("calendarHeatmapDesc") },
  ];

  return (
    <ChartCard title={t("advancedVisualizations")} subtitle={t("advancedVisualizationsDesc")}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10, marginBottom: advancedView ? 20 : 0 }}>
        {cards.map((c) => (
          <button
            key={c.key}
            type="button"
            className={advancedView === c.key ? "primary-btn" : "secondary-btn"}
            onClick={() => setAdvancedView(advancedView === c.key ? null : c.key)}
            style={{ padding: 14, textAlign: "left", display: "flex", flexDirection: "column", gap: 4, height: "100%" }}
          >
            <span style={{ fontWeight: 700, fontSize: 13 }}>{c.title}</span>
            <span style={{ fontSize: 11, opacity: 0.8 }}>{c.desc}</span>
          </button>
        ))}
      </div>

      {advancedView === null && (
        <div style={{ marginTop: 16 }}>
          <EmptyStateCard title={t("selectVisualization")} icon="✦" />
        </div>
      )}
      {advancedView === "panel" && <PanelCompleteness values={filteredValues} t={t} />}
      {advancedView === "scatter" && <ScatterView values={filteredValues} t={t} />}
      {advancedView === "radar" && <RadarView values={filteredValues} t={t} />}
      {advancedView === "boxplot" && <BoxplotView values={filteredValues} t={t} />}
      {advancedView === "waterfall" && <WaterfallView values={filteredValues} t={t} />}
      {advancedView === "calendar" && <CalendarView values={filteredValues} t={t} />}
    </ChartCard>
  );
}

// Panel completeness: custom matrix subgroup x date
function PanelCompleteness({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const data = useMemo(() => {
    const dates = uniqueSortedDates(values);
    const subgroups = new Set<string>();
    const present = new Set<string>();
    for (const v of values) {
      const sg = v.subgroup || v.category_display;
      subgroups.add(sg);
      present.add(`${sg}__${v.date}`);
    }
    return { dates, subgroups: [...subgroups].sort(), present };
  }, [values]);

  if (!data.dates.length || !data.subgroups.length) {
    return <EmptyStateCard title={t("notEnoughData")} icon="▦" />;
  }
  const colW = 52;
  const labelW = 180;
  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ minWidth: labelW + data.dates.length * colW }}>
        <div style={{ display: "flex" }}>
          <div style={{ width: labelW, minWidth: labelW, fontSize: 10, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", padding: "6px 10px" }} />
          {data.dates.map((d) => (
            <div key={d} title={d} style={{ width: colW, minWidth: colW, textAlign: "center", fontSize: 9, color: "var(--muted)", padding: "6px 2px" }}>
              {formatTinyDate(d)}
            </div>
          ))}
        </div>
        {data.subgroups.map((sg) => (
          <div key={sg} style={{ display: "flex", alignItems: "center" }}>
            <div title={sg} style={{ width: labelW, minWidth: labelW, maxWidth: labelW, fontSize: 12, fontWeight: 600, padding: "4px 10px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", borderTop: "1px solid var(--border)" }}>
              {sg}
            </div>
            {data.dates.map((d) => {
              const has = data.present.has(`${sg}__${d}`);
              return (
                <div key={d} style={{ width: colW, minWidth: colW, height: 30, padding: 4, borderTop: "1px solid var(--border)" }}>
                  <div style={{ width: "100%", height: "100%", borderRadius: 6, background: has ? "rgba(124,58,237,0.18)" : NOT_PRESENT_BG, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {has && <span style={{ width: 6, height: 6, borderRadius: 999, background: "#7c3aed" }} />}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function ScatterView({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const { pairs, option } = useMemo(() => {
    // index numeric values by date -> marker
    const byDate = new Map<string, Map<string, number>>();
    for (const v of values) {
      if (v.value_numeric === null || v.value_numeric === undefined) continue;
      if (!byDate.has(v.date)) byDate.set(v.date, new Map());
      byDate.get(v.date)!.set(v.marker_key, v.value_numeric);
    }
    // count co-occurrences per marker pair
    const markerNames = new Map<string, string>();
    for (const v of values) markerNames.set(v.marker_key, v.marker_name);
    const pairCount = new Map<string, { a: string; b: string; pts: [number, number][] }>();
    for (const dayMap of byDate.values()) {
      const keys = [...dayMap.keys()].sort();
      for (let i = 0; i < keys.length; i++) {
        for (let j = i + 1; j < keys.length; j++) {
          const pk = `${keys[i]}|${keys[j]}`;
          if (!pairCount.has(pk)) pairCount.set(pk, { a: keys[i], b: keys[j], pts: [] });
          pairCount.get(pk)!.pts.push([dayMap.get(keys[i])!, dayMap.get(keys[j])!]);
        }
      }
    }
    const best = [...pairCount.values()].filter((p) => p.pts.length >= 3).sort((a, b) => b.pts.length - a.pts.length)[0];
    if (!best) return { pairs: false, option: null };
    const aName = markerNames.get(best.a) || best.a;
    const bName = markerNames.get(best.b) || best.b;
    return {
      pairs: true,
      option: {
        backgroundColor: "transparent",
        tooltip: { ...tooltipBox(), formatter: (p: { value: [number, number] }) => `${aName}: ${p.value[0]}<br/>${bName}: ${p.value[1]}` },
        grid: { left: 52, right: 24, top: 24, bottom: 48 },
        xAxis: { type: "value", name: aName, scale: true, nameTextStyle: { color: AXIS_COLOR, fontSize: 10 }, axisLabel: { color: AXIS_COLOR, fontSize: 10 }, splitLine: { lineStyle: { color: GRID_LINE } } },
        yAxis: { type: "value", name: bName, scale: true, nameTextStyle: { color: AXIS_COLOR, fontSize: 10 }, axisLabel: { color: AXIS_COLOR, fontSize: 10 }, splitLine: { lineStyle: { color: GRID_LINE } } },
        series: [{ type: "scatter", symbolSize: 12, data: best.pts, itemStyle: { color: "#7c3aed", opacity: 0.8 } }],
      },
    };
  }, [values]);

  if (!pairs || !option) return <EmptyStateCard title={t("notEnoughData")} icon="⚬" />;
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

function RadarView({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const option = useMemo(() => {
    const latest = [...latestByMarker(values).values()].filter(
      (v) => v.value_numeric !== null && v.reference_low !== null && v.reference_high !== null,
    );
    if (latest.length < 4) return null;
    const picked = latest.slice(0, 8);
    const indicators = picked.map((v) => ({ name: v.marker_name, max: 100, min: -20 }));
    const data = picked.map((v) => {
      const span = (v.reference_high! - v.reference_low!) || 1;
      return ((v.value_numeric! - v.reference_low!) / span) * 100;
    });
    return {
      backgroundColor: "transparent",
      tooltip: { ...tooltipBox() },
      radar: {
        indicator: indicators,
        axisName: { color: AXIS_COLOR, fontSize: 10 },
        splitLine: { lineStyle: { color: GRID_LINE } },
        splitArea: { areaStyle: { color: ["transparent"] } },
        axisLine: { lineStyle: { color: GRID_LINE } },
      },
      series: [{ type: "radar", data: [{ value: data, name: t("radarSnapshot") }], areaStyle: { color: "rgba(124,58,237,0.18)" }, lineStyle: { color: "#7c3aed" }, itemStyle: { color: "#7c3aed" } }],
    };
  }, [values, t]);

  if (!option) return <EmptyStateCard title={t("notEnoughData")} icon="◈" />;
  return (
    <>
      <div className="muted-text" style={{ fontSize: 11, marginBottom: 8 }}>{t("referenceRangeFromSource")}</div>
      <ReactECharts option={option} style={{ height: 340 }} />
    </>
  );
}

function BoxplotView({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const option = useMemo(() => {
    const byMarker = new Map<string, { name: string; nums: number[] }>();
    for (const v of values) {
      if (v.value_numeric === null || v.value_numeric === undefined) continue;
      if (!byMarker.has(v.marker_key)) byMarker.set(v.marker_key, { name: v.marker_name, nums: [] });
      byMarker.get(v.marker_key)!.nums.push(v.value_numeric);
    }
    const eligible = [...byMarker.values()].filter((m) => m.nums.length >= 4).slice(0, 12);
    if (!eligible.length) return null;
    const boxData = eligible.map((m) => {
      const sorted = [...m.nums].sort((a, b) => a - b);
      const q = (p: number) => {
        const idx = (sorted.length - 1) * p;
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
      };
      return [sorted[0], q(0.25), q(0.5), q(0.75), sorted[sorted.length - 1]];
    });
    return {
      backgroundColor: "transparent",
      tooltip: { ...tooltipBox(), trigger: "item" },
      grid: { left: 52, right: 24, top: 20, bottom: 70 },
      xAxis: { type: "category", data: eligible.map((m) => m.name), axisLabel: { color: AXIS_COLOR, fontSize: 9, rotate: 35 }, axisLine: { lineStyle: { color: GRID_LINE } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: AXIS_COLOR, fontSize: 10 }, splitLine: { lineStyle: { color: GRID_LINE } } },
      series: [{ type: "boxplot", data: boxData, itemStyle: { color: "rgba(124,58,237,0.25)", borderColor: "#7c3aed" } }],
    };
  }, [values]);

  if (!option) return <EmptyStateCard title={t("notEnoughData")} icon="▭" />;
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

function WaterfallView({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const option = useMemo(() => {
    const byMarker = new Map<string, AnalyticsLabValue[]>();
    for (const v of values) {
      if (v.value_numeric === null || v.value_numeric === undefined) continue;
      const list = byMarker.get(v.marker_key) || [];
      list.push(v);
      byMarker.set(v.marker_key, list);
    }
    const deltas: { name: string; delta: number }[] = [];
    for (const list of byMarker.values()) {
      if (list.length < 2) continue;
      const sorted = list.sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date));
      const latest = sorted[sorted.length - 1].value_numeric!;
      const prev = sorted[sorted.length - 2].value_numeric!;
      deltas.push({ name: sorted[0].marker_name, delta: latest - prev });
    }
    const top = deltas.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 14);
    if (!top.length) return null;
    return {
      backgroundColor: "transparent",
      tooltip: { ...tooltipBox(), trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 52, right: 24, top: 20, bottom: 70 },
      xAxis: { type: "category", data: top.map((d) => d.name), axisLabel: { color: AXIS_COLOR, fontSize: 9, rotate: 35 }, axisLine: { lineStyle: { color: GRID_LINE } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: AXIS_COLOR, fontSize: 10 }, splitLine: { lineStyle: { color: GRID_LINE } } },
      series: [{ type: "bar", data: top.map((d) => ({ value: d.delta, itemStyle: { color: d.delta >= 0 ? "#d97706" : "#7c3aed", borderRadius: 4 } })), barWidth: "55%" }],
    };
  }, [values]);

  if (!option) return <EmptyStateCard title={t("notEnoughData")} icon="≋" />;
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

function CalendarView({ values, t }: { values: AnalyticsLabValue[]; t: Translate }) {
  const option = useMemo(() => {
    const byDay = new Map<string, number>();
    let minMs = Infinity;
    let maxMs = -Infinity;
    for (const v of values) {
      const ms = parseDateTime(v.date);
      if (!ms) continue;
      const iso = new Date(ms).toISOString().slice(0, 10);
      byDay.set(iso, (byDay.get(iso) || 0) + 1);
      minMs = Math.min(minMs, ms);
      maxMs = Math.max(maxMs, ms);
    }
    if (!byDay.size) return null;
    const data = [...byDay.entries()].map(([iso, count]) => [iso, count]);
    const maxCount = Math.max(...byDay.values());
    const startYear = new Date(minMs).getFullYear();
    const endYear = new Date(maxMs).getFullYear();
    const range = startYear === endYear ? `${startYear}` : [`${startYear}`, `${endYear}`];
    return {
      backgroundColor: "transparent",
      tooltip: { ...tooltipBox(), formatter: (p: { value: [string, number] }) => `${p.value[0]}<br/>${p.value[1]}` },
      visualMap: { min: 0, max: maxCount, calculable: false, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["rgba(124,58,237,0.15)", "#7c3aed"] }, textStyle: { color: AXIS_COLOR, fontSize: 10 } },
      calendar: {
        range,
        cellSize: ["auto", 16],
        itemStyle: { borderColor: GRID_LINE, color: "transparent" },
        splitLine: { lineStyle: { color: GRID_LINE } },
        dayLabel: { color: AXIS_COLOR, fontSize: 9 },
        monthLabel: { color: AXIS_COLOR, fontSize: 9 },
        yearLabel: { color: AXIS_COLOR, fontSize: 10 },
      },
      series: [{ type: "heatmap", coordinateSystem: "calendar", data }],
    };
  }, [values]);

  if (!option) return <EmptyStateCard title={t("notEnoughData")} icon="▤" />;
  return <ReactECharts option={option} style={{ height: 240 }} />;
}
