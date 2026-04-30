"use client";

import Link from "next/link";
import ThemeToggle from "@/components/theme-toggle";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";

export default function AboutPage() {
  const { t } = useLanguage();

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

          <Link href="/" className="portal-top-link">
            {t("home")}
          </Link>
        </div>

        <div className="about-page-card">
          <div className="portal-badge">{t("aboutBloodworkOs")}</div>

          <h1 className="portal-hero-title about-page-title">
            {t("aboutHeroLine1")}
            <br />
            {t("aboutHeroLine2")}
          </h1>

          <p className="portal-hero-subtitle">{t("aboutSubtitle")}</p>

          <div className="about-page-grid">
            <article className="portal-role-card">
              <div className="portal-role-title">{t("forDoctors")}</div>
              <div className="portal-role-description">{t("forDoctorsDesc")}</div>
            </article>

            <article className="portal-role-card">
              <div className="portal-role-title">{t("forPatients")}</div>
              <div className="portal-role-description">{t("forPatientsDesc")}</div>
            </article>

            <article className="portal-role-card">
              <div className="portal-role-title">{t("forAdmins")}</div>
              <div className="portal-role-description">{t("forAdminsDesc")}</div>
            </article>
          </div>
        </div>
      </div>
    </main>
  );
}
