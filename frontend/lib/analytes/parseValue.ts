import type { ReferenceRange, ValueType } from './types';

export type ParsedValue = {
  raw: string;
  /** Extracted numeric for quantitative results. Null when not parseable or nil. */
  numeric: number | null;
  /** Comparison operator extracted from the raw string, e.g. "<", ">", "≤", "≥". */
  operator: '<' | '>' | '≤' | '≥' | null;
  /** Normalized display string (stripped of redundant whitespace). */
  textNormalized: string | null;
  /** True when the raw value is empty, nil, or a dash placeholder. */
  isNil: boolean;
};

const NIL_TOKENS = new Set([
  '', '-', '--', '---', '—', '–', 'n/a', 'na', 'nil', 'null', 'none', 'nd',
  'not done', 'not tested', 'not detected', 'absent', 'negativ', 'negative',
]);

function isNilRaw(raw: string): boolean {
  const s = raw.trim().toLowerCase();
  if (NIL_TOKENS.has(s)) return true;
  if (/^[-–—]+$/.test(s)) return true;
  return false;
}

/**
 * Parse a raw lab value string into a structured representation.
 * Handles: numeric, operator-prefixed numeric (<, >, ≤, ≥),
 * comma-decimal (Romanian), ranges (takes first number), and qualitative text.
 */
export function parseLabValue(raw: string | null | undefined): ParsedValue {
  const nil: ParsedValue = { raw: '', numeric: null, operator: null, textNormalized: null, isNil: true };

  if (raw === null || raw === undefined) return nil;

  const trimmed = raw.trim();
  if (!trimmed || isNilRaw(trimmed)) return { ...nil, raw: trimmed };

  let operator: ParsedValue['operator'] = null;
  let remaining = trimmed;

  if (/^(>=|≥)/.test(remaining)) {
    operator = '≥';
    remaining = remaining.replace(/^(>=|≥)\s*/, '');
  } else if (/^(<=|≤)/.test(remaining)) {
    operator = '≤';
    remaining = remaining.replace(/^(<=|≤)\s*/, '');
  } else if (/^>/.test(remaining)) {
    operator = '>';
    remaining = remaining.replace(/^>\s*/, '');
  } else if (/^</.test(remaining)) {
    operator = '<';
    remaining = remaining.replace(/^<\s*/, '');
  }

  // Normalize Romanian comma decimal separator
  const normalized = remaining.replace(/,/g, '.');

  // Match first number — handles "3.5 - 10.2" by taking 3.5
  const match = normalized.match(/^([0-9]+(?:\.[0-9]+)?)/);
  const numeric = match ? parseFloat(match[1]) : null;

  return {
    raw: trimmed,
    numeric: numeric !== null && !Number.isNaN(numeric) ? numeric : null,
    operator,
    textNormalized: trimmed,
    isNil: false,
  };
}

/**
 * Check whether a parsed numeric value falls within a reference range.
 * Returns null when the value is nil or non-numeric.
 * Returns true when in range, false when out of range.
 */
export function isInRange(
  parsed: ParsedValue,
  range: Pick<ReferenceRange, 'low' | 'high'>,
): boolean | null {
  if (parsed.isNil || parsed.numeric === null) return null;
  const v = parsed.numeric;
  if (range.low !== undefined && v < range.low) return false;
  if (range.high !== undefined && v > range.high) return false;
  return true;
}

/**
 * Select the most applicable ReferenceRange entry for a patient's sex/age.
 * Falls back to the first 'any' range, then the first range overall.
 */
export function selectReferenceRange(
  ranges: ReferenceRange[] | undefined,
  sex?: 'M' | 'F' | null,
  ageYears?: number | null,
): ReferenceRange | null {
  if (!ranges?.length) return null;

  const candidates = ranges.filter((r) => {
    const sexOk = !r.sex || r.sex === 'any' || r.sex === sex;
    const ageOk =
      (r.ageMin === undefined || ageYears === null || ageYears === undefined || ageYears >= r.ageMin) &&
      (r.ageMax === undefined || ageYears === null || ageYears === undefined || ageYears <= r.ageMax);
    return sexOk && ageOk;
  });

  // Prefer sex-specific over 'any'
  const sexSpecific = candidates.find((r) => r.sex === sex);
  if (sexSpecific) return sexSpecific;

  const anyRange = candidates.find((r) => !r.sex || r.sex === 'any');
  if (anyRange) return anyRange;

  return candidates[0] ?? null;
}

/** True when the flag string indicates an out-of-range result. */
export function isAbnormalFlag(flag: string | null | undefined): boolean {
  const s = (flag ?? '').trim().toLowerCase();
  if (!s || s === 'normal' || s === 'none' || s === 'ok') return false;
  return ['high', 'low', 'abnormal', 'critical', 'borderline', 'elevated'].includes(s);
}

/** Derive an abnormality from numeric value + range when no flag is available. */
export function deriveFlag(
  parsed: ParsedValue,
  range: Pick<ReferenceRange, 'low' | 'high'> | null,
): 'High' | 'Low' | 'Normal' | null {
  if (parsed.isNil || parsed.numeric === null || !range) return null;
  const v = parsed.numeric;
  if (range.low !== undefined && v < range.low) return 'Low';
  if (range.high !== undefined && v > range.high) return 'High';
  return 'Normal';
}

/** Format a numeric value for display, trimming trailing zeros. */
export function formatNumeric(value: number | null, decimalPlaces = 2): string {
  if (value === null) return '—';
  const s = value.toFixed(decimalPlaces);
  return s.replace(/\.?0+$/, '');
}

/** Normalize a ValueType for display label purposes. */
export function valueTypeLabel(vt: ValueType | null | undefined): string {
  if (!vt) return 'Unknown';
  const labels: Record<ValueType, string> = {
    quantitative: 'Quantitative',
    qualitative: 'Qualitative',
    semi_quantitative: 'Semi-quantitative',
    ordinal: 'Ordinal',
    categorical: 'Categorical',
    narrative: 'Narrative',
    composite: 'Composite',
    microbiology: 'Microbiology',
    panel: 'Panel',
  };
  return labels[vt] ?? vt;
}
