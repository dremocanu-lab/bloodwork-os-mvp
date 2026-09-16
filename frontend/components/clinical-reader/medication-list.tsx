"use client";

/**
 * Renders canonical `PatientMedication` rows (Phase 7) exactly as the
 * reader API resolved them — never parses a medication out of raw
 * section text in the browser, never a second medication datastore.
 */

import { useMemo } from "react";
import { Status, type StatusTone } from "@/components/ui";
import { useLanguage } from "@/lib/i18n";
import type { ReaderMedication } from "@/lib/clinical-document-schema";
import { ReaderSourceAction } from "./reader-source-action";

type Props = {
  medications: ReaderMedication[];
  documentContentType?: string | null;
};

const STATUS_TONE: Record<string, StatusTone> = {
  active: "ok",
  as_needed: "info",
  paused: "warn",
  stopped: "muted",
};

const STATUS_LABEL: Record<string, { en: string; ro: string }> = {
  active: { en: "Active", ro: "Activ" },
  as_needed: { en: "As needed", ro: "La nevoie" },
  paused: { en: "Paused", ro: "Suspendat" },
  stopped: { en: "Stopped", ro: "Oprit" },
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function medicationIdentityKey(med: ReaderMedication): string {
  return med.name.trim().toLowerCase();
}

export function MedicationList({ medications, documentContentType }: Props) {
  const { language } = useLanguage();

  const copy =
    language === "ro"
      ? {
          dose: "Doză",
          route: "Cale",
          frequency: "Frecvență",
          starts: "Începe",
          ends: "Se încheie",
          calculated: (source: string) => `Calculat dintr-un curs documentat (${source})`,
          conflictNote: (statuses: string) => `Stare contradictorie între surse (${statuses}) — necesită verificare.`,
          conflictEndDateNote: "Data explicită din sursă diferă de cea calculată — păstrată, necesită verificare.",
          requiresReview: "Necesită verificare",
          empty: "Nicio medicație documentată pentru acest document.",
        }
      : {
          dose: "Dose",
          route: "Route",
          frequency: "Frequency",
          starts: "Starts",
          ends: "Ends",
          calculated: (source: string) => `Calculated from a documented course (${source})`,
          conflictNote: (statuses: string) => `Conflicting status across sources (${statuses}) — requires review.`,
          conflictEndDateNote: "Source-stated end date differs from the calculated one — kept as stated, flagged for review.",
          requiresReview: "Requires review",
          empty: "No medications are documented for this document.",
        };

  const conflictGroups = useMemo(() => {
    const byName = new Map<string, ReaderMedication[]>();
    for (const med of medications) {
      const key = medicationIdentityKey(med);
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key)!.push(med);
    }
    const conflicts = new Map<number, string>(); // medication id -> comma-joined statuses
    for (const rows of byName.values()) {
      const distinctStatuses = Array.from(new Set(rows.map((r) => r.status)));
      if (rows.length > 1 && distinctStatuses.length > 1) {
        const label = distinctStatuses.map((s) => STATUS_LABEL[s]?.[language === "ro" ? "ro" : "en"] || s).join(" / ");
        for (const row of rows) conflicts.set(row.id, label);
      }
    }
    return conflicts;
  }, [medications, language]);

  if (medications.length === 0) {
    return (
      <p className="b-meta" style={{ padding: "var(--s3) 0" }}>
        {copy.empty}
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
      {medications.map((med) => {
        const conflictLabel = conflictGroups.get(med.id);
        const statusLabel = STATUS_LABEL[med.status]?.[language === "ro" ? "ro" : "en"] || med.status;
        const endDateConflict = med.stop_date_basis === "explicit_with_derived_conflict";

        return (
          <div
            key={med.id}
            className="soft-card-tight"
            style={{
              padding: 16,
              background: "var(--panel-2)",
              borderRadius: "var(--r-lg)",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: "var(--fs-body-lg, 15px)" }}>{med.name}</div>
                <div className="b-meta" style={{ fontSize: "var(--fs-caption)", marginTop: 2 }}>
                  {[med.dose_strength, med.route_form, med.frequency].filter(Boolean).join(" · ") || "—"}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <Status tone={STATUS_TONE[med.status] || "muted"}>{statusLabel}</Status>
                {med.is_uncertain ? <Status tone="warn">{copy.requiresReview}</Status> : null}
              </div>
            </div>

            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", fontSize: "var(--fs-caption)" }}>
              <div>
                <span className="b-label">{copy.starts}</span>{" "}
                <span>{formatDate(med.start_date)}</span>
              </div>
              <div>
                <span className="b-label">{copy.ends}</span>{" "}
                <span>{formatDate(med.stop_date)}</span>
                {med.stop_date && med.stop_date_basis === "derived" ? (
                  <div className="b-meta" style={{ marginTop: 2 }}>
                    {copy.calculated(`${formatDate(med.start_date)} → ${formatDate(med.stop_date)}`)}
                  </div>
                ) : null}
              </div>
            </div>

            {endDateConflict ? (
              <p className="b-meta" style={{ fontSize: "var(--fs-caption)", color: "var(--warn-text, var(--muted))" }}>
                {copy.conflictEndDateNote}
              </p>
            ) : null}

            {conflictLabel ? (
              <p className="b-meta" style={{ fontSize: "var(--fs-caption)", color: "var(--warn-text, var(--muted))" }}>
                {copy.conflictNote(conflictLabel)}
              </p>
            ) : null}

            {med.extra_info ? (
              <p className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
                {med.extra_info}
              </p>
            ) : null}

            <div>
              <ReaderSourceAction sourceEvidenceId={med.source_evidence_id} documentContentType={documentContentType} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
