import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

function formatCooldownRemaining(until?: string | null) {
  if (!until) return null;
  const target = new Date(until).getTime();
  if (!Number.isFinite(target)) return null;
  const remainingMs = Math.max(0, target - Date.now());
  const totalMinutes = Math.ceil(remainingMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0 && minutes <= 0) return "clearing now";
  if (hours <= 0) return `${minutes}m left`;
  return `${hours}h ${minutes}m left`;
}

function unique(values: Array<string | null | undefined>) {
  return Array.from(
    new Set(
      values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean),
    ),
  );
}

export default function TradingStatusCard({
  enabled,
  reasonCodes,
  entryAllowed = enabled,
  entryReasonCodes = [],
  entryGate = null,
  weeklyPnlPenalty = null,
  consecutiveLossCooldownUntil = null,
}: {
  enabled: boolean;
  reasonCodes: string[];
  entryAllowed?: boolean;
  entryReasonCodes?: string[];
  entryGate?: Record<string, any> | null;
  weeklyPnlPenalty?: Record<string, any> | null;
  consecutiveLossCooldownUntil?: string | null;
}) {
  const accountDisabled = !enabled;
  const entryBlocked = entryAllowed === false;
  const entryOnlyBlocked = !accountDisabled && entryBlocked;
  const cooldownRemaining = formatCooldownRemaining(consecutiveLossCooldownUntil);

  const allReasons = unique([...reasonCodes, ...entryReasonCodes]);
  const hasConsecutiveLossCooldown = allReasons.includes("CONSECUTIVE_LOSS_COOLDOWN");

  const title = accountDisabled
    ? "Trading Disabled"
    : entryOnlyBlocked
    ? "Entry Blocked"
    : "Trading Enabled";

  const titleClass = accountDisabled
    ? "text-rose-200"
    : entryOnlyBlocked
    ? "text-amber-200"
    : "text-emerald-200";

  const dotClass = accountDisabled
    ? "bg-rose-400 shadow-[0_0_18px_rgba(251,113,133,0.8)]"
    : entryOnlyBlocked
    ? "bg-amber-400 shadow-[0_0_18px_rgba(251,191,36,0.8)]"
    : "bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.8)]";

  const message = accountDisabled
    ? "Account-level safety has disabled trading. New entries are blocked; maintenance remains active."
    : entryOnlyBlocked
    ? "Account is online, but new entries are blocked by the Trade Guardian entry gate. Maintenance remains active."
    : "All entry paths available. Maintenance remains active.";

  const stateChip = accountDisabled
    ? {
        label: "Entry blocked by account safety",
        className: "border-rose-400/20 bg-rose-500/10 text-rose-200",
      }
    : entryOnlyBlocked
    ? {
        label: "Entry Blocked",
        className: "border-amber-400/20 bg-amber-500/10 text-amber-200",
      }
    : {
        label: "Entry Enabled",
        className: "border-emerald-400/20 bg-emerald-500/10 text-emerald-200",
      };

  const reasonClass = accountDisabled
    ? "border-rose-300/20 bg-rose-500/10 text-rose-200"
    : "border-amber-300/20 bg-amber-500/10 text-amber-200";

  return (
    <GlassCard className="h-full">
      <SectionTitle title="Trading Status" subtitle="Entry and safety state" />

      <div className="flex items-center gap-3">
        <span className={`h-3 w-3 animate-pulse rounded-full ${dotClass}`} />
        <div className={`text-2xl font-semibold ${titleClass}`}>{title}</div>
      </div>

      <div className="mt-4 text-sm text-white/55">{message}</div>

      {weeklyPnlPenalty?.active ? (
        <div className="mt-4 rounded-2xl border border-amber-300/20 bg-amber-500/10 p-3 text-sm text-amber-100">
          <div className="font-medium">{weeklyPnlPenalty.label ?? "Weekly PnL penalty applied"}</div>
          <div className="mt-1 text-xs text-amber-100/70">
            Weekly PnL {Number(weeklyPnlPenalty.weekly_pnl_pct ?? 0).toFixed(2)}% · required score{" "}
            {weeklyPnlPenalty.required_trade_score_threshold ?? 85}
          </div>
        </div>
      ) : null}

      {hasConsecutiveLossCooldown && consecutiveLossCooldownUntil ? (
        <div className="mt-4 rounded-2xl border border-rose-300/20 bg-rose-500/10 p-3 text-sm text-rose-100">
          <div className="font-medium">
            Consecutive loss cooldown active{cooldownRemaining ? ` · ${cooldownRemaining}` : ""}
          </div>
          <div className="mt-1 text-xs text-rose-100/70">
            Cooldown until {new Date(consecutiveLossCooldownUntil).toLocaleString()}
          </div>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/70">
          Maintenance Active
        </div>

        <div className={`rounded-full border px-3 py-1 text-xs ${stateChip.className}`}>
          {stateChip.label}
        </div>

        {allReasons.map((reason) => (
          <div
            key={reason}
            className={`rounded-full border px-3 py-1 text-xs ${reasonClass}`}
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
