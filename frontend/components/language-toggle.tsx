"use client";

import { useLanguage } from "@/lib/i18n";

export default function LanguageToggle() {
  const { language, setLanguage } = useLanguage();

  const nextLanguage = language === "en" ? "ro" : "en";

  return (
    <button
      type="button"
      className="secondary-btn"
      onClick={() => setLanguage(nextLanguage)}
      style={{
        height: 42,
        minWidth: 58,
        padding: "0 14px",
        borderRadius: 999,
        fontWeight: 950,
      }}
    >
      {language === "en" ? "RO" : "EN"}
    </button>
  );
}
