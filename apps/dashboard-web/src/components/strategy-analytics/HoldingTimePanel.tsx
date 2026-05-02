import type { HoldingTimesSection } from "../../types/strategyAnalytics";
import { money, minutesLabel, pnlTone } from "../../lib/strategyAnalytics";

export default function HoldingTimePanel({
  section,
}: {
  section: HoldingTimesSection;
}) {
  const summary = section.summary;
  const items = section.items;

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Holding Time Analytics</h2>
        <p className="mt-1 text-sm text-white/50">
          Helps diagnose whether trades are stopping too fast or failing to follow through.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <MiniMetric label="Avg Hold" value={minutesLabel(summary?.avg_hold_minutes)} />
        <MiniMetric label="Median Hold" value={minutesLabel(summary?.median_hold_minutes)} />
        <MiniMetric label="Avg Winner Hold" value={minutesLabel(summary?.avg_winner_hold_minutes)} />
        <MiniMetric label="Avg Loser Hold" value={minutesLabel(summary?.avg_loser_hold_minutes)} />
        <MiniMetric label="Immediate Stop-Outs" value={String(summary?.immediate_stopouts_count ?? 0)} />
        <MiniMetric label="Fast Winners" value={String(summary?.fast_winners_count ?? 0)} />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-white/45">
            <tr className="border-b border-white/10">
              <th className="px-3 py-3 font-medium">Bucket</th>
              <th className="px-3 py-3 font-medium">Trades</th>
              <th className="px-3 py-3 font-medium">Winners</th>
              <th className="px-3 py-3 font-medium">Losers</th>
              <th className="px-3 py-3 font-medium">Gross PnL</th>
              <th className="px-3 py-3 font-medium">Net PnL</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-5 text-white/45">
                  No holding-time data yet.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.bucket_label} className="border-b border-white/5 last:border-b-0">
                  <td className="px-3 py-3 text-white">{row.bucket_label}</td>
                  <td className="px-3 py-3 text-white">{row.trades}</td>
                  <td className="px-3 py-3 text-white">{row.winners}</td>
                  <td className="px-3 py-3 text-white">{row.losers}</td>
                  <td className={`px-3 py-3 ${pnlTone(row.gross_pnl)}`}>{money(row.gross_pnl)}</td>
                  <td className={`px-3 py-3 ${pnlTone(row.net_pnl)}`}>{money(row.net_pnl)}</td>
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
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/10 px-3 py-3">
      <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
      <div className="mt-1 text-sm font-medium text-white">{value}</div>
    </div>
  );
}