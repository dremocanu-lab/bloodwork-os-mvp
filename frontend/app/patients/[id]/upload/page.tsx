"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { useUploadManager } from "@/components/upload-provider";

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
  const { enqueueUploads, tasks, refreshUploadJobs } = useUploadManager();
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
          "PDF-uri, imagini și documente scanate. După ce apeși upload, poți continua să folosești site-ul.",
        clear: "Șterge",
        uploadAndContinue: "Încarcă și continuă",
        chooseAtLeastOneFile: "Alege cel puțin un fișier.",
        emptyTitle: "Lista este goală",
        emptyDesc: "Alege sau trage fișiere aici pentru a începe.",
        loadingPage: "Se încarcă pagina de upload...",
        failedLoad: "Nu s-a putut încărca pagina.",
        currentProgress: "Progres uploaduri",
        backgroundNoticeTitle: "Upload în fundal",
        backgroundNotice:
          "Fișierele se procesează în fundal. Progresul apare aici și în clopoțel.",
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
      noFilesSelectedYet: "No files selected yet",
      dragAndDropFiles: "Drag and drop files",
      or: "or",
      browse: "Browse files",
      uploadSupportText:
        "PDFs, images, and scanned reports. After you start the upload, you can keep using the site.",
      clear: "Clear",
      uploadAndContinue: "Upload and continue",
      chooseAtLeastOneFile: "Choose at least one file.",
      emptyTitle: "Your upload list is empty",
      emptyDesc: "Choose or drag files here to begin.",
      loadingPage: "Loading upload page...",
      failedLoad: "Could not load upload page.",
      currentProgress: "Current upload progress",
      backgroundNoticeTitle: "Background uploads",
      backgroundNotice:
        "Files process in the background. Progress appears here and in the notification bell.",
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

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCount = items.length;
  const canUpload = selectedCount > 0;

  const selectedSummary = useMemo(() => {
    if (!selectedCount) return labels.noFilesSelectedYet;
    return `${selectedCount} ${labels.selected}`;
  }, [selectedCount, labels]);

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
    router.push(`/patients/${patientId}`);
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
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)}>
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

      {tasks.length > 0 && (
        <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
          <div className="section-title" style={{ marginBottom: 12 }}>
            {labels.currentProgress}
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {tasks.slice(0, 8).map((task) => (
              <div key={task.id} className="soft-card-tight" style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 850,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {task.filename}
                    </div>
                    <div className="muted-text" style={{ marginTop: 5, fontSize: 12 }}>
                      {task.message}
                    </div>
                  </div>

                  <div style={{ fontWeight: 900, fontSize: 12, color: "var(--muted)" }}>
                    {task.status}
                  </div>
                </div>

                {(task.status === "uploading" || task.status === "processing" || task.status === "queued") && (
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
                        width: `${Math.max(task.progress || 5, 5)}%`,
                        borderRadius: 999,
                        background: "var(--primary)",
                        transition: "width 180ms ease",
                      }}
                    />
                  </div>
                )}

                {task.error && (
                  <div style={{ marginTop: 8, color: "var(--danger-text)", fontSize: 12 }}>
                    {task.error}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
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

      <div
        className="soft-card-tight"
        style={{
          marginBottom: 24,
          padding: 16,
          background: "var(--panel-2)",
          display: "flex",
          gap: 12,
          alignItems: "flex-start",
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 999,
            display: "grid",
            placeItems: "center",
            background: "var(--panel)",
            border: "1px solid var(--border)",
            flex: "0 0 auto",
          }}
        >
          🔔
        </div>

        <div>
          <div style={{ fontWeight: 900 }}>{labels.backgroundNoticeTitle}</div>
          <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.55 }}>
            {labels.backgroundNotice}
          </div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 0, overflow: "hidden", marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) minmax(320px, 0.9fr)", minHeight: 520 }}>
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
              onChange={(event) => appendFiles(event.target.files || [])}
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
                <div style={{ fontSize: 38, lineHeight: 1, color: "var(--primary)", fontWeight: 900 }}>↑</div>
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
              {items.map((item) => (
                <div
                  key={item.id}
                  className="soft-card-tight"
                  style={{ padding: 14, display: "grid", gridTemplateColumns: "54px minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}
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
                    <div style={{ fontWeight: 850, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {item.file.name}
                    </div>
                    <div className="muted-text" style={{ marginTop: 4, fontSize: 12 }}>
                      {formatFileSize(item.file.size)} · {getUploadHint(item.file)}
                    </div>
                  </div>

                  <button type="button" className="secondary-btn" onClick={() => removeFile(item.id)} style={{ padding: "8px 10px" }}>
                    ×
                  </button>
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

            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", borderTop: "1px solid var(--border)", paddingTop: 18 }}>
              <button type="button" className="secondary-btn" onClick={clearFiles} disabled={!items.length}>
                {labels.clear}
              </button>

              <button
                type="button"
                className="primary-btn"
                onClick={uploadDocuments}
                disabled={!canUpload}
                style={{ padding: "13px 18px", borderRadius: 16, fontWeight: 950 }}
              >
                {labels.uploadAndContinue}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}