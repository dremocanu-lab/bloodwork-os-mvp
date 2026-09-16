"use client";

/**
 * Generic renderer for the discriminated `ClinicalBlock` union
 * (Phase 8K) — a small composition of typed sub-cases, not hundreds of
 * conditional branches and not a dozen trivial one-line files.
 *
 * Reference blocks (`lab_report_reference`/`medication_list`/
 * `dated_event_group`) never carry a copy of the data they point at —
 * they filter the already-fetched canonical lists by id and hand off to
 * the ONE reusable renderer for that entity type.
 */

import { IconAlert } from "@/components/ui/icon";
import type { ClinicalBlock, ClinicalEvent, ReaderLabResult, ReaderMedication } from "@/lib/clinical-document-schema";
import { ClinicalCourseTimeline } from "./clinical-course-timeline";
import { MedicationList } from "./medication-list";
import { StructuredLabReport } from "./structured-lab-report";

type Props = {
  block: ClinicalBlock;
  labs: ReaderLabResult[];
  medications: ReaderMedication[];
  events: ClinicalEvent[];
  documentContentType?: string | null;
};

export function ClinicalBlockRenderer({ block, labs, medications, events, documentContentType }: Props) {
  switch (block.type) {
    case "paragraph":
      return block.text.trim() ? <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.7, margin: 0 }}>{block.text}</p> : null;

    case "key_value":
      return (
        <dl style={{ display: "grid", gridTemplateColumns: "minmax(120px, auto) 1fr", gap: "6px 16px", margin: 0 }}>
          {block.items.map((item, i) => (
            <div key={i} style={{ display: "contents" }}>
              <dt className="b-label">{item.key}</dt>
              <dd style={{ margin: 0 }}>{item.value}</dd>
            </div>
          ))}
        </dl>
      );

    case "bullet_list":
      return (
        <ul style={{ paddingLeft: 20, lineHeight: 1.7, margin: 0 }}>
          {block.items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      );

    case "table":
      return (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-body)" }}>
            {block.headers.length > 0 ? (
              <thead>
                <tr>
                  {block.headers.map((header, i) => (
                    <th
                      key={i}
                      style={{
                        textAlign: "left",
                        padding: "6px 10px",
                        borderBottom: "1px solid var(--border)",
                        fontSize: "var(--fs-caption)",
                        color: "var(--muted)",
                      }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td key={ci} style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "dated_event_group": {
      const scoped = events.filter((event) => block.event_ids.includes(event.source_event_id));
      return <ClinicalCourseTimeline events={scoped} />;
    }

    case "lab_report_reference": {
      const scoped = labs.filter((lab) => block.lab_result_ids.includes(lab.id));
      return <StructuredLabReport labs={scoped} documentContentType={documentContentType} mode="embedded" />;
    }

    case "medication_list": {
      const scoped = medications.filter((med) => block.medication_ids.includes(med.id));
      return <MedicationList medications={scoped} documentContentType={documentContentType} />;
    }

    case "prescription_table":
      return (
        <ul style={{ paddingLeft: 20, lineHeight: 1.7, margin: 0 }}>
          {block.rows.map((row, i) => (
            <li key={i}>
              {row.drug_text}
              {row.dose_text ? ` — ${row.dose_text}` : ""}
            </li>
          ))}
        </ul>
      );

    case "warning":
      return (
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
            padding: "10px 12px",
            background: "var(--panel-2)",
            borderRadius: "var(--r-md, 8px)",
            borderLeft: "3px solid var(--warn, #b08900)",
          }}
        >
          <IconAlert size={14} />
          <p style={{ margin: 0, fontSize: "var(--fs-body)" }}>{block.message}</p>
        </div>
      );

    default:
      return null;
  }
}
