"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
};

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin {
          to {
            transform: rotate(360deg);
          }
        }

        .bloodwork-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: bloodworkSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="bloodwork-spinner" />
    </>
  );
}

export default function NewClinicalNotePage() {
  const params = useParams();
  const router = useRouter();
  const { language } = useLanguage();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const labels = useMemo(() => {
    if (language === "ro") {
      return {
        pageTitle: "Notă clinică nouă",
        back: "Înapoi la fișă",
        cardTitle: "Notă clinică",
        noteTitle: "Titlul notei",
        noteBody: "Scrie nota clinică aici...",
        visibility:
          "Nota va fi vizibilă tuturor medicilor cu acces la pacient. Doar medicul care a creat nota o va putea edita.",
        cancel: "Anulează",
        save: "Salvează nota",
        saving: "Se salvează...",
        loading: "Se încarcă pagina notei...",
        titleRequired: "Titlul notei este obligatoriu.",
        bodyRequired: "Conținutul notei este obligatoriu.",
        failedLoad: "Nu s-a putut încărca pagina notei.",
        failedSave: "Nu s-a putut salva nota.",
      };
    }

    return {
      pageTitle: "New clinical note",
      back: "Back to chart",
      cardTitle: "Clinical note",
      noteTitle: "Note title",
      noteBody: "Write the clinical note here...",
      visibility:
        "This note will be visible to all doctors with patient access. Only the doctor who created it can edit it.",
      cancel: "Cancel",
      save: "Save note",
      saving: "Saving...",
      loading: "Loading note page...",
      titleRequired: "Note title is required.",
      bodyRequired: "Note body is required.",
      failedLoad: "Could not load note page.",
      failedSave: "Could not save note.",
    };
  }, [language]);

  async function fetchData() {
    const [meResponse, profileResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<PatientProfileResponse>(`/patients/${patientId}/profile`),
    ]);

    if (meResponse.data.role !== "doctor") {
      router.push(`/patients/${patientId}`);
      return;
    }

    setCurrentUser(meResponse.data);
    setProfile(profileResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, labels.failedLoad));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

  async function submitNote(event: FormEvent) {
    event.preventDefault();

    if (!title.trim()) {
      setError(labels.titleRequired);
      return;
    }

    if (!content.trim()) {
      setError(labels.bodyRequired);
      return;
    }

    try {
      setSaving(true);
      setError("");

      await api.post(`/patients/${patientId}/notes`, {
        title: title.trim(),
        content: content.trim(),
        is_verified: true,
      });

      router.push(`/patients/${patientId}`);
    } catch (err) {
      setError(getErrorMessage(err, labels.failedSave));
    } finally {
      setSaving(false);
    }
  }

  if (loading || !currentUser || !profile) {
    return (
      <main
        className="app-page-bg"
        style={{
          minHeight: "100vh",
          padding: 24,
          display: "grid",
          placeItems: "center",
        }}
      >
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">{labels.loading}</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={labels.pageTitle}
      subtitle={`${profile.patient.full_name} · CNP ${valueOrDash(profile.patient.cnp)} · ID ${valueOrDash(
        profile.patient.patient_identifier
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)} disabled={saving}>
          {labels.back}
        </button>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      <div
        className="soft-card"
        style={{
          padding: 24,
          marginBottom: 24,
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
        }}
      >
        <div className="section-title">{labels.cardTitle}</div>
        <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.6, maxWidth: 760 }}>
          {labels.visibility}
        </div>
      </div>

      <form onSubmit={submitNote} className="soft-card" style={{ padding: 24, display: "grid", gap: 16 }}>
        <input
          className="text-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={labels.noteTitle}
          disabled={saving}
        />

        <textarea
          className="text-input"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={labels.noteBody}
          rows={16}
          disabled={saving}
          style={{
            resize: "vertical",
            minHeight: 360,
            lineHeight: 1.7,
          }}
        />

        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <button type="button" className="secondary-btn" onClick={() => router.push(`/patients/${patientId}`)} disabled={saving}>
            {labels.cancel}
          </button>

          <button type="submit" className="primary-btn" disabled={saving} style={{ display: "inline-flex", gap: 10, alignItems: "center" }}>
            {saving && <Spinner size={16} />}
            {saving ? labels.saving : labels.save}
          </button>
        </div>
      </form>
    </AppShell>
  );
}
