"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import ThemeToggle from "@/components/theme-toggle";
import LanguageToggle from "@/components/language-toggle";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type Role = "doctor" | "patient" | "admin";

function isRole(value: string): value is Role {
  return value === "doctor" || value === "patient" || value === "admin";
}

function getPostLoginPath(role: Role) {
  if (role === "patient") return "/my-records";
  if (role === "doctor") return "/my-patients";
  return "/assignments";
}

export default function RoleLoginPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();

  const rawRole = params.role;
  const role = Array.isArray(rawRole) ? rawRole[0] : rawRole;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const meta = useMemo(() => {
    if (!role || !isRole(role)) return null;

    if (role === "doctor") {
      return {
        badge: t("doctorAccess"),
        title: t("doctorLogin"),
        subtitle: t("doctorLoginSubtitle"),
        helper: t("doctorLoginHelper"),
      };
    }

    if (role === "patient") {
      return {
        badge: t("patientAccess"),
        title: t("patientLogin"),
        subtitle: t("patientLoginSubtitle"),
        helper: t("patientLoginHelper"),
      };
    }

    return {
      badge: t("adminAccess"),
      title: t("adminLogin"),
      subtitle: t("adminLoginSubtitle"),
      helper: t("adminLoginHelper"),
    };
  }, [role, t]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!role || !isRole(role)) return;

    try {
      setSubmitting(true);
      setError("");

      const response = await api.post("/auth/login", { email, password });

      if (response.data?.user?.role !== role) {
        throw new Error(
          `${t("wrongPortalPrefix")} ${response.data?.user?.role ?? "wrong"} ${t("wrongPortalSuffix")}`
        );
      }

      localStorage.setItem("access_token", response.data.access_token);
      localStorage.setItem("user", JSON.stringify(response.data.user));

      router.push(getPostLoginPath(role));
    } catch (err) {
      setError(getErrorMessage(err, t("loginFailed")));
    } finally {
      setSubmitting(false);
    }
  }

  if (!role || !isRole(role) || !meta) {
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

        <div className="auth-shell">
          <div className="auth-panel">
            <h1 className="auth-title">{t("portalNotFound")}</h1>
            <p className="auth-subtitle">{t("loginRouteNotFound")}</p>
            <Link href="/login" className="portal-primary-btn auth-submit-btn">
              {t("backToLoginChooser")}
            </Link>
          </div>
        </div>
      </main>
    );
  }

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

      <div className="auth-shell">
        <div className="portal-topbar">
          <Link href="/" className="portal-brand-pill">
            <span className="portal-brand-dot" />
            <span>Bloodwork OS</span>
          </Link>

          <Link href="/about" className="portal-top-link">
            {t("aboutUs")}
          </Link>
        </div>

        <div className="auth-grid">
          <section className="auth-copy-panel">
            <div className="portal-badge">{meta.badge}</div>

            <h1 className="portal-hero-title auth-copy-title">
              {meta.title}
              <br />
              made clear.
            </h1>

            <p className="portal-hero-subtitle">{meta.subtitle}</p>

            <div className="auth-helper-card">
              <div className="portal-role-pill">{t("portalOverview")}</div>
              <div className="auth-helper-text">{meta.helper}</div>
            </div>
          </section>

          <section className="auth-panel">
            <h2 className="auth-title">{meta.title}</h2>
            <p className="auth-subtitle">{meta.subtitle}</p>

            <form onSubmit={handleSubmit} className="auth-form">
              <label className="auth-label">
                <span>{t("email")}</span>
                <input
                  className="auth-input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  required
                />
              </label>

              <label className="auth-label">
                <span>{t("password")}</span>
                <input
                  className="auth-input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("passwordPlaceholder")}
                  required
                />
              </label>

              {error ? <div className="auth-error">{error}</div> : null}

              <button
                type="submit"
                className="portal-primary-btn auth-submit-btn"
                disabled={submitting}
              >
                {submitting ? t("signingIn") : meta.title}
              </button>
            </form>

            <div className="auth-footer">
              {t("needNewAccount")}{" "}
              <Link href={`/signup/${role}`}>
                {t("goToSignupPrefix")} {role} {t("goToSignupSuffix")}
              </Link>
            </div>

            <div className="auth-footer">
              {t("needAnotherRole")}{" "}
              <Link href="/login">{t("chooseDifferentPortal")}</Link>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
