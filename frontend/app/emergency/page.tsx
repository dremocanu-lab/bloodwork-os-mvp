"use client";

import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";

export default function EmergencySplashPage() {
  const { t } = useLanguage();

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--app-bg)",
        padding: "60px 32px",
      }}
    >
      <div style={{ position: "fixed", top: 18, right: 18, zIndex: 50 }}>
        <LanguageToggle />
      </div>
      <div style={{ maxWidth: 560, width: "100%", textAlign: "center" }}>
        {/* Logo — centered block */}
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 28 }}>
          <BragiLogo height={96} showText={false} />
        </div>

        <div
          className="muted-text"
          style={{
            fontSize: 12,
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "0.14em",
            marginBottom: 14,
          }}
        >
          Bragi Health
        </div>

        <h1
          style={{
            fontSize: 44,
            fontWeight: 900,
            letterSpacing: "-0.035em",
            lineHeight: 1.1,
            margin: "0 0 18px 0",
          }}
        >
          {t("emergencyPortalTitle")}
        </h1>

        <p
          className="muted-text"
          style={{
            fontSize: 18,
            lineHeight: 1.6,
            maxWidth: 420,
            margin: "0 auto 44px",
          }}
        >
          {t("emergencyPortalSubtitle")}
        </p>

        <Link
          href="/emergency/login"
          className="primary-btn"
          style={{
            display: "inline-block",
            padding: "18px 52px",
            fontSize: 17,
            fontWeight: 700,
            textDecoration: "none",
            borderRadius: 12,
          }}
        >
          {t("emergencyEnterPortal")}
        </Link>

        <p
          className="muted-text"
          style={{ fontSize: 13, marginTop: 22, lineHeight: 1.6 }}
        >
          {t("emergencyAuditNotice")}
        </p>

        {/* Safety notice */}
        <div
          style={{
            marginTop: 52,
            padding: "20px 26px",
            background: "rgba(220,38,38,0.06)",
            border: "1px solid rgba(220,38,38,0.18)",
            borderRadius: 14,
            textAlign: "left",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "0.07em",
              color: "#dc2626",
              marginBottom: 10,
            }}
          >
            {t("emergencyReadOnly")} · {t("emergencyAuditedAccess")}
          </div>
          <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.7, margin: 0 }}>
            No editing, no bulk browsing, no admin functions.
            Every search, session start, and page view is logged automatically.
            Access is valid for 30 minutes per patient and is patient-specific.
          </p>
        </div>
      </div>
    </main>
  );
}
