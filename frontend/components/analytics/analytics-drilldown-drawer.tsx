"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useLanguage } from "@/lib/i18n";
import type { BloodworkTrend } from "@/lib/analytes/types";
import type { AnalyticsLabStatus, AnalyticsLabValue } from "@/lib/analytics/types";
import { parseDateTime } from "@/lib/analytics/transform";

export type DrawerValue = {
  labValue?: AnalyticsLabValue;
  trend?: BloodworkTrend; // for history list
};

interface Props {
  value: DrawerValue | null;
  onClose: () => void;
  patientId: string;
}

const STATUS_STYLES: Record<AnalyticsLabStatus, { bg: string; text: string }> = {
  in_range: { bg: "rgba(22,163,74,0.15)", text: "#16a34a" },
  out_of_range: { bg: "rgba(220,38,38,0.14)", text: "#dc2626" },
  no_reference_range: { bg: "rgba(217,119,6,0.14)", text: "#d97706" },
  qualitative: { bg: "rgba(2,132,199,0.14)", text: "#0284c7" },
  not_numeric: { bg: "var(--panel-2)", text: "var(--muted)" },
};

const ABNORMAL_FLAGS = new Set([
  "high",
  "low",
  "abnormal",
  "critical",
  "borderline",
  "elevated",
  "h",
  "l",
]);

export default function AnalyticsDrilldownDrawer({ value, onClose, patientId }: Props) {
  const router = useRouter();
  const { t } = useLanguage();

  const lab = value?.labValue;
  const trend = value?.trend;

  const statusLabel = useMemo(() => {
    if (!lab) return "";
    switch (lab.status) {
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
  }, [lab, t]);

  const trendLabel = useMemo(() => {
    if (!lab?.trend) return null;
    switch (lab.trend) {
      case "increased":
        return "↑";
      case "decreased":
        return "↓";
      case "stable":
        return "→";
      default:
        return null;
    }
  }, [lab]);

  const history = useMemo(() => {
    if (!trend) return [];
    return [...trend.points].sort((a, b) => parseDateTime(b.date) - parseDateTime(a.date));
  }, [trend]);

  if (!value || !lab) return null;

  const statusStyle = STATUS_STYLES[lab.status];

  function openSource() {
    if (!lab) return;
    const route =
      lab.document_type === "discharge_summary"
        ? `/documents/${lab.document_id}/discharge`
        : `/documents/${lab.document_id}`;
    router.push(route);
  }

  void patientId; // reserved for future deep-links

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        justifyContent: "flex-end",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "min(400px, 100vw)",
          height: "100%",
          background: "var(--panel)",
          borderLeft: "1px solid var(--border)",
          padding: 24,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }}>{lab.marker_name}</div>
            <div className="muted-text" style={{ fontSize: 13, marginTop: 3 }}>
              {lab.category_display}
              {lab.subgroup ? ` · ${lab.subgroup}` : ""}
            </div>
          </div>
          <button
            type="button"
            className="secondary-btn"
            onClick={onClose}
            aria-label="Close"
            style={{ flexShrink: 0, padding: "6px 12px" }}
          >
            ✕
          </button>
        </div>

        {/* Badges */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              padding: "3px 10px",
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 800,
              background: statusStyle.bg,
              color: statusStyle.text,
            }}
          >
            {statusLabel}
          </span>
          {trendLabel && (
            <span
              style={{
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 800,
                background: "var(--panel-2)",
                color: "var(--muted)",
              }}
            >
              {trendLabel}
            </span>
          )}
          <span className="muted-text" style={{ fontSize: 11, alignSelf: "center" }}>
            {lab.date_label}
          </span>
        </div>

        {/* Stat grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {[
            { label: t("latestValue"), value: lab.value_display || "—" },
            { label: t("unitColumn"), value: lab.unit || "—" },
            { label: t("referenceRangeFromSource"), value: lab.reference_range || "—" },
            { label: t("sourceDocuments"), value: lab.document_title },
          ].map(({ label, value: v }) => (
            <div key={label} className="soft-card-tight" style={{ padding: "12px 14px", minWidth: 0 }}>
              <div
                className="muted-text"
                style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}
              >
                {label}
              </div>
              <div style={{ fontWeight: 700, fontSize: 14, wordBreak: "break-word" }}>{v}</div>
            </div>
          ))}
        </div>

        {/* Status banners */}
        {lab.status === "out_of_range" && (
          <div style={{ padding: "12px 14px", background: "var(--danger-bg)", borderRadius: 10, borderLeft: "3px solid var(--danger-text)" }}>
            <div style={{ fontWeight: 700, color: "var(--danger-text)", fontSize: 13, marginBottom: 4 }}>
              {t("outOfRangePresent")}
            </div>
            <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.55 }}>
              {lab.reference_range ? `${t("referenceRangeFromSource")}: ${lab.reference_range}. ` : ""}
              {t("notADiagnosis")}
            </div>
          </div>
        )}
        {lab.status === "no_reference_range" && (
          <div style={{ padding: "12px 14px", background: "var(--warn-bg)", borderRadius: 10, borderLeft: "3px solid var(--warn-text)" }}>
            <div style={{ fontWeight: 700, color: "var(--warn-text)", fontSize: 13 }}>
              {t("referenceRangeNotFound")}
            </div>
          </div>
        )}

        {/* Open source */}
        <button type="button" className="primary-btn" onClick={openSource} style={{ width: "100%" }}>
          {t("openSourceDocument")}
        </button>

        {/* History list */}
        {history.length > 0 && (
          <div>
            <div className="muted-text" style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>
              {t("allSourceValues")}
            </div>
            <div style={{ display: "grid", gap: 6, maxHeight: 260, overflowY: "auto" }}>
              {history.map((p, i) => {
                const abnormal = !!p.flag && ABNORMAL_FLAGS.has(p.flag.toLowerCase());
                return (
                  <div
                    key={`${p.document_id}_${p.date}_${i}`}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "8px 12px",
                      background: "var(--panel-2)",
                      borderRadius: 8,
                    }}
                  >
                    <span style={{ fontSize: 13, color: "var(--muted)" }}>{p.date}</span>
                    <span
                      style={{
                        fontWeight: 700,
                        fontSize: 13,
                        color: abnormal ? "var(--danger-text)" : "var(--foreground)",
                      }}
                    >
                      {p.value_display || "—"} {lab.unit || ""}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Footer disclaimer */}
        <div
          className="muted-text"
          style={{ fontSize: 11, borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: "auto" }}
        >
          {t("sourceLinked")} · {t("referenceOnly")} · {t("notADiagnosis")}
        </div>
      </div>
    </div>
  );
}
