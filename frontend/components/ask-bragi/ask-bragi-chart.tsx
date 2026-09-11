"use client";

/**
 * A restrained inline chart for one Ask-Bragi-resolved lab trend.
 *
 * Deliberately NOT the shared <TrendChart> (components/ui/trend.tsx) —
 * that component's contract (TrendPoint: numeric value + a mandatory
 * document_id per point, click-through keyed by document+lab-result id)
 * doesn't match what the backend already resolves here (a
 * source_evidence_id per point, string-valued lab results). Re-shaping
 * one into the other would cost an extra round-trip per point for no
 * real benefit — this reuses the same visual language (chart-theme.ts
 * tokens) instead of a second, disconnected style.
 *
 * Every point's data is server-resolved (see
 * app/services/ask_bragi/service.py) — never generated client-side —
 * consistent with "the model may request a chart, never generate its
 * datapoints."
 */

import { getChartTokens } from "@/lib/chart-theme";
import type { AskBragiChart } from "@/lib/ask-bragi-api";

const WIDTH = 480;
const HEIGHT = 160;
const PAD = 28;

export function AskBragiChartView({
  chart,
  onPointClick,
}: {
  chart: AskBragiChart;
  onPointClick: (sourceEvidenceId: number) => void;
}) {
  const tokens = getChartTokens();
  const numericPoints = chart.points
    .map((p) => ({ ...p, numericValue: p.value != null ? Number(p.value.replace(",", ".")) : NaN }))
    .filter((p) => Number.isFinite(p.numericValue));

  if (numericPoints.length === 0) {
    return <p className="muted-text">No chartable values were found for &quot;{chart.canonical_name}&quot;.</p>;
  }

  const values = numericPoints.map((p) => p.numericValue);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const stepX = numericPoints.length > 1 ? (WIDTH - PAD * 2) / (numericPoints.length - 1) : 0;
  const coords = numericPoints.map((p, i) => {
    const x = PAD + i * stepX;
    const y = HEIGHT - PAD - ((p.numericValue - min) / range) * (HEIGHT - PAD * 2);
    return { ...p, x, y };
  });

  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");

  return (
    <div>
      <svg
        role="img"
        aria-label={`Trend chart for ${chart.canonical_name}, ${numericPoints.length} points`}
        width="100%"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ maxWidth: WIDTH, display: "block" }}
      >
        <line x1={PAD} y1={HEIGHT - PAD} x2={WIDTH - PAD} y2={HEIGHT - PAD} stroke={tokens.border} strokeWidth={1} />
        <path d={path} fill="none" stroke={tokens.series[0]} strokeWidth={2} />
        {coords.map((c) => {
          const abnormal = (c.flag || "").trim() && (c.flag || "").toLowerCase() !== "normal";
          return (
            <g key={`${c.source_evidence_id}-${c.date}`}>
              <circle
                cx={c.x}
                cy={c.y}
                r={5}
                fill={abnormal ? tokens.danger : tokens.series[0]}
                stroke={tokens.surface}
                strokeWidth={1.5}
                style={{ cursor: c.source_evidence_id ? "pointer" : "default" }}
                onClick={() => c.source_evidence_id && onPointClick(c.source_evidence_id)}
              >
                <title>
                  {c.date}: {c.value} {c.unit}
                  {abnormal ? ` (${c.flag})` : ""}
                </title>
              </circle>
            </g>
          );
        })}
      </svg>
      <p className="muted-text" style={{ fontSize: "var(--fs-caption, 12px)", marginTop: 4 }}>
        {chart.canonical_name} · {numericPoints.length} point{numericPoints.length === 1 ? "" : "s"} · click a point to view its source
      </p>
    </div>
  );
}
