import type { FeePressureSection } from "../../types/strategyAnalytics";
import { money, ratioPercent, ratioTone, pnlTone } from "../../lib/strategyAnalytics";

export default function FeePressurePanel({
  section,
}: {
  section: FeePressureSection;
}) {
  const summary = section.summary;
  const items = section.items;

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Fee Pressure Analytics</h2>
        <p className="mt-1 text-sm text-white/50">
          Exposes where execution cost is destroying otherwise usable edge.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MiniMetric label="Total Fees" value={money(summary?.total_fees)} />
        <MiniMetric
          label="Fee / Gross"
          value={
            summary?.fee_to_gross_ratio != null
              ? ratioPercent(summary.fee_to_gross_ratio * 100)
              : "-"
          }
          tone={ratioTone(summary?.fee_to_gross_ratio)}
        />
        <MiniMetric label="Avg Fees / Trade" value={money(summary?.avg_fees_per_trade)} />
        <MiniMetric label="Worst Fee Symbol" value={summary?.worst_fee_symbol ?? "-"} />
        <MiniMetric
          label="Best Fee Efficiency"
          value={summary?.best_fee_efficiency_symbol ?? "-"}
        />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-white/45">
            <tr className="border-b border-white/10">
              <th className="px-3 py-3 font-medium">Symbol</th>
              <th className="px-3 py-3 font-medium">Gross PnL</th>
              <th className="px-3 py-3 font-medium">Fees</th>
              <th className="px-3 py-3 font-medium">Net PnL</th>
              <th className="px-3 py-3 font-medium">Avg Fees / Trade</th>
              <th className="px-3 py-3 font-medium">Fee / Gross</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-5 text-white/45">
                  No fee pressure data yet.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.symbol} className="border-b border-white/5 last:border-b-0">
                  <td className="px-3 py-3 text-white">{row.symbol}</td>
                  <td className={`px-3 py-3 ${pnlTone(row.gross_pnl)}`}>{money(row.gross_pnl)}</td>
                  <td className="px-3 py-3 text-white">{money(row.total_fees)}</td>
                  <td className={`px-3 py-3 ${pnlTone(row.net_pnl)}`}>{money(row.net_pnl)}</td>
                  <td className="px-3 py-3 text-white">{money(row.avg_fees_per_trade)}</td>
                  <td className={`px-3 py-3 ${ratioTone(row.fee_to_gross_ratio)}`}>
                    {row.fee_to_gross_ratio != null
                      ? ratioPercent(row.fee_to_gross_ratio * 100)
                      : "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MiniMetric({
  label,
  value,
  tone = "text-white",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/10 px-3 py-3">
      <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
      <div className={`mt-1 text-sm font-medium ${tone}`}>{value}</div>
    </div>
  );
}