"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import ThemeToggle from "@/components/theme-toggle";
import { useLanguage } from "@/lib/i18n";

type SidebarUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type SidebarProps = {
  user: SidebarUser;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
};

function getHomeHref(user: SidebarUser) {
  if (user.role === "patient") return "/my-records";
  if (user.role === "doctor") return "/my-patients";
  return "/assignments";
}

export default function Sidebar({ user, mobileOpen = false, onCloseMobile }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { language, setLanguage, t } = useLanguage();

  const navByRole: Record<SidebarUser["role"], { label: string; href: string }[]> = {
    doctor: [
      { label: t("myCurrentPatients"), href: "/my-patients" },
      { label: t("searchPatients"), href: "/patients/search" },
    ],
    patient: [{ label: t("myRecords"), href: "/my-records" }],
    admin: [
      { label: t("assignments"), href: "/assignments" },
      { label: t("searchPatients"), href: "/patients/search" },
      { label: t("activityLog"), href: "/admin/logs" },
    ],
  };

  const navItems = navByRole[user.role];

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    router.push("/login");
  }

  function getWorkspaceLabel() {
    if (user.role === "doctor") {
      return `${user.department || t("department")} · ${user.hospital_name || t("hospital")}`;
    }

    if (user.role === "admin") {
      return `${user.department || t("department")} ${t("admin")} · ${user.hospital_name || t("hospital")}`;
    }

    return t("patientPortal");
  }

  function getRoleLabel() {
    if (user.role === "doctor") return t("doctorWorkspace");
    if (user.role === "admin") return t("adminWorkspace");
    return t("patientPortal");
  }

  return (
    <>
      <aside
        className={`app-sidebar ${mobileOpen ? "mobile-open" : ""}`}
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100dvh",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "grid",
            gap: 16,
            overflowY: "auto",
            paddingBottom: 16,
          }}
        >
          <div className="app-sidebar-brand">
            <Link
              href={getHomeHref(user)}
              onClick={onCloseMobile}
              style={{
                display: "inline-flex",
                textDecoration: "none",
                color: "inherit",
              }}
            >
              <div style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.06em", lineHeight: 1 }}>
                {t("brand")}
              </div>
            </Link>

            <div className="muted-text" style={{ marginTop: 8, fontSize: 13 }}>
              {t("clinicalWorkspace")}
            </div>
          </div>

          <div className="soft-card-tight" style={{ padding: 16 }}>
            <div
              style={{
                display: "inline-flex",
                width: "fit-content",
                padding: "5px 9px",
                borderRadius: 999,
                background: "var(--panel-2)",
                color: "var(--muted)",
                fontSize: 12,
                fontWeight: 900,
                marginBottom: 10,
              }}
            >
              {getRoleLabel()}
            </div>

            <div style={{ fontWeight: 900, lineHeight: 1.25 }}>{user.full_name}</div>

            <div
              className="muted-text"
              style={{
                marginTop: 5,
                fontSize: 13,
                overflowWrap: "anywhere",
                lineHeight: 1.35,
              }}
            >
              {user.email}
            </div>

            <div className="muted-text" style={{ marginTop: 9, fontSize: 13, lineHeight: 1.45 }}>
              {getWorkspaceLabel()}
            </div>
          </div>

          <div
            className="soft-card-tight"
            style={{
              padding: 14,
              display: "grid",
              gap: 12,
            }}
          >
            <div>
              <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>
                {t("language")}
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 8,
                }}
              >
                <button
                  type="button"
                  className={language === "en" ? "primary-btn" : "secondary-btn"}
                  onClick={() => setLanguage("en")}
                  style={{ justifyContent: "center" }}
                >
                  EN
                </button>

                <button
                  type="button"
                  className={language === "ro" ? "primary-btn" : "secondary-btn"}
                  onClick={() => setLanguage("ro")}
                  style={{ justifyContent: "center" }}
                >
                  RO
                </button>
              </div>
            </div>

            <div>
              <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginBottom: 8 }}>
                {t("theme")}
              </div>

              <ThemeToggle compact />
            </div>

            <button type="button" className="secondary-btn" onClick={logout}>
              {t("logout")}
            </button>
          </div>

          <nav style={{ display: "grid", gap: 10 }}>
            {navItems.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onCloseMobile}
                  className={active ? "primary-btn" : "secondary-btn"}
                  style={{
                    justifyContent: "flex-start",
                    textDecoration: "none",
                    width: "100%",
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </aside>

      <button
        type="button"
        className={`sidebar-overlay ${mobileOpen ? "open" : ""}`}
        onClick={onCloseMobile}
        aria-label="Close sidebar"
      />
    </>
  );
}
