"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type UploadStatus = "queued" | "uploading" | "processing" | "done" | "error";

type UploadItem = {
  id: string;
  file: File;
  status: UploadStatus;
  phase?: string;
  progress?: number;
  error?: string;
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
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function getFileBadge(file: File) {
  const name = file.name.toLowerCase();

  if (name.endsWith(".pdf")) return "PDF";
  if (name.endsWith(".png")) return "PNG";
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "JPG";
  if (name.endsWith(".webp")) return "WEBP";
  if (name.endsWith(".doc") || name.endsWith(".docx")) return "DOC";
  return "FILE";
}

function isImageFile(file: File) {
  const name = file.name.toLowerCase();

  return (
    name.endsWith(".png") ||
    name.endsWith(".jpg") ||
    name.endsWith(".jpeg") ||
    name.endsWith(".webp") ||
    name.endsWith(".tif") ||
    name.endsWith(".tiff")
  );
}

function isPdfFile(file: File) {
  return file.name.toLowerCase().endsWith(".pdf");
}

function getQueuedPhase(file: File) {
  if (isImageFile(file)) return "Queued · images need OCR before AI extraction";
  if (isPdfFile(file)) return "Queued · PDFs usually process faster";
  return "Queued";
}

function getProcessingPhase(file: File) {
  if (isImageFile(file)) return "Reading image with OCR, then using AI to structure results...";
  if (isPdfFile(file)) return "Reading PDF text and using AI to structure results...";
  return "Reading document and saving structured record...";
}

export default function MyRecordsUploadPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);

  const sections = useMemo(
    () => [
      { value: "bloodwork", label: t("bloodwork") },
      { value: "medications", label: t("medications") },
      { value: "scans", label: t("scans") },
      { value: "hospitalizations", label: t("hospitalizations") },
      { value: "other", label: t("other") },
    ],
    [t]
  );

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function fetchMe() {
    try {
      const response = await api.get<CurrentUser>("/auth/me");

      if (response.data.role !== "patient") {
        router.push(response.data.role === "doctor" ? "/my-patients" : "/assignments");
        return null;
      }

      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  }

  useEffect(() => {
    async function init() {
      await fetchMe();
      setLoading(false);
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedCount = items.length;
  const uploadedCount = items.filter((item) => item.status === "done").length;
  const failedCount = items.filter((item) => item.status === "error").length;
  const processingCount = items.filter((item) => item.status === "uploading" || item.status === "processing").length;

  const canUpload = selectedCount > 0 && !uploading;

  const activeItem = items.find((item) => item.status === "uploading" || item.status === "processing");

  const uploadLabel = useMemo(() => {
    if (uploading) return `Processing ${uploadedCount}/${selectedCount}...`;
    if (!selectedCount) return t("upload");
    return `${t("upload")} ${selectedCount}`;
  }, [uploading, uploadedCount, selectedCount, t]);

  const selectedSummary = useMemo(() => {
    if (!selectedCount) return t("noFilesSelectedYet");

    const failedText = failedCount ? ` · ${failedCount} ${t("failed")}` : "";
    const processingText = processingCount ? ` · ${processingCount} processing` : "";

    return `${selectedCount} ${t("selected")} · ${uploadedCount} ${t("uploaded")}${processingText}${failedText}`;
  }, [selectedCount, uploadedCount, failedCount, processingCount, t]);

  function updateItem(id: string, patch: Partial<UploadItem>) {
    setItems((prev) => prev.map((current) => (current.id === id ? { ...current, ...patch } : current)));
  }

  function appendFiles(fileList: FileList | File[]) {
    const nextFiles = Array.from(fileList);

    if (!nextFiles.length) return;

    setError("");
    setItems((prev) => [
      ...prev,
      ...nextFiles.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
        status: "queued" as UploadStatus,
        phase: getQueuedPhase(file),
        progress: 0,
      })),
    ]);

    if (hiddenFileInputRef.current) {
      hiddenFileInputRef.current.value = "";
    }
  }

  function removeFile(id: string) {
    if (uploading) return;
    setItems((prev) => prev.filter((item) => item.id !== id));
  }

  function clearFiles() {
    if (uploading) return;

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

  async function uploadDocuments() {
    if (!items.length) {
      setError(t("chooseAtLeastOneFile"));
      return;
    }

    try {
      setUploading(true);
      setError("");

      let hadError = false;

      for (const item of items) {
        if (item.status === "done") continue;

        updateItem(item.id, {
          status: "uploading",
          phase: "Preparing secure upload...",
          progress: 3,
          error: undefined,
        });

        try {
          const formData = new FormData();
          formData.append("file", item.file);
          formData.append("section", uploadSection);

          await api.post("/upload", formData, {
            headers: { "Content-Type": "multipart/form-data" },
            onUploadProgress: (progressEvent) => {
              if (!progressEvent.total) {
                updateItem(item.id, {
                  status: "uploading",
                  phase: "Uploading file...",
                  progress: 20,
                });
                return;
              }

              const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
              const cappedPercent = Math.min(Math.max(percent, 5), 70);

              updateItem(item.id, {
                status: percent >= 100 ? "processing" : "uploading",
                phase: percent >= 100 ? getProcessingPhase(item.file) : `Uploading file... ${percent}%`,
                progress: cappedPercent,
              });
            },
          });

          updateItem(item.id, {
            status: "done",
            phase: "Done · structured record saved",
            progress: 100,
            error: undefined,
          });
        } catch (err) {
          hadError = true;

          updateItem(item.id, {
            status: "error",
            phase: "Upload failed",
            progress: 0,
            error: getErrorMessage(err, t("uploadFailed")),
          });
        }
      }

      if (!hadError) {
        setTimeout(() => {
          router.push("/my-records");
        }, 750);
      } else {
        setError(t("someFilesFailed"));
      }
    } finally {
      setUploading(false);
    }
  }

  function getStatusText(item: UploadItem) {
    if (item.status === "uploading") return ` · ${item.phase || "Uploading file..."}`;
    if (item.status === "processing") return ` · ${item.phase || getProcessingPhase(item.file)}`;
    if (item.status === "done") return ` · ${item.phase || t("fileUploaded")}`;
    if (item.status === "error") return ` · ${item.error || t("fileFailed")}`;
    return ` · ${item.phase || getQueuedPhase(item.file)}`;
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
        <div
          className="soft-card-tight"
          style={{
            padding: 22,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <Spinner size={20} />
          <span className="muted-text">{t("loadingUploadPage")}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("Upload Documents")}
      subtitle={t("Add bloodwork, scans, medication lists, hospital documents, or other records")}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/my-records")} disabled={uploading}>
          {t("backToMyRecords")}
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

      {uploading && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            display: "flex",
            alignItems: "center",
            gap: 12,
            borderColor: "var(--border)",
            background: "var(--panel-2)",
          }}
        >
          <Spinner size={20} />
          <div>
            <div style={{ fontWeight: 900 }}>{activeItem?.phase || "Processing document..."}</div>
            <div className="muted-text" style={{ marginTop: 4, lineHeight: 1.5 }}>
              Keep this page open. PDFs usually finish quickly; images can take longer because they need OCR before AI extraction.
            </div>
          </div>
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
            <div className="section-title">{t("documentType")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("")}
            </div>
          </div>

          <select
            className="text-input"
            value={uploadSection}
            onChange={(e) => setUploadSection(e.target.value)}
            disabled={uploading}
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

      <div
        className="soft-card"
        style={{
          padding: 0,
          overflow: "hidden",
          marginBottom: 24,
        }}
      >
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
              background: dragActive ? "var(--panel-2)" : "var(--panel)",
              transition: "background 160ms ease",
              opacity: uploading ? 0.78 : 1,
            }}
          >
            <input
              ref={hiddenFileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(e) => appendFiles(e.target.files || [])}
              disabled={uploading}
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
                {uploading ? (
                  <Spinner size={36} />
                ) : (
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 16,
                      display: "grid",
                      placeItems: "center",
                      fontSize: 38,
                      lineHeight: 1,
                      color: "var(--primary)",
                      fontWeight: 900,
                    }}
                  >
                    ↑
                  </div>
                )}
              </div>

              <div style={{ fontWeight: 950, fontSize: 32, letterSpacing: "-0.06em" }}>
                {uploading ? "Processing documents" : t("dragAndDropFiles")}
              </div>

              <div className="muted-text" style={{ marginTop: 10, fontSize: 16, lineHeight: 1.6 }}>
                {uploading
                  ? "The backend is reading the file, running OCR if needed, and using AI to structure the results."
                  : t("or")}
              </div>

              {!uploading && (
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
                  {t("browse")}
                </button>
              )}

              <div className="muted-text" style={{ marginTop: 18, lineHeight: 1.6 }}>
                {t("uploadSupportText")}
              </div>

              <div
                className="soft-card-tight"
                style={{
                  marginTop: 18,
                  padding: 14,
                  background: "var(--panel-2)",
                  textAlign: "left",
                }}
              >
                <div style={{ fontWeight: 900, marginBottom: 6 }}>AI extraction note</div>
                <div className="muted-text" style={{ lineHeight: 1.55 }}>
                  Bloodwork uploads are read and structured automatically. Images and scanned PDFs can take longer because they require OCR before AI
                  extraction. If a field is unclear, the system should leave it blank instead of guessing.
                </div>
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
                {t("selectedFiles")}
              </div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {selectedSummary}
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gap: 12,
                alignContent: "start",
                overflowY: "auto",
                overflowX: "hidden",
                paddingRight: 6,
                maxHeight: 360,
                minHeight: 0,
                scrollbarGutter: "stable",
              }}
            >
              {items.map((item) => (
                <div
                  key={item.id}
                  className="soft-card-tight"
                  style={{
                    padding: 14,
                    display: "grid",
                    gridTemplateColumns: "54px minmax(0, 1fr) auto",
                    gap: 12,
                    alignItems: "center",
                    borderColor:
                      item.status === "error"
                        ? "var(--danger-border)"
                        : item.status === "done"
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
                    {getFileBadge(item.file)}
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
                      {item.file.name}
                    </div>

                    <div className="muted-text" style={{ marginTop: 4, fontSize: 12, lineHeight: 1.45 }}>
                      {formatFileSize(item.file.size)}
                      {getStatusText(item)}
                    </div>

                    {(item.status === "uploading" || item.status === "processing") && (
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
                            width: `${item.status === "processing" ? Math.max(item.progress || 74, 74) : item.progress || 8}%`,
                            borderRadius: 999,
                            background: "var(--primary)",
                            transition: "width 180ms ease",
                          }}
                        />
                      </div>
                    )}
                  </div>

                  <div>
                    {item.status === "done" ? (
                      <span
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 999,
                          display: "grid",
                          placeItems: "center",
                          color: "var(--success-text)",
                          background: "var(--success-bg)",
                          fontWeight: 950,
                        }}
                      >
                        ✓
                      </span>
                    ) : item.status === "uploading" || item.status === "processing" ? (
                      <span
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 999,
                          display: "grid",
                          placeItems: "center",
                          background: "var(--panel-2)",
                        }}
                      >
                        <Spinner size={18} />
                      </span>
                    ) : item.status === "error" ? (
                      <span
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 999,
                          display: "grid",
                          placeItems: "center",
                          color: "var(--danger-text)",
                          background: "var(--danger-bg)",
                          fontWeight: 950,
                        }}
                      >
                        !
                      </span>
                    ) : (
                      <button type="button" className="secondary-btn" onClick={() => removeFile(item.id)} disabled={uploading} style={{ padding: "8px 10px" }}>
                        ×
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {!items.length && (
                <div
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    background: "var(--panel-2)",
                  }}
                >
                  <div style={{ fontWeight: 850 }}>{t("Upload List Empty")}</div>
                  <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                    {t("")}
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
              <button type="button" className="secondary-btn" onClick={clearFiles} disabled={uploading || !items.length}>
                {t("clear")}
              </button>

              <button
                type="button"
                className="primary-btn"
                onClick={uploadDocuments}
                disabled={!canUpload}
                style={{
                  padding: "13px 18px",
                  borderRadius: 16,
                  fontWeight: 950,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                {uploading && <Spinner size={16} />}
                {uploadLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}