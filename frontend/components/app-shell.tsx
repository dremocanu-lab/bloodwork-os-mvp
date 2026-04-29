"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import Sidebar from "@/components/sidebar";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { useUploadManager, UploadTask } from "@/components/upload-provider";

type ShellUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type AppShellProps = {
  user: ShellUser;
  title: string;
  subtitle?: string;
  children: ReactNode;
  rightContent?: ReactNode;
};

type AccessRequest = {
  id: number;
  doctor_user_id: number;
  doctor_name?: string | null;
  doctor_email?: string | null;
  doctor_department?: string | null;
  doctor_hospital_name?: string | null;
  status: string;
  requested_at: string;
  responded_at?: string | null;
};

function useViewportFlags() {
  const [width, setWidth] = useState<number>(1440);

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    onResize();

    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return {
    isMobile: width < 900,
    isTablet: width >= 900 && width < 1200,
    isDesktop: width >= 1200,
  };
}

function formatTaskStatus(task: UploadTask) {
  if (task.status === "done") return "Done";
  if (task.status === "error") return "Failed";
  if (task.status === "processing") return "Processing";
  if (task.status === "uploading") return "Uploading";
  return "Queued";
}

function NotificationBell({ user }: { user: ShellUser }) {
  const { tasks, activeCount, clearFinishedUploads } = useUploadManager();
  const [open, setOpen] = useState(false);
  const [accessRequests, setAccessRequests] = useState<AccessRequest[]>([]);

  const pendingRequests = useMemo(
    () => accessRequests.filter((request) => request.status === "pending"),
    [accessRequests]
  );

  async function fetchAccessRequests() {
    if (user.role !== "patient") return;

    try {
      const response = await api.get<AccessRequest[]>("/my/access-requests");
      setAccessRequests(response.data);
    } catch {
      setAccessRequests([]);
    }
  }

  useEffect(() => {
    fetchAccessRequests();

    if (user.role !== "patient") return;

    const interval = window.setInterval(fetchAccessRequests, 30_000);
    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id, user.role]);

  const recentTasks = tasks.slice(0, 8);
  const badgeCount = activeCount + pendingRequests.length + tasks.filter((task) => task.status === "done" || task.status === "error").length;

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        className="secondary-btn"
        onClick={() => setOpen((current) => !current)}
        style={{
          width: 42,
          height: 42,
          padding: 0,
          borderRadius: 999,
          position: "relative",
          display: "grid",
          placeItems: "center",
          fontSize: 18,
        }}
        aria-label="Notifications"
      >
        🔔

        {badgeCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: -4,
              right: -4,
              minWidth: 19,
              height: 19,
              padding: "0 5px",
              borderRadius: 999,
              display: "grid",
              placeItems: "center",
              background: "var(--danger-bg)",
              color: "var(--danger-text)",
              border: "1px solid var(--danger-border)",
              fontSize: 11,
              fontWeight: 950,
              lineHeight: 1,
            }}
          >
            {badgeCount > 9 ? "9+" : badgeCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="soft-card"
          style={{
            position: "absolute",
            top: 50,
            right: 0,
            zIndex: 60,
            width: 360,
            maxWidth: "calc(100vw - 32px)",
            padding: 14,
            boxShadow: "0 24px 80px rgba(0,0,0,0.18)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div style={{ fontWeight: 950, letterSpacing: "-0.03em" }}>Notifications</div>

            {tasks.some((task) => task.status === "done" || task.status === "error") && (
              <button
                type="button"
                className="secondary-btn"
                onClick={clearFinishedUploads}
                style={{ padding: "7px 10px", fontSize: 12 }}
              >
                Clear done
              </button>
            )}
          </div>

          <div style={{ display: "grid", gap: 10, maxHeight: 380, overflowY: "auto" }}>
            {pendingRequests.map((request) => (
              <div
                key={`access-${request.id}`}
                className="soft-card-tight"
                style={{
                  padding: 12,
                  background: "var(--panel-2)",
                }}
              >
                <div style={{ fontWeight: 850, lineHeight: 1.35 }}>
                  Dr. {request.doctor_name || "A doctor"} requested access to your profile.
                </div>
                <div className="muted-text" style={{ marginTop: 5, fontSize: 12, lineHeight: 1.45 }}>
                  {request.doctor_department || "Department not set"} ·{" "}
                  {request.doctor_hospital_name || "Hospital not set"}
                </div>
              </div>
            ))}

            {recentTasks.map((task) => (
              <div
                key={task.id}
                className="soft-card-tight"
                style={{
                  padding: 12,
                  borderColor:
                    task.status === "error"
                      ? "var(--danger-border)"
                      : task.status === "done"
                      ? "var(--success-border)"
                      : "var(--border)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 850,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {task.filename}
                    </div>
                    <div className="muted-text" style={{ marginTop: 5, fontSize: 12, lineHeight: 1.45 }}>
                      {task.message}
                    </div>
                  </div>

                  <span
                    style={{
                      flex: "0 0 auto",
                      fontSize: 11,
                      fontWeight: 900,
                      borderRadius: 999,
                      padding: "5px 8px",
                      background:
                        task.status === "error"
                          ? "var(--danger-bg)"
                          : task.status === "done"
                          ? "var(--success-bg)"
                          : "var(--panel-2)",
                      color:
                        task.status === "error"
                          ? "var(--danger-text)"
                          : task.status === "done"
                          ? "var(--success-text)"
                          : "var(--muted)",
                      border: "1px solid var(--border)",
                      height: 26,
                    }}
                  >
                    {formatTaskStatus(task)}
                  </span>
                </div>

                {(task.status === "uploading" || task.status === "processing") && (
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
                        width: `${task.status === "processing" ? Math.max(task.progress, 74) : task.progress}%`,
                        borderRadius: 999,
                        background: "var(--primary)",
                        transition: "width 180ms ease",
                      }}
                    />
                  </div>
                )}

                {task.error && (
                  <div
                    style={{
                      marginTop: 8,
                      color: "var(--danger-text)",
                      fontSize: 12,
                      lineHeight: 1.45,
                    }}
                  >
                    {task.error}
                  </div>
                )}
              </div>
            ))}

            {!pendingRequests.length && !recentTasks.length && (
              <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 850 }}>No notifications yet</div>
                <div className="muted-text" style={{ marginTop: 5, fontSize: 12, lineHeight: 1.5 }}>
                  Upload progress and access requests will appear here.
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AppShell({ user, title, subtitle, children, rightContent }: AppShellProps) {
  const { isMobile } = useViewportFlags();
  const { t } = useLanguage();
  const [mobileOpen, setMobileOpen] = useState(false);

  function getWorkspaceLabel() {
    if (user.role === "doctor") return t("doctorWorkspace");
    if (user.role === "admin") return t("adminWorkspace");
    return t("patientPortal");
  }

  useEffect(() => {
    if (!isMobile) {
      setMobileOpen(false);
    }
  }, [isMobile]);

  return (
    <div className="app-shell-root">
      <Sidebar user={user} mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

      <main className="app-shell-main">
        {isMobile && (
          <div
            className="soft-card app-mobile-topbar"
            style={{
              position: "sticky",
              top: 12,
              zIndex: 20,
              marginBottom: 14,
            }}
          >
            <button type="button" className="secondary-btn" onClick={() => setMobileOpen(true)}>
              {t("menu")}
            </button>

            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontWeight: 950,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                }}
              >
                Bloodwork OS
              </div>
              <div className="muted-text" style={{ fontSize: 12, marginTop: 3 }}>
                {getWorkspaceLabel()}
              </div>
            </div>

            <div style={{ marginLeft: "auto" }}>
              <NotificationBell user={user} />
            </div>
          </div>
        )}

        <div className="soft-card app-shell-header">
          <div
            className="app-shell-header-row"
            style={{
              alignItems: "flex-start",
              gap: 16,
            }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="app-shell-title">{title}</div>
              {subtitle ? <div className="muted-text app-shell-subtitle">{subtitle}</div> : null}
            </div>

            <div
              className="app-shell-header-actions"
              style={{
                display: "flex",
                gap: 10,
                flexWrap: "wrap",
                justifyContent: "flex-end",
                alignItems: "center",
              }}
            >
              {rightContent}
              <NotificationBell user={user} />
            </div>
          </div>
        </div>

        <div style={{ minWidth: 0 }}>{children}</div>
      </main>
    </div>
  );
}