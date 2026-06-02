"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import BragiLogo from "@/components/bragi-logo";
import ThemeToggle from "@/components/theme-toggle";
import { useLanguage } from "@/lib/i18n";
import { api, getErrorMessage } from "@/lib/api";

type Role = "doctor" | "patient" | "admin";
type Mode = "login" | "signup";

function destination(role: Role) {
  if (role === "patient") return "/my-records";
  if (role === "doctor") return "/my-patients";
  return "/patients/search";
}

export default function RoleAuthPage({ role, mode }: { role: Role; mode: Mode }) {
  const router = useRouter();
  const { t } = useLanguage();

  const roleMeta = {
    doctor: {
      loginTitle: t("doctorLogin"),
      signupTitle: t("doctorSignup"),
      badge: t("clinicalWorkspace"),
      text: t("doctorLoginDesc"),
    },
    patient: {
      loginTitle: t("patientLogin"),
      signupTitle: t("patientSignup"),
      badge: t("personalRecords"),
      text: t("patientLoginDesc"),
    },
    admin: {
      loginTitle: t("adminLogin"),
      signupTitle: t("adminSignup"),
      badge: t("operationsControl"),
      text: t("adminLoginDesc"),
    },
  };

  const meta = roleMeta[role];

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [department, setDepartment] = useState("");
  const [hospitalName, setHospitalName] = useState("");

  const [dateOfBirth, setDateOfBirth] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const title = mode === "login" ? meta.loginTitle : meta.signupTitle;

  async function submit(e: FormEvent) {
    e.preventDefault();

    try {
      setLoading(true);
      setError("");

      if (mode === "login") {
        const response = await api.post("/auth/login", { email, password });

        if (response.data?.user?.role !== role) {
          throw new Error(
            `${t("wrongPortalPrefix")} ${response.data?.user?.role ?? "wrong"} ${t("wrongPortalSuffix")}`
          );
        }

        localStorage.setItem("access_token", response.data.access_token);
        localStorage.setItem("user", JSON.stringify(response.data.user));
        router.push(destination(role));
        return;
      }

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
        payload.sex = sex || null;
        payload.cnp = cnp || null;
        payload.patient_identifier = patientIdentifier || null;
      }

      const response = await api.post("/auth/signup", payload);

      localStorage.setItem("access_token", response.data.access_token);
      localStorage.setItem("user", JSON.stringify(response.data.user));
      router.push(destination(role));
    } catch (err) {
      setError(getErrorMessage(err, `${title} ${t("signupFailed")}`));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="portal-page">
      <div className="auth-shell">
        <div className="portal-topbar">
          <Link href="/" className="portal-brand-pill" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <BragiLogo height={22} showText={false} />
            <span>bragi health</span>
          </Link>

          <Link href="/about" className="portal-top-link">
            {t("aboutUs")}
          </Link>
        </div>

        <div className="auth-grid auth-grid-polished">
          <section className="auth-copy-panel">
            <div className="portal-badge">{meta.badge}</div>

            <h1 className="portal-hero-title auth-copy-title">
              {title}
              <br />
              {t("madeClear")}
            </h1>

            <p className="portal-hero-subtitle">{meta.text}</p>

            <div className={`auth-art-card portal-art-${role}`}>
              <div className="portal-shape shape-a" />
              <div className="portal-shape shape-b" />
              <div className="portal-shape shape-c" />
            </div>
          </section>

          <section className="auth-panel auth-panel-polished">
            <div className="portal-role-pill">{meta.badge}</div>
            <h2 className="auth-title">{title}</h2>
            <p className="auth-subtitle">{meta.text}</p>

            <form onSubmit={submit} className="auth-form">
              {mode === "signup" && (
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
              )}

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

              {mode === "signup" && (role === "doctor" || role === "admin") && (
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

              {mode === "signup" && role === "patient" && (
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
                    <input
                      className="auth-input"
                      value={sex}
                      onChange={(e) => setSex(e.target.value)}
                      placeholder={t("maleFemalePlaceholder")}
                    />
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
                  placeholder={mode === "login" ? t("passwordPlaceholder") : t("createPassword")}
                  required
                />
              </label>

              {error && <div className="auth-error">{error}</div>}

              <button
                className="portal-primary-btn auth-submit-btn"
                type="submit"
                disabled={loading}
              >
                {loading ? t("working") : title}
              </button>
            </form>

            <div className="auth-footer">
              {mode === "login" ? (
                <>
                  {t("needAnAccount")}{" "}
                  <Link href={`/signup/${role}`}>{t("goToSignupPrefix")} {role} {t("goToSignupSuffix")}</Link>
                </>
              ) : (
                <>
                  {t("alreadyHaveAccount")}{" "}
                  <Link href={`/login/${role}`}>{t("goToLoginPrefix")} {role} {t("goToLoginSuffix")}</Link>
                </>
              )}
            </div>

            <div className="auth-footer">
              {t("needAnotherRole")}{" "}
              <Link href={mode === "login" ? "/login" : "/signup"}>
                {t("chooseDifferentPortal")}
              </Link>
            </div>
          </section>
        </div>
      </div>

      <ThemeToggle />
    </main>
  );
}
