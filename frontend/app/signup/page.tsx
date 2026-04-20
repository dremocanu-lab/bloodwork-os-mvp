"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getErrorMessage } from "@/lib/api";

type SignupResponse = {
  access_token: string;
  token_type: string;
  user: {
    id: number;
    email: string;
    full_name: string;
    role: "patient" | "doctor" | "admin";
    department?: string | null;
    hospital_name?: string | null;
  };
};

const DEPARTMENTS = [
  "Endocrinology",
  "General Surgery",
  "Internal Medicine",
  "Family Medicine",
  "Cardiology",
  "Orthopedics",
  "Emergency Medicine",
  "Neurology",
  "Pediatrics",
  "Obstetrics and Gynecology",
  "Oncology",
  "Radiology",
  "ICU",
];

const SEX_OPTIONS = ["Male", "Female"];

function computeAge(dateOfBirth: string) {
  if (!dateOfBirth) return "";
  const dob = new Date(dateOfBirth);
  if (Number.isNaN(dob.getTime())) return "";
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const m = today.getMonth() - dob.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < dob.getDate())) {
    age -= 1;
  }
  return age >= 0 ? String(age) : "";
}

export default function SignupPage() {
  const router = useRouter();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"patient" | "doctor" | "admin">("doctor");

  const [dateOfBirth, setDateOfBirth] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");

  const [department, setDepartment] = useState("");
  const [hospitalName, setHospitalName] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const age = useMemo(() => computeAge(dateOfBirth), [dateOfBirth]);
  const isDoctor = role === "doctor";
  const isPatient = role === "patient";

  const handleSignup = async () => {
    setError("");
    setLoading(true);

    try {
      const response = await api.post<SignupResponse>("/auth/signup", {
        full_name: fullName,
        email,
        password,
        role,
        date_of_birth: dateOfBirth || null,
        age: age || null,
        sex: sex || null,
        cnp: isPatient ? cnp || null : null,
        patient_identifier: isPatient ? patientIdentifier || null : null,
        department: isDoctor ? department || null : null,
        hospital_name: isDoctor ? hospitalName || null : null,
      });

      localStorage.setItem("access_token", response.data.access_token);
      router.push("/");
    } catch (err: any) {
      setError(getErrorMessage(err, "Signup failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-white p-8 text-black">
      <div className="mx-auto max-w-3xl rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="mb-2 text-3xl font-bold">Create account</h1>
        <p className="mb-6 text-sm text-gray-600">
          Build a user for your Bloodwork OS MVP.
        </p>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium">Full name</label>
            <input
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Email</label>
            <input
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              type="email"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Password</label>
            <input
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              type="password"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Role</label>
            <select
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={role}
              onChange={(e) =>
                setRole(e.target.value as "patient" | "doctor" | "admin")
              }
            >
              <option value="doctor">Doctor</option>
              <option value="admin">Admin</option>
              <option value="patient">Patient</option>
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Date of birth</label>
            <input
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              type="date"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Age</label>
            <input
              className="w-full rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm"
              value={age}
              readOnly
              placeholder="Auto-calculated"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Sex</label>
            <select
              className="w-full rounded-xl border border-gray-300 p-3 text-sm"
              value={sex}
              onChange={(e) => setSex(e.target.value)}
            >
              <option value="">Select sex</option>
              {SEX_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          {isDoctor && (
            <>
              <div>
                <label className="mb-2 block text-sm font-medium">Department</label>
                <select
                  className="w-full rounded-xl border border-gray-300 p-3 text-sm"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                >
                  <option value="">Select department</option>
                  {DEPARTMENTS.map((dept) => (
                    <option key={dept} value={dept}>
                      {dept}
                    </option>
                  ))}
                </select>
              </div>

              <div className="md:col-span-2">
                <label className="mb-2 block text-sm font-medium">Hospital</label>
                <input
                  className="w-full rounded-xl border border-gray-300 p-3 text-sm"
                  value={hospitalName}
                  onChange={(e) => setHospitalName(e.target.value)}
                  placeholder="Hospital / clinic name"
                />
              </div>
            </>
          )}

          {isPatient && (
            <>
              <div>
                <label className="mb-2 block text-sm font-medium">CNP</label>
                <input
                  className="w-full rounded-xl border border-gray-300 p-3 text-sm"
                  value={cnp}
                  onChange={(e) => setCnp(e.target.value)}
                  placeholder="CNP"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium">Patient Identifier</label>
                <input
                  className="w-full rounded-xl border border-gray-300 p-3 text-sm"
                  value={patientIdentifier}
                  onChange={(e) => setPatientIdentifier(e.target.value)}
                  placeholder="Hospital ID / patient ID"
                />
              </div>
            </>
          )}
        </div>

        <div className="mt-6 space-y-4">
          <button
            onClick={handleSignup}
            disabled={
              loading ||
              !fullName ||
              !email ||
              !password ||
              !role ||
              (isDoctor && (!department || !hospitalName))
            }
            className="w-full rounded-xl bg-black px-4 py-3 text-white disabled:opacity-50"
          >
            {loading ? "Creating account..." : "Signup"}
          </button>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            onClick={() => router.push("/login")}
            className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm"
          >
            Go to Login
          </button>
        </div>
      </div>
    </main>
  );
}