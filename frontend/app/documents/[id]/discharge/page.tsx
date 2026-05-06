"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import OriginalLayoutViewer from "@/components/original-layout-viewer";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import {
  cleanOneLine,
  formatPdfLikeDischargeText,
  formatSectionPreview,
} from "@/lib/discharge-epicriza-formatter";

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

  const normalized = value.trim();
  const direct = new Date(normalized).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(
    /^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/
  );

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

  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function displayValue(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function parseDischargePayload(noteBody?: string | null): DischargePayload | null {
  if (!noteBody) return null;

  try {
    const parsed = JSON.parse(noteBody);

    if (
      parsed &&
      typeof parsed === "object" &&
      parsed.document_type === "discharge_summary" &&
      Array.isArray(parsed.sections)
    ) {
      return parsed;
    }

    return null;
  } catch {
    return null;
  }
}

function getSectionBody(section?: Partial<DischargeSection> | null) {
  const raw = section?.formatted_body || section?.body || "";
  return formatPdfLikeDischargeText(raw);
}

function sectionIcon(key?: string) {
  if (key === "overview") return "Ov";
  if (key === "full_summary") return "All";
  if (key === "pre_epicriza_summary") return "Pt";
  if (key === "administrative_information") return "Ad";
  if (key === "diagnoses") return "Dx";
  if (key === "epicriza") return "Ep";
  if (key === "investigations") return "Ix";
  if (key === "laboratory_normal") return "N";
  if (key === "laboratory_abnormal") return "Ab";
  if (key === "treatment_in_hospital") return "Tx";
  if (key === "recommended_treatment") return "Rx";
  if (key === "recommendations") return "Fu";
  if (key === "discharge_status") return "St";
  if (key === "audit") return "Au";
  return "Tx";
}

function sectionAccent(key?: string) {
  if (key === "laboratory_abnormal") return "var(--danger-text)";
  if (key === "laboratory_normal") return "var(--success-text)";
  if (key === "recommended_treatment") return "var(--primary)";
  if (key === "epicriza") return "var(--primary)";
  return "var(--muted)";
}

function StatusPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warn" | "danger";
}) {
  const style =
    tone === "success"
      ? {
          background: "var(--success-bg)",
          color: "var(--success-text)",
          borderColor: "var(--success-border)",
        }
      : tone === "warn"
      ? {
          background: "var(--warn-bg)",
          color: "var(--warn-text)",
          borderColor: "var(--warn-border)",
        }
      : tone === "danger"
      ? {
          background: "var(--danger-bg)",
          color: "var(--danger-text)",
          borderColor: "var(--danger-border)",
        }
      : {
          background: "var(--panel-2)",
          color: "var(--muted)",
          borderColor: "var(--border)",
        };

  return (
    <span
      style={{
        display: "inline-flex",
        padding: "7px 10px",
        borderRadius: 999,
        border: `1px solid ${style.borderColor}`,
        background: style.background,
        color: style.color,
        fontSize: 12,
        fontWeight: 950,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function CompactMetaItem({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        minHeight: 34,
        padding: "7px 10px",
        borderRadius: 999,
        border: "1px solid var(--border)",
        background: "var(--panel-2)",
      }}
    >
      <span className="muted-text" style={{ fontSize: 11, fontWeight: 900 }}>
        {label}
      </span>

      <span style={{ fontSize: 12, fontWeight: 950 }}>{displayValue(value)}</span>
    </div>
  );
}

function ReaderToggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: active ? "1px solid color-mix(in srgb, var(--primary) 55%, var(--border))" : "1px solid var(--border)",
        background: active
          ? "linear-gradient(135deg, color-mix(in srgb, var(--primary) 20%, var(--panel)), var(--panel))"
          : "var(--panel-2)",
        color: active ? "var(--primary)" : "var(--foreground)",
        borderRadius: 999,
        padding: "9px 12px",
        fontSize: 12,
        fontWeight: 950,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function SectionTextPanel({
  section,
  text,
  onCopy,
}: {
  section: NavigationSection;
  text?: string | null;
  onCopy?: () => void;
}) {
  const rawText = text || "";

  return (
    <div
      style={{
        minHeight: 0,
        height: "100%",
        display: "grid",
        gridTemplateRows: "auto minmax(0, 1fr)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 14,
          alignItems: "flex-start",
        }}
      >
        <div>
          <div className="section-title">{section.title}</div>

          {section.original_titles?.length ? (
            <div className="muted-text" style={{ marginTop: 6, fontSize: 12, fontWeight: 850 }}>
              Original heading: {section.original_titles.join(" · ")}
            </div>
          ) : null}

          {section.formatting_method && section.formatting_method !== "raw_ocr" ? (
            <div className="muted-text" style={{ marginTop: 6, fontSize: 12, fontWeight: 800 }}>
              AI layout formatted
              {section.formatting_confidence !== null && section.formatting_confidence !== undefined
                ? ` · ${Math.round(section.formatting_confidence * 100)}% confidence`
                : ""}
            </div>
          ) : null}
        </div>

        {onCopy && (
          <button className="secondary-btn" onClick={onCopy}>
            Copy section
          </button>
        )}
      </div>

      <div
        className="soft-card-tight"
        style={{
          padding: 22,
          background: "var(--panel-2)",
          minHeight: 0,
          overflow: "auto",
          borderRadius: 24,
        }}
      >
        <pre
          style={{
            margin: 0,
            whiteSpace: "pre-wrap",
            fontFamily:
              'Arial, Helvetica, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            fontSize: 14,
            lineHeight: 1.42,
            fontWeight: 650,
            color: "var(--foreground)",
            tabSize: 4,
            overflowWrap: "break-word",
            wordBreak: "normal",
          }}
        >
          {rawText || "No text extracted for this section."}
        </pre>
      </div>
    </div>
  );
}

function copyText(text: string) {
  if (!text) return;
  void navigator.clipboard?.writeText(text);
}

function mergeFirstPageSections(rawSections: DischargeSection[]) {
  const firstClinicalIndex = rawSections.findIndex((section) => section.key === "epicriza");

  const preEpicrizaKeys = new Set([
    "administrative_information",
    "discharge_status",
    "diagnoses",
    "pre_epicriza_summary",
  ]);

  const preSections: DischargeSection[] = [];
  const remainingSections: DischargeSection[] = [];

  rawSections.forEach((section, index) => {
    const isBeforeEpicriza = firstClinicalIndex === -1 ? index < 3 : index < firstClinicalIndex;
    const shouldMerge =
      section.key === "pre_epicriza_summary" ||
      preEpicrizaKeys.has(section.key) ||
      (isBeforeEpicriza && section.key !== "epicriza");

    if (shouldMerge) {
      preSections.push(section);
    } else {
      remainingSections.push(section);
    }
  });

  if (!preSections.length) return rawSections;

  const combinedBody = preSections
    .map((section) => {
      const title = cleanOneLine(section.title || section.key || "Details");
      return `[${title}]\n${section.body || ""}`;
    })
    .join("\n\n");

  const combinedFormattedBody = preSections
    .map((section) => {
      const title = cleanOneLine(section.title || section.key || "Details");
      return `[${title}]\n${getSectionBody(section)}`;
    })
    .join("\n\n");

  const originalTitles = preSections.flatMap((section) => section.original_titles || []);
  const hasAiFormatting = preSections.some((section) => section.formatted_body);

  const combined: DischargeSection = {
    key: "pre_epicriza_summary",
    title: "Admission / patient / diagnoses",
    original_titles: Array.from(new Set(originalTitles)),
    body: combinedBody,
    formatted_body: combinedFormattedBody,
    formatting_method: hasAiFormatting ? "mixed" : "raw_ocr",
    formatting_confidence: hasAiFormatting
      ? Math.max(...preSections.map((section) => Number(section.formatting_confidence || 0)))
      : 0,
    confidence: Math.max(...preSections.map((section) => Number(section.confidence || 0.8))),
  };

  return [combined, ...remainingSections];
}

export default function DischargeStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentResponse | null>(null);
  const [activeSectionKey, setActiveSectionKey] = useState("full_summary");
  const [readerMode, setReaderMode] = useState<"structured" | "original">("structured");
  const [loading, setLoading] = useState(true);
  const [openingOriginal, setOpeningOriginal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [error, setError] = useState("");

  async function fetchData() {
    const [meResponse, documentResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<DocumentResponse>(`/documents/${documentId}`),
    ]);

    const isDischarge =
      documentResponse.data.section === "discharge_summary" ||
      documentResponse.data.parsed_data?.report_type === "Discharge summary" ||
      documentResponse.data.parsed_data?.report_type === "discharge_summary";

    if (!isDischarge) {
      router.replace(`/documents/${documentId}`);
      return;
    }

    setCurrentUser(meResponse.data);
    setDocumentData(documentResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setLoading(true);
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load discharge summary."));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const parsed = documentData?.parsed_data;
  const dischargePayload = parseDischargePayload(parsed?.note_body);

  const sections = useMemo(() => {
    return mergeFirstPageSections(dischargePayload?.sections || []);
  }, [dischargePayload?.sections]);

  const fullSummaryText = useMemo(() => {
    return sections.map((section) => `${section.title}\n\n${getSectionBody(section)}`).join("\n\n---\n\n");
  }, [sections]);

  const navigationSections = useMemo<NavigationSection[]>(() => {
    return [
      {
        key: "overview",
        title: "Overview",
        body: "Patient, hospitalization, and document details.",
        synthetic: true,
      },
      {
        key: "full_summary",
        title: "Full discharge summary",
        body: fullSummaryText || "All extracted sections shown together.",
        formatted_body: fullSummaryText || "",
        synthetic: true,
      },
      ...sections.map((section) => ({
        ...section,
        synthetic: false,
      })),
      {
        key: "audit",
        title: "Audit trail",
        body: "Verification and document activity.",
        synthetic: true,
      },
    ];
  }, [sections, fullSummaryText]);

  const activeSection = navigationSections.find((section) => section.key === activeSectionKey) || navigationSections[0];

  const canDelete =
    Boolean(currentUser && documentData && currentUser.id === documentData.uploaded_by_user_id) ||
    currentUser?.role === "admin";

  async function openOriginal() {
    if (!documentData) return;

    try {
      setOpeningOriginal(true);
      setError("");

      const response = await api.get(`/documents/${documentData.document_id}/file`, {
        responseType: "blob",
      });

      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string"
          ? rawContentType
          : documentData.content_type || "application/octet-stream";

      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);

      window.open(fileUrl, "_blank", "noopener,noreferrer");

      window.setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(getErrorMessage(err, "Could not open original file."));
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

      if (currentUser?.role === "patient") {
        router.push("/my-records");
        return;
      }

      if (documentData.patient_id) {
        router.push(`/patients/${documentData.patient_id}`);
        return;
      }

      router.push("/my-records");
    } catch (err) {
      setError(getErrorMessage(err, "Could not delete discharge summary."));
      setConfirmDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  }

  if (loading || !currentUser || !documentData || !parsed) {
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
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">Loading discharge summary...</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={parsed.report_name || "Discharge reader"}
      subtitle={`${valueOrDash(parsed.patient_name)} · CNP ${valueOrDash(parsed.cnp)} · ${
        parsed.is_verified ? "Verified" : "Unverified"
      }`}
      rightContent={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button className="secondary-btn" onClick={openOriginal} disabled={openingOriginal}>
            {openingOriginal ? "Opening..." : "Open original"}
          </button>

          {canDelete && (
            <button
              onClick={() => setConfirmDeleteOpen(true)}
              style={{
                border: "1px solid var(--danger-border)",
                background: "var(--danger-bg)",
                color: "var(--danger-text)",
                borderRadius: 14,
                padding: "11px 15px",
                fontWeight: 950,
                cursor: "pointer",
              }}
            >
              Delete
            </button>
          )}

          <button className="secondary-btn" onClick={() => router.back()}>
            Back
          </button>
        </div>
      }
    >
      {confirmDeleteOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            background: "rgba(15, 23, 42, 0.42)",
            display: "grid",
            placeItems: "center",
            padding: 20,
            backdropFilter: "blur(10px)",
          }}
        >
          <div
            className="soft-card"
            style={{
              width: "min(520px, 100%)",
              padding: 24,
              boxShadow: "0 30px 90px rgba(15, 23, 42, 0.32)",
            }}
          >
            <div style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.05em" }}>
              Delete this discharge summary?
            </div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.65 }}>
              This removes the discharge summary from the patient files and timeline. This can only be done by the
              uploader or an admin.
            </div>

            <div className="soft-card-tight" style={{ marginTop: 16, padding: 14, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{parsed.report_name || documentData.filename}</div>
              <div className="muted-text" style={{ marginTop: 5 }}>
                Uploaded by {valueOrDash(documentData.uploaded_by?.full_name)}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
              <button className="secondary-btn" onClick={() => setConfirmDeleteOpen(false)} disabled={deleting}>
                Cancel
              </button>

              <button
                onClick={deleteDocument}
                disabled={deleting}
                style={{
                  border: "1px solid var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  borderRadius: 14,
                  padding: "11px 15px",
                  fontWeight: 950,
                  cursor: deleting ? "not-allowed" : "pointer",
                }}
              >
                {deleting ? "Deleting..." : "Delete summary"}
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 14,
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
        className="soft-card-tight"
        style={{
          padding: 12,
          marginBottom: 14,
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 7%, var(--panel)), var(--panel))",
        }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <ReaderToggle active={readerMode === "structured"} onClick={() => setReaderMode("structured")}>
            Structured reader
          </ReaderToggle>

          <ReaderToggle active={readerMode === "original"} onClick={() => setReaderMode("original")}>
            Original layout
          </ReaderToggle>

          <StatusPill tone={parsed.is_verified ? "success" : "warn"}>
            {parsed.is_verified ? "Verified" : "Unverified"}
          </StatusPill>

          <StatusPill>{sections.length} sections</StatusPill>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <CompactMetaItem label="Patient" value={parsed.patient_name} />
          <CompactMetaItem
            label="Hospitalization"
            value={`${valueOrDash(parsed.collected_on)} → ${valueOrDash(parsed.reported_on)}`}
          />
        </div>
      </div>

      <div
        className="soft-card"
        style={{
          padding: 16,
          display: "grid",
          gridTemplateColumns: readerMode === "original" ? "minmax(0, 1fr)" : "minmax(310px, 0.28fr) minmax(0, 1fr)",
          gap: 16,
          alignItems: "stretch",
          height: "calc(100vh - 185px)",
          minHeight: 720,
          overflow: "hidden",
        }}
      >
        {readerMode === "structured" && (
          <aside
            className="soft-card-tight"
            style={{
              padding: 14,
              background: "var(--panel-2)",
              height: "100%",
              overflowY: "auto",
            }}
          >
            <div
              className="muted-text"
              style={{
                padding: "6px 8px 12px",
                fontSize: 12,
                fontWeight: 950,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              Sections
            </div>

            <div style={{ display: "grid", gap: 8 }}>
              {navigationSections.map((section) => {
                const active = activeSectionKey === section.key;
                const accent = sectionAccent(section.key);

                return (
                  <button
                    key={section.key}
                    type="button"
                    onClick={() => setActiveSectionKey(section.key)}
                    style={{
                      border: `1px solid ${
                        active ? "color-mix(in srgb, var(--primary) 55%, var(--border))" : "var(--border)"
                      }`,
                      background: active
                        ? "linear-gradient(135deg, color-mix(in srgb, var(--primary) 18%, var(--panel)), var(--panel))"
                        : "var(--panel)",
                      color: "var(--foreground)",
                      borderRadius: 20,
                      padding: 14,
                      textAlign: "left",
                      cursor: "pointer",
                      display: "grid",
                      gridTemplateColumns: "36px minmax(0, 1fr)",
                      gap: 11,
                      alignItems: "center",
                      boxShadow: active ? "0 14px 34px color-mix(in srgb, var(--primary) 15%, transparent)" : "none",
                    }}
                  >
                    <span
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 13,
                        display: "grid",
                        placeItems: "center",
                        background: active
                          ? "color-mix(in srgb, var(--primary) 18%, var(--panel-2))"
                          : "var(--panel-2)",
                        color: active ? "var(--primary)" : accent,
                        border: "1px solid var(--border)",
                        fontSize: 11,
                        fontWeight: 950,
                      }}
                    >
                      {sectionIcon(section.key)}
                    </span>

                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: "block", fontWeight: 950, fontSize: 13 }}>{section.title}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        <section
          className="soft-card-tight"
          style={{
            padding: 26,
            background: "var(--panel)",
            borderRadius: 28,
            height: "100%",
            minHeight: 0,
            display: "grid",
            gridTemplateRows: "minmax(0, 1fr)",
            overflow: "hidden",
          }}
        >
          {readerMode === "original" ? (
            <OriginalLayoutViewer layout={parsed.original_layout} mode="lines" />
          ) : (
            <>
              {activeSectionKey === "overview" && (
                <div
                  style={{
                    minHeight: 0,
                    height: "100%",
                    overflowY: "auto",
                    paddingRight: 8,
                  }}
                >
                  <div className="section-title" style={{ marginBottom: 16 }}>
                    Overview
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 14,
                    }}
                  >
                    <CompactMetaItem label="Patient" value={parsed.patient_name} />
                    <CompactMetaItem label="DOB" value={parsed.date_of_birth} />
                    <CompactMetaItem label="Age" value={parsed.age} />
                    <CompactMetaItem label="Sex" value={parsed.sex} />
                    <CompactMetaItem label="CNP" value={parsed.cnp} />
                    <CompactMetaItem label="Patient ID" value={parsed.patient_identifier} />
                    <CompactMetaItem label="Admission" value={parsed.collected_on} />
                    <CompactMetaItem label="Discharge" value={parsed.reported_on} />
                    <CompactMetaItem label="Doctor" value={parsed.referring_doctor} />
                    <CompactMetaItem label="Language" value={parsed.source_language} />
                  </div>
                </div>
              )}

              {activeSectionKey === "full_summary" && (
                <SectionTextPanel
                  section={{
                    key: "full_summary",
                    title: "Full discharge summary",
                    body: fullSummaryText,
                    formatted_body: fullSummaryText,
                  }}
                  text={fullSummaryText}
                  onCopy={() => copyText(fullSummaryText)}
                />
              )}

              {activeSectionKey !== "overview" && activeSectionKey !== "full_summary" && activeSectionKey !== "audit" && (
                <SectionTextPanel
                  section={activeSection}
                  text={getSectionBody(activeSection)}
                  onCopy={() => copyText(getSectionBody(activeSection))}
                />
              )}

              {activeSectionKey === "audit" && (
                <div
                  style={{
                    minHeight: 0,
                    height: "100%",
                    display: "grid",
                    gridTemplateRows: "auto minmax(0, 1fr)",
                    overflow: "hidden",
                  }}
                >
                  <div className="section-title" style={{ marginBottom: 16 }}>
                    Audit trail
                  </div>

                  <div style={{ display: "grid", gap: 12, minHeight: 0, overflowY: "auto", paddingRight: 8 }}>
                    {(parsed.audit_logs || []).map((log, index) => (
                      <div key={`${log.action}-${log.timestamp}-${index}`} className="soft-card-tight" style={{ padding: 16 }}>
                        <div style={{ fontWeight: 950 }}>{log.action}</div>
                        <div className="muted-text" style={{ marginTop: 5 }}>
                          {valueOrDash(log.actor)} · {formatDate(log.timestamp)}
                        </div>

                        {log.details && (
                          <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.55 }}>
                            {log.details}
                          </div>
                        )}
                      </div>
                    ))}

                    {!parsed.audit_logs?.length && (
                      <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                        <div className="muted-text">No audit activity yet.</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}