"use client";

interface Props {
  title: string;
  description?: string;
  icon?: string; // emoji or symbol
}

export default function EmptyStateCard({ title, description, icon = "○" }: Props) {
  return (
    <div
      className="soft-card-tight"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "32px 24px",
        gap: 8,
        background: "var(--panel-2)",
      }}
    >
      <div
        aria-hidden
        style={{
          fontSize: 28,
          lineHeight: 1,
          color: "var(--muted)",
          opacity: 0.6,
          marginBottom: 2,
        }}
      >
        {icon}
      </div>
      <div style={{ fontWeight: 700, fontSize: 14, color: "var(--foreground)" }}>{title}</div>
      {description && (
        <div className="muted-text" style={{ fontSize: 12, maxWidth: 360, lineHeight: 1.5 }}>
          {description}
        </div>
      )}
    </div>
  );
}
