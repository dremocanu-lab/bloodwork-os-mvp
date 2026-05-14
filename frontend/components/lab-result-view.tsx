"use client";

import type { LabResult, AnalyteEntry, ReferenceRange } from "@/lib/analytes/types";
import { parseLabValue, selectReferenceRange } from "@/lib/analytes/parseValue";
import { classifySeverity, getSeverityStyle } from "@/lib/severity";
import type { Severity } from "@/lib/severity";
import { CATALOG_BY_ID } from "@/lib/analytes/catalog";

type Props = {
  lab: LabResult;
  /** Pre-resolved catalog entry — if omitted, resolved from lab.analyte_id. */
  entry?: AnalyteEntry | null;
  sex?: "M" | "F" | null;
  ageYears?: number | null;
};

function resolveEntry(lab: LabResult, entry?: AnalyteEntry | null): AnalyteEntry | null {
  if (entry !== undefined) return entry ?? null;
  if (lab.analyte_id) return CATALOG_BY_ID[lab.analyte_id] ?? null;
  return null;
}

function resolveDisplayName(lab: LabResult): string {
  return lab.display_name ?? lab.canonical_name ?? lab.raw_test_name ?? "—";
}

type BadgeProps = { severity: Severity; flag?: string | null };

function SeverityBadge({ severity, flag }: BadgeProps) {
  if (severity === "nil" || severity === "unknown") return null;

  const style = getSeverityStyle(severity);
  const label =
    severity === "critical"
      ? "Critical"
      : severity === "abnormal"
      ? flag
        ? flag.charAt(0).toUpperCase() + flag.slice(1).toLowerCase()
        : "Abnormal"
      : severity === "borderline"
      ? "Borderline"
      : "Normal";

  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 7px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.02em",
        background: style.bg,
        color: style.text,
        border: `1px solid ${style.border}`,
        lineHeight: "18px",
      }}
    >
      {label}
    </span>
  );
}

// ── Quantitative ─────────────────────────────────────────────────────────────

function QuantitativeView({
  lab,
  resolvedEntry,
  sex,
  ageYears,
}: {
  lab: LabResult;
  resolvedEntry: AnalyteEntry | null;
  sex?: "M" | "F" | null;
  ageYears?: number | null;
}) {
  const parsed = parseLabValue(lab.value);
  const severity = classifySeverity(parsed, resolvedEntry, lab.flag, sex, ageYears);

  const refRange: ReferenceRange | null = resolvedEntry?.referenceRanges?.length
    ? selectReferenceRange(resolvedEntry.referenceRanges, sex, ageYears)
    : null;

  const displayValue = parsed.isNil
    ? "—"
    : `${parsed.operator ?? ""}${parsed.textNormalized ?? lab.value ?? "—"}`;

  const refText =
    refRange?.text ??
    (refRange?.low !== undefined && refRange?.high !== undefined
      ? `${refRange.low} – ${refRange.high}`
      : refRange?.low !== undefined
      ? `≥ ${refRange.low}`
      : refRange?.high !== undefined
      ? `≤ ${refRange.high}`
      : lab.reference_range ?? null);

  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
      <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text)" }}>{displayValue}</span>
      {lab.unit && (
        <span style={{ fontSize: 12, color: "var(--muted)", marginRight: 4 }}>{lab.unit}</span>
      )}
      <SeverityBadge severity={severity} flag={lab.flag} />
      {refText && (
        <span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 2 }}>
          ref: {refText}
        </span>
      )}
    </div>
  );
}

// ── Qualitative / ordinal ─────────────────────────────────────────────────────

function QualitativeView({ lab }: { lab: LabResult }) {
  const raw = (lab.value ?? "").trim();
  const isNil = !raw || raw === "-" || raw === "—";
  const lower = raw.toLowerCase();

  let color = "var(--text)";
  if (!isNil) {
    if (
      lower === "positive" ||
      lower === "prezent" ||
      lower === "reactiv" ||
      lower === "detected"
    ) {
      color = "var(--sev-abnormal-text)";
    } else if (
      lower === "negative" ||
      lower === "absent" ||
      lower === "non-reactiv" ||
      lower === "not detected"
    ) {
      color = "var(--sev-normal-text)";
    }
  }

  const abnormal = lab.is_abnormal || (lab.flag ? lab.flag.toLowerCase() !== "normal" && lab.flag.toLowerCase() !== "ok" && lab.flag.trim() !== "" : false);

  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
      <span style={{ fontSize: 15, fontWeight: 500, color: isNil ? "var(--muted)" : color }}>
        {isNil ? "—" : raw}
      </span>
      {!isNil && abnormal && <SeverityBadge severity="abnormal" flag={lab.flag} />}
    </div>
  );
}

// ── Narrative / free-text ─────────────────────────────────────────────────────

function NarrativeView({ lab }: { lab: LabResult }) {
  const raw = (lab.value ?? "").trim();
  if (!raw || raw === "-") {
    return <span style={{ color: "var(--muted)", fontSize: 14 }}>—</span>;
  }
  return (
    <p
      style={{
        margin: 0,
        fontSize: 13,
        color: "var(--text)",
        lineHeight: 1.55,
        whiteSpace: "pre-wrap",
      }}
    >
      {raw}
    </p>
  );
}

// ── Dispatcher ────────────────────────────────────────────────────────────────

export default function LabResultView({ lab, entry, sex, ageYears }: Props) {
  const resolvedEntry = resolveEntry(lab, entry);
  const vt = lab.value_type ?? resolvedEntry?.valueType ?? null;
  const displayName = resolveDisplayName(lab);

  let valueNode: React.ReactNode;

  switch (vt) {
    case "quantitative":
    case "semi_quantitative":
      valueNode = (
        <QuantitativeView
          lab={lab}
          resolvedEntry={resolvedEntry}
          sex={sex}
          ageYears={ageYears}
        />
      );
      break;
    case "qualitative":
    case "ordinal":
    case "categorical":
    case "microbiology":
      valueNode = <QualitativeView lab={lab} />;
      break;
    case "narrative":
    case "composite":
    case "panel":
    default:
      valueNode = <NarrativeView lab={lab} />;
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        alignItems: "start",
        gap: "2px 12px",
        padding: "10px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span
        style={{
          fontSize: 13,
          color: "var(--muted)",
          fontWeight: 500,
          gridColumn: "1",
          gridRow: "1",
        }}
      >
        {displayName}
        {lab.category && (
          <span style={{ fontWeight: 400, marginLeft: 6, opacity: 0.7 }}>· {lab.category}</span>
        )}
      </span>
      <div style={{ gridColumn: "1", gridRow: "2" }}>{valueNode}</div>
    </div>
  );
}
