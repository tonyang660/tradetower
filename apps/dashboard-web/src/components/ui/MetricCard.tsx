import GlassCard from "./GlassCard";

export default function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <GlassCard className="min-h-[132px]">
      <div className="text-sm text-white/55">{label}</div>
      <div className="mt-4 text-3xl font-semibold tracking-tight text-white">{value}</div>
      {hint ? <div className="mt-3 text-sm text-white/45">{hint}</div> : null}
    </GlassCard>
  );
}
