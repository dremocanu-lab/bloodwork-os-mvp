"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { EmptyState, ErrorNote, Notice, SectionHead, Status } from "@/components/ui";
import { IconHeart } from "@/components/ui/icon";

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
    <AppShell
      user={currentUser}
      title={t("myDependants")}
      subtitle={t("myDependantsDesc")}
      density="comfortable"
    >
      <div className="b-stack" style={{ maxWidth: 760 }}>
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        {/* Linked patients. Was one bordered card per patient inside another
            card, with the details as a labelled list ("Date of Birth: …",
            "Sex: …"). Now list rows: the person's name leads and their
            details are one secondary line. */}
        <section className="b-surface">
          <SectionHead
            title={t("linkedPatients")}
            count={dependants.length}
            description={t("linkedPatientsDesc")}
          />

          {dependants.length === 0 ? (
            <EmptyState
              icon={<IconHeart size={17} />}
              title={t("noDependantsDesc")}
              description="Enter a patient's care partner code below to link them."
            />
          ) : (
            <div className="b-list">
              {dependants.map((dep) => (
                <div key={dep.patient_id} className="b-list-row" style={{ cursor: "default" }}>
                  <span className="b-avatar" aria-hidden="true">
                    {dep.full_name.charAt(0).toUpperCase()}
                  </span>
                  <span className="b-list-main">
                    <span className="b-list-title">{dep.full_name}</span>
                    <span className="b-list-sub">
                      {[
                        dep.sex,
                        dep.date_of_birth ? `${t("dateOfBirth")} ${dep.date_of_birth}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <span className="b-list-trail">
                    <Status tone="ok">Linked</Status>
                    <span className="b-range">{formatDate(dep.linked_at)}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Link another patient. */}
        <section className="b-surface">
          <SectionHead
            title={t("addAnotherDependant")}
            description={t("addAnotherDependantDesc")}
          />

          <div className="b-section-body">
            <div className="b-stack-tight">
              {linkError ? <ErrorNote>{linkError}</ErrorNote> : null}
              {linkSuccess ? <Notice tone="ok">{linkSuccess}</Notice> : null}

              <form
                onSubmit={handleLinkPatient}
                style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}
              >
                <input
                  type="text"
                  className="b-input"
                  value={linkCode}
                  onChange={(e) => setLinkCode(e.target.value)}
                  placeholder="BW-XXXX-XXXX"
                  aria-label={t("linkPatient")}
                  style={{
                    fontFamily: "ui-monospace, monospace",
                    letterSpacing: "0.05em",
                    flex: "1 1 200px",
                    minWidth: 0,
                    maxWidth: 280,
                  }}
                  disabled={linking}
                />
                <button
                  type="submit"
                  className="b-btn b-btn-primary b-btn-lg"
                  disabled={linking || !linkCode.trim()}
                >
                  {linking ? <span className="b-spinner" /> : null}
                  {linking ? t("linking") : t("linkPatient")}
                </button>
              </form>
            </div>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
