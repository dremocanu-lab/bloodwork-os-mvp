"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "bloodwork-theme";

export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    const nextTheme: Theme = saved === "dark" ? "dark" : "light";

    setTheme(nextTheme);
    document.documentElement.classList.toggle("dark", nextTheme === "dark");
    document.body.classList.toggle("dark", nextTheme === "dark");
  }, []);

  function toggleTheme() {
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    localStorage.setItem(STORAGE_KEY, nextTheme);
    document.documentElement.classList.toggle("dark", nextTheme === "dark");
    document.body.classList.toggle("dark", nextTheme === "dark");
  }

  return (
    <div className={compact ? "theme-toggle-inline" : "theme-toggle-dock"}>
      <div className="theme-toggle-copy">
        <div className="theme-toggle-title">Appearance</div>
        <div className="theme-toggle-subtitle">
          {theme === "dark" ? "Dark mode enabled" : "Light mode enabled"}
        </div>
      </div>

      <button
        type="button"
        className={`theme-toggle-switch ${theme === "dark" ? "is-dark" : ""}`}
        onClick={toggleTheme}
        aria-label="Toggle theme"
      >
        <span className="theme-toggle-knob" />
      </button>
    </div>
  );
}
