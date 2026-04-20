import ChartCard from "./ChartCard";
import type { PerformanceSummary } from "../../types/performance";
import { money, metricNumber } from "../../lib/performance";

export default function TradeQualityPanel({
  summary,
}: {
  summary: PerformanceSummary | null;
}) {
  return (
    <ChartCard title="Trade Quality" subtitle="Edge, payoff quality, and statistical structure">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Average Win</div>
          <div className="mt-1 text-lg font-semibold text-emerald-300">{money(summary?.average_win)}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Average Loss</div>
          <div className="mt-1 text-lg font-semibold text-rose-300">{money(summary?.average_loss)}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Profit Factor</div>
          <div className="mt-1 text-lg font-semibold text-white">{metricNumber(summary?.profit_factor, 2)}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Average R:R</div>
          <div className="mt-1 text-lg font-semibold text-white">{metricNumber(summary?.average_rr, 2)}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Best Trade</div>
          <div className="mt-1 text-lg font-semibold text-emerald-300">{money(summary?.best_trade)}</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-sm text-white/40">Worst Trade</div>
          <div className="mt-1 text-lg font-semibold text-rose-300">{money(summary?.worst_trade)}</div>
        </div>
      </div>
    </ChartCard>
  );
}