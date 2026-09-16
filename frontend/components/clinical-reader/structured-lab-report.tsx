"use client";

/**
 * ONE reusable structured lab report component — the V3 contract's own
 * non-negotiable requirement: used both embedded inside the discharge
 * reader (`mode="embedded"`) and, once Phase 9 wires a route for it, as
 * a standalone derived-artifact view (`mode="standalone"`). Never two
 * separate components with duplicated rendering logic.
 *
 * Renders canonical `LabResult` rows exactly as the reader API already
 * resolved them (`ReaderLabResult[]`) — never re-parses a value from
 * section text; the `StructuredClinicalDocument` paragraph a lab result
 * might also appear in is never treated as a second source of truth.
 *
 * Extracted from (not duplicated alongside) the existing inline
 * `.document-lab-table` pattern in `frontend/app/documents/[id]/page.tsx`
 * — same visual language, same LabValue/Status building blocks.
 */

import { useMemo } from "react";
import { LabValue, Status } from "@/components/ui";
import { useLanguage } from "@/lib/i18n";
import type { ReaderLabResult } from "@/lib/clinical-document-schema";
import { ReaderSourceAction } from "./reader-source-action";

type Props = {
  labs: ReaderLabResult[];
  documentContentType?: string | null;
  mode: "embedded" | "standalone";
};

function labDisplayName(lab: ReaderLabResult): string {
  return lab.display_name || lab.canonical_name || lab.raw_test_name || "—";
}

function labIdentityKey(lab: ReaderLabResult): string {
  return (lab.canonical_name || lab.display_name || lab.raw_test_name || "").trim().toLowerCase();
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function StructuredLabReport({ labs, documentContentType, mode }: Props) {
  const { language } = useLanguage();

  const copy =
    language === "ro"
      ? {
          test: "Analiză",
          result: "Rezultat",
          reference: "Interval referință",
          flag: "Semnificație",
          source: "Sursă",
          other: "Alte analize",
          requiresReview: "Necesită verificare",
          conflictNote: "Valori diferite raportate din surse distincte pentru acest interval — ambele păstrate.",
          empty: "Niciun rezultat de laborator disponibil pentru acest document.",
        }
      : {
          test: "Test",
          result: "Result",
          reference: "Reference range",
          flag: "Flag",
          source: "Source",
          other: "Other",
          requiresReview: "Requires review",
          conflictNote: "Different sources reported different values for this observation — both preserved.",
          empty: "No laboratory results are available for this document.",
        };

  // Group by category (Phase 6's embedded-lab category, or an ordinary
  // upload's own category) — never a fabricated panel name. Within a
  // group, rows are further clustered by (identity, date) so a genuine
  // conflict (two DIFFERENT values for the same analyte/date — the
  // synthetic MCH fixture case) is visible side by side, never merged.
  const groups = useMemo(() => {
    const byCategory = new Map<string, ReaderLabResult[]>();
    for (const lab of labs) {
      const key = lab.category || copy.other;
      if (!byCategory.has(key)) byCategory.set(key, []);
      byCategory.get(key)!.push(lab);
    }
    return Array.from(byCategory.entries());
  }, [labs, copy.other]);

  const conflictIds = useMemo(() => {
    const byIdentityDate = new Map<string, ReaderLabResult[]>();
    for (const lab of labs) {
      const key = `${labIdentityKey(lab)}::${lab.observation_datetime || ""}`;
      if (!byIdentityDate.has(key)) byIdentityDate.set(key, []);
      byIdentityDate.get(key)!.push(lab);
    }
    const ids = new Set<number>();
    for (const rows of byIdentityDate.values()) {
      const distinctValues = new Set(rows.map((r) => (r.value || "").trim()));
      if (rows.length > 1 && distinctValues.size > 1) {
        for (const row of rows) ids.add(row.id);
      }
    }
    return ids;
  }, [labs]);

  if (labs.length === 0) {
    return (
      <p className="b-meta" style={{ padding: "var(--s3) 0" }}>
        {copy.empty}
      </p>
    );
  }

  return (
    <div className={`b-lab-report b-lab-report-${mode}`}>
      <style jsx>{`
        .b-lab-report-group + .b-lab-report-group {
          margin-top: var(--s5);
        }
        .b-lab-report-group-title {
          font-size: var(--fs-caption);
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--muted);
          margin-bottom: var(--s2);
        }
        table.b-lab-table {
          width: 100%;
          border-collapse: collapse;
          font-size: var(--fs-body);
        }
        table.b-lab-table th {
          text-align: left;
          font-size: var(--fs-caption);
          font-weight: 600;
          color: var(--muted);
          padding: 8px 12px;
          border-bottom: 1px solid var(--border);
        }
        table.b-lab-table th.num,
        table.b-lab-table td.num {
          text-align: right;
        }
        table.b-lab-table td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border);
          vertical-align: top;
        }
        table.b-lab-table tr:last-child td {
          border-bottom: none;
        }
        table.b-lab-table tr.conflict-row td:first-child {
          box-shadow: inset 3px 0 0 var(--warn, #b08900);
        }
        @media (max-width: 720px) {
          table.b-lab-table thead {
            display: none;
          }
          table.b-lab-table,
          table.b-lab-table tbody,
          table.b-lab-table tr,
          table.b-lab-table td {
            display: block;
            width: 100%;
          }
          table.b-lab-table tr {
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
          }
          table.b-lab-table td {
            border-bottom: none;
            padding: 2px 0;
          }
          table.b-lab-table td::before {
            content: attr(data-label);
            display: block;
            font-size: var(--fs-caption);
            color: var(--muted);
            margin-bottom: 2px;
          }
        }
      `}</style>
      {groups.map(([category, rows]) => (
        <div key={category} className="b-lab-report-group">
          <div className="b-lab-report-group-title">{category}</div>
          <table className="b-lab-table">
            <thead>
              <tr>
                <th>{copy.test}</th>
                <th className="num">{copy.result}</th>
                <th>{copy.reference}</th>
                <th>{copy.flag}</th>
                <th>{copy.source}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((lab) => {
                const isConflict = conflictIds.has(lab.id);
                return (
                  <tr key={lab.id} className={isConflict ? "conflict-row" : undefined}>
                    <td data-label={copy.test}>
                      <div style={{ fontWeight: 600 }}>{labDisplayName(lab)}</div>
                      {lab.observation_datetime ? (
                        <div className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
                          {formatDate(lab.observation_datetime)}
                        </div>
                      ) : null}
                      {isConflict ? (
                        <div style={{ marginTop: 4 }}>
                          <Status tone="warn">{copy.requiresReview}</Status>
                        </div>
                      ) : null}
                    </td>
                    <td className="num" data-label={copy.result}>
                      <LabValue value={lab.value ?? "—"} unit={lab.unit} flag={lab.flag} />
                    </td>
                    <td data-label={copy.reference}>{lab.reference_range || "—"}</td>
                    <td data-label={copy.flag}>{lab.flag || "—"}</td>
                    <td data-label={copy.source}>
                      <ReaderSourceAction sourceEvidenceId={lab.source_evidence_id} documentContentType={documentContentType} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.some((r) => conflictIds.has(r.id)) ? (
            <p className="b-meta" style={{ fontSize: "var(--fs-caption)", marginTop: 6 }}>
              {copy.conflictNote}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}
