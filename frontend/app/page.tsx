"use client";

import Link from "next/link";
import ThemeToggle from "@/components/theme-toggle";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";

function PortalArt({ emoji }: { emoji: string }) {
  return (
    <div className="portal-art-new">
      <div className="portal-art-glass-card">
        <div className="portal-art-emoji">{emoji}</div>
        <div className="portal-art-lines">
          <span />
          <span />
          <span />
        </div>
      </div>
      <div className="portal-art-floating portal-art-floating-a" />
      <div className="portal-art-floating portal-art-floating-b" />
    </div>
  );
}

export default function LandingPage() {
  const { t } = useLanguage();

  const portalCards = [
    {
      tag: t("clinicalWorkspace"),
      title: t("doctorPortal"),
      description: t("doctorPortalDesc"),
      loginHref: "/login/doctor",
      signupHref: "/signup/doctor",
      artClass: "portal-art-doctor",
      emoji: "🩺",
    },
    {
      tag: t("personalRecords"),
      title: t("patientPortal"),
      description: t("patientPortalDesc"),
      loginHref: "/login/patient",
      signupHref: "/signup/patient",
      artClass: "portal-art-patient",
      emoji: "📁",
    },
    {
      tag: t("operationsControl"),
      title: t("adminPortal"),
      description: t("adminPortalDesc"),
      loginHref: "/login/admin",
      signupHref: "/signup/admin",
      artClass: "portal-art-admin",
      emoji: "⚙️",
    },
  ];

  return (
    <main className="portal-page">
      <div
        style={{
          position: "fixed",
          top: 18,
          right: 18,
          zIndex: 50,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <LanguageToggle />
        <ThemeToggle compact />
      </div>

      <div className="portal-shell">
        <div className="portal-topbar">
          <Link href="/" className="portal-brand-pill">
            <span className="portal-brand-dot" />
            <span>Bloodwork OS</span>
          </Link>

          <Link href="/about" className="portal-top-link">
            {t("aboutUs")}
          </Link>
        </div>

        <div className="portal-hero-grid">
          <section className="portal-hero-copy">
            <div className="portal-badge">{t("clinicalRecordWorkspace")}</div>

            <h1 className="portal-hero-title">
              {t("landingHeroLine1")}
              <br />
              {t("landingHeroLine2")}
              <br />
              {t("landingHeroLine3")}
            </h1>

            <p className="portal-hero-subtitle">{t("landingHeroSubtitle")}</p>
          </section>

          <section className="portal-card-rail">
            {portalCards.map((card) => (
              <article key={card.title} className="portal-role-card">
                <div className="portal-role-card-top">
                  <span className="portal-role-pill">{card.tag}</span>
                  <span className="portal-role-arrow">↗</span>
                </div>

                <div className="portal-role-title">{card.title}</div>
                <div className="portal-role-description">{card.description}</div>

                <div className={`portal-role-art ${card.artClass}`}>
                  <PortalArt emoji={card.emoji} />
                </div>

                <div className="portal-role-actions">
                  <Link href={card.loginHref} className="portal-primary-btn">
                    {t("login")}
                  </Link>
                  <Link href={card.signupHref} className="portal-secondary-btn">
                    {t("signUp")}
                  </Link>
                </div>
              </article>
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}