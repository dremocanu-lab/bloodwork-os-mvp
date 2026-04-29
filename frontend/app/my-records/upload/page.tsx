"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api } from "@/lib/api";
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
          fontWeight: 950,
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
          fontWeight: 950,
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

function isActiveUpload(status: UploadStatus | "selected") {
  return status === "queued" || status === "uploading" || status === "processing";
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
          router.push(response.data.role === "doctor" ? "/my-patients" : "/assignments");
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
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/my-records")}>
          {labels.back}
        </button>
      }
    >
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

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <div>
            <div className="section-title">{labels.documentType}</div>
            <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.55 }}>
              {labels.documentTypeDesc}
            </div>
          </div>

          <select
            className="text-input"
            value={uploadSection}
            onChange={(event) => setUploadSection(event.target.value)}
            style={{ width: 260 }}
          >
            {sections.map((section) => (
              <option key={section.value} value={section.value}>
                {section.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 0, overflow: "hidden", marginBottom: 24 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(320px, 1fr) minmax(320px, 0.9fr)",
            minHeight: 520,
          }}
        >
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            style={{
              display: "grid",
              placeItems: "center",
              padding: 34,
              borderRight: "1px solid var(--border)",
              background: dragActive
                ? "linear-gradient(135deg, color-mix(in srgb, var(--primary) 12%, var(--panel)), var(--panel))"
                : "var(--panel)",
              transition: "background 160ms ease",
            }}
          >
            <input
              ref={hiddenFileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(event) => appendFiles(event.target.files || [])}
            />

            <div style={{ textAlign: "center", maxWidth: 440 }}>
              <div
                style={{
                  width: 92,
                  height: 92,
                  borderRadius: 30,
                  border: "1px solid var(--border)",
                  background: "var(--panel-2)",
                  display: "grid",
                  placeItems: "center",
                  margin: "0 auto 22px",
                }}
              >
                <div style={{ fontSize: 38, lineHeight: 1, color: "var(--primary)", fontWeight: 900 }}>↑</div>
              </div>

              <div style={{ fontWeight: 950, fontSize: 32, letterSpacing: "-0.06em" }}>
                {labels.dragTitle}
              </div>

              <div className="muted-text" style={{ marginTop: 10, fontSize: 16 }}>
                {labels.or}
              </div>

              <button
                type="button"
                className="primary-btn"
                style={{
                  marginTop: 16,
                  minWidth: 210,
                  padding: "15px 22px",
                  borderRadius: 16,
                  fontSize: 16,
                  fontWeight: 950,
                }}
                onClick={() => hiddenFileInputRef.current?.click()}
              >
                {labels.browse}
              </button>

              <div className="muted-text" style={{ marginTop: 18, lineHeight: 1.6 }}>
                {labels.supportText}
              </div>
            </div>
          </div>

          <div
            style={{
              padding: 28,
              background: "var(--panel)",
              display: "grid",
              gridTemplateRows: "auto minmax(0, 1fr) auto",
              gap: 18,
              minWidth: 0,
              maxHeight: 520,
            }}
          >
            <div>
              <div style={{ fontWeight: 950, fontSize: 22, letterSpacing: "-0.04em" }}>
                {labels.selectedFiles}
              </div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {selectedSummary}
              </div>
            </div>

            <div style={{ display: "grid", gap: 12, alignContent: "start", overflowY: "auto", paddingRight: 6 }}>
              {uploadRows.map((row) => (
                <div
                  key={row.id}
                  className="soft-card-tight"
                  style={{
                    padding: 14,
                    display: "grid",
                    gridTemplateColumns: "54px minmax(0, 1fr) auto",
                    gap: 12,
                    alignItems: "center",
                    borderColor:
                      row.status === "error"
                        ? "var(--danger-border)"
                        : row.status === "done"
                        ? "var(--success-border)"
                        : "var(--border)",
                  }}
                >
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: 999,
                      border: "1px solid var(--border)",
                      background: "var(--panel-2)",
                      display: "grid",
                      placeItems: "center",
                      fontWeight: 950,
                      fontSize: 12,
                      color: "var(--muted)",
                    }}
                  >
                    {getFileBadge(row.filename)}
                  </div>

                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 850,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {row.filename}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4, fontSize: 12, lineHeight: 1.45 }}>
                      {row.size ? `${formatFileSize(row.size)} · ` : ""}
                      {row.message}
                    </div>

                    {row.status !== "selected" && (
                      <div
                        style={{
                          marginTop: 10,
                          height: 7,
                          borderRadius: 999,
                          background: "var(--panel-2)",
                          overflow: "hidden",
                          border: "1px solid var(--border)",
                        }}
                      >
                        <div
                          style={{
                            height: "100%",
                            width: `${Math.max(row.progress || 5, 5)}%`,
                            borderRadius: 999,
                            background:
                              row.status === "error"
                                ? "var(--danger-text)"
                                : row.status === "done"
                                ? "var(--success-text)"
                                : "var(--primary)",
                            transition: "width 180ms ease",
                          }}
                        />
                      </div>
                    )}

                    {row.error && (
                      <div
                        style={{
                          marginTop: 8,
                          color: "var(--danger-text)",
                          fontSize: 12,
                          lineHeight: 1.45,
                          maxHeight: 70,
                          overflow: "auto",
                        }}
                      >
                        {row.error}
                      </div>
                    )}
                  </div>

                  {row.local ? (
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => removeFile(row.id)}
                      style={{ padding: "8px 10px" }}
                    >
                      ×
                    </button>
                  ) : (
                    <UploadRowStatus status={row.status} />
                  )}
                </div>
              ))}

              {!uploadRows.length && (
                <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                  <div style={{ fontWeight: 850 }}>{labels.emptyTitle}</div>
                  <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                    {labels.emptyDesc}
                  </div>
                </div>
              )}
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                flexWrap: "wrap",
                borderTop: "1px solid var(--border)",
                paddingTop: 18,
              }}
            >
              <button type="button" className="secondary-btn" onClick={clearFiles} disabled={!items.length}>
                {labels.clear}
              </button>

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="primary-btn"
                  onClick={uploadDocuments}
                  disabled={!canUpload}
                  style={{ padding: "13px 18px", borderRadius: 16, fontWeight: 950 }}
                >
                  {labels.upload}
                </button>

                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => router.push("/my-records")}
                  style={{ padding: "13px 18px", borderRadius: 16, fontWeight: 950 }}
                >
                  {labels.continue}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}