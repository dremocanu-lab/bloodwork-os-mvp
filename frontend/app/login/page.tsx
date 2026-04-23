"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import { getErrorMessage } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";
const THEME_KEY = "bloodwork-theme";

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: {
    id: number;
    email: string;
    full_name: string;
    role: "patient" | "doctor" | "admin";
  };
};

function getInitialTheme() {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(THEME_KEY) === "dark";
}

export default function LoginPage() {
  const router = useRouter();

  const [darkMode, setDarkMode] = useState(false);
  const [mounted, setMounted] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const isDark = getInitialTheme();
    setDarkMode(isDark);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    document.documentElement.classList.toggle("dark", darkMode);
    document.body.classList.toggle("dark", darkMode);
    localStorage.setItem(THEME_KEY, darkMode ? "dark" : "light");
  }, [darkMode, mounted]);

  const theme = useMemo(
    () => ({
      background: darkMode
        ? "linear-gradient(180deg, #07111f 0%, #0b1628 100%)"
        : "linear-gradient(180deg, #f7f9fd 0%, #eef3fb 100%)",
      panel: darkMode ? "rgba(14, 24, 43, 0.94)" : "rgba(255, 255, 255, 0.94)",
      panelBorder: darkMode ? "rgba(120, 143, 180, 0.18)" : "#dbe4f0",
      panelShadow: darkMode
        ? "0 24px 70px rgba(0, 0, 0, 0.35)"
        : "0 24px 70px rgba(37, 52, 83, 0.10)",
      text: darkMode ? "#f7fbff" : "#0f172a",
      muted: darkMode ? "#8fa2bf" : "#64748b",
      inputBg: darkMode ? "#0d1a2f" : "#ffffff",
      inputBorder: darkMode ? "#223553" : "#d7e1ee",
      accent: "#6d5dfc",
      accentSoft: darkMode ? "rgba(109, 93, 252, 0.18)" : "#f1efff",
      secondaryBg: darkMode ? "#101d34" : "#f8fbff",
      secondaryBorder: darkMode ? "#223553" : "#d7e1ee",
      dangerBg: darkMode ? "rgba(127, 29, 29, 0.20)" : "#fef2f2",
      dangerBorder: darkMode ? "rgba(248, 113, 113, 0.20)" : "#fecaca",
      dangerText: darkMode ? "#fecaca" : "#b91c1c",
    }),
    [darkMode]
  );

  const handleLogin = async () => {
    setError("");
    setLoading(true);

    try {
      const response = await axios.post<LoginResponse>(`${API_URL}/auth/login`, {
        email,
        password,
      });

      localStorage.setItem("access_token", response.data.access_token);
      router.push("/");
    } catch (err) {
      setError(getErrorMessage(err, "Login failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        background: theme.background,
        color: theme.text,
        display: "grid",
        gridTemplateColumns: "1.05fr 0.95fr",
      }}
    >
      <section
        style={{
          padding: "48px 56px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background:
            darkMode
              ? "radial-gradient(circle at top left, rgba(109, 93, 252, 0.18), transparent 28%)"
              : "radial-gradient(circle at top left, rgba(109, 93, 252, 0.10), transparent 28%)",
        }}
      >
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 12,
              padding: "12px 18px",
              borderRadius: 999,
              background: theme.panel,
              border: `1px solid ${theme.panelBorder}`,
              boxShadow: theme.panelShadow,
            }}
          >
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: theme.accent,
                boxShadow: "0 0 18px rgba(109, 93, 252, 0.55)",
              }}
            />
            <div style={{ fontWeight: 800, letterSpacing: "-0.03em", fontSize: 20 }}>
              Bloodwork OS
            </div>
          </div>

          <div style={{ marginTop: 64, maxWidth: 560 }}>
            <div
              style={{
                display: "inline-flex",
                padding: "7px 12px",
                borderRadius: 999,
                background: theme.accentSoft,
                color: theme.accent,
                fontWeight: 700,
                fontSize: 13,
                marginBottom: 18,
              }}
            >
              Clinical record workspace
            </div>

            <h1
              style={{
                margin: 0,
                fontSize: 56,
                lineHeight: 1.02,
                letterSpacing: "-0.05em",
                fontWeight: 900,
              }}
            >
              Modern patient records, built for real clinical work.
            </h1>

            <p
              style={{
                marginTop: 20,
                fontSize: 18,
                lineHeight: 1.7,
                color: theme.muted,
                maxWidth: 520,
              }}
            >
              Sign in to access patient charts, structured bloodwork, clinical notes,
              hospitalizations, and physician workflow tools in one clean workspace.
            </p>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gap: 14,
            maxWidth: 720,
          }}
        >
          {[
            ["Structured labs", "Organized bloodwork with readable clinical detail."],
            ["Notes & events", "Follow patient care with notes and hospitalization history."],
            ["Doctor workflow", "Access requests, verification, and patient management."],
          ].map(([title, text]) => (
            <div
              key={title}
              style={{
                background: theme.panel,
                border: `1px solid ${theme.panelBorder}`,
                borderRadius: 24,
                padding: 18,
                boxShadow: theme.panelShadow,
              }}
            >
              <div style={{ fontWeight: 800, marginBottom: 8 }}>{title}</div>
              <div style={{ fontSize: 14, color: theme.muted, lineHeight: 1.6 }}>{text}</div>
            </div>
          ))}
        </div>
      </section>

      <section
        style={{
          padding: "40px 36px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 520,
            background: theme.panel,
            border: `1px solid ${theme.panelBorder}`,
            borderRadius: 32,
            padding: 32,
            boxShadow: theme.panelShadow,
            backdropFilter: "blur(14px)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              marginBottom: 24,
            }}
          >
            <div>
              <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-0.04em" }}>Login</div>
              <div style={{ color: theme.muted, marginTop: 8 }}>
                Sign in to your Bloodwork OS account.
              </div>
            </div>

            <button
              type="button"
              onClick={() => setDarkMode((prev) => !prev)}
              style={{
                border: `1px solid ${theme.secondaryBorder}`,
                background: theme.secondaryBg,
                color: theme.text,
                borderRadius: 999,
                padding: "10px 14px",
                cursor: "pointer",
                fontWeight: 700,
              }}
            >
              {darkMode ? "Dark" : "Light"}
            </button>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            <div>
              <label
                style={{
                  display: "block",
                  marginBottom: 8,
                  fontSize: 14,
                  fontWeight: 700,
                }}
              >
                Email
              </label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                type="email"
                style={{
                  width: "100%",
                  borderRadius: 18,
                  border: `1px solid ${theme.inputBorder}`,
                  background: theme.inputBg,
                  color: theme.text,
                  padding: "15px 16px",
                  outline: "none",
                }}
              />
            </div>

            <div>
              <label
                style={{
                  display: "block",
                  marginBottom: 8,
                  fontSize: 14,
                  fontWeight: 700,
                }}
              >
                Password
              </label>
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                type="password"
                style={{
                  width: "100%",
                  borderRadius: 18,
                  border: `1px solid ${theme.inputBorder}`,
                  background: theme.inputBg,
                  color: theme.text,
                  padding: "15px 16px",
                  outline: "none",
                }}
              />
            </div>

            {error && (
              <div
                style={{
                  borderRadius: 18,
                  padding: 14,
                  background: theme.dangerBg,
                  border: `1px solid ${theme.dangerBorder}`,
                  color: theme.dangerText,
                  fontSize: 14,
                  fontWeight: 600,
                }}
              >
                {error}
              </div>
            )}

            <button
              onClick={handleLogin}
              disabled={loading || !email || !password}
              style={{
                width: "100%",
                border: "none",
                borderRadius: 18,
                background: theme.accent,
                color: "white",
                padding: "15px 18px",
                fontWeight: 800,
                cursor: loading || !email || !password ? "not-allowed" : "pointer",
                opacity: loading || !email || !password ? 0.65 : 1,
              }}
            >
              {loading ? "Signing in..." : "Login"}
            </button>

            <button
              onClick={() => router.push("/signup")}
              style={{
                width: "100%",
                borderRadius: 18,
                border: `1px solid ${theme.secondaryBorder}`,
                background: theme.secondaryBg,
                color: theme.text,
                padding: "15px 18px",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Go to Signup
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}