"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";

const THEME_KEY = "bloodwork-theme";

type PortalCard = {
  label: string;
  title: string;
  subtitle: string;
  accentClass: string;
  loginHref: string;
  signupHref: string;
};

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

const portalCards: Record<"doctor" | "patient" | "admin", PortalCard> = {
  doctor: {
    label: "Clinical Workspace",
    title: "Doctor Portal",
    subtitle: "Review labs, notes, trends, charts, and care updates in one clean workspace.",
    accentClass: "auth-portal-accent-doctor",
    loginHref: "/login/doctor",
    signupHref: "/signup/doctor",
  },
  patient: {
    label: "Personal Records",
    title: "Patient Portal",
    subtitle: "View records, uploads, notes, and doctor-shared updates in one secure place.",
    accentClass: "auth-portal-accent-patient",
    loginHref: "/login/patient",
    signupHref: "/signup/patient",
  },
  admin: {
    label: "Operations Control",
    title: "Admin Portal",
    subtitle: "Manage users, assignments, access, and oversight across the platform.",
    accentClass: "auth-portal-accent-admin",
    loginHref: "/login/admin",
    signupHref: "/signup/admin",
  },
};

function getStoredTheme() {
  if (typeof window === "undefined") return "light";
  return localStorage.getItem(THEME_KEY) || "light";
}

export default function AuthShell({
  title,
  subtitle,
  badge = "Clinical record workspace",
  role,
  children,
  showFormCard = true,
  formTitle,
  formSubtitle,
  rightTopAction,
}: AuthShellProps) {
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

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
              <span>Bloodwork OS</span>
            </Link>

            <Link href="/about" className="auth-top-link">
              About Us
            </Link>
          </div>

          <div className="auth-badge">{badge}</div>

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
                      Login
                    </Link>
                    <Link href={card.signupHref} className="auth-portal-action-secondary">
                      Sign Up
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
          <div className="auth-theme-title">Appearance</div>
          <div className="auth-theme-caption">
            {theme === "dark" ? "Dark mode enabled" : "Light mode enabled"}
          </div>
        </div>

        <button
          type="button"
          className={theme === "dark" ? "auth-theme-toggle dark" : "auth-theme-toggle"}
          onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          aria-label="Toggle light and dark mode"
        >
          <span className="auth-theme-knob" />
        </button>
      </div>
    </main>
  );
}