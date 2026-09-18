"use client";

/**
 * Clinical Reader Intelligence V2 — small, focused display components
 * for the AI Clinical Document Interpreter's grounded output
 * (diagnoses/investigations/recommendations/anomalies/overview). Every
 * item rendered here comes straight from `StructuredClinicalDocument`
 * fields the backend already validated (see
 * backend/app/services/clinical_document/ai_interpreter.py's grounding
 * contract) — these components never invent, reformat, or "clean up"
 * clinical wording; they only choose WHERE and HOW to lay out what the
 * backend already produced.
 *
 * Every one of these renders nothing (returns null) when its input
 * array is empty — Clinical Reader Intelligence V2 Part 13's "don't
 * show a section with nothing meaningful in it" rule applies at the
 * component level too, not just the outline.
 */

import { useLanguage } from "@/lib/i18n";
import { IconAlert } from "@/components/ui/icon";
import type {
  AnomalyFlag,
  ClinicalEvent,
  ClinicalReaderResponse,
  CurrentEncounter,
  Diagnosis,
  DiagnosisRole,
  Investigation,
  InvestigationType,
  RecommendationCategory,
  RecommendationItem,
  TreatmentEra,
} from "@/lib/clinical-document-schema";
import { LabValue } from "@/components/ui";
import { MultiSourceAction, ReaderSourceAction } from "./reader-source-action";

const DIAGNOSIS_ROLE_LABEL: Record<DiagnosisRole, { en: string; ro: string }> = {
  principal: { en: "Primary diagnosis", ro: "Diagnostic principal" },
  secondary: { en: "Secondary diagnosis", ro: "Diagnostic secundar" },
  historical: { en: "Historical diagnosis", ro: "Diagnostic istoric" },
};

const INVESTIGATION_TYPE_LABEL: Record<InvestigationType, { en: string; ro: string }> = {
  imaging: { en: "Imaging", ro: "Imagistică" },
  molecular: { en: "Molecular", ro: "Molecular" },
  pathology: { en: "Pathology", ro: "Anatomopatologie" },
  ecg: { en: "ECG", ro: "EKG" },
  procedure: { en: "Procedure", ro: "Procedură" },
  other: { en: "Other", ro: "Altele" },
};

const RECOMMENDATION_CATEGORY_LABEL: Record<RecommendationCategory, { en: string; ro: string }> = {
  activity: { en: "Activity", ro: "Activitate" },
  hydration: { en: "Hydration", ro: "Hidratare" },
  diet: { en: "Diet", ro: "Dietă" },
  precautions: { en: "Precautions", ro: "Precauții" },
  follow_up: { en: "Follow-up", ro: "Control" },
  medication_recommendation: { en: "Medication", ro: "Medicație" },
  specialist_follow_up: { en: "Specialist follow-up", ro: "Control de specialitate" },
  other: { en: "Other", ro: "Altele" },
};

function useLang() {
  const { language } = useLanguage();
  return language === "ro" ? "ro" : "en";
}

export function DiagnosisList({
  diagnoses,
  documentContentType,
}: {
  diagnoses: Diagnosis[];
  documentContentType?: string | null;
}) {
  const lang = useLang();
  if (!diagnoses.length) return null;

  const order: DiagnosisRole[] = ["principal", "secondary", "historical"];
  const byRole = order.map((role) => ({ role, items: diagnoses.filter((d) => d.role === role) })).filter((g) => g.items.length);

  return (
    <div className="b-diag-list">
      <style jsx>{`
        .b-diag-list {
          display: flex;
          flex-direction: column;
          gap: var(--s4);
        }
        .b-diag-group-label {
          margin: 0 0 var(--s2);
        }
        .b-diag-card {
          display: flex;
          align-items: baseline;
          gap: var(--s3);
          padding: var(--s3);
          border: 1px solid var(--border);
          border-radius: var(--r-md);
          background: var(--surface);
        }
        .b-diag-code {
          flex-shrink: 0;
          font-weight: 700;
          font-size: var(--fs-caption);
          color: var(--primary);
          background: var(--primary-soft);
          border: 1px solid var(--primary-soft-border);
          border-radius: var(--r-md);
          padding: 2px 8px;
        }
        .b-diag-text {
          flex: 1;
          min-width: 0;
        }
      `}</style>
      {byRole.map(({ role, items }) => (
        <div key={role}>
          <h4 className="b-label b-diag-group-label">{DIAGNOSIS_ROLE_LABEL[role][lang]}</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
            {items.map((d) => (
              <div key={d.id} className="b-diag-card">
                {d.code ? <span className="b-diag-code">{d.code}</span> : null}
                <span className="b-diag-text">{d.text}</span>
                <ReaderSourceAction
                  sourceEvidenceId={d.source_evidence_ids[0] ?? null}
                  documentContentType={documentContentType}
                />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function InvestigationCards({
  investigations,
  documentContentType,
}: {
  investigations: Investigation[];
  documentContentType?: string | null;
}) {
  const lang = useLang();
  if (!investigations.length) return null;

  return (
    <div className="b-invest-list">
      <style jsx>{`
        .b-invest-list {
          display: flex;
          flex-direction: column;
          gap: var(--s3);
        }
        .b-invest-card {
          padding: var(--s4);
          border: 1px solid var(--border);
          border-radius: var(--r-lg);
          background: var(--surface);
        }
        .b-invest-title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--s2);
          margin-bottom: var(--s2);
        }
        .b-invest-title {
          display: flex;
          align-items: center;
          gap: var(--s2);
          font-weight: 600;
          min-width: 0;
        }
        .b-invest-type-badge {
          font-size: var(--fs-caption);
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.02em;
        }
        .b-invest-label {
          font-size: var(--fs-caption);
          color: var(--muted);
          margin: var(--s2) 0 2px;
        }
      `}</style>
      {investigations.map((investigation) => (
        <div key={investigation.id} className="b-invest-card">
          <div className="b-invest-title-row">
            <div className="b-invest-title">
              <span>{investigation.title}</span>
              <span className="b-invest-type-badge">{INVESTIGATION_TYPE_LABEL[investigation.investigation_type][lang]}</span>
            </div>
            <ReaderSourceAction
              sourceEvidenceId={investigation.source_evidence_ids[0] ?? null}
              documentContentType={documentContentType}
            />
          </div>
          {investigation.findings ? (
            <>
              <div className="b-invest-label">{lang === "ro" ? "Constatări" : "Findings"}</div>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{investigation.findings}</p>
            </>
          ) : null}
          {investigation.conclusion ? (
            <>
              <div className="b-invest-label">{lang === "ro" ? "Concluzie" : "Conclusion"}</div>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{investigation.conclusion}</p>
            </>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function RecommendationList({
  recommendations,
  documentContentType,
}: {
  recommendations: RecommendationItem[];
  documentContentType?: string | null;
}) {
  const lang = useLang();
  if (!recommendations.length) return null;

  const byCategory = new Map<RecommendationCategory, RecommendationItem[]>();
  for (const item of recommendations) {
    const list = byCategory.get(item.category) || [];
    list.push(item);
    byCategory.set(item.category, list);
  }

  return (
    <div className="b-rec-list">
      <style jsx>{`
        .b-rec-list {
          display: flex;
          flex-direction: column;
          gap: var(--s3);
        }
        .b-rec-group-label {
          margin: 0 0 var(--s1);
        }
        .b-rec-item {
          margin-bottom: 4px;
        }
        .b-rec-item-row {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: var(--s2);
        }
      `}</style>
      {Array.from(byCategory.entries()).map(([category, items]) => (
        <div key={category}>
          <h4 className="b-label b-rec-group-label">{RECOMMENDATION_CATEGORY_LABEL[category][lang]}</h4>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {items.map((item) => (
              <li key={item.id} className="b-rec-item">
                <div className="b-rec-item-row">
                  <span>{item.text}</span>
                  <ReaderSourceAction
                    sourceEvidenceId={item.source_evidence_ids[0] ?? null}
                    documentContentType={documentContentType}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function AnomalyWarnings({
  anomalies,
  documentContentType,
}: {
  anomalies: AnomalyFlag[];
  documentContentType?: string | null;
}) {
  const lang = useLang();
  if (!anomalies.length) return null;

  return (
    <div className="b-anomaly-list">
      <style jsx>{`
        .b-anomaly-list {
          display: flex;
          flex-direction: column;
          gap: var(--s2);
        }
        .b-anomaly-item {
          display: flex;
          gap: var(--s2);
          padding: var(--s3);
          border-radius: var(--r-md);
          background: var(--warn-bg, rgba(176, 137, 0, 0.08));
          border: 1px solid var(--warn, #b08900);
          color: var(--text);
          font-size: var(--fs-caption);
          align-items: flex-start;
        }
        .b-anomaly-body {
          flex: 1;
          min-width: 0;
        }
        .b-anomaly-original {
          font-family: var(--font-mono, monospace);
          color: var(--muted);
        }
        .b-anomaly-action {
          margin-top: 4px;
        }
      `}</style>
      {anomalies.map((anomaly) => (
        <div key={anomaly.id} className="b-anomaly-item">
          <IconAlert size={14} />
          <div className="b-anomaly-body">
            <div>
              {lang === "ro" ? "Posibilă inconsistență în sursă" : "Possible source inconsistency"}: {anomaly.message}
            </div>
            {anomaly.original_value ? (
              <div className="b-anomaly-original">
                {lang === "ro" ? "Valoare originală" : "Original value"}: {anomaly.original_value}
              </div>
            ) : null}
            <div className="b-anomaly-action">
              <ReaderSourceAction
                sourceEvidenceId={anomaly.source_evidence_ids[0] ?? null}
                documentContentType={documentContentType}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** A compact, structured (never one giant LLM paragraph) clinical
 * overview — Part 7A. Every item here is a pointer into data that's
 * ALREADY rendered in full elsewhere in the reader; this panel is a
 * navigational/orientation summary, not a second source of truth. */
export function OverviewPanel({
  currentEncounter,
  metadata,
  diagnoses,
  labs,
  investigations,
  recommendations,
  interpretationStatus,
}: {
  currentEncounter: CurrentEncounter | null;
  metadata: { admission_date: string | null; discharge_date: string | null };
  diagnoses: Diagnosis[];
  labs: ClinicalReaderResponse["labs"];
  investigations: Investigation[];
  recommendations: RecommendationItem[];
  interpretationStatus: string | null;
}) {
  const lang = useLang();
  const admission = currentEncounter?.admission_date || metadata.admission_date;
  const discharge = currentEncounter?.discharge_date || metadata.discharge_date;
  const principalDiagnosis = diagnoses.find((d) => d.role === "principal");
  const abnormalLabs = labs
    .filter((l) => {
      const flag = l.flag?.toUpperCase();
      return flag === "H" || flag === "L" || flag?.startsWith("H") || flag?.startsWith("L");
    })
    .slice(0, 6);

  return (
    <div className="b-overview">
      <style jsx>{`
        .b-overview {
          display: flex;
          flex-direction: column;
          gap: var(--s4);
        }
        .b-overview-block {
          padding: var(--s3) 0;
          border-bottom: 1px solid var(--border);
        }
        .b-overview-block:last-child {
          border-bottom: none;
        }
        .b-overview-label {
          margin: 0 0 4px;
        }
        .b-overview-value {
          font-size: var(--fs-h2);
          font-weight: 600;
        }
      `}</style>

      <div className="b-overview-block">
        <h4 className="b-label b-overview-label">{lang === "ro" ? "Internare" : "Hospitalization"}</h4>
        <div className="b-overview-value">
          {admission || "—"} {discharge ? `→ ${discharge}` : ""}
        </div>
      </div>

      {principalDiagnosis ? (
        <div className="b-overview-block">
          <h4 className="b-label b-overview-label">{lang === "ro" ? "Diagnostic principal" : "Primary diagnosis"}</h4>
          <div className="b-overview-value">
            {principalDiagnosis.code ? `${principalDiagnosis.code} — ` : ""}
            {principalDiagnosis.text}
          </div>
        </div>
      ) : null}

      {abnormalLabs.length ? (
        <div className="b-overview-block">
          <h4 className="b-label b-overview-label">{lang === "ro" ? "Rezultate recente anormale" : "Recent abnormal results"}</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {abnormalLabs.map((lab) => (
              <div key={lab.id} style={{ display: "flex", justifyContent: "space-between", gap: "var(--s3)", alignItems: "center" }}>
                <span>{lab.display_name || lab.canonical_name || lab.raw_test_name}</span>
                <LabValue value={lab.value} unit={lab.unit} flag={lab.flag} />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {investigations.length ? (
        <div className="b-overview-block">
          <h4 className="b-label b-overview-label">{lang === "ro" ? "Investigații principale" : "Key investigations"}</h4>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {investigations.slice(0, 4).map((investigation) => (
              <li key={investigation.id}>{investigation.title}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {recommendations.length ? (
        <div className="b-overview-block">
          <h4 className="b-label b-overview-label">{lang === "ro" ? "Recomandări" : "Recommendations"}</h4>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {recommendations.slice(0, 5).map((item) => (
              <li key={item.id}>{item.text}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {interpretationStatus ? (
        <p className="b-meta" style={{ fontSize: "var(--fs-caption)", margin: 0 }}>
          {lang === "ro" ? "Organizat din sursă · Neverificat" : "Organized from source · Unverified"}
        </p>
      ) : null}
    </div>
  );
}

/** Part 7C — the current-encounter-scoped slice of the Clinical Course,
 * using ONLY events the interpreter placed in `current_encounter.
 * event_ids` (never a guess) — falls back to nothing (null) rather than
 * showing historical events mislabeled as current. */
export function CurrentHospitalizationEvents({
  currentEncounter,
  events,
  documentContentType,
}: {
  currentEncounter: CurrentEncounter | null;
  events: ClinicalEvent[];
  documentContentType?: string | null;
}) {
  if (!currentEncounter || !currentEncounter.event_ids.length) return null;
  const currentEvents = events.filter((e) => currentEncounter.event_ids.includes(e.source_event_id));
  if (!currentEvents.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
      {currentEvents.map((event) => (
        <div
          key={event.source_event_id}
          style={{ padding: "var(--s3)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", background: "var(--surface)" }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--s2)" }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{event.normalized_date || event.raw_date_text}</div>
            <ReaderSourceAction
              sourceEvidenceId={event.source_evidence_ids[0] ?? null}
              documentContentType={documentContentType}
            />
          </div>
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{event.raw_text}</p>
        </div>
      ))}
    </div>
  );
}

const TREATMENT_ERA_TITLE = { en: "Treatment eras", ro: "Perioade de tratament" };

/** Source Intelligence + Provenance V2, Part 33 — treatment eras had no
 * reader UI at all before this (the field existed on the schema but
 * nothing rendered it). Each era is a multi-source AI summary grounded
 * in real dated_events, so it gets `MultiSourceAction`'s "View sources
 * (N)" cycler, never a single fake "exact" source. */
export function TreatmentEraList({
  treatmentEras,
  documentContentType,
}: {
  treatmentEras: TreatmentEra[];
  documentContentType?: string | null;
}) {
  const lang = useLang();
  if (!treatmentEras.length) return null;

  return (
    <div>
      <h3 className="b-label" style={{ marginBottom: 10 }}>
        {TREATMENT_ERA_TITLE[lang]}
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
        {treatmentEras.map((era) => (
          <div
            key={era.id}
            style={{ padding: "var(--s3)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", background: "var(--surface)" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--s2)", flexWrap: "wrap" }}>
              <div style={{ fontWeight: 600 }}>
                {era.label}
                {era.start_date || era.end_date ? (
                  <span className="b-meta" style={{ fontWeight: 400, marginLeft: 8 }}>
                    {era.start_date || "—"} → {era.end_date || (lang === "ro" ? "prezent" : "present")}
                  </span>
                ) : null}
              </div>
              <MultiSourceAction sourceEvidenceIds={era.source_evidence_ids} documentContentType={documentContentType} />
            </div>
            {era.description ? (
              <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", color: "var(--muted)", fontSize: "var(--fs-caption)" }}>
                {era.description}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
