import type { AnalyteEntry, BloodworkTrend, LabResult } from './types';
import { ANALYTE_CATALOG } from './catalog';

function stripDiacritics(text: string): string {
  return text.normalize('NFKD').replace(/[̀-ͯ]/g, '');
}

function normalizeText(text: string | null | undefined): string {
  if (!text) return '';
  let s = stripDiacritics(String(text)).toLowerCase();
  s = s
    .replace(/[μµ]/g, 'u')
    .replace(/×/g, 'x')
    .replace(/[–—]/g, '-')
    .replace(/[_:;,()[\]{}]/g, ' ')
    .replace(/[^a-z0-9%+#./\- ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return s;
}

function compactKey(text: string | null | undefined): string {
  return normalizeText(text).replace(/[^a-z0-9%#]/g, '');
}

const SCORE_EXACT = 100;
const SCORE_COMPACT = 98;
const SCORE_WORD_BOUNDARY = 88;
const SCORE_SUBSTRING_LONG = 72;
const SCORE_REVERSE_SUBSTRING = 62;
const SCORE_THRESHOLD = 62;

function scoreCandidate(input: string, inputCompact: string, candidate: string): number {
  const norm = normalizeText(candidate);
  if (!norm) return 0;

  if (input === norm) return SCORE_EXACT;

  const compact = compactKey(candidate);
  if (inputCompact && inputCompact === compact) return SCORE_COMPACT;

  // Word-boundary containment: all words of the shorter appear in the longer
  if (norm.length >= 3) {
    const words = norm.split(' ').filter(Boolean);
    if (words.length && words.every((w) => input.includes(w))) return SCORE_WORD_BOUNDARY;
  }

  if (norm.length >= 4 && input.includes(norm)) return SCORE_SUBSTRING_LONG;
  if (input.length >= 4 && norm.includes(input)) return SCORE_REVERSE_SUBSTRING;

  return 0;
}

/**
 * Find the best-matching AnalyteEntry for a given canonical/raw name pair.
 * Returns null if no match exceeds the confidence threshold.
 */
export function findAnalyteEntry(
  canonicalName: string | null | undefined,
  rawName?: string | null,
  catalog: AnalyteEntry[] = ANALYTE_CATALOG,
): AnalyteEntry | null {
  const primary = normalizeText(canonicalName);
  const fallback = normalizeText(rawName);
  const input = primary || fallback;
  if (!input) return null;

  const inputCompact = compactKey(input);

  let best: AnalyteEntry | null = null;
  let bestScore = 0;

  for (const entry of catalog) {
    const candidates = [entry.canonicalName.en, entry.canonicalName.ro, ...entry.aliases];

    for (const candidate of candidates) {
      const score = scoreCandidate(input, inputCompact, candidate);
      if (score > bestScore) {
        bestScore = score;
        best = entry;
      }
    }
  }

  return bestScore >= SCORE_THRESHOLD ? best : null;
}

/** Enrich a single LabResult with catalog-matched metadata. */
export function enrichLabResult(
  lab: LabResult,
  catalog: AnalyteEntry[] = ANALYTE_CATALOG,
): LabResult {
  const entry = findAnalyteEntry(lab.canonical_name, lab.raw_test_name, catalog);
  if (!entry) return lab;
  return {
    ...lab,
    analyte_id: entry.id,
    value_type: entry.valueType,
    specimen: entry.specimen,
    needs_review: entry.needsReview ?? false,
  };
}

/** Enrich a BloodworkTrend with catalog-matched metadata. */
export function enrichBloodworkTrend(
  trend: BloodworkTrend,
  catalog: AnalyteEntry[] = ANALYTE_CATALOG,
): BloodworkTrend {
  const entry = findAnalyteEntry(trend.canonical_name, trend.display_name, catalog);
  if (!entry) return trend;
  return {
    ...trend,
    analyte_id: entry.id,
    value_type: entry.valueType,
  };
}

/** Enrich an array of LabResults in one pass. */
export function enrichLabResults(
  labs: LabResult[],
  catalog: AnalyteEntry[] = ANALYTE_CATALOG,
): LabResult[] {
  return labs.map((lab) => enrichLabResult(lab, catalog));
}
