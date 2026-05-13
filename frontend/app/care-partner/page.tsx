"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
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

type SharedPage = {
  document_id: number;
  patient_full_name?: string | null;
  section?: string | null;
  test_date?: string | null;
  report_name?: string | null;
  filename?: string | null;
  shared_at: string;
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function CarePartnerDashboardPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [sharedPages, setSharedPages] = useState<SharedPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");

        if (meResponse.data.role !== "care_partner") {
          if (meResponse.data.role === "patient") router.replace("/my-records");
          else if (meResponse.data.role === "doctor") router.replace("/my-patients");
          else router.replace("/assignments");
          return;
        }

        setCurrentUser(meResponse.data);

        const [dependantsResponse, sharedResponse] = await Promise.all([
          api.get<Dependant[]>("/my/dependants"),
          api.get<SharedPage[]>("/my/shared-pages"),
        ]);

        setDependants(dependantsResponse.data || []);
        setSharedPages(sharedResponse.data || []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load data."));
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

  const recentShared = sharedPages.slice(0, 5);

  return (
    <AppShell user={currentUser} title={t("carePartnerDashboard")} subtitle={t("carePartnerDashboardDesc")}>
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

      <div style={{ display: "grid", gap: 20 }}>
        {/* Stat strip */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: 12,
          }}
        >
          <div className="soft-card" style={{ padding: "16px 20px" }}>
            <div className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
              {t("myDependants")}
            </div>
            <div style={{ fontSize: 40, fontWeight: 950, letterSpacing: "-0.05em", lineHeight: 1.1, marginTop: 6 }}>
              {dependants.length}
            </div>
          </div>

          <div className="soft-card" style={{ padding: "16px 20px" }}>
            <div className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
              {t("sharedWithMe")}
            </div>
            <div style={{ fontSize: 40, fontWeight: 950, letterSpacing: "-0.05em", lineHeight: 1.1, marginTop: 6 }}>
              {sharedPages.length}
            </div>
          </div>
        </div>

        {/* Quick actions */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          <Link
            href="/care-partner/upload"
            className="soft-card"
            style={{
              padding: 20,
              textDecoration: "none",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ fontSize: 22 }}>↑</div>
            <div style={{ fontWeight: 900 }}>{t("uploadDocuments")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("carePartnerUploadDesc")}</div>
          </Link>

          <Link
            href="/care-partner/shared"
            className="soft-card"
            style={{
              padding: 20,
              textDecoration: "none",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ fontSize: 22 }}>◫</div>
            <div style={{ fontWeight: 900 }}>{t("sharedWithMe")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("sharedWithMeDesc")}</div>
          </Link>

          <Link
            href="/care-partner/dependants"
            className="soft-card"
            style={{
              padding: 20,
              textDecoration: "none",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ fontSize: 22 }}>+</div>
            <div style={{ fontWeight: 900 }}>{t("myDependants")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>{t("myDependantsDesc")}</div>
          </Link>
        </div>

        {/* Recent shared pages */}
        {recentShared.length > 0 && (
          <div className="soft-card" style={{ padding: 24 }}>
            <div style={{ marginBottom: 16 }}>
              <div className="section-title">{t("recentlyShared")}</div>
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              {recentShared.map((page) => (
                <Link
                  key={page.document_id}
                  href={`/documents/${page.document_id}`}
                  className="soft-card-tight"
                  style={{
                    padding: 16,
                    textDecoration: "none",
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1fr) auto",
                    gap: 12,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 900 }}>
                      {page.report_name || page.filename || t("document")}
                    </div>
                    <div className="muted-text" style={{ marginTop: 3, fontSize: 13 }}>
                      {page.patient_full_name} · {page.section}
                      {page.test_date ? ` · ${formatDate(page.test_date)}` : ""}
                    </div>
                  </div>
                  <div className="muted-text" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    {formatDate(page.shared_at)}
                  </div>
                </Link>
              ))}
            </div>

            {sharedPages.length > 5 && (
              <div style={{ marginTop: 14 }}>
                <Link href="/care-partner/shared" className="secondary-btn" style={{ textDecoration: "none" }}>
                  {t("viewAll")} ({sharedPages.length})
                </Link>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
