import ChartCard from "./ChartCard";
import type { DirectionalBreakdown } from "../../types/performance";
import { money, metricNumber } from "../../lib/performance";

export default function DirectionalBreakdownPanel({
  breakdown,
}: {
  breakdown: DirectionalBreakdown | null;
}) {
  const longSide = breakdown?.long;
  const shortSide = breakdown?.short;

  return (
    <ChartCard title="Directional Bias" subtitle="Long versus short contribution and edge">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-[24px] border border-emerald-400/10 bg-emerald-500/5 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-emerald-200/80">Long</div>
          <div className="mt-3 space-y-2 text-sm text-white/65">
            <div className="flex justify-between"><span>Trades</span><span className="text-white">{longSide?.trades ?? 0}</span></div>
            <div className="flex justify-between"><span>PnL</span><span className="text-emerald-300">{money(longSide?.pnl)}</span></div>
            <div className="flex justify-between"><span>Win Rate</span><span className="text-white">{metricNumber(longSide?.win_rate, 2)}%</span></div>
            <div className="flex justify-between"><span>Expectancy</span><span className="text-white">{money(longSide?.expectancy)}</span></div>
          </div>
        </div>

        <div className="rounded-[24px] border border-rose-400/10 bg-rose-500/5 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-rose-200/80">Short</div>
          <div className="mt-3 space-y-2 text-sm text-white/65">
            <div className="flex justify-between"><span>Trades</span><span className="text-white">{shortSide?.trades ?? 0}</span></div>
            <div className="flex justify-between"><span>PnL</span><span className="text-rose-300">{money(shortSide?.pnl)}</span></div>
            <div className="flex justify-between"><span>Win Rate</span><span className="text-white">{metricNumber(shortSide?.win_rate, 2)}%</span></div>
            <div className="flex justify-between"><span>Expectancy</span><span className="text-white">{money(shortSide?.expectancy)}</span></div>
          </div>
        </div>
      </div>
    </ChartCard>
  );
}