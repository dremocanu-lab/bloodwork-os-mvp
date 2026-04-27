"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

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

type UploadStatus = "queued" | "uploading" | "done" | "error";

type UploadItem = {
  id: string;
  file: File;
  status: UploadStatus;
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
  if (name.endsWith(".tif") || name.endsWith(".tiff")) return "TIFF";

  return "FILE";
}

export default function DoctorPatientUploadPage() {
  const params = useParams();
  const router = useRouter();
  const { language } = useLanguage();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        title: "Încarcă documente",
        subtitle: "Încarcă analize, scanări sau documente clinice pentru pacient.",
        back: "Înapoi la fișă",
        documentType: "Tip document",
        documentTypeDesc: "Alege unde va fi organizat documentul în fișa pacientului.",
        bloodwork: "Analize",
        scans: "Scanări",
        medications: "Medicație",
        hospitalizations: "Spitalizări",
        other: "Altele",
        selectedFiles: "Fișiere selectate",
        selected: "selectate",
        uploaded: "încărcate",
        failed: "eșuate",
        noFilesSelectedYet: "Niciun fișier selectat încă",
        dragAndDropFiles: "Trage fișierele aici",
        or: "sau",
        browse: "Alege fișiere",
        uploadSupportText: "PDF-uri, imagini și documente scanate. Analizele vor fi structurate automat când este posibil.",
        clear: "Șterge",
        upload: "Încarcă",
        uploading: "Se încarcă",
        fileUploading: "se încarcă",
        fileUploaded: "încărcat",
        fileFailed: "eșuat",
        uploadFailed: "Încărcarea a eșuat.",
        someFilesFailed: "Unele fișiere nu s-au încărcat.",
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
      scans: "Scans",
      medications: "Medications",
      hospitalizations: "Hospitalizations",
      other: "Other",
      selectedFiles: "Selected files",
      selected: "selected",
      uploaded: "uploaded",
      failed: "failed",
      noFilesSelectedYet: "No files selected yet",
      dragAndDropFiles: "Drag and drop files",
      or: "or",
      browse: "Browse",
      uploadSupportText: "PDFs, images, and scanned reports. Bloodwork will be structured automatically when possible.",
      clear: "Clear",
      upload: "Upload",
      uploading: "Uploading",
      fileUploading: "uploading",
      fileUploaded: "uploaded",
      fileFailed: "failed",
      uploadFailed: "Upload failed.",
      someFilesFailed: "Some files failed to upload.",
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
      { value: "scans", label: labels.scans },
      { value: "medications", label: labels.medications },
      { value: "hospitalizations", label: labels.hospitalizations },
      { value: "other", label: labels.other },
    ],
    [labels]
  );

  const selectedCount = items.length;
  const uploadedCount = items.filter((item) => item.status === "done").length;
  const failedCount = items.filter((item) => item.status === "error").length;
  const canUpload = selectedCount > 0 && !uploading;

  const selectedSummary = useMemo(() => {
    if (!selectedCount) return labels.noFilesSelectedYet;

    const failedText = failedCount ? ` · ${failedCount} ${labels.failed}` : "";
    return `${selectedCount} ${labels.selected} · ${uploadedCount} ${labels.uploaded}${failedText}`;
  }, [selectedCount, uploadedCount, failedCount, labels]);

  const uploadLabel = useMemo(() => {
    if (uploading) return `${labels.uploading} ${uploadedCount}/${selectedCount}...`;
    if (!selectedCount) return labels.upload;
    return `${labels.upload} ${selectedCount}`;
  }, [uploading, uploadedCount, selectedCount, labels]);

  async function fetchData() {
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
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, labels.failedLoad));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

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
      setError(labels.chooseAtLeastOneFile);
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
          formData.append("patient_id", String(patientId));
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
                    error: getErrorMessage(err, labels.uploadFailed),
                  }
                : current
            )
          );
        }
      }

      if (!hadError) {
        setTimeout(() => {
          router.push(`/patients/${patientId}`);
        }, 700);
      } else {
        setError(labels.someFilesFailed);
      }
    } finally {
      setUploading(false);
    }
  }

  function getStatusText(item: UploadItem) {
    if (item.status === "uploading") return ` · ${labels.fileUploading}`;
    if (item.status === "done") return ` · ${labels.fileUploaded}`;
    if (item.status === "error") return ` · ${item.error || labels.fileFailed}`;
    return "";
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
      subtitle={`${profile.patient.full_name} · CNP ${valueOrDash(profile.patient.cnp)} · ID ${valueOrDash(
        profile.patient.patient_identifier
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)} disabled={uploading}>
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
            <div className="muted-text" style={{ marginTop: 6 }}>
              {labels.documentTypeDesc}
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
                ? "linear-gradient(135deg, color-mix(in srgb, var(--primary) 14%, var(--panel)), var(--panel))"
                : "var(--panel)",
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
                {labels.dragAndDropFiles}
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
                disabled={uploading}
              >
                {labels.browse}
              </button>

              <div className="muted-text" style={{ marginTop: 18, lineHeight: 1.6 }}>
                {labels.uploadSupportText}
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
                {labels.selectedFiles}
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
                          background: "var(--panel-2)",
                        }}
                      >
                        <Spinner size={16} />
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
              <button type="button" className="secondary-btn" onClick={clearFiles} disabled={uploading || !items.length}>
                {labels.clear}
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
                  gap: 10,
                  alignItems: "center",
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