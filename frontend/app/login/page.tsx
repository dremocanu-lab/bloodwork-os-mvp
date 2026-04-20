"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

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

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          err?.response?.data?.error ||
          "Login failed."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-white p-8 text-black">
      <div className="mx-auto max-w-md rounded-xl border border-gray-300 bg-white p-6 shadow-sm">
        <h1 className="mb-2 text-3xl font-bold">Login</h1>
        <p className="mb-6 text-sm text-gray-600">
          Sign in to your Bloodwork MVP account.
        </p>

        <div className="space-y-4">
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

          <button
            onClick={handleLogin}
            disabled={loading || !email || !password}
            className="w-full rounded-lg bg-black px-4 py-3 text-white disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Login"}
          </button>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            onClick={() => router.push("/signup")}
            className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
          >
            Go to Signup
          </button>
        </div>
      </div>
    </main>
  );
}