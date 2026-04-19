import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { OpenPosition } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function OpenPositionsPanel({
  positions,
}: {
  positions: (OpenPosition & { pnl_pct_on_margin?: number })[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Open Positions" subtitle="Live position blotter and margin state" />

      {positions.length === 0 ? (
        <div className="mt-3 rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          No open positions. Live exposure will appear here once entries are filled.
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {positions.map((p, index) => {
            const pnl = p.unrealized_pnl ?? 0;
            const pnlTone =
              pnl > 0 ? "text-emerald-300" : pnl < 0 ? "text-rose-300" : "text-white";

            return (
              <div
                key={`${p.symbol}-${p.position_id ?? index}`}
                className="grid gap-3 rounded-[24px] border border-white/8 bg-white/5 p-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[0.8fr_0.7fr_0.8fr_0.7fr_0.9fr_0.9fr_1fr_0.8fr_1fr]"
              >
                <div>
                  <div className="font-semibold text-white">{p.symbol}</div>
                  <div
                    className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${
                      p.side === "long"
                        ? "bg-emerald-500/12 text-emerald-200"
                        : "bg-rose-500/12 text-rose-200"
                    }`}
                  >
                    {p.side}
                  </div>
                </div>

                <div>
                  <div className="text-white/40">Size</div>
                  <div className="mt-1 text-white">{p.remaining_size ?? p.original_size ?? "-"}</div>
                </div>

                <div>
                  <div className="text-white/40">Leverage</div>
                  <div className="mt-1 text-white">{p.leverage ?? "-"}</div>
                </div>

                <div>
                  <div className="text-white/40">Margin</div>
                  <div className="mt-1 text-white">{money(p.margin_used)}</div>
                </div>

                <div>
                  <div className="text-white/40">Notional</div>
                  <div className="mt-1 text-white">{money(p.notional)}</div>
                </div>

                <div>
                  <div className="text-white/40">Entry / Current</div>
                  <div className="mt-1 text-white">
                    {p.entry_price ?? "-"} / {p.current_price ?? "-"}
                  </div>
                </div>

                <div>
                  <div className="text-white/40">PnL / Margin %</div>
                  <div className={`mt-1 font-medium ${pnlTone}`}>
                    {money(p.unrealized_pnl)} · {(p.pnl_pct_on_margin ?? 0).toFixed(2)}%
                  </div>
                </div>

                <div>
                  <div className="text-white/40">Fees</div>
                  <div className="mt-1 text-white">{money(p.fees_paid)}</div>
                </div>

                <div>
                  <div className="text-white/40">Status</div>
                  <div className="mt-1 text-white">{p.status ?? "OPEN"}</div>
                  <div className="mt-1 text-xs text-white/35">
                    {p.opened_at ? new Date(p.opened_at).toLocaleString() : "-"}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}