// Transform-layer types for the Patient Analytics workspace.
// These shapes are derived client-side from BloodworkTrend[] + DocumentCard[]
// and are never sent to the backend.

export type AnalyticsLabStatus =
  | "in_range"
  | "out_of_range"
  | "no_reference_range"
  | "qualitative"
  | "not_numeric";

export type AnalyticsTrendDirection =
  | "increased"
  | "decreased"
  | "stable"
  | "insufficient_data";

export type AnalyticsLabValue = {
  id: string; // `${test_key}_${date}_${document_id}`
  marker_key: string;
  marker_name: string;
  canonical_name?: string | null;
  category: string;
  category_display: string;
  subgroup?: string | null;
  value_raw?: string | null;
  value_numeric?: number | null;
  value_display: string;
  unit?: string | null;
  reference_range?: string | null;
  reference_low?: number | null;
  reference_high?: number | null;
  flag?: string | null;
  status: AnalyticsLabStatus;
  trend?: AnalyticsTrendDirection;
  date: string;
  date_label: string;
  document_id: number;
  document_title: string;
  document_type: string;
  document_type_display: string;
  uploaded_by?: string | null;
  verified?: boolean;
};

export type AnalyticsDocument = {
  id: number;
  title: string;
  section: string;
  document_type_display: string;
  date: string;
  date_label: string;
  month_label: string;
  uploaded_by?: string | null;
  extracted_values_count: number;
  out_of_range_count: number;
  verified?: boolean;
  route: string;
};

export type AnalyticsMedication = {
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
  route: string;
};
