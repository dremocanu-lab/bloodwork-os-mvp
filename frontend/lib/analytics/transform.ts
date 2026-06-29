import type { BloodworkTrend, TrendPoint } from "@/lib/analytes/types";
import type {
  AnalyticsDocument,
  AnalyticsLabStatus,
  AnalyticsLabValue,
  AnalyticsMedication,
  AnalyticsTrendDirection,
} from "@/lib/analytics/types";

// ── Input shapes (subset of API responses) ──────────────────────────────────

export type DocumentCardInput = {
  id: number;
  filename: string;
  report_name?: string | null;
  section: string;
  is_verified?: boolean;
  has_abnormal?: boolean;
  has_abnormal_labs?: boolean;
  reviewed_by_current_doctor?: boolean;
  collected_on?: string | null;
  test_date?: string | null;
  reported_on?: string | null;
  registered_on?: string | null;
  generated_on?: string | null;
  created_at?: string | null;
  uploaded_by?: { id: number; full_name: string } | null;
};

export type MedicationInput = {
  id: number;
  name: string;
  status: string;
  dose_strength?: string | null;
  frequency?: string | null;
  route_form?: string | null;
  reason?: string | null;
  is_uncertain?: boolean;
  official_match_status?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
};

// ── Constants ────────────────────────────────────────────────────────────────

export const ABNORMAL_FLAGS = new Set([
  "high",
  "low",
  "abnormal",
  "critical",
  "borderline",
  "elevated",
  "h",
  "l",
]);

const CATEGORY_DISPLAY: Record<string, string> = {
  "Hematologie": "Hemogramă",
  "Citomorfologie Manuala": "Citomorfologie",
  "Coagulare": "Coagulogramă",
  "Biochimie generala": "Biochimie",
  "Endocrinologie": "Endocrinologie",
  "Imunologie": "Imunologie",
  "Markeri tumorali": "Markeri tumorali",
  "Biologie moleculara generala": "Biologie moleculară",
  "Microbiologie": "Microbiologie",
};

const DEFAULT_CATEGORY_DISPLAY = "Analize medicale";

const DOCUMENT_TYPE_DISPLAY: Record<string, string> = {
  bloodwork: "Lab panel",
  discharge_summary: "Discharge summary",
  scans: "Imaging report",
  notes: "Clinical note",
  medications: "Medication document",
  hospitalizations: "Hospitalization record",
  other: "Other source record",
};

const DEFAULT_DOCUMENT_TYPE_DISPLAY = "Other source record";

// Subgroup keyword rules. First match wins (order matters).
const SUBGROUP_RULES: { subgroup: string; keywords: string[] }[] = [
  { subgroup: "CBC / Hemogramă", keywords: ["wbc", "rbc", "hemoglobina", "hb", "hematocrit", "mcv", "mch", "mchc", "rdw"] },
  { subgroup: "Differential", keywords: ["neutrofile", "neutrophile", "limfocite", "monocite", "eozinofile", "bazofile"] },
  { subgroup: "Platelets", keywords: ["trombocite", "plt"] },
  { subgroup: "Coagulation", keywords: ["pt", "inr", "aptt", "fibrinogen", "d-dimer", "ddimer"] },
  { subgroup: "Renal / Electrolytes", keywords: ["creatinina", "uree", "egfr", "acid uric", "na", "k", "cl"] },
  { subgroup: "Liver / Biliary", keywords: ["alt", "ast", "ggt", "fosfataza", "bilirubina", "ldh", "albumina"] },
  { subgroup: "Lipids", keywords: ["colesterol", "ldl", "hdl", "trigliceride"] },
  { subgroup: "Glucose / Metabolic", keywords: ["glicemie", "hba1c", "insulina"] },
  { subgroup: "Thyroid", keywords: ["tsh", "ft4", "ft3", "anti-tpo", "trab"] },
  { subgroup: "Iron / Vitamins", keywords: ["fier", "feritina", "transferina", "b12", "folat", "vitamina d"] },
  { subgroup: "Inflammation", keywords: ["crp", "vsh", "procalcitonina", "pcr"] },
  { subgroup: "Autoimmune", keywords: ["factor reumatoid", "ana", "anti-dsdna", "accp", "iga", "igg", "igm", "c3", "c4"] },
  { subgroup: "Serology", keywords: ["vdrl", "hbsag", "hcv", "hiv", "toxoplasma", "rubella", "cmv", "ebv"] },
  { subgroup: "Hormones", keywords: ["lh", "fsh", "estradiol", "testosteron", "prolactina", "pth", "cortizol"] },
  { subgroup: "Tumor Markers", keywords: ["psa", "cea", "ca19-9", "ca125", "ca15-3", "afp", "beta-hcg"] },
  { subgroup: "Molecular / PCR", keywords: ["pcr", "dna", "rna", "arn"] },
];

// ── Date helpers ─────────────────────────────────────────────────────────────

export function parseDateTime(value?: string | null): number {
  if (!value) return 0;
  const normalized = value.trim();
  const direct = new Date(normalized).getTime();
  if (!Number.isNaN(direct)) return direct;
  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);
  if (!match) return 0;
  const day = Number(match[1]);
  const month = Number(match[2]);
  const rawYear = Number(match[3]);
  const year = rawYear < 100 ? 2000 + rawYear : rawYear;
  const parsed = new Date(year, month - 1, day).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function formatDateLabel(value?: string | null): string {
  if (!value) return "—";
  const ms = parseDateTime(value);
  if (!ms) return value;
  return new Date(ms).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatMonthLabel(value?: string | null): string {
  if (!value) return "—";
  const ms = parseDateTime(value);
  if (!ms) return value;
  return new Date(ms).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}

function getDocumentDate(doc: DocumentCardInput): string {
  return (
    doc.collected_on ||
    doc.test_date ||
    doc.reported_on ||
    doc.registered_on ||
    doc.generated_on ||
    doc.created_at ||
    ""
  );
}

// ── Value / status helpers ───────────────────────────────────────────────────

function parseNumeric(value?: string | null): number | null {
  if (value === null || value === undefined) return null;
  const cleaned = String(value).replace(/,/g, ".").match(/-?\d+(\.\d+)?/);
  if (!cleaned) return null;
  const num = Number(cleaned[0]);
  return Number.isNaN(num) ? null : num;
}

export function parseReferenceRange(
  range?: string | null,
): { low: number | null; high: number | null } {
  if (!range) return { low: null, high: null };
  const match = range.match(/([0-9.,]+)\s*[-–]\s*([0-9.,]+)/);
  if (!match) return { low: null, high: null };
  const low = Number(match[1].replace(",", "."));
  const high = Number(match[2].replace(",", "."));
  return {
    low: Number.isNaN(low) ? null : low,
    high: Number.isNaN(high) ? null : high,
  };
}

function isAbnormalFlag(flag?: string | null): boolean {
  return !!flag && ABNORMAL_FLAGS.has(flag.toLowerCase());
}

function computeStatus(
  flag: string | null | undefined,
  referenceRange: string | null | undefined,
  valueNumeric: number | null,
): AnalyticsLabStatus {
  if (isAbnormalFlag(flag)) return "out_of_range";
  if (referenceRange && referenceRange.trim() !== "") return "in_range";
  if (valueNumeric !== null) return "no_reference_range";
  return "not_numeric";
}

export function mapCategoryDisplay(category?: string | null): string {
  if (!category || category.trim() === "") return DEFAULT_CATEGORY_DISPLAY;
  return CATEGORY_DISPLAY[category] || category;
}

export function mapDocumentTypeDisplay(section?: string | null): string {
  if (!section) return DEFAULT_DOCUMENT_TYPE_DISPLAY;
  return DOCUMENT_TYPE_DISPLAY[section] || DEFAULT_DOCUMENT_TYPE_DISPLAY;
}

export function resolveSubgroup(
  markerName: string,
  category?: string | null,
): string | null {
  const haystack = `${markerName} ${category || ""}`.toLowerCase();
  for (const rule of SUBGROUP_RULES) {
    for (const kw of rule.keywords) {
      // Word-ish boundary check to avoid matching "na" inside "creatinina" etc.
      const re = new RegExp(`(^|[^a-z0-9])${escapeRegExp(kw)}([^a-z0-9]|$)`, "i");
      if (re.test(haystack)) return rule.subgroup;
    }
  }
  return null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function computeTrendDirection(points: TrendPoint[]): AnalyticsTrendDirection {
  const numeric = [...points]
    .sort((a, b) => parseDateTime(a.date) - parseDateTime(b.date))
    .map((p) => parseNumeric(p.value_display))
    .filter((v): v is number => v !== null);
  if (numeric.length < 2) return "insufficient_data";
  const latest = numeric[numeric.length - 1];
  const prev = numeric[numeric.length - 2];
  if (latest > prev * 1.05) return "increased";
  if (latest < prev * 0.95) return "decreased";
  return "stable";
}

// ── Main transforms ──────────────────────────────────────────────────────────

/**
 * Build a flat list of AnalyticsLabValue rows from enriched BloodworkTrend[].
 * One row per (marker, date, document).
 */
export function buildAnalyticsLabValues(
  trends: BloodworkTrend[],
  documents: DocumentCardInput[],
): AnalyticsLabValue[] {
  const docById = new Map<number, DocumentCardInput>();
  for (const doc of documents) docById.set(doc.id, doc);

  const rows: AnalyticsLabValue[] = [];

  for (const trend of trends) {
    const markerName = trend.display_name || trend.test_key;
    const category = trend.category || "";
    const categoryDisplay = mapCategoryDisplay(category);
    const subgroup = resolveSubgroup(markerName, category);
    const trendDirection = computeTrendDirection(trend.points);

    for (const point of trend.points) {
      const doc = docById.get(point.document_id);
      const section = doc?.section || "bloodwork";
      const valueNumeric = parseNumeric(point.value_display);
      const refRange = point.reference_range ?? null;
      const { low, high } = parseReferenceRange(refRange);
      const status = computeStatus(point.flag, refRange, valueNumeric);

      rows.push({
        id: `${trend.test_key}_${point.date}_${point.document_id}`,
        marker_key: trend.test_key,
        marker_name: markerName,
        canonical_name: trend.canonical_name ?? null,
        category,
        category_display: categoryDisplay,
        subgroup,
        value_raw: point.value_display ?? null,
        value_numeric: valueNumeric,
        value_display: point.value_display || "—",
        unit: trend.unit ?? null,
        reference_range: refRange,
        reference_low: low,
        reference_high: high,
        flag: point.flag ?? null,
        status,
        trend: trendDirection,
        date: point.date,
        date_label: formatDateLabel(point.date),
        document_id: point.document_id,
        document_title:
          doc?.report_name || doc?.filename || point.report_name || `Document #${point.document_id}`,
        document_type: section,
        document_type_display: mapDocumentTypeDisplay(section),
        uploaded_by: doc?.uploaded_by?.full_name ?? null,
        verified: doc?.is_verified,
      });
    }
  }

  return rows;
}

/**
 * Build AnalyticsDocument[] (one per source document) with counts derived
 * from the lab values that reference each document.
 */
export function buildAnalyticsDocuments(
  documents: DocumentCardInput[],
  labValues: AnalyticsLabValue[],
): AnalyticsDocument[] {
  const valuesByDoc = new Map<number, AnalyticsLabValue[]>();
  for (const v of labValues) {
    const list = valuesByDoc.get(v.document_id) || [];
    list.push(v);
    valuesByDoc.set(v.document_id, list);
  }

  return documents.map((doc) => {
    const date = getDocumentDate(doc);
    const values = valuesByDoc.get(doc.id) || [];
    const outOfRange = values.filter((v) => v.status === "out_of_range").length;
    const isDischarge = doc.section === "discharge_summary";

    return {
      id: doc.id,
      title: doc.report_name || doc.filename || `Document #${doc.id}`,
      section: doc.section,
      document_type_display: mapDocumentTypeDisplay(doc.section),
      date,
      date_label: formatDateLabel(date),
      month_label: formatMonthLabel(date),
      uploaded_by: doc.uploaded_by?.full_name ?? null,
      extracted_values_count: values.length,
      out_of_range_count: outOfRange,
      verified: doc.is_verified,
      route: isDischarge ? `/documents/${doc.id}/discharge` : `/documents/${doc.id}`,
    };
  });
}

export function buildAnalyticsMedications(
  medications: MedicationInput[],
  patientId: string,
): AnalyticsMedication[] {
  return medications.map((med) => ({
    id: med.id,
    name: med.name,
    status: med.status,
    dose_strength: med.dose_strength ?? null,
    frequency: med.frequency ?? null,
    route_form: med.route_form ?? null,
    reason: med.reason ?? null,
    is_uncertain: med.is_uncertain,
    official_match_status: med.official_match_status ?? null,
    start_date: med.start_date ?? null,
    stop_date: med.stop_date ?? null,
    route: `/patients/${patientId}/medications/${med.id}`,
  }));
}

export function isAbnormalLabValue(v: AnalyticsLabValue): boolean {
  return v.status === "out_of_range";
}
