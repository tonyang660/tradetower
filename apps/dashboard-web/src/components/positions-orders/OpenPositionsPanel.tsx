import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { OpenPosition } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function statusTone(status?: string | null) {
  if (!status) return "bg-white/10 text-white/70";
  if (status.includes("TP")) return "bg-emerald-500/12 text-emerald-200";
  if (status.includes("BREAKEVEN")) return "bg-amber-500/12 text-amber-200";
  return "bg-white/10 text-white/70";
}

function protectionChipTone(
  kind: "sl" | "tp1" | "tp2" | "tp3",
  status?: string | null
) {
  const normalized = status ?? "";

  if (kind === "sl") {
    if (normalized.includes("BREAKEVEN")) {
      return "border-amber-400/15 bg-amber-500/10 text-amber-200";
    }
    return "border-rose-400/15 bg-rose-500/10 text-rose-200";
  }

  if (kind === "tp1" && normalized.includes("TP1")) {
    return "border-emerald-300/25 bg-emerald-400/18 text-emerald-100";
  }
  if (kind === "tp2" && normalized.includes("TP2")) {
    return "border-emerald-300/25 bg-emerald-400/18 text-emerald-100";
  }
  if (kind === "tp3" && normalized.includes("TP3")) {
    return "border-emerald-300/25 bg-emerald-400/18 text-emerald-100";
  }

  return "border-emerald-400/15 bg-emerald-500/10 text-emerald-200";
}

export default function OpenPositionsPanel({
  positions,
}: {
  positions: (OpenPosition & { pnl_pct_on_margin?: number })[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Open Positions" subtitle="Live position blotter, protection, and margin state" />

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
                className="grid gap-3 rounded-[24px] border border-white/8 bg-white/5 px-5 py-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[0.82fr_0.58fr_0.58fr_0.72fr_0.82fr_0.92fr_1fr_0.72fr_0.88fr_1.5fr]"
              >
                <div>
                  <div className="text-[1.05rem] font-semibold tracking-tight text-white">{p.symbol}</div>
                  <div
                    className={`mt-1 inline-flex rounded-full px-2 py-1 text-[10px] ${
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
                  <div className={`mt-1 text-[1.02rem] font-semibold tracking-tight ${pnlTone}`}>
                    {money(p.unrealized_pnl)} · {(p.pnl_pct_on_margin ?? 0).toFixed(2)}%
                  </div>
                </div>

                <div>
                  <div className="text-white/40">Fees</div>
                  <div className="mt-1 text-white">{money(p.fees_paid)}</div>
                </div>

                <div>
                  <div className="text-white/40">Status</div>
                  <div className={`mt-1 inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium ${statusTone(p.status)}`}>
                    {p.status ?? "OPEN"}
                  </div>
                </div>

                
                <div>
                  <div className="text-white/40">Protection</div>

                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {p.stop_loss != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("sl", p.status)}`}
                      >
                        SL {p.stop_loss}
                      </span>
                    ) : null}

                    {p.tp1 != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp1", p.status)}`}
                      >
                        TP1 {p.tp1}
                      </span>
                    ) : null}

                    {p.tp2 != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp2", p.status)}`}
                      >
                        TP2 {p.tp2}
                      </span>
                    ) : null}

                    {p.tp3 != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp3", p.status)}`}
                      >
                        TP3 {p.tp3}
                      </span>
                    ) : null}
                  </div>

                  <div className="mt-2 text-[11px] text-white/30">
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