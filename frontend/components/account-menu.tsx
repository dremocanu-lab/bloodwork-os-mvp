"use client";

/**
 * Account menu.
 *
 * Language, appearance and sign-out used to occupy two cards at the top of
 * the sidebar, above the navigation. They are preferences, not destinations,
 * so they now live in a popover behind the account button - which is where
 * every comparable product puts them, and which gives the navigation back
 * its prime real estate.
 *
 * On phones the same content renders as a bottom sheet.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useLanguage } from "@/lib/i18n";
import type { NavUser } from "@/lib/navigation";
import { getWorkspaceLabel } from "@/lib/navigation";
import {
  IconCheck,
  IconChevronUpDown,
  IconGlobe,
  IconLogout,
  IconMoon,
  IconSun,
} from "@/components/ui/icon";

const THEME_KEY = "bloodwork-theme";

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    // Read the applied state, not just storage: the boot script may have
    // selected dark from the OS preference with nothing saved yet.
    const applied = document.documentElement.classList.contains("dark");
    setTheme(applied ? "dark" : "light");
  }, []);

  function apply(next: "light" | "dark") {
    setTheme(next);
    localStorage.setItem(THEME_KEY, next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.body.classList.toggle("dark", next === "dark");
  }

  return { theme, apply };
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join("");
}

export default function AccountMenu({ user }: { user: NavUser }) {
  const router = useRouter();
  const { language, setLanguage, t } = useLanguage();
  const { theme, apply } = useTheme();
  const [open, setOpen] = useState(false);
  const isPhone = useMediaQuery("(max-width: 640px)");
  const wrapRef = useRef<HTMLDivElement>(null);

  // Dismiss on outside click and on Escape - expected of any popover.
  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: MouseEvent | TouchEvent) {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    router.push("/login");
  }

  const panel = (
    <>
      <div className="b-menu-label">{t("navSignedInAs")}</div>
      <div style={{ padding: "0 8px 8px", minWidth: 0 }}>
        <div className="b-account-name" style={{ fontSize: "var(--fs-sm)" }}>
          {user.full_name}
        </div>
        <div className="b-account-sub">{user.email}</div>
      </div>

      <div className="b-menu-sep" />

      <div className="b-menu-label">
        <IconGlobe size={11} style={{ display: "inline", verticalAlign: -1, marginRight: 4 }} />
        {t("language")}
      </div>
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

      <div className="b-menu-label">{t("theme")}</div>
      <button type="button" className="b-menu-item" onClick={() => apply("light")}>
        <IconSun size={14} />
        {t("lightModeEnabled")}
        {theme === "light" ? (
          <span className="b-menu-trail" style={{ color: "var(--primary)" }}>
            <IconCheck size={13} />
          </span>
        ) : null}
      </button>
      <button type="button" className="b-menu-item" onClick={() => apply("dark")}>
        <IconMoon size={14} />
        {t("darkModeEnabled")}
        {theme === "dark" ? (
          <span className="b-menu-trail" style={{ color: "var(--primary)" }}>
            <IconCheck size={13} />
          </span>
        ) : null}
      </button>

      <div className="b-menu-sep" />

      <button type="button" className="b-menu-item b-menu-item-danger" onClick={logout}>
        <IconLogout size={14} />
        {t("logout")}
      </button>
    </>
  );

  return (
    <div ref={wrapRef} style={{ position: "relative", minWidth: 0 }}>
      <button
        type="button"
        className="b-account-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t("navAccountMenu")}
      >
        <span className="b-avatar" aria-hidden="true">
          {initials(user.full_name)}
        </span>
        <span className="b-account-text">
          <span className="b-account-name">{user.full_name}</span>
          <span className="b-account-sub">{getWorkspaceLabel(user, t)}</span>
        </span>
        <IconChevronUpDown size={13} style={{ color: "var(--faint)", flexShrink: 0 }} />
      </button>

      {open && !isPhone ? (
        <div
          className="b-menu b-menu-up"
          role="menu"
          style={{ bottom: "calc(100% + 6px)", left: 0, right: 0, minWidth: 200 }}
        >
          {panel}
        </div>
      ) : null}

      {open && isPhone ? (
        <>
          <button
            type="button"
            className="b-scrim"
            aria-label={t("navClose")}
            onClick={() => setOpen(false)}
          />
          <div className="b-sheet" role="menu">
            <div className="b-sheet-grab" />
            <div className="b-sheet-body">{panel}</div>
          </div>
        </>
      ) : null}
    </div>
  );
}
