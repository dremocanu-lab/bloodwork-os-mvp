"use client";

import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
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
        padding: "40px 24px",
      }}
    >
      <div style={{ maxWidth: 480, width: "100%", textAlign: "center" }}>
        <BragiLogo height={72} showText={false} />

        <div
          className="muted-text"
          style={{
            fontSize: 10,
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            marginTop: 20,
            marginBottom: 10,
          }}
        >
          Bragi Health
        </div>

        <h1
          style={{
            fontSize: 30,
            fontWeight: 900,
            letterSpacing: "-0.03em",
            lineHeight: 1.15,
            margin: "0 0 14px 0",
          }}
        >
          {t("emergencyPortalTitle")}
        </h1>

        <p
          className="muted-text"
          style={{
            fontSize: 15,
            lineHeight: 1.65,
            maxWidth: 380,
            margin: "0 auto 36px",
          }}
        >
          {t("emergencyPortalSubtitle")}
        </p>

        <Link
          href="/emergency/login"
          className="primary-btn"
          style={{
            display: "inline-block",
            padding: "14px 36px",
            fontSize: 15,
            fontWeight: 700,
            textDecoration: "none",
          }}
        >
          {t("emergencyEnterPortal")}
        </Link>

        <p
          className="muted-text"
          style={{ fontSize: 12, marginTop: 18, lineHeight: 1.6 }}
        >
          {t("emergencyAuditNotice")}
        </p>

        {/* Safety notice */}
        <div
          style={{
            marginTop: 40,
            padding: "16px 20px",
            background: "rgba(220,38,38,0.06)",
            border: "1px solid rgba(220,38,38,0.18)",
            borderRadius: 12,
            textAlign: "left",
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "0.07em",
              color: "#dc2626",
              marginBottom: 8,
            }}
          >
            {t("emergencyReadOnly")} · {t("emergencyAuditedAccess")}
          </div>
          <p className="muted-text" style={{ fontSize: 12, lineHeight: 1.65, margin: 0 }}>
            No editing, no bulk browsing, no admin functions.
            Every search, session start, and page view is logged automatically.
            Access is valid for 30 minutes per patient and is patient-specific.
          </p>
        </div>
      </div>
    </main>
  );
}
