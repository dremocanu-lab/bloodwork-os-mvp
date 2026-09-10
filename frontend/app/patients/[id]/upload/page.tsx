"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { ErrorNote, SectionHead, Status } from "@/components/ui";
import { IconClose, IconUpload } from "@/components/ui/icon";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
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

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
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

  return "File · will be saved to the chart";
}

export default function DoctorPatientUploadPage() {
  const params = useParams();
  const router = useRouter();
  const { language } = useLanguage();
  const { enqueueUploads, visibleTasks, refreshUploadJobs } = useUploadManager();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);
  const patientId = params?.id as string;

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        title: "Încarcă documente",
        subtitle: "Încarcă analize, scanări sau documente clinice pentru pacient.",
        back: "Înapoi la fișă",
        documentType: "Tip document",
        documentTypeDesc: "Alege secțiunea unde va fi organizat documentul în fișa pacientului.",
        bloodwork: "Analize",
        dischargeSummary: "Fișă de externare",
        scans: "Scanări",
        medications: "Medicație",
        hospitalizations: "Spitalizări",
        other: "Altele",
        selectedFiles: "Fișiere selectate",
        selected: "selectate",
        noFilesSelectedYet: "Niciun fișier selectat încă",
        dragAndDropFiles: "Trage fișierele aici",
        or: "sau",
        browse: "Alege fișiere",
        uploadSupportText:
          "PDF-uri, imagini și documente scanate. După ce apeși Upload, procesarea continuă în fundal.",
        clear: "Șterge",
        upload: "Încarcă",
        continue: "Continuă",
        chooseAtLeastOneFile: "Alege cel puțin un fișier.",
        emptyTitle: "Lista este goală",
        emptyDesc: "Alege sau trage fișiere aici pentru a începe.",
        loadingPage: "Se încarcă pagina de upload...",
        failedLoad: "Nu s-a putut încărca pagina.",
      };
    }

    return {
      title: "Upload documents",
      subtitle: "Upload bloodwork, scans, or clinical files for this patient.",
      back: "Back to chart",
      documentType: "Document type",
      documentTypeDesc: "Choose where this document should be organized in the patient chart.",
      bloodwork: "Bloodwork",
      dischargeSummary: "Discharge summary",
      scans: "Scans",
      medications: "Medications",
      hospitalizations: "Hospitalizations",
      other: "Other",
      selectedFiles: "Selected files",
      selected: "selected",
      noFilesSelectedYet: "No files selected yet",
      dragAndDropFiles: "Drag and drop files",
      or: "or",
      browse: "Browse files",
      uploadSupportText:
        "PDFs, images, and scanned reports. After pressing Upload, processing continues in the background.",
      clear: "Clear",
      upload: "Upload",
      continue: "Continue",
      chooseAtLeastOneFile: "Choose at least one file.",
      emptyTitle: "Your upload list is empty",
      emptyDesc: "Choose or drag files here to begin.",
      loadingPage: "Loading upload page...",
      failedLoad: "Could not load upload page.",
    };
  }, [language]);

  const sections = useMemo(
    () => [
      { value: "bloodwork", label: labels.bloodwork },
      { value: "discharge_summary", label: labels.dischargeSummary },
      { value: "scans", label: labels.scans },
      { value: "medications", label: labels.medications },
      { value: "hospitalizations", label: labels.hospitalizations },
      { value: "other", label: labels.other },
    ],
    [labels]
  );

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

    const taskRows = visibleTasks
      .filter((task) => String(task.patientId || "") === String(patientId))
      .map((task) => ({
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
  }, [items, visibleTasks, patientId]);

  const selectedSummary = useMemo(() => {
    if (!uploadRows.length) return labels.noFilesSelectedYet;
    return `${uploadRows.length} ${labels.selected}`;
  }, [uploadRows.length, labels]);

  useEffect(() => {
    async function init() {
      try {
        setError("");

        const [meResponse, profileResponse] = await Promise.all([
          api.get<CurrentUser>("/auth/me"),
          api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
        ]);

        if (meResponse.data.role !== "doctor" && meResponse.data.role !== "admin") {
          router.push(`/patients/${patientId}`);
          return;
        }

        setCurrentUser(meResponse.data);
        setProfile(profileResponse.data);
        await refreshUploadJobs();
      } catch (err) {
        setError(getErrorMessage(err, labels.failedLoad));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [patientId, router, refreshUploadJobs, labels.failedLoad]);

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
        patientId,
        patientName: profile?.patient.full_name,
      }
    );

    setItems([]);
    setError("");
  }

  if (loading || !currentUser || !profile) {
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
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">{labels.loadingPage}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={labels.title}
      subtitle={`${profile.patient.full_name} · CNP ${valueOrDash(
        profile.patient.cnp
      )} · ID ${valueOrDash(profile.patient.patient_identifier)}`}
      breadcrumbs={[
        { label: profile.patient.full_name, href: `/patients/${patientId}` },
        { label: labels.title },
      ]}
      rightContent={
        <button
          type="button"
          className="b-btn b-btn-secondary"
          onClick={() => router.push(`/patients/${patientId}`)}
        >
          {labels.back}
        </button>
      }
    >
      <div className="b-stack" style={{ maxWidth: 900 }}>
        {error ? <ErrorNote>{error}</ErrorNote> : null}

        {/* One coherent upload workspace: where the files belong, the
            dropzone, and the queue all live in a single card. The section
            picker stays above the dropzone (it changes how the record gets
            organized, easy to forget once files are queued), but it no
            longer needs its own separate white card to say so. */}
        <section className="b-surface">
          <div
            className="b-toolbar"
            style={{ borderBottom: "1px solid var(--border)", alignItems: "center", minHeight: 52 }}
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

          <div style={{ padding: "0 var(--s4) var(--s4)" }}>
            <input
              ref={hiddenFileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(event) => appendFiles(event.target.files || [])}
            />

            {uploadRows.length ? (
              <div
                className={`b-drop-compact ${dragActive ? "is-over" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <span className="b-empty-icon" style={{ flexShrink: 0 }}>
                  <IconUpload size={15} />
                </span>
                <span style={{ minWidth: 0 }}>
                  <div className="b-drop-title">{labels.dragAndDropFiles}</div>
                  <p className="b-drop-hint">{labels.uploadSupportText}</p>
                </span>
                <button
                  type="button"
                  className="b-btn b-btn-secondary b-btn-sm"
                  style={{ marginLeft: "auto", flexShrink: 0 }}
                  onClick={() => hiddenFileInputRef.current?.click()}
                >
                  {labels.browse}
                </button>
              </div>
            ) : (
              <div
                className={`b-drop ${dragActive ? "is-over" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <span className="b-empty-icon">
                  <IconUpload size={17} />
                </span>
                <div className="b-drop-title">{labels.dragAndDropFiles}</div>
                <button
                  type="button"
                  className="b-btn b-btn-secondary"
                  onClick={() => hiddenFileInputRef.current?.click()}
                >
                  {labels.browse}
                </button>
                <p className="b-drop-hint" style={{ maxWidth: "56ch" }}>
                  {labels.uploadSupportText}
                </p>
              </div>
            )}
          </div>

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
          ) : null}

          {/* Single primary action — appears only once there's a local
              file to send; leaving via the header's "Back to chart" button
              already covers cancelling. */}
          {items.length ? (
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
              <button type="button" className="b-btn b-btn-primary" onClick={uploadDocuments}>
                <IconUpload size={14} />
                {labels.upload} ({items.length})
              </button>
            </div>
          ) : null}

          {uploadRows.length ? (
            <p className="b-meta" style={{ padding: "0 var(--s4) var(--s3)" }}>
              Uploading continues in the background — you can leave this page and the
              documents will appear in your record when processing finishes.
            </p>
          ) : null}
        </section>
      </div>
    </AppShell>
  );
}
