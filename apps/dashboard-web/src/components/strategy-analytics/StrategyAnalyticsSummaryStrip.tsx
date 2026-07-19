import MetricCard from "../ui/MetricCard";
import type { StrategyAnalyticsSummary } from "../../types/strategyAnalytics";
import {
  money,
  metricNumber,
  minutesLabel,
  ratioPercent,
} from "../../lib/strategyAnalytics";

export default function StrategyAnalyticsSummaryStrip({
  summary,
}: {
  summary: StrategyAnalyticsSummary | null;
}) {
  const s = summary;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-8">
      <MetricCard
        label="Closed Trades"
        value={String(s?.total_closed_trades ?? 0)}
        hint="Trades included in analytics"
      />
      <MetricCard
        label="Gross PnL"
        value={money(s?.gross_pnl)}
        hint="Before fees"
      />
      <MetricCard
        label="Net PnL"
        value={money(s?.net_pnl)}
        hint="After fees"
      />
      <MetricCard
        label="Total Fees"
        value={money(s?.total_fees)}
        hint="Execution cost drag"
      />
      <MetricCard
        label="Avg Trade Score"
        value={metricNumber(s?.avg_trade_score, 2)}
        hint="Filled trade quality"
      />
      <MetricCard
        label="Avg Hold Time"
        value={minutesLabel(s?.avg_hold_minutes)}
        hint="Closed trade duration"
      />
      <MetricCard
        label="Best / Worst Symbol"
        value={`${s?.best_symbol ?? "-"} / ${s?.worst_symbol ?? "-"}`}
        hint="By net pnl"
        valueClassName="mt-4 break-words text-lg font-semibold tracking-tight text-white sm:text-xl"
      />
      <MetricCard
        label="Fee / Gross"
        value={s?.fee_to_gross_ratio != null ? ratioPercent(s.fee_to_gross_ratio * 100) : "-"}
        hint="Higher means more drag"
      />
    </div>
  );
}
