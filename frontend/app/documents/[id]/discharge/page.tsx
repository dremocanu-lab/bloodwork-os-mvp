"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import OriginalLayoutViewer from "@/components/original-layout-viewer";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { formatPdfLikeDischargeText } from "@/lib/discharge-epicriza-formatter";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type UploadedBy = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type CarePartnerLink = {
  care_partner_user_id: number;
  care_partner_name: string;
  care_partner_email: string;
  linked_at: string;
};

type DocumentShare = {
  care_partner_user_id: number;
  care_partner_name: string;
  care_partner_email: string;
  shared_at: string;
};

type AuditLog = {
  action: string;
  actor?: string | null;
  timestamp: string;
  details?: string | null;
};

type LayoutBlock = {
  id: string;
  type: "paragraph" | "line" | string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

type LayoutPage = {
  page_number: number;
  width: number;
  height: number;
  paragraph_blocks?: LayoutBlock[];
  line_blocks?: LayoutBlock[];
};

type OriginalLayout = {
  provider?: string;
  plain_text?: string;
  pages?: LayoutPage[];
};

type DischargeSection = {
  key: string;
  title: string;
  original_titles?: string[];
  body: string;
  formatted_body?: string | null;
  formatting_method?: string | null;
  formatting_confidence?: number | null;
  confidence?: number;
};

type DischargePayload = {
  document_type?: string;
  sections?: DischargeSection[];
};

type DocumentResponse = {
  document_id: number;
  patient_id: number;
  filename: string;
  content_type?: string | null;
  section: string;
  uploaded_by_user_id?: number | null;
  uploaded_by?: UploadedBy | null;
  parsed_data: {
    patient_name?: string | null;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
    lab_name?: string | null;
    referring_doctor?: string | null;
    report_name?: string | null;
    report_type?: string | null;
    source_language?: string | null;
    collected_on?: string | null;
    reported_on?: string | null;
    registered_on?: string | null;
    generated_on?: string | null;
    created_at?: string | null;
    is_verified?: boolean;
    verified_by?: string | null;
    verified_at?: string | null;
    last_edited_at?: string | null;
    note_body?: string | null;
    original_layout?: OriginalLayout | null;
    audit_logs?: AuditLog[];
  };
};

type NavigationSection = DischargeSection & {
  synthetic?: boolean;
};

const READER_FONT =
  '"Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

const FONT_SIZE_MIN = 11;
const FONT_SIZE_MAX = 22;
const FONT_SIZE_DEFAULT = 14;

// ─── Utilities ────────────────────────────────────────────────────────────────

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin { to { transform: rotate(360deg); } }
        .bloodwork-spinner {
          width: ${size}px; height: ${size}px;
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

function displayValue(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function parseDischargePayload(noteBody?: string | null): DischargePayload | null {
  if (!noteBody) return null;
  try {
    const parsed = JSON.parse(noteBody);
    if (parsed && typeof parsed === "object" && parsed.document_type === "discharge_summary" && Array.isArray(parsed.sections)) {
      return parsed;
    }
    return null;
  } catch { return null; }
}

function getSectionBody(section?: Partial<DischargeSection> | null) {
  const raw = section?.formatted_body || section?.body || "";
  return formatPdfLikeDischargeText(raw);
}

function sectionColor(key?: string): string {
  if (key === "overview") return "#6d5dfc";
  if (key === "full_summary") return "#6d5dfc";
  if (key === "administrative_information") return "#64748b";
  if (key === "diagnoses") return "#f59e0b";
  if (key === "epicriza") return "#8b5cf6";
  if (key === "pre_epicriza_summary") return "#a78bfa";
  if (key === "investigations") return "#06b6d4";
  if (key === "laboratory_normal") return "#10b981";
  if (key === "laboratory_abnormal") return "#ef4444";
  if (key === "treatment_in_hospital") return "#3b82f6";
  if (key === "recommended_treatment") return "#6d5dfc";
  if (key === "recommendations") return "#14b8a6";
  if (key === "discharge_status") return "#94a3b8";
  if (key === "audit") return "#94a3b8";
  return "#94a3b8";
}

function copyText(text: string) {
  if (!text) return;
  void navigator.clipboard?.writeText(text);
}

function parseAdminLines(body: string): Array<{ label: string; value: string }> {
  const results: Array<{ label: string; value: string }> = [];
  const seen = new Set<string>();
  for (const rawLine of body.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const colonIndex = line.indexOf(":");
    if (colonIndex < 2 || colonIndex > 60) continue;
    const label = line.slice(0, colonIndex).trim();
    const value = line.slice(colonIndex + 1).trim();
    if (!value || label.length < 2) continue;
    const key = label.toLowerCase().replace(/\s+/g, " ");
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ label, value });
  }
  return results;
}

function mergeFirstPageSections(rawSections: DischargeSection[]) {
  return rawSections;
}

// ─── UI Components ────────────────────────────────────────────────────────────

function MetaField({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--muted)", lineHeight: 1 }}>
        {label}
      </span>
      <span style={{ fontSize: 14, fontWeight: 950, letterSpacing: "-0.02em", lineHeight: 1.2 }}>
        {displayValue(value)}
      </span>
    </div>
  );
}

function SegmentedControl({
  options,
  active,
  onChange,
}: {
  options: { value: string; label: string }[];
  active: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: "inline-flex", border: "1px solid var(--border)", borderRadius: 999, background: "var(--panel-2)", padding: 3, gap: 2 }}>
      {options.map((opt) => {
        const isActive = active === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            style={{
              border: "none",
              borderRadius: 999,
              padding: "7px 14px",
              fontSize: 12,
              fontWeight: 950,
              letterSpacing: "-0.01em",
              background: isActive ? "var(--panel)" : "transparent",
              color: isActive ? "var(--foreground)" : "var(--muted)",
              cursor: "pointer",
              boxShadow: isActive ? "0 1px 4px rgba(0,0,0,0.09)" : "none",
              transition: "background 160ms ease, color 160ms ease, box-shadow 160ms ease",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function StatusDot({ verified, t }: { verified: boolean; t: (k: string) => string }) {
  const color = verified ? "var(--success-text)" : "var(--warn-text)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: color, flexShrink: 0 }} />
      <span style={{ fontSize: 12, fontWeight: 900, color, letterSpacing: "-0.01em" }}>
        {verified ? t("verified") : t("unverified")}
      </span>
    </div>
  );
}

function FontSizeControl({ fontSize, onChange }: { fontSize: number; onChange: (next: number) => void }) {
  const { t } = useLanguage();
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 2, border: "1px solid var(--border)", borderRadius: 999, background: "var(--panel-2)", padding: "3px 4px" }}>
      <button
        type="button"
        onClick={() => onChange(Math.max(FONT_SIZE_MIN, fontSize - 1))}
        disabled={fontSize <= FONT_SIZE_MIN}
        style={{ width: 28, height: 28, borderRadius: 999, border: "none", background: "transparent", color: fontSize <= FONT_SIZE_MIN ? "var(--muted)" : "var(--foreground)", fontSize: 16, fontWeight: 700, cursor: fontSize <= FONT_SIZE_MIN ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", lineHeight: 1 }}
        title={t("smallerText")}
      >−</button>
      <span style={{ fontSize: 11, fontWeight: 950, color: "var(--muted)", minWidth: 26, textAlign: "center" }}>{fontSize}</span>
      <button
        type="button"
        onClick={() => onChange(Math.min(FONT_SIZE_MAX, fontSize + 1))}
        disabled={fontSize >= FONT_SIZE_MAX}
        style={{ width: 28, height: 28, borderRadius: 999, border: "none", background: "transparent", color: fontSize >= FONT_SIZE_MAX ? "var(--muted)" : "var(--foreground)", fontSize: 16, fontWeight: 700, cursor: fontSize >= FONT_SIZE_MAX ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", lineHeight: 1 }}
        title={t("largerText")}
      >+</button>
    </div>
  );
}

function escapeRegex(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function SectionTextPanel({
  section,
  text,
  fontSize,
  onCopy,
}: {
  section: NavigationSection;
  text?: string | null;
  fontSize: number;
  onCopy?: () => void;
}) {
  const { t } = useLanguage();
  const rawText = text || "";
  const [query, setQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const matchCount = useMemo(() => {
    if (!query.trim() || !rawText) return 0;
    return (rawText.match(new RegExp(escapeRegex(query), "gi")) || []).length;
  }, [rawText, query]);

  useEffect(() => { setMatchIndex(0); }, [query]);

  useEffect(() => {
    if (!query.trim() || !contentRef.current || matchCount === 0) return;
    const marks = contentRef.current.querySelectorAll("[data-match]");
    const target = marks[matchIndex];
    if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [matchIndex, query, matchCount]);

  // Ctrl+F / Cmd+F intercept
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const prevMatch = useCallback(() => {
    setMatchIndex((i) => (i - 1 + matchCount) % matchCount);
  }, [matchCount]);

  const nextMatch = useCallback(() => {
    setMatchIndex((i) => (i + 1) % matchCount);
  }, [matchCount]);

  const renderedText = useMemo(() => {
    if (!query.trim() || !rawText) return rawText || t("noTextExtracted");
    const escaped = escapeRegex(query);
    const parts = rawText.split(new RegExp(`(${escaped})`, "gi"));
    let counter = 0;
    return parts.map((part, i) => {
      if (part.toLowerCase() === query.toLowerCase()) {
        const idx = counter++;
        const isCurrent = idx === matchIndex;
        return (
          <mark
            key={i}
            data-match="true"
            style={{
              background: isCurrent
                ? "color-mix(in srgb, var(--primary) 55%, transparent)"
                : "color-mix(in srgb, var(--primary) 22%, transparent)",
              color: "inherit",
              borderRadius: 3,
              padding: "0 1px",
              outline: isCurrent ? "1.5px solid color-mix(in srgb, var(--primary) 70%, transparent)" : "none",
            }}
          >
            {part}
          </mark>
        );
      }
      return part;
    });
  }, [rawText, query, matchIndex, t]);

  return (
    <div style={{ minHeight: 0, height: "100%", display: "grid", gridTemplateRows: "auto auto minmax(0, 1fr)", gap: 12, overflow: "hidden" }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div>
          <div className="section-title">{section.title}</div>
          {section.original_titles?.length ? (
            <div className="muted-text" style={{ marginTop: 5, fontSize: 11, fontWeight: 900, letterSpacing: "0.02em" }}>
              {t("originalHeadingLabel")} {section.original_titles.join(" · ")}
            </div>
          ) : null}
          {section.formatting_method && section.formatting_method !== "raw_ocr" ? (
            <div className="muted-text" style={{ marginTop: 4, fontSize: 11, fontWeight: 800 }}>
              {t("aiLayoutFormatted")}
              {section.formatting_confidence !== null && section.formatting_confidence !== undefined
                ? ` · ${Math.round(section.formatting_confidence * 100)}%`
                : ""}
            </div>
          ) : null}
        </div>
        {onCopy && (
          <button className="secondary-btn" onClick={onCopy} style={{ flexShrink: 0 }}>
            {t("copySection")}
          </button>
        )}
      </div>

      {/* Search bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            padding: "6px 12px",
            borderRadius: 999,
            border: "1px solid var(--border)",
            background: "var(--panel-2)",
            flex: "1 1 180px",
            maxWidth: 320,
          }}
        >
          <span style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1, flexShrink: 0 }}>⌕</span>
          <input
            ref={searchInputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.shiftKey ? prevMatch() : nextMatch();
              if (e.key === "Escape") setQuery("");
            }}
            placeholder={t("searchInSection") || "Search in section…"}
            style={{
              border: "none",
              background: "transparent",
              outline: "none",
              fontSize: 12,
              fontWeight: 800,
              color: "var(--foreground)",
              flex: 1,
              minWidth: 0,
            }}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              style={{ border: "none", background: "transparent", color: "var(--muted)", cursor: "pointer", fontSize: 14, lineHeight: 1, padding: 0, flexShrink: 0 }}
            >
              ×
            </button>
          )}
        </div>

        {query.trim() && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            <span style={{ fontSize: 11, fontWeight: 900, color: matchCount > 0 ? "var(--muted)" : "var(--danger-text)", whiteSpace: "nowrap" }}>
              {matchCount > 0 ? `${matchIndex + 1} / ${matchCount}` : t("noMatches") || "No matches"}
            </span>
            <button
              type="button"
              onClick={prevMatch}
              disabled={matchCount === 0}
              style={{ width: 28, height: 28, borderRadius: 999, border: "1px solid var(--border)", background: "var(--panel-2)", color: matchCount === 0 ? "var(--muted)" : "var(--foreground)", cursor: matchCount === 0 ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}
            >↑</button>
            <button
              type="button"
              onClick={nextMatch}
              disabled={matchCount === 0}
              style={{ width: 28, height: 28, borderRadius: 999, border: "1px solid var(--border)", background: "var(--panel-2)", color: matchCount === 0 ? "var(--muted)" : "var(--foreground)", cursor: matchCount === 0 ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}
            >↓</button>
          </div>
        )}
      </div>

      {/* Text content */}
      <div
        ref={contentRef}
        className="soft-card-tight"
        style={{ padding: 22, background: "var(--panel-2)", minHeight: 0, overflow: "auto", borderRadius: 20 }}
      >
        <pre
          style={{
            margin: 0,
            whiteSpace: "pre-wrap",
            fontFamily: READER_FONT,
            fontSize: fontSize,
            lineHeight: 1.7,
            fontWeight: 450,
            color: "var(--foreground)",
            tabSize: 4,
            overflowWrap: "break-word",
            wordBreak: "normal",
          }}
        >
          {renderedText}
        </pre>
      </div>
    </div>
  );
}

function AdminBoxesPanel({
  section,
  parsed,
  dischargePayload,
}: {
  section: NavigationSection;
  parsed: DocumentResponse["parsed_data"];
  dischargePayload: DischargePayload | null;
}) {
  const { t } = useLanguage();
  const payloadMeta = (dischargePayload as Record<string, unknown>) || {};

  const metaFields = [
    { label: t("patient"), value: parsed.patient_name },
    { label: t("cnp"), value: parsed.cnp },
    { label: t("dob"), value: parsed.date_of_birth },
    { label: t("age"), value: parsed.age },
    { label: t("sex"), value: parsed.sex },
    { label: t("hospital"), value: parsed.lab_name ?? (payloadMeta.hospital_name as string | null) },
    { label: t("doctor"), value: parsed.referring_doctor },
    { label: t("admittedCapital"), value: parsed.collected_on },
    { label: t("discharged"), value: parsed.reported_on },
  ].filter((f): f is { label: string; value: string } => Boolean(f.value));

  const metaLabelKeys = new Set(metaFields.map((f) => f.label.toLowerCase()));
  const bodyFields = parseAdminLines(section.body || "").filter((f) => !metaLabelKeys.has(f.label.toLowerCase()));
  const allFields = [...metaFields, ...bodyFields];

  return (
    <div style={{ minHeight: 0, height: "100%", overflowY: "auto", paddingRight: 8 }}>
      <div style={{ marginBottom: 18 }}>
        <div className="section-title">{section.title}</div>
        {section.original_titles?.length ? (
          <div className="muted-text" style={{ marginTop: 5, fontSize: 11, fontWeight: 900, letterSpacing: "0.02em" }}>
            {t("originalHeadingLabel")} {section.original_titles.join(" · ")}
          </div>
        ) : null}
      </div>
      <div
        className="soft-card-tight"
        style={{ padding: 24, background: "var(--panel-2)", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 22 }}
      >
        {allFields.map((field) => (
          <MetaField key={field.label} label={field.label} value={field.value} />
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DischargeStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentResponse | null>(null);
  const [activeSectionKey, setActiveSectionKey] = useState("full_summary");
  const [readerMode, setReaderMode] = useState<"structured" | "original">("structured");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [fontSize, setFontSize] = useState(FONT_SIZE_DEFAULT);
  const [loading, setLoading] = useState(true);
  const [openingOriginal, setOpeningOriginal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [error, setError] = useState("");

  const [carePartners, setCarePartners] = useState<CarePartnerLink[]>([]);
  const [documentShares, setDocumentShares] = useState<DocumentShare[]>([]);
  const [sharingId, setSharingId] = useState<number | null>(null);

  // Auto-collapse sidebar on mobile
  useEffect(() => {
    function onResize() {
      if (window.innerWidth < 900) setSidebarOpen(false);
      else setSidebarOpen(true);
    }
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  async function fetchData() {
    if (!documentId) throw new Error("Missing document id.");
    const meResponse = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(meResponse.data);
    const documentResponse = await api.get<DocumentResponse>(`/documents/${documentId}`);
    if (!documentResponse.data?.parsed_data) throw new Error("Document loaded, but parsed_data is missing.");
    const isDischarge =
      documentResponse.data.section === "discharge_summary" ||
      documentResponse.data.parsed_data?.report_type === "Discharge summary" ||
      documentResponse.data.parsed_data?.report_type === "discharge_summary";
    if (!isDischarge) { router.replace(`/documents/${documentId}`); return; }
    setDocumentData(documentResponse.data);

    if (meResponse.data.role === "patient") {
      const [cpResponse, sharesResponse] = await Promise.all([
        api.get<CarePartnerLink[]>("/my/care-partners"),
        api.get<DocumentShare[]>(`/documents/${documentId}/shares`),
      ]);
      setCarePartners(cpResponse.data || []);
      setDocumentShares(sharesResponse.data || []);
    }
  }

  useEffect(() => {
    async function init() {
      try {
        setLoading(true);
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, t("couldNotLoadDischargeSummary")));
      } finally {
        setLoading(false);
      }
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const parsed = documentData?.parsed_data;
  const dischargePayload = parseDischargePayload(parsed?.note_body);

  const sections = useMemo(() => mergeFirstPageSections(dischargePayload?.sections || []), [dischargePayload?.sections]);

  const fullSummaryText = useMemo(() => {
    return sections.map((s) => `${s.title}\n\n${getSectionBody(s)}`).join("\n\n---\n\n");
  }, [sections]);

  const navigationSections = useMemo<NavigationSection[]>(() => {
    return [
      { key: "overview", title: t("overviewSection"), body: t("overviewSectionDesc"), synthetic: true },
      { key: "full_summary", title: t("fullDischargeSummary"), body: fullSummaryText || t("allSectionsDescription"), formatted_body: fullSummaryText || "", synthetic: true },
      ...sections.map((s) => ({ ...s, synthetic: false })),
      { key: "audit", title: t("auditTrail"), body: t("auditTrailDesc"), synthetic: true },
    ];
  }, [sections, fullSummaryText, t]);

  const activeSection = navigationSections.find((s) => s.key === activeSectionKey) || navigationSections[0];

  const canDelete =
    Boolean(currentUser && documentData && currentUser.id === documentData.uploaded_by_user_id) ||
    currentUser?.role === "admin";

  async function toggleShare(cpUserId: number) {
    if (!documentData) return;
    const isShared = documentShares.some((s) => s.care_partner_user_id === cpUserId);
    try {
      setSharingId(cpUserId);
      setError("");
      if (isShared) {
        await api.delete(`/documents/${documentData.document_id}/share/${cpUserId}`);
        setDocumentShares((prev) => prev.filter((s) => s.care_partner_user_id !== cpUserId));
      } else {
        await api.post(`/documents/${documentData.document_id}/share`, {
          care_partner_user_id: cpUserId,
        });
        const sharesResponse = await api.get<DocumentShare[]>(`/documents/${documentData.document_id}/shares`);
        setDocumentShares(sharesResponse.data || []);
      }
    } catch (err) {
      setError(getErrorMessage(err, "Could not update share."));
    } finally {
      setSharingId(null);
    }
  }

  async function openOriginal() {
    if (!documentData) return;
    try {
      setOpeningOriginal(true);
      setError("");
      const response = await api.get(`/documents/${documentData.document_id}/file`, { responseType: "blob" });
      const rawContentType = response.headers["content-type"];
      const contentType = typeof rawContentType === "string" ? rawContentType : documentData.content_type || "application/octet-stream";
      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);
      window.open(fileUrl, "_blank", "noopener,noreferrer");
      window.setTimeout(() => window.URL.revokeObjectURL(fileUrl), 60_000);
    } catch (err) {
      setError(getErrorMessage(err, t("failedOpenOriginal")));
    } finally {
      setOpeningOriginal(false);
    }
  }

  async function deleteDocument() {
    if (!documentData) return;
    try {
      setDeleting(true);
      setError("");
      await api.delete(`/documents/${documentData.document_id}`);
      if (currentUser?.role === "patient") { router.push("/my-records"); return; }
      if (documentData.patient_id) { router.push(`/patients/${documentData.patient_id}`); return; }
      router.push("/my-records");
    } catch (err) {
      setError(getErrorMessage(err, t("failedLoadRecord")));
      setConfirmDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">{t("loadingDischargeSummary")}</span>
        </div>
      </main>
    );
  }

  if (!currentUser || !documentData || !parsed) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, maxWidth: 620 }}>
          <div style={{ fontSize: 22, fontWeight: 950, marginBottom: 8 }}>{t("couldNotLoadDischargeSummary")}</div>
          <div className="muted-text" style={{ lineHeight: 1.6 }}>{t("dischargeSummaryBadFormat")}</div>
          {error ? (
            <div style={{ marginTop: 14, padding: 14, borderRadius: 16, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)", fontWeight: 800, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
              {error}
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            <button className="secondary-btn" onClick={() => router.push("/my-records")}>{t("backToMyRecords")}</button>
            <button className="secondary-btn" onClick={() => window.location.reload()}>{t("tryAgain")}</button>
          </div>
        </div>
      </main>
    );
  }

  const showStructured = readerMode === "structured";
  const gridColumns = !showStructured
    ? "minmax(0, 1fr)"
    : sidebarOpen
    ? "minmax(220px, 0.24fr) minmax(0, 1fr)"
    : "44px minmax(0, 1fr)";

  return (
    <AppShell
      user={currentUser}
      title={parsed.report_name || t("loadingDischargeSummary")}
      subtitle={`${valueOrDash(parsed.patient_name)} · CNP ${valueOrDash(parsed.cnp)} · ${parsed.is_verified ? t("verified") : t("unverified")}`}
      rightContent={
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center" }}>
          <button className="secondary-btn" onClick={openOriginal} disabled={openingOriginal}>
            {openingOriginal ? t("opening") : t("openOriginal")}
          </button>
          {canDelete && (
            <button
              onClick={() => setConfirmDeleteOpen(true)}
              style={{ border: "1px solid var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)", borderRadius: 14, padding: "11px 15px", fontWeight: 950, cursor: "pointer" }}
            >
              {t("delete")}
            </button>
          )}
          <button className="secondary-btn" onClick={() => router.back()}>{t("back")}</button>
        </div>
      }
    >
      {/* Delete confirm modal */}
      {confirmDeleteOpen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(15,23,42,0.42)", display: "grid", placeItems: "center", padding: 20, backdropFilter: "blur(10px)" }}>
          <div className="soft-card" style={{ width: "min(520px, 100%)", padding: 28, boxShadow: "0 30px 90px rgba(15,23,42,0.32)" }}>
            <div style={{ fontSize: 22, fontWeight: 950, letterSpacing: "-0.05em" }}>{t("deleteThisDischargeSummary")}</div>
            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.65 }}>{t("deleteDischargeDesc")}</div>
            <div className="soft-card-tight" style={{ marginTop: 18, padding: 16, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 950 }}>{parsed.report_name || documentData.filename}</div>
              <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>{t("uploadedBy")} {valueOrDash(documentData.uploaded_by?.full_name)}</div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
              <button className="secondary-btn" onClick={() => setConfirmDeleteOpen(false)} disabled={deleting}>{t("cancel")}</button>
              <button
                onClick={deleteDocument}
                disabled={deleting}
                style={{ border: "1px solid var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)", borderRadius: 14, padding: "11px 18px", fontWeight: 950, cursor: deleting ? "not-allowed" : "pointer" }}
              >
                {deleting ? t("deleting") : t("deleteSummary")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 14, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Toolbar */}
      <div
        className="soft-card-tight"
        style={{ padding: "10px 14px", marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center", overflowX: "auto" }}
      >
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexShrink: 0 }}>
          <SegmentedControl
            options={[
              { value: "structured", label: t("structuredReader") },
              { value: "original", label: t("originalLayoutLabel") },
            ]}
            active={readerMode}
            onChange={(v) => setReaderMode(v as "structured" | "original")}
          />
          <div style={{ width: 1, height: 18, background: "var(--border)", flexShrink: 0 }} />
          <StatusDot verified={Boolean(parsed.is_verified)} t={t} />
          <span style={{ fontSize: 12, fontWeight: 900, color: "var(--muted)", letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
            {sections.length} {t("sectionsSidebar").toLowerCase()}
          </span>
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", flexShrink: 0 }}>
          {readerMode === "structured" && (
            <>
              <FontSizeControl fontSize={fontSize} onChange={setFontSize} />
              <div style={{ width: 1, height: 18, background: "var(--border)", flexShrink: 0 }} />
            </>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--muted)" }}>{t("patient")}</span>
            <span style={{ fontSize: 13, fontWeight: 950, letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>{valueOrDash(parsed.patient_name)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--muted)" }}>{t("hospitalization")}</span>
            <span style={{ fontSize: 13, fontWeight: 950, letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>
              {valueOrDash(parsed.collected_on)} — {valueOrDash(parsed.reported_on)}
            </span>
          </div>
        </div>
      </div>

      {/* Main reader */}
      <div
        className="soft-card"
        style={{
          padding: 12,
          display: "grid",
          gridTemplateColumns: gridColumns,
          gap: 12,
          alignItems: "stretch",
          height: "calc(100vh - 182px)",
          minHeight: 400,
          overflow: "hidden",
          transition: "grid-template-columns 240ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        {/* Sidebar — both states always rendered, opacity-transitioned for smooth in/out */}
        {showStructured && (
          <div style={{ position: "relative", height: "100%", overflow: "hidden" }}>
            {/* Open state */}
            <aside
              style={{
                position: "absolute", inset: 0,
                height: "100%", overflowY: "auto",
                display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: 10,
                opacity: sidebarOpen ? 1 : 0,
                pointerEvents: sidebarOpen ? "auto" : "none",
                transition: "opacity 220ms ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "2px 2px 0 8px" }}>
                <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--muted)" }}>
                  {t("sectionsSidebar")}
                </span>
                <button
                  type="button"
                  onClick={() => setSidebarOpen(false)}
                  title={t("collapseSidebarLabel")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "4px 10px 4px 8px",
                    borderRadius: 999,
                    border: "1px solid var(--border)",
                    background: "var(--panel-2)",
                    color: "var(--muted)",
                    fontSize: 11,
                    fontWeight: 900,
                    letterSpacing: "0.02em",
                    cursor: "pointer",
                    transition: "color 160ms ease, background 160ms ease",
                  }}
                >
                  <span style={{ fontSize: 14, lineHeight: 1 }}>‹</span>
                  <span>Hide</span>
                </button>
              </div>

              <div style={{ display: "grid", gap: 3, alignContent: "start", overflowY: "auto" }}>
                {navigationSections.map((section) => {
                  const active = activeSectionKey === section.key;
                  const color = sectionColor(section.key);
                  return (
                    <button
                      key={section.key}
                      type="button"
                      onClick={() => setActiveSectionKey(section.key)}
                      style={{
                        border: "none",
                        background: active ? "color-mix(in srgb, var(--primary) 10%, var(--panel-2))" : "transparent",
                        borderRadius: 10,
                        padding: "10px 10px",
                        textAlign: "left",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        width: "100%",
                        transition: "background 140ms ease",
                      }}
                    >
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: 999,
                          background: color,
                          opacity: active ? 1 : 0.38,
                          flexShrink: 0,
                          transition: "opacity 140ms ease",
                          boxShadow: active ? `0 0 7px ${color}80` : "none",
                        }}
                      />
                      <span
                        style={{
                          fontSize: 12.5,
                          fontWeight: active ? 950 : 800,
                          color: active ? "var(--foreground)" : "var(--muted)",
                          lineHeight: 1.35,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          transition: "color 140ms ease, font-weight 140ms ease",
                          flex: 1,
                          minWidth: 0,
                        }}
                      >
                        {section.title}
                      </span>
                    </button>
                  );
                })}
              </div>
            </aside>

            {/* Collapsed strip */}
            <div
              style={{
                position: "absolute", inset: 0,
                display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 6,
                opacity: sidebarOpen ? 0 : 1,
                pointerEvents: sidebarOpen ? "none" : "auto",
                transition: "opacity 220ms ease",
              }}
            >
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                title={t("openSectionsLabel")}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  padding: "8px 6px",
                  borderRadius: 999,
                  border: "1px solid var(--border)",
                  background: "var(--panel-2)",
                  color: "var(--muted)",
                  cursor: "pointer",
                  transition: "color 160ms ease, background 160ms ease",
                  position: "relative",
                  zIndex: 1,
                }}
              >
                <span style={{ fontSize: 16, lineHeight: 1 }}>›</span>
              </button>

              {/* Gradient below the button hinting at hidden sections */}
              <div
                style={{
                  position: "absolute",
                  left: 0, right: 0,
                  top: 50, bottom: 0,
                  background: "linear-gradient(to bottom, transparent, color-mix(in srgb, var(--primary) 55%, transparent) 35%, color-mix(in srgb, var(--primary) 45%, transparent))",
                  pointerEvents: "none",
                  borderRadius: "0 0 6px 6px",
                }}
              />
            </div>
          </div>
        )}

        {/* Reader panel */}
        <section
          className="soft-card-tight"
          style={{ padding: 24, background: "var(--panel)", borderRadius: 20, height: "100%", minHeight: 0, display: "grid", gridTemplateRows: "minmax(0, 1fr)", overflow: "hidden", position: "relative" }}
        >
          {readerMode === "original" ? (
            <OriginalLayoutViewer layout={parsed.original_layout} mode="lines" />
          ) : (
            <>
              {activeSectionKey === "overview" && (
                <div style={{ minHeight: 0, height: "100%", overflowY: "auto", paddingRight: 8 }}>
                  <div className="section-title" style={{ marginBottom: 20 }}>{t("overviewSection")}</div>
                  <div className="soft-card-tight" style={{ padding: 24, background: "var(--panel-2)", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(155px, 1fr))", gap: 24 }}>
                    <MetaField label={t("patient")} value={parsed.patient_name} />
                    <MetaField label={t("dob")} value={parsed.date_of_birth} />
                    <MetaField label={t("age")} value={parsed.age} />
                    <MetaField label={t("sex")} value={parsed.sex} />
                    <MetaField label={t("cnp")} value={parsed.cnp} />
                    <MetaField label={t("patientId")} value={parsed.patient_identifier} />
                    <MetaField label={t("admittedCapital")} value={parsed.collected_on} />
                    <MetaField label={t("discharged")} value={parsed.reported_on} />
                    <MetaField label={t("doctor")} value={parsed.referring_doctor} />
                    <MetaField label={t("language")} value={parsed.source_language} />
                  </div>
                </div>
              )}

              {activeSectionKey === "full_summary" && (
                <SectionTextPanel
                  section={{ key: "full_summary", title: t("fullDischargeSummary"), body: fullSummaryText, formatted_body: fullSummaryText }}
                  text={fullSummaryText}
                  fontSize={fontSize}
                  onCopy={() => copyText(fullSummaryText)}
                />
              )}

              {activeSectionKey !== "overview" &&
                activeSectionKey !== "full_summary" &&
                activeSectionKey !== "audit" &&
                (activeSection.key === "administrative_information" ? (
                  <AdminBoxesPanel section={activeSection} parsed={parsed} dischargePayload={dischargePayload} />
                ) : (
                  <SectionTextPanel
                    section={activeSection}
                    text={getSectionBody(activeSection)}
                    fontSize={fontSize}
                    onCopy={() => copyText(getSectionBody(activeSection))}
                  />
                ))}

              {activeSectionKey === "audit" && (
                <div style={{ minHeight: 0, height: "100%", display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: 16, overflow: "hidden" }}>
                  <div className="section-title">{t("auditTrail")}</div>
                  <div style={{ display: "grid", gap: 10, minHeight: 0, overflowY: "auto", paddingRight: 8, alignContent: "start" }}>
                    {(parsed.audit_logs || []).map((log, index) => (
                      <div key={`${log.action}-${log.timestamp}-${index}`} className="soft-card-tight" style={{ padding: 16 }}>
                        <div style={{ fontWeight: 950 }}>{log.action}</div>
                        <div className="muted-text" style={{ marginTop: 5, fontSize: 13 }}>{valueOrDash(log.actor)} · {formatDate(log.timestamp)}</div>
                        {log.details && <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.55 }}>{log.details}</div>}
                      </div>
                    ))}
                    {!parsed.audit_logs?.length && (
                      <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                        <div className="muted-text">{t("noAuditActivity")}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {currentUser?.role === "patient" && (
        <div style={{ padding: "0 0 24px" }}>
          <div className="soft-card" style={{ padding: 24 }}>
            <div style={{ marginBottom: 16 }}>
              <div className="section-title">{t("shareThisPage")}</div>
              <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
                {t("shareThisPageDesc")}
              </div>
            </div>

            {carePartners.length === 0 ? (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div className="muted-text">{t("noCarePartnersToShare")}</div>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {carePartners.map((cp) => {
                  const isShared = documentShares.some((s) => s.care_partner_user_id === cp.care_partner_user_id);
                  const isWorking = sharingId === cp.care_partner_user_id;
                  return (
                    <div
                      key={cp.care_partner_user_id}
                      className="soft-card-tight"
                      style={{
                        padding: "12px 16px",
                        display: "grid",
                        gridTemplateColumns: "minmax(0,1fr) auto",
                        gap: 12,
                        alignItems: "center",
                        background: isShared
                          ? "color-mix(in srgb, var(--primary) 6%, var(--panel))"
                          : undefined,
                        borderColor: isShared
                          ? "color-mix(in srgb, var(--primary) 25%, transparent)"
                          : undefined,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 900 }}>{cp.care_partner_name}</div>
                        <div className="muted-text" style={{ fontSize: 12, marginTop: 2 }}>
                          {cp.care_partner_email}
                        </div>
                      </div>
                      <button
                        type="button"
                        className={isShared ? "primary-btn" : "secondary-btn"}
                        onClick={() => toggleShare(cp.care_partner_user_id)}
                        disabled={isWorking}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {isWorking ? t("working") : isShared ? t("unshare") : t("share")}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}
