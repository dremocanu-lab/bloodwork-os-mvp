type TopbarUser = {
  full_name: string;
  role: "patient" | "doctor" | "admin";
};

export default function Topbar({
  title,
  subtitle,
  user,
  rightContent,
}: {
  title: string;
  subtitle?: string;
  user: TopbarUser;
  rightContent?: React.ReactNode;
}) {
  return (
    <div
      style={{
        marginBottom: 28,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ minWidth: 280 }}>
        <div
          className="soft-card-tight"
          style={{
            padding: "12px 16px",
            marginBottom: 16,
            maxWidth: 360,
            color: "#6b7280",
            fontSize: 14,
          }}
        >
          Search patients, documents, or workflow items
        </div>

        <div style={{ fontSize: 36, fontWeight: 800, lineHeight: 1.1 }}>{title}</div>
        {subtitle && (
          <div style={{ marginTop: 8, fontSize: 15, color: "#6b7280" }}>{subtitle}</div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        {rightContent}
        <div className="soft-card-tight" style={{ padding: "12px 16px", minWidth: 150 }}>
          <div style={{ fontWeight: 700 }}>{user.full_name}</div>
          <div style={{ fontSize: 13, color: "#6b7280", marginTop: 4, textTransform: "capitalize" }}>
            {user.role}
          </div>
        </div>
      </div>
    </div>
  );
}
