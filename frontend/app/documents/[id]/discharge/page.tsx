"use client";

/**
 * Discharge / clinical-document reader — Clinical Document Intelligence
 * V3 Phase 8, rebuilt again for Clinical Reader Intelligence V2.
 *
 * V2 adds, on top of the existing canonical `StructuredClinicalDocument`
 * contract (`GET /documents/{id}/clinical-reader`): an Overview panel,
 * real Diagnosis/Investigation/Recommendation cards (grounded, AI-
 * derived, never invented — see the backend's ai_interpreter.py), a
 * Current Hospitalization view separating this encounter from
 * historical narrative embedded in the same document, deterministic
 * empty-template section suppression, and an "Original narrative" mode
 * that always shows every section's raw content unfiltered — never a
 * regression in fidelity, only a smarter default presentation. None of
 * this requires a document to have been reprocessed: every new field is
 * additive and defaults to empty/None, so an un-reprocessed (or AI-
 * unavailable) document still renders exactly as much as it always did
 * via the existing canonical-section outline + ClinicalCourseTimeline/
 * StructuredLabReport/MedicationList components — this page degrades to
 * that, never to an error.
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { AskBragiSideTab } from "@/components/ask-bragi/ask-bragi-side-tab";
import { api, getErrorMessage } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";
import type { ClinicalReaderResponse, ClinicalSection } from "@/lib/clinical-document-schema";
import { CANONICAL_SECTION_LABELS } from "@/lib/clinical-document-schema";
import { ClinicalBlockRenderer } from "@/components/clinical-reader/clinical-block-renderer";
import { ClinicalCourseTimeline } from "@/components/clinical-reader/clinical-course-timeline";
import { DocumentHeader } from "@/components/clinical-reader/document-header";
import { StructuredLabReport } from "@/components/clinical-reader/structured-lab-report";
import { MedicationList } from "@/components/clinical-reader/medication-list";
import {
  AnomalyWarnings,
  CurrentHospitalizationEvents,
  DiagnosisList,
  InvestigationCards,
  OverviewPanel,
  RecommendationList,
} from "@/components/clinical-reader/interpretation-panels";

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

/** A navigable reader entry — either a real canonical section or one of
 * the new synthetic V2 views (Overview/Current Hospitalization/Original
 * narrative) that aren't themselves one of `structured_document.
 * sections[]`. Kept in ONE outline/dispatch list so there is exactly one
 * "what's in the nav, what renders when selected" mechanism, not two. */
type OutlineEntry =
  | { kind: "overview"; id: "overview" }
  | { kind: "current_encounter"; id: "current_encounter" }
  | { kind: "section"; id: string; section: ClinicalSection }
  | { kind: "original"; id: "original" };

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
          overview: "Rezumat",
          currentHospitalization: "Internarea curentă",
          original: "Narațiune sursă completă",
          reprocess: "Reorganizează cu AI",
          reprocessing: "Se reorganizează...",
          reprocessFailed: "Reorganizarea nu a putut fi finalizată.",
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
          overview: "Overview",
          currentHospitalization: "Current hospitalization",
          original: "Full source narrative",
          reprocess: "Reorganize with AI",
          reprocessing: "Reorganizing...",
          reprocessFailed: "Reorganizing could not be completed.",
        };

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [payload, setPayload] = useState<ClinicalReaderResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [carePartners, setCarePartners] = useState<CarePartnerLink[]>([]);
  const [documentShares, setDocumentShares] = useState<DocumentShare[]>([]);
  const [sharingId, setSharingId] = useState<number | null>(null);
  const [reprocessing, setReprocessing] = useState(false);

  useEffect(() => {
    function onResize() {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    }
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  async function loadReaderPayload() {
    const readerResponse = await api.get<ClinicalReaderResponse>(`/documents/${documentId}/clinical-reader`);
    setPayload(readerResponse.data);
    return readerResponse.data;
  }

  useEffect(() => {
    // `cancelled` guards against a StrictMode dev double-invoke (or a
    // real unmount/route change mid-fetch) landing its state updates
    // AFTER a newer load — without it, an initial `setActiveEntryId
    // ("overview")` from a slow, stale invocation could silently stomp
    // whatever section the user had already navigated to by the time it
    // resolves. This was a real, reproduced bug (a section click getting
    // reverted back to Overview a moment later), not a hypothetical one.
    let cancelled = false;

    async function load() {
      if (!documentId) return;
      try {
        setLoading(true);
        setError("");
        const meResponse = await api.get<CurrentUser>("/auth/me");
        if (cancelled) return;
        setCurrentUser(meResponse.data);

        const readerData = await loadReaderPayload();
        if (cancelled) return;

        // Canonical Document Intelligence V3 routing — a derived lab
        // artifact whose id lands here has no structured_document of
        // its own to render, so hand off to its real reader instead of
        // showing an empty state.
        if (readerData.document.derived_artifact_kind === "lab_report") {
          router.replace(`/documents/${documentId}/lab-report`);
          return;
        }

        setActiveEntryId("overview");

        if (meResponse.data.role === "patient") {
          const [cpResponse, sharesResponse] = await Promise.all([
            api.get<CarePartnerLink[]>("/my/care-partners"),
            api.get<DocumentShare[]>(`/documents/${documentId}/shares`),
          ]);
          if (cancelled) return;
          setCarePartners(cpResponse.data || []);
          setDocumentShares(sharesResponse.data || []);
        }
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, copy.loadFailed));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const structuredDocument = payload?.structured_document || null;
  const allSections: ClinicalSection[] = structuredDocument?.sections || [];
  // Empty-template sections (Part 12) are never shown in the intelligent
  // reader view — still fully available via "Original narrative" below,
  // which reads from `allSections` unfiltered.
  const visibleSections = allSections.filter((s) => !s.is_template_only);

  const currentEncounter = structuredDocument?.current_encounter || null;
  const hasCurrentEncounterContent = Boolean(
    currentEncounter && (currentEncounter.event_ids.length > 0 || currentEncounter.section_ids.length > 0)
  );

  const outline: OutlineEntry[] = useMemo(() => {
    if (!structuredDocument) return [];
    const entries: OutlineEntry[] = [{ kind: "overview", id: "overview" }];
    if (hasCurrentEncounterContent) entries.push({ kind: "current_encounter", id: "current_encounter" });
    for (const section of visibleSections) {
      entries.push({ kind: "section", id: section.id, section });
    }
    entries.push({ kind: "original", id: "original" });
    return entries;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structuredDocument, visibleSections.length, hasCurrentEncounterContent]);

  const activeEntry = outline.find((e) => e.id === activeEntryId) || outline[0] || null;

  const canDelete = Boolean(currentUser && payload && currentUser.id) && currentUser?.role !== "care_partner";
  const canReprocess = Boolean(currentUser) && currentUser?.role !== "care_partner";

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

  async function reprocessDocument() {
    if (!payload) return;
    try {
      setReprocessing(true);
      setError("");
      await api.post(`/documents/${payload.document.id}/reprocess-clinical-structure`);
      await loadReaderPayload();
    } catch (err) {
      setError(getErrorMessage(err, copy.reprocessFailed));
    } finally {
      setReprocessing(false);
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

  const { document, labs, medications } = payload;

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
                patientId: currentUser.role === "patient" ? undefined : document.patient_id,
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
          {canReprocess ? (
            <button type="button" className="b-btn b-btn-ghost b-btn-sm" onClick={reprocessDocument} disabled={reprocessing}>
              {reprocessing ? copy.reprocessing : copy.reprocess}
            </button>
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

      {!structuredDocument || outline.length === 0 ? (
        <p className="muted-text">{copy.noStructuredContent}</p>
      ) : isMobile ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
          <select
            aria-label="Document section"
            value={activeEntry?.id || ""}
            onChange={(e) => setActiveEntryId(e.target.value)}
            className="text-input"
          >
            {outline.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {outlineEntryLabel(entry, copy)}
              </option>
            ))}
          </select>
          {activeEntry ? (
            <EntryContent
              entry={activeEntry}
              structuredDocument={structuredDocument}
              labs={labs}
              medications={medications}
              documentContentType={document.content_type}
              copy={copy}
              allSections={allSections}
              onViewOriginal={() => setActiveEntryId("original")}
            />
          ) : null}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 0.22fr) minmax(0, 1fr)", gap: "var(--s5)", alignItems: "start" }}>
          <SyntheticOutline entries={outline} activeId={activeEntry?.id || null} onSelect={setActiveEntryId} copy={copy} />
          {activeEntry ? (
            <EntryContent
              entry={activeEntry}
              structuredDocument={structuredDocument}
              labs={labs}
              medications={medications}
              documentContentType={document.content_type}
              copy={copy}
              allSections={allSections}
              onViewOriginal={() => setActiveEntryId("original")}
            />
          ) : null}
        </div>
      )}
    </AppShell>
  );
}

function outlineEntryLabel(entry: OutlineEntry, copy: { overview: string; currentHospitalization: string; original: string }): string {
  if (entry.kind === "overview") return copy.overview;
  if (entry.kind === "current_encounter") return copy.currentHospitalization;
  if (entry.kind === "original") return copy.original;
  return CANONICAL_SECTION_LABELS[entry.section.canonical_key] || entry.section.display_title;
}

/** Renders the outline nav: real canonical sections plus the new
 * synthetic V2 entries (Overview/Current Hospitalization/Original) in
 * one list — one nav, one selection model, never two. */
function SyntheticOutline({
  entries,
  activeId,
  onSelect,
  copy,
}: {
  entries: OutlineEntry[];
  activeId: string | null;
  onSelect: (id: string) => void;
  copy: { overview: string; currentHospitalization: string; original: string };
}) {
  return (
    <nav aria-label="Document outline" className="b-doc-outline">
      <style jsx>{`
        .b-doc-outline {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .b-doc-outline-btn {
          text-align: left;
          padding: var(--s2) var(--s3);
          border-radius: var(--r-md);
          border: none;
          background: transparent;
          color: var(--text);
          font-size: var(--fs-caption);
          cursor: pointer;
        }
        .b-doc-outline-btn.active {
          background: var(--primary-soft);
          color: var(--primary);
          font-weight: 600;
        }
      `}</style>
      {entries.map((entry) => (
        <button
          key={entry.id}
          type="button"
          className={`b-doc-outline-btn ${entry.id === activeId ? "active" : ""}`}
          onClick={() => onSelect(entry.id)}
        >
          {outlineEntryLabel(entry, copy)}
        </button>
      ))}
    </nav>
  );
}

function EntryContent({
  entry,
  structuredDocument,
  labs,
  medications,
  documentContentType,
  copy,
  allSections,
  onViewOriginal,
}: {
  entry: OutlineEntry;
  structuredDocument: NonNullable<ClinicalReaderResponse["structured_document"]>;
  labs: ClinicalReaderResponse["labs"];
  medications: ClinicalReaderResponse["medications"];
  documentContentType?: string | null;
  copy: { clinicalCourse: string; currentHospitalization: string; original: string };
  allSections: ClinicalSection[];
  onViewOriginal: () => void;
}) {
  const events = structuredDocument.dated_events;

  if (entry.kind === "overview") {
    return (
      <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
        <OverviewPanel
          currentEncounter={structuredDocument.current_encounter}
          metadata={structuredDocument.metadata}
          diagnoses={structuredDocument.diagnoses}
          labs={labs}
          investigations={structuredDocument.investigations}
          recommendations={structuredDocument.recommendations}
          interpretationStatus={structuredDocument.interpretation?.status || null}
        />
        <div style={{ marginTop: "var(--s4)" }}>
          <AnomalyWarnings anomalies={structuredDocument.anomalies} />
        </div>
      </div>
    );
  }

  if (entry.kind === "current_encounter") {
    return (
      <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
        <h2 className="b-section-title" style={{ marginTop: 0, marginBottom: 16 }}>
          {copy.currentHospitalization}
        </h2>
        <CurrentHospitalizationEvents currentEncounter={structuredDocument.current_encounter} events={events} />
      </div>
    );
  }

  if (entry.kind === "original") {
    return (
      <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
        <h2 className="b-section-title" style={{ marginTop: 0, marginBottom: 16 }}>
          {copy.original}
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          {allSections.map((section) => (
            <div key={section.id}>
              <h3 className="b-label" style={{ marginBottom: 8 }}>
                {section.source_headings[0] || CANONICAL_SECTION_LABELS[section.canonical_key] || section.display_title}
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
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
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const section = entry.section;

  return (
    <div className="soft-card-tight" style={{ padding: 20, background: "var(--panel-2)", borderRadius: "var(--r-lg)" }}>
      <h2 className="b-section-title" style={{ marginTop: 0, marginBottom: 16 }}>
        {CANONICAL_SECTION_LABELS[section.canonical_key] || section.display_title}
      </h2>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
        {section.canonical_key === "diagnoses" && structuredDocument.diagnoses.length > 0 ? (
          <DiagnosisList diagnoses={structuredDocument.diagnoses} />
        ) : (section.canonical_key === "investigations" || section.canonical_key === "imaging") &&
          structuredDocument.investigations.length > 0 ? (
          <InvestigationCards investigations={structuredDocument.investigations} />
        ) : section.canonical_key === "recommendations" && structuredDocument.recommendations.length > 0 ? (
          <RecommendationList recommendations={structuredDocument.recommendations} />
        ) : section.canonical_key === "laboratory_results" ? (
          // Never fall through to the raw blocks below when canonical
          // LabResult rows exist for this document (Part 1F/8A) — and
          // never show BOTH a populated table and "no labs available" at
          // once (Part 1G/8E): when this section has real content but no
          // canonical rows parsed from it, that is its own distinct
          // "detected but could not be structured" state, not silence.
          <StructuredLabReport
            labs={labs}
            documentContentType={documentContentType}
            mode="embedded"
            rawSectionHasContent={section.blocks.length > 0}
            onViewOriginal={onViewOriginal}
          />
        ) : (section.canonical_key === "discharge_medications" || section.canonical_key === "medications") &&
          medications.length > 0 ? (
          <MedicationList medications={medications} documentContentType={documentContentType} />
        ) : (
          section.blocks.map((block, i) => (
            <ClinicalBlockRenderer
              key={i}
              block={block}
              labs={labs}
              medications={medications}
              events={events}
              documentContentType={documentContentType}
            />
          ))
        )}

        {section.canonical_key === "clinical_course" && events.length > 0 ? (
          <div>
            <h3 className="b-label" style={{ marginBottom: 10 }}>
              {copy.clinicalCourse}
            </h3>
            <ClinicalCourseTimeline events={events} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
