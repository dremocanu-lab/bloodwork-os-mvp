export type ValueType =
  | 'quantitative'
  | 'qualitative'
  | 'semi_quantitative'
  | 'ordinal'
  | 'categorical'
  | 'narrative'
  | 'composite'
  | 'microbiology'
  | 'panel';

export type Specimen =
  | 'serum'
  | 'plasma'
  | 'urine'
  | 'csf'
  | 'pericardial'
  | 'peritoneal'
  | 'stool'
  | 'swab'
  | 'whole_blood'
  | 'tissue'
  | 'other';

export type ReferenceRange = {
  sex?: 'M' | 'F' | 'any';
  ageMin?: number;
  ageMax?: number;
  low?: number;
  high?: number;
  text?: string;
  unit?: string;
};

export type CriticalBand = {
  low?: number;
  high?: number;
  unit?: string;
};

export type CategoricalSystem = {
  system: string;
  version?: string;
  values: string[];
};

// API response shape for a single extracted lab row, plus optional client-side enrichment.
// Fields added by the analyte matcher (Phase 4) are optional and never sent to the backend.
export type LabResult = {
  id: number;
  raw_test_name?: string | null;
  canonical_name?: string | null;
  display_name?: string | null;
  category?: string | null;
  value?: string | null;
  flag?: string | null;
  reference_range?: string | null;
  unit?: string | null;
  is_abnormal?: boolean;
  // Populated client-side by the analyte matcher (never persisted):
  analyte_id?: string | null;
  value_type?: ValueType | null;
  specimen?: Specimen | null;
  needs_review?: boolean;
};

export type TrendPoint = {
  document_id: number;
  date: string;
  value: number;
  value_display: string;
  flag?: string | null;
  report_name?: string | null;
  reference_range?: string | null;
};

export type BloodworkTrend = {
  test_key: string;
  display_name: string;
  canonical_name?: string | null;
  category?: string | null;
  unit?: string | null;
  latest: TrendPoint;
  previous?: TrendPoint | null;
  delta?: number | null;
  points: TrendPoint[];
  // Populated client-side by the analyte matcher:
  analyte_id?: string | null;
  value_type?: ValueType | null;
};

export type AnalyteEntry = {
  id: string;
  loinc: string | null;
  canonicalName: { en: string; ro: string };
  aliases: string[];
  specimen: Specimen;
  valueType: ValueType;
  units?: {
    preferred: string;
    alternatives?: string[];
  };
  qualitativeValues?: string[];
  ordinalScale?: string[];
  categoricalSystem?: CategoricalSystem;
  referenceRanges?: ReferenceRange[];
  criticalBands?: CriticalBand[];
  panelMembers?: string[];
  trendIsClinicallyPrimary?: boolean;
  interpretationField?: 'none' | 'optional' | 'expected';
  needsReview?: boolean;
};
