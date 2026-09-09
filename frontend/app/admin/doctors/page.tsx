"use client";

/**
 * Admin - doctors.
 *
 * Was a grid of 300px cards, each with a 44px avatar, an uppercase org line
 * and a 22px violet caseload figure - three doctors filled a screen. The
 * brief is explicit that admin records should not be cards, and it is right:
 * an administrator comparing caseloads needs a sortable column, not a
 * gallery. Now a table with search, sortable caseload and row actions.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  CellPrimary,
  Column,
  DataTable,
  EmptyState,
  ErrorNote,
  Metric,
  Metrics,
  TableSkeleton,
  Toolbar,
} from "@/components/ui";
import { IconChevronRight, IconUsers } from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

type AdminDoctor = {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
  hospital_name?: string | null;
  current_patient_count: number;
};

function initials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") || "D"
  );
}

export default function AdminDoctorsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [doctors, setDoctors] = useState<AdminDoctor[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<NavUser>("/auth/me");
        if (me.data.role !== "admin") {
          router.replace("/login");
          return;
        }
        setCurrentUser(me.data);
        const response = await api.get<AdminDoctor[]>("/admin/doctors");
        setDoctors(response.data || []);
      } catch {
        setError("Could not load doctors.");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return doctors;
    return doctors.filter((doctor) =>
      [doctor.full_name, doctor.email, doctor.department, doctor.hospital_name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [doctors, query]);

  const stats = useMemo(() => {
    const total = doctors.length;
    const assigned = doctors.reduce((sum, doctor) => sum + doctor.current_patient_count, 0);
    const unassigned = doctors.filter((doctor) => doctor.current_patient_count === 0).length;
    return {
      total,
      assigned,
      unassigned,
      average: total ? Math.round((assigned / total) * 10) / 10 : 0,
    };
  }, [doctors]);

  const columns: Column<AdminDoctor>[] = useMemo(
    () => [
      {
        key: "doctor",
        header: "Doctor",
        sortable: true,
        sortValue: (row) => row.full_name,
        render: (row) => (
          <CellPrimary
            avatar={initials(row.full_name)}
            title={row.full_name}
            sub={row.email}
          />
        ),
      },
      {
        key: "department",
        header: "Department",
        sortable: true,
        sortValue: (row) => row.department || "",
        hideBelow: 640,
        render: (row) =>
          row.department ? (
            <span style={{ color: "var(--text-2)" }}>{row.department}</span>
          ) : (
            <span className="b-range">—</span>
          ),
      },
      {
        key: "hospital",
        header: "Hospital",
        sortable: true,
        sortValue: (row) => row.hospital_name || "",
        hideBelow: 1100,
        render: (row) =>
          row.hospital_name ? (
            <span style={{ color: "var(--text-2)" }}>{row.hospital_name}</span>
          ) : (
            <span className="b-range">—</span>
          ),
      },
      {
        key: "caseload",
        header: "Patients",
        numeric: true,
        width: 120,
        sortable: true,
        sortValue: (row) => row.current_patient_count,
        render: (row) =>
          row.current_patient_count > 0 ? (
            <span style={{ fontWeight: 600 }}>{row.current_patient_count}</span>
          ) : (
            <span className="b-range">0</span>
          ),
      },
      {
        key: "go",
        header: <span className="sr-only">{t("viewPatients")}</span>,
        width: 100,
        render: (row) => (
          <div className="b-row-actions">
            <button
              type="button"
              className="b-btn b-btn-secondary b-btn-sm"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/admin/doctors/${row.id}`);
              }}
            >
              {t("viewPatients")}
              <IconChevronRight size={12} />
            </button>
          </div>
        ),
      },
    ],
    [router, t]
  );

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={6} columns={4} />
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("adminDoctorsNav")}
      subtitle={t("adminDoctorsSubtitle")}
    >
      <div className="b-stack">
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        <Metrics>
          <Metric label="Doctors" value={stats.total} />
          <Metric label="Active assignments" value={stats.assigned} />
          <Metric label="Average caseload" value={stats.average} />
          <Metric
            label="Without patients"
            value={stats.unassigned}
            tone={stats.unassigned > 0 ? "warn" : undefined}
          />
        </Metrics>

        <section className="b-surface">
          <Toolbar
            search={query}
            onSearch={setQuery}
            searchPlaceholder="Search by name, email, department…"
            count={filtered.length}
            countLabel="doctors"
          />

          <DataTable
            rows={filtered}
            columns={columns}
            rowKey={(row) => row.id}
            onRowClick={(row) => router.push(`/admin/doctors/${row.id}`)}
            caption={t("adminDoctorsNav")}
            initialSort={{ key: "caseload", dir: "desc" }}
            emptyState={
              <EmptyState
                icon={<IconUsers size={17} />}
                title={t("noDoctorsInDepartment")}
                description={t("searchDoctorsDesc")}
              />
            }
          />
        </section>
      </div>
    </AppShell>
  );
}
