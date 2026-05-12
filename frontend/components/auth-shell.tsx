"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/i18n";

const THEME_KEY = "bloodwork-theme";

type AuthShellProps = {
  title: string;
  subtitle: string;
  badge?: string;
  role: "doctor" | "patient" | "admin";
  children?: ReactNode;
  showFormCard?: boolean;
  formTitle?: string;
  formSubtitle?: string;
  rightTopAction?: ReactNode;
};

function getStoredTheme() {
  if (typeof window === "undefined") return "light";
  return localStorage.getItem(THEME_KEY) || "light";
}

export default function AuthShell({
  title,
  subtitle,
  badge,
  role,
  children,
  showFormCard = true,
  formTitle,
  formSubtitle,
  rightTopAction,
}: AuthShellProps) {
  const { t } = useLanguage();
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  const resolvedBadge = badge ?? t("clinicalRecordWorkspace");

  const portalCards = {
    doctor: {
      label: t("clinicalWorkspace"),
      title: t("doctorPortal"),
      subtitle: t("doctorPortalDesc"),
      accentClass: "auth-portal-accent-doctor",
      loginHref: "/login/doctor",
      signupHref: "/signup/doctor",
    },
    patient: {
      label: t("personalRecords"),
      title: t("patientPortal"),
      subtitle: t("patientPortalDesc"),
      accentClass: "auth-portal-accent-patient",
      loginHref: "/login/patient",
      signupHref: "/signup/patient",
    },
    admin: {
      label: t("operationsControl"),
      title: t("adminPortal"),
      subtitle: t("adminPortalDesc"),
      accentClass: "auth-portal-accent-admin",
      loginHref: "/login/admin",
      signupHref: "/signup/admin",
    },
  };

  useEffect(() => {
    const saved = getStoredTheme();
    const nextTheme = saved === "dark" ? "dark" : "light";
    setTheme(nextTheme);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const isDark = theme === "dark";
    document.documentElement.classList.toggle("dark", isDark);
    document.body.classList.toggle("dark", isDark);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme, mounted]);

  return (
    <main className="auth-page">
      <div className="auth-page-inner">
        <section className="auth-hero">
          <div className="auth-brand-row">
            <Link href="/" className="auth-brand-pill">
              <span className="auth-brand-dot" />
              <span>{t("brand")}</span>
            </Link>

            <Link href="/about" className="auth-top-link">
              {t("aboutUs")}
            </Link>
          </div>

          <div className="auth-badge">{resolvedBadge}</div>

          <h1 className="auth-hero-title">{title}</h1>
          <p className="auth-hero-subtitle">{subtitle}</p>

          <div className="auth-portal-grid">
            {(["doctor", "patient", "admin"] as const).map((key) => {
              const card = portalCards[key];
              const active = role === key;

              return (
                <div
                  key={key}
                  className={`auth-portal-card ${active ? "is-active" : ""}`}
                >
                  <div className="auth-portal-top">
                    <span className="auth-portal-pill">{card.label}</span>
                    <span className="auth-portal-arrow">↗</span>
                  </div>

                  <div className="auth-portal-title">{card.title}</div>
                  <div className="auth-portal-subtitle">{card.subtitle}</div>

                  <div className={`auth-portal-art ${card.accentClass}`}>
                    <div className="auth-art-shape auth-art-shape-a" />
                    <div className="auth-art-shape auth-art-shape-b" />
                    <div className="auth-art-shape auth-art-shape-c" />
                  </div>

                  <div className="auth-portal-actions">
                    <Link
                      href={card.loginHref}
                      className={active ? "auth-portal-action-primary" : "auth-portal-action-secondary"}
                    >
                      {t("login")}
                    </Link>
                    <Link href={card.signupHref} className="auth-portal-action-secondary">
                      {t("signUp")}
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {showFormCard && (
          <section className="auth-form-column">
            <div className="auth-form-card">
              <div className="auth-form-card-top">
                <div>
                  <h2 className="auth-form-title">{formTitle}</h2>
                  {formSubtitle ? <p className="auth-form-subtitle">{formSubtitle}</p> : null}
                </div>

                <div className="auth-form-side-actions">{rightTopAction}</div>
              </div>

              {children}
            </div>
          </section>
        )}
      </div>

      <div className="auth-theme-dock">
        <div>
          <div className="auth-theme-title">{t("appearance")}</div>
          <div className="auth-theme-caption">
            {theme === "dark" ? t("darkModeEnabled") : t("lightModeEnabled")}
          </div>
        </div>

        <button
          type="button"
          className={theme === "dark" ? "auth-theme-toggle dark" : "auth-theme-toggle"}
          onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          aria-label={t("appearance")}
        >
          <span className="auth-theme-knob" />
        </button>
      </div>
    </main>
  );
}
