"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  EmptyState as SharedEmptyState,
  LabValue,
  Status,
  Toolbar,
} from "@/components/ui";
import {
  IconChevronRight,
  IconClose,
  IconExternal,
  IconPlus,
  IconSearch,
  IconTimeline,
  IconUpload,
} from "@/components/ui/icon";

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

/**
 * PCP workspace primitives.
 *
 * These four helpers give the whole 1,900-line workspace its visual
 * character, so they were re-pointed at the Bragi design system rather than
 * restyling every call site: `Card` is a hairline surface instead of a
 * 20px-padded rounded panel, `CardTitle` matches SectionHead, `Pill` is a
 * bounded chip instead of a coloured lozenge, and the empty state is the
 * shared one. Every card in the workspace picked up the new language for
 * free.
 */

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
    <section
      className={`b-surface ${className ?? ""}`}
      style={{ minWidth: 0, padding: "var(--s3) var(--s4) var(--s4)", ...style }}
    >
      {children}
    </section>
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
      className="b-section-head"
      style={{ padding: 0, marginBottom: "var(--s3)", minHeight: 0 }}
    >
      <div style={{ minWidth: 0 }}>
        <h2 className="b-section-title">{title}</h2>
        {subtitle ? (
          <p className="b-meta" style={{ marginTop: 2 }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      {action ? <div style={{ flexShrink: 0, display: "flex", gap: "var(--s2)" }}>{action}</div> : null}
    </div>
  );
}

/** Body padding for card content that is not a flush list or table. */
function CardBody({
  children,
  flush,
  style,
}: {
  children: React.ReactNode;
  flush?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={flush ? "b-section-body b-section-body-flush" : "b-section-body"}
      style={style}
    >
      {children}
    </div>
  );
}

function Pill({
  label,
  color,
  bg,
}: {
  label: string;
  /** Retained for call-site compatibility; mapped onto a chip tone. */
  color?: string;
  bg?: string;
}) {
  const tone =
    color?.includes("danger") || color?.includes("sev-critical")
      ? "b-chip-danger"
      : color?.includes("warn")
      ? "b-chip-warn"
      : color?.includes("ok") || color?.includes("success")
      ? "b-chip-ok"
      : color?.includes("primary")
      ? "b-chip-brand"
      : "";
  void bg;

  return <span className={`b-chip ${tone}`}>{label}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <SharedEmptyState title={text} />;
}

// ── Blocked page ──────────────────────────────────────────────────────────────

function PCPBlockedPage({ user }: { user: CurrentUser }) {
  const { t } = useLanguage();

  return (
    <AppShell user={user} title={t("pcpWorkspace")}>
      <section className="b-surface">
        <SharedEmptyState
          title={t("pcpWorkspace")}
          description={t("pcpBlockedBody")}
          actions={
            <Link href="/my-patients" className="b-btn b-btn-secondary">
              {t("myCurrentPatients")}
            </Link>
          }
        />
      </section>
    </AppShell>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

/**
 * Patient tab bar - the heart of the PCP workspace.
 *
 * Rebuilt as a real tab strip sharing one baseline, the way a browser or an
 * IDE does it, instead of eight free-floating 12px-radius boxes each with its
 * own border and violet glow. The active tab connects to the content below via
 * a 2px underline, so "which patient am I reading?" is unambiguous even with
 * eight open.
 */
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
      className="b-tabs"
      role="group"
      aria-label={t("pcpWorkspace")}
      style={{ gap: 2, marginBottom: "var(--s5)" }}
    >
      {tabs.map((tab) => {
        const active = tab.patientId === activeId;
        const patient = patientMap.get(tab.patientId);
        const meta = patient ? ageSex(patient) : null;

        return (
          <div
            key={tab.patientId}
            className="b-tab"
            data-active={active ? "true" : undefined}
            style={{ height: 44, paddingRight: 2, gap: 4, maxWidth: 220 }}
          >
            <button
              type="button"
              aria-current={active ? "true" : undefined}
              onClick={() => onSelect(tab.patientId)}
              style={{
                display: "grid",
                gap: 0,
                border: 0,
                background: "transparent",
                color: "inherit",
                font: "inherit",
                textAlign: "left",
                cursor: "pointer",
                minWidth: 0,
                padding: 0,
              }}
            >
              <span
                style={{
                  fontWeight: active ? 600 : 500,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 160,
                  display: "block",
                }}
              >
                {tab.patientName}
              </span>
              {meta ? (
                <span
                  style={{
                    fontSize: "var(--fs-micro)",
                    color: "var(--muted)",
                    whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {meta}
                </span>
              ) : null}
            </button>

            <button
              type="button"
              className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
              onClick={(event) => {
                event.stopPropagation();
                onClose(tab.patientId);
              }}
              aria-label={`${t("pcpCloseTab")}: ${tab.patientName}`}
              title={t("pcpCloseTab")}
              style={{ width: 20, height: 20, flexShrink: 0 }}
            >
              <IconClose size={12} />
            </button>
          </div>
        );
      })}

      <button
        type="button"
        onClick={onAdd}
        disabled={maxReached}
        className="b-btn b-btn-ghost b-btn-sm"
        title={maxReached ? `${t("pcpMaxTabsReached")} ${t("pcpMaxTabsBody")}` : t("pcpAddPatient")}
        style={{ alignSelf: "center", marginLeft: "var(--s2)", flexShrink: 0 }}
      >
        <IconPlus size={13} />
        {t("pcpAddPatient")}
      </button>
    </div>
  );
}

// ── Patient selector panel ────────────────────────────────────────────────────

/**
 * Approved-patient picker.
 *
 * Was a stack of 12px-radius tinted boxes with a filled violet "Add patient"
 * button on every row - eight competing primary actions. Now a searchable
 * list where the whole row opens the patient and the trailing state says
 * whether it is already open.
 */
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
    <div style={{ maxWidth: 680 }}>
      <section className="b-surface">
        <CardTitle
          title={t("pcpCurrentApprovedPatients")}
          action={
            <Link href="/patients/search" className="b-btn b-btn-secondary b-btn-sm">
              <IconSearch size={13} />
              {t("pcpSearchMorePatients")}
            </Link>
          }
        />

        {maxReached ? (
          <div className="b-notice b-notice-warn" style={{ margin: "0 var(--s4) var(--s3)" }}>
            <span>
              <strong style={{ fontWeight: 600 }}>{t("pcpMaxTabsReached")}</strong>{" "}
              {t("pcpMaxTabsBody")}
            </span>
          </div>
        ) : null}

        <Toolbar
          search={query}
          onSearch={setQuery}
          searchPlaceholder={`${t("pcpSearchApprovedPatients")}…`}
          count={filtered.length}
          countLabel={t("navPatients").toLowerCase()}
        />

        {patients.length === 0 ? (
          <SharedEmptyState title={t("pcpNoPatients")} />
        ) : filtered.length === 0 ? (
          <SharedEmptyState title={t("navNoResults")} />
        ) : (
          <div className="b-list">
            {filtered.map((p) => {
              const isOpen = openIds.has(p.id);
              const disabled = maxReached && !isOpen;

              return (
                <button
                  key={p.id}
                  type="button"
                  className="b-list-row"
                  onClick={() => onOpen(p)}
                  disabled={disabled}
                  style={disabled ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
                >
                  <span className="b-avatar" aria-hidden="true">
                    {initials(p.full_name)}
                  </span>
                  <span className="b-list-main">
                    <span className="b-list-title">{p.full_name}</span>
                    {ageSex(p) ? <span className="b-list-sub">{ageSex(p)}</span> : null}
                  </span>
                  <span className="b-list-trail">
                    {isOpen ? (
                      <Status tone="info">{t("pcpSwitchToTab")}</Status>
                    ) : (
                      <IconChevronRight size={14} className="b-list-chevron" />
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

// ── Patient hero card ─────────────────────────────────────────────────────────

/**
 * Patient context bar.
 *
 * Was a 56px-avatar hero card with a violet gradient, a left accent stripe,
 * a drop shadow, five coloured pills and four side-by-side buttons - one of
 * which was a filled primary. It cost roughly 130px before any clinical
 * content, on a page whose whole point is dense longitudinal review.
 *
 * Now: the same 52px context bar the doctor chart uses, so a clinician moving
 * between the two workspaces sees one product. Identity and care context stay
 * visible; the secondary actions moved behind an overflow menu, leaving one
 * clear primary ("open the full chart").
 */
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

  const contextTone =
    careCtx === "active_admission" ? "ok" : careCtx === "past_admission" ? "muted" : "info";

  const meta = [
    ageSex(p),
    p.patient_identifier ? `ID ${p.patient_identifier}` : null,
    p.bragi_code ? `Bragi ${p.bragi_code}` : null,
  ].filter(Boolean) as string[];

  return (
    <div
      className="b-surface"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--s3)",
        padding: "var(--s2) var(--s4)",
        minHeight: 52,
        marginBottom: "var(--s4)",
        flexWrap: "wrap",
      }}
    >
      <span className="b-avatar" aria-hidden="true">
        {initials(p.full_name)}
      </span>

      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="b-ctx-name">{p.full_name}</div>
        <div className="b-ctx-meta">
          {meta.map((entry, index) => (
            <span key={entry} style={{ display: "inline-flex", gap: 6 }}>
              {index > 0 ? <span className="b-ctx-dot">·</span> : null}
              {entry}
            </span>
          ))}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--s2)",
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        <Status tone={contextTone}>{summary.care_context_label}</Status>
        <Status tone="ok">{t("pcpActiveAccess")}</Status>

        <Link href={`/patients/${patientId}`} className="b-btn b-btn-primary b-btn-sm">
          {t("pcpOpenFullChart")}
          <IconExternal size={12} />
        </Link>

        <Link
          href={`/patients/${patientId}/notes/new`}
          className="b-btn b-btn-secondary b-btn-sm"
          title={t("pcpAddNote")}
        >
          <IconPlus size={13} />
          {t("pcpAddNote")}
        </Link>

        <Link
          href={`/patients/${patientId}/upload`}
          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
          title={t("pcpUploadDocument")}
          aria-label={t("pcpUploadDocument")}
        >
          <IconUpload size={14} />
        </Link>

        <Link
          href={`/patients/${patientId}/timeline`}
          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
          title={t("pcpViewTimeline")}
          aria-label={t("pcpViewTimeline")}
        >
          <IconTimeline size={14} />
        </Link>
      </div>
    </div>
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

      {/* Filter chips: the shared square-cornered filter control, not
          full-radius lozenges with their own colour scheme. */}
      <div className="b-filters" style={{ marginBottom: "var(--s3)" }}>
        {FILTERS.map((f) => {
          const count =
            f.key === "all"
              ? events.length
              : events.filter((e) => filterMatchesEvent(f.key, e)).length;
          if (count === 0 && f.key !== "all") return null;

          return (
            <button
              key={f.key}
              type="button"
              className="b-filter"
              aria-pressed={activeFilter === f.key}
              onClick={() => {
                setActiveFilter(f.key);
                setShowAll(false);
              }}
            >
              {t(f.labelKey)}
              {count > 0 ? <span className="b-filter-count">{count}</span> : null}
            </button>
          );
        })}
      </div>

      {/* Timeline list */}
      {filtered.length === 0 ? (
        <EmptyState text={t("pcpNoTimelineEvents")} />
      ) : (
        <div
          className="b-timeline"
          style={{ marginLeft: "calc(var(--s4) * -1)", marginRight: "calc(var(--s4) * -1)" }}
        >
          {shown.map((ev) => {
            const cfg = getEventConfig(ev.event_type);

            return (
              <Link
                key={ev.id}
                href={ev.route || `/patients/${patientId}`}
                className="b-tl-event"
                style={{ textDecoration: "none" }}
              >
                <span className="b-tl-date">{formatDateShort(ev.date)}</span>

                <span className="b-tl-spine" aria-hidden="true">
                  <span
                    className="b-tl-node"
                    style={{ background: cfg.dot, borderColor: cfg.dot }}
                  />
                </span>

                <span className="b-tl-main">
                  <span className="b-tl-title">{ev.title}</span>
                  <span className="b-tl-sub">
                    <span style={{ color: "var(--text-2)" }}>
                      {getEventTypeLabel(ev.event_type, t)}
                    </span>
                    {ev.is_source_linked ? ` · ${t("pcpSourceLinkedEvent")}` : ""}
                    {ev.summary ? ` · ${ev.summary}` : ""}
                  </span>
                </span>

                <span className="b-tl-trail">
                  <IconChevronRight size={13} className="b-list-chevron" />
                </span>
              </Link>
            );
          })}

          {hasMore ? (
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
                onClick={() => setShowAll(true)}
              >
                {t("pcpShowMoreEvents")} ({filtered.length - TIMELINE_PAGE_SIZE})
              </button>
            </div>
          ) : null}
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
        <div
          className="b-list"
          style={{ marginLeft: "calc(var(--s4) * -1)", marginRight: "calc(var(--s4) * -1)" }}
        >
          {shown.map((doc) => (
            <Link
              key={doc.id}
              href={`/documents/${doc.id}`}
              className="b-list-row"
              style={{ textDecoration: "none" }}
            >
              <span className="b-list-main">
                <span className="b-list-title">
                  {doc.report_name || doc.lab_name || doc.filename}
                </span>
                <span className="b-list-sub">
                  {sectionLabel(doc.section)} · {formatDate(doc.test_date)}
                </span>
              </span>
              <span className="b-list-trail">
                {doc.is_verified ? (
                  <Status tone="ok">Verified</Status>
                ) : (
                  <Status tone="muted">Unverified</Status>
                )}
                <IconChevronRight size={13} className="b-list-chevron" />
              </span>
            </Link>
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
        title={t("navMedications")}
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
                    fontWeight: 600,
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

      {hasFlag ? (
        <p className="b-meta" style={{ marginBottom: "var(--s2)" }}>
          {t("pcpOutOfRange")} · {t("pcpRefRangeSource")}
        </p>
      ) : null}

      {/* A two-column key/value grid rather than eight tinted mini-cards.
          The analyte name recedes, the figure carries the weight, and the
          reference range sits under it in muted tabular figures. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
          gap: 1,
          background: "var(--border)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-md)",
          overflow: "hidden",
        }}
      >
        {shown.map((lab, index) => (
          <div key={index} style={{ background: "var(--surface)", padding: "7px 10px" }}>
            <div className="b-cell-sub" title={lab.name || undefined}>
              {lab.name || "—"}
            </div>
            <div style={{ fontSize: "var(--fs-body)", marginTop: 1 }}>
              <LabValue value={lab.value ?? "—"} unit={lab.unit} flag={lab.flag} />
            </div>
            {lab.reference_range ? (
              <div className="b-range">{lab.reference_range}</div>
            ) : null}
          </div>
        ))}
      </div>

      {labs.labs.length > 8 ? (
        <p className="b-meta" style={{ marginTop: "var(--s2)" }}>
          +{labs.labs.length - 8} {t("pcpMoreInSource")} ·{" "}
          <Link href={`/documents/${labs.document_id}`} style={{ color: "var(--primary)", fontWeight: 500 }}>
            {t("pcpOpenLabPanel")}
          </Link>
        </p>
      ) : null}
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
        <div
          className="b-list"
          style={{ marginLeft: "calc(var(--s4) * -1)", marginRight: "calc(var(--s4) * -1)" }}
        >
          {shown.map((n) => (
            <Link
              key={n.id}
              href={`/documents/${n.id}`}
              className="b-list-row"
              style={{ textDecoration: "none", alignItems: "flex-start" }}
            >
              <span className="b-list-main">
                <span className="b-list-title">{n.report_name || n.filename}</span>
                {n.note_preview ? (
                  <span
                    className="b-list-sub"
                    style={{
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      whiteSpace: "normal",
                    } as React.CSSProperties}
                  >
                    {n.note_preview}
                  </span>
                ) : null}
              </span>
              <span className="b-list-trail">
                <span className="b-range">{formatDate(n.created_at)}</span>
                <IconChevronRight size={13} className="b-list-chevron" />
              </span>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Care context card ─────────────────────────────────────────────────────────

/**
 * Care context.
 *
 * Was four rounded, tinted, bordered rows - one of them a green-on-green
 * pill inside a green box. Now a plain key/value block: the label recedes,
 * the value is the content, and only the access state carries a status dot.
 */
function CareContextCard({ summary }: { summary: PCPSummary }) {
  const { t } = useLanguage();
  const p = summary.patient;
  const careCtx = summary.care_context;

  const contextTone =
    careCtx === "active_admission" ? "ok" : careCtx === "past_admission" ? "muted" : "muted";

  return (
    <Card>
      <CardTitle title={t("pcpCareContext")} />
      <div className="b-kv">
        <div className="b-kv-key">{t("pcpCareContext")}</div>
        <div className="b-kv-value">
          <Status tone={contextTone}>{summary.care_context_label}</Status>
        </div>

        {p.date_of_birth ? (
          <>
            <div className="b-kv-key">Date of birth</div>
            <div className="b-kv-value num">{p.date_of_birth}</div>
          </>
        ) : null}

        <div className="b-kv-key">Access status</div>
        <div className="b-kv-value">
          <Status tone="ok">{t("pcpActiveAccess")}</Status>
        </div>

        {p.bragi_code ? (
          <>
            <div className="b-kv-key">Bragi code</div>
            <div className="b-kv-value num">{p.bragi_code}</div>
          </>
        ) : null}

        {p.patient_identifier ? (
          <>
            <div className="b-kv-key">Patient ID</div>
            <div className="b-kv-value num">{p.patient_identifier}</div>
          </>
        ) : null}
      </div>
    </Card>
  );
}

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
          <div style={{ fontSize: 19, marginBottom: 12 }}>🔒</div>
          <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 8 }}>
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
