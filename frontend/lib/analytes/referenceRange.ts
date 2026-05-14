import type { AnalyteEntry, CriticalBand } from './types';
import type { ParsedValue } from './parseValue';

function isOutsideBand(numeric: number, band: CriticalBand): boolean {
  if (band.low !== undefined && numeric < band.low) return true;
  if (band.high !== undefined && numeric > band.high) return true;
  return false;
}

/** True when the numeric value falls outside any critical band defined for the analyte. */
export function isCriticalValue(parsed: ParsedValue, entry: AnalyteEntry): boolean {
  if (parsed.isNil || parsed.numeric === null) return false;
  if (!entry.criticalBands?.length) return false;
  return entry.criticalBands.some((band) => isOutsideBand(parsed.numeric!, band));
}
