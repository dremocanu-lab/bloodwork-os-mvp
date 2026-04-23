"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import { getErrorMessage } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";
const THEME_KEY = "bloodwork-theme";

type SignupResponse = {
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

function calculateAgeFromDob(value: string) {
  if (!value) return "";
  const dob = new Date(value);
  if (Number.isNaN(dob.getTime())) return "";

  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const monthDiff = today.getMonth() - dob.getMonth();

  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) {
    age -= 1;
  }

  return String(age);
}

export default function SignupPage() {
  const router = useRouter();

  const [darkMode, setDarkMode] = useState(false);
  const [mounted, setMounted] = useState(false);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"patient" | "doctor" | "admin">("doctor");

  const [dateOfBirth, setDateOfBirth] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");
  const [department, setDepartment] = useState("");
  const [hospitalName, setHospitalName] = useState("");

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

  useEffect(() => {
    setAge(calculateAgeFromDob(dateOfBirth));
  }, [dateOfBirth]);

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

  const handleSignup = async () => {
    setError("");
    setLoading(true);

    try {
      const response = await axios.post<SignupResponse>(`${API_URL}/auth/signup`, {
        full_name: fullName,
        email,
        password,
        role,
        date_of_birth: dateOfBirth || null,
        age: age || null,
        sex: sex || null,
        cnp: cnp || null,
        patient_identifier: patientIdentifier || null,
        department: role === "doctor" ? department || null : null,
        hospital_name: role === "doctor" ? hospitalName || null : null,
      });

      localStorage.setItem("access_token", response.data.access_token);
      router.push("/");
    } catch (err) {
      setError(getErrorMessage(err, "Signup failed."));
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
              Create your workspace
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
              One account. One clean clinical record system.
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
              Set up a patient, doctor, or admin account and start using organized charts,
              bloodwork views, notes, and clinical workflows immediately.
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
            ["Patient access", "Patients can view their own chart and uploaded records."],
            ["Doctor workflow", "Doctors can review results, write notes, and manage care."],
            ["Admin control", "Admins can connect doctors and patients cleanly."],
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
            maxWidth: 620,
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
              <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-0.04em" }}>Signup</div>
              <div style={{ color: theme.muted, marginTop: 8 }}>
                Create a new Bloodwork OS account.
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

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 16,
            }}
          >
            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Full Name
              </label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Full name"
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
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Email
              </label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                placeholder="name@example.com"
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
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Password
              </label>
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                type="password"
                placeholder="Password"
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
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Role
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "patient" | "doctor" | "admin")}
                style={{
                  width: "100%",
                  borderRadius: 18,
                  border: `1px solid ${theme.inputBorder}`,
                  background: theme.inputBg,
                  color: theme.text,
                  padding: "15px 16px",
                  outline: "none",
                }}
              >
                <option value="doctor">Doctor</option>
                <option value="admin">Admin</option>
                <option value="patient">Patient</option>
              </select>
            </div>

            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Date of Birth
              </label>
              <input
                value={dateOfBirth}
                onChange={(e) => setDateOfBirth(e.target.value)}
                type="date"
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
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Age
              </label>
              <input
                value={age}
                readOnly
                placeholder="Auto-calculated"
                style={{
                  width: "100%",
                  borderRadius: 18,
                  border: `1px solid ${theme.inputBorder}`,
                  background: theme.secondaryBg,
                  color: theme.text,
                  padding: "15px 16px",
                  outline: "none",
                }}
              />
            </div>

            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Sex
              </label>
              <select
                value={sex}
                onChange={(e) => setSex(e.target.value)}
                style={{
                  width: "100%",
                  borderRadius: 18,
                  border: `1px solid ${theme.inputBorder}`,
                  background: theme.inputBg,
                  color: theme.text,
                  padding: "15px 16px",
                  outline: "none",
                }}
              >
                <option value="">Select sex</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
              </select>
            </div>

            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                CNP
              </label>
              <input
                value={cnp}
                onChange={(e) => setCnp(e.target.value)}
                placeholder="Optional"
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

            <div style={{ gridColumn: "1 / -1" }}>
              <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                Patient Identifier
              </label>
              <input
                value={patientIdentifier}
                onChange={(e) => setPatientIdentifier(e.target.value)}
                placeholder="Optional patient ID / PID"
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

            {role === "doctor" && (
              <>
                <div>
                  <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                    Department
                  </label>
                  <input
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    placeholder="Endocrinology, General Surgery..."
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
                  <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 700 }}>
                    Hospital
                  </label>
                  <input
                    value={hospitalName}
                    onChange={(e) => setHospitalName(e.target.value)}
                    placeholder="Hospital name"
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
              </>
            )}
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
                marginTop: 18,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: "grid", gap: 12, marginTop: 20 }}>
            <button
              onClick={handleSignup}
              disabled={
                loading ||
                !fullName ||
                !email ||
                !password ||
                !role ||
                (role === "doctor" && (!department || !hospitalName))
              }
              style={{
                width: "100%",
                border: "none",
                borderRadius: 18,
                background: theme.accent,
                color: "white",
                padding: "15px 18px",
                fontWeight: 800,
                cursor: "pointer",
                opacity:
                  loading ||
                  !fullName ||
                  !email ||
                  !password ||
                  !role ||
                  (role === "doctor" && (!department || !hospitalName))
                    ? 0.65
                    : 1,
              }}
            >
              {loading ? "Creating account..." : "Create Account"}
            </button>

            <button
              onClick={() => router.push("/login")}
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
              Go to Login
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}