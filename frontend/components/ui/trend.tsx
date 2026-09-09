"use client";

/**
 * Lab trend visuals.
 *
 * Two components, one visual language (shared with the ECharts theme):
 *
 *  - <Sparkline> - a ~26px inline SVG for a table row. Deliberately not
 *    ECharts: a patient with 50 analytes would otherwise instantiate 50 chart
 *    runtimes, which is what made the old chart page so heavy.
 *  - <TrendChart> - the expanded figure with axes, reference band, grid and
 *    hover readout, used when a clinician opens one analyte.
 *
 * Replaces the previous hand-rolled SVG which hard-coded `var(--primary,
 * #8b5cf6)` and a near-white text fallback, so labels were invisible in light
 * mode, and used font-weight 950 on every tick label.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { TrendPoint } from "@/lib/analytes/types";

function parseRange(range?: string | null): { low: number; high: number } | null {
  if (!range) return null;
  // Accepts "13-17", "13 - 17", "13.5–17.2", "< 5", "> 200".
  const between = range.match(/(-?\d+(?:[.,]\d+)?)\s*[-–—]\s*(-?\d+(?:[.,]\d+)?)/);
  if (between) {
    const low = Number(between[1].replace(",", "."));
    const high = Number(between[2].replace(",", "."));
    if (Number.isFinite(low) && Number.isFinite(high) && high > low) return { low, high };
  }
  return null;
}

/** True when a reference range is parseable, i.e. a band will be drawn. */
export function hasReferenceBand(range?: string | null) {
  return parseRange(range) !== null;
}

function isAbnormal(flag?: string | null) {
  const value = (flag || "").trim().toLowerCase();
  return value !== "" && value !== "normal" && value !== "n";
}

/* ==========================================================================
   Sparkline
   ========================================================================== */

export function Sparkline({
  points,
  height = 26,
  width = 120,
  tone,
}: {
  points: TrendPoint[];
  height?: number;
  width?: number;
  /** Colour by clinical state rather than always brand violet. */
  tone?: "brand" | "danger" | "muted";
}) {
  const path = useMemo(() => {
    if (points.length < 2) return null;

    const values = points.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || Math.max(Math.abs(max) * 0.2, 1);
    const pad = 3;

    const coords = points.map((point, index) => {
      const x = (index / (points.length - 1)) * (width - pad * 2) + pad;
      const y = height - pad - ((point.value - min) / span) * (height - pad * 2);
      return { x, y };
    });

    return {
      line: coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" "),
      last: coords[coords.length - 1],
    };
  }, [points, width, height]);

  const stroke =
    tone === "danger" ? "var(--danger)" : tone === "muted" ? "var(--faint)" : "var(--chart-1)";

  if (!path) {
    // A single reading is not a trend; say so rather than drawing a dot.
    return (
      <span className="b-range" style={{ display: "inline-block", lineHeight: `${height}px` }}>
        —
      </span>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      aria-hidden="true"
      style={{ display: "block", overflow: "visible" }}
    >
      <path d={path.line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={path.last.x} cy={path.last.y} r={2.2} fill={stroke} />
    </svg>
  );
}

/* ==========================================================================
   Expanded trend chart
   ========================================================================== */

export function TrendChart({
  points,
  unit,
  referenceRange,
  height = 220,
  onPointClick,
  highlightedDocumentId,
  formatDate,
}: {
  points: TrendPoint[];
  unit?: string | null;
  referenceRange?: string | null;
  height?: number;
  onPointClick?: (documentId: number) => void;
  highlightedDocumentId?: number | null;
  formatDate?: (value?: string | null) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);

  // Draw at the container's real pixel width so the SVG never has to be
  // distorted to fit, and text stays at its intended size at every
  // breakpoint.
  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next && next > 80) setWidth(Math.round(next));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const layout = useMemo(() => {
    if (!points.length) return null;

    // Tighter gutters when there is little width to spend.
    const compact = width < 460;
    const margin = {
      top: 14,
      right: compact ? 10 : 16,
      bottom: 26,
      left: compact ? 34 : 44,
    };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;

    const values = points.map((p) => p.value);
    const range = parseRange(referenceRange);

    // Include the reference band in the domain so it is always visible.
    const candidates = [...values, ...(range ? [range.low, range.high] : [])];
    const rawMin = Math.min(...candidates);
    const rawMax = Math.max(...candidates);
    const span = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.2, 1);
    // Clinical quantities are not negative: if every reading is >= 0, don't
    // let headroom padding put a negative number on the axis.
    const padded = rawMin - span * 0.12;
    const yMin = rawMin >= 0 ? Math.max(0, padded) : padded;
    const yMax = rawMax + span * 0.12;
    const yRange = yMax - yMin || 1;

    const toY = (value: number) => margin.top + plotH - ((value - yMin) / yRange) * plotH;
    const coords = points.map((point, index) => ({
      x: margin.left + (index * plotW) / Math.max(points.length - 1, 1),
      y: toY(point.value),
      point,
    }));

    return {
      width,
      margin,
      plotW,
      plotH,
      coords,
      yMin,
      yMax,
      yRange,
      toY,
      band: range
        ? { y: toY(range.high), h: Math.max(toY(range.low) - toY(range.high), 1), ...range }
        : null,
      compact,
      ticks: [0, 0.5, 1].map((t) => ({ y: margin.top + plotH * t, value: yMax - yRange * t })),
    };
  }, [points, referenceRange, height, width]);

  if (!layout) return null;

  const active =
    hover != null
      ? layout.coords[hover]
      : highlightedDocumentId != null
      ? layout.coords.find((c) => c.point.document_id === highlightedDocumentId) ?? null
      : null;

  const fmt = formatDate ?? ((value?: string | null) => value ?? "");

  return (
    <div
      ref={wrapRef}
      className="trend-chart-wrap"
      style={{ minHeight: height, padding: 0, border: 0, background: "transparent" }}
    >
      <svg
        viewBox={`0 0 ${layout.width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Trend of ${points.length} results${unit ? ` in ${unit}` : ""}`}
        style={{ display: "block", overflow: "visible" }}
      >
        {/* Reference range: a calm band, so "in range" is spatial rather than
            something the reader has to compute from a printed interval. */}
        {layout.band ? (
          <>
            <rect
              x={layout.margin.left}
              y={layout.band.y}
              width={layout.plotW}
              height={layout.band.h}
              fill="var(--chart-band)"
            />
            <text
              x={layout.margin.left + layout.plotW}
              y={layout.band.y - 3}
              textAnchor="end"
              fill="var(--chart-axis)"
              fontSize="9"
            >
              ref {layout.band.low}–{layout.band.high}
            </text>
          </>
        ) : null}

        {layout.ticks.map((tick, index) => (
          <g key={index}>
            <line
              x1={layout.margin.left}
              x2={layout.width - layout.margin.right}
              y1={tick.y}
              y2={tick.y}
              stroke="var(--chart-grid)"
              strokeWidth={1}
            />
            <text
              x={layout.margin.left - 7}
              y={tick.y + 3}
              textAnchor="end"
              fill="var(--chart-axis)"
              fontSize="9"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {Number(tick.value.toFixed(2))}
            </text>
          </g>
        ))}

        <path
          d={layout.coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x} ${c.y}`).join(" ")}
          fill="none"
          stroke="var(--chart-1)"
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {active ? (
          <line
            x1={active.x}
            x2={active.x}
            y1={layout.margin.top}
            y2={layout.margin.top + layout.plotH}
            stroke="var(--border-strong)"
            strokeDasharray="3 3"
          />
        ) : null}

        {layout.coords.map((c, index) => {
          const abnormal = isAbnormal(c.point.flag);
          const isActive = active?.point.document_id === c.point.document_id;
          return (
            <g key={`${c.point.document_id}-${index}`}>
              <circle
                cx={c.x}
                cy={c.y}
                r={isActive ? 4.5 : 3.2}
                fill={abnormal ? "var(--danger)" : "var(--chart-1)"}
                stroke="var(--surface)"
                strokeWidth={1.5}
              />
              {/* Generous invisible hit area - 3px dots are not a target. */}
              <circle
                cx={c.x}
                cy={c.y}
                r={14}
                fill="transparent"
                style={{ cursor: onPointClick ? "pointer" : "default" }}
                onMouseEnter={() => setHover(index)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onPointClick?.(c.point.document_id)}
              />
            </g>
          );
        })}

        {/* Date labels: first and last only, so they never collide. */}
        <text
          x={layout.margin.left}
          y={height - 8}
          fill="var(--chart-axis)"
          fontSize={layout.compact ? "8" : "9"}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {fmt(layout.coords[0]?.point.date)}
        </text>
        {layout.coords.length > 1 ? (
          <text
            x={layout.width - layout.margin.right}
            y={height - 8}
            textAnchor="end"
            fill="var(--chart-axis)"
            fontSize={layout.compact ? "8" : "9"}
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {fmt(layout.coords[layout.coords.length - 1]?.point.date)}
          </text>
        ) : null}
      </svg>

      {active ? (
        <div
          className="b-meta"
          style={{
            marginTop: 4,
            fontVariantNumeric: "tabular-nums",
            color: "var(--text-2)",
            textAlign: "center",
          }}
        >
          <strong style={{ color: "var(--text)", fontWeight: 600 }}>
            {active.point.value_display}
          </strong>
          {unit ? <span className="b-unit">{unit}</span> : null} · {fmt(active.point.date)}
          {active.point.reference_range ? (
            <span className="b-range"> · ref {active.point.reference_range}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
