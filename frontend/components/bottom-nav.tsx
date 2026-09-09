"use client";

/**
 * Mobile bottom navigation.
 *
 * Replaces the "Menu" button that was the only way to move around Bragi on a
 * phone. The role's primary destinations are now one thumb-tap away, and
 * everything else is in the More sheet - so nothing became unreachable, it
 * just got re-ranked for the viewport.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useLanguage } from "@/lib/i18n";
import {
  activeNavKey,
  flattenNav,
  getNavGroups,
  getWorkspaceLabel,
  type NavUser,
} from "@/lib/navigation";
import { IconMore } from "@/components/ui/icon";

export default function BottomNav({ user }: { user: NavUser }) {
  const pathname = usePathname();
  const { t } = useLanguage();
  const [sheetOpen, setSheetOpen] = useState(false);

  const groups = getNavGroups(user, t);
  const all = flattenNav(groups);
  const activeKey = activeNavKey(all, pathname);

  const primary = all.filter((item) => item.primary).slice(0, 4);
  const overflow = all.filter((item) => !primary.includes(item));

  return (
    <>
      <nav className="b-bottom-nav" aria-label={getWorkspaceLabel(user, t)}>
        {primary.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.key}
              href={item.href}
              className="b-bottom-item"
              aria-current={activeKey === item.key ? "page" : undefined}
            >
              <Icon size={19} />
              <span>{item.label}</span>
            </Link>
          );
        })}

        {overflow.length ? (
          <button
            type="button"
            className="b-bottom-item"
            onClick={() => setSheetOpen(true)}
            aria-expanded={sheetOpen}
            aria-label={t("navMore")}
          >
            <IconMore size={19} />
            <span>{t("navMore")}</span>
          </button>
        ) : null}
      </nav>

      {sheetOpen ? (
        <>
          <button
            type="button"
            className="b-scrim"
            aria-label={t("navClose")}
            onClick={() => setSheetOpen(false)}
          />
          <div className="b-sheet" role="dialog" aria-label={t("navMore")}>
            <div className="b-sheet-grab" />
            <div className="b-sheet-body">
              {overflow.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    className="b-sheet-item"
                    aria-current={activeKey === item.key ? "page" : undefined}
                    onClick={() => setSheetOpen(false)}
                  >
                    <Icon size={17} style={{ color: "var(--muted)", flexShrink: 0 }} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
