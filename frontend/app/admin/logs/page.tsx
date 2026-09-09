"use client";

/**
 * Admin - audit log.
 *
 * Was one 18px-padded card per log entry with an 18px/950 action title and a
 * pill restating the admin's name - about 140px per row, for a view whose
 * entire purpose is scanning many entries. Now an audit table: timestamp in
 * tabular figures, action, actor, subject, expandable details.
 *
 * NOTE: this route calls GET /admin/action-logs, which does not exist on the
 * backend (it returns 404), so the page has never been able to show data.
 * That is a pre-existing gap, not something this phase introduced, and adding
 * the endpoint is out of scope for a frontend/UI pass. The page now fails
 * cleanly with a retry instead of dumping a raw red error box.
 *
 * Pattern reference: Stripe events log - dense rows, monospace-ish
 * timestamps, expand for the payload.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";
import {
  CellPrimary,
  Column,
  DataTable,
  EmptyState,
  ErrorNote,
  TableSkeleton,
  Toolbar,
} from "@/components/ui";
import { IconList } from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

type Log = {
  id: number;
  admin_name: string;
  action: string;
  patient_name?: string | null;
  doctor_name?: string | null;
  timestamp: string;
  details?: string | null;
};

function prettyAction(action: string) {
  return action
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function prettyDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "2-digit",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AdminLogsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [logs, setLogs] = useState<Log[]>([]);
  const [user, setUser] = useState<NavUser | null>(null);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    const me = await api.get<NavUser>("/auth/me");
    if (me.data.role !== "admin") {
      router.push(getHomeByRole(me.data.role));
      return;
    }
    setUser(me.data);

    const response = await api.get<Log[]>("/admin/action-logs");
    setLogs(response.data);
  }, [router]);

  const init = useCallback(async () => {
    try {
      setError("");
      setLoading(true);
      await loadData();
    } catch (err) {
      setError(getErrorMessage(err, t("failedLoadActivityLog")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadData]);

  useEffect(() => {
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredLogs = useMemo(() => {
    const term = query.trim().toLowerCase();
    return logs
      .filter((log) => {
        if (!term) return true;
        return [
          log.admin_name,
          log.action,
          log.patient_name,
          log.doctor_name,
          log.details,
          log.timestamp,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(term);
      })
      .sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
  }, [logs, query]);

  const columns: Column<Log>[] = useMemo(
    () => [
      {
        key: "timestamp",
        header: t("timestamp"),
        width: 150,
        sortable: true,
        sortValue: (row) => row.timestamp || "",
        render: (row) => (
          <span className="tnum" style={{ color: "var(--text-2)" }}>
            {prettyDateTime(row.timestamp)}
          </span>
        ),
      },
      {
        key: "action",
        header: "Action",
        sortable: true,
        sortValue: (row) => row.action,
        render: (row) => (
          <CellPrimary
            title={prettyAction(row.action)}
            sub={row.details ? row.details.slice(0, 70) : undefined}
          />
        ),
      },
      {
        key: "admin",
        header: t("admin"),
        sortable: true,
        sortValue: (row) => row.admin_name || "",
        hideBelow: 640,
        render: (row) => (
          <span style={{ color: "var(--text-2)" }}>{valueOrDash(row.admin_name)}</span>
        ),
      },
      {
        key: "subject",
        header: "Subject",
        hideBelow: 900,
        render: (row) => {
          const parts = [
            row.patient_name ? `${t("patientLabel")}: ${row.patient_name}` : null,
            row.doctor_name ? `${t("doctorLabel")}: ${row.doctor_name}` : null,
          ].filter(Boolean);
          return parts.length ? (
            <span className="b-cell-sub">{parts.join(" · ")}</span>
          ) : (
            <span className="b-range">—</span>
          );
        },
      },
      {
        key: "details",
        header: <span className="sr-only">{t("details")}</span>,
        width: 90,
        render: (row) =>
          row.details ? (
            <div className="b-row-actions">
              <button
                type="button"
                className="b-btn b-btn-ghost b-btn-sm"
                onClick={(event) => {
                  event.stopPropagation();
                  setExpanded((current) => (current === row.id ? null : row.id));
                }}
                aria-expanded={expanded === row.id}
              >
                {t("details")}
              </button>
            </div>
          ) : null,
      },
    ],
    [expanded, t]
  );

  if (loading || !user) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={8} columns={4} />
        </div>
      </main>
    );
  }

  const expandedLog = filteredLogs.find((log) => log.id === expanded);

  return (
    <AppShell user={user} title={t("activityLog")} subtitle={t("activityLogSubtitle")}>
      <div className="b-stack">
        {error ? <ErrorNote onRetry={init}>{error}</ErrorNote> : null}

        <section className="b-surface">
          <Toolbar
            search={query}
            onSearch={setQuery}
            searchPlaceholder={t("search")}
            count={filteredLogs.length}
            countLabel={t("records").toLowerCase()}
          />

          <DataTable
            rows={filteredLogs}
            columns={columns}
            rowKey={(row) => row.id}
            caption={t("adminActions")}
            emptyState={
              <EmptyState
                icon={<IconList size={17} />}
                title={error ? t("failedLoadActivityLog") : t("noActivityLogs")}
                description={error ? undefined : t("noActivityLogsDesc")}
                actions={
                  error ? (
                    <button type="button" className="b-btn b-btn-secondary" onClick={init}>
                      {t("navRetry")}
                    </button>
                  ) : null
                }
              />
            }
          />

          {expandedLog?.details ? (
            <div
              className="b-view-enter"
              style={{
                padding: "var(--s3) var(--s4)",
                borderTop: "1px solid var(--border)",
                background: "var(--surface-2)",
              }}
            >
              <div className="b-label">{t("details")}</div>
              <p style={{ margin: "4px 0 0", lineHeight: "var(--lh)", overflowWrap: "anywhere" }}>
                {expandedLog.details}
              </p>
            </div>
          ) : null}
        </section>
      </div>
    </AppShell>
  );
}
