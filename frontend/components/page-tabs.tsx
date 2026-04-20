"use client";

type Tab = {
  key: string;
  label: string;
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
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 24 }}>
      {tabs.map((tab) => {
        const active = tab.key === activeTab;

        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            style={{
              border: active ? "none" : "1px solid var(--border)",
              background: active ? "var(--accent)" : "white",
              color: active ? "white" : "#374151",
              borderRadius: 16,
              padding: "10px 16px",
              fontWeight: 700,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}