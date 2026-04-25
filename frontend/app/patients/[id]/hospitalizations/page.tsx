"use client";

import { useEffect, useMemo, useState } from "react";
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

type PatientEvent = {
  id: number;
  patient_id: number;
  doctor_user_id: number;
  event_type: string;
  status: string;
  title: string;
  description?: string | null;
  hospital_name?: string | null;
  department?: string | null;
  admitted_at: string;
  discharged_at?: string | null;
  doctor_name?: string | null;
};

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  sections: {
    notes: unknown[];
    bloodwork: unknown[];
    medications: unknown[];
    scans: unknown[];
    hospitalizations: unknown[];
    other: unknown[];
  };
  doctor_access: unknown[];
  events: PatientEvent[];
};

type FilterMode = "all" | "active" | "past";

function formatDateTime(value?: string | null) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString();
}

export default function PatientHospitalizationsPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [filterMode, setFilterMode] = useState<FilterMode>("all");

  const [eventTitle, setEventTitle] = useState("");
  const [eventDescription, setEventDescription] = useState("");
  const [creatingEvent, setCreatingEvent] = useState(false);
  const [dischargingId, setDischargingId] = useState<number | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function fetchMe() {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  }

  async function fetchProfile() {
    const response = await api.get<PatientProfileResponse>(`/patients/${patientId}/profile`);
    setProfile(response.data);
  }

  useEffect(() => {
    async function init() {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await fetchProfile();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadHospitalizations")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [patientId]);

  async function createEvent() {
    if (!eventTitle.trim()) {
      setError(t("hospitalizationTitleRequired"));
      return;
    }

    try {
      setCreatingEvent(true);
      setError("");

      await api.post(`/patients/${patientId}/events`, {
        event_type: "hospitalization",
        title: eventTitle,
        description: eventDescription || null,
      });

      setEventTitle("");
      setEventDescription("");
      await fetchProfile();
      setFilterMode("active");
    } catch (err) {
      setError(getErrorMessage(err, t("failedCreateHospitalization")));
    } finally {
      setCreatingEvent(false);
    }
  }

  async function dischargeEvent(eventId: number) {
    try {
      setDischargingId(eventId);
      setError("");

      await api.post(`/patient-events/${eventId}/discharge`);
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, t("failedDischargeHospitalization")));
    } finally {
      setDischargingId(null);
    }
  }

  const activeEvents = useMemo(() => {
    return (profile?.events || []).filter((event) => event.status === "active");
  }, [profile]);

  const pastEvents = useMemo(() => {
    return (profile?.events || []).filter((event) => event.status !== "active");
  }, [profile]);

  const filteredEvents = useMemo(() => {
    const events = profile?.events || [];

    const filtered =
      filterMode === "active"
        ? activeEvents
        : filterMode === "past"
        ? pastEvents
        : events;

    return [...filtered].sort((a, b) => {
      const aDate = a.discharged_at || a.admitted_at || "";
      const bDate = b.discharged_at || b.admitted_at || "";
      return bDate.localeCompare(aDate);
    });
  }, [profile, filterMode, activeEvents, pastEvents]);

  const stats = useMemo(() => {
    return {
      all: profile?.events.length || 0,
      active: activeEvents.length,
      past: pastEvents.length,
    };
  }, [profile, activeEvents, pastEvents]);

  if (loading || !currentUser || !profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingHospitalizations")}</p>
      </main>
    );
  }

  const canManageEvents = currentUser.role === "doctor";

  return (
    <AppShell
      user={currentUser}
      title={t("hospitalizationsTitle")}
      subtitle={`${profile.patient.full_name} · ${t("dob")} ${valueOrDash(
        profile.patient.date_of_birth
      )} · ${t("age")} ${valueOrDash(profile.patient.age)} · ${t("sex")} ${valueOrDash(
        profile.patient.sex
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
          {t("backToChart")}
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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div className="stat-card stat-card-accent-violet">
          <div className="stat-card-label">{t("allHospitalizations")}</div>
          <div className="stat-card-value">{stats.all}</div>
        </div>

        <div className="stat-card stat-card-accent-green">
          <div className="stat-card-label">{t("activeHospitalizations")}</div>
          <div className="stat-card-value">{stats.active}</div>
        </div>

        <div className="stat-card stat-card-accent-blue">
          <div className="stat-card-label">{t("pastHospitalizations")}</div>
          <div className="stat-card-value">{stats.past}</div>
        </div>
      </div>

      {canManageEvents && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            {t("addHospitalizationEvent")}
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            <input
              className="text-input"
              value={eventTitle}
              onChange={(e) => setEventTitle(e.target.value)}
              placeholder={t("hospitalizationTitlePlaceholder")}
            />

            <textarea
              className="text-input"
              value={eventDescription}
              onChange={(e) => setEventDescription(e.target.value)}
              placeholder={t("hospitalizationDescriptionPlaceholder")}
              rows={4}
            />

            <div>
              <button className="primary-btn" onClick={createEvent} disabled={creatingEvent}>
                {creatingEvent ? t("creating") : t("createHospitalization")}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="soft-card" style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            marginBottom: 18,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div className="section-title">{t("hospitalizationsTitle")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("hospitalizationsSubtitle")}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {(["all", "active", "past"] as FilterMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={filterMode === mode ? "primary-btn" : "secondary-btn"}
                onClick={() => setFilterMode(mode)}
              >
                {mode === "all"
                  ? t("all")
                  : mode === "active"
                  ? t("active")
                  : t("pastHospitalizations")}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {filteredEvents.map((event) => {
            const isActive = event.status === "active";

            return (
              <div
                key={event.id}
                className="soft-card-tight"
                style={{
                  padding: 18,
                  borderColor: isActive ? "var(--success-border)" : "var(--border)",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    gap: 16,
                    alignItems: "start",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <div style={{ fontWeight: 900, fontSize: 20 }}>{event.title}</div>

                      <span
                        style={{
                          display: "inline-flex",
                          padding: "6px 10px",
                          borderRadius: 999,
                          background: isActive ? "var(--success-bg)" : "var(--panel-2)",
                          color: isActive ? "var(--success-text)" : "var(--muted)",
                          fontWeight: 900,
                          fontSize: 12,
                        }}
                      >
                        {isActive ? t("admitted") : t("discharged")}
                      </span>
                    </div>

                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
                      {valueOrDash(event.department)} · {valueOrDash(event.hospital_name)} · {t("doctor")}{" "}
                      {valueOrDash(event.doctor_name)}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4, lineHeight: 1.7 }}>
                      {t("admittedAt")} {formatDateTime(event.admitted_at)}
                      {event.discharged_at ? ` · ${t("dischargedAt")} ${formatDateTime(event.discharged_at)}` : ""}
                    </div>

                    {event.description && (
                      <div style={{ marginTop: 12, lineHeight: 1.7 }}>{event.description}</div>
                    )}
                  </div>

                  {canManageEvents && isActive && (
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className="secondary-btn"
                        onClick={() => dischargeEvent(event.id)}
                        disabled={dischargingId === event.id}
                      >
                        {dischargingId === event.id ? t("discharging") : t("discharge")}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {!filteredEvents.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>
                {filterMode === "active"
                  ? t("noActiveHospitalizations")
                  : filterMode === "past"
                  ? t("noPastHospitalizations")
                  : t("noHospitalizationsRecorded")}
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}