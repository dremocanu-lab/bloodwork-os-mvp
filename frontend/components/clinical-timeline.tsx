"use client";

import { useLanguage } from "@/lib/i18n";

type TimelineItem = {
  id: string;
  type: "document" | "event";
  date: string;
  title: string;
  subtitle: string;
  documentId?: number;
  eventId?: number;
  section?: string;
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

function formatShortDate(value?: string | null) {
  if (!value) return "—";

  const time = parseDateTime(value);

  if (!time) return value;

  return new Date(time).toLocaleDateString(undefined, {
    month: "short",
    day: "2-digit",
  });
}

function getYear(value?: string | null, noDateText = "No date") {
  const time = parseDateTime(value);

  if (!time) return noDateText;

  return String(new Date(time).getFullYear());
}

function getTypeLabel(item: TimelineItem, t: (key: string) => string) {
  if (item.section === "bloodwork") return t("bloodwork");
  if (item.section === "discharge_summary") return t("dischargeSummaryLabel");
  if (item.section === "scans") return t("scan");
  if (item.section === "medications") return t("medication");
  if (item.section === "hospitalizations") return t("hospitalEvent");
  if (item.section === "notes") return t("note");
  if (item.type === "event") return t("careEvent");
  return t("record");
}

function getItemTone(item: TimelineItem) {
  if (item.section === "discharge_summary") {
    return {
      dot: "var(--primary)",
      bg: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
      border: "color-mix(in srgb, var(--primary) 32%, var(--border))",
      pillBg: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))",
      pillText: "var(--primary)",
    };
  }

  if (item.type === "event" || item.section === "hospitalizations") {
    return {
      dot: "var(--success-text)",
      bg: "linear-gradient(135deg, color-mix(in srgb, var(--success-bg) 72%, var(--panel)), var(--panel))",
      border: "var(--success-border)",
      pillBg: "var(--success-bg)",
      pillText: "var(--success-text)",
    };
  }

  if (item.section === "bloodwork") {
    return {
      dot: "var(--danger-text)",
      bg: "var(--panel)",
      border: "var(--border)",
      pillBg: "var(--danger-bg)",
      pillText: "var(--danger-text)",
    };
  }

  if (item.section === "scans") {
    return {
      dot: "var(--warn-text)",
      bg: "var(--panel)",
      border: "var(--border)",
      pillBg: "var(--warn-bg)",
      pillText: "var(--warn-text)",
    };
  }

  return {
    dot: "var(--muted)",
    bg: "var(--panel)",
    border: "var(--border)",
    pillBg: "var(--panel-2)",
    pillText: "var(--muted)",
  };
}

function TimelineButton({
  item,
  compact = false,
  onOpenDocument,
  onOpenEvent,
}: {
  item: TimelineItem;
  compact?: boolean;
  onOpenDocument?: (documentId: number) => void;
  onOpenEvent?: (eventId: number) => void;
}) {
  const { t } = useLanguage();
  const tone = getItemTone(item);
  const canOpen = Boolean(
    (item.documentId && onOpenDocument) || (item.eventId && onOpenEvent)
  );

  function handleOpen() {
    if (item.documentId && onOpenDocument) {
      onOpenDocument(item.documentId);
      return;
    }

    if (item.eventId && onOpenEvent) {
      onOpenEvent(item.eventId);
    }
  }

  return (
    <div
      className="soft-card-tight"
      style={{
        padding: compact ? 12 : 15,
        background: tone.bg,
        borderColor: tone.border,
        display: "grid",
        gridTemplateColumns: canOpen ? "minmax(0, 1fr) auto" : "minmax(0, 1fr)",
        gap: 12,
        alignItems: "center",
        borderRadius: compact ? 16 : 18,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 9,
            minWidth: 0,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              width: compact ? 7 : 8,
              height: compact ? 7 : 8,
              borderRadius: 999,
              background: tone.dot,
              flex: "0 0 auto",
            }}
          />

          <div
            className="timeline-item-title"
            style={{
              fontWeight: 950,
              fontSize: compact ? 13 : 15,
              letterSpacing: "-0.025em",
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.title}
          </div>

          <span
            style={{
              display: "inline-flex",
              padding: compact ? "4px 7px" : "5px 8px",
              borderRadius: 999,
              background: tone.pillBg,
              color: tone.pillText,
              fontSize: compact ? 10 : 11,
              fontWeight: 950,
              lineHeight: 1,
            }}
          >
            {getTypeLabel(item, t)}
          </span>
        </div>

        <div
          className="muted-text timeline-item-subtitle"
          style={{
            marginTop: compact ? 5 : 7,
            lineHeight: 1.45,
            fontSize: compact ? 12 : 13,
          }}
        >
          {item.subtitle}
        </div>
      </div>

      {canOpen && (
        <button
          type="button"
          className="secondary-btn"
          onClick={handleOpen}
          style={{
            borderRadius: 14,
            padding: compact ? "8px 11px" : "10px 13px",
            fontSize: compact ? 12 : 13,
            fontWeight: 950,
            whiteSpace: "nowrap",
          }}
        >
          {t("open")}
        </button>
      )}
    </div>
  );
}

function AdmissionGroup({
  item,
  onOpenDocument,
  onOpenEvent,
}: {
  item: TimelineItem;
  onOpenDocument?: (documentId: number) => void;
  onOpenEvent?: (eventId: number) => void;
}) {
  const { t } = useLanguage();
  const children = item.children || [];
  const tone = getItemTone(item);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "96px minmax(0, 1fr)",
        gap: 14,
        alignItems: "start",
      }}
    >
      <div
        style={{
          paddingTop: 8,
          textAlign: "right",
          position: "sticky",
          top: 10,
        }}
      >
        <div
          style={{
            fontWeight: 950,
            fontSize: 16,
            letterSpacing: "-0.045em",
          }}
        >
          {getYear(item.date, t("noDate"))}
        </div>
        <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginTop: 3 }}>
          {formatShortDate(item.date)}
        </div>
      </div>

      <div style={{ position: "relative", paddingLeft: 18 }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 17,
            bottom: 12,
            width: 2,
            borderRadius: 999,
            background:
              children.length > 0
                ? "linear-gradient(180deg, var(--primary), color-mix(in srgb, var(--primary) 18%, var(--border)))"
                : "var(--border)",
          }}
        />

        <div
          style={{
            position: "absolute",
            left: -4,
            top: 13,
            width: 10,
            height: 10,
            borderRadius: 999,
            background: tone.dot,
            boxShadow: "0 0 0 5px var(--panel)",
          }}
        />

        <div
          className="soft-card-tight"
          style={{
            padding: 16,
            background:
              "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
            borderColor: "color-mix(in srgb, var(--primary) 34%, var(--border))",
            borderRadius: 22,
          }}
        >
          <TimelineButton
            item={item}
            onOpenDocument={onOpenDocument}
            onOpenEvent={onOpenEvent}
          />

          {children.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div
                className="muted-text"
                style={{
                  fontSize: 12,
                  fontWeight: 950,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 10,
                }}
              >
                {t("recordsDuringAdmission")}
              </div>

              <div style={{ display: "grid", gap: 9 }}>
                {children.map((child) => (
                  <TimelineButton
                    key={child.id}
                    item={child}
                    compact
                    onOpenDocument={onOpenDocument}
                    onOpenEvent={onOpenEvent}
                  />
                ))}
              </div>
            </div>
          )}

          {!children.length && (
            <div
              className="muted-text"
              style={{
                marginTop: 10,
                fontSize: 12,
                lineHeight: 1.5,
              }}
            >
              {t("noLinkedRecordsInAdmission")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RegularTimelineItem({
  item,
  onOpenDocument,
  onOpenEvent,
}: {
  item: TimelineItem;
  onOpenDocument?: (documentId: number) => void;
  onOpenEvent?: (eventId: number) => void;
}) {
  const { t } = useLanguage();
  const tone = getItemTone(item);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "96px minmax(0, 1fr)",
        gap: 14,
        alignItems: "start",
      }}
    >
      <div style={{ paddingTop: 8, textAlign: "right" }}>
        <div
          style={{
            fontWeight: 950,
            fontSize: 16,
            letterSpacing: "-0.045em",
          }}
        >
          {getYear(item.date, t("noDate"))}
        </div>
        <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginTop: 3 }}>
          {formatShortDate(item.date)}
        </div>
      </div>

      <div style={{ position: "relative", paddingLeft: 18 }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 17,
            bottom: -15,
            width: 2,
            borderRadius: 999,
            background: "var(--border)",
          }}
        />

        <div
          style={{
            position: "absolute",
            left: -4,
            top: 13,
            width: 10,
            height: 10,
            borderRadius: 999,
            background: tone.dot,
            boxShadow: "0 0 0 5px var(--panel)",
          }}
        />

        <TimelineButton item={item} onOpenDocument={onOpenDocument} onOpenEvent={onOpenEvent} />
      </div>
    </div>
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
  const visibleItems = typeof maxItems === "number" ? items.slice(0, maxItems) : items;
  const hiddenCount = Math.max(items.length - visibleItems.length, 0);
  const empty = emptyText ?? t("noTimelineActivity");

  if (!items.length) {
    return (
      <div
        className="soft-card-tight"
        style={{
          padding: 18,
          background: "var(--panel-2)",
        }}
      >
        <div className="muted-text">{empty}</div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "grid", gap: 16 }}>
        {visibleItems.map((item) => {
          const hasChildren = Boolean(item.children?.length);

          if (hasChildren || item.section === "discharge_summary" || item.section === "hospitalizations") {
            return (
              <AdmissionGroup
                key={item.id}
                item={item}
                onOpenDocument={onOpenDocument}
                onOpenEvent={onOpenEvent}
              />
            );
          }

          return (
            <RegularTimelineItem
              key={item.id}
              item={item}
              onOpenDocument={onOpenDocument}
              onOpenEvent={onOpenEvent}
            />
          );
        })}
      </div>

      {showSeeFullTimeline && onSeeFullTimeline && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            paddingTop: 4,
          }}
        >
          <button
            type="button"
            className="secondary-btn"
            onClick={onSeeFullTimeline}
            style={{
              borderRadius: 16,
              padding: "12px 16px",
              fontWeight: 950,
            }}
          >
            {hiddenCount > 0
              ? `${t("seeFullTimeline")} (${hiddenCount} ${t("moreLabel")})`
              : t("seeFullTimeline")}
          </button>
        </div>
      )}
    </div>
  );
}
