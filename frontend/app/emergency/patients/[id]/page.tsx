"use client";

// Backward-compat redirect: /emergency/patients/[id] → /emergency/workspace?tab=[sessionId]

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { EMERGENCY_STORAGE_KEYS, getEmergencyUser } from "@/lib/emergency-api";

export default function EmergencyPatientRedirectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    const u = getEmergencyUser();
    if (!u || (u.role !== "emergency_worker" && u.role !== "admin")) {
      router.replace("/emergency/login");
      return;
    }
    const sessionId = localStorage.getItem(EMERGENCY_STORAGE_KEYS.sessionId);
    if (sessionId) {
      router.replace(`/emergency/workspace?tab=${sessionId}`);
    } else {
      router.replace("/emergency/workspace");
    }
  }, [params.id, router]);

  return null;
}
