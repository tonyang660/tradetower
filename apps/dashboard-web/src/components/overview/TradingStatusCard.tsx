import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function TradingStatusCard({
  enabled,
  reasonCodes,
}: {
  enabled: boolean;
  reasonCodes: string[];
}) {
  return (
    <GlassCard className="h-full">
      <SectionTitle title="Trading Status" subtitle="Entry and safety state" />

      <div className="flex items-center gap-3">
        <span
          className={`h-3 w-3 rounded-full ${
            enabled
              ? "bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.8)] animate-pulse"
              : "bg-rose-400 shadow-[0_0_18px_rgba(251,113,133,0.8)] animate-pulse"
          }`}
        />
        <div className={`text-2xl font-semibold ${enabled ? "text-emerald-200" : "text-rose-200"}`}>
          {enabled ? "Trading Enabled" : "Trading Disabled"}
        </div>
      </div>

      <div className="mt-4 text-sm text-white/55">
        {enabled
          ? "All entry paths available. Maintenance remains active."
          : "Trading is currently suspended or blocked."}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/70">
          Maintenance Active
        </div>

        {enabled ? (
          <div className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200">
            Entry Enabled
          </div>
        ) : (
          <div className="rounded-full border border-rose-400/20 bg-rose-500/10 px-3 py-1 text-xs text-rose-200">
            Entry Disabled
          </div>
        )}

        {reasonCodes.map((reason) => (
          <div
            key={reason}
            className="rounded-full border border-amber-300/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-200"
          >
            {reason}
          </div>
        ))}
      </div>
    </GlassCard>
  );
}