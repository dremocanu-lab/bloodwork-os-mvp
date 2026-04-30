"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type Doctor = {
  id: number;
  email: string;
  full_name: string;
  role: "doctor";
  department?: string | null;
  hospital_name?: string | null;
};

type PatientProfile = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  doctor_access: {
    doctor_user_id: number;
    doctor_name: string;
    doctor_email: string;
    department?: string | null;
    hospital_name?: string | null;
    granted_at?: string | null;
  }[];
};

export default function AssignDoctorPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = Number(params.id);

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [patientProfile, setPatientProfile] = useState<PatientProfile | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [query, setQuery] = useState("");

  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [assigningId, setAssigningId] = useState<number | null>(null);
  const [replaceExisting, setReplaceExisting] = useState(true);
  const [error, setError] = useState("");

  async function searchDoctors(nextQuery: string) {
    setSearching(true);

    try {
      const response = await api.get<Doctor[]>("/admin/scoped-doctors/search", {
        params: { q: nextQuery.trim() },
      });

      setDoctors(response.data);
    } finally {
      setSearching(false);
    }
  }

  async function loadInitial() {
    const meResponse = await api.get<CurrentUser>("/auth/me");

    if (meResponse.data.role !== "admin") {
      router.push(meResponse.data.role === "doctor" ? "/my-patients" : "/my-records");
      return;
    }

    setCurrentUser(meResponse.data);

    const profileResponse = await api.get<PatientProfile>(`/patients/${patientId}/profile`);
    setPatientProfile(profileResponse.data);

    await searchDoctors("");
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await loadInitial();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadAssignmentPage")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, []);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    searchDoctors(query);
  }

  async function assignDoctor(doctorId: number) {
    try {
      setAssigningId(doctorId);
      setError("");

      await api.post("/admin/scoped-assign-doctor", {
        patient_id: patientId,
        doctor_user_id: doctorId,
        replace_existing: replaceExisting,
      });

      router.push("/assignments");
    } catch (err) {
      setError(getErrorMessage(err, t("failedAssignDoctor")));
    } finally {
      setAssigningId(null);
    }
  }

  const assignedDoctorIds = useMemo(() => {
    return new Set(patientProfile?.doctor_access.map((item) => item.doctor_user_id) ?? []);
  }, [patientProfile]);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingAssignmentPage")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("assignDoctor")}
      subtitle={`${t("assignDoctorSubtitlePrefix")} ${valueOrDash(currentUser.department)} ${t(
        "assignDoctorSubtitleMiddle"
      )} ${valueOrDash(currentUser.hospital_name)}.`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/assignments")}>
          {t("backToAssignments")}
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      {patientProfile && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title">{patientProfile.patient.full_name}</div>
          <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
            {t("dob")} {valueOrDash(patientProfile.patient.date_of_birth)} · {t("age")}{" "}
            {valueOrDash(patientProfile.patient.age)} · {t("sex")} {valueOrDash(patientProfile.patient.sex)}
          </div>
          <div className="muted-text" style={{ marginTop: 4 }}>
            {t("patientId")} {valueOrDash(patientProfile.patient.patient_identifier)}
          </div>
        </div>
      )}

      <div className="soft-card" style={{ padding: 24 }}>
        <form onSubmit={onSearch} style={{ display: "grid", gap: 14, marginBottom: 20 }}>
          <div>
            <div className="section-title">{t("searchDoctors")}</div>
            <div className="muted-text" style={{ marginTop: 8 }}>
              {t("searchDoctorsDesc")}
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <input
              className="text-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("searchDoctorsPlaceholder")}
            />

            <button className="primary-btn" type="submit" disabled={searching}>
              {searching ? t("searching") : t("search")}
            </button>
          </div>

          <label
            className="soft-card-tight"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: 14,
              cursor: "pointer",
              background: "var(--panel-2)",
            }}
          >
            <input
              type="checkbox"
              checked={replaceExisting}
              onChange={(e) => setReplaceExisting(e.target.checked)}
            />
            <span style={{ fontWeight: 800 }}>{t("replaceCurrentDoctor")}</span>
          </label>
        </form>

        <div style={{ display: "grid", gap: 14 }}>
          {doctors.map((doctor) => {
            const alreadyAssigned = assignedDoctorIds.has(doctor.id);

            return (
              <div key={doctor.id} className="soft-card-tight" style={{ padding: 18 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 16,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 900, fontSize: 18 }}>{doctor.full_name}</div>
                    <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.7 }}>
                      {doctor.email}
                    </div>
                    <div className="muted-text" style={{ marginTop: 4 }}>
                      {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                    </div>
                  </div>

                  <button
                    className={alreadyAssigned ? "secondary-btn" : "primary-btn"}
                    disabled={alreadyAssigned || assigningId === doctor.id}
                    onClick={() => assignDoctor(doctor.id)}
                  >
                    {alreadyAssigned
                      ? t("alreadyAssigned")
                      : assigningId === doctor.id
                      ? t("assigning")
                      : replaceExisting
                      ? t("assignReplace")
                      : t("addAssignment")}
                  </button>
                </div>
              </div>
            );
          })}

          {!doctors.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{t("noScopedDoctorsFound")}</div>
              <div className="muted-text" style={{ marginTop: 8 }}>
                {t("noScopedDoctorsFoundDesc")}
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
