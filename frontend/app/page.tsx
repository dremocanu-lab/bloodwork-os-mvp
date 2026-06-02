"use client";

import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import { useLanguage } from "@/lib/i18n";

export default function VideoLandingPage() {
  const { language, setLanguage, t } = useLanguage();

  return (
    <main
      style={{
        position: "relative",
        minHeight: "100dvh",
        overflow: "hidden",
        background: "#000",
        color: "#fff",
      }}
    >
      {/* Video background */}
      <video
        autoPlay
        loop
        muted
        playsInline
        style={{
          position: "fixed",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          zIndex: 0,
        }}
      >
        <source src="/hero.mp4" type="video/mp4" />
      </video>

      {/* Gradient overlay */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          background:
            "linear-gradient(120deg, rgba(0,0,0,0.62) 0%, rgba(0,0,0,0.38) 55%, rgba(0,0,0,0.52) 100%)",
          zIndex: 1,
        }}
      />

      {/* Top bar */}
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "26px 36px",
        }}
      >
        <BragiLogo height={40} showText forceWhite />

        <button
          type="button"
          onClick={() => setLanguage(language === "en" ? "ro" : "en")}
          style={{
            height: 40,
            minWidth: 58,
            padding: "0 16px",
            borderRadius: 999,
            border: "1.5px solid rgba(255,255,255,0.45)",
            background: "rgba(255,255,255,0.1)",
            backdropFilter: "blur(8px)",
            color: "#fff",
            fontWeight: 950,
            fontSize: 13,
            cursor: "pointer",
            letterSpacing: "0.04em",
            transition: "background 200ms ease, border-color 200ms ease, transform 160ms ease",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.18)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(255,255,255,0.7)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.1)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(255,255,255,0.45)";
          }}
        >
          {language === "en" ? "RO" : "EN"}
        </button>
      </div>

      {/* Hero content */}
      <div
        style={{
          position: "relative",
          zIndex: 2,
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "120px clamp(24px, 8vw, 120px) 80px",
          maxWidth: 780,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: "clamp(40px, 6.5vw, 82px)",
            fontWeight: 950,
            letterSpacing: "-0.06em",
            lineHeight: 1.0,
            color: "#fff",
          }}
        >
          {t("videoLandingTitle1")}
          <br />
          {t("videoLandingTitle2")}
        </h1>

        <p
          style={{
            marginTop: 28,
            fontSize: "clamp(15px, 1.8vw, 19px)",
            lineHeight: 1.7,
            color: "rgba(255,255,255,0.72)",
            maxWidth: 520,
          }}
        >
          {t("videoLandingSubtitle")}
        </p>

        <Link
          href="/login"
          style={{
            marginTop: 52,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            alignSelf: "flex-start",
            padding: "16px 40px",
            border: "1.5px solid rgba(255,255,255,0.6)",
            borderRadius: 999,
            background: "rgba(255,255,255,0.08)",
            backdropFilter: "blur(10px)",
            color: "#fff",
            fontWeight: 800,
            fontSize: 15,
            letterSpacing: "-0.01em",
            textDecoration: "none",
            transition: "background 220ms ease, border-color 220ms ease, transform 180ms cubic-bezier(0.22,1,0.36,1), box-shadow 220ms ease",
          }}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLAnchorElement;
            el.style.background = "rgba(255,255,255,0.16)";
            el.style.borderColor = "rgba(255,255,255,0.85)";
            el.style.transform = "translateY(-2px)";
            el.style.boxShadow = "0 12px 32px rgba(0,0,0,0.28)";
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLAnchorElement;
            el.style.background = "rgba(255,255,255,0.08)";
            el.style.borderColor = "rgba(255,255,255,0.6)";
            el.style.transform = "translateY(0)";
            el.style.boxShadow = "none";
          }}
        >
          {t("enterPortal")}
        </Link>
      </div>
    </main>
  );
}
