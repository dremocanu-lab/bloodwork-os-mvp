"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import LanguageToggle from "@/components/language-toggle";
import { useLanguage } from "@/lib/i18n";
import { api, getErrorMessage } from "@/lib/api";
import { EMERGENCY_STORAGE_KEYS } from "@/lib/emergency-api";

export default function EmergencySignupPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [organization, setOrganization] = useState("");
  const [department, setDepartment] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const res = await api.post("/auth/signup", {
        full_name: fullName,
        email,
        password,
        role: "emergency_worker",
        hospital_name: organization || null,
        department: department || null,
      });

      const { access_token, user } = res.data as {
        access_token: string;
        user: { id: number; email: string; full_name: string; role: string };
      };

      // Log them straight in — store emergency token and redirect to search
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.token, access_token);
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.user, JSON.stringify(user));
      router.push("/emergency/search");
    } catch (err) {
      setError(getErrorMessage(err, "Sign up failed. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--app-bg)",
        padding: "40px 24px",
      }}
    >
      <div style={{ position: "fixed", top: 18, right: 18, zIndex: 50 }}>
        <LanguageToggle />
      </div>
      <div style={{ maxWidth: 420, width: "100%" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <Link href="/emergency" style={{ display: "inline-block" }}>
            <BragiLogo height={48} showText={false} />
          </Link>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 900,
              letterSpacing: "-0.02em",
              margin: "16px 0 6px",
            }}
          >
            {t("emergencySignup")}
          </h1>
          <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.55 }}>
            {t("emergencySignupSubtitle")}
          </p>
        </div>

        {/* Form */}
        <div className="soft-card" style={{ padding: "28px 28px" }}>
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Field label="Full name">
              <input
                type="text"
                className="text-input"
                placeholder="Jane Smith"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            <Field label="Email">
              <input
                type="email"
                className="text-input"
                placeholder="worker@organization.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            <Field label={t("emergencySignupOrg")}>
              <input
                type="text"
                className="text-input"
                placeholder={t("emergencySignupOrgPlaceholder")}
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            <Field label={t("emergencySignupDept")}>
              <input
                type="text"
                className="text-input"
                placeholder={t("emergencySignupDeptPlaceholder")}
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            <Field label="Password">
              <input
                type="password"
                className="text-input"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            <Field label="Confirm password">
              <input
                type="password"
                className="text-input"
                placeholder="••••••••"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </Field>

            {error && (
              <div
                style={{
                  padding: "10px 14px",
                  background: "var(--danger-bg)",
                  border: "1px solid var(--danger-border)",
                  borderRadius: 8,
                  fontSize: 13,
                  color: "var(--danger-text)",
                  lineHeight: 1.5,
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              className="primary-btn"
              disabled={loading}
              style={{ fontSize: 15, padding: "12px", marginTop: 4 }}
            >
              {loading ? "Creating account…" : t("emergencySignup")}
            </button>
          </form>
        </div>

        {/* Footer links */}
        <div style={{ marginTop: 18, textAlign: "center" }}>
          <span className="muted-text" style={{ fontSize: 13 }}>
            {t("emergencyAlreadyHaveAccount")}{" "}
          </span>
          <Link
            href="/emergency/login"
            style={{ fontSize: 13, fontWeight: 700, color: "var(--primary)" }}
          >
            {t("emergencySignIn")}
          </Link>
        </div>

        {/* Audit notice */}
        <div
          style={{
            marginTop: 20,
            padding: "12px 16px",
            background: "rgba(220,38,38,0.06)",
            border: "1px solid rgba(220,38,38,0.15)",
            borderRadius: 10,
            fontSize: 12,
            lineHeight: 1.6,
          }}
        >
          <span style={{ fontWeight: 700, color: "#dc2626" }}>{t("emergencyReadOnly")}.</span>{" "}
          <span className="muted-text">{t("emergencyAuditNotice")}</span>
        </div>
      </div>
    </main>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        style={{
          display: "block",
          fontSize: 11,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--muted)",
          marginBottom: 6,
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}
