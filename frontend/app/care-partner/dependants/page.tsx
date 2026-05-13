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
  const [linkCode, setLinkCode] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState("");
  const [linkSuccess, setLinkSuccess] = useState("");

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

  async function handleLinkPatient(e: React.FormEvent) {
    e.preventDefault();
    setLinkError("");
    setLinkSuccess("");
    if (!linkCode.trim()) return;
    setLinking(true);
    try {
      const res = await api.post<Dependant>("/my/link-patient", { care_partner_code: linkCode.trim().toUpperCase() });
      setDependants((prev) => [...prev, res.data]);
      setLinkCode("");
      setLinkSuccess(t("patientLinkedSuccess"));
    } catch (err) {
      setLinkError(getErrorMessage(err, "Could not link patient."));
    } finally {
      setLinking(false);
    }
  }

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

        <div className="soft-card-tight" style={{ marginTop: 20, padding: 20 }}>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontWeight: 950, fontSize: 14, letterSpacing: "-0.02em" }}>
              {t("addAnotherDependant")}
            </div>
            <div className="muted-text" style={{ marginTop: 4, fontSize: 13, lineHeight: 1.5 }}>
              {t("addAnotherDependantDesc")}
            </div>
          </div>

          {linkError && (
            <div
              className="soft-card-tight"
              style={{ marginBottom: 12, padding: 12, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)", fontSize: 13 }}
            >
              {linkError}
            </div>
          )}

          {linkSuccess && (
            <div
              className="soft-card-tight"
              style={{ marginBottom: 12, padding: 12, borderColor: "var(--success-border)", background: "var(--success-bg)", color: "var(--success-text)", fontSize: 13 }}
            >
              {linkSuccess}
            </div>
          )}

          <form onSubmit={handleLinkPatient} style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <input
              type="text"
              className="form-input"
              value={linkCode}
              onChange={(e) => setLinkCode(e.target.value)}
              placeholder="BW-XXXX-XXXX"
              style={{ fontFamily: "monospace", flex: "1 1 180px", minWidth: 0 }}
              disabled={linking}
            />
            <button type="submit" className="primary-btn" disabled={linking || !linkCode.trim()}>
              {linking ? t("linking") : t("linkPatient")}
            </button>
          </form>
        </div>
      </div>
    </AppShell>
  );
}
