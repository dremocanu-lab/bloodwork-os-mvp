"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type UserRole = "patient" | "doctor" | "admin";

type SidebarUser = {
  full_name: string;
  email: string;
  role: UserRole;
};

type NavItem = {
  label: string;
  href: string;
  roles: UserRole[];
};

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/", roles: ["doctor", "admin"] },
  { label: "My Patients", href: "/my-patients", roles: ["doctor"] },
  { label: "My Records", href: "/my-records", roles: ["patient"] },
];

export default function Sidebar({ user }: { user: SidebarUser }) {
  const pathname = usePathname();
  const items = navItems.filter((item) => item.roles.includes(user.role));

  return (
    <aside
      style={{
        width: 270,
        position: "fixed",
        top: 0,
        left: 0,
        bottom: 0,
        background: "var(--sidebar)",
        borderRight: "1px solid var(--border)",
        padding: 20,
        display: "flex",
        flexDirection: "column",
        zIndex: 40,
      }}
    >
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 14,
              background: "linear-gradient(135deg, #6d5dfc 0%, #8a7cff 100%)",
              color: "white",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 800,
            }}
          >
            BW
          </div>
          <div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>Bloodwork OS</div>
            <div style={{ fontSize: 13, color: "#6b7280" }}>
              Clinical record workspace
            </div>
          </div>
        </div>
      </div>

      <div style={{ fontSize: 12, fontWeight: 800, color: "#9ca3af", marginBottom: 12 }}>
        WORKSPACE
      </div>

      <nav style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {items.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));

          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "12px 14px",
                borderRadius: 16,
                background: active ? "#f1efff" : "transparent",
                color: active ? "#5b4ee6" : "#374151",
                fontWeight: active ? 700 : 600,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 999,
                  background: active ? "#6d5dfc" : "#d1d5db",
                  display: "inline-block",
                }}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div style={{ marginTop: "auto" }}>
        <div
          className="soft-card-tight"
          style={{
            padding: 16,
            display: "grid",
            gap: 4,
            borderRadius: 18,
          }}
        >
          <div style={{ fontWeight: 700 }}>{user.full_name}</div>
          <div className="muted-text" style={{ fontSize: 13 }}>
            {user.email}
          </div>
          <div
            style={{
              marginTop: 10,
              display: "inline-flex",
              width: "fit-content",
              padding: "6px 10px",
              borderRadius: 999,
              background: "#eef2ff",
              color: "#4f46e5",
              fontSize: 12,
              fontWeight: 700,
              textTransform: "capitalize",
            }}
          >
            {user.role}
          </div>
        </div>
      </div>
    </aside>
  );
}