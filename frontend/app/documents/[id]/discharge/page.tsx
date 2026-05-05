"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";

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

type DischargeSection = {
  key: string;
  title: string;
  original_titles?: string[];
  body: string;
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
    audit_logs?: AuditLog[];
  };
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

function sectionIcon(key?: string) {
  if (key === "diagnoses") return "Dx";
  if (key === "epicriza") return "Ep";
  if (key === "investigations") return "Ix";
  if (key === "treatment_in_hospital") return "Tx";
  if (key === "recommended_treatment") return "Rx";
  if (key === "recommendations") return "Fu";
  if (key === "discharge_status") return "St";
  return "Tx";
}

function sectionPreview(body?: string) {
  const text = (body || "").replace(/\s+/g, " ").trim();

  if (!text) return "No extracted text.";

  if (text.length <= 88) return text;

  return `${text.slice(0, 88)}...`;
}

function StatBubble({
  label,
  value,
  note,
}: {
  label: string;
  value?: string | number | null;
  note?: string | null;
}) {
  return (
    <div
      className="soft-card-tight"
      style={{
        padding: 18,
        background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 7%, var(--panel)), var(--panel))",
      }}
    >
      <div className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
        {label}
      </div>

      <div
        style={{
          marginTop: 8,
          fontSize: 18,
          fontWeight: 950,
          letterSpacing: "-0.035em",
          lineHeight: 1.25,
          wordBreak: "break-word",
        }}
      >
        {valueOrDash(value === null || value === undefined ? value : String(value))}
      </div>

      {note && (
        <div className="muted-text" style={{ marginTop: 7, fontSize: 12, lineHeight: 1.45 }}>
          {note}
        </div>
      )}
    </div>
  );
}

function StatusPill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
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
      }}
    >
      {children}
    </span>
  );
}

function copyText(text: string) {
  if (!text) return;
  void navigator.clipboard?.writeText(text);
}

export default function DischargeStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentResponse | null>(null);
  const [activeSectionKey, setActiveSectionKey] = useState("full_summary");
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
  const sections = dischargePayload?.sections || [];

  const navigationSections = useMemo(() => {
    return [
      {
        key: "overview",
        title: "Overview",
        body: "Patient, hospitalization, and document details.",
      },
      {
        key: "full_summary",
        title: "Full discharge summary",
        body: "All extracted sections shown together.",
      },
      ...sections,
      {
        key: "audit",
        title: "Audit trail",
        body: "Verification and document activity.",
      },
    ];
  }, [sections]);

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

  const fullSummaryText = sections
    .map((section) => `${section.title}\n\n${section.body}`)
    .join("\n\n---\n\n");

  return (
    <AppShell
      user={currentUser}
      title={parsed.report_name || "Discharge summary"}
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
                    This removes the discharge summary from the patient files and timeline. This can only be done by the uploader or an admin.
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

      <div
        className="soft-card"
        style={{
          padding: 24,
          marginBottom: 24,
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 12%, var(--panel)), var(--panel))",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              <StatusPill tone={parsed.is_verified ? "success" : "warn"}>
                {parsed.is_verified ? "Verified" : "Unverified"}
              </StatusPill>
              <StatusPill>Discharge summary</StatusPill>
              <StatusPill>{sections.length} sections</StatusPill>
            </div>

            <div style={{ fontSize: 32, fontWeight: 950, letterSpacing: "-0.06em" }}>
              {parsed.report_name || "Discharge summary"}
            </div>

            <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.65 }}>
              Narrative discharge record extracted from the original document and organized into clinical sections.
            </div>
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <StatBubble
          label="Patient"
          value={parsed.patient_name}
          note={`DOB ${valueOrDash(parsed.date_of_birth)} · Sex ${valueOrDash(parsed.sex)} · CNP ${valueOrDash(
            parsed.cnp
          )}`}
        />

        <StatBubble
          label="Hospitalization"
          value={`${valueOrDash(parsed.collected_on)} → ${valueOrDash(parsed.reported_on)}`}
          note="Admission to discharge period"
        />

        <StatBubble
          label="Document"
          value={parsed.report_type || "Discharge summary"}
          note={`Language ${valueOrDash(parsed.source_language)} · Uploaded by ${valueOrDash(
            documentData.uploaded_by?.full_name
          )}`}
        />
      </div>

      <div
        className="soft-card"
        style={{
          padding: 18,
          display: "grid",
          gridTemplateColumns: "minmax(250px, 0.34fr) minmax(0, 1fr)",
          gap: 18,
          alignItems: "start",
        }}
      >
        <aside
          className="soft-card-tight"
          style={{
            padding: 12,
            background: "var(--panel-2)",
            position: "sticky",
            top: 18,
            maxHeight: "calc(100vh - 120px)",
            overflow: "auto",
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
                    borderRadius: 18,
                    padding: 12,
                    textAlign: "left",
                    cursor: "pointer",
                    display: "grid",
                    gridTemplateColumns: "34px minmax(0, 1fr)",
                    gap: 10,
                    alignItems: "start",
                    boxShadow: active ? "0 14px 34px color-mix(in srgb, var(--primary) 15%, transparent)" : "none",
                  }}
                >
                  <span
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 12,
                      display: "grid",
                      placeItems: "center",
                      background: active
                        ? "color-mix(in srgb, var(--primary) 18%, var(--panel-2))"
                        : "var(--panel-2)",
                      color: active ? "var(--primary)" : "var(--muted)",
                      border: "1px solid var(--border)",
                      fontSize: 11,
                      fontWeight: 950,
                    }}
                  >
                    {section.key === "overview"
                      ? "Ov"
                      : section.key === "full_summary"
                      ? "All"
                      : section.key === "audit"
                      ? "Au"
                      : sectionIcon(section.key)}
                  </span>

                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: "block", fontWeight: 950, fontSize: 13 }}>
                      {section.title}
                    </span>
                    <span className="muted-text" style={{ display: "block", marginTop: 5, fontSize: 12, lineHeight: 1.35 }}>
                      {sectionPreview(section.body)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section
          className="soft-card-tight"
          style={{
            padding: 24,
            minHeight: 560,
            background: "var(--panel)",
            borderRadius: 26,
          }}
        >
          {activeSectionKey === "overview" && (
            <div>
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
                <StatBubble label="Patient name" value={parsed.patient_name} />
                <StatBubble label="Date of birth" value={parsed.date_of_birth} />
                <StatBubble label="Age" value={parsed.age} />
                <StatBubble label="Sex" value={parsed.sex} />
                <StatBubble label="CNP" value={parsed.cnp} />
                <StatBubble label="Patient ID" value={parsed.patient_identifier} />
                <StatBubble label="Admission date" value={parsed.collected_on} />
                <StatBubble label="Discharge date" value={parsed.reported_on} />
                <StatBubble label="Referring doctor" value={parsed.referring_doctor} />
                <StatBubble label="Source language" value={parsed.source_language} />
              </div>
            </div>
          )}

          {activeSectionKey === "full_summary" && (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  flexWrap: "wrap",
                  marginBottom: 16,
                }}
              >
                <div>
                  <div className="section-title">Full discharge summary</div>
                  <div className="muted-text" style={{ marginTop: 6 }}>
                    All extracted sections displayed in document order.
                  </div>
                </div>

                <button className="secondary-btn" onClick={() => copyText(fullSummaryText)}>
                  Copy all
                </button>
              </div>

              <div style={{ display: "grid", gap: 16 }}>
                {sections.map((section, index) => (
                  <div key={`${section.key}-${index}`} className="soft-card-tight" style={{ padding: 18 }}>
                    <div style={{ fontWeight: 950, fontSize: 18, letterSpacing: "-0.035em" }}>
                      {section.title}
                    </div>

                    {section.original_titles?.length ? (
                      <div className="muted-text" style={{ marginTop: 5, fontSize: 12, fontWeight: 800 }}>
                        Original heading: {section.original_titles.join(" · ")}
                      </div>
                    ) : null}

                    <div
                      style={{
                        whiteSpace: "pre-wrap",
                        marginTop: 14,
                        lineHeight: 1.75,
                        fontWeight: 650,
                      }}
                    >
                      {section.body || "No text extracted for this section."}
                    </div>
                  </div>
                ))}

                {!sections.length && (
                  <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                    <div style={{ fontWeight: 900 }}>No discharge sections found.</div>
                    <div className="muted-text" style={{ marginTop: 6 }}>
                      The backend did not return a structured discharge payload for this document.
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeSectionKey !== "overview" && activeSectionKey !== "full_summary" && activeSectionKey !== "audit" && (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  flexWrap: "wrap",
                  marginBottom: 16,
                }}
              >
                <div>
                  <div className="section-title">{activeSection.title}</div>

                  {"original_titles" in activeSection && activeSection.original_titles?.length ? (
                    <div className="muted-text" style={{ marginTop: 6, fontSize: 12, fontWeight: 850 }}>
                      Original heading: {activeSection.original_titles.join(" · ")}
                    </div>
                  ) : null}
                </div>

                {"body" in activeSection && (
                  <button className="secondary-btn" onClick={() => copyText(activeSection.body || "")}>
                    Copy section
                  </button>
                )}
              </div>

              <div
                className="soft-card-tight"
                style={{
                  padding: 22,
                  background: "var(--panel-2)",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.8,
                  fontWeight: 650,
                  minHeight: 260,
                }}
              >
                {activeSection.body || "No text extracted for this section."}
              </div>
            </div>
          )}

          {activeSectionKey === "audit" && (
            <div>
              <div className="section-title" style={{ marginBottom: 16 }}>
                Audit trail
              </div>

              <div style={{ display: "grid", gap: 12 }}>
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
        </section>
      </div>
    </AppShell>
  );
}