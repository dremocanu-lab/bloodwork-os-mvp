"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, getErrorMessage } from "@/lib/api";

export type UploadStatus = "queued" | "uploading" | "processing" | "done" | "error" | "needs_confirmation";

export type UploadTask = {
  id: string;
  jobId?: number;
  filename: string;
  size: number;
  section: string;
  patientId?: string | number | null;
  patientName?: string | null;
  status: UploadStatus;
  progress: number;
  message: string;
  createdAt: string;
  finishedAt?: string;
  error?: string;
  documentId?: number | null;
  documentType?: string | null;
  classificationStatus?: string | null;
  classificationConfidence?: number | null;
};

type UploadDestination = {
  section: string;
  patientId?: string | number | null;
  patientName?: string | null;
};

type AutoClassifyDestination = {
  patientId?: string | number | null;
  patientName?: string | null;
};

type BackendUploadJob = {
  id: number;
  patient_id: number;
  section: string | null;
  filename: string;
  content_type?: string | null;
  status: string;
  progress: number;
  message?: string | null;
  error?: string | null;
  document_id?: number | null;
  document_type?: string | null;
  classification_status?: string | null;
  classification_confidence?: number | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type UploadManagerContextValue = {
  tasks: UploadTask[];
  visibleTasks: UploadTask[];
  activeCount: number;
  enqueueUploads: (files: File[], destination: UploadDestination) => void;
  enqueueAutoClassifyUploads: (files: File[], destination: AutoClassifyDestination) => void;
  confirmDocumentType: (jobId: number, documentType: string) => Promise<void>;
  clearFinishedUploads: () => void;
  refreshUploadJobs: () => Promise<void>;
};

const UploadManagerContext = createContext<UploadManagerContextValue | null>(null);

const FINISHED_VISIBLE_MS = 7_000;

function makeLocalTask(file: File, destination: UploadDestination): UploadTask {
  return {
    id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
    filename: file.name,
    size: file.size,
    section: destination.section,
    patientId: destination.patientId,
    patientName: destination.patientName,
    status: "uploading",
    progress: 2,
    message: "Sending file...",
    createdAt: new Date().toISOString(),
  };
}

function statusFromBackend(status: string): UploadStatus {
  if (status === "done") return "done";
  if (status === "error") return "error";
  if (status === "needs_confirmation") return "needs_confirmation";
  if (status === "processing") return "processing";
  if (status === "uploading") return "uploading";
  return "queued";
}

function isActive(status: UploadStatus) {
  return (
    status === "queued" ||
    status === "uploading" ||
    status === "processing" ||
    status === "needs_confirmation"
  );
}

function shouldShowFinished(task: UploadTask) {
  if (isActive(task.status)) return true;
  if (!task.finishedAt) return true;

  const finishedMs = new Date(task.finishedAt).getTime();
  if (Number.isNaN(finishedMs)) return false;

  return Date.now() - finishedMs < FINISHED_VISIBLE_MS;
}

export function UploadManagerProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const completedDispatchRef = useRef<Set<number>>(new Set());

  const updateTask = useCallback((id: string, patch: Partial<UploadTask>) => {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, ...patch } : task)));
  }, []);

  const refreshUploadJobs = useCallback(async () => {
    // Don't poll when there is no session — avoids spurious 401s on login/signup pages.
    if (typeof window === "undefined" || !localStorage.getItem("access_token")) return;

    try {
      const response = await api.get<BackendUploadJob[]>("/upload-jobs");

      setTasks((current) => {
        const next = [...current];

        response.data.forEach((job) => {
          const status = statusFromBackend(job.status);
          const finishedAt = job.finished_at || undefined;

          const incomingIsOldFinished =
            !isActive(status) &&
            finishedAt &&
            Date.now() - new Date(finishedAt).getTime() > FINISHED_VISIBLE_MS;

          const existingIndex = next.findIndex((task) => task.jobId === job.id);

          // Do not re-add old completed/failed jobs forever.
          if (existingIndex < 0 && incomingIsOldFinished) {
            return;
          }

          const normalized: UploadTask = {
            id: existingIndex >= 0 ? next[existingIndex].id : `job-${job.id}`,
            jobId: job.id,
            filename: job.filename,
            size: existingIndex >= 0 ? next[existingIndex].size : 0,
            section: job.section || (existingIndex >= 0 ? next[existingIndex].section : ""),
            patientId: job.patient_id,
            patientName: existingIndex >= 0 ? next[existingIndex].patientName : null,
            status,
            progress: job.progress ?? 0,
            message: job.message || "Upload job updated.",
            createdAt: job.created_at,
            finishedAt,
            error: job.error || undefined,
            documentId: job.document_id || null,
            documentType: job.document_type ?? null,
            classificationStatus: job.classification_status ?? null,
            classificationConfidence: job.classification_confidence ?? null,
          };

          const oldStatus = existingIndex >= 0 ? next[existingIndex].status : undefined;

          if (existingIndex >= 0) {
            next[existingIndex] = {
              ...next[existingIndex],
              ...normalized,
              size: next[existingIndex].size || normalized.size,
              patientName: next[existingIndex].patientName || normalized.patientName,
            };
          } else {
            next.push(normalized);
          }

          if (
            status === "done" &&
            job.document_id &&
            oldStatus !== "done" &&
            !completedDispatchRef.current.has(job.id)
          ) {
            completedDispatchRef.current.add(job.id);

            window.dispatchEvent(
              new CustomEvent("bloodwork-upload-complete", {
                detail: {
                  jobId: job.id,
                  documentId: job.document_id,
                  patientId: job.patient_id,
                },
              })
            );
          }
        });

        return next
          .filter(shouldShowFinished)
          .sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""))
          .slice(0, 30);
      });
    } catch {
      // Silent: logged-out pages or expired tokens should not break the app shell.
    }
  }, []);

  const enqueueUploads = useCallback(
    (files: File[], destination: UploadDestination) => {
      if (!files.length) return;

      files.forEach((file) => {
        const localTask = makeLocalTask(file, destination);
        setTasks((current) => [localTask, ...current]);

        window.setTimeout(async () => {
          try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("section", destination.section);

            if (destination.patientId) {
              formData.append("patient_id", String(destination.patientId));
            }

            const response = await api.post<BackendUploadJob>("/upload/background", formData, {
              headers: { "Content-Type": "multipart/form-data" },
              onUploadProgress: (progressEvent) => {
                if (!progressEvent.total) {
                  updateTask(localTask.id, {
                    status: "uploading",
                    progress: 20,
                    message: "Sending file...",
                  });
                  return;
                }

                const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);

                updateTask(localTask.id, {
                  status: "uploading",
                  progress: Math.min(Math.max(percent, 5), 40),
                  message: `Sending file... ${percent}%`,
                });
              },
            });

            updateTask(localTask.id, {
              jobId: response.data.id,
              status: statusFromBackend(response.data.status),
              progress: response.data.progress || 5,
              message: response.data.message || "Queued for processing.",
              createdAt: response.data.created_at,
              documentId: response.data.document_id || null,
            });

            await refreshUploadJobs();
          } catch (err) {
            updateTask(localTask.id, {
              status: "error",
              progress: 100,
              message: `${file.name} failed to start.`,
              finishedAt: new Date().toISOString(),
              error: getErrorMessage(err, "Upload failed."),
            });
          }
        }, 50);
      });
    },
    [refreshUploadJobs, updateTask]
  );

  const enqueueAutoClassifyUploads = useCallback(
    (files: File[], destination: AutoClassifyDestination) => {
      if (!files.length) return;

      // One combined request ("upload once"), but each file gets its own
      // local task immediately so per-file progress/status never blocks
      // on the others — the backend processes each independently too.
      const localTasks = files.map((file) =>
        makeLocalTask(file, { section: "", patientId: destination.patientId, patientName: destination.patientName })
      );
      setTasks((current) => [...localTasks, ...current]);

      window.setTimeout(async () => {
        try {
          const formData = new FormData();
          files.forEach((file) => formData.append("files", file));

          if (destination.patientId) {
            formData.append("patient_id", String(destination.patientId));
          }

          const response = await api.post<
            Array<BackendUploadJob | { filename: string; status: string; error?: string }>
          >("/upload/batch", formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });

          response.data.forEach((result, index) => {
            const localTask = localTasks[index];
            if (!localTask) return;

            if ("id" in result) {
              updateTask(localTask.id, {
                jobId: result.id,
                status: statusFromBackend(result.status),
                progress: result.progress || 5,
                message: result.message || "Queued for processing.",
                createdAt: result.created_at,
                documentId: result.document_id || null,
                documentType: result.document_type ?? null,
                classificationStatus: result.classification_status ?? null,
                classificationConfidence: result.classification_confidence ?? null,
              });
            } else {
              updateTask(localTask.id, {
                status: "error",
                progress: 100,
                message: `${localTask.filename} failed to start.`,
                finishedAt: new Date().toISOString(),
                error: result.error || "Upload failed.",
              });
            }
          });

          await refreshUploadJobs();
        } catch (err) {
          const message = getErrorMessage(err, "Upload failed.");
          localTasks.forEach((localTask) => {
            updateTask(localTask.id, {
              status: "error",
              progress: 100,
              message: `${localTask.filename} failed to start.`,
              finishedAt: new Date().toISOString(),
              error: message,
            });
          });
        }
      }, 50);
    },
    [refreshUploadJobs, updateTask]
  );

  const confirmDocumentType = useCallback(
    async (jobId: number, documentType: string) => {
      const response = await api.post<BackendUploadJob>(`/upload-jobs/${jobId}/confirm-type`, {
        document_type: documentType,
      });

      setTasks((current) =>
        current.map((task) =>
          task.jobId === jobId
            ? {
                ...task,
                status: statusFromBackend(response.data.status),
                progress: response.data.progress || task.progress,
                message: response.data.message || task.message,
                section: response.data.section || task.section,
                documentType: response.data.document_type ?? task.documentType,
                classificationStatus: response.data.classification_status ?? task.classificationStatus,
              }
            : task
        )
      );

      await refreshUploadJobs();
    },
    [refreshUploadJobs]
  );

  useEffect(() => {
    void refreshUploadJobs();

    const refreshInterval = window.setInterval(() => {
      void refreshUploadJobs();
    }, 2500);

    const cleanupInterval = window.setInterval(() => {
      setTasks((current) => current.filter(shouldShowFinished));
    }, 1000);

    return () => {
      window.clearInterval(refreshInterval);
      window.clearInterval(cleanupInterval);
    };
  }, [refreshUploadJobs]);

  const clearFinishedUploads = useCallback(() => {
    setTasks((current) => current.filter((task) => isActive(task.status)));
  }, []);

  const visibleTasks = useMemo(() => tasks.filter(shouldShowFinished), [tasks]);
  const activeCount = useMemo(() => tasks.filter((task) => isActive(task.status)).length, [tasks]);

  const value = useMemo(
    () => ({
      tasks,
      visibleTasks,
      activeCount,
      enqueueUploads,
      enqueueAutoClassifyUploads,
      confirmDocumentType,
      clearFinishedUploads,
      refreshUploadJobs,
    }),
    [
      tasks,
      visibleTasks,
      activeCount,
      enqueueUploads,
      enqueueAutoClassifyUploads,
      confirmDocumentType,
      clearFinishedUploads,
      refreshUploadJobs,
    ]
  );

  return <UploadManagerContext.Provider value={value}>{children}</UploadManagerContext.Provider>;
}

export function useUploadManager() {
  const context = useContext(UploadManagerContext);

  if (!context) {
    throw new Error("useUploadManager must be used inside UploadManagerProvider");
  }

  return context;
}
