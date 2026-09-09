"use client";

/**
 * Theme toggle.
 *
 * `compact` (used in every auth/marketing header) used to render an
 * "Appearance / Light mode enabled" label block plus a switch. Three words of
 * chrome for a preference, and on narrow headers it pushed the user's name
 * into a multi-line wrap. Compact is now a single icon button showing the
 * theme you would switch *to*, which is how every comparable product does it.
 *
 * The non-compact dock keeps its label, since it stands alone at the bottom
 * of marketing pages with room to explain itself.
 */

import { useEffect, useState } from "react";
import { useLanguage } from "@/lib/i18n";
import { IconMoon, IconSun } from "@/components/ui/icon";

type Theme = "light" | "dark";

const STORAGE_KEY = "bloodwork-theme";

export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { t } = useLanguage();
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    // Read the applied state, not just storage: the boot script may have
    // selected dark from the OS preference with nothing saved yet.
    const applied = document.documentElement.classList.contains("dark");
    setTheme(applied ? "dark" : "light");
  }, []);

  function toggleTheme() {
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    localStorage.setItem(STORAGE_KEY, nextTheme);
    document.documentElement.classList.toggle("dark", nextTheme === "dark");
    document.body.classList.toggle("dark", nextTheme === "dark");
  }

  const switchToLabel = theme === "dark" ? t("lightModeEnabled") : t("darkModeEnabled");

  if (compact) {
    return (
      <button
        type="button"
        className="b-btn b-btn-secondary b-btn-icon"
        onClick={toggleTheme}
        aria-label={switchToLabel}
        title={switchToLabel}
      >
        {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
      </button>
    );
  }

  return (
    <div className="theme-toggle-dock">
      <div className="theme-toggle-copy">
        <div className="theme-toggle-title">{t("appearance")}</div>
        <div className="theme-toggle-subtitle">
          {theme === "dark" ? t("darkModeEnabled") : t("lightModeEnabled")}
        </div>
      </div>

      <button
        type="button"
        className={`theme-toggle-switch ${theme === "dark" ? "is-dark" : ""}`}
        onClick={toggleTheme}
        aria-label={t("appearance")}
        aria-checked={theme === "dark"}
        role="switch"
      >
        <span className="theme-toggle-knob" />
      </button>
    </div>
  );
}
