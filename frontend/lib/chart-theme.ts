/**
 * Bragi chart theme.
 *
 * One visual voice for every chart in the product, whether it is an ECharts
 * figure on the Analytics page or a hand-drawn SVG sparkline in a lab-trend
 * row: same series palette, same grid weight, same axis type, same tooltip.
 *
 * Colours are read from the CSS custom properties at call time, so charts
 * follow light/dark automatically instead of hard-coding hex values (the
 * previous charts baked in `#8b5cf6` and a `--foreground` fallback of
 * `#f8fafc`, which rendered near-white text on white in light mode).
 */

export type ChartTokens = {
  series: string[];
  grid: string;
  axis: string;
  text: string;
  muted: string;
  surface: string;
  border: string;
  band: string;
  ok: string;
  warn: string;
  danger: string;
};

const FALLBACK: ChartTokens = {
  series: ["#6d5dfc", "#0e8f9e", "#c2650c", "#c02a72", "#2563eb", "#0b7a53"],
  grid: "#eef1f6",
  axis: "#93a1b5",
  text: "#0f172a",
  muted: "#64748b",
  surface: "#ffffff",
  border: "#e3e8f0",
  band: "rgba(109, 93, 252, 0.07)",
  ok: "#087f5b",
  warn: "#b45309",
  danger: "#b42318",
};

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string) {
  const value = styles.getPropertyValue(name).trim();
  return value || fallback;
}

/** Resolve the current theme's chart tokens. Safe during SSR. */
export function getChartTokens(): ChartTokens {
  if (typeof window === "undefined") return FALLBACK;

  const styles = getComputedStyle(document.documentElement);

  return {
    series: [1, 2, 3, 4, 5, 6].map((n) =>
      readVar(styles, `--chart-${n}`, FALLBACK.series[n - 1])
    ),
    grid: readVar(styles, "--chart-grid", FALLBACK.grid),
    axis: readVar(styles, "--chart-axis", FALLBACK.axis),
    text: readVar(styles, "--text", FALLBACK.text),
    muted: readVar(styles, "--muted", FALLBACK.muted),
    surface: readVar(styles, "--surface", FALLBACK.surface),
    border: readVar(styles, "--border", FALLBACK.border),
    band: readVar(styles, "--chart-band", FALLBACK.band),
    ok: readVar(styles, "--ok", FALLBACK.ok),
    warn: readVar(styles, "--warn", FALLBACK.warn),
    danger: readVar(styles, "--danger", FALLBACK.danger),
  };
}

const FONT =
  'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';

/**
 * Base ECharts option shared by every chart. Spread this first, then add the
 * series and any per-chart overrides:
 *
 *   { ...baseChartOption(), series: [...] }
 */
export function baseChartOption(tokens: ChartTokens = getChartTokens()) {
  return {
    color: tokens.series,
    backgroundColor: "transparent",
    animationDuration: 320,
    animationEasing: "cubicOut" as const,
    textStyle: {
      fontFamily: FONT,
      fontSize: 11,
      color: tokens.muted,
    },
    grid: {
      left: 8,
      right: 12,
      top: 18,
      bottom: 6,
      containLabel: true,
    },
    tooltip: {
      trigger: "axis" as const,
      backgroundColor: tokens.surface,
      borderColor: tokens.border,
      borderWidth: 1,
      padding: [7, 10],
      textStyle: {
        color: tokens.text,
        fontFamily: FONT,
        fontSize: 12,
      },
      extraCssText:
        "border-radius:6px;box-shadow:0 4px 12px rgba(15,23,42,.1);font-variant-numeric:tabular-nums;",
      axisPointer: {
        type: "line" as const,
        lineStyle: { color: tokens.axis, width: 1, type: "dashed" as const },
      },
    },
    legend: {
      icon: "roundRect",
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 14,
      textStyle: { color: tokens.muted, fontFamily: FONT, fontSize: 11 },
    },
  };
}

/** Category axis with a hairline baseline and no tick marks. */
export function categoryAxis(tokens: ChartTokens = getChartTokens()) {
  return {
    type: "category" as const,
    boundaryGap: false,
    axisLine: { lineStyle: { color: tokens.border } },
    axisTick: { show: false },
    axisLabel: { color: tokens.axis, fontSize: 10, fontFamily: FONT, hideOverlap: true },
    splitLine: { show: false },
  };
}

/** Value axis: no axis line, just faint horizontal rules. */
export function valueAxis(tokens: ChartTokens = getChartTokens()) {
  return {
    type: "value" as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: tokens.axis, fontSize: 10, fontFamily: FONT },
    splitLine: { lineStyle: { color: tokens.grid, width: 1 } },
  };
}

/** A line series in the Bragi style: 1.75px stroke, small markers, soft fill. */
export function lineSeries(
  name: string,
  data: (number | null)[],
  options: { index?: number; area?: boolean; tokens?: ChartTokens } = {}
) {
  const tokens = options.tokens ?? getChartTokens();
  const color = tokens.series[(options.index ?? 0) % tokens.series.length];

  return {
    name,
    type: "line" as const,
    data,
    smooth: false,
    symbol: "circle",
    symbolSize: 5,
    showSymbol: data.filter((v) => v != null).length <= 24,
    connectNulls: true,
    lineStyle: { width: 1.75, color },
    itemStyle: { color, borderColor: tokens.surface, borderWidth: 1.5 },
    emphasis: { focus: "series" as const, scale: 1.25 },
    ...(options.area
      ? {
          areaStyle: {
            opacity: 0.08,
            color,
          },
        }
      : null),
  };
}

/**
 * Series palette as CSS custom-property references.
 *
 * ECharts resolves `var(--chart-1)` when it paints into the DOM, so charts
 * declared with these follow the active theme without re-reading tokens on
 * every theme change. Use this for ECharts options; use `getChartTokens()`
 * when you need concrete values (canvas maths, SVG you build yourself).
 */
export const CHART_SERIES = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];
