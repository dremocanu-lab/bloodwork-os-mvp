"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import ThemeToggle from "@/components/theme-toggle";
import { api, getErrorMessage } from "@/lib/api";

type Role = "doctor" | "patient" | "admin";
type Mode = "login" | "signup";

const copy = {
  doctor: {
    loginTitle: "Doctor Login",
    signupTitle: "Doctor Signup",
    badge: "Clinical Workspace",
    text: "Review charts, structured bloodwork, notes, uploads, and patient timelines.",
  },
  patient: {
    loginTitle: "Patient Login",
    signupTitle: "Patient Signup",
    badge: "Personal Records",
    text: "Access records, uploads, doctor notes, approvals, and shared updates securely.",
  },
  admin: {
    loginTitle: "Admin Login",
    signupTitle: "Admin Signup",
    badge: "Operations Control",
    text: "Manage assignments, permissions, user roles, and access oversight.",
  },
};

function destination(role: Role) {
  if (role === "patient") return "/my-records";
  if (role === "doctor") return "/my-patients";
  return "/patients/search";
}

export default function RoleAuthPage({ role, mode }: { role: Role; mode: Mode }) {
  const router = useRouter();
  const meta = copy[role];

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
        const response = await api.post("/auth/login", {
          email,
          password,
        });

        if (response.data?.user?.role !== role) {
          throw new Error(
            `This account belongs to the ${response.data?.user?.role ?? "wrong"} portal.`
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
      setError(getErrorMessage(err, `${title} failed.`));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="portal-page">
      <div className="auth-shell">
        <div className="portal-topbar">
          <Link href="/" className="portal-brand-pill">
            <span className="portal-brand-dot" />
            <span>Bloodwork OS</span>
          </Link>

          <Link href="/about" className="portal-top-link">
            About Us
          </Link>
        </div>

        <div className="auth-grid auth-grid-polished">
          <section className="auth-copy-panel">
            <div className="portal-badge">{meta.badge}</div>

            <h1 className="portal-hero-title auth-copy-title">
              {title}
              <br />
              made clear.
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
                  <span>Full Name</span>
                  <input
                    className="auth-input"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Full name"
                    required
                  />
                </label>
              )}

              <label className="auth-label">
                <span>Email</span>
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
                    <span>Department</span>
                    <input
                      className="auth-input"
                      value={department}
                      onChange={(e) => setDepartment(e.target.value)}
                      placeholder="Endocrinology"
                      required
                    />
                  </label>

                  <label className="auth-label">
                    <span>Hospital</span>
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
                    <span>Date of Birth</span>
                    <input
                      className="auth-input"
                      type="date"
                      value={dateOfBirth}
                      onChange={(e) => setDateOfBirth(e.target.value)}
                    />
                  </label>

                  <label className="auth-label">
                    <span>Sex</span>
                    <input
                      className="auth-input"
                      value={sex}
                      onChange={(e) => setSex(e.target.value)}
                      placeholder="Male / Female"
                    />
                  </label>

                  <label className="auth-label">
                    <span>CNP</span>
                    <input
                      className="auth-input"
                      value={cnp}
                      onChange={(e) => setCnp(e.target.value)}
                      placeholder="Optional"
                    />
                  </label>

                  <label className="auth-label">
                    <span>Patient ID</span>
                    <input
                      className="auth-input"
                      value={patientIdentifier}
                      onChange={(e) => setPatientIdentifier(e.target.value)}
                      placeholder="Optional"
                    />
                  </label>
                </>
              )}

              <label className="auth-label">
                <span>Password</span>
                <input
                  className="auth-input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === "login" ? "Password" : "Create password"}
                  required
                />
              </label>

              {error && <div className="auth-error">{error}</div>}

              <button
                className="portal-primary-btn auth-submit-btn"
                type="submit"
                disabled={loading}
              >
                {loading ? "Working..." : title}
              </button>
            </form>

            <div className="auth-footer">
              {mode === "login" ? (
                <>
                  Need an account?{" "}
                  <Link href={`/signup/${role}`}>Go to {role} signup</Link>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <Link href={`/login/${role}`}>Go to {role} login</Link>
                </>
              )}
            </div>

            <div className="auth-footer">
              Need another role?{" "}
              <Link href={mode === "login" ? "/login" : "/signup"}>
                Choose a different portal
              </Link>
            </div>
          </section>
        </div>
      </div>

      <ThemeToggle />
    </main>
  );
}