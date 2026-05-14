import type { AnalyteEntry } from './analytes/types';
import type { ParsedValue } from './analytes/parseValue';
import { isCriticalValue } from './analytes/referenceRange';
import { isInRange, selectReferenceRange, isAbnormalFlag, deriveFlag } from './analytes/parseValue';

export type Severity = 'critical' | 'abnormal' | 'borderline' | 'normal' | 'nil' | 'unknown';

export type SeverityStyle = {
  bg: string;
  text: string;
  border: string;
};

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 5,
  abnormal: 4,
  borderline: 3,
  normal: 2,
  unknown: 1,
  nil: 0,
};

/** Numeric rank so severities can be compared (higher = more severe). */
export function severityRank(s: Severity): number {
  return SEVERITY_RANK[s];
}

/**
 * Classify a lab result into a severity level.
 * Uses critical bands first, then flag field, then numeric vs reference range.
 */
export function classifySeverity(
  parsed: ParsedValue,
  entry: AnalyteEntry | null,
  flag?: string | null,
  sex?: 'M' | 'F' | null,
  ageYears?: number | null,
): Severity {
  if (parsed.isNil) return 'nil';

  if (entry && isCriticalValue(parsed, entry)) return 'critical';

  if (flag && isAbnormalFlag(flag)) return 'abnormal';

  if (entry?.referenceRanges?.length) {
    const range = selectReferenceRange(entry.referenceRanges, sex, ageYears);
    if (range) {
      const inRange = isInRange(parsed, range);
      if (inRange === false) {
        const derived = deriveFlag(parsed, range);
        if (derived === 'High' || derived === 'Low') return 'abnormal';
      }
      if (inRange === true) return 'normal';
    }
  }

  if (parsed.numeric !== null) return 'unknown';
  return 'unknown';
}

/** CSS token values for a given severity level. */
export function getSeverityStyle(severity: Severity): SeverityStyle {
  switch (severity) {
    case 'critical':
      return {
        bg: 'var(--sev-critical-bg)',
        text: 'var(--sev-critical-text)',
        border: 'var(--sev-critical-border)',
      };
    case 'abnormal':
      return {
        bg: 'var(--sev-abnormal-bg)',
        text: 'var(--sev-abnormal-text)',
        border: 'var(--sev-abnormal-border)',
      };
    case 'borderline':
      return {
        bg: 'var(--sev-borderline-bg)',
        text: 'var(--sev-borderline-text)',
        border: 'var(--sev-borderline-border)',
      };
    case 'normal':
      return {
        bg: 'var(--sev-normal-bg)',
        text: 'var(--sev-normal-text)',
        border: 'var(--sev-normal-border)',
      };
    default:
      return {
        bg: 'var(--panel-2)',
        text: 'var(--muted)',
        border: 'var(--border)',
      };
  }
}
