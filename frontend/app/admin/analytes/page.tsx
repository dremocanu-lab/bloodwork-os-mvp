"use client";

/**
 * Admin - analyte gaps (data-quality queue).
 *
 * A genuine operational queue: extracted lab names the catalog does not
 * recognise, which an administrator works through by adding synonyms. The old
 * page split them into two hand-rolled grids under coloured headings, with a
 * four-tile summary of 28px figures on top.
 *
 * Now one table with a severity filter, a sortable occurrence count (so the
 * highest-impact gaps come first), and the copy-to-clipboard action kept
 * exactly where it was useful.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { findAnalyteEntry } from "@/lib/analytes/match";
import {
  Column,
  DataTable,
  EmptyState,
  ErrorNote,
  FilterChip,
  Metric,
  Metrics,
  Status,
  TableSkeleton,
  Toolbar,
} from "@/components/ui";
import { IconCheck, IconLab } from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

type AnalyteGap = {
  canonical_name: string;
  raw_names: string[];
  count: number;
  last_document_id: number | null;
};

type GapRow = AnalyteGap & { tsMatch: boolean };

type GapFilter = "all" | "missing" | "drift";

/** Copy the exact canonical name for pasting into a catalog file. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard unavailable (insecure context) - leave the label unchanged.
    }
  }

  return (
    <button
      type="button"
      className="b-btn b-btn-secondary b-btn-sm"
      onClick={(event) => {
        event.stopPropagation();
        handleCopy();
      }}
      style={{ minWidth: 62 }}
    >
      {copied ? <IconCheck size={12} /> : null}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function AnalyteGapsPage() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [gaps, setGaps] = useState<AnalyteGap[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<GapFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      setLoading(true);
      const [meResponse, gapsResponse] = await Promise.all([
        api.get<NavUser>("/auth/me"),
        api.get<AnalyteGap[]>("/admin/analyte-gaps"),
      ]);

      if (meResponse.data.role !== "admin") {
        router.replace("/assignments");
        return;
      }

      setCurrentUser(meResponse.data);
      setGaps(gapsResponse.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not load analyte gaps."));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * A gap the TS catalog also misses is worse than one it knows about: the
   * former is genuinely unrecognised everywhere, the latter is catalog drift
   * between the TS and Python catalogs.
   */
  const enrichedGaps = useMemo<GapRow[]>(
    () =>
      gaps.map((gap) => ({
        ...gap,
        tsMatch: findAnalyteEntry(gap.canonical_name) !== null,
      })),
    [gaps]
  );

  const counts = useMemo(
    () => ({
      all: enrichedGaps.length,
      missing: enrichedGaps.filter((gap) => !gap.tsMatch).length,
      drift: enrichedGaps.filter((gap) => gap.tsMatch).length,
    }),
    [enrichedGaps]
  );

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return enrichedGaps.filter((gap) => {
      if (filter === "missing" && gap.tsMatch) return false;
      if (filter === "drift" && !gap.tsMatch) return false;
      if (!term) return true;
      return (
        gap.canonical_name.toLowerCase().includes(term) ||
        gap.raw_names.some((raw) => raw.toLowerCase().includes(term))
      );
    });
  }, [enrichedGaps, query, filter]);

  const totalOccurrences = useMemo(
    () => enrichedGaps.reduce((sum, gap) => sum + gap.count, 0),
    [enrichedGaps]
  );

  const columns: Column<GapRow>[] = useMemo(
    () => [
      {
        key: "name",
        header: "Canonical name",
        sortable: true,
        sortValue: (row) => row.canonical_name,
        render: (row) => (
          <span className="b-cell-title" style={{ fontFamily: "ui-monospace, monospace" }}>
            {row.canonical_name}
          </span>
        ),
      },
      {
        key: "severity",
        header: "Status",
        width: 190,
        sortable: true,
        sortValue: (row) => (row.tsMatch ? 1 : 0),
        hideBelow: 640,
        render: (row) =>
          row.tsMatch ? (
            <Status tone="warn">Python needs synonym</Status>
          ) : (
            <Status tone="danger">Missing from both</Status>
          ),
      },
      {
        key: "raw",
        header: "Seen as",
        hideBelow: 900,
        render: (row) =>
          row.raw_names.length ? (
            <span className="b-strip">
              {row.raw_names.slice(0, 3).map((raw) => (
                <span key={raw} className="b-chip">
                  {raw}
                </span>
              ))}
              {row.raw_names.length > 3 ? (
                <span className="b-range">+{row.raw_names.length - 3}</span>
              ) : null}
            </span>
          ) : (
            <span className="b-range">—</span>
          ),
      },
      {
        key: "count",
        header: "Rows",
        numeric: true,
        width: 72,
        sortable: true,
        sortValue: (row) => row.count,
        render: (row) => <span style={{ fontWeight: 600 }}>{row.count}</span>,
      },
      {
        key: "actions",
        header: <span className="sr-only">Actions</span>,
        width: 160,
        render: (row) => (
          <div className="b-row-actions">
            {row.last_document_id ? (
              <button
                type="button"
                className="b-btn b-btn-ghost b-btn-sm"
                onClick={(event) => {
                  event.stopPropagation();
                  router.push(`/documents/${row.last_document_id}`);
                }}
              >
                Doc #{row.last_document_id}
              </button>
            ) : null}
            <CopyButton text={row.canonical_name} />
          </div>
        ),
      },
    ],
    [router]
  );

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={8} columns={4} />
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="Analyte gaps"
      subtitle="Lab analyte names extracted from documents that the catalog does not recognise"
    >
      <div className="b-stack">
        {error ? <ErrorNote onRetry={load}>{error}</ErrorNote> : null}

        <Metrics>
          <Metric label="Distinct gaps" value={counts.all} sub="Unrecognised names" />
          <Metric
            label="Missing from both"
            value={counts.missing}
            tone={counts.missing > 0 ? "alert" : undefined}
            sub="Not in either catalog"
          />
          <Metric
            label="Catalog drift"
            value={counts.drift}
            tone={counts.drift > 0 ? "warn" : undefined}
            sub="In TS, not in Python"
          />
          <Metric label="Affected rows" value={totalOccurrences} sub="Across all documents" />
        </Metrics>

        <section className="b-surface">
          <Toolbar
            search={query}
            onSearch={setQuery}
            searchPlaceholder="Filter by canonical or raw name…"
            filters={
              <>
                <FilterChip
                  label="All"
                  count={counts.all}
                  active={filter === "all"}
                  onClick={() => setFilter("all")}
                />
                <FilterChip
                  label="Missing from both"
                  count={counts.missing}
                  active={filter === "missing"}
                  onClick={() => setFilter("missing")}
                />
                <FilterChip
                  label="Catalog drift"
                  count={counts.drift}
                  active={filter === "drift"}
                  onClick={() => setFilter("drift")}
                />
              </>
            }
            count={filtered.length}
            countLabel="gaps"
          />

          <DataTable
            rows={filtered}
            columns={columns}
            rowKey={(row) => row.canonical_name}
            caption="Unknown analytes"
            initialSort={{ key: "count", dir: "desc" }}
            rowClassName={(row) => (row.tsMatch ? "row-warn" : "row-alert")}
            emptyState={
              <EmptyState
                icon={<IconLab size={17} />}
                title={query || filter !== "all" ? "No gaps match this filter" : "No analyte gaps"}
                description={
                  query || filter !== "all"
                    ? "Try a different search term or filter."
                    : "Every extracted analyte name is recognised by the catalog."
                }
              />
            }
          />
        </section>

        <p className="b-meta" style={{ maxWidth: "80ch" }}>
          Copy a canonical name to add it as a synonym in{" "}
          <code
            style={{
              fontSize: "var(--fs-xs)",
              background: "var(--surface-3)",
              padding: "1px 5px",
              borderRadius: "var(--r-sm)",
            }}
          >
            lab_catalog.py
          </code>{" "}
          or{" "}
          <code
            style={{
              fontSize: "var(--fs-xs)",
              background: "var(--surface-3)",
              padding: "1px 5px",
              borderRadius: "var(--r-sm)",
            }}
          >
            catalog.ts
          </code>
          . Sorting by affected rows puts the highest-impact gaps first.
        </p>
      </div>
    </AppShell>
  );
}
