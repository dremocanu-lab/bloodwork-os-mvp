"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

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

function maskCnp(cnp?: string | null): string {
  if (!cnp) return "—";
  if (cnp.length <= 6) return cnp;
  return cnp.slice(0, 6) + "•".repeat(cnp.length - 6);
}

function formatDate(v?: string | null) {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function AssignPatientsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [doctors, setDoctors] = useState<AdminDoctor[]>([]);
  const [loading, setLoading] = useState(true);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AdminPatient[]>([]);
  const [searching, setSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [selectedPatient, setSelectedPatient] = useState<AdminPatient | null>(null);
  const [existingDoctorIds, setExistingDoctorIds] = useState<Set<number>>(new Set());
  const [selectedDoctorIds, setSelectedDoctorIds] = useState<Set<number>>(new Set());

  const [confirming, setConfirming] = useState(false);
  const [confirmSuccess, setConfirmSuccess] = useState("");
  const [confirmError, setConfirmError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (me.data.role !== "admin") { router.replace("/login"); return; }
        setCurrentUser(me.data);
        const docs = await api.get<AdminDoctor[]>("/admin/doctors");
        setDoctors(docs.data || []);
      } catch {
        // handled by AppShell auth redirect
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setSearchResults([]); return; }
    setSearching(true);
    try {
      const res = await api.get<AdminPatient[]>(`/admin/patients/search?q=${encodeURIComponent(q)}`);
      setSearchResults(res.data || []);
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
      const res = await api.get<{ doctor_user_id: number }[]>(`/admin/patients/${patient.id}/assignments`);
      const ids = new Set((res.data || []).map((a) => a.doctor_user_id));
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
      if (next.has(doctorId)) {
        next.delete(doctorId);
      } else {
        next.add(doctorId);
      }
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
      const res = await api.post<{ created: number; skipped: number }>("/admin/assignments/batch", {
        patient_id: selectedPatient.id,
        doctor_user_ids: newIds,
      });
      const { created, skipped } = res.data;
      if (skipped > 0) {
        setConfirmSuccess(`${created} ${t("assignedSuccessfully")} ${skipped} ${t("partialAssignSuccess")}`);
      } else {
        setConfirmSuccess(t("assignedSuccessfully"));
      }
      setExistingDoctorIds(new Set(selectedDoctorIds));
      const docs = await api.get<AdminDoctor[]>("/admin/doctors");
      setDoctors(docs.data || []);
    } catch (err) {
      setConfirmError(getErrorMessage(err, "Could not confirm assignment."));
    } finally {
      setConfirming(false);
    }
  }

  const newSelectionsCount = [...selectedDoctorIds].filter((id) => !existingDoctorIds.has(id)).length;

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  return (
    <AppShell user={currentUser} title={t("assignPatients")} subtitle={t("assignPatientsSubtitle")}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "44% 56%",
          gap: 20,
          height: "calc(100dvh - 200px)",
          minHeight: 500,
        }}
      >
        {/* ── LEFT: Patient search ── */}
        <div
          className="soft-card"
          style={{ padding: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
            <div style={{ fontWeight: 950, fontSize: 16, letterSpacing: "-0.03em" }}>{t("selectPatient")}</div>
            <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>{t("selectPatientSubtitle")}</div>
            <div style={{ position: "relative", marginTop: 12 }}>
              <span
                style={{
                  position: "absolute",
                  left: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--muted)",
                  pointerEvents: "none",
                  display: "flex",
                }}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                  <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" strokeWidth="1.6" />
                  <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </span>
              <input
                type="text"
                className="form-input"
                style={{ paddingLeft: 34 }}
                placeholder={t("searchByNameOrCnp")}
                value={searchQuery}
                onChange={(e) => handleSearchInput(e.target.value)}
                autoComplete="off"
              />
            </div>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
            {searching && (
              <div className="muted-text" style={{ padding: "12px 4px", fontSize: 13 }}>{t("loading")}</div>
            )}

            {!searching && searchQuery.trim() && searchResults.length === 0 && (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div className="muted-text" style={{ fontSize: 13 }}>{t("noPatientsFound")}</div>
              </div>
            )}


            <div style={{ display: "grid", gap: 8 }}>
              {searchResults.map((patient) => {
                const isSelected = selectedPatient?.id === patient.id;
                return (
                  <button
                    key={patient.id}
                    type="button"
                    onClick={() => selectPatient(patient)}
                    style={{
                      textAlign: "left",
                      padding: "14px 16px",
                      borderRadius: 14,
                      border: isSelected
                        ? "1.5px solid var(--primary)"
                        : "1px solid var(--border)",
                      background: isSelected
                        ? "color-mix(in srgb, var(--primary) 8%, var(--panel))"
                        : "var(--panel-2)",
                      cursor: "pointer",
                      transition: "background 160ms ease, border-color 160ms ease",
                      width: "100%",
                    }}
                  >
                    <div style={{ fontWeight: 950, fontSize: 14, letterSpacing: "-0.02em" }}>
                      {patient.full_name}
                    </div>
                    <div className="muted-text" style={{ marginTop: 5, fontSize: 12, display: "flex", gap: 12, flexWrap: "wrap" }}>
                      {patient.date_of_birth && (
                        <span>DOB: {formatDate(patient.date_of_birth)}</span>
                      )}
                      {patient.cnp && (
                        <span>CNP: {maskCnp(patient.cnp)}</span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── RIGHT: Doctor selection + confirmation ── */}
        <div
          className="soft-card"
          style={{ padding: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
            <div style={{ fontWeight: 950, fontSize: 16, letterSpacing: "-0.03em" }}>{t("assignDoctors")}</div>
            <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>{t("assignDoctorsSubtitle")}</div>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
            {!selectedPatient ? (
              <div style={{ padding: "32px 16px", textAlign: "center" }}>
                <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
                  {t("selectPatientToContinue")}
                </div>
              </div>
            ) : doctors.length === 0 ? (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div className="muted-text" style={{ fontSize: 13 }}>{t("noDoctorsInDepartment")}</div>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {doctors.map((doctor) => {
                  const isExisting = existingDoctorIds.has(doctor.id);
                  const isSelected = selectedDoctorIds.has(doctor.id);
                  return (
                    <button
                      key={doctor.id}
                      type="button"
                      onClick={() => toggleDoctor(doctor.id)}
                      style={{
                        textAlign: "left",
                        padding: "14px 16px",
                        borderRadius: 14,
                        border: isSelected
                          ? "1.5px solid var(--primary)"
                          : "1px solid var(--border)",
                        background: isSelected
                          ? "color-mix(in srgb, var(--primary) 8%, var(--panel))"
                          : "var(--panel-2)",
                        cursor: "pointer",
                        transition: "background 160ms ease, border-color 160ms ease",
                        width: "100%",
                        display: "grid",
                        gridTemplateColumns: "minmax(0,1fr) auto",
                        gap: 10,
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 950, fontSize: 14, letterSpacing: "-0.02em" }}>
                          {doctor.full_name}
                        </div>
                        <div className="muted-text" style={{ marginTop: 3, fontSize: 12 }}>
                          {doctor.email}
                        </div>
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                        {isExisting && (
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 900,
                              padding: "3px 8px",
                              borderRadius: 999,
                              background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))",
                              color: "var(--primary)",
                              letterSpacing: "0.02em",
                            }}
                          >
                            {t("alreadyAssigned")}
                          </span>
                        )}
                        <div
                          style={{
                            width: 20,
                            height: 20,
                            borderRadius: 6,
                            border: isSelected ? "none" : "1.5px solid var(--border)",
                            background: isSelected ? "var(--primary)" : "transparent",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                          }}
                        >
                          {isSelected && (
                            <svg width="12" height="9" viewBox="0 0 12 9" fill="none">
                              <path d="M1 4L4.5 7.5L11 1" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Confirmation footer */}
          <div
            style={{
              padding: "16px 24px",
              borderTop: "1px solid var(--border)",
              flexShrink: 0,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {confirmSuccess && (
              <div
                className="soft-card-tight"
                style={{
                  padding: "10px 14px",
                  borderColor: "var(--success-border)",
                  background: "var(--success-bg)",
                  color: "var(--success-text)",
                  fontSize: 13,
                  fontWeight: 800,
                }}
              >
                {confirmSuccess}
              </div>
            )}
            {confirmError && (
              <div
                className="soft-card-tight"
                style={{
                  padding: "10px 14px",
                  borderColor: "var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  fontSize: 13,
                }}
              >
                {confirmError}
              </div>
            )}

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div className="muted-text" style={{ fontSize: 13 }}>
                {selectedPatient ? (
                  <>
                    <span style={{ fontWeight: 900, color: "var(--text)" }}>{selectedPatient.full_name}</span>
                    {" · "}
                    {newSelectionsCount > 0
                      ? `${newSelectionsCount} new doctor${newSelectionsCount !== 1 ? "s" : ""} to assign`
                      : "no new doctors selected"}
                  </>
                ) : (
                  t("selectPatientToContinue")
                )}
              </div>

              <button
                type="button"
                className="primary-btn"
                onClick={confirmAssignment}
                disabled={confirming || !selectedPatient || newSelectionsCount === 0}
                style={{ whiteSpace: "nowrap", flexShrink: 0 }}
              >
                {confirming ? "Confirming..." : t("confirmAssignment")}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
