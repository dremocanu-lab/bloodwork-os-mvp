"use client";

type TimelineItem = {
  id: string;
  type: "document" | "event";
  date: string;
  title: string;
  subtitle: string;
  documentId?: number;
  eventId?: number;
};

function parseTimelineDate(value?: string | null) {
  if (!value) return 0;

  const normalized = value.trim();
  const direct = new Date(normalized).getTime();

  if (!Number.isNaN(direct)) return direct;

  const match = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);

  if (match) {
    const day = Number(match[1]);
    const month = Number(match[2]);
    const yearRaw = Number(match[3]);
    const year = yearRaw < 100 ? 2000 + yearRaw : yearRaw;
    const parsed = new Date(year, month - 1, day).getTime();

    if (!Number.isNaN(parsed)) return parsed;
  }

  return 0;
}

function formatAxisYear(value?: string | null) {
  const time = parseTimelineDate(value);
  if (!time) return "—";

  return new Date(time).toLocaleDateString(undefined, {
    year: "numeric",
  });
}

function formatAxisDate(value?: string | null) {
  const time = parseTimelineDate(value);
  if (!time) return value || "No date";

  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
  });
}

function formatFullDate(value?: string | null) {
  const time = parseTimelineDate(value);
  if (!time) return value || "No date";

  return new Date(time).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function getDateKey(value?: string | null) {
  const time = parseTimelineDate(value);
  if (!time) return "unknown";

  const date = new Date(time);
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function sortTimelineItems(items: TimelineItem[]) {
  return [...items].sort((a, b) => {
    const aTime = parseTimelineDate(a.date);
    const bTime = parseTimelineDate(b.date);

    if (aTime || bTime) return bTime - aTime;

    return (b.date || "").localeCompare(a.date || "");
  });
}

function groupTimelineItems(items: TimelineItem[]) {
  const sorted = sortTimelineItems(items);
  const groups: Array<{
    key: string;
    date: string;
    items: TimelineItem[];
  }> = [];

  sorted.forEach((item) => {
    const key = getDateKey(item.date);
    const existing = groups.find((group) => group.key === key);

    if (existing) {
      existing.items.push(item);
    } else {
      groups.push({
        key,
        date: item.date,
        items: [item],
      });
    }
  });

  return groups;
}

export default function ClinicalTimeline({
  items,
  maxItems,
  onOpenDocument,
  onSeeFullTimeline,
  showSeeFullTimeline = false,
  emptyText = "No timeline activity yet.",
  scrollable = false,
  maxHeight = 760,
}: {
  items: TimelineItem[];
  maxItems?: number;
  onOpenDocument?: (documentId: number) => void;
  onSeeFullTimeline?: () => void;
  showSeeFullTimeline?: boolean;
  emptyText?: string;
  scrollable?: boolean;
  maxHeight?: number;
}) {
  const sortedItems = sortTimelineItems(items);
  const visibleItems = typeof maxItems === "number" ? sortedItems.slice(0, maxItems) : sortedItems;
  const groups = groupTimelineItems(visibleItems);
  const hiddenCount = Math.max(sortedItems.length - visibleItems.length, 0);

  if (!visibleItems.length) {
    return (
      <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
        <div className="muted-text">{emptyText}</div>
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          maxHeight: scrollable ? maxHeight : undefined,
          overflowY: scrollable ? "auto" : undefined,
          overflowX: "hidden",
          paddingRight: scrollable ? 8 : 0,
          scrollbarWidth: "thin",
          scrollbarColor: "color-mix(in srgb, var(--primary) 50%, var(--border)) transparent",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "112px minmax(0, 1fr)",
            gap: 18,
            position: "relative",
          }}
        >
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              left: 111,
              top: 8,
              bottom: 8,
              width: 1,
              background: "linear-gradient(180deg, transparent, var(--border), transparent)",
            }}
          />

          {groups.map((group, groupIndex) => {
            const isFirstYearInList =
              groupIndex === 0 || formatAxisYear(groups[groupIndex - 1].date) !== formatAxisYear(group.date);

            return (
              <div key={group.key} style={{ display: "contents" }}>
                <div
                  style={{
                    position: "relative",
                    minHeight: 76,
                    paddingTop: 6,
                    textAlign: "right",
                    paddingRight: 18,
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      right: -5,
                      top: 16,
                      width: 11,
                      height: 11,
                      borderRadius: 999,
                      background: "var(--primary)",
                      border: "3px solid var(--panel)",
                      boxShadow: "0 0 0 1px var(--border)",
                      zIndex: 2,
                    }}
                  />

                  {isFirstYearInList && (
                    <div
                      style={{
                        fontWeight: 950,
                        fontSize: 18,
                        letterSpacing: "-0.04em",
                        color: "var(--foreground)",
                        marginBottom: 2,
                      }}
                    >
                      {formatAxisYear(group.date)}
                    </div>
                  )}

                  <div
                    className="muted-text"
                    style={{
                      fontSize: 13,
                      fontWeight: 850,
                    }}
                  >
                    {formatAxisDate(group.date)}
                  </div>
                </div>

                <div
                  style={{
                    display: "grid",
                    gap: 10,
                    paddingBottom: groupIndex === groups.length - 1 ? 0 : 14,
                  }}
                >
                  {group.items.map((item) => (
                    <div
                      key={item.id}
                      className="soft-card-tight"
                      style={{
                        padding: 16,
                        background:
                          item.type === "event"
                            ? "color-mix(in srgb, var(--primary) 7%, var(--panel))"
                            : "var(--panel)",
                        borderColor:
                          item.type === "event"
                            ? "color-mix(in srgb, var(--primary) 28%, var(--border))"
                            : "var(--border)",
                      }}
                    >
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "minmax(0, 1fr) auto",
                          gap: 12,
                          alignItems: "start",
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div
                            style={{
                              display: "flex",
                              gap: 9,
                              alignItems: "center",
                              flexWrap: "wrap",
                              marginBottom: 4,
                            }}
                          >
                            <span
                              style={{
                                width: 9,
                                height: 9,
                                borderRadius: 999,
                                background: item.type === "event" ? "var(--primary)" : "var(--muted)",
                                display: "inline-flex",
                                flex: "0 0 auto",
                              }}
                            />

                            <div
                              style={{
                                fontWeight: 900,
                                letterSpacing: "-0.02em",
                              }}
                            >
                              {item.title}
                            </div>
                          </div>

                          <div className="muted-text" style={{ lineHeight: 1.55 }}>
                            {formatFullDate(item.date)} · {item.subtitle}
                          </div>
                        </div>

                        {item.documentId && onOpenDocument && (
                          <button
                            type="button"
                            className="secondary-btn"
                            onClick={() => onOpenDocument(item.documentId as number)}
                            style={{
                              whiteSpace: "nowrap",
                            }}
                          >
                            Open
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showSeeFullTimeline && onSeeFullTimeline && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            marginTop: 18,
          }}
        >
          <button
            type="button"
            className="primary-btn"
            onClick={onSeeFullTimeline}
            style={{
              padding: "13px 18px",
              borderRadius: 16,
              fontWeight: 950,
            }}
          >
            See full timeline{hiddenCount > 0 ? ` (${hiddenCount} more)` : ""}
          </button>
        </div>
      )}
    </div>
  );
}