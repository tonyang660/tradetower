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
    <GlassCard className="min-h-[122px]">
      <div className="text-sm text-white/50">{label}</div>
      <div className="mt-3 text-[2rem] font-semibold tracking-tight text-white">{value}</div>
      {hint ? <div className="mt-2 text-sm text-white/40">{hint}</div> : null}
    </GlassCard>
  );
}