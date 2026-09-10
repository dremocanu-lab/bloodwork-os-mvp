"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { EmptyState, ErrorNote, SectionHead, Status } from "@/components/ui";
import { IconClose, IconUpload } from "@/components/ui/icon";
import { api, getErrorMessage } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";
import { UploadStatus, useUploadManager } from "@/components/upload-provider";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type UploadItem = {
  id: string;
  file: File;
};

type DocumentTypeChoice = {
  value: string;
  label_en: string;
  label_ro: string;
};

type UploadRow = {
  id: string;
  jobId?: number;
  filename: string;
  size: number;
  status: UploadStatus | "selected";
  progress: number;
  message: string;
  error?: string;
  local: boolean;
  documentType?: string | null;
  classificationStatus?: string | null;
};

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin {
          to {
            transform: rotate(360deg);
          }
        }

        .bloodwork-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: bloodworkSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="bloodwork-spinner" />
    </>
  );
}

function formatFileSize(bytes: number) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function getFileBadge(fileOrName: File | string) {
  const name = typeof fileOrName === "string" ? fileOrName.toLowerCase() : fileOrName.name.toLowerCase();

  if (name.endsWith(".pdf")) return "PDF";
  if (name.endsWith(".png")) return "PNG";
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "JPG";
  if (name.endsWith(".webp")) return "WEBP";
  if (name.endsWith(".tif") || name.endsWith(".tiff")) return "TIFF";
  if (name.endsWith(".doc") || name.endsWith(".docx")) return "DOC";
  return "FILE";
}

function getUploadHint(file: File) {
  const name = file.name.toLowerCase();

  if (
    name.endsWith(".png") ||
    name.endsWith(".jpg") ||
    name.endsWith(".jpeg") ||
    name.endsWith(".webp") ||
    name.endsWith(".tif") ||
    name.endsWith(".tiff")
  ) {
    return "Image · will be identified automatically";
  }

  if (name.endsWith(".pdf")) {
    return "PDF · will be identified automatically";
  }

  return "File · will be saved to your records";
}

export default function MyRecordsUploadPage() {
  const router = useRouter();
  const { language } = useLanguage();
  const { enqueueAutoClassifyUploads, confirmDocumentType, confirmIdentity, visibleTasks, refreshUploadJobs } =
    useUploadManager();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        title: "Adaugă documente medicale",
        subtitle: "Selectează una sau mai multe analize, scrisori medicale, scanări sau rețete. Bragi le organizează automat.",
        back: "Înapoi la documentele mele",
        dragTitle: "Trage fișierele aici",
        browse: "Alege fișiere",
        supportText:
          "PDF-uri, imagini și documente scanate. Bragi identifică automat tipul fiecărui document — nu trebuie să alegi o categorie.",
        selectedFiles: "Fișiere selectate",
        noFiles: "Niciun fișier selectat încă",
        selected: "selectate",
        clear: "Șterge",
        upload: "Încarcă",
        continue: "Continuă",
        emptyTitle: "Lista este goală",
        emptyDesc: "Alege sau trage fișiere aici pentru a începe.",
        chooseAtLeastOneFile: "Alege cel puțin un fișier.",
        loadingUploadPage: "Se încarcă pagina de upload...",
        detecting: "Se identifică tipul documentului...",
        confirmType: "Confirmă tipul",
        confirmModalTitle: "Nu suntem complet siguri ce tip de document este",
        confirmModalDesc: "Cea mai bună estimare Bragi este mai jos. Alege tipul corect dacă e nevoie.",
        bestGuess: "Estimare Bragi",
        cancel: "Anulează",
        confirmAction: "Confirmă tipul",
        itsMe: "Sunt eu",
        notMine: "Nu e al meu",
        setAside: "Pus deoparte",
        alreadyUploaded: "Deja încărcat",
      };
    }

    return {
      title: "Add medical records",
      subtitle: "Select one or more lab results, medical letters, scans, or prescriptions. Bragi organizes them automatically.",
      back: "Back to my records",
      dragTitle: "Drag and drop files",
      browse: "Browse files",
      supportText:
        "PDFs, images, and scanned reports. Bragi automatically identifies each document's type — no need to pick a category.",
      selectedFiles: "Selected files",
      noFiles: "No files selected yet",
      selected: "selected",
      clear: "Clear",
      upload: "Upload",
      continue: "Continue",
      emptyTitle: "Your upload list is empty",
      emptyDesc: "Choose or drag files here to begin.",
      chooseAtLeastOneFile: "Choose at least one file.",
      loadingUploadPage: "Loading upload page...",
      detecting: "Identifying document type...",
      confirmType: "Confirm type",
      confirmModalTitle: "We're not completely sure what this document is",
      confirmModalDesc: "Bragi's best guess is below. Choose the correct type if it isn't right.",
      bestGuess: "Bragi's best guess",
      cancel: "Cancel",
      confirmAction: "Confirm type",
      itsMe: "It's me",
      notMine: "Not mine",
      setAside: "Set aside",
      alreadyUploaded: "Already uploaded",
    };
  }, [language]);

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [documentTypes, setDocumentTypes] = useState<DocumentTypeChoice[]>([]);
  const [confirmTarget, setConfirmTarget] = useState<UploadRow | null>(null);
  const [confirmChoice, setConfirmChoice] = useState("");
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");

  const canUpload = items.length > 0;

  const documentTypeLabel = useMemo(() => {
    const map = new Map(documentTypes.map((choice) => [choice.value, choice]));
    return (value?: string | null) => {
      if (!value) return null;
      const choice = map.get(value);
      if (!choice) return value;
      return language === "ro" ? choice.label_ro : choice.label_en;
    };
  }, [documentTypes, language]);

  const uploadRows = useMemo<UploadRow[]>(() => {
    const localRows = items.map((item) => ({
      id: item.id,
      filename: item.file.name,
      size: item.file.size,
      status: "selected" as const,
      progress: 0,
      message: getUploadHint(item.file),
      error: "",
      local: true,
    }));

    const taskRows = visibleTasks.map((task) => ({
      id: task.id,
      jobId: task.jobId,
      filename: task.filename,
      size: task.size,
      status: task.status,
      progress: task.progress,
      // Show the translated label only while the backend is literally on
      // that exact stage — not "while we don't know the type yet", which
      // never resolves for a mixed-PDF upload (split documents have no
      // single document_type on the job) and left this stuck for the
      // entire processing duration. Every later stage message (including
      // "Separating records...") comes from the backend and displays as-is,
      // same as the rest of the pipeline's untranslated status text.
      message:
        task.status === "processing" && task.message === "Identifying document type..."
          ? labels.detecting
          : task.message,
      error: task.error || "",
      local: false,
      documentType: task.documentType,
      classificationStatus: task.classificationStatus,
    }));

    return [...localRows, ...taskRows];
  }, [items, visibleTasks, labels.detecting]);

  const selectedSummary = useMemo(() => {
    if (!uploadRows.length) return labels.noFiles;
    return `${uploadRows.length} ${labels.selected}`;
  }, [uploadRows.length, labels]);

  useEffect(() => {
    async function init() {
      try {
        const response = await api.get<CurrentUser>("/auth/me");

        if (response.data.role !== "patient") {
          router.push(getHomeByRole(response.data.role));
          return;
        }

        setCurrentUser(response.data);
        await refreshUploadJobs();

        try {
          const typesResponse = await api.get<DocumentTypeChoice[]>("/document-types");
          setDocumentTypes(typesResponse.data);
        } catch {
          // Non-fatal: the confirm dialog falls back to raw values.
        }
      } catch {
        localStorage.removeItem("access_token");
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [router, refreshUploadJobs]);

  function appendFiles(fileList: FileList | File[]) {
    const nextFiles = Array.from(fileList);

    if (!nextFiles.length) return;

    setError("");
    setItems((prev) => [
      ...prev,
      ...nextFiles.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
      })),
    ]);

    if (hiddenFileInputRef.current) {
      hiddenFileInputRef.current.value = "";
    }
  }

  function removeFile(id: string) {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }

  function clearFiles() {
    setItems([]);
    setError("");

    if (hiddenFileInputRef.current) {
      hiddenFileInputRef.current.value = "";
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    if (event.dataTransfer.files?.length) {
      appendFiles(event.dataTransfer.files);
    }
  }

  function uploadDocuments() {
    if (!items.length) {
      setError(labels.chooseAtLeastOneFile);
      return;
    }

    enqueueAutoClassifyUploads(items.map((item) => item.file), {});

    setItems([]);
    setError("");
  }

  function openConfirm(row: UploadRow) {
    setConfirmTarget(row);
    setConfirmChoice(row.documentType || "");
    setConfirmError("");
  }

  function closeConfirm() {
    if (confirmBusy) return;
    setConfirmTarget(null);
    setConfirmError("");
  }

  async function submitConfirm() {
    if (!confirmTarget?.jobId || !confirmChoice) return;

    setConfirmBusy(true);
    setConfirmError("");

    try {
      await confirmDocumentType(confirmTarget.jobId, confirmChoice);
      setConfirmTarget(null);
    } catch (err) {
      setConfirmError(getErrorMessage(err, "Could not confirm document type."));
    } finally {
      setConfirmBusy(false);
    }
  }

  if (loading || !currentUser) {
    return (
      <main
        className="app-page-bg"
        style={{
          minHeight: "100vh",
          padding: 24,
          display: "grid",
          placeItems: "center",
        }}
      >
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", alignItems: "center", gap: 12 }}>
          <Spinner size={20} />
          <span className="muted-text">{labels.loadingUploadPage}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={labels.title}
      subtitle={labels.subtitle}
      density="comfortable"
      rightContent={
        <button
          type="button"
          className="b-btn b-btn-secondary"
          onClick={() => router.push("/my-records")}
        >
          {labels.back}
        </button>
      }
    >
      <div className="b-stack" style={{ maxWidth: 900 }}>
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        {/* The dropzone is the whole first step now — there is no document-type
            selector to fill in first. Bragi classifies each file from its
            content once it's uploaded (see the queue below), and only asks
            when it's genuinely unsure about one file. */}
        <section className="b-surface">
          <div style={{ padding: "var(--s4)" }}>
            <input
              ref={hiddenFileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(event) => appendFiles(event.target.files || [])}
            />

            <div
              className={`b-drop ${dragActive ? "is-over" : ""}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <span className="b-empty-icon">
                <IconUpload size={17} />
              </span>
              <div className="b-drop-title">{labels.dragTitle}</div>
              <button
                type="button"
                className="b-btn b-btn-secondary"
                onClick={() => hiddenFileInputRef.current?.click()}
              >
                {labels.browse}
              </button>
              <p className="b-drop-hint" style={{ maxWidth: "56ch" }}>
                {labels.supportText}
              </p>
            </div>
          </div>
        </section>

        {/* The queue. Each row states which file, how big, and where it is
            in the pipeline — including the type Bragi detected once it's
            known. A row with a "?" badge is the only one that needs input;
            everything else keeps moving on its own. */}
        <section className="b-surface">
          <SectionHead
            title={labels.selectedFiles}
            count={uploadRows.length || undefined}
            description={selectedSummary}
            actions={
              items.length ? (
                <button type="button" className="b-btn b-btn-ghost b-btn-sm" onClick={clearFiles}>
                  {labels.clear}
                </button>
              ) : null
            }
          />

          {uploadRows.length ? (
            <div>
              {uploadRows.map((row) => {
                const typeLabel = documentTypeLabel(row.documentType);

                return (
                  <div className="b-queue-row" key={row.id}>
                    <span
                      className="b-chip"
                      style={{
                        justifyContent: "center",
                        width: 34,
                        fontSize: "var(--fs-micro)",
                        flexShrink: 0,
                      }}
                    >
                      {getFileBadge(row.filename)}
                    </span>

                    <span style={{ minWidth: 0 }}>
                      <span className="b-cell-title" style={{ display: "block" }}>
                        {row.filename}
                      </span>
                      <span className="b-cell-sub" style={{ display: "block" }}>
                        {row.size ? `${formatFileSize(row.size)} · ` : ""}
                        {row.status === "done" && typeLabel ? typeLabel : row.message}
                      </span>

                      {row.status !== "selected" ? (
                        <span className="b-progress" style={{ display: "block", marginTop: 5 }}>
                          <span
                            className="b-progress-bar"
                            style={{
                              display: "block",
                              width: `${Math.max(row.progress || 5, 5)}%`,
                              background:
                                row.status === "error"
                                  ? "var(--danger)"
                                  : row.status === "done"
                                  ? "var(--ok)"
                                  : row.status === "needs_confirmation"
                                  ? "var(--warning, var(--danger))"
                                  : "var(--primary)",
                            }}
                          />
                        </span>
                      ) : null}

                      {row.error ? (
                        <span
                          style={{
                            display: "block",
                            marginTop: 4,
                            color: "var(--danger)",
                            fontSize: "var(--fs-xs)",
                            lineHeight: "var(--lh)",
                            maxHeight: 64,
                            overflow: "auto",
                          }}
                        >
                          {row.error}
                        </span>
                      ) : null}
                    </span>

                    <span
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--s2)",
                        flexShrink: 0,
                      }}
                    >
                      {row.status === "needs_confirmation" && confirmTarget?.id === row.id ? (
                        // Inline, anchored right at this file's own row —
                        // only THIS ambiguous file asks for input; every
                        // other row keeps processing independently, and
                        // the picker appears exactly where the user is
                        // already looking, not as a centered dialog that
                        // dims the rest of the upload queue.
                        <span
                          className="b-inline-confirm"
                          style={{ display: "flex", alignItems: "center", gap: "var(--s1)", flexWrap: "wrap" }}
                        >
                          <select
                            className="b-input"
                            style={{ height: 28, fontSize: "var(--fs-micro)", padding: "0 6px" }}
                            value={confirmChoice}
                            onChange={(event) => setConfirmChoice(event.target.value)}
                            disabled={confirmBusy}
                            autoFocus
                          >
                            {documentTypes.map((choice) => (
                              <option key={choice.value} value={choice.value}>
                                {language === "ro" ? choice.label_ro : choice.label_en}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="b-btn b-btn-primary b-btn-sm"
                            onClick={submitConfirm}
                            disabled={confirmBusy || !confirmChoice}
                          >
                            {confirmBusy ? <Spinner size={12} /> : null}
                            {labels.confirmAction}
                          </button>
                          <button
                            type="button"
                            className="b-btn b-btn-ghost b-btn-sm"
                            onClick={closeConfirm}
                            disabled={confirmBusy}
                          >
                            {labels.cancel}
                          </button>
                          {confirmError ? (
                            <span style={{ width: "100%", color: "var(--danger)", fontSize: "var(--fs-micro)" }}>
                              {confirmError}
                            </span>
                          ) : null}
                        </span>
                      ) : row.status === "needs_confirmation" ? (
                        <button
                          type="button"
                          className="b-btn b-btn-secondary b-btn-sm"
                          onClick={() => openConfirm(row)}
                        >
                          {labels.confirmType}
                        </button>
                      ) : row.status === "needs_identity_confirmation" ? (
                        <span style={{ display: "flex", gap: "var(--s1)" }}>
                          <button
                            type="button"
                            className="b-btn b-btn-secondary b-btn-sm"
                            onClick={() => row.jobId && confirmIdentity(row.jobId, true)}
                          >
                            {labels.itsMe}
                          </button>
                          <button
                            type="button"
                            className="b-btn b-btn-ghost b-btn-sm"
                            onClick={() => row.jobId && confirmIdentity(row.jobId, false)}
                          >
                            {labels.notMine}
                          </button>
                        </span>
                      ) : row.status === "quarantined" ? (
                        <Status tone="danger">{labels.setAside}</Status>
                      ) : row.status === "duplicate" ? (
                        <Status tone="muted">{labels.alreadyUploaded}</Status>
                      ) : row.status === "done" ? (
                        <Status tone="ok">Ready</Status>
                      ) : row.status === "error" ? (
                        <Status tone="danger">Failed</Status>
                      ) : row.status === "processing" ? (
                        <Status tone="processing">Processing</Status>
                      ) : row.status === "uploading" ? (
                        <Status tone="processing">Uploading</Status>
                      ) : row.status === "queued" ? (
                        <Status tone="info">Queued</Status>
                      ) : (
                        <Status tone="muted">Selected</Status>
                      )}

                      {row.local ? (
                        <button
                          type="button"
                          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
                          onClick={() => removeFile(row.id)}
                          aria-label={`Remove ${row.filename}`}
                        >
                          <IconClose size={13} />
                        </button>
                      ) : null}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState
              icon={<IconUpload size={17} />}
              title={labels.emptyTitle}
              description={labels.emptyDesc}
            />
          )}

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              gap: "var(--s2)",
              padding: "var(--s3) var(--s4)",
              borderTop: "1px solid var(--border)",
            }}
          >
            <button
              type="button"
              className="b-btn b-btn-secondary"
              onClick={() => router.push("/my-records")}
            >
              {labels.continue}
            </button>
            <button
              type="button"
              className="b-btn b-btn-primary"
              onClick={uploadDocuments}
              disabled={!canUpload}
            >
              <IconUpload size={14} />
              {labels.upload}
              {items.length ? ` (${items.length})` : ""}
            </button>
          </div>

          <p className="b-meta" style={{ padding: "0 var(--s4) var(--s3)" }}>
            Uploading continues in the background — you can leave this page and the
            documents will appear in your record when processing finishes.
          </p>
        </section>
      </div>

    </AppShell>
  );
}
