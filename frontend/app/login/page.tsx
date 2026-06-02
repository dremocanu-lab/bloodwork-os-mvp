"use client";

import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
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
          <Link href="/" className="portal-brand-pill" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <BragiLogo height={22} showText={false} />
            <span>bragi health</span>
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
          className="soft-card-tight"
          style={{
            marginTop: 40,
            padding: "22px 28px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 24,
            flexWrap: "wrap",
            background: "color-mix(in srgb, var(--primary) 5%, var(--panel))",
            borderColor: "color-mix(in srgb, var(--primary) 18%, transparent)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: "color-mix(in srgb, var(--primary) 14%, var(--panel-2))",
                border: "1px solid color-mix(in srgb, var(--primary) 25%, transparent)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 22,
                flexShrink: 0,
              }}
            >
              🛡️
            </div>

            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 900,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--primary)",
                  marginBottom: 3,
                }}
              >
                Hospital Administration
              </div>
              <div style={{ fontWeight: 950, fontSize: 15, letterSpacing: "-0.02em", lineHeight: 1.2 }}>
                {t("adminBannerTitle")}
              </div>
              <div className="muted-text" style={{ marginTop: 4, fontSize: 13, lineHeight: 1.4 }}>
                {t("adminBannerDesc")}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexShrink: 0, flexWrap: "wrap" }}>
            <Link
              href="/login/admin"
              className="primary-btn"
              style={{ textDecoration: "none", whiteSpace: "nowrap" }}
            >
              {t("adminSignIn")}
            </Link>
            <Link
              href="/signup/admin"
              className="secondary-btn"
              style={{ textDecoration: "none", whiteSpace: "nowrap" }}
            >
              {t("adminSignUp")}
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
