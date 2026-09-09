"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { EmptyState, ErrorNote, SectionHead, Status } from "@/components/ui";
import { IconClose, IconUpload } from "@/components/ui/icon";
import { api } from "@/lib/api";
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

type UploadRow = {
  id: string;
  filename: string;
  size: number;
  status: UploadStatus | "selected";
  progress: number;
  message: string;
  error?: string;
  local: boolean;
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

function UploadRowStatus({ status }: { status: UploadRow["status"] }) {
  if (status === "done") {
    return (
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: 999,
          display: "grid",
          placeItems: "center",
          background: "var(--success-bg)",
          color: "var(--success-text)",
          border: "1px solid var(--success-border)",
          fontWeight: 600,
          flex: "0 0 auto",
        }}
      >
        ✓
      </span>
    );
  }

  if (status === "error") {
    return (
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: 999,
          display: "grid",
          placeItems: "center",
          background: "var(--danger-bg)",
          color: "var(--danger-text)",
          border: "1px solid var(--danger-border)",
          fontWeight: 600,
          flex: "0 0 auto",
        }}
      >
        !
      </span>
    );
  }

  if (status === "selected") return null;

  return <Spinner size={18} />;
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
    return "Image · OCR may take longer";
  }

  if (name.endsWith(".pdf")) {
    return "PDF · will be structured automatically";
  }

  return "File · will be saved to your records";
}

export default function MyRecordsUploadPage() {
  const router = useRouter();
  const { language } = useLanguage();
  const { enqueueUploads, visibleTasks, refreshUploadJobs } = useUploadManager();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        title: "Încarcă documente",
        subtitle: "Adaugă analize, scanări, liste de medicamente sau alte documente medicale.",
        back: "Înapoi la documentele mele",
        documentType: "Tip document",
        documentTypeDesc: "Alege secțiunea unde vor fi organizate fișierele.",
        bloodwork: "Analize",
        dischargeSummary: "Fișă de externare",
        medications: "Medicație",
        scans: "Scanări",
        hospitalizations: "Spitalizări",
        other: "Altele",
        dragTitle: "Trage fișierele aici",
        or: "sau",
        browse: "Alege fișiere",
        supportText:
          "PDF-uri, imagini și documente scanate. După ce apeși Upload, procesarea continuă în fundal.",
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
      };
    }

    return {
      title: "Upload documents",
      subtitle: "Add bloodwork, scans, medication lists, hospital documents, or other records.",
      back: "Back to my records",
      documentType: "Document type",
      documentTypeDesc: "Choose where these files should be organized in your record.",
      bloodwork: "Bloodwork",
      dischargeSummary: "Discharge summary",
      medications: "Medications",
      scans: "Scans",
      hospitalizations: "Hospitalizations",
      other: "Other",
      dragTitle: "Drag and drop files",
      or: "or",
      browse: "Browse files",
      supportText:
        "PDFs, images, and scanned reports. After pressing Upload, processing continues in the background.",
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
    };
  }, [language]);

  const sections = useMemo(
    () => [
      { value: "bloodwork", label: labels.bloodwork },
      { value: "discharge_summary", label: labels.dischargeSummary },
      { value: "medications", label: labels.medications },
      { value: "scans", label: labels.scans },
      { value: "hospitalizations", label: labels.hospitalizations },
      { value: "other", label: labels.other },
    ],
    [labels]
  );

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const canUpload = items.length > 0;

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
      filename: task.filename,
      size: task.size,
      status: task.status,
      progress: task.progress,
      message: task.message,
      error: task.error || "",
      local: false,
    }));

    return [...localRows, ...taskRows];
  }, [items, visibleTasks]);

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

    enqueueUploads(
      items.map((item) => item.file),
      {
        section: uploadSection,
      }
    );

    setItems([]);
    setError("");
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

        {/* Step 1: where the files belong. Kept above the dropzone because the
            answer changes how the record is organised, and it is easy to
            forget once files are already queued. */}
        <section className="b-surface">
          <div
            className="b-toolbar"
            style={{ borderBottom: 0, alignItems: "center", minHeight: 52 }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="b-section-title">{labels.documentType}</div>
              <p className="b-meta" style={{ marginTop: 2 }}>
                {labels.documentTypeDesc}
              </p>
            </div>

            <select
              className="b-input"
              value={uploadSection}
              onChange={(event) => setUploadSection(event.target.value)}
              aria-label={labels.documentType}
              style={{ width: "auto", minWidth: 200, flexShrink: 0 }}
            >
              {sections.map((section) => (
                <option key={section.value} value={section.value}>
                  {section.label}
                </option>
              ))}
            </select>
          </div>
        </section>

        {/* Step 2: the dropzone. Was a 520px half-page panel with a 32px/950
            heading and a pill button; now a normal dashed dropzone that
            leaves the queue room to be the main event. */}
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

        {/* Step 3: the queue. Each row states which file, how big, and where
            it is in the pipeline - the state vocabulary that later phases
            (extraction, identity check, duplicate check, quarantine) can
            extend without another redesign. */}
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
              {uploadRows.map((row) => (
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
                      {row.message}
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
                    {row.status === "done" ? (
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
              ))}
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
