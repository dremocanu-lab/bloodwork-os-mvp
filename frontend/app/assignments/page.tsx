"use client";

/**
 * Admin - assign patients to doctors.
 *
 * A two-pane operational flow: find a patient on the left, pick doctors on
 * the right, confirm at the bottom. That structure was sound, so the work
 * here was making it feel like an operations console rather than a page of
 * 14px-radius tinted buttons: hairline list rows, real checkboxes, doctor
 * caseload visible while choosing, and a confirmation footer that names what
 * is about to change before it changes.
 *
 * Pattern reference: Stripe / Linear two-pane pickers - list, detail,
 * committed action in a persistent footer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  EmptyState,
  ErrorNote,
  Notice,
  SectionHead,
  Status,
  TableSkeleton,
  Toolbar,
} from "@/components/ui";
import { IconCheck, IconSearch, IconUsers } from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

type AdminPatient = {
  id: number;
  full_name: string;
  date_of_birth?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
};

type AdminDoctor = {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
  hospital_name?: string | null;
  current_patient_count: number;
};

/** CNP is identifying data: show only the last four digits in a list view. */
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

export default function AssignPatientsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [doctors, setDoctors] = useState<AdminDoctor[]>([]);
  const [loading, setLoading] = useState(true);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AdminPatient[]>([]);
  const [searching, setSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [selectedPatient, setSelectedPatient] = useState<AdminPatient | null>(null);
  const [existingDoctorIds, setExistingDoctorIds] = useState<Set<number>>(new Set());
  const [selectedDoctorIds, setSelectedDoctorIds] = useState<Set<number>>(new Set());

  const [doctorQuery, setDoctorQuery] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmSuccess, setConfirmSuccess] = useState("");
  const [confirmError, setConfirmError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<NavUser>("/auth/me");
        if (me.data.role !== "admin") {
          router.replace("/login");
          return;
        }
        setCurrentUser(me.data);
        const docs = await api.get<AdminDoctor[]>("/admin/doctors");
        setDoctors(docs.data || []);
      } catch {
        // Auth failures are handled by the shell's redirect.
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const runSearch = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const response = await api.get<AdminPatient[]>(
        `/admin/patients/search?q=${encodeURIComponent(query)}`
      );
      setSearchResults(response.data || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, []);

  function handleSearchInput(value: string) {
    setSearchQuery(value);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => runSearch(value), 320);
  }

  async function selectPatient(patient: AdminPatient) {
    setSelectedPatient(patient);
    setConfirmSuccess("");
    setConfirmError("");
    try {
      const response = await api.get<{ doctor_user_id: number }[]>(
        `/admin/patients/${patient.id}/assignments`
      );
      const ids = new Set((response.data || []).map((entry) => entry.doctor_user_id));
      setExistingDoctorIds(ids);
      setSelectedDoctorIds(new Set(ids));
    } catch {
      setExistingDoctorIds(new Set());
      setSelectedDoctorIds(new Set());
    }
  }

  function toggleDoctor(doctorId: number) {
    setSelectedDoctorIds((prev) => {
      const next = new Set(prev);
      if (next.has(doctorId)) next.delete(doctorId);
      else next.add(doctorId);
      return next;
    });
    setConfirmSuccess("");
    setConfirmError("");
  }

  async function confirmAssignment() {
    if (!selectedPatient) return;

    const newIds = [...selectedDoctorIds].filter((id) => !existingDoctorIds.has(id));
    if (newIds.length === 0) {
      setConfirmError("No new doctors selected.");
      return;
    }

    setConfirming(true);
    setConfirmError("");
    setConfirmSuccess("");
    try {
      const response = await api.post<{ created: number; skipped: number }>(
        "/admin/assignments/batch",
        { patient_id: selectedPatient.id, doctor_user_ids: newIds }
      );
      const { created, skipped } = response.data;
      setConfirmSuccess(
        skipped > 0
          ? `${created} ${t("assignedSuccessfully")} ${skipped} ${t("partialAssignSuccess")}`
          : t("assignedSuccessfully")
      );
      setExistingDoctorIds(new Set(selectedDoctorIds));
      const docs = await api.get<AdminDoctor[]>("/admin/doctors");
      setDoctors(docs.data || []);
    } catch (err) {
      setConfirmError(getErrorMessage(err, "Could not confirm assignment."));
    } finally {
      setConfirming(false);
    }
  }

  const newSelections = useMemo(
    () => [...selectedDoctorIds].filter((id) => !existingDoctorIds.has(id)),
    [selectedDoctorIds, existingDoctorIds]
  );

  const visibleDoctors = useMemo(() => {
    const term = doctorQuery.trim().toLowerCase();
    if (!term) return doctors;
    return doctors.filter((doctor) =>
      [doctor.full_name, doctor.email, doctor.department, doctor.hospital_name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [doctors, doctorQuery]);

  const newDoctorNames = newSelections
    .map((id) => doctors.find((doctor) => doctor.id === id)?.full_name)
    .filter(Boolean) as string[];

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={6} columns={3} />
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("assignPatients")}
      subtitle={t("assignPatientsSubtitle")}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(280px, 38%) minmax(0, 1fr)",
          gap: "var(--s4)",
          alignItems: "start",
          minWidth: 0,
        }}
        className="admin-assign-grid"
      >
        {/* ── Patient search ─────────────────────────────────────────── */}
        <section className="b-surface" style={{ minWidth: 0 }}>
          <SectionHead title={t("selectPatient")} description={t("selectPatientSubtitle")} />

          <div className="b-toolbar">
            <div className="b-search" style={{ flex: 1, minWidth: 0 }}>
              <IconSearch size={14} className="b-search-icon" />
              <input
                type="search"
                className="b-input"
                style={{ height: "var(--ctl-h)" }}
                placeholder={t("searchByNameOrCnp")}
                value={searchQuery}
                onChange={(event) => handleSearchInput(event.target.value)}
                autoComplete="off"
                aria-label={t("searchByNameOrCnp")}
              />
            </div>
          </div>

          {searching ? (
            <TableSkeleton rows={4} columns={2} />
          ) : !searchQuery.trim() ? (
            <EmptyState
              icon={<IconSearch size={17} />}
              title="Search for a patient"
              description="Start typing a name or patient code to find someone to assign."
            />
          ) : searchResults.length === 0 ? (
            <EmptyState title={t("noPatientsFound")} />
          ) : (
            <div className="b-list">
              {searchResults.map((patient) => {
                const isSelected = selectedPatient?.id === patient.id;
                return (
                  <button
                    key={patient.id}
                    type="button"
                    className="b-list-row"
                    aria-current={isSelected ? "true" : undefined}
                    onClick={() => selectPatient(patient)}
                    style={
                      isSelected
                        ? {
                            background: "var(--primary-soft)",
                            boxShadow: "inset 2px 0 0 var(--primary)",
                          }
                        : undefined
                    }
                  >
                    <span className="b-avatar" aria-hidden="true">
                      {initials(patient.full_name)}
                    </span>
                    <span className="b-list-main">
                      <span className="b-list-title">{patient.full_name}</span>
                      <span className="b-list-sub">
                        {patient.date_of_birth ? `DOB ${formatDate(patient.date_of_birth)}` : null}
                        {patient.cnp ? ` · CNP ${maskCnp(patient.cnp)}` : null}
                        {patient.patient_identifier ? ` · ID ${patient.patient_identifier}` : null}
                      </span>
                    </span>
                    {isSelected ? (
                      <span className="b-list-trail" style={{ color: "var(--primary)" }}>
                        <IconCheck size={14} />
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {/* ── Doctor selection ───────────────────────────────────────── */}
        <section className="b-surface" style={{ minWidth: 0 }}>
          <SectionHead
            title={t("assignDoctors")}
            description={t("assignDoctorsSubtitle")}
            actions={
              selectedPatient ? (
                <span className="b-chip b-chip-brand">{selectedPatient.full_name}</span>
              ) : null
            }
          />

          {!selectedPatient ? (
            <EmptyState
              icon={<IconUsers size={17} />}
              title={t("selectPatientToContinue")}
              description="Doctor caseloads and current assignments appear once a patient is selected."
            />
          ) : (
            <>
              {doctors.length > 6 ? (
                <Toolbar
                  search={doctorQuery}
                  onSearch={setDoctorQuery}
                  searchPlaceholder="Search doctors…"
                  count={visibleDoctors.length}
                  countLabel="doctors"
                />
              ) : null}

              {visibleDoctors.length === 0 ? (
                <EmptyState title={t("noDoctorsInDepartment")} />
              ) : (
                <div className="b-list">
                  {visibleDoctors.map((doctor) => {
                    const isExisting = existingDoctorIds.has(doctor.id);
                    const isSelected = selectedDoctorIds.has(doctor.id);

                    return (
                      <label
                        key={doctor.id}
                        className="b-list-row"
                        style={{ cursor: "pointer" }}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleDoctor(doctor.id)}
                          aria-label={`Assign ${doctor.full_name}`}
                        />

                        <span className="b-list-main">
                          <span className="b-list-title">{doctor.full_name}</span>
                          <span className="b-list-sub">
                            {doctor.email}
                            {doctor.department ? ` · ${doctor.department}` : ""}
                          </span>
                        </span>

                        <span className="b-list-trail">
                          {isExisting ? (
                            <Status tone="ok">{t("alreadyAssigned")}</Status>
                          ) : isSelected ? (
                            <Status tone="info">Will be assigned</Status>
                          ) : null}
                          <span className="b-range">
                            {doctor.current_patient_count} patients
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}

              {/* Confirmation footer: says what will change, then does it. */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--s2)",
                  padding: "var(--s3) var(--s4)",
                  borderTop: "1px solid var(--border)",
                }}
              >
                {confirmSuccess ? <Notice tone="ok">{confirmSuccess}</Notice> : null}
                {confirmError ? <ErrorNote>{confirmError}</ErrorNote> : null}

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "var(--s3)",
                    flexWrap: "wrap",
                  }}
                >
                  <div className="b-meta" style={{ minWidth: 0, flex: 1 }}>
                    {newSelections.length > 0 ? (
                      <>
                        Grant{" "}
                        <strong style={{ color: "var(--text)", fontWeight: 600 }}>
                          {newDoctorNames.join(", ")}
                        </strong>{" "}
                        access to{" "}
                        <strong style={{ color: "var(--text)", fontWeight: 600 }}>
                          {selectedPatient.full_name}
                        </strong>
                        &apos;s record.
                      </>
                    ) : (
                      "Select at least one doctor who does not already have access."
                    )}
                  </div>

                  <button
                    type="button"
                    className="b-btn b-btn-primary"
                    onClick={confirmAssignment}
                    disabled={confirming || newSelections.length === 0}
                    style={{ flexShrink: 0 }}
                  >
                    {confirming ? <span className="b-spinner" /> : null}
                    {t("confirmAssignment")}
                    {newSelections.length > 0 ? ` (${newSelections.length})` : ""}
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      <style jsx>{`
        /* Below tablet the two panes stack: picking a patient then scrolling
           to the doctors reads better than two 45%-wide columns. */
        @media (max-width: 1000px) {
          .admin-assign-grid {
            grid-template-columns: minmax(0, 1fr) !important;
          }
        }
      `}</style>
    </AppShell>
  );
}
