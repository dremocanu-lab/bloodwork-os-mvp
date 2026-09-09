"use client";

/**
 * Language toggle.
 *
 * Was a 42px full-radius pill at weight 950. Now a standard small secondary
 * button, matching the compact theme toggle it always sits next to.
 */

import { useLanguage } from "@/lib/i18n";

export default function LanguageToggle() {
  const { language, setLanguage, t } = useLanguage();

  const nextLanguage = language === "en" ? "ro" : "en";

  return (
    <button
      type="button"
      className="b-btn b-btn-secondary"
      onClick={() => setLanguage(nextLanguage)}
      aria-label={t("language")}
      title={t("language")}
      style={{ minWidth: 44 }}
    >
      {language === "en" ? "RO" : "EN"}
    </button>
  );
}
