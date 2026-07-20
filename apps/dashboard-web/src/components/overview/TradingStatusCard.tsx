import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function TradingStatusCard({
  enabled,
  reasonCodes,
  entryAllowed = enabled,
  entryReasonCodes = [],
  entryGate = null,
}: {
  enabled: boolean;
  reasonCodes: string[];
  entryAllowed?: boolean;
  entryReasonCodes?: string[];
  entryGate?: Record<string, any> | null;
}) {
  const entryBlocked = enabled && entryAllowed === false;
  const title = !enabled
    ? "Trading Disabled"
    : entryBlocked
    ? "Entry Blocked"
    : "Trading Enabled";

  const titleClass = !enabled
    ? "text-rose-200"
    : entryBlocked
    ? "text-amber-200"
    : "text-emerald-200";

  const dotClass = !enabled
    ? "bg-rose-400 shadow-[0_0_18px_rgba(251,113,133,0.8)]"
    : entryBlocked
    ? "bg-amber-400 shadow-[0_0_18px_rgba(251,191,36,0.8)]"
    : "bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.8)]";

  const message = !enabled
    ? "Trading is currently suspended or blocked. Maintenance remains active."
    : entryBlocked
    ? "Account is online, but new entries are blocked by the same Trade Guardian entry gate used by the scheduler."
    : "All entry paths available. Maintenance remains active.";

  const uniqueEntryReasons = Array.from(new Set(entryReasonCodes.filter(Boolean)));
  const uniqueTradingReasons = Array.from(new Set(reasonCodes.filter(Boolean)));

  return (
    <GlassCard className="h-full">
      <SectionTitle title="Trading Status" subtitle="Entry and safety state" />

      <div className="flex items-center gap-3">
        <span className={`h-3 w-3 animate-pulse rounded-full ${dotClass}`} />
        <div className={`text-2xl font-semibold ${titleClass}`}>{title}</div>
      </div>

      <div className="mt-4 text-sm text-white/55">{message}</div>

      <div className="mt-4 flex flex-wrap gap-2">
        <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/70">
          Maintenance Active
        </div>

        {entryAllowed ? (
          <div className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200">
            Entry Enabled
          </div>
        ) : (
          <div className="rounded-full border border-amber-400/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-200">
            Entry Blocked
          </div>
        )}

        {!enabled ? (
          <div className="rounded-full border border-rose-400/20 bg-rose-500/10 px-3 py-1 text-xs text-rose-200">
            Account Trading Disabled
          </div>
        ) : null}

        {uniqueTradingReasons.map((reason) => (
          <div
            key={`trading-${reason}`}
            className="rounded-full border border-rose-300/20 bg-rose-500/10 px-3 py-1 text-xs text-rose-200"
          >
            {reason}
          </div>
        ))}

        {uniqueEntryReasons.map((reason) => (
          <div
            key={`entry-${reason}`}
            className="rounded-full border border-amber-300/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-200"
          >
            {reason}
          </div>
        ))}
      </div>

      {entryGate?.execution_mode ? (
        <div className="mt-3 text-xs text-white/35">
          Execution mode: <span className="text-white/55">{entryGate.execution_mode}</span>
        </div>
      ) : null}
    </GlassCard>
  );
}
