"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import BragiLogo from "@/components/bragi-logo";
import { useLanguage } from "@/lib/i18n";
import { api, getErrorMessage } from "@/lib/api";
import { EMERGENCY_STORAGE_KEYS, getEmergencyUser } from "@/lib/emergency-api";

export default function EmergencyLoginPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Redirect if already logged in as emergency worker
  useEffect(() => {
    const u = getEmergencyUser();
    if (u && (u.role === "emergency_worker" || u.role === "admin")) {
      router.replace("/emergency/search");
    }
  }, [router]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post("/auth/login", { email, password });
      const { access_token, user } = res.data as {
        access_token: string;
        user: { id: number; email: string; full_name: string; role: string };
      };

      if (user.role !== "emergency_worker" && user.role !== "admin") {
        setError(t("emergencyWrongRole"));
        setLoading(false);
        return;
      }

      localStorage.setItem(EMERGENCY_STORAGE_KEYS.token, access_token);
      localStorage.setItem(EMERGENCY_STORAGE_KEYS.user, JSON.stringify(user));
      router.push("/emergency/search");
    } catch (err) {
      setError(getErrorMessage(err, "Login failed. Please check your credentials."));
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
      <div style={{ maxWidth: 400, width: "100%" }}>
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
            {t("emergencyLogin")}
          </h1>
          <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.5 }}>
            {t("emergencyLoginSubtitle")}
          </p>
        </div>

        {/* Login form */}
        <div className="soft-card" style={{ padding: "28px 28px" }}>
          <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <label
                htmlFor="email"
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
                Email
              </label>
              <input
                id="email"
                type="email"
                className="text-input"
                placeholder="worker@organization.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </div>

            <div>
              <label
                htmlFor="password"
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
                Password
              </label>
              <input
                id="password"
                type="password"
                className="text-input"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                style={{ width: "100%", fontSize: 15 }}
              />
            </div>

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
              {loading ? "Signing in…" : t("emergencyEnterPortal")}
            </button>
          </form>
        </div>

        {/* Safety notice */}
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

        <div style={{ marginTop: 18, textAlign: "center" }}>
          <span className="muted-text" style={{ fontSize: 13 }}>
            {t("emergencyNoAccount")}{" "}
          </span>
          <Link
            href="/emergency/signup"
            style={{ fontSize: 13, fontWeight: 700, color: "var(--primary)" }}
          >
            {t("emergencyCreateAccount")}
          </Link>
        </div>

        <div style={{ marginTop: 12, textAlign: "center" }}>
          <Link
            href="/"
            className="muted-text"
            style={{ fontSize: 12, textDecoration: "none" }}
          >
            ← Back to main app
          </Link>
        </div>
      </div>
    </main>
  );
}
