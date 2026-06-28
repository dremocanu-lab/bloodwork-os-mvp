"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { getHomeByRole } from "@/lib/routing";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
};

type OfficialSection = {
  [sectionTitle: string]: string;
};

type OfficialInfo = {
  rxnorm_name?: string;
  rxcui?: string;
  label_title?: string;
  sections?: OfficialSection;
  candidates?: Array<{ rxcui: string; name: string; score?: string }>;
};

type PatientMedication = {
  id: number;
  name: string;
  dose_strength?: string | null;
  frequency?: string | null;
  reason?: string | null;
  status: string;
  route_form?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
  prescriber?: string | null;
  extra_info?: string | null;
  is_uncertain: boolean;
  created_at: string;
  updated_at?: string | null;
  official_match_status?: string | null;
  official_source_name?: string | null;
  official_source_url?: string | null;
  rxnorm_rxcui?: string | null;
  dailymed_setid?: string | null;
  official_info?: OfficialInfo | null;
  official_retrieved_at?: string | null;
  official_label_date?: string | null;
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--success-bg)", text: "var(--success-text)" },
  as_needed: { bg: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", text: "var(--primary)" },
  paused: { bg: "var(--warn-bg)", text: "var(--warn-text)" },
  stopped: { bg: "var(--panel-2)", text: "var(--muted)" },
};

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontWeight: 700, fontSize: 15 }}>{valueOrDash(value)}</div>
    </div>
  );
}

export default function MedicationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const medicationId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [med, setMed] = useState<PatientMedication | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Edit state
  const [editName, setEditName] = useState("");
  const [editDose, setEditDose] = useState("");
  const [editFrequency, setEditFrequency] = useState("");
  const [editReason, setEditReason] = useState("");
  const [editStatus, setEditStatus] = useState("active");
  const [editRoute, setEditRoute] = useState("");
  const [editStartDate, setEditStartDate] = useState("");
  const [editStopDate, setEditStopDate] = useState("");
  const [editPrescriber, setEditPrescriber] = useState("");
  const [editExtraInfo, setEditExtraInfo] = useState("");
  const [editUncertain, setEditUncertain] = useState(false);

  useEffect(() => {
    async function init() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        setCurrentUser(me.data);
        if (me.data.role !== "patient") {
          router.push(getHomeByRole(me.data.role));
          return;
        }
        const res = await api.get<PatientMedication>(`/my/medications/${medicationId}`);
        setMed(res.data);
      } catch (err) {
        setError(getErrorMessage(err, t("medSaveError")));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [medicationId, router]);

  function startEditing() {
    if (!med) return;
    setEditName(med.name);
    setEditDose(med.dose_strength || "");
    setEditFrequency(med.frequency || "");
    setEditReason(med.reason || "");
    setEditStatus(med.status);
    setEditRoute(med.route_form || "");
    setEditStartDate(med.start_date || "");
    setEditStopDate(med.stop_date || "");
    setEditPrescriber(med.prescriber || "");
    setEditExtraInfo(med.extra_info || "");
    setEditUncertain(med.is_uncertain);
    setEditing(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editName.trim()) {
      setError(t("medNameRequired"));
      return;
    }
    try {
      setSaving(true);
      setError("");
      const res = await api.put<PatientMedication>(`/my/medications/${medicationId}`, {
        name: editName.trim(),
        dose_strength: editDose.trim() || null,
        frequency: editFrequency.trim() || null,
        reason: editReason.trim() || null,
        status: editStatus,
        route_form: editRoute.trim() || null,
        start_date: editStartDate || null,
        stop_date: editStopDate || null,
        prescriber: editPrescriber.trim() || null,
        extra_info: editExtraInfo.trim() || null,
        is_uncertain: editUncertain,
      });
      setMed(res.data);
      setEditing(false);
    } catch (err) {
      setError(getErrorMessage(err, t("medSaveError")));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    try {
      setDeleting(true);
      await api.delete(`/my/medications/${medicationId}`);
      router.push("/my-records/medications");
    } catch (err) {
      setError(getErrorMessage(err, t("medSaveError")));
      setDeleting(false);
    }
  }

  async function handleRefreshOfficialInfo() {
    try {
      setRefreshing(true);
      setError("");
      await api.post(`/my/medications/${medicationId}/refresh-official-info`);
      const res = await api.get<PatientMedication>(`/my/medications/${medicationId}`);
      setMed(res.data);
    } catch (err) {
      setError(getErrorMessage(err, t("medSaveError")));
    } finally {
      setRefreshing(false);
    }
  }

  async function handleSelectRxcui(rxcui: string, name: string) {
    try {
      setRefreshing(true);
      setError("");
      await api.post(`/my/medications/${medicationId}/select-rxcui`, { rxcui, name });
      const res = await api.get<PatientMedication>(`/my/medications/${medicationId}`);
      setMed(res.data);
    } catch (err) {
      setError(getErrorMessage(err, t("medSaveError")));
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  if (!med || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{error || t("medSaveError")}</p>
      </main>
    );
  }

  const STATUS_LABELS: Record<string, string> = {
    active: t("active"),
    as_needed: t("medStatusAsNeeded"),
    paused: t("medStatusPaused"),
    stopped: t("medStatusStopped"),
  };

  const STATUS_OPTIONS = [
    { value: "active", label: t("active") },
    { value: "as_needed", label: t("medStatusAsNeeded") },
    { value: "paused", label: t("medStatusPaused") },
    { value: "stopped", label: t("medStatusStopped") },
  ];

  const statusStyle = STATUS_COLORS[med.status] || STATUS_COLORS.stopped;
  const officialInfo = med.official_info;
  const sections = officialInfo?.sections || {};
  const hasSections = Object.keys(sections).length > 0;
  const candidates = officialInfo?.candidates || [];

  if (editing) {
    return (
      <AppShell user={currentUser} title={t("editMedication")}>
        <div
          className="soft-card-tight"
          style={{ marginBottom: 24, padding: 14, background: "color-mix(in srgb, var(--primary) 8%, var(--panel))", borderColor: "color-mix(in srgb, var(--primary) 22%, transparent)" }}
        >
          <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
            {t("medSafetyEditDesc")}
          </div>
        </div>

        <form onSubmit={handleSave}>
          <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>{t("medDetails")}</div>

            {error && (
              <div style={{ marginBottom: 16, padding: "12px 16px", borderRadius: 12, background: "var(--danger-bg)", color: "var(--danger-text)", border: "1px solid var(--danger-border)", fontSize: 14 }}>
                {error}
              </div>
            )}

            <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medName")} <span style={{ color: "var(--danger-text)" }}>*</span></span>
              <input className="text-input" type="text" value={editName} onChange={(e) => setEditName(e.target.value)} required />
            </label>

            <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("status")}</span>
              <select className="text-input" value={editStatus} onChange={(e) => setEditStatus(e.target.value)} style={{ cursor: "pointer" }}>
                {STATUS_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
              </select>
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medDoseStrength")}</span>
                <input className="text-input" type="text" value={editDose} onChange={(e) => setEditDose(e.target.value)} />
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medFrequency")}</span>
                <input className="text-input" type="text" value={editFrequency} onChange={(e) => setEditFrequency(e.target.value)} />
              </label>
            </div>

            <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medRouteForm")}</span>
              <input className="text-input" type="text" value={editRoute} onChange={(e) => setEditRoute(e.target.value)} />
            </label>

            <label style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 20, cursor: "pointer" }}>
              <input type="checkbox" checked={editUncertain} onChange={(e) => setEditUncertain(e.target.checked)} style={{ marginTop: 2, width: 16, height: 16, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 800 }}>{t("medDoseNotVerified")}</div>
                <div className="muted-text" style={{ fontSize: 12 }}>{t("medDoseNotVerifiedHint")}</div>
              </div>
            </label>

            <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medRecordedReason")}</span>
              <textarea className="text-input" rows={2} value={editReason} onChange={(e) => setEditReason(e.target.value)} style={{ resize: "vertical" }} />
            </label>
          </div>

          <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>{t("medOptionalDetails")}</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 800 }}>{t("startDate")}</span>
                <input className="text-input" type="date" value={editStartDate} onChange={(e) => setEditStartDate(e.target.value)} />
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 800 }}>{t("stopDate")}</span>
                <input className="text-input" type="date" value={editStopDate} onChange={(e) => setEditStopDate(e.target.value)} />
              </label>
            </div>
            <label style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medPrescribedBy")}</span>
              <input className="text-input" type="text" value={editPrescriber} onChange={(e) => setEditPrescriber(e.target.value)} />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>{t("medAdditionalNotes")}</span>
              <textarea className="text-input" rows={3} value={editExtraInfo} onChange={(e) => setEditExtraInfo(e.target.value)} style={{ resize: "vertical" }} />
            </label>
          </div>

          <div style={{ display: "flex", gap: 12 }}>
            <button type="submit" className="primary-btn" disabled={saving}>{saving ? t("saving") : t("saveChanges")}</button>
            <button type="button" className="secondary-btn" onClick={() => { setEditing(false); setError(""); }}>{t("cancel")}</button>
          </div>
        </form>
      </AppShell>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={med.name}
      rightContent={
        <div style={{ display: "flex", gap: 10 }}>
          <button type="button" className="secondary-btn" onClick={startEditing}>{t("edit")}</button>
          <button
            type="button"
            className="secondary-btn"
            style={{ color: "var(--danger-text)", borderColor: "var(--danger-border)" }}
            onClick={() => setConfirmDelete(true)}
          >
            {t("delete")}
          </button>
        </div>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 16, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Safety notice */}
      <div
        className="soft-card-tight"
        style={{ marginBottom: 20, padding: 14, background: "color-mix(in srgb, var(--primary) 8%, var(--panel))", borderColor: "color-mix(in srgb, var(--primary) 22%, transparent)" }}
      >
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--primary)", marginBottom: 3 }}>
          {t("medSafetyTitleSingle")}
        </div>
        <div className="muted-text" style={{ fontSize: 12 }}>
          {t("medSafetyViewDesc")}
        </div>
      </div>

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="soft-card" style={{ marginBottom: 20, padding: 20, borderColor: "var(--danger-border)", background: "color-mix(in srgb, var(--danger-bg) 60%, var(--panel))" }}>
          <div style={{ fontWeight: 800, color: "var(--danger-text)", marginBottom: 8 }}>{t("medDeleteTitle")}</div>
          <div className="muted-text" style={{ marginBottom: 16, fontSize: 13 }}>{t("medDeleteDesc")}</div>
          <div style={{ display: "flex", gap: 10 }}>
            <button type="button" className="primary-btn" style={{ background: "var(--danger-text)" }} onClick={handleDelete} disabled={deleting}>
              {deleting ? t("deleting") : t("medDeleteConfirm")}
            </button>
            <button type="button" className="secondary-btn" onClick={() => setConfirmDelete(false)}>{t("cancel")}</button>
          </div>
        </div>
      )}

      {/* Main info */}
      <div className="soft-card" style={{ padding: 24, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 800, background: statusStyle.bg, color: statusStyle.text }}>
            {STATUS_LABELS[med.status] || med.status}
          </span>
          {med.is_uncertain && (
            <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 800, background: "var(--warn-bg)", color: "var(--warn-text)" }}>
              {t("medDoseNotVerified")}
            </span>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 18 }}>
          <Field label={t("medName")} value={med.name} />
          <Field label={t("medDoseStrength")} value={med.dose_strength} />
          <Field label={t("medRouteForm")} value={med.route_form} />
          <Field label={t("medFrequency")} value={med.frequency} />
          <Field label={t("medRecordedReason")} value={med.reason} />
          <Field label={t("medPrescribedBy")} value={med.prescriber} />
          <Field label={t("startDate")} value={med.start_date} />
          <Field label={t("stopDate")} value={med.stop_date} />
        </div>

        {med.extra_info && (
          <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <div className="muted-text" style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              {t("medAdditionalNotes")}
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.7 }}>{med.extra_info}</div>
          </div>
        )}

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          <div className="muted-text" style={{ fontSize: 11 }}>
            {t("created")} {med.created_at}
            {med.updated_at ? ` · ${t("lastEdited")} ${med.updated_at}` : ""}
          </div>
        </div>
      </div>

      {/* Official information */}
      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <div>
            <div className="section-title" style={{ marginBottom: 4 }}>{t("medOfficialLabelInfo")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>
              {t("medOfficialRefOnly")}
            </div>
          </div>
          <button
            type="button"
            className="secondary-btn"
            onClick={handleRefreshOfficialInfo}
            disabled={refreshing || med.official_match_status === "pending"}
            style={{ flexShrink: 0, fontSize: 13 }}
          >
            {refreshing ? t("working") : t("refresh")}
          </button>
        </div>

        {(!med.official_match_status || med.official_match_status === "pending") && (
          <div className="muted-text" style={{ fontSize: 13 }}>{t("medOfficialLookingUp")}</div>
        )}

        {med.official_match_status === "not_matched" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialNoMatchTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("medOfficialNoMatchDesc")}
            </div>
          </div>
        )}

        {med.official_match_status === "vague" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialVagueTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("medOfficialVagueDesc")}
            </div>
          </div>
        )}

        {med.official_match_status === "error" && (
          <div className="soft-card-tight" style={{ padding: 14, background: "var(--panel-2)" }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("medOfficialErrorTitle")}</div>
            <div className="muted-text" style={{ fontSize: 13 }}>
              {t("medOfficialErrorDesc")}
            </div>
          </div>
        )}

        {med.official_match_status === "multiple" && candidates.length > 0 && (
          <div>
            <div style={{ fontWeight: 700, marginBottom: 10 }}>{t("medOfficialMultipleTitle")}</div>
            <div style={{ display: "grid", gap: 8 }}>
              {candidates.map((c) => (
                <button
                  key={c.rxcui}
                  type="button"
                  className="soft-card-tight"
                  style={{ padding: 14, textAlign: "left", cursor: "pointer", display: "block" }}
                  onClick={() => handleSelectRxcui(c.rxcui, c.name)}
                  disabled={refreshing}
                >
                  <div style={{ fontWeight: 700 }}>{c.name}</div>
                  <div className="muted-text" style={{ fontSize: 12, marginTop: 3 }}>RxCUI: {c.rxcui}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {med.official_match_status === "matched" && (
          <div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
              <span style={{
                padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 800,
                background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))", color: "var(--primary)",
              }}>
                {t("medMatchMatched")}
              </span>
              <span className="muted-text" style={{ fontSize: 12 }}>
                {officialInfo?.rxnorm_name || med.name}
                {med.rxnorm_rxcui ? ` · RxCUI ${med.rxnorm_rxcui}` : ""}
              </span>
              {med.official_source_url && (
                <a
                  href={med.official_source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="secondary-btn"
                  style={{ fontSize: 12, padding: "4px 10px", borderRadius: 999 }}
                >
                  {t("medViewSource")}
                </a>
              )}
            </div>

            {med.official_source_name && (
              <div className="muted-text" style={{ fontSize: 12, marginBottom: 12 }}>
                Source: {med.official_source_name}
                {med.official_label_date ? ` · Label date: ${med.official_label_date}` : ""}
                {med.official_retrieved_at ? ` · ${t("retrieved")}: ${med.official_retrieved_at.slice(0, 10)}` : ""}
              </div>
            )}

            <div
              className="soft-card-tight"
              style={{ padding: 12, marginBottom: 16, background: "color-mix(in srgb, var(--warn-bg) 50%, var(--panel-2))", borderColor: "var(--warn-text)" }}
            >
              <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.65 }}>
                {t("medOfficialDisclaimerLong")}
              </div>
            </div>

            {hasSections ? (
              <div style={{ display: "grid", gap: 14 }}>
                {Object.entries(sections).map(([title, content]) => (
                  <div key={title} className="soft-card-tight" style={{ padding: 16 }}>
                    <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 8 }}>{title}</div>
                    <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
                      {content}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted-text" style={{ fontSize: 13 }}>
                {t("medOfficialNoSections")}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <button type="button" className="secondary-btn" onClick={() => router.push("/my-records/medications")}>
          {t("backToMedications")}
        </button>
      </div>
    </AppShell>
  );
}
