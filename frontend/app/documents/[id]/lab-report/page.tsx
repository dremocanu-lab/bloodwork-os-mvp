"use client";

/**
 * Standalone derived lab artifact reader — Clinical Document Intelligence
 * V3, Phase 9. A coherent lab report embedded inside a discharge document
 * appears in Documents as a real, independently openable clinical
 * artifact; opening it lands here and renders `StructuredLabReport(mode=
 * "standalone")` against the SAME canonical `LabResult` rows Phase 6
 * created on the parent document — never a copy, never a second lab
 * datastore. This page never fetches or shows a second data source: it
 * calls the exact same `GET /documents/{id}/clinical-reader` endpoint the
 * Phase 8 discharge reader uses, which already branches for a derived
 * artifact (see documents.py::get_clinical_reader_payload).
 *
 * Deliberately restrained (V3 contract): no "DERIVED" badge, no alarming
 * styling — just an honest, quiet "Derived from: <parent>" line, same
 * visual language as the rest of the reader.
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import type { ClinicalReaderResponse } from "@/lib/clinical-document-schema";
import { StructuredLabReport } from "@/components/clinical-reader/structured-lab-report";
import { isPdfContentType, ReaderSourceAction } from "@/components/clinical-reader/reader-source-action";
import { Status } from "@/components/ui";
import { resolveDocumentRoute } from "@/lib/document-routing";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

function Spinner({ size = 20 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes labReportSpin {
          to {
            transform: rotate(360deg);
          }
        }
        .lab-report-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: labReportSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="lab-report-spinner" />
    </>
  );
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function parentDocumentPath(parentId: number, parentDocumentType?: string | null) {
  return resolveDocumentRoute({ document_type: parentDocumentType }, parentId);
}

export default function DerivedLabReportPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;
  const { t, language } = useLanguage();

  const copy =
    language === "ro"
      ? {
          loading: "Se încarcă raportul...",
          loadFailed: "Nu s-a putut încărca raportul de laborator",
          loadFailedDesc: "Acest raport de laborator derivat nu a putut fi citit.",
          backToRecords: "Înapoi la evidențele mele",
          tryAgain: "Încearcă din nou",
          back: "Înapoi",
          verified: "Verificat",
          unverified: "Neverificat",
        }
      : {
          loading: "Loading laboratory report...",
          loadFailed: "Could not load this laboratory report",
          loadFailedDesc: "This derived laboratory report could not be read.",
          backToRecords: "Back to my records",
          tryAgain: "Try again",
          back: "Back",
          verified: "Verified",
          unverified: "Unverified",
        };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [payload, setPayload] = useState<ClinicalReaderResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      if (!documentId) return;
      try {
        setLoading(true);
        setError("");
        const meResponse = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(meResponse.data);

        const readerResponse = await api.get<ClinicalReaderResponse>(`/documents/${documentId}/clinical-reader`);

        // This route only ever renders a derived lab artifact — if the id
        // resolves to an ordinary document (e.g. a stale/typed-in URL),
        // hand off to the generic reader instead of rendering nothing.
        if (readerResponse.data.document.derived_artifact_kind !== "lab_report") {
          router.replace(`/documents/${documentId}`);
          return;
        }

        setPayload(readerResponse.data);
      } catch (err) {
        setError(getErrorMessage(err, copy.loadFailed));
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  if (loading) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner />
          <span className="muted-text">{copy.loading}</span>
        </div>
      </main>
    );
  }

  if (!currentUser || !payload) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, maxWidth: 620 }}>
          <div style={{ fontSize: 22, fontWeight: 600, marginBottom: 8 }}>{copy.loadFailed}</div>
          <div className="muted-text" style={{ lineHeight: 1.6 }}>
            {copy.loadFailedDesc}
          </div>
          {error ? (
            <div
              style={{
                marginTop: 14,
                padding: 14,
                borderRadius: "var(--r-lg)",
                background: "var(--danger-bg)",
                color: "var(--danger-text)",
                border: "1px solid var(--danger-border)",
                fontWeight: 600,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
              }}
            >
              {error}
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            <button className="secondary-btn" onClick={() => router.push("/my-records")}>
              {copy.backToRecords}
            </button>
            <button className="secondary-btn" onClick={() => window.location.reload()}>
              {copy.tryAgain}
            </button>
          </div>
        </div>
      </main>
    );
  }

  const { document, labs, derived_artifact: derivedArtifact } = payload;
  const parentIsPdf = isPdfContentType(derivedArtifact?.parent_content_type);

  return (
    <AppShell
      user={currentUser}
      title={t("laboratoryReport")}
      subtitle={document.test_date ? formatDate(document.test_date) : undefined}
      rightContent={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {derivedArtifact?.parent_document_id ? (
            <button
              type="button"
              className="b-btn b-btn-ghost b-btn-sm"
              onClick={() => router.push(parentDocumentPath(derivedArtifact.parent_document_id!, derivedArtifact.parent_document_type))}
            >
              {t("viewSourceDocument")}
            </button>
          ) : null}
          <button className="secondary-btn" onClick={() => router.back()}>
            {copy.back}
          </button>
        </div>
      }
    >
      {error ? (
        <div
          style={{
            marginBottom: "var(--s4)",
            padding: 12,
            borderRadius: "var(--r-lg)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
            border: "1px solid var(--danger-border)",
            fontSize: "var(--fs-caption)",
          }}
        >
          {error}
        </div>
      ) : null}

      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "flex-start",
          paddingBottom: "var(--s3)",
          borderBottom: "1px solid var(--border)",
          marginBottom: "var(--s4)",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: "var(--fs-h2, 20px)", fontWeight: 700, margin: 0, lineHeight: 1.3 }}>
            {t("laboratoryReport")}
          </h1>
          {derivedArtifact?.parent_report_name || derivedArtifact?.parent_filename ? (
            <div className="b-meta" style={{ fontSize: "var(--fs-caption)", marginTop: 4 }}>
              {t("derivedFrom")}: {derivedArtifact.parent_report_name || derivedArtifact.parent_filename}
            </div>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <Status tone={document.is_verified ? "ok" : "muted"}>{document.is_verified ? copy.verified : copy.unverified}</Status>
          {parentIsPdf ? (
            <ReaderSourceAction
              sourceEvidenceId={document.document_level_source_evidence_id}
              documentContentType={derivedArtifact?.parent_content_type}
            />
          ) : null}
        </div>
      </header>

      <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
        <StructuredLabReport labs={labs} documentContentType={derivedArtifact?.parent_content_type} mode="standalone" />
      </div>
    </AppShell>
  );
}
