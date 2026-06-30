"use client";

import { ReactNode } from "react";
import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import { useLanguage } from "@/lib/i18n";

type EmergencyShellUser = {
  id: number;
  email: string;
  full_name: string;
  role: string;
};

type EmergencyShellProps = {
  user: EmergencyShellUser | null;
  children: ReactNode;
  onLogout?: () => void;
};

export default function EmergencyShell({ user, children, onLogout }: EmergencyShellProps) {
  const { t } = useLanguage();

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--app-bg)",
      }}
    >
      {/* Top bar */}
      <div
        style={{
          background: "var(--panel)",
          borderBottom: "1px solid var(--border)",
          padding: "10px 24px",
          display: "flex",
          alignItems: "center",
          gap: 14,
          position: "sticky",
          top: 0,
          zIndex: 30,
        }}
      >
        <Link
          href="/emergency"
          style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none", color: "inherit" }}
        >
          <BragiLogo height={30} showText={false} />
          <div style={{ lineHeight: 1.25 }}>
            <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: "-0.01em" }}>
              {t("emergencyPortalTitle")}
            </div>
            <div className="muted-text" style={{ fontSize: 10 }}>Bragi Health</div>
          </div>
        </Link>

        <div style={{ flex: 1 }} />

        {user && (
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="muted-text" style={{ fontSize: 12 }}>{user.full_name}</span>
            {onLogout && (
              <button
                type="button"
                className="secondary-btn"
                style={{ fontSize: 12, padding: "5px 12px" }}
                onClick={onLogout}
              >
                {t("emergencySignOut")}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Emergency status bar */}
      <div
        style={{
          background: "rgba(220,38,38,0.06)",
          borderBottom: "1px solid rgba(220,38,38,0.16)",
          padding: "6px 24px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: "#dc2626",
            display: "inline-block",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 10,
            fontWeight: 900,
            color: "#dc2626",
            textTransform: "uppercase",
            letterSpacing: "0.07em",
          }}
        >
          {t("emergencyAuditedAccess")}
        </span>
        <span className="muted-text" style={{ fontSize: 10 }}>·</span>
        <span className="muted-text" style={{ fontSize: 11 }}>{t("emergencyReadOnly")}</span>
        <span className="muted-text" style={{ fontSize: 10 }}>·</span>
        <span className="muted-text" style={{ fontSize: 11 }}>{t("emergencyTimeLimitedAccess")}</span>
        <span className="muted-text" style={{ fontSize: 10 }}>·</span>
        <span className="muted-text" style={{ fontSize: 11 }}>{t("emergencyUseOnlyForEmergency")}</span>
      </div>

      {/* Content */}
      <div
        style={{
          flex: 1,
          maxWidth: 860,
          width: "100%",
          margin: "0 auto",
          padding: "36px 24px 60px",
        }}
      >
        {children}
      </div>
    </div>
  );
}
