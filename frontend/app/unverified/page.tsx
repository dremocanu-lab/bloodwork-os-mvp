"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import AppShell from "@/components/app-shell";
import PageTabs from "@/components/page-tabs";
import StatCard from "@/components/stat-card";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
};

type SavedDocument = {
  id: number;
  patient_id?: number;
  filename: string;
  patient_name: string | null;
  report_name: string | null;
  test_date: string | null;
  section?: string;
  is_verified?: boolean;
};

export default function UnverifiedPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documents, setDocuments] = useState<SavedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [filterText, setFilterText] = useState("");

  const tabs = [
    { key: "all", label: t("all") },
    { key: "bloodwork", label: t("bloodwork") },
    { key: "other", label: t("otherSections") },
  ];

  const unverifiedDocuments = useMemo(
    () => documents.filter((doc) => !doc.is_verified),
    [documents]
  );

  const filteredDocuments = useMemo(() => {
    let docs = [...unverifiedDocuments];

    if (activeTab === "bloodwork") {
      docs = docs.filter((doc) => doc.section === "bloodwork");
    }

    if (activeTab === "other") {
      docs = docs.filter((doc) => doc.section !== "bloodwork");
    }

    if (filterText.trim()) {
      const term = filterText.trim().toLowerCase();
      docs = docs.filter((doc) => {
        const haystack = [
          doc.patient_name || "",
          doc.filename || "",
          doc.report_name || "",
          doc.section || "",
        ]
          .join(" ")
          .toLowerCase();

        return haystack.includes(term);
      });
    }

    return docs;
  }, [unverifiedDocuments, activeTab, filterText]);

  const bloodworkCount = useMemo(
    () => unverifiedDocuments.filter((doc) => doc.section === "bloodwork").length,
    [unverifiedDocuments]
  );

  const otherCount = useMemo(
    () => unverifiedDocuments.filter((doc) => doc.section !== "bloodwork").length,
    [unverifiedDocuments]
  );

  const fetchMe = async () => {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  };

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const response = await api.get<SavedDocument[]>("/documents");
      setDocuments(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load documents."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      const token =
        typeof window !== "undefined"
          ? localStorage.getItem("access_token")
          : null;

      if (!token) {
        router.push("/login");
        return;
      }

      const me = await fetchMe();
      if (!me) return;

      if (me.role === "patient" || me.role === "care_partner") {
        router.push(getHomeByRole(me.role));
        return;
      }

      await fetchDocuments();
    };

    init();
  }, []);

  if (!currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingQueue")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("unverifiedQueue")}
      subtitle={t("unverifiedQueueDesc")}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/")}>
          {t("backToDashboard")}
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

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16, marginBottom: 24 }}>
        <StatCard label={t("totalUnverified")} value={unverifiedDocuments.length} accent="orange" />
        <StatCard label={t("bloodwork")} value={bloodworkCount} accent="violet" />
        <StatCard label={t("otherSections")} value={otherCount} accent="blue" />
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto",
            gap: 12,
            alignItems: "end",
            marginBottom: 18,
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              {t("filterQueue")}
            </div>
            <input
              className="text-input"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder={t("filterQueuePlaceholder")}
            />
          </div>

          <button className="primary-btn" onClick={fetchDocuments}>
            {t("refreshQueue")}
          </button>
        </div>

        <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

        {loading ? (
          <p className="muted-text">{t("loadingQueue")}</p>
        ) : filteredDocuments.length === 0 ? (
          <p className="muted-text">{t("noUnverifiedDocuments")}</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("patient")}</th>
                  <th>{t("filename")}</th>
                  <th>{t("sectionColumn")}</th>
                  <th>{t("reportName")}</th>
                  <th>{t("date")}</th>
                  <th>{t("action")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.map((doc) => (
                  <tr key={doc.id}>
                    <td>{valueOrDash(doc.patient_name)}</td>
                    <td>{doc.filename}</td>
                    <td>{valueOrDash(doc.section)}</td>
                    <td>{valueOrDash(doc.report_name)}</td>
                    <td>{valueOrDash(doc.test_date)}</td>
                    <td>
                      {doc.patient_id ? (
                        <button
                          className="secondary-btn"
                          onClick={() => router.push(`/patients/${doc.patient_id}`)}
                        >
                          {t("openPatient")}
                        </button>
                      ) : (
                        <span className="muted-text">{t("noPatientLinked")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
