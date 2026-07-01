"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

export default function DocumentPublicIdPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const publicId = Array.isArray(params.document_public_id)
    ? params.document_public_id[0]
    : params.document_public_id;

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!publicId) return;
    api
      .get<{ id: number; public_id: string }>(`/documents/by-public-id/${publicId}`)
      .then((res) => {
        router.replace(`/documents/${res.data.id}`);
      })
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 403) setError(t("noAccessToRecord"));
        else if (status === 404) setError(t("documentNotFound"));
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
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 400 }}>
          <div style={{ fontSize: 32, marginBottom: 16 }}>📄</div>
          <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 8 }}>{error}</div>
          <button
            type="button"
            className="primary-btn"
            style={{ marginTop: 16 }}
            onClick={() => router.back()}
          >
            Go back
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
      }}
    >
      <p className="muted-text">{t("resolvingRecord")}</p>
    </main>
  );
}
