"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const THEME_KEY = "bloodwork-theme";

type SidebarUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type NavItem = {
  label: string;
  href: string;
};

function getStoredTheme() {
  if (typeof window === "undefined") return "light";
  return localStorage.getItem(THEME_KEY) || "light";
}

export default function Sidebar({ user }: { user: SidebarUser }) {
  const router = useRouter();
  const pathname = usePathname();

  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const saved = getStoredTheme();
    const nextTheme = saved === "dark" ? "dark" : "light";
    setTheme(nextTheme);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const isDark = theme === "dark";
    document.documentElement.classList.toggle("dark", isDark);
    document.body.classList.toggle("dark", isDark);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme, mounted]);

  const navItems = useMemo<NavItem[]>(() => {
    if (user.role === "doctor") {
      return [
        { label: "Dashboard", href: "/" },
        { label: "My Patients", href: "/my-patients" },
      ];
    }

    if (user.role === "patient") {
      return [
        { label: "My Records", href: "/my-records" },
        { label: "Dashboard", href: "/" },
      ];
    }

    return [
      { label: "Dashboard", href: "/" },
    ];
  }, [user.role]);

  return (
    <aside
      style={{
        minHeight: "100vh",
        borderRight: "1px solid var(--border)",
        background: "var(--sidebar-bg)",
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 18,
        position: "sticky",
        top: 0,
      }}
    >
      <div
        className="soft-card-tight"
        style={{
          padding: 18,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 74,
        }}
      >
        <div
          style={{
            fontWeight: 900,
            fontSize: 24,
            letterSpacing: "-0.04em",
            textAlign: "center",
            lineHeight: 1.05,
          }}
        >
          Bloodwork OS
        </div>
      </div>

      <div className="soft-card-tight" style={{ padding: 18 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 800,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "var(--muted)",
            marginBottom: 10,
          }}
        >
          Profile
        </div>

        <div style={{ fontSize: 20, fontWeight: 800, lineHeight: 1.15 }}>
          {user.full_name}
        </div>

        <div className="muted-text" style={{ marginTop: 8 }}>
          {user.email}
        </div>

        <div style={{ marginTop: 12 }}>
          <span
            style={{
              display: "inline-flex",
              padding: "6px 10px",
              borderRadius: 999,
              background: "var(--primary-soft)",
              color: "var(--primary)",
              fontWeight: 800,
              fontSize: 12,
              textTransform: "capitalize",
            }}
          >
            {user.role}
          </span>
        </div>

        {user.role === "doctor" && (
          <div className="muted-text" style={{ marginTop: 12, lineHeight: 1.6 }}>
            {user.department || "—"} <br />
            {user.hospital_name || "—"}
          </div>
        )}
      </div>

      <nav
        className="soft-card-tight"
        style={{
          padding: 12,
          display: "grid",
          gap: 8,
        }}
      >
        {navItems.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname?.startsWith(item.href));

          return (
            <button
              key={item.href}
              type="button"
              onClick={() => router.push(item.href)}
              style={{
                width: "100%",
                border: active ? "1px solid var(--primary)" : "1px solid var(--border)",
                background: active ? "var(--primary-soft)" : "var(--panel)",
                color: active ? "var(--primary)" : "var(--text)",
                borderRadius: 16,
                padding: "14px 16px",
                textAlign: "left",
                fontWeight: 800,
                cursor: "pointer",
              }}
            >
              {item.label}
            </button>
          );
        })}
      </nav>

      <div style={{ flex: 1 }} />

      <div
        className="soft-card-tight"
        style={{
          padding: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontWeight: 800 }}>Appearance</div>
          <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>
            {theme === "dark" ? "Dark mode" : "Light mode"}
          </div>
        </div>

        <button
          type="button"
          onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          style={{
            position: "relative",
            width: 64,
            height: 36,
            borderRadius: 999,
            border: "1px solid var(--border)",
            background: theme === "dark" ? "var(--primary)" : "var(--panel-2)",
            cursor: "pointer",
            transition: "all 180ms ease",
            padding: 0,
          }}
          aria-label="Toggle dark mode"
        >
          <span
            style={{
              position: "absolute",
              top: 4,
              left: theme === "dark" ? 32 : 4,
              width: 26,
              height: 26,
              borderRadius: "50%",
              background: "#ffffff",
              transition: "all 180ms ease",
              boxShadow: "0 4px 10px rgba(0,0,0,0.18)",
            }}
          />
        </button>
      </div>
    </aside>
  );
}