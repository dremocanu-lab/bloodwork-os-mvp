"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import AppShell from "@/components/app-shell";
import PageTabs from "@/components/page-tabs";
import StatCard from "@/components/stat-card";

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

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documents, setDocuments] = useState<SavedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [filterText, setFilterText] = useState("");

  const tabs = [
    { key: "all", label: "All" },
    { key: "bloodwork", label: "Bloodwork" },
    { key: "other", label: "Other Sections" },
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

      if (me.role === "patient") {
        router.push("/my-records");
        return;
      }

      await fetchDocuments();
    };

    init();
  }, []);

  if (!currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading...</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="Unverified Queue"
      subtitle="Review pending documents that still need human verification."
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/")}>
          Back to Dashboard
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "#fecaca",
            background: "#fef2f2",
            color: "#b91c1c",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16, marginBottom: 24 }}>
        <StatCard label="Total Unverified" value={unverifiedDocuments.length} accent="orange" />
        <StatCard label="Bloodwork" value={bloodworkCount} accent="violet" />
        <StatCard label="Other Sections" value={otherCount} accent="blue" />
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
              Filter queue
            </div>
            <input
              className="text-input"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="Filter by patient, filename, report, or section"
            />
          </div>

          <button className="primary-btn" onClick={fetchDocuments}>
            Refresh Queue
          </button>
        </div>

        <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

        {loading ? (
          <p className="muted-text">Loading queue...</p>
        ) : filteredDocuments.length === 0 ? (
          <p className="muted-text">No unverified documents found.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Filename</th>
                  <th>Section</th>
                  <th>Report</th>
                  <th>Date</th>
                  <th>Action</th>
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
                          Open Patient
                        </button>
                      ) : (
                        <span className="muted-text">No patient linked</span>
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