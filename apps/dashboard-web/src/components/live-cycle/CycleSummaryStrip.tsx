import GlassCard from "../ui/GlassCard";

function SummaryMiniCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <GlassCard className="min-h-[104px] p-4">
      <div className="text-xs uppercase tracking-[0.16em] text-white/35">{label}</div>
      <div className="mt-3 text-[2rem] font-semibold tracking-tight text-white">{value}</div>
      {hint ? <div className="mt-2 text-sm text-white/45">{hint}</div> : null}
    </GlassCard>
  );
}

export default function CycleSummaryStrip({
  summary,
}: {
  summary: {
    cycle_id: string;
    duration_seconds: number | null;
    refreshed_symbols_count: number;
    candidates_found: number;
    strategy_analyzed: number;
    strategy_trade_candidates: number;
    strategy_observe_candidates: number;
    strategy_no_trade: number;
    paper_fills: number;
    error_count: number;
  };
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-7">
      <SummaryMiniCard
        label="Cycle ID"
        value={summary.cycle_id.slice(11, 19)}
        hint="Latest cycle"
      />
      <SummaryMiniCard
        label="Duration"
        value={summary.duration_seconds !== null ? `${summary.duration_seconds}s` : "-"}
        hint="Completion time"
      />
      <SummaryMiniCard
        label="Refreshed"
        value={String(summary.refreshed_symbols_count)}
        hint="Symbols refreshed"
      />
      <SummaryMiniCard
        label="Candidates"
        value={String(summary.candidates_found)}
        hint="Passed filter"
      />
      <SummaryMiniCard
        label="Analyzed"
        value={String(summary.strategy_analyzed)}
        hint={`${summary.strategy_no_trade} no-trade`}
      />
      <SummaryMiniCard
        label="Trade · Observe"
        value={`${summary.strategy_trade_candidates} · ${summary.strategy_observe_candidates}`}
        hint="Strategy output split"
      />
      <SummaryMiniCard
        label="Fills"
        value={String(summary.paper_fills)}
        hint={summary.error_count > 0 ? `${summary.error_count} errors` : "No errors"}
      />
    </div>
  );
}