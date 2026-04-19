import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { RecentClosedPosition } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function RecentClosedPositionsPanel({
  positions,
}: {
  positions: RecentClosedPosition[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Recent Closed Positions" subtitle="Execution-focused trade history" />

      {positions.length === 0 ? (
        <div className="mt-3 rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          No recently closed positions. Realized trade history will populate after exits.
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {positions.map((p, index) => (
            <div
              key={p.trade_id}
              className={`grid gap-3 rounded-[24px] border p-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[0.8fr_0.7fr_0.7fr_0.9fr_0.9fr_0.8fr_0.8fr_1fr] ${
                index === 0 ? "border-violet-300/12 bg-white/6" : "border-white/8 bg-white/5"
              }`}
            >
              <div>
                <div className="font-semibold text-white">{p.symbol}</div>
                <div
                  className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${
                    p.direction === "long"
                      ? "bg-emerald-500/12 text-emerald-200"
                      : "bg-rose-500/12 text-rose-200"
                  }`}
                >
                  {p.direction}
                </div>
                {index === 0 ? (
                  <div className="mt-2 inline-flex rounded-full border border-violet-300/15 bg-violet-500/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-violet-200">
                    Latest
                  </div>
                ) : null}
              </div>

              <div>
                <div className="text-white/40">Leverage</div>
                <div className="mt-1 text-white">{p.leverage ?? "-"}</div>
              </div>

              <div>
                <div className="text-white/40">Size</div>
                <div className="mt-1 text-white">{p.size ?? "-"}</div>
              </div>

              <div>
                <div className="text-white/40">Notional</div>
                <div className="mt-1 text-white">{money(p.notional)}</div>
              </div>

              <div>
                <div className="text-white/40">Realized PnL</div>
                <div
                  className={`mt-1 font-medium ${
                    p.realized_pnl > 0
                      ? "text-emerald-300"
                      : p.realized_pnl < 0
                      ? "text-rose-300"
                      : "text-white"
                  }`}
                >
                  {money(p.realized_pnl)} · {p.pnl_pct.toFixed(2)}%
                </div>
              </div>

              <div>
                <div className="text-white/40">Fees</div>
                <div className="mt-1 text-white">{money(p.fees_paid)}</div>
              </div>

              <div>
                <div className="text-white/40">Result</div>
                <div
                  className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${
                    p.win_loss === "WIN"
                      ? "bg-emerald-500/12 text-emerald-200"
                      : p.win_loss === "LOSS"
                      ? "bg-rose-500/12 text-rose-200"
                      : "bg-white/10 text-white/70"
                  }`}
                >
                  {p.win_loss}
                </div>
              </div>

              <div>
                <div className="text-white/40">Closed</div>
                <div className="mt-1 text-white">
                  {p.closed_at ? new Date(p.closed_at).toLocaleString() : "-"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}