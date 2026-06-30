"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import EmergencyShell from "@/components/emergency-shell";
import { emergencyApi, getEmergencyUser, clearEmergencySession } from "@/lib/emergency-api";
import { useLanguage } from "@/lib/i18n";

type LabRow = {
  id: number;
  raw_test_name?: string | null;
  canonical_name?: string | null;
  display_name?: string | null;
  category?: string | null;
  source_section?: string | null;
  value?: string | null;
  flag?: string | null;
  reference_range?: string | null;
  unit?: string | null;
  is_abnormal?: boolean;
};

type ParsedData = {
  patient_name?: string | null;
  date_of_birth?: string | null;
  age?: string | null;
  sex?: string | null;
  lab_name?: string | null;
  sample_type?: string | null;
  referring_doctor?: string | null;
  report_name?: string | null;
  report_type?: string | null;
  source_language?: string | null;
  test_date?: string | null;
  collected_on?: string | null;
  reported_on?: string | null;
  registered_on?: string | null;
  generated_on?: string | null;
  note_body?: string | null;
  is_verified?: boolean;
  verified_by?: string | null;
  verified_at?: string | null;
  created_at?: string | null;
  has_abnormal?: boolean;
  labs: LabRow[];
};

type DocumentData = {
  document_id: number;
  patient_id: number;
  filename: string;
  section: string;
  content_type?: string | null;
  parsed_data: ParsedData;
};

const NIL_VALUES = new Set(["", "-", "--", "—", "–", "n/a", "na", "nil", "null", "none"]);

function isNilValue(v?: string | null) {
  const c = (v ?? "").trim().toLowerCase().replace(/[−–—]/g, "-");
  return NIL_VALUES.has(c) || /^-+$/.test(c);
}

function isAbnormalFlag(flag?: string | null) {
  const c = (flag ?? "").trim().toLowerCase();
  return ["high", "low", "abnormal", "critical", "borderline"].includes(c);
}

function hasDisplayableFlag(flag?: string | null) {
  const c = (flag ?? "").trim().toLowerCase();
  return !!c && !["none", "null", "undefined", "-", "—"].includes(c);
}

function valueOrDash(v?: string | null) {
  return v && v.trim() ? v : "—";
}

function formatDate(v?: string | null) {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function bestName(lab: LabRow) {
  return lab.display_name || lab.canonical_name || lab.raw_test_name || "—";
}

function getFlagColor(flag?: string | null, value?: string | null) {
  if (isNilValue(value)) return { bg: "var(--panel-2)", color: "var(--muted)", border: "var(--border)" };
  if (!hasDisplayableFlag(flag)) return { bg: "var(--panel-2)", color: "var(--muted)", border: "var(--border)" };
  const c = (flag ?? "").trim().toLowerCase();
  if (c === "normal" || c === "ok") return { bg: "var(--success-bg)", color: "var(--success-text)", border: "var(--success-border)" };
  if (isAbnormalFlag(flag)) return { bg: "var(--danger-bg)", color: "var(--danger-text)", border: "var(--danger-border)" };
  return { bg: "var(--panel-2)", color: "var(--muted)", border: "var(--border)" };
}

function MetaItem({ label, value }: { label: string; value?: string | null }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)" }}>
        {label}
      </span>
      <span style={{ fontSize: 14, fontWeight: 900, letterSpacing: "-0.02em" }}>{valueOrDash(value)}</span>
    </div>
  );
}

function DocumentViewInner() {
  const params = useParams<{ document_id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useLanguage();

  const documentId = params?.document_id;
  const sessionId = searchParams.get("session_id");

  const [user, setUser] = useState<ReturnType<typeof getEmergencyUser>>(null);
  const [doc, setDoc] = useState<DocumentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const u = getEmergencyUser();
    if (!u || (u.role !== "emergency_worker" && u.role !== "admin")) {
      router.replace("/emergency/login");
      return;
    }
    setUser(u);

    if (!documentId || !sessionId) {
      setError(t("emergencyDocSessionRequired"));
      setLoading(false);
      return;
    }

    emergencyApi
      .get<DocumentData>(`/emergency/documents/${documentId}?session_id=${sessionId}`)
      .then((r) => {
        setDoc(r.data);
      })
      .catch((err) => {
        const msg = (err?.response?.data?.detail as string) ?? "";
        setError(msg || t("emergencyDocNotFound"));
      })
      .finally(() => setLoading(false));
  }, [documentId, sessionId, router, t]);

  const workspaceHref = sessionId ? `/emergency/workspace?tab=${sessionId}` : "/emergency/workspace";

  const orderedGroups = useMemo(() => {
    if (!doc) return [];
    const labs = doc.parsed_data.labs || [];
    const groups = new Map<string, { title: string; rows: LabRow[] }>();
    for (const lab of labs) {
      const key = lab.source_section || lab.category || "Other";
      if (!groups.has(key)) groups.set(key, { title: key, rows: [] });
      groups.get(key)!.rows.push(lab);
    }
    return Array.from(groups.values());
  }, [doc]);

  function handleLogout() {
    clearEmergencySession();
    router.replace("/emergency/login");
  }

  if (loading) {
    return (
      <EmergencyShell user={user} onLogout={handleLogout}>
        <p className="muted-text" style={{ fontSize: 14 }}>{t("loadingStructuredDocument")}</p>
      </EmergencyShell>
    );
  }

  const parsed = doc?.parsed_data;
  const isNote = doc?.section === "notes";

  return (
    <EmergencyShell user={user} onLogout={handleLogout}>
      <style jsx global>{`
        .ew-doc-table { width: 100%; border-collapse: separate; border-spacing: 0; }
        .ew-doc-table th { text-align: left; font-size: 11px; color: var(--muted); font-weight: 900; padding: 10px 12px; border-bottom: 1px solid var(--border); background: var(--panel-2); }
        .ew-doc-table td { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: middle; font-size: 13px; }
        .ew-doc-table tr:last-child td { border-bottom: 0; }
        .ew-doc-table tr.abnormal-row td { background: color-mix(in srgb, var(--danger-bg) 60%, transparent); }
        @media (max-width: 680px) {
          .ew-doc-table, .ew-doc-table thead, .ew-doc-table tbody, .ew-doc-table th, .ew-doc-table td, .ew-doc-table tr { display: block; }
          .ew-doc-table thead { display: none; }
          .ew-doc-table tr { border-bottom: 1px solid var(--border); padding: 8px 0; }
          .ew-doc-table td { border-bottom: 0; padding: 6px 12px; }
          .ew-doc-table td::before { content: attr(data-label); display: block; color: var(--muted); font-size: 10px; font-weight: 900; margin-bottom: 3px; }
        }
      `}</style>

      {/* Back nav */}
      <div style={{ marginBottom: 20 }}>
        <Link
          href={workspaceHref}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: "var(--primary)", textDecoration: "none" }}
        >
          ← {t("emergencyBackToWorkspace")}
        </Link>
      </div>

      {error && (
        <div
          className="soft-card"
          style={{ padding: 22, marginBottom: 20, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}
        >
          <div style={{ fontWeight: 900, fontSize: 16, marginBottom: 6 }}>{t("emergencyDocNotFound")}</div>
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>{error}</div>
          <div style={{ marginTop: 16 }}>
            <Link href={workspaceHref} style={{ fontSize: 13, color: "var(--primary)", fontWeight: 700, textDecoration: "none" }}>
              {t("emergencyBackToWorkspace")}
            </Link>
          </div>
        </div>
      )}

      {doc && parsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Header card */}
          <div
            className="soft-card"
            style={{
              padding: 22,
              background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 8%, var(--panel)), var(--panel))",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 950, letterSpacing: "-0.04em", marginBottom: 8 }}>
                  {parsed.report_name || doc.filename}
                </div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <span
                    style={{
                      fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.07em",
                      padding: "3px 9px", borderRadius: 999, background: "rgba(220,38,38,0.08)",
                      color: "#dc2626", border: "1px solid rgba(220,38,38,0.18)",
                    }}
                  >
                    {t("emergencyReadOnly")}
                  </span>
                  <span
                    style={{
                      fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.07em",
                      padding: "3px 9px", borderRadius: 999, background: "var(--panel-2)",
                      color: "var(--muted)", border: "1px solid var(--border)",
                    }}
                  >
                    {doc.section}
                  </span>
                  {parsed.is_verified && (
                    <span
                      style={{
                        fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.07em",
                        padding: "3px 9px", borderRadius: 999, background: "var(--success-bg)",
                        color: "var(--success-text)", border: "1px solid var(--success-border)",
                      }}
                    >
                      {t("verified")}
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="muted-text" style={{ marginTop: 12, fontSize: 12 }}>
              {t("emergencyDocReadOnlyNotice")}
            </div>
          </div>

          {/* Patient + document meta */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            <div className="soft-card" style={{ padding: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 14 }}>
                {t("patient")}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "14px 16px" }}>
                <MetaItem label={t("name")} value={parsed.patient_name} />
                <MetaItem label={t("dateOfBirth")} value={parsed.date_of_birth} />
                <MetaItem label={t("age")} value={parsed.age} />
                <MetaItem label={t("sex")} value={parsed.sex} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 14 }}>
                {t("documentDetails")}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "14px 16px" }}>
                <MetaItem label={t("reportType")} value={parsed.report_type} />
                <MetaItem label={t("lab")} value={parsed.lab_name} />
                <MetaItem label={t("referringDoctor")} value={parsed.referring_doctor} />
                <MetaItem label={t("collectedOn")} value={parsed.collected_on || parsed.test_date} />
                <MetaItem label={t("reportedOn")} value={parsed.reported_on} />
              </div>
            </div>
          </div>

          {/* Note body */}
          {isNote && parsed.note_body && (
            <div className="soft-card" style={{ padding: 22 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 14 }}>
                {t("clinicalNote")}
              </div>
              <div
                className="soft-card-tight"
                style={{ padding: 18, background: "var(--panel-2)", lineHeight: 1.8, whiteSpace: "pre-wrap", fontSize: 14 }}
              >
                {parsed.note_body}
              </div>
            </div>
          )}

          {/* Lab results */}
          {!isNote && orderedGroups.length > 0 && (
            <div className="soft-card" style={{ padding: 22 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 16 }}>
                {t("structuredData")} · {(parsed.labs || []).length} {t("structuredLabRowsExtracted")}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                {orderedGroups.map(({ title, rows }) => (
                  <div key={title}>
                    <div style={{ fontWeight: 950, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--muted)", marginBottom: 8 }}>
                      {title}
                    </div>
                    <div className="soft-card-tight" style={{ padding: 0, overflow: "hidden" }}>
                      <table className="ew-doc-table">
                        <thead>
                          <tr>
                            <th style={{ width: "38%" }}>{t("test")}</th>
                            <th>{t("value")}</th>
                            <th>{t("unit")}</th>
                            <th>{t("reference")}</th>
                            <th>{t("flag")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((lab) => {
                            const nil = isNilValue(lab.value);
                            const abnormal = !nil && (lab.is_abnormal || isAbnormalFlag(lab.flag));
                            const fc = getFlagColor(lab.flag, lab.value);
                            return (
                              <tr key={lab.id} className={abnormal ? "abnormal-row" : ""}>
                                <td data-label={t("test")}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    {abnormal && <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--danger-text)", flexShrink: 0 }} />}
                                    <span style={{ fontWeight: 900 }}>{bestName(lab)}</span>
                                  </div>
                                </td>
                                <td data-label={t("value")}>
                                  <span style={{ fontWeight: 900 }}>{nil ? "nil" : valueOrDash(lab.value)}</span>
                                </td>
                                <td data-label={t("unit")}>
                                  <span className="muted-text">{valueOrDash(lab.unit)}</span>
                                </td>
                                <td data-label={t("reference")}>
                                  <span className="muted-text">{valueOrDash(lab.reference_range)}</span>
                                </td>
                                <td data-label={t("flag")}>
                                  <span style={{ display: "inline-flex", padding: "4px 9px", borderRadius: 999, border: `1px solid ${fc.border}`, background: fc.bg, color: fc.color, fontSize: 11, fontWeight: 900 }}>
                                    {nil ? "nil" : hasDisplayableFlag(lab.flag) ? lab.flag : "—"}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!isNote && orderedGroups.length === 0 && (
            <div className="soft-card" style={{ padding: 22 }}>
              <div className="muted-text" style={{ fontSize: 13 }}>{t("noStructuredLabs")}</div>
            </div>
          )}

          {/* Footer audit notice */}
          <p className="muted-text" style={{ fontSize: 11, textAlign: "center", paddingBottom: 20 }}>
            {t("emergencyNotADiagnosis")} · {t("emergencyReadOnly")} · {t("emergencyAuditedAccess")}
          </p>
        </div>
      )}
    </EmergencyShell>
  );
}

export default function EmergencyDocumentPage() {
  return (
    <Suspense>
      <DocumentViewInner />
    </Suspense>
  );
}
