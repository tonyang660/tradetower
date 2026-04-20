import MetricCard from "../ui/MetricCard";
import type { PerformanceSummary } from "../../types/performance";
import { money, metricNumber } from "../../lib/performance";

export default function PerformanceSummaryStrip({
  summary,
}: {
  summary: PerformanceSummary | null;
}) {
  const s = summary;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-8">
      <MetricCard label="Gross PnL" value={money(s?.gross_pnl)} hint="Winning pnl before fees" />
      <MetricCard label="Net PnL" value={money(s?.net_pnl)} hint="After losses and fees" />
      <MetricCard label="Fees Paid" value={money(s?.total_fees_paid)} hint="Cumulative execution costs" />
      <MetricCard
        label="Max Drawdown"
        value={`${money(s?.max_drawdown_value)} · ${metricNumber(s?.max_drawdown_pct, 2)}%`}
        hint="Peak-to-trough pain"
      />
      <MetricCard label="Total Trades" value={String(s?.total_trades ?? 0)} hint="Closed trades" />
      <MetricCard label="Win Rate" value={`${metricNumber(s?.win_rate, 2)}%`} hint="Winning trade frequency" />
      <MetricCard label="Expectancy" value={money(s?.expectancy)} hint="Average pnl per trade" />
      <MetricCard label="Sharpe Ratio" value={metricNumber(s?.sharpe_ratio, 2)} hint="Trade-level return quality" />
    </div>
  );
}