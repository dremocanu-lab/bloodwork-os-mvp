"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

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

export default function SignupPage() {
  const router = useRouter();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"patient" | "doctor" | "admin">("doctor");

  const [dateOfBirth, setDateOfBirth] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      });

      localStorage.setItem("access_token", response.data.access_token);
      router.push("/");
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          err?.response?.data?.error ||
          "Signup failed."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-white p-8 text-black">
      <div className="mx-auto max-w-2xl rounded-xl border border-gray-300 bg-white p-6 shadow-sm">
        <h1 className="mb-2 text-3xl font-bold">Signup</h1>
        <p className="mb-6 text-sm text-gray-600">
          Create a new Bloodwork MVP account.
        </p>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium">Full Name</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Email</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              type="email"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Password</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              type="password"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Role</label>
            <select
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={role}
              onChange={(e) =>
                setRole(e.target.value as "patient" | "doctor" | "admin")
              }
            >
              <option value="doctor">doctor</option>
              <option value="admin">admin</option>
              <option value="patient">patient</option>
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Date of Birth</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              placeholder="1999-01-31 or 31.01.1999"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Age</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              placeholder="25"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">Sex</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={sex}
              onChange={(e) => setSex(e.target.value)}
              placeholder="Male / Female"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">CNP</label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={cnp}
              onChange={(e) => setCnp(e.target.value)}
              placeholder="Optional"
            />
          </div>

          <div className="md:col-span-2">
            <label className="mb-2 block text-sm font-medium">
              Patient Identifier
            </label>
            <input
              className="w-full rounded border border-gray-300 p-3 text-sm"
              value={patientIdentifier}
              onChange={(e) => setPatientIdentifier(e.target.value)}
              placeholder="Optional patient ID / PID"
            />
          </div>
        </div>

        <div className="mt-6 space-y-3">
          <button
            onClick={handleSignup}
            disabled={loading || !fullName || !email || !password || !role}
            className="w-full rounded-lg bg-black px-4 py-3 text-white disabled:opacity-50"
          >
            {loading ? "Creating account..." : "Create Account"}
          </button>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            onClick={() => router.push("/login")}
            className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
          >
            Go to Login
          </button>
        </div>
      </div>
    </main>
  );
}