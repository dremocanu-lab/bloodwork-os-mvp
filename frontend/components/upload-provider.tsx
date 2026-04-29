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

export type UploadStatus = "queued" | "uploading" | "processing" | "done" | "error";

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
};

type UploadDestination = {
  section: string;
  patientId?: string | number | null;
  patientName?: string | null;
};

type BackendUploadJob = {
  id: number;
  patient_id: number;
  section: string;
  filename: string;
  content_type?: string | null;
  status: string;
  progress: number;
  message?: string | null;
  error?: string | null;
  document_id?: number | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type UploadManagerContextValue = {
  tasks: UploadTask[];
  visibleTasks: UploadTask[];
  activeCount: number;
  enqueueUploads: (files: File[], destination: UploadDestination) => void;
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
  if (status === "processing") return "processing";
  if (status === "uploading") return "uploading";
  return "queued";
}

function isActive(status: UploadStatus) {
  return status === "queued" || status === "uploading" || status === "processing";
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
            section: job.section,
            patientId: job.patient_id,
            patientName: existingIndex >= 0 ? next[existingIndex].patientName : null,
            status,
            progress: job.progress ?? 0,
            message: job.message || "Upload job updated.",
            createdAt: job.created_at,
            finishedAt,
            error: job.error || undefined,
            documentId: job.document_id || null,
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
      clearFinishedUploads,
      refreshUploadJobs,
    }),
    [tasks, visibleTasks, activeCount, enqueueUploads, clearFinishedUploads, refreshUploadJobs]
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