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

type TimelineEvent = {
  id: number;
  title: string;
  event_type: string;
  status: string;
  admitted_at: string;
  discharged_at: string | null;
  hospital_name: string | null;
  department: string | null;
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
  timeline_preview: TimelineEvent[];
  recent_notes: NotePreview[];
};

type PCPTab = {
  patientId: number;
  patientName: string;
};

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

function ageSex(p: { age?: string | null; sex?: string | null }) {
  return [p.age, p.sex].filter(Boolean).join(" · ") || null;
}

function sectionLabel(section: string) {
  const map: Record<string, string> = {
    bloodwork: "Lab panel",
    discharge_summary: "Discharge summary",
    scans: "Imaging report",
    notes: "Clinical note",
    medications: "Medication document",
    hospitalizations: "Hospitalization record",
    other: "Source record",
  };
  return map[section] ?? "Source record";
}

function flagColor(flag: string | null): string {
  if (!flag) return "var(--muted)";
  const f = flag.toLowerCase();
  if (f === "h" || f === "high" || f === "l" || f === "low" || f === "a" || f === "abnormal") {
    return "var(--danger-text)";
  }
  return "var(--muted)";
}

// ── Small reusable card pieces ────────────────────────────────────────────────

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="soft-card" style={{ padding: "16px 20px", ...style }}>
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 900,
        letterSpacing: "0.07em",
        textTransform: "uppercase",
        color: "var(--muted)",
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <p className="muted-text" style={{ fontSize: 13, margin: 0 }}>{text}</p>;
}

function StatusPill({ label, color }: { label: string; color?: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 800,
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        color: color ?? "var(--muted)",
      }}
    >
      {label}
    </span>
  );
}

// ── Blocked page ──────────────────────────────────────────────────────────────

function PCPBlockedPage({ user }: { user: CurrentUser }) {
  const { t } = useLanguage();
  return (
    <AppShell user={user} title={t("pcpWorkspace")}>
      <div
        style={{
          maxWidth: 480,
          margin: "60px auto",
          textAlign: "center",
          padding: "0 24px",
        }}
      >
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
}: {
  tabs: PCPTab[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onClose: (id: number) => void;
  onAdd: () => void;
  maxReached: boolean;
}) {
  const { t } = useLanguage();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        gap: 4,
        overflowX: "auto",
        padding: "0 0 1px",
        borderBottom: "2px solid var(--border)",
        marginBottom: 20,
        scrollbarWidth: "none",
        msOverflowStyle: "none",
      } as React.CSSProperties}
    >
      {tabs.map((tab) => {
        const active = tab.patientId === activeId;
        return (
          <div
            key={tab.patientId}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "9px 14px 9px 16px",
              borderRadius: "10px 10px 0 0",
              border: "1px solid var(--border)",
              borderBottom: active ? "2px solid var(--primary)" : "1px solid transparent",
              background: active
                ? "color-mix(in srgb, var(--primary) 8%, var(--panel))"
                : "var(--panel-2)",
              cursor: "pointer",
              flexShrink: 0,
              maxWidth: 200,
              transition: "background 0.12s, border-color 0.12s",
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
                fontWeight: active ? 800 : 600,
                fontSize: 13,
                color: active ? "var(--primary)" : "var(--foreground)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 140,
              }}
            >
              {tab.patientName}
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onClose(tab.patientId); }}
              title={t("pcpCloseTab")}
              style={{
                background: "none",
                border: "none",
                padding: "0 2px",
                cursor: "pointer",
                color: "var(--muted)",
                fontSize: 15,
                lineHeight: 1,
                flexShrink: 0,
                borderRadius: 4,
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
        title={maxReached ? `${t("pcpMaxTabsReached")} ${t("pcpMaxTabsBody")}` : t("pcpAddPatient")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "9px 14px",
          borderRadius: "10px 10px 0 0",
          border: "1px dashed var(--border)",
          background: "transparent",
          cursor: maxReached ? "not-allowed" : "pointer",
          flexShrink: 0,
          fontWeight: 700,
          fontSize: 13,
          color: maxReached ? "var(--muted)" : "var(--primary)",
          opacity: maxReached ? 0.5 : 1,
          whiteSpace: "nowrap",
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

  const filtered = patients.filter((p) =>
    p.full_name.toLowerCase().includes(query.toLowerCase()) ||
    (p.patient_identifier ?? "").toLowerCase().includes(query.toLowerCase())
  );

  const openIds = new Set(openTabs.map((t) => t.patientId));

  return (
    <div style={{ maxWidth: 640 }}>
      <Card>
        <SectionLabel>{t("pcpCurrentApprovedPatients")}</SectionLabel>

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

        {patients.length === 0 && (
          <EmptyRow text={t("pcpNoPatients")} />
        )}

        {patients.length > 0 && filtered.length === 0 && (
          <EmptyRow text="No matching patients." />
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
                  background: isOpen ? "color-mix(in srgb, var(--primary) 5%, var(--panel-2))" : "var(--panel-2)",
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
                    fontWeight: 950,
                    fontSize: 14,
                    flexShrink: 0,
                  }}
                >
                  {p.full_name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 800, fontSize: 14 }}>{p.full_name}</div>
                  {ageSex(p) && (
                    <div className="muted-text" style={{ fontSize: 12 }}>{ageSex(p)}</div>
                  )}
                </div>
                <button
                  type="button"
                  className={isOpen ? "secondary-btn" : "primary-btn"}
                  style={{ fontSize: 12, padding: "6px 14px", flexShrink: 0 }}
                  onClick={() => onOpen(p)}
                  disabled={maxReached && !isOpen}
                >
                  {isOpen ? "Switch to tab" : t("pcpAddPatient")}
                </button>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
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

// ── PCP patient profile sections ──────────────────────────────────────────────

function OverviewSection({ summary, patientId }: { summary: PCPSummary; patientId: number }) {
  const { t } = useLanguage();
  const p = summary.patient;
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: 999,
            background: "var(--primary)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 950,
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          {p.full_name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 900, fontSize: 18, marginBottom: 4 }}>{p.full_name}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {ageSex(p) && <StatusPill label={ageSex(p)!} />}
            <StatusPill label={t("pcpActiveAccess")} color="var(--success-text)" />
            <StatusPill label={summary.care_context_label} />
          </div>
          {p.patient_identifier && (
            <div className="muted-text" style={{ fontSize: 12 }}>
              ID: {p.patient_identifier}
              {p.bragi_code ? ` · Bragi: ${p.bragi_code}` : ""}
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginTop: 18,
          paddingTop: 14,
          borderTop: "1px solid var(--border)",
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
          href={`/patients/${patientId}/medications/list`}
          className="secondary-btn"
          style={{ fontSize: 13, textDecoration: "none" }}
        >
          {t("pcpViewMedications")}
        </Link>
        <Link
          href={`/patients/${patientId}/timeline`}
          className="secondary-btn"
          style={{ fontSize: 13, textDecoration: "none" }}
        >
          {t("pcpViewTimeline")}
        </Link>
      </div>
    </Card>
  );
}

function MedicationsSection({ medications, patientId }: { medications: Medication[]; patientId: number }) {
  const { t } = useLanguage();
  const active = medications.filter((m) => m.status === "active");
  const other = medications.filter((m) => m.status !== "active");
  const shown = [...active, ...other].slice(0, 8);

  return (
    <Card>
      <SectionLabel>{t("pcpViewMedications")}</SectionLabel>
      {shown.length === 0 && <EmptyRow text={t("pcpNoMedications")} />}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {shown.map((m) => (
          <div
            key={m.id}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 800, fontSize: 13 }}>{m.name}</div>
              <div className="muted-text" style={{ fontSize: 12 }}>
                {[m.dose_strength, m.frequency, m.route_form].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>
            <StatusPill
              label={m.status}
              color={m.status === "active" ? "var(--success-text)" : "var(--muted)"}
            />
          </div>
        ))}
      </div>
      {medications.length > 8 && (
        <div style={{ marginTop: 10 }}>
          <Link
            href={`/patients/${patientId}/medications/list`}
            className="secondary-btn"
            style={{ fontSize: 12, textDecoration: "none" }}
          >
            View all {medications.length} medications
          </Link>
        </div>
      )}
    </Card>
  );
}

function LatestLabsSection({ labs }: { labs: PCPSummary["latest_labs"] }) {
  const { t } = useLanguage();
  if (!labs || labs.labs.length === 0) {
    return (
      <Card>
        <SectionLabel>{t("pcpLatestLabs")}</SectionLabel>
        <EmptyRow text={t("pcpNoLabs")} />
      </Card>
    );
  }

  const shown = labs.labs.slice(0, 12);
  const hasFlag = shown.some((l) => l.flag && l.flag.toLowerCase() !== "n");

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: "0.07em", textTransform: "uppercase", color: "var(--muted)" }}>
          {t("pcpLatestLabs")}
        </div>
        <div className="muted-text" style={{ fontSize: 11 }}>
          {labs.lab_name || "Source document"} · {formatDate(labs.test_date)}
        </div>
      </div>
      {hasFlag && (
        <div
          className="muted-text"
          style={{
            fontSize: 11,
            padding: "6px 10px",
            borderRadius: 8,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            marginBottom: 10,
          }}
        >
          Out-of-range value present · Reference range from source document · Source-linked
        </div>
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
          gap: 8,
        }}
      >
        {shown.map((lab, i) => (
          <div
            key={i}
            style={{
              padding: "8px 10px",
              borderRadius: 10,
              border: `1px solid ${lab.flag && lab.flag.toLowerCase() !== "n" ? "color-mix(in srgb, var(--danger-text) 30%, transparent)" : "var(--border)"}`,
              background: lab.flag && lab.flag.toLowerCase() !== "n" ? "color-mix(in srgb, var(--danger-bg) 30%, var(--panel-2))" : "var(--panel-2)",
            }}
          >
            <div className="muted-text" style={{ fontSize: 11, marginBottom: 2 }}>{lab.name || "—"}</div>
            <div style={{ fontWeight: 900, fontSize: 15, color: flagColor(lab.flag) }}>
              {lab.value ?? "—"} <span style={{ fontWeight: 400, fontSize: 11 }}>{lab.unit ?? ""}</span>
            </div>
            {lab.reference_range && (
              <div className="muted-text" style={{ fontSize: 10, marginTop: 2 }}>{lab.reference_range}</div>
            )}
          </div>
        ))}
      </div>
      {labs.labs.length > 12 && (
        <div className="muted-text" style={{ fontSize: 12, marginTop: 10 }}>
          +{labs.labs.length - 12} more in source document
        </div>
      )}
      <div style={{ marginTop: 12 }}>
        <Link
          href={`/documents/${labs.document_id}`}
          className="secondary-btn"
          style={{ fontSize: 12, textDecoration: "none" }}
        >
          {t("pcpOpenDocument")}
        </Link>
      </div>
    </Card>
  );
}

function RecentRecordsSection({ docs, patientId }: { docs: PCPDoc[]; patientId: number }) {
  const { t } = useLanguage();
  return (
    <Card>
      <SectionLabel>{t("pcpRecentRecords")}</SectionLabel>
      {docs.length === 0 && <EmptyRow text={t("pcpNoRecentRecords")} />}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {docs.map((doc) => (
          <div
            key={doc.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>
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
              style={{ fontSize: 12, padding: "5px 12px", textDecoration: "none", flexShrink: 0 }}
            >
              {t("pcpOpenDocument")}
            </Link>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14 }}>
        <Link
          href={`/patients/${patientId}`}
          className="secondary-btn"
          style={{ fontSize: 12, textDecoration: "none" }}
        >
          {t("pcpOpenFullChart")} →
        </Link>
      </div>
    </Card>
  );
}

function TimelinePreviewSection({ events, patientId }: { events: TimelineEvent[]; patientId: number }) {
  const { t } = useLanguage();
  return (
    <Card>
      <SectionLabel>{t("pcpTimelinePreview")}</SectionLabel>
      {events.length === 0 && <EmptyRow text={t("pcpNoTimeline")} />}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {events.map((e) => (
          <div
            key={e.id}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
              <div style={{ fontWeight: 700, fontSize: 13, flex: 1, minWidth: 0 }}>{e.title}</div>
              <StatusPill
                label={e.status}
                color={e.status === "active" ? "var(--success-text)" : "var(--muted)"}
              />
            </div>
            <div className="muted-text" style={{ fontSize: 12 }}>
              {formatDate(e.admitted_at)}
              {e.discharged_at ? ` → ${formatDate(e.discharged_at)}` : ""}
              {e.hospital_name ? ` · ${e.hospital_name}` : ""}
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14 }}>
        <Link
          href={`/patients/${patientId}/timeline`}
          className="secondary-btn"
          style={{ fontSize: 12, textDecoration: "none" }}
        >
          {t("pcpOpenFullTimeline")} →
        </Link>
      </div>
    </Card>
  );
}

function NotesSection({ notes, patientId }: { notes: NotePreview[]; patientId: number }) {
  const { t } = useLanguage();
  return (
    <Card>
      <SectionLabel>{t("pcpNotes")}</SectionLabel>
      {notes.length === 0 && <EmptyRow text={t("pcpNoNotes")} />}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {notes.map((n) => (
          <div
            key={n.id}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <div style={{ fontWeight: 700, fontSize: 13, flex: 1, minWidth: 0 }}>
                {n.report_name || n.filename}
              </div>
              <div className="muted-text" style={{ fontSize: 11, flexShrink: 0 }}>{formatDate(n.created_at)}</div>
            </div>
            {n.note_preview && (
              <p className="muted-text" style={{ fontSize: 12, margin: 0, lineHeight: 1.5 }}>
                {n.note_preview}{n.note_preview.length >= 200 ? "…" : ""}
              </p>
            )}
            <div style={{ marginTop: 8 }}>
              <Link
                href={`/documents/${n.id}`}
                className="secondary-btn"
                style={{ fontSize: 12, padding: "4px 10px", textDecoration: "none" }}
              >
                {t("pcpOpenNote")}
              </Link>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14 }}>
        <Link
          href={`/patients/${patientId}/notes/new`}
          className="secondary-btn"
          style={{ fontSize: 12, textDecoration: "none" }}
        >
          + {t("pcpAddNote")}
        </Link>
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
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔒</div>
          <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 8 }}>{t("pcpAccessRevoked")}</div>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <OverviewSection summary={summary} patientId={patientId} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
          gap: 14,
        }}
      >
        <MedicationsSection medications={summary.medications} patientId={patientId} />
        <LatestLabsSection labs={summary.latest_labs} />
      </div>

      <RecentRecordsSection docs={summary.recent_documents} patientId={patientId} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
          gap: 14,
        }}
      >
        <TimelinePreviewSection events={summary.timeline_preview} patientId={patientId} />
        <NotesSection notes={summary.recent_notes} patientId={patientId} />
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

  // summary cache: patientId → summary | null | "revoked"
  const [summaryCache, setSummaryCache] = useState<Record<number, PCPSummary | null | "revoked">>({});
  const [loadingCache, setLoadingCache] = useState<Record<number, boolean>>({});

  const [showAddPanel, setShowAddPanel] = useState(false);
  const [maxTabsWarning, setMaxTabsWarning] = useState(false);

  const summaryRef = useRef(summaryCache);
  summaryRef.current = summaryCache;

  function setActiveId(id: number | null) {
    setActiveIdState(id);
    saveActiveToStorage(id);
  }

  // Load user + approved patients
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

        // Only fetch PCP patients if PCP or admin
        if (u.role === "admin" || u.doctor_type === "pcp") {
          const patientsRes = await api.get<PCPPatient[]>("/pcp/patients");
          setApprovedPatients(patientsRes.data);

          // Restore tabs from localStorage and validate access
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

  const loadSummary = useCallback(
    (patientId: number) => {
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
        .finally(() => setLoadingCache((prev) => ({ ...prev, [patientId]: false })));
    },
    []
  );

  useEffect(() => {
    if (activeId !== null && !showAddPanel) loadSummary(activeId);
  }, [activeId, showAddPanel, loadSummary]);

  function openPatient(p: PCPPatient) {
    // If already open, switch to it
    const existing = openTabs.find((t) => t.patientId === p.id);
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
    const newTabs = openTabs.filter((t) => t.patientId !== patientId);
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

  // Non-PCP doctors see blocked page
  if (user.role === "doctor" && user.doctor_type !== "pcp") {
    return <PCPBlockedPage user={user} />;
  }

  const activeSummaryRaw = activeId !== null ? summaryCache[activeId] : undefined;
  const activeSummary = activeSummaryRaw === "revoked" ? null : (activeSummaryRaw ?? null);
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
      />

      {showPanel && (
        <PCPPatientSelectPanel
          patients={approvedPatients}
          openTabs={openTabs}
          onOpen={openPatient}
          maxReached={openTabs.length >= MAX_TABS}
        />
      )}

      {showProfile && (
        activeLoading ? (
          <div className="muted-text" style={{ padding: "40px 0", textAlign: "center" }}>
            Loading patient data…
          </div>
        ) : (
          <PCPPatientProfile
            patientId={activeId!}
            summary={activeSummary}
            accessOk={activeAccessOk}
          />
        )
      )}
    </AppShell>
  );
}
