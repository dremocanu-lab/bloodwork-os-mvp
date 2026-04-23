"use client";

import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/sidebar";

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

export default function AppShell({
  user,
  title,
  subtitle,
  children,
  rightContent,
}: AppShellProps) {
  const router = useRouter();

  const logout = () => {
    localStorage.removeItem("access_token");
    router.push("/login");
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--app-bg)",
        color: "var(--text)",
        display: "grid",
        gridTemplateColumns: "280px minmax(0, 1fr)",
      }}
    >
      <Sidebar user={user} />

      <main
        style={{
          minWidth: 0,
          padding: 28,
        }}
      >
        <div
          className="soft-card"
          style={{
            padding: 24,
            marginBottom: 24,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "start",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 34,
                  fontWeight: 900,
                  letterSpacing: "-0.04em",
                  lineHeight: 1.02,
                }}
              >
                {title}
              </div>

              {subtitle ? (
                <div
                  className="muted-text"
                  style={{
                    marginTop: 10,
                    fontSize: 15,
                    lineHeight: 1.6,
                  }}
                >
                  {subtitle}
                </div>
              ) : null}
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                marginLeft: "auto",
              }}
            >
              {rightContent}
              <button className="secondary-btn" onClick={logout}>
                Log out
              </button>
            </div>
          </div>
        </div>

        {children}
      </main>
    </div>
  );
}