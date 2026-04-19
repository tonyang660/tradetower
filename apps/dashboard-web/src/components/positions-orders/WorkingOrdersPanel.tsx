import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { WorkingOrder } from "../../types/positionsOrders";

function statusTone(status: string) {
  if (status === "PENDING_ENTRY" || status === "RESTING") {
    return "bg-amber-500/12 text-amber-200";
  }
  if (status === "CANCELLED") {
    return "bg-white/10 text-white/65";
  }
  if (status === "REJECTED") {
    return "bg-rose-500/12 text-rose-200";
  }
  return "bg-white/10 text-white/70";
}

export default function WorkingOrdersPanel({
  orders,
}: {
  orders: WorkingOrder[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Working Orders" subtitle="Pending entries, targets, and stop protection" />

      {orders.length === 0 ? (
        <div className="mt-3 rounded-[24px] border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          No working orders. Resting entries, linked stops, and targets will appear here.
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {orders.map((order) => (
            <div
              key={order.order_id}
              className="grid gap-3 rounded-[24px] border border-white/8 bg-white/5 p-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[0.9fr_0.8fr_0.9fr_0.9fr_1.25fr_0.9fr_1fr]"
            >
              <div>
                <div className="font-semibold text-white">{order.symbol}</div>
                <div
                  className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${
                    order.side === "long"
                      ? "bg-emerald-500/12 text-emerald-200"
                      : "bg-rose-500/12 text-rose-200"
                  }`}
                >
                  {order.side}
                </div>
              </div>

              <div>
                <div className="text-white/40">Type</div>
                <div className="mt-1 text-white">{order.order_type}</div>
              </div>

              <div>
                <div className="text-white/40">Entry</div>
                <div className="mt-1 text-white">{order.entry_price ?? "-"}</div>
              </div>

              <div>
                <div className="text-white/40">Stop Loss</div>
                <div className="mt-1 text-rose-200">{order.stop_loss ?? "-"}</div>
              </div>

              <div>
                <div className="text-white/40">Take Profit Targets</div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {order.tp1 !== undefined ? (
                    <span className="rounded-full border border-emerald-400/15 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200">
                      TP1 {order.tp1}
                    </span>
                  ) : null}
                  {order.tp2 !== undefined ? (
                    <span className="rounded-full border border-emerald-400/15 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200">
                      TP2 {order.tp2}
                    </span>
                  ) : null}
                  {order.tp3 !== undefined ? (
                    <span className="rounded-full border border-emerald-400/15 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200">
                      TP3 {order.tp3}
                    </span>
                  ) : null}
                </div>
              </div>

              <div>
                <div className="text-white/40">Status</div>
                <div className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] ${statusTone(order.status)}`}>
                  {order.status}
                </div>
              </div>

              <div>
                <div className="text-white/40">Submitted</div>
                <div className="mt-1 text-white">
                  {order.submitted_at ? new Date(order.submitted_at).toLocaleString() : "-"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}