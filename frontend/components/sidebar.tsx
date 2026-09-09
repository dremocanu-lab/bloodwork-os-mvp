"use client";

/**
 * Desktop sidebar / mobile drawer.
 *
 * Rebuilt around three ideas:
 *  - Navigation is a list of links, not a stack of primary/secondary buttons.
 *    The active item is the only one with brand colour, so "where am I" is
 *    answerable at a glance.
 *  - Preferences (language, appearance, sign out) moved out of the nav into
 *    the account menu at the bottom, freeing the space they used to occupy
 *    above the actual destinations.
 *  - The brand lockup is a 24px mark plus the workspace name, not an 88px
 *    logo block. Role context stays visible but costs one line.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLanguage } from "@/lib/i18n";
import {
  activeNavKey,
  flattenNav,
  getHomeHref,
  getNavGroups,
  getOrgLabel,
  getWorkspaceLabel,
  type NavUser,
} from "@/lib/navigation";
import AccountMenu from "@/components/account-menu";
import { IconClose } from "@/components/ui/icon";

function BragiMark({ size = 22 }: { size?: number }) {
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

export default function Sidebar({
  user,
  mobileOpen = false,
  onCloseMobile,
}: {
  user: NavUser;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}) {
  const pathname = usePathname();
  const { t } = useLanguage();

  const groups = getNavGroups(user, t);
  const activeKey = activeNavKey(flattenNav(groups), pathname);
  const org = getOrgLabel(user, t);

  return (
    <>
      <aside
        className={`app-sidebar ${mobileOpen ? "mobile-open" : ""}`}
        aria-label={getWorkspaceLabel(user, t)}
      >
        <div className="b-side-brand">
          <Link
            href={getHomeHref(user)}
            onClick={onCloseMobile}
            className="b-side-brand"
            style={{ border: 0, height: "auto", padding: 0, flex: 1, minWidth: 0 }}
          >
            <BragiMark size={22} />
            <span className="b-side-brand-text">
              <span className="b-side-brand-name">bragi</span>
              <span className="b-side-brand-role">{getWorkspaceLabel(user, t)}</span>
            </span>
          </Link>

          {/* Drawer close affordance, mobile only. */}
          <button
            type="button"
            className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
            onClick={onCloseMobile}
            aria-label={t("navClose")}
            style={{ display: mobileOpen ? "inline-flex" : "none" }}
          >
            <IconClose size={15} />
          </button>
        </div>

        <nav className="b-side-scroll">
          {groups.map((group) => (
            <div key={group.key} style={{ minWidth: 0 }}>
              {group.label ? <div className="b-side-group">{group.label}</div> : null}

              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeKey === item.key;

                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    onClick={onCloseMobile}
                    className="b-nav-item"
                    aria-current={isActive ? "page" : undefined}
                  >
                    <Icon size={15} className="b-nav-icon" />
                    <span className="b-nav-label">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="b-side-foot">
          {org ? (
            <div
              className="b-account-sub"
              style={{ padding: "0 6px 6px", whiteSpace: "normal", lineHeight: 1.35 }}
            >
              {org}
            </div>
          ) : null}
          <AccountMenu user={user} />
        </div>
      </aside>

      <button
        type="button"
        className={`sidebar-overlay ${mobileOpen ? "open" : ""}`}
        onClick={onCloseMobile}
        aria-label={t("navClose")}
        tabIndex={mobileOpen ? 0 : -1}
      />
    </>
  );
}
