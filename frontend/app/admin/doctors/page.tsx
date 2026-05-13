"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type AdminDoctor = {
  id: number;
  full_name: string;
  email: string;
  department?: string | null;
  hospital_name?: string | null;
  current_patient_count: number;
};

export default function AdminDoctorsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [doctors, setDoctors] = useState<AdminDoctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (me.data.role !== "admin") { router.replace("/login"); return; }
        setCurrentUser(me.data);
        const res = await api.get<AdminDoctor[]>("/admin/doctors");
        setDoctors(res.data || []);
      } catch {
        setError("Could not load doctors.");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  return (
    <AppShell user={currentUser} title={t("adminDoctorsNav")} subtitle={t("adminDoctorsSubtitle")}>
      {error && (
        <div
          className="soft-card-tight"
          style={{ marginBottom: 20, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}
        >
          {error}
        </div>
      )}

      {doctors.length === 0 ? (
        <div className="soft-card" style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontWeight: 900, marginBottom: 8 }}>{t("noDoctorsInDepartment")}</div>
          <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
            {t("searchDoctorsDesc")}
          </div>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: 20,
          }}
        >
          {doctors.map((doctor) => (
            <div
              key={doctor.id}
              className="soft-card"
              style={{
                padding: 24,
                display: "flex",
                flexDirection: "column",
                gap: 0,
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 16 }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 999,
                    background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))",
                    border: "1px solid color-mix(in srgb, var(--primary) 22%, transparent)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 950,
                    fontSize: 17,
                    color: "var(--primary)",
                    flexShrink: 0,
                    letterSpacing: "-0.03em",
                  }}
                >
                  {doctor.full_name.charAt(0).toUpperCase()}
                </div>

                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 950,
                      fontSize: 16,
                      letterSpacing: "-0.03em",
                      lineHeight: 1.2,
                      overflowWrap: "anywhere",
                    }}
                  >
                    {doctor.full_name}
                  </div>
                  <div
                    className="muted-text"
                    style={{ marginTop: 3, fontSize: 13, overflowWrap: "anywhere" }}
                  >
                    {doctor.email}
                  </div>
                </div>
              </div>

              {(doctor.department || doctor.hospital_name) && (
                <div
                  className="muted-text"
                  style={{
                    fontSize: 12,
                    fontWeight: 900,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    marginBottom: 14,
                  }}
                >
                  {[doctor.department, doctor.hospital_name].filter(Boolean).join(" · ")}
                </div>
              )}

              <div style={{ flex: 1 }} />

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  paddingTop: 14,
                  borderTop: "1px solid var(--border)",
                  marginTop: 14,
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                  <span
                    style={{
                      fontSize: 22,
                      fontWeight: 950,
                      letterSpacing: "-0.04em",
                      color: "var(--primary)",
                    }}
                  >
                    {doctor.current_patient_count}
                  </span>
                  <span className="muted-text" style={{ fontSize: 12, fontWeight: 800 }}>
                    {t("currentPatientsCount")}
                  </span>
                </div>

                <Link
                  href={`/admin/doctors/${doctor.id}`}
                  className="secondary-btn"
                  style={{ textDecoration: "none", whiteSpace: "nowrap", fontSize: 13 }}
                >
                  {t("viewPatients")}
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
