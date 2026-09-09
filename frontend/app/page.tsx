"use client";

/**
 * Bragi landing page.
 *
 * Was a full-bleed autoplaying video hero behind a 62% black scrim, an
 * 82px/950 headline and two glassmorphic pill buttons — a look that shared
 * nothing with the calm clinical product behind it, and whose crimson/teal
 * video was not even in the Bragi palette.
 *
 * Now a quiet, credible entry page in the product's own design language:
 * restrained type, the Bragi violet, a plain statement of what Bragi is, and
 * direct routes into each role. The hero footage is kept, but as a contained,
 * muted panel — a product visual rather than a brand takeover — and it does
 * not play at all under prefers-reduced-motion.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n";
import { IconChevronRight, IconHeart, IconShield, IconUsers } from "@/components/ui/icon";

function BragiMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 56 68"
      width={(size * 56) / 68}
      height={size}
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <path
        d="M6 4h44a2 2 0 0 1 2 2v32c0 16-28 26-28 26S-4 54-4 38V6a2 2 0 0 1 2-2Z"
        transform="translate(4)"
        fill="#82C09A"
      />
      <rect x="14" y="28" width="28" height="6" rx="3" fill="#fff" />
      <rect x="25" y="17" width="6" height="28" rx="3" fill="#fff" />
    </svg>
  );
}

export default function LandingPage() {
  const { language, setLanguage, t } = useLanguage();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [reducedMotion, setReducedMotion] = useState(false);

  // Honour prefers-reduced-motion: a looping background video is exactly the
  // kind of constant movement that setting exists to stop.
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setReducedMotion(query.matches);
      if (query.matches) videoRef.current?.pause();
      else void videoRef.current?.play().catch(() => {});
    };
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  const roles = [
    {
      key: "doctor",
      icon: IconUsers,
      title: t("doctorLogin"),
      description: t("doctorLoginDesc"),
      href: "/login/doctor",
    },
    {
      key: "patient",
      icon: IconHeart,
      title: t("patientLogin"),
      description: t("patientLoginDesc"),
      href: "/login/patient",
    },
    {
      key: "care_partner",
      icon: IconShield,
      title: t("carePartnerLogin"),
      description: t("carePartnerLoginDesc"),
      href: "/login/care_partner",
    },
  ];

  return (
    <main className="portal-page">
      <div className="portal-shell">
        <header className="portal-topbar">
          <span className="portal-brand-pill">
            <BragiMark size={24} />
            bragi
          </span>

          <nav style={{ display: "flex", alignItems: "center", gap: "var(--s4)" }}>
            <Link href="/about" className="portal-top-link">
              {t("navAbout")}
            </Link>
            <button
              type="button"
              className="b-btn b-btn-ghost b-btn-sm"
              onClick={() => setLanguage(language === "en" ? "ro" : "en")}
              aria-label={t("language")}
            >
              {language === "en" ? "RO" : "EN"}
            </button>
            <Link href="/login" className="b-btn b-btn-secondary b-btn-sm">
              {t("enterPortal")}
            </Link>
          </nav>
        </header>

        <div className="portal-hero-grid">
          <div className="portal-hero-copy">
            <span className="portal-badge">
              <span
                aria-hidden="true"
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "var(--r-full)",
                  background: "var(--brand-500)",
                }}
              />
              {t("clinicalWorkspace")}
            </span>

            <h1 className="portal-hero-title">
              {t("videoLandingTitle1")}
              <br />
              {t("videoLandingTitle2")}
            </h1>

            <p className="portal-hero-subtitle">{t("videoLandingSubtitle")}</p>

            <div className="portal-hero-inline-actions">
              <Link href="/login" className="portal-primary-btn">
                {t("enterPortal")}
                <IconChevronRight size={14} />
              </Link>
              <Link href="/emergency" className="portal-secondary-btn">
                {t("emergencyPortalTitle")}
              </Link>
            </div>
          </div>

          {/* Contained product visual. Muted and bordered, so it reads as an
              image of the product rather than the page's whole identity. */}
          <div
            style={{
              position: "relative",
              borderRadius: "var(--r-xl)",
              border: "1px solid var(--border)",
              overflow: "hidden",
              background: "var(--surface-2)",
              aspectRatio: "4 / 3",
              minWidth: 0,
            }}
          >
            <video
              ref={videoRef}
              autoPlay={!reducedMotion}
              loop
              muted
              playsInline
              aria-hidden="true"
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                opacity: 0.5,
                display: "block",
              }}
            >
              <source src="/hero.mp4" type="video/mp4" />
            </video>

            {/* A soft violet veil pulls the footage back toward the Bragi
                palette instead of letting its own colours lead. */}
            <div
              aria-hidden="true"
              style={{
                position: "absolute",
                inset: 0,
                background:
                  "color-mix(in srgb, var(--brand-500) 16%, color-mix(in srgb, var(--surface) 62%, transparent))",
              }}
            />
          </div>
        </div>

        {/* Direct role entry, so the first click is "who am I", not "log in". */}
        <section style={{ marginTop: "var(--s8)" }}>
          <h2 className="b-label" style={{ marginBottom: "var(--s3)" }}>
            {t("navSignInAs")}
          </h2>

          <div className="portal-card-rail" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            {roles.map((role) => {
              const Icon = role.icon;
              return (
                <Link key={role.key} href={role.href} className="portal-role-card">
                  <span className="portal-art-initial" aria-hidden="true">
                    <Icon size={15} />
                  </span>
                  <span className="portal-role-body">
                    <span className="portal-role-title">{role.title}</span>
                    <span className="portal-role-description">{role.description}</span>
                  </span>
                  <IconChevronRight size={15} className="portal-role-arrow" />
                </Link>
              );
            })}
          </div>
        </section>

        <footer
          style={{
            marginTop: "var(--s9)",
            paddingTop: "var(--s4)",
            borderTop: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--s4)",
            flexWrap: "wrap",
          }}
        >
          <span className="b-meta">Bragi Health · {t("clinicalWorkspace")}</span>
          <span style={{ display: "flex", gap: "var(--s4)" }}>
            <Link href="/about" className="portal-top-link">
              {t("navAbout")}
            </Link>
            <Link href="/emergency" className="portal-top-link">
              {t("emergencyPortalTitle")}
            </Link>
          </span>
        </footer>
      </div>
    </main>
  );
}
