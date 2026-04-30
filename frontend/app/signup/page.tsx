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

function getPostSignupPath(role: Role) {
  if (role === "patient") return "/my-records";
  if (role === "doctor") return "/my-patients";
  return "/assignments";
}

export default function RoleSignupPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();

  const rawRole = params.role;
  const role = Array.isArray(rawRole) ? rawRole[0] : rawRole;

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [department, setDepartment] = useState("");
  const [hospitalName, setHospitalName] = useState("");

  const [dateOfBirth, setDateOfBirth] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const meta = useMemo(() => {
    if (!role || !isRole(role)) return null;

    if (role === "doctor") {
      return {
        badge: t("doctorRegistration"),
        title: t("doctorSignup"),
        subtitle: t("doctorSignupSubtitle"),
        helper: t("doctorSignupHelper"),
      };
    }

    if (role === "patient") {
      return {
        badge: t("patientRegistration"),
        title: t("patientSignup"),
        subtitle: t("patientSignupSubtitle"),
        helper: t("patientSignupHelper"),
      };
    }

    return {
      badge: t("adminRegistration"),
      title: t("adminSignup"),
      subtitle: t("adminSignupSubtitle"),
      helper: t("adminSignupHelper"),
    };
  }, [role, t]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!role || !isRole(role)) return;

    try {
      setSubmitting(true);
      setError("");

      const payload: Record<string, string | null> = {
        full_name: fullName,
        email,
        password,
        role,
      };

      if (role === "doctor" || role === "admin") {
        payload.department = department;
        payload.hospital_name = hospitalName;
      }

      if (role === "patient") {
        payload.date_of_birth = dateOfBirth || null;
        payload.sex = sex;
        payload.cnp = cnp || null;
        payload.patient_identifier = patientIdentifier || null;
      }

      const response = await api.post("/auth/signup", payload);

      localStorage.setItem("access_token", response.data.access_token);
      localStorage.setItem("user", JSON.stringify(response.data.user));

      router.push(getPostSignupPath(role));
    } catch (err) {
      setError(getErrorMessage(err, t("signupFailed")));
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
            <p className="auth-subtitle">{t("signupRouteNotFound")}</p>
            <Link href="/signup" className="portal-primary-btn auth-submit-btn">
              {t("backToSignupChooser")}
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
            <h1 className="portal-hero-title auth-copy-title">{meta.title}</h1>
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
                <span>{t("fullName")}</span>
                <input
                  className="auth-input"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder={t("fullNamePlaceholder")}
                  required
                />
              </label>

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

              {(role === "doctor" || role === "admin") && (
                <>
                  <label className="auth-label">
                    <span>{t("department")}</span>
                    <input
                      className="auth-input"
                      value={department}
                      onChange={(e) => setDepartment(e.target.value)}
                      placeholder="Endocrinology"
                      required
                    />
                  </label>

                  <label className="auth-label">
                    <span>{t("hospital")}</span>
                    <input
                      className="auth-input"
                      value={hospitalName}
                      onChange={(e) => setHospitalName(e.target.value)}
                      placeholder="Fundeni"
                      required
                    />
                  </label>
                </>
              )}

              {role === "patient" && (
                <>
                  <label className="auth-label">
                    <span>{t("dateOfBirth")}</span>
                    <input
                      className="auth-input"
                      type="date"
                      value={dateOfBirth}
                      onChange={(e) => setDateOfBirth(e.target.value)}
                    />
                  </label>

                  <label className="auth-label">
                    <span>{t("sex")}</span>
                    <select
                      className="auth-input"
                      value={sex}
                      onChange={(e) => setSex(e.target.value)}
                      required
                    >
                      <option value="" disabled>
                        Select sex
                      </option>
                      <option value="Male">Male</option>
                      <option value="Female">Female</option>
                    </select>
                  </label>

                  <label className="auth-label">
                    <span>{t("cnp")}</span>
                    <input
                      className="auth-input"
                      value={cnp}
                      onChange={(e) => setCnp(e.target.value)}
                      placeholder={t("optional")}
                    />
                  </label>

                  <label className="auth-label">
                    <span>{t("patientId")}</span>
                    <input
                      className="auth-input"
                      value={patientIdentifier}
                      onChange={(e) => setPatientIdentifier(e.target.value)}
                      placeholder={t("optional")}
                    />
                  </label>
                </>
              )}

              <label className="auth-label">
                <span>{t("password")}</span>
                <input
                  className="auth-input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t("createPassword")}
                  required
                />
              </label>

              {error ? <div className="auth-error">{error}</div> : null}

              <button
                type="submit"
                className="portal-primary-btn auth-submit-btn"
                disabled={submitting}
              >
                {submitting ? t("creatingAccount") : meta.title}
              </button>
            </form>

            <div className="auth-footer">
              {t("alreadyHaveAccount")}{" "}
              <Link href={`/login/${role}`}>
                {t("goToLoginPrefix")} {role} {t("goToLoginSuffix")}
              </Link>
            </div>

            <div className="auth-footer">
              {t("needAnotherRole")} <Link href="/signup">{t("chooseDifferentPortal")}</Link>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}