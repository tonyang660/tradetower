import MetricCard from "../ui/MetricCard";
import type { PositionsAnalytics } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function PositionAnalyticsStrip({
  analytics,
}: {
  analytics: PositionsAnalytics;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
      <MetricCard
        label="Open Positions"
        value={String(analytics.open_positions)}
        hint="Currently active exposure"
      />
      <MetricCard
        label="Total Notional"
        value={money(analytics.total_notional)}
        hint="Gross market exposure"
      />
      <MetricCard
        label="Used Margin"
        value={money(analytics.total_margin_used)}
        hint="Estimated capital engaged"
      />
      <MetricCard
        label="Net Open PnL"
        value={`${money(analytics.total_open_pnl)} · ${analytics.total_open_pnl_pct_on_margin.toFixed(2)}%`}
        hint="Relative to used margin"
      />
      <MetricCard
        label="Long / Short"
        value={`${analytics.long_exposure_pct.toFixed(0)}% / ${analytics.short_exposure_pct.toFixed(0)}%`}
        hint="Exposure split"
      />
      <MetricCard
        label="Biggest Winner / Loser"
        value={`${analytics.biggest_winner_symbol ?? "-"} / ${analytics.biggest_loser_symbol ?? "-"}`}
        hint="Current symbol leaders"
      />
    </div>
  );
}