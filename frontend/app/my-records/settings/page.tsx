"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import Link from "next/link";
import { useLanguage } from "@/lib/i18n";
import ThemeToggle from "@/components/theme-toggle";
import { SectionHead } from "@/components/ui";
import { IconChevronRight } from "@/components/ui/icon";

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

type EmergencyContact = {
  id: number;
  name: string;
  relationship: string | null;
  phone: string | null;
  notes: string | null;
  created_at: string;
};

const EMPTY_FORM = { name: "", relationship: "", phone: "", notes: "" };

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

/**
 * Was a full-radius filled pill; now the shared chip, so the three emergency
 * qualifiers read as bounded labels rather than three coloured lozenges.
 */
function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "primary";
}) {
  return <span className={`b-chip ${tone === "primary" ? "b-chip-brand" : ""}`}>{children}</span>;
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
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--s3)",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className="b-switch"
      >
        <span className="b-switch-knob" />
      </button>

      <span style={{ fontSize: "var(--fs-body)", fontWeight: 500 }}>{label}</span>
    </div>
  );
}

export default function PatientSettingsPage() {
  const router = useRouter();
  const { language, setLanguage, t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [carePartnerCode, setCarePartnerCode] = useState<CarePartnerCodeResponse | null>(null);
  const [emergencyAccess, setEmergencyAccess] = useState<EmergencyAccessSetting | null>(null);
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
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

  // Contact form state
  const [showContactForm, setShowContactForm] = useState(false);
  const [editingContact, setEditingContact] = useState<EmergencyContact | null>(null);
  const [contactForm, setContactForm] = useState(EMPTY_FORM);
  const [contactSaving, setContactSaving] = useState(false);
  const [contactError, setContactError] = useState("");
  const [deletingContactId, setDeletingContactId] = useState<number | null>(null);

  useEffect(() => {
    async function init() {
      try {
        const meResponse = await api.get<CurrentUser>("/auth/me");
        if (meResponse.data.role !== "patient") {
          router.replace(meResponse.data.role === "doctor" ? "/my-patients" : "/assignments");
          return;
        }
        setCurrentUser(meResponse.data);

        const [codeResponse, emergencyResponse, contactsResponse] = await Promise.all([
          api.get<CarePartnerCodeResponse>("/my/care-partner-code"),
          api.get<EmergencyAccessSetting>("/my/settings/emergency-access"),
          api.get<EmergencyContact[]>("/my/settings/emergency-contacts"),
        ]);
        setCarePartnerCode(codeResponse.data);
        setEmergencyAccess(emergencyResponse.data);
        setContacts(contactsResponse.data);
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

  function openAddForm() {
    setEditingContact(null);
    setContactForm(EMPTY_FORM);
    setContactError("");
    setShowContactForm(true);
  }

  function openEditForm(c: EmergencyContact) {
    setEditingContact(c);
    setContactForm({
      name: c.name,
      relationship: c.relationship ?? "",
      phone: c.phone ?? "",
      notes: c.notes ?? "",
    });
    setContactError("");
    setShowContactForm(true);
  }

  function cancelContactForm() {
    setShowContactForm(false);
    setEditingContact(null);
    setContactForm(EMPTY_FORM);
    setContactError("");
  }

  async function saveContact() {
    if (!contactForm.name.trim()) {
      setContactError("Name is required.");
      return;
    }
    try {
      setContactSaving(true);
      setContactError("");
      const payload = {
        name: contactForm.name.trim(),
        relationship: contactForm.relationship.trim() || null,
        phone: contactForm.phone.trim() || null,
        notes: contactForm.notes.trim() || null,
      };
      if (editingContact) {
        const res = await api.put<EmergencyContact>(
          `/my/settings/emergency-contacts/${editingContact.id}`,
          payload
        );
        setContacts((prev) => prev.map((c) => (c.id === editingContact.id ? res.data : c)));
      } else {
        const res = await api.post<EmergencyContact>("/my/settings/emergency-contacts", payload);
        setContacts((prev) => [...prev, res.data]);
      }
      cancelContactForm();
    } catch (err) {
      setContactError(getErrorMessage(err, "Could not save contact."));
    } finally {
      setContactSaving(false);
    }
  }

  async function deleteContact(id: number) {
    try {
      setDeletingContactId(id);
      await api.delete(`/my/settings/emergency-contacts/${id}`);
      setContacts((prev) => prev.filter((c) => c.id !== id));
      if (editingContact?.id === id) cancelContactForm();
    } catch (err) {
      setContactError(getErrorMessage(err, "Could not remove contact."));
    } finally {
      setDeletingContactId(null);
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
  const canAddContact = contacts.length < 5;

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

      <div style={{ display: "grid", gap: "var(--s4)", maxWidth: 720, margin: "0 auto" }}>

        {/* Care partner access lives on My Access, alongside the list of
            people who actually hold access - this page used to carry a second
            copy of the same code, copy button and regenerate flow. */}
        <section className="b-surface">
          <SectionHead
            title={t("carePartnerCode")}
            description={t("carePartnerCodeDesc")}
            actions={
              <Link href="/my-records/access" className="b-btn b-btn-secondary b-btn-sm">
                {t("myAccess")}
                <IconChevronRight size={12} />
              </Link>
            }
          />
        </section>

        {/* Emergency Access */}
        <div
          className="b-surface"
          style={{
            padding: 24,
            borderColor: emergencyEnabled
              ? "var(--primary-soft-border)"
              : undefined,
            background: emergencyEnabled
              ? "var(--surface)"
              : undefined,
          }}
        >
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <div className="section-title">{t("settingsEmergencyAccess")}</div>
              {emergencyEnabled && (
                <span className="b-chip b-chip-brand">
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
              borderRadius: "var(--r-md)",
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
            className={emergencyEnabled ? "b-notice" : "b-surface-2"}
            style={{
              padding: "10px 12px",
              marginBottom: emergencyError ? 10 : 0,
              display: "block",
            }}
          >
            <div
              style={{
                fontSize: "var(--fs-sm)",
                fontWeight: 600,
                color: emergencyEnabled ? "inherit" : "var(--muted)",
                marginBottom: 3,
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

        {/* Emergency Contacts */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
              <div className="section-title">{t("settingsEmergencyContactsTitle")}</div>
              {canAddContact && !showContactForm && (
                <button type="button" className="secondary-btn" style={{ fontSize: 13 }} onClick={openAddForm}>
                  + {t("settingsContactAdd")}
                </button>
              )}
            </div>
            <div className="muted-text" style={{ fontSize: 13, lineHeight: 1.6 }}>
              {t("settingsEmergencyContactsDesc")}
            </div>
          </div>

          {/* Contact list */}
          {contacts.length === 0 && !showContactForm && (
            <div
              className="soft-card-tight"
              style={{ padding: "14px 16px", background: "var(--panel-2)", marginBottom: 0 }}
            >
              <p className="muted-text" style={{ fontSize: 13, margin: 0 }}>{t("settingsContactsEmpty")}</p>
            </div>
          )}

          {contacts.map((c) => (
            <div key={c.id}>
              {editingContact?.id === c.id && showContactForm ? (
                <ContactForm
                  form={contactForm}
                  onChange={setContactForm}
                  onSave={saveContact}
                  onCancel={cancelContactForm}
                  saving={contactSaving}
                  error={contactError}
                  t={t}
                />
              ) : (
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    padding: "12px 0",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{c.name}</div>
                    <div className="muted-text" style={{ fontSize: 12, lineHeight: 1.55 }}>
                      {[c.relationship, c.phone, c.notes].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      className="secondary-btn"
                      style={{ fontSize: 12, padding: "5px 12px" }}
                      onClick={() => openEditForm(c)}
                      disabled={showContactForm || deletingContactId !== null}
                    >
                      {t("settingsContactEdit")}
                    </button>
                    <button
                      type="button"
                      className="secondary-btn"
                      style={{ fontSize: 12, padding: "5px 12px", color: "var(--danger-text)", borderColor: "var(--danger-border)" }}
                      onClick={() => deleteContact(c.id)}
                      disabled={deletingContactId === c.id || showContactForm}
                    >
                      {deletingContactId === c.id ? "…" : t("settingsContactDelete")}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Add form (when not editing an existing contact) */}
          {showContactForm && !editingContact && (
            <div style={{ marginTop: contacts.length > 0 ? 16 : 0 }}>
              <ContactForm
                form={contactForm}
                onChange={setContactForm}
                onSave={saveContact}
                onCancel={cancelContactForm}
                saving={contactSaving}
                error={contactError}
                t={t}
              />
            </div>
          )}

          {!canAddContact && !showContactForm && (
            <div className="muted-text" style={{ fontSize: 12, marginTop: 12 }}>
              {t("settingsContactMaxReached")}
            </div>
          )}

          {canAddContact && !showContactForm && contacts.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <button type="button" className="secondary-btn" style={{ fontSize: 13 }} onClick={openAddForm}>
                + {t("settingsContactAdd")}
              </button>
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
            className="b-btn b-btn-secondary"
            onClick={() => router.push("/my-records/access")}
          >
            {t("openSharingDashboard")}
            <IconChevronRight size={12} />
          </button>
        </div>

        {/* Display preferences. This card used to say "language and theme
            preferences are available in the sidebar" - a settings page whose
            settings were somewhere else. The actual controls are here now
            (they are also in the account menu, which is fine: one is the
            quick switch, this is the settings home). */}
        <section className="b-surface">
          <SectionHead title={t("displayPreferences")} />
          <div className="b-section-body">
            <div className="b-kv">
              <div className="b-kv-key">{t("language")}</div>
              <div className="b-kv-value">
                <div className="b-segmented" role="group" aria-label={t("language")}>
                  {(["en", "ro"] as const).map((code) => (
                    <button
                      key={code}
                      type="button"
                      aria-pressed={language === code}
                      onClick={() => setLanguage(code)}
                    >
                      {code === "en" ? "English" : "Română"}
                    </button>
                  ))}
                </div>
              </div>

              <div className="b-kv-key">{t("theme")}</div>
              <div className="b-kv-value">
                <ThemeToggle compact />
              </div>
            </div>
          </div>
        </section>

        {/* Account & Privacy */}
        <section className="b-surface" style={{ borderColor: "var(--danger-border)" }}>
          <SectionHead
            title={t("accountAndPrivacy")}
            description={t("deleteAccountDesc")}
            actions={
              <button
                type="button"
                className="b-btn b-btn-danger-quiet"
                onClick={() => {
                  setDeleteConfirmText("");
                  setDeleteError("");
                  setShowDeleteModal(true);
                }}
              >
                {t("deleteAccount")}
              </button>
            }
          />
        </section>
      </div>

      {/* Regenerate Code Modal */}
      {showRegenerateModal && (
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
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
            role="alertdialog"
            aria-modal="true"
            style={{ padding: 28, maxWidth: 440, width: "100%", border: "1px solid var(--border-strong)", boxShadow: "var(--shadow-lg)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 10 }}>
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

      {/* DELIBERATE EXCEPTION to the "no centered dialogs" rule (see
          BRAGI_REDUCTO_PLAN.md §12): account deletion is irreversible and
          removes the user's access and data entirely — a genuine
          blocking/critical workflow, not routine, so a larger centered
          confirmation surface is warranted. No dark backdrop (the rest of
          the page stays visible); a strong border/shadow keeps the modal
          clearly distinguished instead. */}
      {showDeleteModal && (
        <div
          role="presentation"
          style={{
            position: "fixed",
            inset: 0,
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
            role="alertdialog"
            aria-modal="true"
            style={{
              padding: 28,
              maxWidth: 460,
              width: "100%",
              borderColor: "var(--danger-border)",
              boxShadow: "var(--shadow-lg)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 10, color: "var(--danger-text)" }}>
              {t("deleteAccount")}
            </div>
            <div
              className="muted-text"
              style={{
                fontSize: 13,
                lineHeight: 1.65,
                marginBottom: 18,
                padding: "12px 14px",
                borderRadius: "var(--r-md)",
                background: "var(--danger-bg)",
                color: "var(--danger-text)",
                border: "1px solid var(--danger-border)",
              }}
            >
              {t("confirmDeleteAccountWarning")}
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span className="muted-text" style={{ fontSize: 12, fontWeight: 600 }}>
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

function ContactForm({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
  error,
  t,
}: {
  form: typeof EMPTY_FORM;
  onChange: (f: typeof EMPTY_FORM) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string;
  t: (k: string) => string;
}) {
  return (
    <div
      style={{
        padding: "16px 18px",
        borderRadius: "var(--r-md)",
        border: "1px solid var(--border)",
        background: "var(--panel-2)",
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{t("settingsContactName")} *</span>
          <input
            className="text-input"
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            placeholder="Full name"
            disabled={saving}
            autoFocus
          />
        </label>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{t("settingsContactRelationship")}</span>
          <input
            className="text-input"
            value={form.relationship}
            onChange={(e) => onChange({ ...form, relationship: e.target.value })}
            placeholder="e.g. Spouse, Parent"
            disabled={saving}
          />
        </label>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{t("settingsContactPhone")}</span>
          <input
            className="text-input"
            value={form.phone}
            onChange={(e) => onChange({ ...form, phone: e.target.value })}
            placeholder="+40 700 000 000"
            disabled={saving}
            type="tel"
          />
        </label>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{t("settingsContactNotes")}</span>
          <input
            className="text-input"
            value={form.notes}
            onChange={(e) => onChange({ ...form, notes: e.target.value })}
            placeholder="e.g. Available after 6pm"
            disabled={saving}
          />
        </label>
      </div>
      {error && (
        <div style={{ fontSize: 13, color: "var(--danger-text)", padding: "8px 12px", background: "var(--danger-bg)", borderRadius: 8, border: "1px solid var(--danger-border)" }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="primary-btn" style={{ fontSize: 13 }} onClick={onSave} disabled={saving}>
          {saving ? "…" : t("settingsContactSave")}
        </button>
        <button type="button" className="secondary-btn" style={{ fontSize: 13 }} onClick={onCancel} disabled={saving}>
          {t("cancel")}
        </button>
      </div>
    </div>
  );
}
