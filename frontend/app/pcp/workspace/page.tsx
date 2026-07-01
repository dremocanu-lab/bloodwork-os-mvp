"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

// ── Types ─────────────────────────────────────────────────────────────────────

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
  doctor_type?: "pcp" | "specialist" | null;
};

type PCPPatient = {
  id: number;
  full_name: string;
  age: string | null;
  sex: string | null;
  date_of_birth: string | null;
  patient_identifier: string | null;
};

type Medication = {
  id: number;
  name: string;
  dose_strength: string | null;
  frequency: string | null;
  status: string;
  route_form: string | null;
  is_uncertain: boolean;
  created_at?: string | null;
};

type PCPDoc = {
  id: number;
  section: string;
  filename: string;
  report_name: string | null;
  lab_name: string | null;
  test_date: string | null;
  is_verified: boolean;
  created_at: string | null;
};

type Lab = {
  name: string | null;
  value: string | null;
  unit: string | null;
  flag: string | null;
  reference_range: string | null;
  category: string | null;
};

type PcpTimelineEvent = {
  id: string;
  event_type:
    | "lab_panel"
    | "discharge_summary"
    | "imaging_report"
    | "clinical_note"
    | "medication_record"
    | "hospitalization_record"
    | "procedure_report"
    | "pathology_report"
    | "source_document"
    | "other";
  title: string;
  date: string;
  source_id: number | null;
  source_type: string | null;
  summary: string | null;
  route: string | null;
  is_source_linked: boolean;
};

type NotePreview = {
  id: number;
  filename: string;
  report_name: string | null;
  note_preview: string | null;
  created_at: string | null;
};

type PCPSummary = {
  patient: {
    id: number;
    full_name: string;
    age: string | null;
    sex: string | null;
    date_of_birth: string | null;
    patient_identifier: string | null;
    bragi_code: string | null;
  };
  care_context: "outpatient" | "active_admission" | "past_admission";
  care_context_label: string;
  access: { has_active_access: boolean };
  medications: Medication[];
  recent_documents: PCPDoc[];
  latest_labs: {
    document_id: number;
    test_date: string | null;
    lab_name: string | null;
    labs: Lab[];
  } | null;
  pcp_timeline: PcpTimelineEvent[];
  recent_notes: NotePreview[];
};

type PCPTab = {
  patientId: number;
  patientName: string;
};

type TimelineFilter =
  | "all"
  | "lab_panel"
  | "discharge_summary"
  | "imaging_report"
  | "clinical_note"
  | "medication_record"
  | "hospitalization_record";

// ── Storage ───────────────────────────────────────────────────────────────────

const TABS_KEY = "pcp_tab_ids";
const ACTIVE_KEY = "pcp_active_tab";
const MAX_TABS = 8;

function loadTabsFromStorage(): PCPTab[] {
  try {
    const raw = localStorage.getItem(TABS_KEY);
    return raw ? (JSON.parse(raw) as PCPTab[]) : [];
  } catch {
    return [];
  }
}
function saveTabsToStorage(tabs: PCPTab[]) {
  localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
}
function loadActiveFromStorage(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}
function saveActiveToStorage(id: number | null) {
  if (id === null) localStorage.removeItem(ACTIVE_KEY);
  else localStorage.setItem(ACTIVE_KEY, String(id));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(val?: string | null) {
  if (!val) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return val;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateShort(val?: string | null) {
  if (!val) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return val;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function ageSex(p: { age?: string | null; sex?: string | null }) {
  return [p.age, p.sex].filter(Boolean).join(" · ") || null;
}

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function sectionLabel(section: string) {
  const map: Record<string, string> = {
    bloodwork: "Lab panel",
    discharge_summary: "Discharge summary",
    scans: "Imaging",
    notes: "Clinical note",
    medications: "Medication doc",
    hospitalizations: "Hospitalization",
    other: "Source record",
  };
  return map[section] ?? "Source record";
}

function flagIsOutOfRange(flag: string | null) {
  if (!flag) return false;
  const f = flag.toLowerCase();
  return f === "h" || f === "high" || f === "l" || f === "low" || f === "a" || f === "abnormal";
}

function flagColor(flag: string | null): string {
  return flagIsOutOfRange(flag) ? "var(--danger-text)" : "inherit";
}

// ── Event type config ─────────────────────────────────────────────────────────

type EventConfig = {
  label: string;
  color: string;
  bg: string;
  dot: string;
};

function getEventConfig(eventType: string): EventConfig {
  const configs: Record<string, EventConfig> = {
    lab_panel: {
      label: "Lab panel",
      color: "#6d5dfc",
      bg: "color-mix(in srgb, #6d5dfc 10%, var(--panel-2))",
      dot: "#6d5dfc",
    },
    discharge_summary: {
      label: "Discharge summary",
      color: "#7c3aed",
      bg: "color-mix(in srgb, #7c3aed 10%, var(--panel-2))",
      dot: "#7c3aed",
    },
    imaging_report: {
      label: "Imaging report",
      color: "#0891b2",
      bg: "color-mix(in srgb, #0891b2 10%, var(--panel-2))",
      dot: "#0891b2",
    },
    clinical_note: {
      label: "Clinical note",
      color: "#059669",
      bg: "color-mix(in srgb, #059669 10%, var(--panel-2))",
      dot: "#059669",
    },
    medication_record: {
      label: "Medication record",
      color: "#d97706",
      bg: "color-mix(in srgb, #d97706 10%, var(--panel-2))",
      dot: "#d97706",
    },
    hospitalization_record: {
      label: "Hospitalization",
      color: "#dc2626",
      bg: "color-mix(in srgb, #dc2626 10%, var(--panel-2))",
      dot: "#dc2626",
    },
    procedure_report: {
      label: "Procedure report",
      color: "#0891b2",
      bg: "color-mix(in srgb, #0891b2 10%, var(--panel-2))",
      dot: "#0891b2",
    },
    pathology_report: {
      label: "Pathology report",
      color: "#7c3aed",
      bg: "color-mix(in srgb, #7c3aed 10%, var(--panel-2))",
      dot: "#7c3aed",
    },
    source_document: {
      label: "Source record",
      color: "var(--muted)",
      bg: "var(--panel-2)",
      dot: "var(--border)",
    },
  };
  return configs[eventType] ?? configs.source_document;
}

function getEventTypeLabel(eventType: string, t: (k: string) => string): string {
  const map: Record<string, string> = {
    lab_panel: t("pcpEventTypeLab"),
    discharge_summary: t("pcpEventTypeDischarge"),
    imaging_report: t("pcpEventTypeImaging"),
    clinical_note: t("pcpEventTypeNote"),
    medication_record: t("pcpEventTypeMedication"),
    hospitalization_record: t("pcpEventTypeHospitalization"),
    procedure_report: t("pcpEventTypeProcedure"),
    pathology_report: t("pcpEventTypePathology"),
    source_document: t("pcpEventTypeSource"),
  };
  return map[eventType] ?? t("pcpEventTypeOther");
}

function filterMatchesEvent(filter: TimelineFilter, event: PcpTimelineEvent): boolean {
  if (filter === "all") return true;
  if (filter === "lab_panel") return event.event_type === "lab_panel";
  if (filter === "discharge_summary")
    return event.event_type === "discharge_summary";
  if (filter === "imaging_report") return event.event_type === "imaging_report";
  if (filter === "clinical_note") return event.event_type === "clinical_note";
  if (filter === "medication_record")
    return event.event_type === "medication_record";
  if (filter === "hospitalization_record")
    return event.event_type === "hospitalization_record";
  return true;
}

// ── Small shared UI pieces ────────────────────────────────────────────────────

function Card({
  children,
  style,
  className,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    <div className={`soft-card ${className ?? ""}`} style={{ padding: "18px 20px", ...style }}>
      {children}
    </div>
  );
}

function CardTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
        marginBottom: subtitle ? 2 : 14,
      }}
    >
      <div>
        <div style={{ fontWeight: 900, fontSize: 14, letterSpacing: "-0.01em" }}>{title}</div>
        {subtitle && (
          <div className="muted-text" style={{ fontSize: 11, marginTop: 2, marginBottom: 12 }}>
            {subtitle}
          </div>
        )}
      </div>
      {action && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  );
}

function Pill({
  label,
  color,
  bg,
}: {
  label: string;
  color?: string;
  bg?: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 9px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        background: bg ?? "var(--panel-2)",
        border: "1px solid var(--border)",
        color: color ?? "var(--muted)",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <p className="muted-text" style={{ fontSize: 13, margin: "8px 0 0" }}>
      {text}
    </p>
  );
}

// ── Blocked page ──────────────────────────────────────────────────────────────

function PCPBlockedPage({ user }: { user: CurrentUser }) {
  const { t } = useLanguage();
  return (
    <AppShell user={user} title={t("pcpWorkspace")}>
      <div style={{ maxWidth: 480, margin: "60px auto", textAlign: "center", padding: "0 24px" }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 999,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 24px",
            fontSize: 28,
          }}
        >
          🔒
        </div>
        <div style={{ fontWeight: 900, fontSize: 20, marginBottom: 12 }}>{t("pcpWorkspace")}</div>
        <p className="muted-text" style={{ fontSize: 14, lineHeight: 1.65 }}>
          {t("pcpBlockedBody")}
        </p>
        <Link
          href="/my-patients"
          className="primary-btn"
          style={{ display: "inline-flex", marginTop: 28, textDecoration: "none" }}
        >
          {t("myCurrentPatients")}
        </Link>
      </div>
    </AppShell>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function PCPTabBar({
  tabs,
  activeId,
  onSelect,
  onClose,
  onAdd,
  maxReached,
  patients,
}: {
  tabs: PCPTab[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onClose: (id: number) => void;
  onAdd: () => void;
  maxReached: boolean;
  patients: PCPPatient[];
}) {
  const { t } = useLanguage();
  const patientMap = new Map(patients.map((p) => [p.id, p]));

  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        gap: 3,
        overflowX: "auto",
        padding: "0 0 0",
        marginBottom: 20,
        scrollbarWidth: "none",
        msOverflowStyle: "none",
      } as React.CSSProperties}
    >
      {tabs.map((tab) => {
        const active = tab.patientId === activeId;
        const patient = patientMap.get(tab.patientId);
        const meta = patient ? ageSex(patient) : null;
        return (
          <div
            key={tab.patientId}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 12px 8px 14px",
              borderRadius: 12,
              border: `1.5px solid ${active ? "var(--primary)" : "var(--border)"}`,
              background: active
                ? "color-mix(in srgb, var(--primary) 9%, var(--panel))"
                : "var(--panel)",
              cursor: "pointer",
              flexShrink: 0,
              maxWidth: 220,
              transition: "border-color 0.12s, background 0.12s",
              boxShadow: active ? "0 2px 12px color-mix(in srgb, var(--primary) 18%, transparent)" : "none",
            }}
          >
            <button
              type="button"
              onClick={() => onSelect(tab.patientId)}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                textAlign: "left",
                minWidth: 0,
              }}
            >
              <div
                style={{
                  fontWeight: active ? 800 : 600,
                  fontSize: 13,
                  color: active ? "var(--primary)" : "var(--text)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: 150,
                }}
              >
                {tab.patientName}
              </div>
              {meta && (
                <div
                  className="muted-text"
                  style={{ fontSize: 10, marginTop: 1, whiteSpace: "nowrap" }}
                >
                  {meta}
                </div>
              )}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onClose(tab.patientId);
              }}
              title={t("pcpCloseTab")}
              style={{
                background: "none",
                border: "none",
                padding: "2px 3px",
                cursor: "pointer",
                color: "var(--muted)",
                fontSize: 16,
                lineHeight: 1,
                flexShrink: 0,
                borderRadius: 4,
                marginLeft: 2,
              }}
            >
              ×
            </button>
          </div>
        );
      })}

      <button
        type="button"
        onClick={onAdd}
        disabled={maxReached}
        title={
          maxReached
            ? `${t("pcpMaxTabsReached")} ${t("pcpMaxTabsBody")}`
            : t("pcpAddPatient")
        }
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "8px 14px",
          borderRadius: 12,
          border: "1.5px dashed var(--border)",
          background: "transparent",
          cursor: maxReached ? "not-allowed" : "pointer",
          flexShrink: 0,
          fontWeight: 700,
          fontSize: 13,
          color: maxReached ? "var(--muted)" : "var(--primary)",
          opacity: maxReached ? 0.5 : 1,
          whiteSpace: "nowrap",
          transition: "border-color 0.12s",
        }}
      >
        + {t("pcpAddPatient")}
      </button>
    </div>
  );
}

// ── Patient selector panel ────────────────────────────────────────────────────

function PCPPatientSelectPanel({
  patients,
  openTabs,
  onOpen,
  maxReached,
}: {
  patients: PCPPatient[];
  openTabs: PCPTab[];
  onOpen: (p: PCPPatient) => void;
  maxReached: boolean;
}) {
  const { t } = useLanguage();
  const [query, setQuery] = useState("");

  const filtered = patients.filter(
    (p) =>
      p.full_name.toLowerCase().includes(query.toLowerCase()) ||
      (p.patient_identifier ?? "").toLowerCase().includes(query.toLowerCase())
  );

  const openIds = new Set(openTabs.map((tab) => tab.patientId));

  return (
    <div style={{ maxWidth: 620 }}>
      <Card>
        <CardTitle title={t("pcpCurrentApprovedPatients")} />

        {maxReached && (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--panel-2)",
              border: "1px solid var(--border)",
              fontSize: 13,
              marginBottom: 14,
            }}
          >
            <strong>{t("pcpMaxTabsReached")}</strong> {t("pcpMaxTabsBody")}
          </div>
        )}

        <input
          className="text-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`${t("pcpSearchApprovedPatients")}…`}
          style={{ marginBottom: 14 }}
        />

        {patients.length === 0 && <EmptyState text={t("pcpNoPatients")} />}
        {patients.length > 0 && filtered.length === 0 && (
          <EmptyState text="No matching patients." />
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((p) => {
            const isOpen = openIds.has(p.id);
            return (
              <div
                key={p.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: "1px solid var(--border)",
                  background: isOpen
                    ? "color-mix(in srgb, var(--primary) 5%, var(--panel-2))"
                    : "var(--panel-2)",
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 999,
                    background: "var(--primary)",
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 900,
                    fontSize: 14,
                    flexShrink: 0,
                  }}
                >
                  {initials(p.full_name)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 800, fontSize: 14 }}>{p.full_name}</div>
                  {ageSex(p) && (
                    <div className="muted-text" style={{ fontSize: 12 }}>
                      {ageSex(p)}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className={isOpen ? "secondary-btn" : "primary-btn"}
                  style={{ fontSize: 12, padding: "6px 14px", flexShrink: 0 }}
                  onClick={() => onOpen(p)}
                  disabled={maxReached && !isOpen}
                >
                  {isOpen ? t("pcpSwitchToTab") : t("pcpAddPatient")}
                </button>
              </div>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 16,
            paddingTop: 14,
            borderTop: "1px solid var(--border)",
          }}
        >
          <Link
            href="/patients/search"
            className="secondary-btn"
            style={{ display: "inline-flex", fontSize: 13, textDecoration: "none" }}
          >
            {t("pcpSearchMorePatients")} →
          </Link>
        </div>
      </Card>
    </div>
  );
}

// ── Patient hero card ─────────────────────────────────────────────────────────

function PatientHeroCard({
  summary,
  patientId,
}: {
  summary: PCPSummary;
  patientId: number;
}) {
  const { t } = useLanguage();
  const p = summary.patient;
  const careCtx = summary.care_context;

  const contextColor =
    careCtx === "active_admission"
      ? "var(--danger-text)"
      : careCtx === "past_admission"
      ? "var(--warn-text)"
      : "var(--success-text)";
  const contextBg =
    careCtx === "active_admission"
      ? "var(--danger-bg)"
      : careCtx === "past_admission"
      ? "var(--warn-bg)"
      : "var(--success-bg)";

  return (
    <Card
      style={{
        marginBottom: 18,
        background: "linear-gradient(135deg, var(--panel) 0%, color-mix(in srgb, var(--primary) 3%, var(--panel)) 100%)",
        borderLeft: "3px solid var(--primary)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 18, flexWrap: "wrap" }}>
        {/* Avatar */}
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: 999,
            background: "var(--primary)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 900,
            fontSize: 20,
            flexShrink: 0,
            boxShadow: "0 4px 14px color-mix(in srgb, var(--primary) 30%, transparent)",
          }}
        >
          {initials(p.full_name)}
        </div>

        {/* Name + meta */}
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 900, fontSize: 20, letterSpacing: "-0.02em", marginBottom: 6 }}>
            {p.full_name}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {ageSex(p) && <Pill label={ageSex(p)!} />}
            <Pill
              label={t("pcpActiveAccess")}
              color="var(--success-text)"
              bg="var(--success-bg)"
            />
            <Pill
              label={summary.care_context_label}
              color={contextColor}
              bg={contextBg}
            />
            {p.bragi_code && (
              <Pill label={`Bragi: ${p.bragi_code}`} color="var(--muted)" />
            )}
            {p.patient_identifier && (
              <Pill label={`ID: ${p.patient_identifier}`} color="var(--muted)" />
            )}
          </div>
        </div>

        {/* Quick actions */}
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <Link
            href={`/patients/${patientId}`}
            className="primary-btn"
            style={{ fontSize: 13, textDecoration: "none" }}
          >
            {t("pcpOpenFullChart")}
          </Link>
          <Link
            href={`/patients/${patientId}/notes/new`}
            className="secondary-btn"
            style={{ fontSize: 13, textDecoration: "none" }}
          >
            {t("pcpAddNote")}
          </Link>
          <Link
            href={`/patients/${patientId}/upload`}
            className="secondary-btn"
            style={{ fontSize: 13, textDecoration: "none" }}
          >
            {t("pcpUploadDocument")}
          </Link>
          <Link
            href={`/patients/${patientId}/timeline`}
            className="secondary-btn"
            style={{ fontSize: 13, textDecoration: "none" }}
          >
            {t("pcpViewTimeline")}
          </Link>
        </div>
      </div>
    </Card>
  );
}

// ── Timeline card ─────────────────────────────────────────────────────────────

const TIMELINE_PAGE_SIZE = 10;

const FILTERS: { key: TimelineFilter; labelKey: string }[] = [
  { key: "all", labelKey: "pcpAllEvents" },
  { key: "lab_panel", labelKey: "pcpLabsFilter" },
  { key: "discharge_summary", labelKey: "pcpDocumentsFilter" },
  { key: "imaging_report", labelKey: "pcpImagingFilter" },
  { key: "clinical_note", labelKey: "pcpNotesFilter" },
  { key: "medication_record", labelKey: "pcpMedicationsFilter" },
  { key: "hospitalization_record", labelKey: "pcpHospitalizationsFilter" },
];

function TimelineCard({
  events,
  patientId,
}: {
  events: PcpTimelineEvent[];
  patientId: number;
}) {
  const { t } = useLanguage();
  const [activeFilter, setActiveFilter] = useState<TimelineFilter>("all");
  const [showAll, setShowAll] = useState(false);

  const filtered = events.filter((e) => filterMatchesEvent(activeFilter, e));
  const shown = showAll ? filtered : filtered.slice(0, TIMELINE_PAGE_SIZE);
  const hasMore = filtered.length > TIMELINE_PAGE_SIZE && !showAll;

  return (
    <Card style={{ marginBottom: 14 }}>
      <CardTitle
        title={t("pcpTimeline")}
        subtitle={t("pcpTimelineSubtitle")}
        action={
          <Link
            href={`/patients/${patientId}/timeline`}
            className="secondary-btn"
            style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none" }}
          >
            {t("pcpOpenFullTimeline")} →
          </Link>
        }
      />

      {/* Filter chips */}
      <div
        style={{
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
          marginBottom: 18,
        }}
      >
        {FILTERS.map((f) => {
          const count =
            f.key === "all"
              ? events.length
              : events.filter((e) => filterMatchesEvent(f.key, e)).length;
          if (count === 0 && f.key !== "all") return null;
          const active = activeFilter === f.key;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => {
                setActiveFilter(f.key);
                setShowAll(false);
              }}
              style={{
                padding: "4px 12px",
                borderRadius: 999,
                border: `1.5px solid ${active ? "var(--primary)" : "var(--border)"}`,
                background: active
                  ? "color-mix(in srgb, var(--primary) 10%, var(--panel))"
                  : "var(--panel-2)",
                color: active ? "var(--primary)" : "var(--muted)",
                fontWeight: active ? 800 : 600,
                fontSize: 12,
                cursor: "pointer",
                whiteSpace: "nowrap",
                transition: "border-color 0.12s, background 0.12s",
              }}
            >
              {t(f.labelKey)} {count > 0 && <span style={{ opacity: 0.7 }}>{count}</span>}
            </button>
          );
        })}
      </div>

      {/* Timeline list */}
      {filtered.length === 0 ? (
        <EmptyState text={t("pcpNoTimelineEvents")} />
      ) : (
        <div style={{ position: "relative" }}>
          {/* Vertical rail */}
          <div
            style={{
              position: "absolute",
              left: 11,
              top: 8,
              bottom: 8,
              width: 2,
              background: "var(--border)",
              borderRadius: 1,
            }}
          />

          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {shown.map((ev, idx) => {
              const cfg = getEventConfig(ev.event_type);
              const isLast = idx === shown.length - 1;
              return (
                <div
                  key={ev.id}
                  style={{
                    display: "flex",
                    gap: 16,
                    paddingBottom: isLast ? 0 : 16,
                    position: "relative",
                  }}
                >
                  {/* Dot */}
                  <div style={{ flexShrink: 0, width: 24, display: "flex", justifyContent: "center" }}>
                    <div
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: 999,
                        background: cfg.dot,
                        border: "2px solid var(--panel)",
                        boxShadow: `0 0 0 2px ${cfg.dot}`,
                        marginTop: 6,
                        zIndex: 1,
                        position: "relative",
                      }}
                    />
                  </div>

                  {/* Content */}
                  <div
                    style={{
                      flex: 1,
                      minWidth: 0,
                      padding: "10px 14px",
                      borderRadius: 12,
                      border: "1px solid var(--border)",
                      background: "var(--panel-2)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 8,
                        flexWrap: "wrap",
                        marginBottom: 4,
                      }}
                    >
                      <span
                        style={{
                          padding: "1px 8px",
                          borderRadius: 999,
                          fontSize: 10,
                          fontWeight: 800,
                          color: cfg.color,
                          background: cfg.bg,
                          border: `1px solid ${cfg.color}33`,
                          whiteSpace: "nowrap",
                          letterSpacing: "0.02em",
                        }}
                      >
                        {getEventTypeLabel(ev.event_type, t)}
                      </span>
                      {ev.is_source_linked && (
                        <span
                          style={{
                            padding: "1px 8px",
                            borderRadius: 999,
                            fontSize: 10,
                            fontWeight: 700,
                            color: "var(--success-text)",
                            background: "var(--success-bg)",
                            border: "1px solid #bbf7d033",
                          }}
                        >
                          {t("pcpSourceLinkedEvent")}
                        </span>
                      )}
                      <span className="muted-text" style={{ fontSize: 11, marginLeft: "auto" }}>
                        {formatDateShort(ev.date)}
                      </span>
                    </div>

                    <div
                      style={{
                        fontWeight: 700,
                        fontSize: 13,
                        marginBottom: ev.summary ? 4 : 0,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={ev.title}
                    >
                      {ev.title}
                    </div>

                    {ev.summary && (
                      <p
                        className="muted-text"
                        style={{ fontSize: 12, margin: "0 0 8px", lineHeight: 1.5 }}
                      >
                        {ev.summary}
                      </p>
                    )}

                    {ev.route && (
                      <Link
                        href={ev.route}
                        className="secondary-btn"
                        style={{
                          fontSize: 11,
                          padding: "3px 10px",
                          textDecoration: "none",
                          display: "inline-flex",
                        }}
                      >
                        {t("pcpOpenSource")}
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {hasMore && (
            <div style={{ marginTop: 14, paddingLeft: 40 }}>
              <button
                type="button"
                className="secondary-btn"
                style={{ fontSize: 12 }}
                onClick={() => setShowAll(true)}
              >
                {t("pcpShowMoreEvents")} ({filtered.length - TIMELINE_PAGE_SIZE} more)
              </button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ── Recent source records card ────────────────────────────────────────────────

function RecentRecordsCard({
  docs,
  patientId,
}: {
  docs: PCPDoc[];
  patientId: number;
}) {
  const { t } = useLanguage();
  const shown = docs.slice(0, 5);

  return (
    <Card>
      <CardTitle
        title={t("pcpRecentRecords")}
        action={
          <Link
            href={`/patients/${patientId}`}
            className="secondary-btn"
            style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none" }}
          >
            {t("pcpViewAllDocuments")} →
          </Link>
        }
      />

      {shown.length === 0 ? (
        <EmptyState text={t("pcpNoRecentRecords")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {shown.map((doc) => (
            <div
              key={doc.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 12px",
                borderRadius: 10,
                border: "1px solid var(--border)",
                background: "var(--panel-2)",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 13,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {doc.report_name || doc.lab_name || doc.filename}
                </div>
                <div className="muted-text" style={{ fontSize: 11 }}>
                  {sectionLabel(doc.section)} · {formatDate(doc.test_date)}
                  {doc.is_verified ? " · Verified" : ""}
                </div>
              </div>
              <Link
                href={`/documents/${doc.id}`}
                className="secondary-btn"
                style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none", flexShrink: 0 }}
              >
                {t("pcpOpenDocument")}
              </Link>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Medications card ──────────────────────────────────────────────────────────

function MedicationsCard({
  medications,
  patientId,
}: {
  medications: Medication[];
  patientId: number;
}) {
  const { t } = useLanguage();
  const active = medications.filter((m) => m.status === "active");
  const other = medications.filter((m) => m.status !== "active");
  const ordered = [...active, ...other];
  const shown = ordered.slice(0, 4);

  return (
    <Card style={{ marginBottom: 12 }}>
      <CardTitle
        title={t("pcpViewMedications")}
        subtitle="Patient-entered medication records."
        action={
          <Link
            href={`/patients/${patientId}/medications/list`}
            className="secondary-btn"
            style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none" }}
          >
            {t("pcpViewAllMedications")}
          </Link>
        }
      />

      {shown.length === 0 ? (
        <EmptyState text={t("pcpNoMedications")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {shown.map((m) => (
            <div
              key={m.id}
              style={{
                padding: "8px 12px",
                borderRadius: 10,
                border: "1px solid var(--border)",
                background: "var(--panel-2)",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 800,
                    fontSize: 13,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {m.name}
                </div>
                <div
                  className="muted-text"
                  style={{
                    fontSize: 11,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {[m.dose_strength, m.frequency, m.route_form].filter(Boolean).join(" · ") || "—"}
                </div>
              </div>
              <Pill
                label={m.status}
                color={m.status === "active" ? "var(--success-text)" : "var(--muted)"}
                bg={m.status === "active" ? "var(--success-bg)" : "var(--panel-2)"}
              />
            </div>
          ))}
        </div>
      )}

      {medications.length > 4 && (
        <div className="muted-text" style={{ fontSize: 11, marginTop: 8 }}>
          +{medications.length - 4} more ·{" "}
          <Link
            href={`/patients/${patientId}/medications/list`}
            style={{ color: "var(--primary)", textDecoration: "none", fontWeight: 700 }}
          >
            {t("pcpViewAllMedications")}
          </Link>
        </div>
      )}
    </Card>
  );
}

// ── Latest labs card ──────────────────────────────────────────────────────────

function LatestLabsCard({ labs }: { labs: PCPSummary["latest_labs"] }) {
  const { t } = useLanguage();

  if (!labs || labs.labs.length === 0) {
    return (
      <Card style={{ marginBottom: 12 }}>
        <CardTitle title={t("pcpLatestLabs")} />
        <EmptyState text={t("pcpNoLabs")} />
      </Card>
    );
  }

  const shown = labs.labs.slice(0, 8);
  const hasFlag = shown.some((l) => flagIsOutOfRange(l.flag));

  return (
    <Card style={{ marginBottom: 12 }}>
      <CardTitle
        title={t("pcpLatestLabs")}
        subtitle={`${labs.lab_name || "Source document"} · ${formatDate(labs.test_date)}`}
        action={
          <Link
            href={`/documents/${labs.document_id}`}
            className="secondary-btn"
            style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none" }}
          >
            {t("pcpOpenLabPanel")}
          </Link>
        }
      />

      {hasFlag && (
        <div
          className="muted-text"
          style={{
            fontSize: 11,
            padding: "5px 10px",
            borderRadius: 8,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            marginBottom: 10,
          }}
        >
          {t("pcpOutOfRange")} · {t("pcpRefRangeSource")}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 6,
        }}
      >
        {shown.map((lab, i) => {
          const oor = flagIsOutOfRange(lab.flag);
          return (
            <div
              key={i}
              style={{
                padding: "7px 10px",
                borderRadius: 9,
                border: `1px solid ${oor ? "color-mix(in srgb, var(--danger-text) 25%, transparent)" : "var(--border)"}`,
                background: oor
                  ? "color-mix(in srgb, var(--danger-bg) 40%, var(--panel-2))"
                  : "var(--panel-2)",
              }}
            >
              <div className="muted-text" style={{ fontSize: 10, marginBottom: 1 }}>
                {lab.name || "—"}
              </div>
              <div
                style={{
                  fontWeight: 900,
                  fontSize: 14,
                  color: flagColor(lab.flag),
                  lineHeight: 1.2,
                }}
              >
                {lab.value ?? "—"}{" "}
                <span style={{ fontWeight: 400, fontSize: 10, color: "var(--muted)" }}>
                  {lab.unit ?? ""}
                </span>
              </div>
              {lab.reference_range && (
                <div className="muted-text" style={{ fontSize: 9, marginTop: 2 }}>
                  {lab.reference_range}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {labs.labs.length > 8 && (
        <div className="muted-text" style={{ fontSize: 11, marginTop: 8 }}>
          +{labs.labs.length - 8} {t("pcpMoreInSource")} ·{" "}
          <Link
            href={`/documents/${labs.document_id}`}
            style={{ color: "var(--primary)", textDecoration: "none", fontWeight: 700 }}
          >
            {t("pcpOpenLabPanel")}
          </Link>
        </div>
      )}
    </Card>
  );
}

// ── Notes card ────────────────────────────────────────────────────────────────

function NotesCard({
  notes,
  patientId,
}: {
  notes: NotePreview[];
  patientId: number;
}) {
  const { t } = useLanguage();
  const shown = notes.slice(0, 3);

  return (
    <Card style={{ marginBottom: 12 }}>
      <CardTitle
        title={t("pcpNotes")}
        action={
          <Link
            href={`/patients/${patientId}/notes/new`}
            className="secondary-btn"
            style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none" }}
          >
            + {t("pcpAddNote")}
          </Link>
        }
      />

      {shown.length === 0 ? (
        <EmptyState text={t("pcpNoNotes")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {shown.map((n) => (
            <div
              key={n.id}
              style={{
                padding: "9px 12px",
                borderRadius: 10,
                border: "1px solid var(--border)",
                background: "var(--panel-2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 13,
                    flex: 1,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {n.report_name || n.filename}
                </div>
                <div className="muted-text" style={{ fontSize: 10, flexShrink: 0 }}>
                  {formatDate(n.created_at)}
                </div>
              </div>
              {n.note_preview && (
                <p
                  className="muted-text"
                  style={{
                    fontSize: 11,
                    margin: "0 0 6px",
                    lineHeight: 1.5,
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  } as React.CSSProperties}
                >
                  {n.note_preview}
                </p>
              )}
              <Link
                href={`/documents/${n.id}`}
                className="secondary-btn"
                style={{ fontSize: 10, padding: "3px 9px", textDecoration: "none" }}
              >
                {t("pcpOpenNote")}
              </Link>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Care context card ─────────────────────────────────────────────────────────

function CareContextCard({ summary }: { summary: PCPSummary }) {
  const { t } = useLanguage();
  const p = summary.patient;

  const careCtx = summary.care_context;
  const contextColor =
    careCtx === "active_admission"
      ? "var(--danger-text)"
      : careCtx === "past_admission"
      ? "var(--warn-text)"
      : "var(--success-text)";
  const contextBg =
    careCtx === "active_admission"
      ? "var(--danger-bg)"
      : careCtx === "past_admission"
      ? "var(--warn-bg)"
      : "var(--success-bg)";

  return (
    <Card>
      <CardTitle title={t("pcpCareContext")} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 12px",
            borderRadius: 10,
            background: contextBg,
            border: `1px solid ${contextColor}33`,
          }}
        >
          <span className="muted-text" style={{ fontSize: 12 }}>
            {t("pcpCareContext")}
          </span>
          <span style={{ fontWeight: 800, fontSize: 12, color: contextColor }}>
            {summary.care_context_label}
          </span>
        </div>

        {p.date_of_birth && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "7px 12px",
              borderRadius: 10,
              background: "var(--panel-2)",
              border: "1px solid var(--border)",
            }}
          >
            <span className="muted-text" style={{ fontSize: 12 }}>Date of birth</span>
            <span style={{ fontWeight: 700, fontSize: 12 }}>{p.date_of_birth}</span>
          </div>
        )}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "7px 12px",
            borderRadius: 10,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
          }}
        >
          <span className="muted-text" style={{ fontSize: 12 }}>Access status</span>
          <Pill label={t("pcpActiveAccess")} color="var(--success-text)" bg="var(--success-bg)" />
        </div>

        {p.bragi_code && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "7px 12px",
              borderRadius: 10,
              background: "var(--panel-2)",
              border: "1px solid var(--border)",
            }}
          >
            <span className="muted-text" style={{ fontSize: 12 }}>Bragi code</span>
            <span
              style={{
                fontWeight: 700,
                fontSize: 12,
                fontFamily: "monospace",
                color: "var(--primary)",
              }}
            >
              {p.bragi_code}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}

// ── Patient profile (dashboard layout) ───────────────────────────────────────

function PCPPatientProfile({
  patientId,
  summary,
  accessOk,
}: {
  patientId: number;
  summary: PCPSummary | null;
  accessOk: boolean;
}) {
  const { t } = useLanguage();

  if (!accessOk) {
    return (
      <Card>
        <div style={{ textAlign: "center", padding: "28px 0" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔒</div>
          <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 8 }}>
            {t("pcpAccessRevoked")}
          </div>
          <p className="muted-text" style={{ fontSize: 13 }}>
            This patient&apos;s access is no longer active.
          </p>
        </div>
      </Card>
    );
  }

  if (!summary) {
    return (
      <div className="muted-text" style={{ padding: "40px 0", textAlign: "center" }}>
        Loading patient data…
      </div>
    );
  }

  return (
    <div>
      {/* Hero card — full width */}
      <PatientHeroCard summary={summary} patientId={patientId} />

      {/* Main dashboard grid: 60% left / 40% right */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)",
          gap: 14,
          alignItems: "start",
        }}
      >
        {/* Left column: Timeline + Recent Records */}
        <div>
          <TimelineCard events={summary.pcp_timeline ?? []} patientId={patientId} />
          <RecentRecordsCard docs={summary.recent_documents} patientId={patientId} />
        </div>

        {/* Right column: Medications + Labs + Notes + Care Context */}
        <div>
          <MedicationsCard medications={summary.medications} patientId={patientId} />
          <LatestLabsCard labs={summary.latest_labs} />
          <NotesCard notes={summary.recent_notes} patientId={patientId} />
          <CareContextCard summary={summary} />
        </div>
      </div>

      {/* Bottom CTA */}
      <div
        className="soft-card"
        style={{
          marginTop: 14,
          padding: "14px 20px",
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span className="muted-text" style={{ fontSize: 13, flex: 1 }}>
          {t("pcpOpenFullChart")} · {t("pcpLongitudinalRecord")}
        </span>
        <Link
          href={`/patients/${patientId}`}
          className="secondary-btn"
          style={{ fontSize: 13, textDecoration: "none" }}
        >
          {t("pcpOpenFullChart")} →
        </Link>
        <Link
          href={`/patients/${patientId}/timeline`}
          className="secondary-btn"
          style={{ fontSize: 13, textDecoration: "none" }}
        >
          {t("pcpOpenFullTimeline")} →
        </Link>
        <Link
          href={`/patients/${patientId}/medications/list`}
          className="secondary-btn"
          style={{ fontSize: 13, textDecoration: "none" }}
        >
          {t("pcpViewAllMedications")} →
        </Link>
      </div>
    </div>
  );
}

// ── Main workspace page ───────────────────────────────────────────────────────

export default function PCPWorkspacePage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loadingAuth, setLoadingAuth] = useState(true);
  const [approvedPatients, setApprovedPatients] = useState<PCPPatient[]>([]);
  const [openTabs, setOpenTabs] = useState<PCPTab[]>([]);
  const [activeId, setActiveIdState] = useState<number | null>(null);

  const [summaryCache, setSummaryCache] = useState<
    Record<number, PCPSummary | null | "revoked">
  >({});
  const [loadingCache, setLoadingCache] = useState<Record<number, boolean>>({});
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [maxTabsWarning, setMaxTabsWarning] = useState(false);

  const summaryRef = useRef(summaryCache);
  summaryRef.current = summaryCache;

  function setActiveId(id: number | null) {
    setActiveIdState(id);
    saveActiveToStorage(id);
  }

  useEffect(() => {
    async function init() {
      try {
        const meRes = await api.get<CurrentUser>("/auth/me");
        const u = meRes.data;

        if (u.role !== "doctor" && u.role !== "admin") {
          router.replace("/my-patients");
          return;
        }

        setUser(u);

        if (u.role === "admin" || u.doctor_type === "pcp") {
          const patientsRes = await api.get<PCPPatient[]>("/pcp/patients");
          setApprovedPatients(patientsRes.data);

          const savedTabs = loadTabsFromStorage();
          const savedActive = loadActiveFromStorage();

          const validIds = new Set(patientsRes.data.map((p) => p.id));
          const validTabs = savedTabs.filter((tab) => validIds.has(tab.patientId));
          setOpenTabs(validTabs);
          saveTabsToStorage(validTabs);

          const restoredActive = validTabs.some((tab) => tab.patientId === savedActive)
            ? savedActive
            : validTabs.length > 0
            ? validTabs[0].patientId
            : null;
          setActiveIdState(restoredActive);
        }
      } catch {
        router.replace("/my-patients");
      } finally {
        setLoadingAuth(false);
      }
    }
    init();
  }, [router]);

  const loadSummary = useCallback((patientId: number) => {
    if (summaryRef.current[patientId] !== undefined) return;
    setLoadingCache((prev) => ({ ...prev, [patientId]: true }));
    api
      .get<PCPSummary>(`/pcp/patients/${patientId}/summary`)
      .then((res) => setSummaryCache((prev) => ({ ...prev, [patientId]: res.data })))
      .catch((err) => {
        const status = err?.response?.status;
        setSummaryCache((prev) => ({
          ...prev,
          [patientId]: status === 403 ? "revoked" : null,
        }));
      })
      .finally(() =>
        setLoadingCache((prev) => ({ ...prev, [patientId]: false }))
      );
  }, []);

  useEffect(() => {
    if (activeId !== null && !showAddPanel) loadSummary(activeId);
  }, [activeId, showAddPanel, loadSummary]);

  function openPatient(p: PCPPatient) {
    const existing = openTabs.find((tab) => tab.patientId === p.id);
    if (existing) {
      setActiveId(p.id);
      setShowAddPanel(false);
      return;
    }
    if (openTabs.length >= MAX_TABS) {
      setMaxTabsWarning(true);
      return;
    }
    setMaxTabsWarning(false);
    const newTab: PCPTab = { patientId: p.id, patientName: p.full_name };
    const newTabs = [...openTabs, newTab];
    setOpenTabs(newTabs);
    saveTabsToStorage(newTabs);
    setActiveId(p.id);
    setShowAddPanel(false);
  }

  function closeTab(patientId: number) {
    const newTabs = openTabs.filter((tab) => tab.patientId !== patientId);
    setOpenTabs(newTabs);
    saveTabsToStorage(newTabs);
    setMaxTabsWarning(false);
    if (activeId === patientId) {
      const next = newTabs.length > 0 ? newTabs[newTabs.length - 1].patientId : null;
      setActiveId(next);
    }
  }

  function handleSelectTab(patientId: number) {
    setActiveId(patientId);
    setShowAddPanel(false);
  }

  function handleAddClick() {
    if (openTabs.length >= MAX_TABS) {
      setMaxTabsWarning(true);
    } else {
      setMaxTabsWarning(false);
      setShowAddPanel(true);
      setActiveId(null);
    }
  }

  if (loadingAuth) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading…</p>
      </main>
    );
  }

  if (!user) return null;

  if (user.role === "doctor" && user.doctor_type !== "pcp") {
    return <PCPBlockedPage user={user} />;
  }

  const activeSummaryRaw = activeId !== null ? summaryCache[activeId] : undefined;
  const activeSummary =
    activeSummaryRaw === "revoked" ? null : (activeSummaryRaw ?? null);
  const activeAccessOk = activeSummaryRaw !== "revoked";
  const activeLoading = activeId !== null && loadingCache[activeId];

  const showProfile = activeId !== null && !showAddPanel;
  const showPanel = showAddPanel || (openTabs.length === 0 && !showProfile);

  return (
    <AppShell user={user} title={t("pcpWorkspace")} subtitle={t("pcpWorkspaceSubtitle")}>
      {maxTabsWarning && (
        <div
          style={{
            padding: "10px 16px",
            marginBottom: 14,
            borderRadius: 10,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            fontSize: 13,
          }}
        >
          <strong>{t("pcpMaxTabsReached")}</strong> {t("pcpMaxTabsBody")}
        </div>
      )}

      <PCPTabBar
        tabs={openTabs}
        activeId={activeId}
        onSelect={handleSelectTab}
        onClose={closeTab}
        onAdd={handleAddClick}
        maxReached={openTabs.length >= MAX_TABS}
        patients={approvedPatients}
      />

      {showPanel && (
        <PCPPatientSelectPanel
          patients={approvedPatients}
          openTabs={openTabs}
          onOpen={openPatient}
          maxReached={openTabs.length >= MAX_TABS}
        />
      )}

      {showProfile &&
        (activeLoading ? (
          <div className="muted-text" style={{ padding: "40px 0", textAlign: "center" }}>
            Loading patient data…
          </div>
        ) : (
          <PCPPatientProfile
            patientId={activeId!}
            summary={activeSummary}
            accessOk={activeAccessOk}
          />
        ))}
    </AppShell>
  );
}
