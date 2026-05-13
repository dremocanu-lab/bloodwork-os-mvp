"use client";

import { useEffect, useState } from "react";
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

type Dependant = {
  patient_id: number;
  full_name: string;
  date_of_birth?: string | null;
  sex?: string | null;
  linked_at: string;
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function MyDependantsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");

        if (meResponse.data.role !== "care_partner") {
          router.replace("/login");
          return;
        }

        setCurrentUser(meResponse.data);

        const response = await api.get<Dependant[]>("/my/dependants");
        setDependants(response.data || []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load dependants."));
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
    <AppShell user={currentUser} title={t("myDependants")} subtitle={t("myDependantsDesc")}>
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

      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ marginBottom: 18 }}>
          <div className="section-title">{t("linkedPatients")}</div>
          <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
            {t("linkedPatientsDesc")}
          </div>
        </div>

        {dependants.length === 0 ? (
          <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)" }}>
            <div className="muted-text">{t("noDependantsDesc")}</div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {dependants.map((dep) => (
              <div
                key={dep.patient_id}
                className="soft-card-tight"
                style={{ padding: 18 }}
              >
                <div style={{ fontWeight: 900, fontSize: 16 }}>{dep.full_name}</div>
                {dep.date_of_birth && (
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {t("dateOfBirth")}: {dep.date_of_birth}
                  </div>
                )}
                {dep.sex && (
                  <div className="muted-text" style={{ marginTop: 2 }}>
                    {t("sex")}: {dep.sex}
                  </div>
                )}
                <div className="muted-text" style={{ marginTop: 6, fontSize: 12 }}>
                  {t("linkedAt")} {formatDate(dep.linked_at)}
                </div>
              </div>
            ))}
          </div>
        )}

        <div
          className="soft-card-tight"
          style={{ marginTop: 20, padding: 16, background: "var(--panel-2)" }}
        >
          <div className="muted-text" style={{ lineHeight: 1.6 }}>
            {t("addDependantHint")}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
