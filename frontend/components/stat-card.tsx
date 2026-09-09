/**
 * Legacy StatCard shim.
 *
 * Was a 22px-padded rounded card with a gradient tint, a coloured top border
 * and a 34px/800 figure - four of them filled a whole phone screen before any
 * real content. It is now a hairline metric tile with a 21px figure and no
 * decoration. Prefer <Metrics>/<Metric> from components/ui for new work; this
 * exists so existing callers keep working with the new visual language.
 */

export default function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  /** Retained for call-site compatibility; colour no longer varies by accent. */
  accent?: "violet" | "green" | "orange" | "blue";
}) {
  void accent;

  // `.stat-card` is a self-contained hairline tile, so this still works when
  // dropped into a plain grid rather than a <Metrics> row.
  return (
    <div className="stat-card">
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value">{value}</div>
    </div>
  );
}
