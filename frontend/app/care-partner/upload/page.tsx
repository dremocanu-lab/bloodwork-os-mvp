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
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type Dependant = {
  patient_id: number;
  full_name: string;
  date_of_birth?: string | null;
  sex?: string | null;
  linked_at: string;
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
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: 999,
        border: "2px solid var(--border)",
        borderTopColor: "var(--primary)",
        animation: "spin 0.8s linear infinite",
      }}
    />
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

const SECTIONS = [
  "bloodwork",
  "discharge_summary",
  "medications",
  "scans",
  "hospitalizations",
  "other",
] as const;

export default function CarePartnerUploadPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const { enqueueUploads, visibleTasks, refreshUploadJobs } = useUploadManager();
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const uploadRows: UploadRow[] = useMemo(() => {
    const localRows: UploadRow[] = items.map((item) => ({
      id: item.id,
      filename: item.file.name,
      size: item.file.size,
      status: "selected",
      progress: 0,
      message: "",
      local: true,
    }));

    const taskRows: UploadRow[] = visibleTasks
      .filter((task) => task.patientId === selectedPatientId)
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
  }, [items, visibleTasks, selectedPatientId]);

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");

        if (meResponse.data.role !== "care_partner") {
          router.replace("/login");
          return;
        }

        setCurrentUser(meResponse.data);

        const depResponse = await api.get<Dependant[]>("/my/dependants");
        const deps = depResponse.data || [];
        setDependants(deps);

        if (deps.length > 0) {
          setSelectedPatientId(deps[0].patient_id);
        }

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
    if (hiddenFileInputRef.current) hiddenFileInputRef.current.value = "";
  }

  function removeFile(id: string) {
    setItems((prev) => prev.filter((item) => item.id !== id));
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
    if (event.dataTransfer.files?.length) appendFiles(event.dataTransfer.files);
  }

  function uploadDocuments() {
    if (!items.length) {
      setError(t("chooseAtLeastOneFile"));
      return;
    }
    if (!selectedPatientId) {
      setError(t("selectDependantFirst"));
      return;
    }

    enqueueUploads(
      items.map((item) => item.file),
      { section: uploadSection, patientId: selectedPatientId }
    );

    setItems([]);
    setError("");
  }

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={t("uploadDocuments")}
      subtitle={t("carePartnerUploadDesc")}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/care-partner")}>
          {t("back")}
        </button>
      }
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: "grid", gap: 20 }}>
        {dependants.length === 0 ? (
          <div className="soft-card" style={{ padding: 32, textAlign: "center" }}>
            <div style={{ fontWeight: 900, fontSize: 18, marginBottom: 8 }}>{t("noDependantsYet")}</div>
            <div className="muted-text">{t("noDependantsUploadDesc")}</div>
          </div>
        ) : (
          <>
            {/* Patient selector */}
            <div className="soft-card" style={{ padding: 20 }}>
              <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>
                {t("uploadingFor")}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                  gap: 8,
                }}
              >
                {dependants.map((dep) => (
                  <button
                    key={dep.patient_id}
                    type="button"
                    className={selectedPatientId === dep.patient_id ? "primary-btn" : "secondary-btn"}
                    onClick={() => setSelectedPatientId(dep.patient_id)}
                    style={{ justifyContent: "flex-start" }}
                  >
                    {dep.full_name}
                  </button>
                ))}
              </div>
            </div>

            {/* Section selector */}
            <div className="soft-card" style={{ padding: 20 }}>
              <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>
                {t("documentType")}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                  gap: 8,
                }}
              >
                {SECTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={uploadSection === s ? "primary-btn" : "secondary-btn"}
                    onClick={() => setUploadSection(s)}
                    style={{ justifyContent: "center" }}
                  >
                    {t(s as Parameters<typeof t>[0]) ?? s}
                  </button>
                ))}
              </div>
            </div>

            {/* Drop zone */}
            <div
              className="soft-card"
              style={{ padding: 20 }}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div
                style={{
                  border: `2px dashed ${dragActive ? "var(--primary)" : "var(--border)"}`,
                  borderRadius: 12,
                  padding: "32px 20px",
                  textAlign: "center",
                  background: dragActive
                    ? "color-mix(in srgb, var(--primary) 5%, var(--panel-2))"
                    : "var(--panel-2)",
                  transition: "all 0.15s",
                  cursor: "pointer",
                }}
                onClick={() => hiddenFileInputRef.current?.click()}
              >
                <div style={{ fontWeight: 900, fontSize: 16 }}>{t("dragFilesHere")}</div>
                <div className="muted-text" style={{ marginTop: 6 }}>{t("orBrowse")}</div>
                <input
                  ref={hiddenFileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.doc,.docx"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    if (e.target.files) appendFiles(e.target.files);
                  }}
                />
              </div>
            </div>

            {/* File list */}
            {uploadRows.length > 0 && (
              <div className="soft-card" style={{ padding: 20 }}>
                <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
                    {uploadRows.length} {t("filesSelected")}
                  </div>
                  {items.length > 0 && (
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => { setItems([]); setError(""); }}
                      style={{ padding: "6px 10px", fontSize: 12 }}
                    >
                      {t("clearAll")}
                    </button>
                  )}
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  {uploadRows.map((row) => (
                    <div
                      key={row.id}
                      className="soft-card-tight"
                      style={{
                        padding: "10px 14px",
                        display: "grid",
                        gridTemplateColumns: "28px minmax(0,1fr) auto",
                        gap: 10,
                        alignItems: "center",
                      }}
                    >
                      <UploadRowStatus status={row.status} />
                      <div>
                        <div style={{ fontWeight: 900, fontSize: 13 }}>{row.filename}</div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {formatFileSize(row.size)}
                          {row.message ? ` · ${row.message}` : ""}
                          {row.error ? ` · ${row.error}` : ""}
                        </div>
                      </div>
                      {row.local && (
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => removeFile(row.id)}
                          style={{ padding: "5px 8px", fontSize: 12 }}
                        >
                          ×
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {error && (
              <div
                className="soft-card-tight"
                style={{
                  padding: 14,
                  borderColor: "var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                }}
              >
                {error}
              </div>
            )}

            <button
              type="button"
              className="primary-btn"
              onClick={uploadDocuments}
              disabled={!items.length || !selectedPatientId}
              style={{ justifyContent: "center" }}
            >
              ↑ {t("upload")}
            </button>
          </>
        )}
      </div>
    </AppShell>
  );
}
