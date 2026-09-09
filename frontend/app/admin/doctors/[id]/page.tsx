"use client";

/**
 * Admin - doctor detail and caseload.
 *
 * Two changes that matter here beyond the visual pass:
 *
 *  1. Ending an assignment revokes a clinician's access to a patient record.
 *     It used to happen on a single click of a quiet secondary button. It now
 *     goes through a confirmation that names the doctor and the patient, which
 *     is what the brief asks for on sensitive access changes.
 *  2. The two patient lists became tables with a sortable assignment date, so
 *     an administrator can actually audit a caseload.
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  CellPrimary,
  Column,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorNote,
  Metric,
  Metrics,
  Status,
  TableSkeleton,
  Tabs,
} from "@/components/ui";
import { IconUsers } from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

type DoctorDetail = {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
  hospital_name?: string | null;
  current_patient_count: number;
  historical_assignment_count: number;
};

type CurrentPatient = {
  assignment_id: number;
  patient_id: number;
  full_name: string;
  date_of_birth?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
  assigned_at: string;
};

type HistoryEntry = CurrentPatient & {
  ended_at?: string | null;
  is_active: boolean;
};

function maskCnp(cnp?: string | null): string {
  if (!cnp) return "—";
  if (cnp.length <= 4) return cnp;
  return "•".repeat(Math.min(cnp.length - 4, 9)) + cnp.slice(-4);
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function initials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") || "P"
  );
}

export default function DoctorDetailPage() {
  const router = useRouter();
  const params = useParams();
  const doctorId = params?.id as string;
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [doctor, setDoctor] = useState<DoctorDetail | null>(null);
  const [currentPatients, setCurrentPatients] = useState<CurrentPatient[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"current" | "history">("current");
  const [endingId, setEndingId] = useState<number | null>(null);
  const [endError, setEndError] = useState("");
  const [pendingEnd, setPendingEnd] = useState<CurrentPatient | null>(null);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<NavUser>("/auth/me");
        if (me.data.role !== "admin") {
          router.replace("/login");
          return;
        }
        setCurrentUser(me.data);

        const [docResponse, currentResponse, historyResponse] = await Promise.all([
          api.get<DoctorDetail>(`/admin/doctors/${doctorId}`),
          api.get<CurrentPatient[]>(`/admin/doctors/${doctorId}/current-patients`),
          api.get<HistoryEntry[]>(`/admin/doctors/${doctorId}/patient-history`),
        ]);
        setDoctor(docResponse.data);
        setCurrentPatients(currentResponse.data || []);
        setHistory(historyResponse.data || []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load doctor details."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router, doctorId]);

  async function endAssignment(assignmentId: number) {
    setEndingId(assignmentId);
    setEndError("");
    try {
      await api.post(`/admin/assignments/${assignmentId}/end`, {});
      setCurrentPatients((prev) => prev.filter((p) => p.assignment_id !== assignmentId));
      setHistory((prev) =>
        prev.map((entry) =>
          entry.assignment_id === assignmentId
            ? { ...entry, is_active: false, ended_at: new Date().toISOString() }
            : entry
        )
      );
      if (doctor) {
        setDoctor({ ...doctor, current_patient_count: doctor.current_patient_count - 1 });
      }
      setPendingEnd(null);
    } catch (err) {
      setEndError(getErrorMessage(err, "Could not end assignment."));
    } finally {
      setEndingId(null);
    }
  }

  const currentColumns: Column<CurrentPatient>[] = useMemo(
    () => [
      {
        key: "patient",
        header: t("navPatients"),
        sortable: true,
        sortValue: (row) => row.full_name,
        render: (row) => (
          <CellPrimary
            avatar={initials(row.full_name)}
            title={row.full_name}
            sub={
              <>
                {row.date_of_birth ? `DOB ${formatDate(row.date_of_birth)}` : null}
                {row.cnp ? ` · CNP ${maskCnp(row.cnp)}` : null}
              </>
            }
          />
        ),
      },
      {
        key: "assigned",
        header: t("assignedOn"),
        width: 150,
        sortable: true,
        sortValue: (row) => row.assigned_at || "",
        hideBelow: 640,
        render: (row) => (
          <span className="tnum" style={{ color: "var(--text-2)" }}>
            {formatDate(row.assigned_at)}
          </span>
        ),
      },
      {
        key: "actions",
        header: <span className="sr-only">Actions</span>,
        width: 150,
        render: (row) => (
          <div className="b-row-actions">
            <button
              type="button"
              className="b-btn b-btn-secondary b-btn-sm"
              onClick={(event) => {
                event.stopPropagation();
                router.push(`/patients/${row.patient_id}`);
              }}
            >
              Open record
            </button>
            <button
              type="button"
              className="b-btn b-btn-danger-quiet b-btn-sm"
              onClick={(event) => {
                event.stopPropagation();
                setPendingEnd(row);
              }}
              disabled={endingId === row.assignment_id}
            >
              {t("endAssignment")}
            </button>
          </div>
        ),
      },
    ],
    [endingId, router, t]
  );

  const historyColumns: Column<HistoryEntry>[] = useMemo(
    () => [
      {
        key: "patient",
        header: t("navPatients"),
        sortable: true,
        sortValue: (row) => row.full_name,
        render: (row) => (
          <CellPrimary
            avatar={initials(row.full_name)}
            title={row.full_name}
            sub={
              <>
                {row.date_of_birth ? `DOB ${formatDate(row.date_of_birth)}` : null}
                {row.cnp ? ` · CNP ${maskCnp(row.cnp)}` : null}
              </>
            }
          />
        ),
      },
      {
        key: "assigned",
        header: t("assignedOn"),
        width: 140,
        sortable: true,
        sortValue: (row) => row.assigned_at || "",
        hideBelow: 640,
        render: (row) => (
          <span className="tnum" style={{ color: "var(--text-2)" }}>
            {formatDate(row.assigned_at)}
          </span>
        ),
      },
      {
        key: "ended",
        header: t("endedOn"),
        width: 140,
        sortable: true,
        sortValue: (row) => row.ended_at || "",
        hideBelow: 900,
        render: (row) =>
          row.ended_at ? (
            <span className="tnum" style={{ color: "var(--text-2)" }}>
              {formatDate(row.ended_at)}
            </span>
          ) : (
            <span className="b-range">—</span>
          ),
      },
      {
        key: "status",
        header: "Status",
        width: 130,
        sortable: true,
        sortValue: (row) => (row.is_active ? 0 : 1),
        render: (row) =>
          row.is_active ? (
            <Status tone="ok">{t("assignmentStatusActive")}</Status>
          ) : (
            <Status tone="muted">{t("assignmentStatusEnded")}</Status>
          ),
      },
    ],
    [t]
  );

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={6} columns={3} />
        </div>
      </main>
    );
  }

  if (!doctor) {
    return (
      <AppShell
        user={currentUser}
        title="Doctor not found"
        breadcrumbs={[{ label: t("adminDoctorsNav"), href: "/admin/doctors" }]}
      >
        <section className="b-surface">
          <EmptyState
            title="Doctor not found"
            description={error || "This doctor may have been removed."}
            actions={
              <button
                type="button"
                className="b-btn b-btn-secondary"
                onClick={() => router.push("/admin/doctors")}
              >
                {t("adminDoctorsNav")}
              </button>
            }
          />
        </section>
      </AppShell>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={doctor.full_name}
      subtitle={[doctor.email, doctor.department, doctor.hospital_name]
        .filter(Boolean)
        .join(" · ")}
      breadcrumbs={[
        { label: t("adminDoctorsNav"), href: "/admin/doctors" },
        { label: doctor.full_name },
      ]}
      banner={
        <div className="b-ctx">
          <div className="b-ctx-tabs">
            <Tabs
              tabs={[
                {
                  key: "current",
                  label: t("currentPatientsTab"),
                  count: currentPatients.length,
                },
                { key: "history", label: t("patientHistoryTab"), count: history.length },
              ]}
              activeTab={activeTab}
              onChange={(key) => setActiveTab(key as "current" | "history")}
              ariaLabel={doctor.full_name}
            />
          </div>
        </div>
      }
    >
      <div className="b-stack b-view-enter" key={activeTab}>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {endError ? <ErrorNote>{endError}</ErrorNote> : null}

        <Metrics>
          <Metric label="Current patients" value={doctor.current_patient_count} />
          <Metric label="Total assignments" value={doctor.historical_assignment_count} />
          <Metric
            label="Ended"
            value={history.filter((entry) => !entry.is_active).length}
          />
        </Metrics>

        <section className="b-surface">
          {activeTab === "current" ? (
            <DataTable
              rows={currentPatients}
              columns={currentColumns}
              rowKey={(row) => row.assignment_id}
              onRowClick={(row) => router.push(`/patients/${row.patient_id}`)}
              caption={t("currentPatientsTab")}
              initialSort={{ key: "assigned", dir: "desc" }}
              emptyState={
                <EmptyState
                  icon={<IconUsers size={17} />}
                  title={t("noCurrentPatientsAdmin")}
                  actions={
                    <button
                      type="button"
                      className="b-btn b-btn-secondary"
                      onClick={() => router.push("/assignments")}
                    >
                      {t("assignPatients")}
                    </button>
                  }
                />
              }
            />
          ) : (
            <DataTable
              rows={history}
              columns={historyColumns}
              rowKey={(row) => row.assignment_id}
              onRowClick={(row) => router.push(`/patients/${row.patient_id}`)}
              caption={t("patientHistoryTab")}
              initialSort={{ key: "assigned", dir: "desc" }}
              emptyState={
                <EmptyState icon={<IconUsers size={17} />} title={t("noPatientHistoryAdmin")} />
              }
            />
          )}
        </section>
      </div>

      {/* Access revocation is irreversible from this screen, so it names both
          parties and what the doctor loses before it happens. */}
      <ConfirmDialog
        open={pendingEnd !== null}
        onClose={() => setPendingEnd(null)}
        onConfirm={() => pendingEnd && endAssignment(pendingEnd.assignment_id)}
        title={t("endAssignment")}
        confirmLabel={
          endingId !== null ? t("endingAssignment") : t("endAssignment")
        }
        busy={endingId !== null}
        consequence={
          pendingEnd ? (
            <>
              <strong style={{ fontWeight: 600 }}>{doctor.full_name}</strong> will immediately lose
              access to <strong style={{ fontWeight: 600 }}>{pendingEnd.full_name}</strong>&apos;s
              record. The assignment stays in the history log and can be re-created from Assign
              Patients.
            </>
          ) : null
        }
      />
    </AppShell>
  );
}
