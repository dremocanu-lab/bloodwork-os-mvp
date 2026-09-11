"use client";

/**
 * Bragi application shell.
 *
 * Every authenticated surface in every role renders inside this. The header
 * is compact and sticky (breadcrumb, title, actions) instead of a 34px/900
 * heading floating in its own rounded card, and the page body is width-capped
 * and centred so 1440px+ screens do not stretch tables to unreadable widths.
 *
 * Responsive strategy is CSS-first: the sidebar becomes an off-canvas drawer
 * and the bottom bar appears via media query, so there is no layout flash
 * from measuring the viewport in JS on first paint.
 */

import { ReactNode, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Sidebar from "@/components/sidebar";
import BottomNav from "@/components/bottom-nav";
import { useLanguage } from "@/lib/i18n";
import { getWorkspaceLabel, type NavUser } from "@/lib/navigation";
import { IconChevronRight, IconMenu } from "@/components/ui/icon";

export type Crumb = { label: string; href?: string };

type AppShellProps = {
  user: NavUser;
  title: string;
  subtitle?: string;
  children: ReactNode;
  /** Header actions, right-aligned. Keep to two or three. */
  rightContent?: ReactNode;
  /** Trail above the title. The workspace root is prepended automatically. */
  breadcrumbs?: Crumb[];
  /**
   * Rendered flush under the header, outside the padded body - for a patient
   * context bar, a tab row or a filter strip that should span full width.
   */
  banner?: ReactNode;
  /** Patient surfaces read better a little looser than clinical/admin ones. */
  density?: "compact" | "default" | "comfortable";
  /** Suppress the page header when a surface supplies its own context bar. */
  hideHeader?: boolean;
};

export default function AppShell({
  user,
  title,
  subtitle,
  children,
  rightContent,
  breadcrumbs,
  banner,
  density,
  hideHeader = false,
}: AppShellProps) {
  const { t } = useLanguage();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close the drawer on navigation so it never survives a route change.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Lock background scroll while the drawer is open.
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mobileOpen]);

  const resolvedDensity =
    density ?? (user.role === "patient" || user.role === "care_partner" ? "comfortable" : "compact");

  const densityClass =
    resolvedDensity === "comfortable"
      ? "density-comfortable"
      : resolvedDensity === "compact"
      ? "density-compact"
      : "";

  return (
    <div className={`app-shell-root ${densityClass}`}>
      <Sidebar user={user} mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />

      <div className="app-shell-main">
        {/* Mobile: menu + which workspace you are in. Kept to 48px so it costs
            almost nothing of a phone screen. It shows the workspace rather
            than the page title, because the page title is already the h1
            directly below - repeating it wasted a line and told the user
            nothing new about where they were. */}
        <div className="app-mobile-topbar">
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon"
            onClick={() => setMobileOpen(true)}
            aria-label={t("navOpenMenu")}
            aria-expanded={mobileOpen}
          >
            <IconMenu size={18} />
          </button>

          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="app-mobile-brand">{getWorkspaceLabel(user, t)}</div>
          </div>
        </div>

        {/* One coherent sticky stack: the header and the banner (patient
            context bar / tab row) stick TOGETHER as a single unit, never
            as two independently-sticky elements both pinned to `top: 0` —
            that was a real, reproduced bug (e.g. Overview's patient name
            visibly bleeding through underneath the Overview/Timeline/Labs/
            Documents tab row while scrolling): two sticky siblings at the
            same `top: 0` occupy the same on-screen band once both are
            stuck, and with each using a semi-transparent/blurred
            background, whichever painted on top let the other's text show
            through. Wrapping both in one sticky container means there is
            only ever one stuck box, with the header and banner simply
            stacked inside it in normal flow — no overlap possible, and no
            transparency needed to hide it (see the opaque, solid
            backgrounds on .app-shell-header/.b-ctx in globals.css).
            `app-shell-sticky-with-header` only matters on mobile, where
            the fuller header intentionally scrolls away (it repeats
            content the compact `.app-mobile-topbar` already shows) while
            the banner/tabs stay pinned on their own — see globals.css. */}
        <div className={`app-shell-sticky${!hideHeader ? " app-shell-sticky-with-header" : ""}`}>
          {!hideHeader ? (
            <header className="app-shell-header">
              <div className="app-shell-header-row">
                <div style={{ minWidth: 0, flex: 1 }}>
                  {breadcrumbs?.length ? (
                    <nav className="b-crumbs" aria-label="Breadcrumb">
                      <span className="b-side-brand-role" style={{ flexShrink: 0 }}>
                        {getWorkspaceLabel(user, t)}
                      </span>
                      {breadcrumbs.map((crumb) => (
                        <span
                          key={`${crumb.label}-${crumb.href ?? ""}`}
                          style={{ display: "inline-flex", alignItems: "center", gap: 5, minWidth: 0 }}
                        >
                          <IconChevronRight size={11} className="b-crumbs-sep" />
                          {crumb.href ? (
                            <Link href={crumb.href}>{crumb.label}</Link>
                          ) : (
                            <span style={{ color: "var(--text-2)" }}>{crumb.label}</span>
                          )}
                        </span>
                      ))}
                    </nav>
                  ) : null}

                  <h1 className="app-shell-title">{title}</h1>
                  {subtitle ? <p className="app-shell-subtitle">{subtitle}</p> : null}
                </div>

                {rightContent ? (
                  <div className="app-shell-header-actions">{rightContent}</div>
                ) : null}
              </div>
            </header>
          ) : null}

          {banner}
        </div>

        <main className="app-shell-body b-view-enter" style={{ minWidth: 0 }}>
          {children}
        </main>
      </div>

      <BottomNav user={user} />
    </div>
  );
}
