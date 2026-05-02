import type { ExitOutcomesSection } from "../../types/strategyAnalytics";
import { money, pnlTone, ratioPercent } from "../../lib/strategyAnalytics";

export default function ExitOutcomePanel({
  section,
}: {
  section: ExitOutcomesSection;
}) {
  const summary = section.summary;
  const items = section.items;

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Exit Outcome Quality</h2>
        <p className="mt-1 text-sm text-white/50">
          Shows how often trades reach targets versus stopping out, and the quality of those outcomes.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MiniMetric label="Stop-Loss Rate" value={ratioPercent(summary?.stop_loss_rate)} />
        <MiniMetric label="TP1 Rate" value={ratioPercent(summary?.tp1_rate)} />
        <MiniMetric label="TP2 Rate" value={ratioPercent(summary?.tp2_rate)} />
        <MiniMetric label="TP3 Rate" value={ratioPercent(summary?.tp3_rate)} />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-white/45">
            <tr className="border-b border-white/10">
              <th className="px-3 py-3 font-medium">Exit Type</th>
              <th className="px-3 py-3 font-medium">Executions</th>
              <th className="px-3 py-3 font-medium">Avg Realized PnL</th>
              <th className="px-3 py-3 font-medium">Total Realized PnL</th>
              <th className="px-3 py-3 font-medium">Fees</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-5 text-white/45">
                  No exit outcome data yet.
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.exit_type} className="border-b border-white/5 last:border-b-0">
                  <td className="px-3 py-3 text-white">{row.exit_type.replace("_", " ")}</td>
                  <td className="px-3 py-3 text-white">{row.executions}</td>
                  <td className={`px-3 py-3 ${pnlTone(row.avg_realized_pnl)}`}>
                    {row.avg_realized_pnl != null ? money(row.avg_realized_pnl) : "-"}
                  </td>
                  <td className={`px-3 py-3 ${pnlTone(row.total_realized_pnl)}`}>
                    {money(row.total_realized_pnl)}
                  </td>
                  <td className="px-3 py-3 text-white">{money(row.total_fees)}</td>
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