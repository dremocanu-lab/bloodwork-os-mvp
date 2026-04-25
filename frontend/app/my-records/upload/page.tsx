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

type UploadStatus = "queued" | "uploading" | "done" | "error";

type UploadItem = {
  id: string;
  file: File;
  status: UploadStatus;
  error?: string;
};

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
  }, []);

  const selectedCount = items.length;
  const uploadedCount = items.filter((item) => item.status === "done").length;
  const failedCount = items.filter((item) => item.status === "error").length;

  const canUpload = selectedCount > 0 && !uploading;

  const uploadLabel = useMemo(() => {
    if (uploading) return `${t("uploading")} ${uploadedCount}/${selectedCount}...`;
    if (!selectedCount) return t("upload");
    return `${t("upload")} ${selectedCount}`;
  }, [uploading, uploadedCount, selectedCount, t]);

  const selectedSummary = useMemo(() => {
    if (!selectedCount) return t("noFilesSelectedYet");

    const failedText = failedCount ? ` · ${failedCount} ${t("failed")}` : "";
    return `${selectedCount} ${t("selected")} · ${uploadedCount} ${t("uploaded")}${failedText}`;
  }, [selectedCount, uploadedCount, failedCount, t]);

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
        setItems((prev) =>
          prev.map((current) =>
            current.id === item.id ? { ...current, status: "uploading", error: undefined } : current
          )
        );

        try {
          const formData = new FormData();
          formData.append("file", item.file);
          formData.append("section", uploadSection);

          await api.post("/upload", formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });

          setItems((prev) =>
            prev.map((current) =>
              current.id === item.id ? { ...current, status: "done", error: undefined } : current
            )
          );
        } catch (err) {
          hadError = true;

          setItems((prev) =>
            prev.map((current) =>
              current.id === item.id
                ? {
                    ...current,
                    status: "error",
                    error: getErrorMessage(err, t("uploadFailed")),
                  }
                : current
            )
          );
        }
      }

      if (!hadError) {
        setTimeout(() => {
          router.push("/my-records");
        }, 650);
      } else {
        setError(t("someFilesFailed"));
      }
    } finally {
      setUploading(false);
    }
  }

  function getStatusText(item: UploadItem) {
    if (item.status === "uploading") return ` · ${t("fileUploading")}`;
    if (item.status === "done") return ` · ${t("fileUploaded")}`;
    if (item.status === "error") return ` · ${item.error || t("fileFailed")}`;
    return "";
  }

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingUploadPage")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("uploadDocumentsTitle")}
      subtitle={t("uploadDocumentsSubtitle")}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/my-records")}>
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
              {t("documentTypeDesc")}
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
            }}
          >
            <input
              ref={hiddenFileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(e) => appendFiles(e.target.files || [])}
            />

            <div style={{ textAlign: "center", maxWidth: 420 }}>
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
              </div>

              <div style={{ fontWeight: 950, fontSize: 32, letterSpacing: "-0.06em" }}>
                {t("dragAndDropFiles")}
              </div>

              <div className="muted-text" style={{ marginTop: 10, fontSize: 16 }}>
                {t("or")}
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
                disabled={uploading}
              >
                {t("browse")}
              </button>

              <div className="muted-text" style={{ marginTop: 18, lineHeight: 1.6 }}>
                {t("uploadSupportText")}
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
                paddingRight: 6,
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
                    <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
                      {formatFileSize(item.file.size)}
                      {getStatusText(item)}
                    </div>
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
                    ) : item.status === "uploading" ? (
                      <span
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 999,
                          display: "grid",
                          placeItems: "center",
                          color: "var(--muted)",
                          background: "var(--panel-2)",
                          fontWeight: 950,
                        }}
                      >
                        …
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() => removeFile(item.id)}
                        disabled={uploading}
                        style={{ padding: "8px 10px" }}
                      >
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
                  <div style={{ fontWeight: 850 }}>{t("yourUploadListEmpty")}</div>
                  <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                    {t("uploadListEmptyDesc")}
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
                }}
              >
                {uploadLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}