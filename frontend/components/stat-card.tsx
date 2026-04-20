export default function StatCard({
  label,
  value,
  accent = "violet",
}: {
  label: string;
  value: string | number;
  accent?: "violet" | "green" | "orange" | "blue";
}) {
  const pillClass =
    accent === "green"
      ? "stat-pill stat-pill-green"
      : accent === "orange"
      ? "stat-pill stat-pill-orange"
      : accent === "blue"
      ? "stat-pill stat-pill-blue"
      : "stat-pill stat-pill-violet";

  return (
    <div className="soft-card" style={{ padding: 22 }}>
      <div className={pillClass}>{label}</div>
      <div style={{ marginTop: 16, fontSize: 34, fontWeight: 800 }}>{value}</div>
    </div>
  );
}