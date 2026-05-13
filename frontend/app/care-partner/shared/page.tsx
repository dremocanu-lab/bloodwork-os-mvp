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

const SECTION_ORDER = [
  "bloodwork",
  "discharge_summary",
  "medications",
  "hospitalizations",
  "scans",
  "other",
  "notes",
];

export default function SharedWithMePage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [sharedPages, setSharedPages] = useState<SharedPage[]>([]);
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

        const response = await api.get<SharedPage[]>("/my/shared-pages");
        setSharedPages(response.data || []);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load shared pages."));
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

  const grouped: Record<string, SharedPage[]> = {};
  for (const page of sharedPages) {
    const key = page.section || "other";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(page);
  }

  const sections = SECTION_ORDER.filter((s) => grouped[s]);

  return (
    <AppShell user={currentUser} title={t("sharedWithMe")} subtitle={t("sharedWithMeDesc")}>
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

      {sharedPages.length === 0 ? (
        <div className="soft-card" style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontWeight: 900, fontSize: 18, marginBottom: 8 }}>{t("nothingSharedYet")}</div>
          <div className="muted-text">{t("nothingSharedYetDesc")}</div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 24 }}>
          {sections.map((section) => (
            <div key={section} className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14, textTransform: "capitalize" }}>
                {section.replace(/_/g, " ")}
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                {grouped[section].map((page) => (
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
                        {page.patient_full_name}
                        {page.test_date ? ` · ${formatDate(page.test_date)}` : ""}
                      </div>
                    </div>
                    <div className="muted-text" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                      {t("sharedOn")} {formatDate(page.shared_at)}
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
