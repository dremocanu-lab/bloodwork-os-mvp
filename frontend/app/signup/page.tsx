"use client";

import Link from "next/link";
import ThemeToggle from "@/components/theme-toggle";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";

export default function SignupChooserPage() {
  const { t } = useLanguage();

  const portalCards = [
    {
      key: "doctor",
      tag: t("clinicalWorkspace"),
      title: t("doctorSignup"),
      description: t("doctorSignupDesc"),
      loginHref: "/login/doctor",
      signupHref: "/signup/doctor",
      artClass: "portal-art-doctor",
    },
    {
      key: "patient",
      tag: t("personalRecords"),
      title: t("patientSignup"),
      description: t("patientSignupDesc"),
      loginHref: "/login/patient",
      signupHref: "/signup/patient",
      artClass: "portal-art-patient",
    },
    {
      key: "admin",
      tag: t("operationsControl"),
      title: t("adminSignup"),
      description: t("adminSignupDesc"),
      loginHref: "/login/admin",
      signupHref: "/signup/admin",
      artClass: "portal-art-admin",
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
            <div className="portal-badge">{t("createYourAccount")}</div>

            <h1 className="portal-hero-title">
              {t("signUpByRoleLine1")}
              <br />
              {t("signUpByRoleLine2")}
              <br />
              {t("signUpByRoleLine3")}
            </h1>

            <p className="portal-hero-subtitle">{t("signupChooserSubtitle")}</p>
          </section>

          <section className="portal-card-rail">
            {portalCards.map((card) => (
              <article key={card.key} className="portal-role-card">
                <div className="portal-role-card-top">
                  <span className="portal-role-pill">{card.tag}</span>
                  <span className="portal-role-arrow">↗</span>
                </div>

                <div className="portal-role-title">{card.title}</div>
                <div className="portal-role-description">{card.description}</div>

                <div className={`portal-role-art ${card.artClass}`}>
                  <div className="portal-shape shape-a" />
                  <div className="portal-shape shape-b" />
                  <div className="portal-shape shape-c" />
                </div>

                <div className="portal-role-actions">
                  <Link href={card.signupHref} className="portal-primary-btn">
                    {t("signUp")}
                  </Link>

                  <Link href={card.loginHref} className="portal-secondary-btn">
                    {t("login")}
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