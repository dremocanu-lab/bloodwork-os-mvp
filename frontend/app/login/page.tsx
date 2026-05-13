"use client";

import Link from "next/link";
import ThemeToggle from "@/components/theme-toggle";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";

export default function LoginChooserPage() {
  const { t } = useLanguage();

  const portalCards = [
    {
      key: "doctor",
      initial: "D",
      tag: t("clinicalWorkspace"),
      title: t("doctorLogin"),
      description: t("doctorLoginDesc"),
      loginHref: "/login/doctor",
      signupHref: "/signup/doctor",
      artClass: "portal-art-doctor",
    },
    {
      key: "patient",
      initial: "P",
      tag: t("personalRecords"),
      title: t("patientLogin"),
      description: t("patientLoginDesc"),
      loginHref: "/login/patient",
      signupHref: "/signup/patient",
      artClass: "portal-art-patient",
    },
    {
      key: "care_partner",
      initial: "C",
      tag: t("carePartnerPortal"),
      title: t("carePartnerLogin"),
      description: t("carePartnerLoginDesc"),
      loginHref: "/login/care_partner",
      signupHref: "/signup/care_partner",
      artClass: "portal-art-care-partner",
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
            <div className="portal-badge">{t("chooseYourPortal")}</div>

            <h1 className="portal-hero-title">
              {t("signInByRoleLine1")}
              <br />
              {t("signInByRoleLine2")}
              <br />
              {t("signInByRoleLine3")}
            </h1>

            <p className="portal-hero-subtitle">{t("loginChooserSubtitle")}</p>
          </section>

          <section className="portal-card-rail">
            {portalCards.map((card) => (
              <article key={card.key} className="portal-role-card">
                <div className={`portal-role-art ${card.artClass}`}>
                  <div className="portal-art-orb portal-art-orb-lg" />
                  <div className="portal-art-orb portal-art-orb-sm" />
                  <div className="portal-art-orb portal-art-orb-mid" />
                  <div className="portal-art-initial">{card.initial}</div>
                </div>

                <div className="portal-role-body">
                  <div className="portal-role-label">{card.tag}</div>
                  <div className="portal-role-title">{card.title}</div>
                  <div className="portal-role-description">{card.description}</div>
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

        <div
          style={{
            marginTop: 40,
            paddingTop: 24,
            borderTop: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          <span className="muted-text" style={{ fontSize: 13 }}>
            {t("adminPortalLabel")}
          </span>
          <Link href="/login/admin" className="portal-top-link" style={{ fontSize: 13 }}>
            {t("adminSignIn")}
          </Link>
          <span className="muted-text" style={{ fontSize: 13 }}>·</span>
          <Link href="/signup/admin" className="portal-top-link" style={{ fontSize: 13 }}>
            {t("adminSignUp")}
          </Link>
        </div>
      </div>
    </main>
  );
}
