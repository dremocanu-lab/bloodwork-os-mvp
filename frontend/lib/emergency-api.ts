import axios from "axios";
import { getErrorMessage } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://bloodwork-os-api.onrender.com";

export const emergencyApi = axios.create({ baseURL: API_URL });

emergencyApi.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("emergency_access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export { getErrorMessage };

export const EMERGENCY_STORAGE_KEYS = {
  token: "emergency_access_token",
  user: "emergency_user",
  sessionId: "emergency_session_id",
  expiresAt: "emergency_session_expires_at",
  patientId: "emergency_patient_id",
} as const;

export function clearEmergencySession() {
  Object.values(EMERGENCY_STORAGE_KEYS).forEach((k) => localStorage.removeItem(k));
}

export function getEmergencyUser(): { id: number; email: string; full_name: string; role: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(EMERGENCY_STORAGE_KEYS.user);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
