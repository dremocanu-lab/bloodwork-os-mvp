"use client";

/**
 * Ask Bragi's inline lab-trend chart — reuses the SAME expanded
 * <TrendChart> Analize/Overview already use for a single analyte
 * (components/ui/trend.tsx), rather than a second, disconnected chart
 * implementation. That component already solves real axes, a reference
 * band (correctly omitted when points disagree on the range — see its
 * own "rangesAgree" check), a hover/tap/keyboard readout with value,
 * unit, date, reference range, and abnormal-flag text — all of which
 * this file used to hand-roll as a bare, unlabeled SVG line (see git
 * history for the old version this replaced).
 *
 * Every point's data is server-resolved (see
 * app/services/ask_bragi/service.py) — never generated client-side —
 * consistent with "the model may request a chart, never generate its
 * datapoints."
 */

import { TrendChart } from "@/components/ui/trend";
import type { TrendPoint } from "@/lib/analytes/types";
import { parseDateTime } from "@/lib/analytics/transform";
import type { AskBragiChart } from "@/lib/ask-bragi-api";

function formatChartDate(value?: string | null) {
  if (!value) return "—";
  const time = parseDateTime(value);
  if (!time) return value;
  return new Date(time).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function AskBragiChartView({
  chart,
  onPointClick,
}: {
  chart: AskBragiChart;
  onPointClick: (sourceEvidenceId: number) => void;
}) {
  // Only real, chartable observations: a numeric value and real row
  // identity (document_id/lab_result_id) to click through to — a point
  // missing either isn't something <TrendChart> (or a source link) can
  // do anything honest with.
  const points = chart.points
    .map((p) => ({
      ...p,
      numericValue: p.value != null ? Number(p.value.replace(",", ".")) : NaN,
    }))
    .filter((p) => Number.isFinite(p.numericValue) && p.document_id != null);

  if (points.length === 0) {
    return <p className="muted-text">No chartable values were found for &quot;{chart.canonical_name}&quot;.</p>;
  }

  // Do not silently combine incompatible units on one axis (BRAGI
  // product spec §36) — if the observations themselves disagree on
  // unit (a real data-quality signal, e.g. a lab switching assays),
  // say so rather than plotting a misleading single scale.
  const distinctUnits = Array.from(new Set(points.map((p) => p.unit).filter(Boolean)));
  if (distinctUnits.length > 1) {
    return (
      <p className="muted-text">
        {chart.canonical_name}: these observations use different units ({distinctUnits.join(", ")}) — plotting
        them on one axis would misrepresent the values, so no chart is shown. See the individual results below
        instead.
      </p>
    );
  }
  const unit = distinctUnits[0] ?? null;

  const trendPoints: TrendPoint[] = points.map((p) => ({
    document_id: p.document_id as number,
    lab_result_id: p.lab_result_id,
    date: p.date ?? "",
    value: p.numericValue,
    value_display: p.value ?? String(p.numericValue),
    flag: p.flag,
    reference_range: p.reference_range,
  }));

  const latest = points[points.length - 1];
  const hasAnyReferenceRange = points.some((p) => p.reference_range);

  function handlePointClick(documentId: number, labResultId?: number | null) {
    const match = points.find(
      (p) => p.document_id === documentId && (labResultId == null || p.lab_result_id === labResultId)
    );
    if (match?.source_evidence_id != null) onPointClick(match.source_evidence_id);
  }

  return (
    <div>
      <TrendChart
        points={trendPoints}
        unit={unit}
        referenceRange={latest.reference_range}
        onPointClick={handlePointClick}
        formatDate={formatChartDate}
      />
      <p className="muted-text" style={{ fontSize: "var(--fs-caption, 12px)", marginTop: 4 }}>
        {chart.canonical_name} · {points.length} point{points.length === 1 ? "" : "s"} · click a point to view its
        source
      </p>
      {!hasAnyReferenceRange ? (
        <p className="muted-text" style={{ fontSize: "var(--fs-caption, 12px)", margin: "2px 0 0" }}>
          Reference range not available in this source.
        </p>
      ) : null}
    </div>
  );
}
