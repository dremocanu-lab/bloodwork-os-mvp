"use client";

/**
 * Legacy PageTabs shim.
 *
 * The original painted the active tab with `var(--accent)` - a variable that
 * was never declared, so the active tab rendered with no background - and
 * hard-coded `background: white` / `color: #374151`, which broke in dark
 * mode. It now delegates to the shared underline Tabs so every tab row in
 * Bragi looks and behaves the same. The prop signature is unchanged.
 */

import { Tabs } from "@/components/ui";

type Tab = {
  key: string;
  label: string;
  count?: number;
};

export default function PageTabs({
  tabs,
  activeTab,
  onChange,
}: {
  tabs: Tab[];
  activeTab: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div style={{ marginBottom: "var(--s4)" }}>
      <Tabs tabs={tabs} activeTab={activeTab} onChange={onChange} />
    </div>
  );
}
