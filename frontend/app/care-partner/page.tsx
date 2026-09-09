"use client";

/**
 * Care partner home.
 *
 * Was two 40px/950 figures and then three cards that just repeated the
 * sidebar's own destinations - a dashboard that navigated instead of
 * informing. A care partner opens Bragi to answer "who am I looking after,
 * and what is new for them?", so that is what the page now leads with: the
 * linked patients, then what has recently been shared.
 *
 * Kept simpler than the clinician workspaces on purpose - no trends, no
 * density controls, plain language.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  EmptyState,
  ErrorNote,
  Metric,
  Metrics,
  SectionHead,
  TableSkeleton,
} from "@/components/ui";
import {
  IconChevronRight,
  IconDocument,
  IconHeart,
  IconUpload,
} from "@/components/ui/icon";
import type { NavUser } from "@/lib/navigation";

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

function initials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") || "P"
  );
}

export default function CarePartnerDashboardPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<NavUser | null>(null);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [sharedPages, setSharedPages] = useState<SharedPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<NavUser>("/auth/me");

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
      <main className="app-page-bg" style={{ padding: "var(--s6)" }}>
        <div className="b-surface">
          <TableSkeleton rows={5} columns={2} />
        </div>
      </main>
    );
  }

  const recentShared = sharedPages.slice(0, 6);

  return (
    <AppShell
      user={currentUser}
      title={t("carePartnerDashboard")}
      subtitle={t("carePartnerDashboardDesc")}
      density="comfortable"
      rightContent={
        <Link href="/care-partner/upload" className="b-btn b-btn-primary">
          <IconUpload size={14} />
          {t("uploadDocuments")}
        </Link>
      }
    >
      <div className="b-stack">
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        <Metrics>
          <Metric label={t("myDependants")} value={dependants.length} />
          <Metric label={t("sharedWithMe")} value={sharedPages.length} />
        </Metrics>

        {/* Who you look after, first. */}
        <section className="b-surface">
          <SectionHead
            title={t("myDependants")}
            count={dependants.length}
            description={t("myDependantsDesc")}
            actions={
              <Link href="/care-partner/dependants" className="b-btn b-btn-secondary b-btn-sm">
                {t("viewAll").replace(" →", "")}
                <IconChevronRight size={12} />
              </Link>
            }
          />
          <div className="b-section-body b-section-body-flush">
            {dependants.length ? (
              <div className="b-list">
                {dependants.map((dependant) => (
                  <Link
                    key={dependant.patient_id}
                    href="/care-partner/dependants"
                    className="b-list-row"
                    style={{ textDecoration: "none" }}
                  >
                    <span className="b-avatar" aria-hidden="true">
                      {initials(dependant.full_name)}
                    </span>
                    <span className="b-list-main">
                      <span className="b-list-title">{dependant.full_name}</span>
                      <span className="b-list-sub">
                        {[
                          dependant.sex,
                          dependant.date_of_birth ? `Born ${formatDate(dependant.date_of_birth)}` : null,
                          `Linked ${formatDate(dependant.linked_at)}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                    <span className="b-list-trail">
                      <IconChevronRight size={13} className="b-list-chevron" />
                    </span>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<IconHeart size={17} />}
                title="No linked patients yet"
                description="Ask the person you care for to share their Bragi care-partner code with you."
                actions={
                  <Link href="/care-partner/dependants" className="b-btn b-btn-secondary">
                    {t("myDependants")}
                  </Link>
                }
              />
            )}
          </div>
        </section>

        <section className="b-surface">
          <SectionHead
            title={t("recentlyShared")}
            count={sharedPages.length}
            description={t("sharedWithMeDesc")}
            actions={
              sharedPages.length > recentShared.length ? (
                <Link href="/care-partner/shared" className="b-btn b-btn-secondary b-btn-sm">
                  {t("viewAll").replace(" →", "")}
                  <IconChevronRight size={12} />
                </Link>
              ) : null
            }
          />
          <div className="b-section-body b-section-body-flush">
            {recentShared.length ? (
              <div className="b-list">
                {recentShared.map((page) => (
                  <Link
                    key={page.document_id}
                    href={`/documents/${page.document_id}`}
                    className="b-list-row"
                    style={{ textDecoration: "none" }}
                  >
                    <span className="b-list-main">
                      <span className="b-list-title">
                        {page.report_name || page.filename || t("document")}
                      </span>
                      <span className="b-list-sub">
                        {[
                          page.patient_full_name,
                          page.section,
                          page.test_date ? formatDate(page.test_date) : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                    <span className="b-list-trail">
                      <span className="b-range">{formatDate(page.shared_at)}</span>
                      <IconChevronRight size={13} className="b-list-chevron" />
                    </span>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<IconDocument size={17} />}
                title="Nothing shared with you yet"
                description="Documents a patient shares directly with you will appear here."
              />
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
