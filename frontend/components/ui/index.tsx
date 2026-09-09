"use client";

/**
 * Bragi shared UI primitives.
 *
 * These exist so Patients, Labs, Documents, Medications, Access requests,
 * admin queues and audit views all render with the same density, alignment,
 * sort affordances, empty states and loading states. Before this each page
 * hand-rolled its own rows and its own idea of what a table looked like.
 */

import {
  ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  IconAlert,
  IconChevronDown,
  IconChevronRight,
  IconClose,
  IconFilter,
  IconInbox,
  IconSearch,
} from "@/components/ui/icon";

/* ==========================================================================
   Surface + section
   ========================================================================== */

export function Surface({
  children,
  className = "",
  style,
  padded = false,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  padded?: boolean;
}) {
  return (
    <section
      className={`b-surface ${className}`}
      style={{ minWidth: 0, ...(padded ? { padding: "var(--s4)" } : null), ...style }}
    >
      {children}
    </section>
  );
}

export function SectionHead({
  title,
  count,
  actions,
  description,
}: {
  title: ReactNode;
  count?: number;
  actions?: ReactNode;
  description?: ReactNode;
}) {
  return (
    <div className="b-section-head">
      <div style={{ minWidth: 0 }}>
        <h2 className="b-section-title">
          {title}
          {typeof count === "number" ? <span className="b-tab-count">{count}</span> : null}
        </h2>
        {description ? (
          <p className="b-meta" style={{ marginTop: 2 }}>
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center", flexShrink: 0 }}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}

/* ==========================================================================
   Tabs
   ========================================================================== */

export type TabDef = { key: string; label: string; count?: number };

/**
 * Underline tabs. Replaces the old PageTabs, which painted the active tab
 * with `var(--accent)` - a variable that was never defined - and hard-coded
 * `background: white`, so it was both invisible and broken in dark mode.
 */
export function Tabs({
  tabs,
  activeTab,
  onChange,
  ariaLabel,
}: {
  tabs: TabDef[];
  activeTab: string;
  onChange: (key: string) => void;
  ariaLabel?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // Left/Right arrows move between tabs, as expected of a tablist.
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const index = tabs.findIndex((tab) => tab.key === activeTab);
    const next = event.key === "ArrowRight" ? index + 1 : index - 1;
    const target = tabs[(next + tabs.length) % tabs.length];
    if (target) {
      onChange(target.key);
      listRef.current
        ?.querySelector<HTMLButtonElement>(`[data-tab="${target.key}"]`)
        ?.focus();
    }
  }

  return (
    <div className="b-tabs" role="tablist" aria-label={ariaLabel} ref={listRef} onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const selected = tab.key === activeTab;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            data-tab={tab.key}
            className="b-tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.key)}
          >
            {tab.label}
            {typeof tab.count === "number" ? (
              <span className="b-tab-count">{tab.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/* ==========================================================================
   Toolbar: search + filters + count
   ========================================================================== */

export function Toolbar({
  search,
  onSearch,
  searchPlaceholder,
  filters,
  count,
  countLabel,
  actions,
}: {
  search?: string;
  onSearch?: (value: string) => void;
  searchPlaceholder?: string;
  filters?: ReactNode;
  count?: number;
  countLabel?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="b-toolbar">
      {onSearch ? (
        <div className="b-search b-toolbar-search">
          <IconSearch size={14} className="b-search-icon" />
          <input
            className="b-input"
            value={search ?? ""}
            onChange={(event) => onSearch(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            type="search"
          />
        </div>
      ) : null}

      {filters ? <div className="b-filters">{filters}</div> : null}

      {typeof count === "number" ? (
        <div className="b-toolbar-count">
          {count.toLocaleString()} {countLabel}
        </div>
      ) : null}

      {actions ? (
        <div
          style={{
            display: "flex",
            gap: "var(--s2)",
            alignItems: "center",
            marginLeft: typeof count === "number" ? 0 : "auto",
          }}
        >
          {actions}
        </div>
      ) : null}
    </div>
  );
}

export function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="b-filter" aria-pressed={active} onClick={onClick}>
      {label}
      {typeof count === "number" ? <span className="b-filter-count">{count}</span> : null}
    </button>
  );
}

/**
 * Mobile filter sheet. Desktop filter strips would otherwise wrap into three
 * rows on a phone; below the breakpoint they collapse into one button that
 * opens a sheet of the same controls.
 */
export function FilterSheetButton({
  label,
  activeCount,
  children,
}: {
  label: string;
  activeCount?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" className="b-filter" onClick={() => setOpen(true)}>
        <IconFilter size={13} />
        {label}
        {activeCount ? <span className="b-filter-count">{activeCount}</span> : null}
      </button>

      {open ? (
        <>
          <button
            type="button"
            className="b-scrim"
            aria-label="Close"
            onClick={() => setOpen(false)}
          />
          <div className="b-sheet" role="dialog" aria-label={label}>
            <div className="b-sheet-grab" />
            <div className="b-sheet-head">
              <div className="b-sheet-title">{label}</div>
              <button
                type="button"
                className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
                onClick={() => setOpen(false)}
                aria-label="Close"
                style={{ marginLeft: "auto" }}
              >
                <IconClose size={15} />
              </button>
            </div>
            <div className="b-sheet-body" style={{ padding: "var(--s4)" }}>
              {children}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}

/* ==========================================================================
   Table
   ========================================================================== */

export type SortDir = "asc" | "desc";

export type Column<Row> = {
  key: string;
  header: ReactNode;
  /** Right-align and use tabular figures. For values, counts and dates. */
  numeric?: boolean;
  center?: boolean;
  width?: number | string;
  sortable?: boolean;
  /** Value used for sorting; falls back to the rendered cell. */
  sortValue?: (row: Row) => string | number;
  render: (row: Row) => ReactNode;
  /** Hide below this width - the field stays available in the detail view. */
  hideBelow?: 640 | 900 | 1100;
};

export function useSort<Row>(
  rows: Row[],
  columns: Column<Row>[],
  initial?: { key: string; dir: SortDir }
) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(initial ?? null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return rows;

    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = column.sortValue!(a);
      const bv = column.sortValue!(b);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * factor;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * factor;
    });
  }, [rows, columns, sort]);

  function toggle(key: string) {
    setSort((current) =>
      current?.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  return { sorted, sort, toggle };
}

export function DataTable<Row>({
  rows,
  columns,
  rowKey,
  onRowClick,
  rowClassName,
  emptyState,
  loading,
  loadingRows = 6,
  caption,
  initialSort,
}: {
  rows: Row[];
  columns: Column<Row>[];
  rowKey: (row: Row) => string | number;
  onRowClick?: (row: Row) => void;
  rowClassName?: (row: Row) => string | undefined;
  emptyState?: ReactNode;
  loading?: boolean;
  loadingRows?: number;
  caption?: string;
  initialSort?: { key: string; dir: SortDir };
}) {
  const { sorted, sort, toggle } = useSort(rows, columns, initialSort);

  if (loading) {
    return <TableSkeleton rows={loadingRows} columns={columns.length} />;
  }

  if (!rows.length) {
    return <>{emptyState ?? <EmptyState title="Nothing to show" />}</>;
  }

  return (
    // Focusable + named because below 640px this wrapper is the table's
    // horizontal scroller, and a scrollable region needs keyboard access.
    <div className="b-table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table
        className={`b-table b-table-hover ${onRowClick ? "b-table-clickable" : ""}`}
      >
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => {
              const isSorted = sort?.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={[
                    column.numeric ? "num" : "",
                    column.center ? "center" : "",
                    column.sortable && column.sortValue ? "sortable" : "",
                    column.hideBelow ? `hide-below-${column.hideBelow}` : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={column.width ? { width: column.width } : undefined}
                  aria-sort={
                    isSorted ? (sort!.dir === "asc" ? "ascending" : "descending") : undefined
                  }
                  onClick={
                    column.sortable && column.sortValue ? () => toggle(column.key) : undefined
                  }
                >
                  {column.sortable && column.sortValue ? (
                    <span className="b-th-sort">
                      {column.header}
                      <IconChevronDown size={9} className="b-th-sort-icon" />
                    </span>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              className={rowClassName?.(row)}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={[
                    column.numeric ? "num" : "",
                    column.center ? "center" : "",
                    column.hideBelow ? `hide-below-${column.hideBelow}` : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Name over a secondary line, with optional avatar. The standard first cell. */
export function CellPrimary({
  title,
  sub,
  avatar,
  marker,
}: {
  title: ReactNode;
  sub?: ReactNode;
  avatar?: string;
  marker?: ReactNode;
}) {
  return (
    <div className="b-cell-primary">
      {marker}
      {avatar ? (
        <span className="b-avatar b-avatar-sm" aria-hidden="true">
          {avatar}
        </span>
      ) : null}
      <span className="b-cell-stack">
        <span className="b-cell-title">{title}</span>
        {sub ? <span className="b-cell-sub">{sub}</span> : null}
      </span>
    </div>
  );
}

/* ==========================================================================
   Status
   ========================================================================== */

export type StatusTone = "ok" | "warn" | "danger" | "info" | "muted" | "processing";

export function Status({ tone = "muted", children }: { tone?: StatusTone; children: ReactNode }) {
  return <span className={`b-status b-status-${tone}`}>{children}</span>;
}

export function Chip({
  tone,
  children,
}: {
  tone?: "ok" | "warn" | "danger" | "info" | "brand" | "critical";
  children: ReactNode;
}) {
  return <span className={`b-chip ${tone ? `b-chip-${tone}` : ""}`}>{children}</span>;
}

/**
 * A lab value with its unit and out-of-range direction. Units recede, the
 * figure carries the weight, and abnormality is one coloured arrow rather
 * than a filled red badge.
 */
export function LabValue({
  value,
  unit,
  flag,
  range,
}: {
  value: ReactNode;
  unit?: string | null;
  flag?: string | null;
  range?: string | null;
}) {
  const normalized = (flag || "").toLowerCase();
  const isHigh = normalized.includes("high") || normalized === "h";
  const isLow = normalized.includes("low") || normalized === "l";
  const isCritical = normalized.includes("critical") || normalized.includes("panic");
  const abnormal = isHigh || isLow || isCritical;

  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5, minWidth: 0 }}>
      <span
        className={`b-value ${
          isCritical ? "b-value-critical" : abnormal ? "b-value-abnormal" : ""
        }`}
      >
        {value}
      </span>
      {unit ? <span className="b-unit">{unit}</span> : null}
      {abnormal ? (
        <span
          className={`b-flag ${
            isCritical ? "b-flag-critical" : isHigh ? "b-flag-high" : "b-flag-low"
          }`}
          title={flag ?? undefined}
        >
          {isHigh ? "↑" : isLow ? "↓" : "!"}
        </span>
      ) : null}
      {range ? <span className="b-range">{range}</span> : null}
    </span>
  );
}

/* ==========================================================================
   States: loading, empty, error
   ========================================================================== */

export function Skeleton({
  width,
  height = 10,
  style,
}: {
  width?: number | string;
  height?: number;
  style?: CSSProperties;
}) {
  return <span className="b-skeleton" style={{ display: "block", width, height, ...style }} />;
}

export function TableSkeleton({ rows = 6, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div className="b-skeleton-row" key={rowIndex}>
          {Array.from({ length: columns }).map((__, colIndex) => (
            <Skeleton
              key={colIndex}
              height={9}
              style={{
                flex: colIndex === 0 ? 2 : 1,
                opacity: 1 - rowIndex * 0.1,
              }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  actions,
  icon,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="b-empty">
      <span className="b-empty-icon">{icon ?? <IconInbox size={17} />}</span>
      <div className="b-empty-title">{title}</div>
      {description ? <div className="b-empty-desc">{description}</div> : null}
      {actions ? <div className="b-empty-actions">{actions}</div> : null}
    </div>
  );
}

export function ErrorNote({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div className="b-error" role="alert">
      <IconAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ minWidth: 0, flex: 1 }}>{children}</span>
      {onRetry ? (
        <button
          type="button"
          className="b-btn b-btn-sm b-btn-ghost"
          onClick={onRetry}
          style={{ color: "inherit" }}
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "ok";
  children: ReactNode;
}) {
  const cls = tone === "warn" ? "b-notice b-notice-warn" : tone === "ok" ? "b-notice b-notice-ok" : "b-notice";
  return <div className={cls}>{children}</div>;
}

/* ==========================================================================
   Metrics
   ========================================================================== */

export function Metrics({ children }: { children: ReactNode }) {
  return <div className="b-metrics">{children}</div>;
}

export function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "alert" | "warn";
}) {
  return (
    <div className="b-metric">
      <div className="b-metric-label">{label}</div>
      <div
        className={`b-metric-value ${
          tone === "alert" ? "b-metric-value-alert" : tone === "warn" ? "b-metric-value-warn" : ""
        }`}
      >
        {value}
      </div>
      {sub ? <div className="b-metric-sub">{sub}</div> : null}
    </div>
  );
}

/* ==========================================================================
   Overlays
   ========================================================================== */

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "lg";
}) {
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <button type="button" className="b-scrim" aria-label="Close" onClick={onClose} />
      <div className="b-dialog-wrap">
        <div
          className={`b-dialog ${size === "lg" ? "b-dialog-lg" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
        >
          <div className="b-dialog-head">
            <div style={{ minWidth: 0, flex: 1 }}>
              <h2 className="b-dialog-title" id={titleId}>
                {title}
              </h2>
              {description ? <p className="b-dialog-desc">{description}</p> : null}
            </div>
            <button
              type="button"
              className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
              onClick={onClose}
              aria-label="Close"
            >
              <IconClose size={15} />
            </button>
          </div>

          {children ? <div className="b-dialog-body">{children}</div> : null}
          {footer ? <div className="b-dialog-foot">{footer}</div> : null}
        </div>
      </div>
    </>
  );
}

/**
 * Destructive confirmation. Names what will happen rather than asking
 * "Are you sure?", which is what makes an irreversible admin action safe.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  consequence,
  confirmLabel = "Confirm",
  busy,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: ReactNode;
  consequence: ReactNode;
  confirmLabel?: string;
  busy?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <button type="button" className="b-btn b-btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="b-btn b-btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? <span className="b-spinner" /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="b-danger-note">
        <IconAlert size={15} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>{consequence}</span>
      </div>
    </Dialog>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <button type="button" className="b-scrim" aria-label="Close" onClick={onClose} />
      <aside className="b-drawer" role="dialog" aria-modal="true">
        <div className="b-drawer-head">
          <div className="b-section-title" style={{ minWidth: 0, flex: 1 }}>
            {title}
          </div>
          {actions}
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={onClose}
            aria-label="Close"
          >
            <IconClose size={15} />
          </button>
        </div>
        <div className="b-drawer-body">{children}</div>
      </aside>
    </>
  );
}

/** Overflow menu for rare or destructive row actions. */
export function Menu({
  label,
  children,
  align = "end",
}: {
  label: string;
  children: ReactNode;
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
        onClick={(event) => {
          event.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <IconChevronDown size={14} />
      </button>

      {open ? (
        <div
          className="b-menu"
          role="menu"
          style={{ top: "calc(100% + 4px)", [align === "end" ? "right" : "left"]: 0 }}
          onClick={() => setOpen(false)}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function MenuItem({
  children,
  onClick,
  danger,
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  danger?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`b-menu-item ${danger ? "b-menu-item-danger" : ""}`}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.();
      }}
    >
      {icon}
      {children}
    </button>
  );
}

export { IconChevronRight };
