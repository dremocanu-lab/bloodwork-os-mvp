"use client";

/**
 * Discharge / clinical-document reader — Clinical Document Intelligence
 * V3, Phase 8. Rebuilt around the canonical `StructuredClinicalDocument`
 * contract (`GET /documents/{id}/clinical-reader`) instead of the old
 * ad-hoc `{document_type, sections}` payload this page used to parse
 * directly out of `note_body`. ONE reader for both an OLD document
 * (upconverted server-side, transparently, by `parse_structured_
 * document`) and a real forward-parsed one — never two parallel
 * implementations.
 *
 * Deliberately removed in this rebuild (see the V3 handoff, section
 * 9g, for the full reasoning): the flat `DischargeSection`/
 * `parseDischargePayload` legacy parsing, the font-size control (tied
 * to the old `<pre>`-based prose panel this structured UI no longer
 * has), and `OriginalLayoutViewer`/`original_layout` rendering — that
 * field is confirmed always empty in production (`original_layout_json`
 * is not a real `Document` column; see CURRENT_PIPELINE_MAP.md §17) so
 * the old "Original layout" reader mode never rendered anything real.
 * "View original"/"Open original file" now goes through the shared
 * `openSourceEvidence` system (or an honest direct-file-open fallback
 * for a non-PDF source) instead of always opening a new browser tab.
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { AskBragiSideTab } from "@/components/ask-bragi/ask-bragi-side-tab";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";
import type { ClinicalReaderResponse, ClinicalSection } from "@/lib/clinical-document-schema";
import { CANONICAL_SECTION_LABELS } from "@/lib/clinical-document-schema";
import { ClinicalBlockRenderer } from "@/components/clinical-reader/clinical-block-renderer";
import { ClinicalCourseTimeline } from "@/components/clinical-reader/clinical-course-timeline";
import { DocumentHeader } from "@/components/clinical-reader/document-header";
import { DocumentOutline } from "@/components/clinical-reader/document-outline";
import { StructuredLabReport } from "@/components/clinical-reader/structured-lab-report";
import { MedicationList } from "@/components/clinical-reader/medication-list";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type CarePartnerLink = {
  care_partner_user_id: number;
  care_partner_name: string;
  care_partner_email: string;
};

type DocumentShare = {
  care_partner_user_id: number;
  care_partner_name: string;
};

const MOBILE_BREAKPOINT = 900;

function Spinner({ size = 20 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes readerSpin {
          to {
            transform: rotate(360deg);
          }
        }
        .reader-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: readerSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="reader-spinner" />
    </>
  );
}

export default function DischargeStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;
  const { language } = useLanguage();

  const copy =
    language === "ro"
      ? {
          loading: "Se încarcă documentul...",
          loadFailed: "Nu s-a putut încărca documentul",
          loadFailedDesc: "Documentul nu a putut fi citit ca fișă clinică structurată.",
          backToRecords: "Înapoi la evidențele mele",
          tryAgain: "Încearcă din nou",
          back: "Înapoi",
          verified: "Verificat",
          unverified: "Neverificat",
          delete: "Șterge",
          share: "Distribuie",
          deleteConfirmTitle: "Ștergi acest document?",
          deleteConfirmBody: "Această acțiune este permanentă și nu poate fi anulată.",
          cancel: "Anulează",
          confirmDelete: "Șterge definitiv",
          noSharedYet: "Niciun partener de îngrijire adăugat încă.",
          shared: "Distribuit",
          notShared: "Nedistribuit",
          noStructuredContent: "Acest document nu are conținut clinic structurat disponibil.",
          clinicalCourse: "Cronologie clinică",
        }
      : {
          loading: "Loading document...",
          loadFailed: "Could not load this document",
          loadFailedDesc: "This document could not be read as a structured clinical record.",
          backToRecords: "Back to my records",
          tryAgain: "Try again",
          back: "Back",
          verified: "Verified",
          unverified: "Unverified",
          delete: "Delete",
          share: "Share",
          deleteConfirmTitle: "Delete this document?",
          deleteConfirmBody: "This action is permanent and cannot be undone.",
          cancel: "Cancel",
          confirmDelete: "Delete permanently",
          noSharedYet: "No care partners added yet.",
          shared: "Shared",
          notShared: "Not shared",
          noStructuredContent: "This document has no structured clinical content available.",
          clinicalCourse: "Clinical course timeline",
        };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [payload, setPayload] = useState<ClinicalReaderResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [carePartners, setCarePartners] = useState<CarePartnerLink[]>([]);
  const [documentShares, setDocumentShares] = useState<DocumentShare[]>([]);
  const [sharingId, setSharingId] = useState<number | null>(null);

  useEffect(() => {
    function onResize() {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    }
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    async function load() {
      if (!documentId) return;
      try {
        setLoading(true);
        setError("");
        const meResponse = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(meResponse.data);

        const readerResponse = await api.get<ClinicalReaderResponse>(`/documents/${documentId}/clinical-reader`);
        setPayload(readerResponse.data);

        const firstSection = readerResponse.data.structured_document?.sections?.[0];
        if (firstSection) setActiveSectionId(firstSection.id);

        if (meResponse.data.role === "patient") {
          const [cpResponse, sharesResponse] = await Promise.all([
            api.get<CarePartnerLink[]>("/my/care-partners"),
            api.get<DocumentShare[]>(`/documents/${documentId}/shares`),
          ]);
          setCarePartners(cpResponse.data || []);
          setDocumentShares(sharesResponse.data || []);
        }
      } catch (err) {
        setError(getErrorMessage(err, copy.loadFailed));
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const sections: ClinicalSection[] = payload?.structured_document?.sections || [];
  const activeSection = sections.find((s) => s.id === activeSectionId) || sections[0] || null;

  const canDelete = Boolean(currentUser && payload && currentUser.id) && currentUser?.role !== "care_partner";

  async function toggleShare(cpUserId: number) {
    if (!payload) return;
    const isShared = documentShares.some((s) => s.care_partner_user_id === cpUserId);
    try {
      setSharingId(cpUserId);
      if (isShared) {
        await api.delete(`/documents/${payload.document.id}/share/${cpUserId}`);
        setDocumentShares((prev) => prev.filter((s) => s.care_partner_user_id !== cpUserId));
      } else {
        await api.post(`/documents/${payload.document.id}/share`, { care_partner_user_id: cpUserId });
        const sharesResponse = await api.get<DocumentShare[]>(`/documents/${payload.document.id}/shares`);
        setDocumentShares(sharesResponse.data || []);
      }
    } catch (err) {
      setError(getErrorMessage(err, "Could not update share."));
    } finally {
      setSharingId(null);
    }
  }

  async function deleteDocument() {
    if (!payload) return;
    try {
      setDeleting(true);
      await api.delete(`/documents/${payload.document.id}`);
      if (currentUser?.role === "patient") {
        router.push("/my-records");
        return;
      }
      router.push(getHomeByRole(currentUser?.role ?? ""));
    } catch (err) {
      setError(getErrorMessage(err, copy.loadFailed));
      setConfirmDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  }

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

  const { document, structured_document: structuredDocument, labs, medications } = payload;

  return (
    <AppShell
      user={currentUser}
      title={document.report_name || document.filename}
      subtitle={`${document.document_type || "discharge_summary"} · ${document.is_verified ? copy.verified : copy.unverified}`}
      rightContent={
        <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
          {currentUser.role !== "care_partner" ? (
            <AskBragiSideTab
              target={{
                audience: currentUser.role === "patient" ? "patient" : "doctor",
                patientId: currentUser.role === "patient" ? undefined : document.id,
                documentId: document.id,
                initialScope: "document",
                suggestions: [
                  language === "ro" ? "De ce am fost internat?" : "Why was I admitted?",
                  language === "ro" ? "Ce urmărire a fost recomandată?" : "What follow-up was recommended?",
                  language === "ro" ? "Ce medicamente au fost menționate?" : "What medications were mentioned?",
                ],
              }}
            />
          ) : null}
          {currentUser.role === "patient" ? (
            <div style={{ position: "relative" }}>
              <button type="button" className="b-btn b-btn-ghost b-btn-sm" onClick={() => setShareOpen((v) => !v)}>
                {copy.share}
              </button>
              {shareOpen ? (
                <div
                  className="soft-card-tight"
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 6px)",
                    width: 260,
                    padding: 12,
                    background: "var(--panel)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-lg)",
                    boxShadow: "var(--shadow-md, 0 6px 24px rgba(0,0,0,0.12))",
                    zIndex: 20,
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  {carePartners.length === 0 ? (
                    <p className="b-meta" style={{ fontSize: "var(--fs-caption)", margin: 0 }}>
                      {copy.noSharedYet}
                    </p>
                  ) : (
                    carePartners.map((cp) => {
                      const isShared = documentShares.some((s) => s.care_partner_user_id === cp.care_partner_user_id);
                      return (
                        <div key={cp.care_partner_user_id} style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                          <span style={{ fontSize: "var(--fs-caption)" }}>{cp.care_partner_name}</span>
                          <button
                            type="button"
                            className="b-btn b-btn-ghost b-btn-sm"
                            disabled={sharingId === cp.care_partner_user_id}
                            onClick={() => toggleShare(cp.care_partner_user_id)}
                          >
                            {isShared ? copy.shared : copy.notShared}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
          {canDelete ? (
            <button type="button" className="b-btn b-btn-ghost b-btn-sm" onClick={() => setConfirmDeleteOpen(true)}>
              {copy.delete}
            </button>
          ) : null}
          <button className="secondary-btn" onClick={() => router.back()}>
            {copy.back}
          </button>
        </div>
      }
    >
      {confirmDeleteOpen ? (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "grid",
            placeItems: "center",
            zIndex: 200,
          }}
        >
          <div className="soft-card-tight" style={{ padding: 22, maxWidth: 420, background: "var(--panel)" }}>
            <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 8 }}>{copy.deleteConfirmTitle}</div>
            <p className="muted-text" style={{ lineHeight: 1.6 }}>
              {copy.deleteConfirmBody}
            </p>
            <div style={{ display: "flex", gap: 10, marginTop: 18, justifyContent: "flex-end" }}>
              <button className="secondary-btn" onClick={() => setConfirmDeleteOpen(false)} disabled={deleting}>
                {copy.cancel}
              </button>
              <button className="b-btn" style={{ background: "var(--danger)", color: "#fff" }} onClick={deleteDocument} disabled={deleting}>
                {deleting ? <Spinner size={14} /> : copy.confirmDelete}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <DocumentHeader document={document} metadata={structuredDocument?.metadata} />

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

      {!structuredDocument || sections.length === 0 ? (
        <p className="muted-text">{copy.noStructuredContent}</p>
      ) : isMobile ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
          <select
            aria-label="Document section"
            value={activeSection?.id || ""}
            onChange={(e) => setActiveSectionId(e.target.value)}
            className="text-input"
          >
            {sections.map((section) => (
              <option key={section.id} value={section.id}>
                {CANONICAL_SECTION_LABELS[section.canonical_key] || section.display_title}
              </option>
            ))}
          </select>
          {activeSection ? (
            <SectionContent
              section={activeSection}
              structuredDocument={structuredDocument}
              labs={labs}
              medications={medications}
              documentContentType={document.content_type}
              clinicalCourseLabel={copy.clinicalCourse}
            />
          ) : null}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 0.22fr) minmax(0, 1fr)", gap: "var(--s5)", alignItems: "start" }}>
          <DocumentOutline sections={sections} activeSectionId={activeSection?.id || null} onSelect={setActiveSectionId} />
          {activeSection ? (
            <SectionContent
              section={activeSection}
              structuredDocument={structuredDocument}
              labs={labs}
              medications={medications}
              documentContentType={document.content_type}
              clinicalCourseLabel={copy.clinicalCourse}
            />
          ) : null}
        </div>
      )}
    </AppShell>
  );
}

function SectionContent({
  section,
  structuredDocument,
  labs,
  medications,
  documentContentType,
  clinicalCourseLabel,
}: {
  section: ClinicalSection;
  structuredDocument: NonNullable<ClinicalReaderResponse["structured_document"]>;
  labs: ClinicalReaderResponse["labs"];
  medications: ClinicalReaderResponse["medications"];
  documentContentType?: string | null;
  clinicalCourseLabel: string;
}) {
  const events = structuredDocument.dated_events;

  return (
    <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
      <h2 className="b-section-title" style={{ marginTop: 0, marginBottom: 16 }}>
        {CANONICAL_SECTION_LABELS[section.canonical_key] || section.display_title}
      </h2>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
        {section.blocks.map((block, i) => (
          <ClinicalBlockRenderer
            key={i}
            block={block}
            labs={labs}
            medications={medications}
            events={events}
            documentContentType={documentContentType}
          />
        ))}

        {section.canonical_key === "clinical_course" && events.length > 0 ? (
          <div>
            <h3 className="b-label" style={{ marginBottom: 10 }}>
              {clinicalCourseLabel}
            </h3>
            <ClinicalCourseTimeline events={events} />
          </div>
        ) : null}

        {section.canonical_key === "laboratory_results" ? (
          <StructuredLabReport labs={labs} documentContentType={documentContentType} mode="embedded" />
        ) : null}

        {(section.canonical_key === "discharge_medications" || section.canonical_key === "medications") && medications.length > 0 ? (
          <MedicationList medications={medications} documentContentType={documentContentType} />
        ) : null}
      </div>
    </div>
  );
}
