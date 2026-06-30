"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type CarePartnerCodeResponse = {
  code: string;
  created_at: string;
};

type EmergencyAccessSetting = {
  emergency_search_enabled: boolean;
  updated_at: string | null;
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "primary" }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "3px 9px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: "0.01em",
        background: tone === "primary" ? "color-mix(in srgb, var(--primary) 12%, var(--panel-2))" : "var(--panel-2)",
        color: tone === "primary" ? "var(--primary)" : "var(--muted)",
        border: `1px solid ${tone === "primary" ? "color-mix(in srgb, var(--primary) 30%, transparent)" : "var(--border)"}`,
      }}
    >
      {children}
    </span>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        userSelect: "none",
      }}
    >
      <div
        onClick={() => !disabled && onChange(!checked)}
        role="switch"
        aria-checked={checked}
        style={{
          width: 44,
          height: 24,
          borderRadius: 999,
          background: checked ? "var(--primary)" : "var(--border)",
          position: "relative",
          transition: "background 0.18s",
          flexShrink: 0,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 3,
            left: checked ? 23 : 3,
            width: 18,
            height: 18,
            borderRadius: 999,
            background: "white",
            boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
            transition: "left 0.18s",
          }}
        />
      </div>
      <span style={{ fontSize: 14, fontWeight: 700 }}>{label}</span>
    </label>
  );
}

export default function PatientSettingsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [carePartnerCode, setCarePartnerCode] = useState<CarePartnerCodeResponse | null>(null);
  const [emergencyAccess, setEmergencyAccess] = useState<EmergencyAccessSetting | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [codeCopied, setCodeCopied] = useState(false);
  const [showRegenerateModal, setShowRegenerateModal] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const [emergencySaving, setEmergencySaving] = useState(false);
  const [emergencyError, setEmergencyError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");
        if (meResponse.data.role !== "patient") {
          router.replace(meResponse.data.role === "doctor" ? "/my-patients" : "/assignments");
          return;
        }
        setCurrentUser(meResponse.data);

        const [codeResponse, emergencyResponse] = await Promise.all([
          api.get<CarePartnerCodeResponse>("/my/care-partner-code"),
          api.get<EmergencyAccessSetting>("/my/settings/emergency-access"),
        ]);
        setCarePartnerCode(codeResponse.data);
        setEmergencyAccess(emergencyResponse.data);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load settings."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [router]);

  async function copyCode() {
    if (!carePartnerCode) return;
    try {
      await navigator.clipboard.writeText(carePartnerCode.code);
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  }

  async function regenerateCode() {
    try {
      setRegenerating(true);
      setError("");
      const response = await api.post<CarePartnerCodeResponse>("/my/care-partner-code/regenerate");
      setCarePartnerCode(response.data);
      setShowRegenerateModal(false);
    } catch (err) {
      setError(getErrorMessage(err, "Could not regenerate code."));
    } finally {
      setRegenerating(false);
    }
  }

  async function deleteAccount() {
    try {
      setDeleting(true);
      setDeleteError("");
      await api.delete("/my/account");
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      router.replace("/login");
    } catch (err) {
      setDeleteError(getErrorMessage(err, "Could not delete account."));
      setDeleting(false);
    }
  }

  async function toggleEmergencyAccess(enabled: boolean) {
    if (emergencySaving) return;
    try {
      setEmergencySaving(true);
      setEmergencyError("");
      const response = await api.put<EmergencyAccessSetting>("/my/settings/emergency-access", {
        emergency_search_enabled: enabled,
      });
      setEmergencyAccess(response.data);
    } catch (err) {
      setEmergencyError(getErrorMessage(err, "Could not update emergency access setting."));
    } finally {
      setEmergencySaving(false);
    }
  }

  if (loading) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loading")}</p>
      </main>
    );
  }

  if (!currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{error || t("loading")}</p>
      </main>
    );
  }

  const deleteReady = deleteConfirmText.trim().toLowerCase() === "delete";
  const emergencyEnabled = emergencyAccess?.emergency_search_enabled ?? false;

  return (
    <AppShell user={currentUser} title={t("patientSettings")}>
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 16,
            padding: 16,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ display: "grid", gap: 16, maxWidth: 680 }}>

        {/* Patient Access Code */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>{t("carePartnerCode")}</div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("carePartnerCodeDesc")}
            </div>
          </div>

          {carePartnerCode ? (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "14px 18px",
                  borderRadius: 18,
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)",
                  marginBottom: 14,
                }}
              >
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 22,
                    fontWeight: 950,
                    letterSpacing: "0.08em",
                    flex: 1,
                    color: "var(--primary)",
                  }}
                >
                  {carePartnerCode.code}
                </span>
                <button type="button" className="secondary-btn" onClick={copyCode} style={{ flexShrink: 0 }}>
                  {codeCopied ? t("copied") : t("copyCode")}
                </button>
              </div>
              <div className="muted-text" style={{ fontSize: 12, marginBottom: 16 }}>
                {t("codeGeneratedAt")} {formatDate(carePartnerCode.created_at)}
              </div>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setShowRegenerateModal(true)}
              >
                {t("regenerateCode")}
              </button>
            </>
          ) : (
            <div className="muted-text">{t("loadingCode")}</div>
          )}
        </div>

        {/* Emergency Access */}
        <div
          className="soft-card"
          style={{
            padding: 24,
            borderColor: emergencyEnabled
              ? "color-mix(in srgb, var(--primary) 30%, transparent)"
              : undefined,
            background: emergencyEnabled
              ? "color-mix(in srgb, var(--primary) 5%, var(--panel))"
              : undefined,
          }}
        >
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <div className="section-title">{t("settingsEmergencyAccess")}</div>
              {emergencyEnabled && (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 900,
                    textTransform: "uppercase",
                    letterSpacing: "0.07em",
                    color: "var(--primary)",
                    background: "color-mix(in srgb, var(--primary) 12%, var(--panel-2))",
                    border: "1px solid color-mix(in srgb, var(--primary) 28%, transparent)",
                    borderRadius: 999,
                    padding: "2px 9px",
                  }}
                >
                  {t("settingsEmergencyDiscoverability")}
                </span>
              )}
            </div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.65 }}>
              {t("settingsEmergencyDiscoverabilityDesc")}
            </div>
          </div>

          {/* Badges */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 20 }}>
            <Badge>{t("settingsEmergencyBadgeReadOnly")}</Badge>
            <Badge>{t("settingsEmergencyBadgeAudited")}</Badge>
            <Badge>{t("settingsEmergencyBadgeSessions")}</Badge>
          </div>

          {/* Toggle */}
          <div
            style={{
              padding: "16px 18px",
              borderRadius: 14,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
              marginBottom: 16,
            }}
          >
            <Toggle
              checked={emergencyEnabled}
              onChange={toggleEmergencyAccess}
              disabled={emergencySaving}
              label={t("settingsEmergencyToggleLabel")}
            />
          </div>

          {/* Status text */}
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 12,
              background: emergencyEnabled
                ? "color-mix(in srgb, var(--primary) 8%, var(--panel-2))"
                : "var(--panel-2)",
              border: `1px solid ${emergencyEnabled ? "color-mix(in srgb, var(--primary) 22%, transparent)" : "var(--border)"}`,
              marginBottom: emergencyError ? 10 : 0,
            }}
          >
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: emergencyEnabled ? "var(--primary)" : "var(--muted)",
                marginBottom: 4,
              }}
            >
              {emergencyEnabled ? t("settingsEmergencyEnabledStatus") : t("settingsEmergencyDisabledStatus")}
            </div>
            <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.55 }}>
              {t("settingsEmergencySafetyNote")}
              {!emergencyEnabled && <> {t("settingsEmergencyCanTurnOff")}</>}
            </div>
          </div>

          {emergencyError && (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: 10,
                background: "var(--danger-bg)",
                border: "1px solid var(--danger-border)",
                color: "var(--danger-text)",
                fontSize: 13,
                marginBottom: 0,
                marginTop: 10,
              }}
            >
              {emergencyError}
            </div>
          )}

          {emergencyAccess?.updated_at && (
            <div className="muted-text" style={{ fontSize: 11, marginTop: 12 }}>
              Last updated {formatDate(emergencyAccess.updated_at)}
            </div>
          )}
        </div>

        {/* Emergency Access History placeholder */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 10 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>{t("settingsEmergencyHistoryTitle")}</div>
          </div>
          <div
            className="soft-card-tight"
            style={{ padding: "16px 18px", background: "var(--panel-2)" }}
          >
            <p className="muted-text" style={{ fontSize: 13, lineHeight: 1.65, margin: 0 }}>
              {t("settingsEmergencyHistoryPlaceholder")}
            </p>
          </div>
        </div>

        {/* Sharing & Visibility */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>{t("sharingAndVisibility")}</div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("sharingAndVisibilityDesc")}
            </div>
          </div>
          <button
            type="button"
            className="primary-btn"
            onClick={() => router.push("/my-records/access")}
          >
            {t("openSharingDashboard")}
          </button>
        </div>

        {/* Display Preferences */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>{t("displayPreferences")}</div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("language")} · {t("theme")}
            </div>
          </div>
          <div className="muted-text" style={{ fontSize: 13 }}>
            Language and theme preferences are available in the sidebar.
          </div>
        </div>

        {/* Account & Privacy */}
        <div
          className="soft-card"
          style={{
            padding: 24,
            borderColor: "var(--danger-border)",
            background: "color-mix(in srgb, var(--danger-bg) 18%, var(--panel))",
          }}
        >
          <div style={{ marginBottom: 16 }}>
            <div className="section-title" style={{ marginBottom: 6, color: "var(--danger-text)" }}>
              {t("accountAndPrivacy")}
            </div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("deleteAccountDesc")}
            </div>
          </div>
          <button
            type="button"
            className="secondary-btn"
            style={{ borderColor: "var(--danger-border)", color: "var(--danger-text)" }}
            onClick={() => { setDeleteConfirmText(""); setDeleteError(""); setShowDeleteModal(true); }}
          >
            {t("deleteAccount")}
          </button>
        </div>
      </div>

      {/* Regenerate Code Modal */}
      {showRegenerateModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 999,
            padding: 24,
          }}
          onClick={() => !regenerating && setShowRegenerateModal(false)}
        >
          <div
            className="soft-card"
            style={{ padding: 28, maxWidth: 440, width: "100%" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 950, fontSize: 18, marginBottom: 10 }}>
              {t("regenerateCodeConfirmTitle")}
            </div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.65, marginBottom: 22 }}>
              {t("regenerateCodeConfirmDesc")}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                className="secondary-btn"
                disabled={regenerating}
                onClick={() => setShowRegenerateModal(false)}
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                className="primary-btn"
                disabled={regenerating}
                onClick={regenerateCode}
              >
                {regenerating ? t("working") : t("regenerateCode")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Account Modal */}
      {showDeleteModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 999,
            padding: 24,
          }}
          onClick={() => !deleting && setShowDeleteModal(false)}
        >
          <div
            className="soft-card"
            style={{
              padding: 28,
              maxWidth: 460,
              width: "100%",
              borderColor: "var(--danger-border)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 950, fontSize: 18, marginBottom: 10, color: "var(--danger-text)" }}>
              {t("deleteAccount")}
            </div>
            <div
              className="muted-text"
              style={{
                fontSize: 13,
                lineHeight: 1.65,
                marginBottom: 18,
                padding: "12px 14px",
                borderRadius: 14,
                background: "var(--danger-bg)",
                color: "var(--danger-text)",
                border: "1px solid var(--danger-border)",
              }}
            >
              {t("confirmDeleteAccountWarning")}
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
                  Type <strong>delete</strong> to confirm
                </span>
                <input
                  className="text-input"
                  value={deleteConfirmText}
                  onChange={(e) => setDeleteConfirmText(e.target.value)}
                  placeholder="delete"
                  disabled={deleting}
                  autoComplete="off"
                />
              </label>
            </div>
            {deleteError && (
              <div style={{ color: "var(--danger-text)", fontSize: 13, marginBottom: 14 }}>
                {deleteError}
              </div>
            )}
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                className="secondary-btn"
                disabled={deleting}
                onClick={() => setShowDeleteModal(false)}
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                className="secondary-btn"
                disabled={!deleteReady || deleting}
                style={{
                  borderColor: deleteReady ? "var(--danger-border)" : undefined,
                  color: deleteReady ? "var(--danger-text)" : undefined,
                  opacity: !deleteReady ? 0.45 : 1,
                }}
                onClick={deleteAccount}
              >
                {deleting ? t("deletingAccount") : t("confirmDeleteAccount")}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
