import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { OpenPosition } from "../../types/positionsOrders";

function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function numberText(value: number | null | undefined, digits = 8) {
  if (value == null) return "-";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function statusTone(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  if (normalized.includes("tp")) return "bg-emerald-500/12 text-emerald-200";
  if (normalized.includes("breakeven")) return "bg-amber-500/12 text-amber-200";
  if (normalized.includes("stop")) return "bg-rose-500/12 text-rose-200";
  return "bg-white/10 text-white/70";
}

function protectionChipTone(kind: "sl" | "tp1" | "tp2" | "tp3", hit?: boolean) {
  if (kind === "sl") {
    return "border-rose-400/15 bg-rose-500/10 text-rose-200";
  }

  if (hit) {
    return "border-emerald-300/25 bg-emerald-400/18 text-emerald-100";
  }

  return "border-emerald-400/15 bg-emerald-500/10 text-emerald-200";
}

function inferredStatus(position: OpenPosition) {
  if (position.tp3_hit) return "TP3 Reached";
  if (position.tp2_hit) return "TP2 Reached";
  if (position.tp1_hit) return "TP1 Reached";
  return position.status ?? "open";
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

            const displayStatus = inferredStatus(p);

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
                  <div className="mt-1 text-white">
                    {numberText(p.remaining_size ?? p.original_size ?? p.size, 8)}
                  </div>
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
                    {numberText(p.entry_price)} / {numberText(p.current_price)}
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
                  <div className={`mt-1 inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium ${statusTone(displayStatus)}`}>
                    {displayStatus}
                  </div>
                </div>

                <div>
                  <div className="text-white/40">Protection</div>

                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {p.stop_loss != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("sl")}`}
                      >
                        SL {numberText(p.stop_loss)}
                      </span>
                    ) : null}

                    {p.tp1_price != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp1", p.tp1_hit)}`}
                      >
                        TP1 {numberText(p.tp1_price)}
                      </span>
                    ) : null}

                    {p.tp2_price != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp2", p.tp2_hit)}`}
                      >
                        TP2 {numberText(p.tp2_price)}
                      </span>
                    ) : null}

                    {p.tp3_price != null ? (
                      <span
                        className={`rounded-full border px-2 py-1 text-[10px] ${protectionChipTone("tp3", p.tp3_hit)}`}
                      >
                        TP3 {numberText(p.tp3_price)}
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