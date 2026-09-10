"use client";

/**
 * Clinical timeline.
 *
 * Rebuilt for long histories. The previous version rendered every event as a
 * gradient-filled rounded card with a 950-weight title, a coloured pill and a
 * full-size "Open" button - roughly 90px per event, so ten years of records
 * was unreadable, and nested admissions produced cards inside cards inside
 * cards.
 *
 * Now: events are ~40px rows on a hairline spine, grouped under sticky
 * month anchors so the reader always knows which period they are looking at.
 * Admissions keep their grouping but collapse by default, expanding in place
 * to reveal the records that fall inside the stay. Category is a small
 * coloured node rather than a badge, and the whole row is the click target.
 *
 * Pattern reference: Calendly scheduled-events (sticky date bands + compact
 * rows), Basecamp latest-activity (date anchors), Stripe events list.
 *
 * The props API is unchanged, so every existing caller keeps working.
 */

import { useMemo, useState } from "react";
import { useLanguage } from "@/lib/i18n";
import { IconChevronDown, IconChevronRight } from "@/components/ui/icon";
import { EmptyState } from "@/components/ui";
import { documentTypeOrSectionLabel } from "@/lib/document-taxonomy-labels";

type TimelineItem = {
  id: string;
  type: "document" | "event";
  date: string;
  title: string;
  subtitle: string;
  documentId?: number;
  eventId?: number;
  section?: string;
  /** Bragi's finer-grained document type (Phase 1+ uploads only — see
   * BRAGI_REDUCTO_PLAN.md Phase 5). Optional so every existing caller that
   * doesn't pass it keeps behaving exactly as before, falling back to
   * `section`. */
  documentType?: string | null;
  children?: TimelineItem[];
};

type ClinicalTimelineProps = {
  items: TimelineItem[];
  maxItems?: number;
  onOpenDocument?: (documentId: number) => void;
  onOpenEvent?: (eventId: number) => void;
  onSeeFullTimeline?: () => void;
  showSeeFullTimeline?: boolean;
  emptyText?: string;
};

function parseDateTime(value?: string | null) {
  if (!value) return 0;
  const normalized = value.trim();
  const direct = new Date(normalized).getTime();
  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(
    /^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/
  );
  if (!match) return 0;

  const day = Number(match[1]);
  const month = Number(match[2]);
  const rawYear = Number(match[3]);
  const year = rawYear < 100 ? 2000 + rawYear : rawYear;
  const hour = match[4] ? Number(match[4]) : 0;
  const minute = match[5] ? Number(match[5]) : 0;

  const parsed = new Date(year, month - 1, day, hour, minute).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** "12 Mar" - the day within its month group. */
function formatDayLabel(value?: string | null) {
  const time = parseDateTime(value);
  if (!time) return "—";
  return new Date(time).toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

/** "March 2026" - the sticky group anchor. */
function formatPeriod(time: number, noDateText: string) {
  if (!time) return noDateText;
  return new Date(time).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function periodKey(value?: string | null) {
  const time = parseDateTime(value);
  if (!time) return "unknown";
  const date = new Date(time);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function getTypeLabel(item: TimelineItem, t: (key: string) => string, language: string) {
  const fallback = (() => {
    if (item.section === "bloodwork") return t("bloodwork");
    if (item.section === "discharge_summary") return t("dischargeSummaryLabel");
    if (item.section === "scans") return t("scan");
    if (item.section === "medications") return t("medication");
    if (item.section === "hospitalizations") return t("hospitalEvent");
    if (item.section === "notes") return t("note");
    if (item.type === "event") return t("careEvent");
    return t("record");
  })();

  // Prefer the finer-grained document_type (e.g. "Imaging Report" instead
  // of just "Scan") when it's known — falls back to the section-based
  // label above for documents uploaded before automatic classification
  // existed, or when documentType isn't passed at all.
  return documentTypeOrSectionLabel(item.documentType, fallback, language);
}

/**
 * The node colour encodes the record category. Kept to the semantic set so a
 * timeline reads as one system rather than a colour wheel - and crucially,
 * bloodwork is no longer red by default (red now means "abnormal", not
 * "this is a blood test").
 */
function nodeClass(item: TimelineItem) {
  if (item.section === "discharge_summary") return "b-tl-node-brand";
  if (item.type === "event" || item.section === "hospitalizations") return "b-tl-node-ok";
  if (item.section === "scans") return "b-tl-node-warn";
  if (item.section === "notes") return "b-tl-node-info";
  return "";
}

function TimelineRow({
  item,
  onOpen,
  expandable,
  expanded,
  onToggle,
  childCount,
  indented,
}: {
  item: TimelineItem;
  onOpen?: () => void;
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  childCount?: number;
  indented?: boolean;
}) {
  const { t, language } = useLanguage();

  return (
    <button
      type="button"
      className="b-tl-event"
      aria-expanded={expandable ? expanded : undefined}
      onClick={expandable ? onToggle : onOpen}
      style={indented ? { paddingLeft: "calc(var(--s4) + 28px)" } : undefined}
    >
      <span className="b-tl-date">{formatDayLabel(item.date)}</span>

      <span className="b-tl-spine" aria-hidden="true">
        <span className={`b-tl-node ${nodeClass(item)}`} />
      </span>

      {/* data-date feeds the mobile layout, where the date gutter collapses
          into the main column via CSS rather than duplicating the node. */}
      <span className="b-tl-main" data-date={formatDayLabel(item.date)}>
        <span className="b-tl-title">{item.title}</span>
        <span className="b-tl-sub">
          <span style={{ color: "var(--text-2)" }}>{getTypeLabel(item, t, language)}</span>
          {item.subtitle ? ` · ${item.subtitle}` : ""}
        </span>
      </span>

      <span className="b-tl-trail">
        {expandable && childCount ? (
          <span className="b-tab-count">{childCount}</span>
        ) : null}

        {expandable ? (
          <IconChevronDown
            size={13}
            style={{
              color: "var(--faint)",
              transform: expanded ? "rotate(180deg)" : "none",
              transition: "transform var(--dur-2) var(--ease)",
            }}
          />
        ) : onOpen ? (
          <IconChevronRight size={13} className="b-list-chevron" />
        ) : null}
      </span>
    </button>
  );
}

export default function ClinicalTimeline({
  items,
  maxItems,
  onOpenDocument,
  onOpenEvent,
  onSeeFullTimeline,
  showSeeFullTimeline,
  emptyText,
}: ClinicalTimelineProps) {
  const { t } = useLanguage();
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const visibleItems = typeof maxItems === "number" ? items.slice(0, maxItems) : items;
  const hiddenCount = Math.max(items.length - visibleItems.length, 0);

  // Group into calendar months so the sticky anchors have something to say.
  const groups = useMemo(() => {
    const map = new Map<string, { key: string; time: number; items: TimelineItem[] }>();

    for (const item of visibleItems) {
      const key = periodKey(item.date);
      const existing = map.get(key);
      if (existing) {
        existing.items.push(item);
      } else {
        map.set(key, { key, time: parseDateTime(item.date), items: [item] });
      }
    }

    return Array.from(map.values());
  }, [visibleItems]);

  function toggle(id: string) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openItem(item: TimelineItem) {
    if (item.documentId && onOpenDocument) {
      onOpenDocument(item.documentId);
      return;
    }
    if (item.eventId && onOpenEvent) onOpenEvent(item.eventId);
  }

  function canOpen(item: TimelineItem) {
    return Boolean((item.documentId && onOpenDocument) || (item.eventId && onOpenEvent));
  }

  if (!items.length) {
    return <EmptyState title={emptyText ?? t("noTimelineActivity")} />;
  }

  return (
    <div className="b-timeline">
      {groups.map((group) => (
        <div className="b-tl-group" key={group.key}>
          <div className="b-tl-anchor">
            {formatPeriod(group.time, t("noDate"))}
            <span className="b-tl-anchor-count">
              {group.items.length}{" "}
              {group.items.length === 1 ? t("record").toLowerCase() : t("records").toLowerCase()}
            </span>
          </div>

          {group.items.map((item) => {
            const children = item.children || [];
            const isGroup = children.length > 0;
            const expanded = expandedIds.has(item.id);

            return (
              <div key={item.id}>
                <TimelineRow
                  item={item}
                  onOpen={canOpen(item) ? () => openItem(item) : undefined}
                  expandable={isGroup}
                  expanded={expanded}
                  onToggle={() => toggle(item.id)}
                  childCount={children.length}
                />

                {/* Records that fall inside an admission, indented under it
                    rather than nested in another card. */}
                {isGroup && expanded ? (
                  <div className="b-view-enter" style={{ background: "var(--surface-2)" }}>
                    {canOpen(item) ? (
                      <button
                        type="button"
                        className="b-tl-event"
                        onClick={() => openItem(item)}
                        style={{ paddingLeft: "calc(var(--s4) + 28px)" }}
                      >
                        <span className="b-tl-date" />
                        <span className="b-tl-spine" aria-hidden="true">
                          <span className="b-tl-node b-tl-node-brand" />
                        </span>
                        <span className="b-tl-main">
                          <span className="b-tl-title" style={{ color: "var(--primary)" }}>
                            {t("open")} — {item.title}
                          </span>
                        </span>
                        <span className="b-tl-trail">
                          <IconChevronRight size={13} className="b-list-chevron" />
                        </span>
                      </button>
                    ) : null}

                    {children.map((child) => (
                      <TimelineRow
                        key={child.id}
                        item={child}
                        indented
                        onOpen={canOpen(child) ? () => openItem(child) : undefined}
                      />
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ))}

      {showSeeFullTimeline && onSeeFullTimeline ? (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            padding: "var(--s3)",
            borderTop: "1px solid var(--border)",
          }}
        >
          <button type="button" className="b-btn b-btn-secondary b-btn-sm" onClick={onSeeFullTimeline}>
            {hiddenCount > 0
              ? `${t("seeFullTimeline")} · ${hiddenCount} ${t("moreLabel")}`
              : t("seeFullTimeline")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
