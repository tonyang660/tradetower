import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { RecentClosedPosition } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function numberText(value: number | null | undefined, digits = 8) {
  if (value == null) return "-";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function pnlTone(value: number) {
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-white";
}

function resultTone(value: string) {
  if (value === "WIN") return "bg-emerald-500/12 text-emerald-200";
  if (value === "LOSS") return "bg-rose-500/12 text-rose-200";
  return "bg-white/10 text-white/70";
}

export default function RecentClosedPositionsPanel({
  positions,
}: {
  positions: RecentClosedPosition[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Recent Closed Positions" subtitle="Recently completed trades and realized outcomes" />

      {positions.length === 0 ? (
        <div className="mt-3 rounded-[24px] border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          No closed positions yet. Completed trades will appear here once exits finalize.
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {positions.map((trade) => (
            <div
              key={trade.trade_id}
              className="grid gap-3 rounded-[24px] border border-white/8 bg-white/5 p-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[0.9fr_0.7fr_0.78fr_0.78fr_0.72fr_0.72fr_0.78fr_0.72fr_0.9fr]"
            >
              <div>
                <div className="font-semibold text-white">{trade.symbol}</div>
                <div className="mt-1 inline-flex rounded-full px-2 py-1 text-[11px] bg-white/10 text-white/70">
                  {trade.direction}
                </div>
              </div>

              <div>
                <div className="text-white/40">Entry</div>
                <div className="mt-1 text-white">{numberText(trade.entry_price)}</div>
              </div>

              <div>
                <div className="text-white/40">Exit</div>
                <div className="mt-1 text-white">{numberText(trade.exit_price)}</div>
              </div>

              <div>
                <div className="text-white/40">Size</div>
                <div className="mt-1 text-white">{numberText(trade.size)}</div>
              </div>

              <div>
                <div className="text-white/40">Leverage</div>
                <div className="mt-1 text-white">{trade.leverage ?? "-"}</div>
              </div>

              <div>
                <div className="text-white/40">Notional</div>
                <div className="mt-1 text-white">{money(trade.notional)}</div>
              </div>

              <div>
                <div className="text-white/40">PnL</div>
                <div className={`mt-1 font-semibold ${pnlTone(trade.realized_pnl)}`}>
                  {money(trade.realized_pnl)}
                </div>
                <div className="mt-1 text-[11px] text-white/35">
                  {trade.pnl_pct.toFixed(2)}%
                </div>
              </div>

              <div>
                <div className="text-white/40">Fees</div>
                <div className="mt-1 text-white">{money(trade.fees_paid)}</div>
              </div>

              <div>
                <div className="text-white/40">Result</div>
                <div className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${resultTone(trade.win_loss)}`}>
                  {trade.win_loss}
                </div>
                <div className="mt-2 text-[11px] text-white/30">
                  {trade.closed_at ? new Date(trade.closed_at).toLocaleString() : "-"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}