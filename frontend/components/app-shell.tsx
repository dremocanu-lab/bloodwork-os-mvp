"use client";

import { ReactNode, useEffect, useState } from "react";
import Sidebar from "@/components/sidebar";
import { useLanguage } from "@/lib/i18n";

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

            {rightContent && (
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
              </div>
            )}
          </div>
        </div>

        <div style={{ minWidth: 0 }}>{children}</div>
      </main>
    </div>
  );
}