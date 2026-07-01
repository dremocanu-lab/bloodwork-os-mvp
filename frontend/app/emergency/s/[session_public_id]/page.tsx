"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { emergencyApi } from "@/lib/emergency-api";
import { useLanguage } from "@/lib/i18n";

export default function EmergencySessionPublicIdPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const publicId = Array.isArray(params.session_public_id)
    ? params.session_public_id[0]
    : params.session_public_id;

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!publicId) return;
    emergencyApi
      .get<{ id: number; public_id: string }>(
        `/emergency/sessions/by-public-id/${publicId}`
      )
      .then((res) => {
        router.replace(`/emergency/workspace?session_id=${res.data.id}`);
      })
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 403) setError(t("noAccessToRecord"));
        else if (status === 404) setError(t("linkNoLongerAvailable"));
        else setError(t("linkNoLongerAvailable"));
      });
  }, [publicId, router, t]);

  if (error) {
    return (
      <main
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          background: "var(--portal-bg)",
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 400 }}>
          <div style={{ fontSize: 32, marginBottom: 16 }}>🔒</div>
          <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 8 }}>{error}</div>
          <p className="muted-text" style={{ fontSize: 14, marginBottom: 20 }}>
            Emergency sessions expire automatically. Start a new session from the emergency portal.
          </p>
          <button
            type="button"
            className="primary-btn"
            style={{ marginTop: 8 }}
            onClick={() => router.push("/emergency")}
          >
            Emergency portal
          </button>
        </div>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--portal-bg)",
      }}
    >
      <p className="muted-text">{t("resolvingRecord")}</p>
    </main>
  );
}
