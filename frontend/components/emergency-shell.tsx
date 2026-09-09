"use client";

/**
 * Emergency access portal shell.
 *
 * This is the surface someone uses under time pressure, so it is the one
 * place where the design leans deliberately operational: a persistent red
 * audit strip stating exactly what kind of access this is, and nothing
 * decorative competing with it.
 *
 * Changes: the theme switch and language toggle were sitting inline in the
 * header with their "Appearance / Light mode enabled" label, which pushed the
 * worker's name into a three-line wrap. Preferences now live behind a single
 * overflow menu, the name and sign-out are on one line, and the content
 * column is wider so the patient record is not squeezed into 860px.
 */

import { ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/i18n";
import {
  IconChevronDown,
  IconLogout,
  IconMoon,
  IconSun,
  IconCheck,
} from "@/components/ui/icon";

type EmergencyShellUser = {
  id: number;
  email: string;
  full_name: string;
  role: string;
};

type EmergencyShellProps = {
  user: EmergencyShellUser | null;
  children: ReactNode;
  onLogout?: () => void;
  /** Wide surfaces (a patient record) opt out of the narrow reading column. */
  wide?: boolean;
};

const THEME_KEY = "bloodwork-theme";

function EmergencyMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 56 68"
      width={(size * 56) / 68}
      height={size}
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <path
        d="M6 4h44a2 2 0 0 1 2 2v32c0 16-28 26-28 26S-4 54-4 38V6a2 2 0 0 1 2-2Z"
        transform="translate(4)"
        fill="#82C09A"
      />
      <rect x="14" y="28" width="28" height="6" rx="3" fill="#fff" />
      <rect x="25" y="17" width="6" height="28" rx="3" fill="#fff" />
    </svg>
  );
}

export default function EmergencyShell({
  user,
  children,
  onLogout,
  wide = false,
}: EmergencyShellProps) {
  const { language, setLanguage, t } = useLanguage();
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Read the applied state, not just storage: the boot script may have
    // selected dark from the OS preference with nothing saved yet.
    const applied = document.documentElement.classList.contains("dark");
    setTheme(applied ? "dark" : "light");
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(event: MouseEvent) {
      if (!wrapRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  function applyTheme(next: "light" | "dark") {
    setTheme(next);
    localStorage.setItem(THEME_KEY, next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.body.classList.toggle("dark", next === "dark");
  }

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
      }}
    >
      {/* Header */}
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          display: "flex",
          alignItems: "center",
          gap: "var(--s3)",
          minHeight: 48,
          padding: "0 var(--s5)",
          background: "var(--surface)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <Link
          href="/emergency"
          style={{ display: "flex", alignItems: "center", gap: "var(--s2)", minWidth: 0 }}
        >
          <EmergencyMark size={22} />
          <span style={{ minWidth: 0 }}>
            <span
              style={{
                display: "block",
                fontSize: "var(--fs-sm)",
                fontWeight: 600,
                letterSpacing: "-0.012em",
                lineHeight: 1.2,
              }}
            >
              {t("emergencyPortalTitle")}
            </span>
            <span
              style={{
                display: "block",
                fontSize: "var(--fs-micro)",
                color: "var(--muted)",
              }}
            >
              Bragi Health
            </span>
          </span>
        </Link>

        <div style={{ flex: 1 }} />

        {user ? (
          <div ref={wrapRef} style={{ position: "relative", flexShrink: 0 }}>
            <button
              type="button"
              className="b-btn b-btn-ghost b-btn-sm"
              onClick={() => setMenuOpen((value) => !value)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              style={{ maxWidth: 220 }}
            >
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {user.full_name}
              </span>
              <IconChevronDown size={12} />
            </button>

            {menuOpen ? (
              <div
                className="b-menu"
                role="menu"
                style={{ top: "calc(100% + 4px)", right: 0 }}
              >
                <div className="b-menu-label">{t("navSignedInAs")}</div>
                <div style={{ padding: "0 8px 8px" }}>
                  <div className="b-account-sub">{user.email}</div>
                </div>

                <div className="b-menu-sep" />
                <div className="b-menu-label">{t("language")}</div>
                {(["en", "ro"] as const).map((code) => (
                  <button
                    key={code}
                    type="button"
                    className="b-menu-item"
                    onClick={() => setLanguage(code)}
                  >
                    {code === "en" ? "English" : "Română"}
                    {language === code ? (
                      <span className="b-menu-trail" style={{ color: "var(--primary)" }}>
                        <IconCheck size={13} />
                      </span>
                    ) : null}
                  </button>
                ))}

                <div className="b-menu-sep" />
                <button
                  type="button"
                  className="b-menu-item"
                  onClick={() => applyTheme(theme === "dark" ? "light" : "dark")}
                >
                  {theme === "dark" ? <IconSun size={14} /> : <IconMoon size={14} />}
                  {theme === "dark" ? t("lightModeEnabled") : t("darkModeEnabled")}
                </button>

                {onLogout ? (
                  <>
                    <div className="b-menu-sep" />
                    <button
                      type="button"
                      className="b-menu-item b-menu-item-danger"
                      onClick={onLogout}
                    >
                      <IconLogout size={14} />
                      {t("emergencySignOut")}
                    </button>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </header>

      {/* Audit strip: the one piece of loud colour in Bragi, because it states
          that this access is logged, read-only and time-limited. */}
      <div
        role="status"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--s2)",
          flexWrap: "wrap",
          padding: "5px var(--s5)",
          background: "var(--danger-bg)",
          borderBottom: "1px solid var(--danger-border)",
          fontSize: "var(--fs-xs)",
          color: "var(--danger)",
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 6,
            height: 6,
            borderRadius: "var(--r-full)",
            background: "currentColor",
            flexShrink: 0,
          }}
        />
        <strong
          style={{
            fontWeight: 600,
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            fontSize: "var(--fs-micro)",
          }}
        >
          {t("emergencyAuditedAccess")}
        </strong>
        <span style={{ opacity: 0.7 }}>·</span>
        <span>{t("emergencyReadOnly")}</span>
        <span style={{ opacity: 0.7 }}>·</span>
        <span>{t("emergencyTimeLimitedAccess")}</span>
        <span style={{ opacity: 0.7 }}>·</span>
        <span>{t("emergencyUseOnlyForEmergency")}</span>
      </div>

      <main
        style={{
          flex: 1,
          width: "100%",
          maxWidth: wide ? "var(--content-max)" : 780,
          margin: "0 auto",
          padding: "var(--s5) var(--s5) var(--s8)",
          minWidth: 0,
        }}
        className="b-view-enter"
      >
        {children}
      </main>
    </div>
  );
}
