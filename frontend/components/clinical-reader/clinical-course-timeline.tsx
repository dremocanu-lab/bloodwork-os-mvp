"use client";

/**
 * Clinical Course as a chronological event timeline — built directly
 * from `StructuredClinicalDocument.dated_events` (Phase 5), never
 * re-parsed from prose in the browser.
 *
 * Suspicious chronology (V3 contract's own "never silently repair"
 * rule): an event is sorted by its real `normalized_date` even when
 * that date is itself flagged suspicious (e.g. year 3036) — the date is
 * never "corrected" into a more plausible position, and its own
 * warnings render on the event itself, never hidden.
 */

import { IconAlert } from "@/components/ui/icon";
import { Status } from "@/components/ui";
import { useLanguage } from "@/lib/i18n";
import type { ClinicalEvent } from "@/lib/clinical-document-schema";

const EVENT_TYPE_LABEL: Record<string, { en: string; ro: string }> = {
  admission: { en: "Admission", ro: "Internare" },
  follow_up: { en: "Follow-up", ro: "Control" },
  procedure: { en: "Procedure", ro: "Procedură" },
  treatment_change: { en: "Treatment change", ro: "Modificare tratament" },
  investigation: { en: "Investigation", ro: "Investigație" },
  discharge: { en: "Discharge", ro: "Externare" },
  consultation: { en: "Consultation", ro: "Consultație" },
  other: { en: "Event", ro: "Eveniment" },
};

export function ClinicalCourseTimeline({ events }: { events: ClinicalEvent[] }) {
  const { language } = useLanguage();
  const lang = language === "ro" ? "ro" : "en";

  if (events.length === 0) return null;

  // Chronological ordering ONLY when a real normalized_date exists — an
  // event with none keeps document order, appended after every dated
  // one, rather than being guessed into a position.
  const sorted = [...events].sort((a, b) => {
    if (a.normalized_date && b.normalized_date) return a.normalized_date.localeCompare(b.normalized_date);
    if (a.normalized_date) return -1;
    if (b.normalized_date) return 1;
    return 0;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
      {sorted.map((event) => {
        const label = EVENT_TYPE_LABEL[event.event_type]?.[lang] || event.event_type;
        const hasWarning = event.warnings.length > 0;
        return (
          <div
            key={event.source_event_id}
            className="soft-card-tight"
            style={{
              padding: 14,
              background: "var(--panel-2)",
              borderRadius: "var(--r-lg)",
              borderLeft: hasWarning ? "3px solid var(--warn, #b08900)" : "3px solid transparent",
            }}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span style={{ fontWeight: 700 }}>{event.normalized_date || event.raw_date_text}</span>
              {event.normalized_date && event.normalized_date !== event.raw_date_text ? (
                <span className="b-meta" style={{ fontSize: "var(--fs-caption)" }}>
                  ({event.raw_date_text})
                </span>
              ) : null}
              <Status tone="info">{label}</Status>
            </div>
            <p style={{ marginTop: 8, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{event.raw_text}</p>
            {event.procedures.length > 0 || event.structured_observations.length > 0 ? (
              <ul style={{ marginTop: 6, paddingLeft: 18, fontSize: "var(--fs-caption)", color: "var(--muted)" }}>
                {[...event.procedures, ...event.structured_observations].map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            ) : null}
            {hasWarning ? (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
                {event.warnings.map((warning, i) => (
                  <div key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                    <IconAlert size={13} />
                    <p className="b-meta" style={{ fontSize: "var(--fs-caption)", margin: 0 }}>
                      {warning}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
