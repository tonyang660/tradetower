import { useMemo, useState } from "react";
import type { ReactNode } from "react";

type ExecutedOrderItem = {
  executionId: number;
  orderId: number | null;
  accountId: number;
  symbol: string;
  executionType: string;
  positionSide: string;
  orderType: string;
  fillPrice: number | null;
  filledSize: number | null;
  feePaid: number;
  slippageBps: number;
  executionTimestamp: string | null;
  notes: string | null;
  linkedPositionId: number | null;
  realizedPnl?: number | null;
};

const PAGE_SIZE = 20;

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `$${value.toFixed(2)}`;
}

function number(value: number | null | undefined, digits = 8) {
  if (value == null || Number.isNaN(value)) return "-";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString();
}

function executionTone(executionType: string) {
  const key = executionType.toUpperCase();
  if (key === "STOP_LOSS") return "bg-rose-500/12 text-rose-200 border border-rose-400/20";
  if (key.startsWith("TP")) return "bg-emerald-500/12 text-emerald-200 border border-emerald-400/20";
  if (key === "ENTRY") return "bg-sky-500/12 text-sky-200 border border-sky-400/20";
  return "bg-white/8 text-white/80 border border-white/10";
}

function sideTone(side: string) {
  return side.toLowerCase() === "long"
    ? "bg-emerald-500/12 text-emerald-200 border border-emerald-400/20"
    : "bg-rose-500/12 text-rose-200 border border-rose-400/20";
}

function pnlTone(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "text-white";
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-white";
}

export default function ExecutedOrdersPanel({
  items,
}: {
  items: ExecutedOrderItem[];
}) {
  const [page, setPage] = useState(0);

  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));

  const visibleItems = useMemo(() => {
    const start = page * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  }, [items, page]);

  const safePage = Math.min(page, totalPages - 1);
  if (safePage !== page) {
    setPage(safePage);
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Executed Orders</h2>
          <p className="mt-1 text-sm text-white/50">
            Filled entries and maintenance executions such as TP1, TP2, TP3, and stop-loss.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/60">
            {items.length} total
          </div>
          <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/60">
            Page {totalPages === 0 ? 0 : page + 1} / {totalPages}
          </div>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-white/10 bg-black/10 px-4 py-6 text-sm text-white/45">
          No executed orders yet.
        </div>
      ) : (
        <>
          <div className="mt-4 max-h-[720px] overflow-y-auto pr-1">
            <div className="space-y-3">
              {visibleItems.map((item) => (
                <article
                  key={item.executionId}
                  className="rounded-xl border border-white/10 bg-black/10 p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-base font-semibold text-white">{item.symbol}</div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide ${executionTone(item.executionType)}`}>
                          {item.executionType.replace("_", " ")}
                        </span>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide ${sideTone(item.positionSide)}`}>
                          {item.positionSide}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-white/70">
                          {item.orderType || "unknown"}
                        </span>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-xs text-white/45">Executed</div>
                      <div className="mt-1 text-sm text-white/85">{formatDateTime(item.executionTimestamp)}</div>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                    <Metric label="Fill Price" value={number(item.fillPrice, 8)} />
                    <Metric label="Filled Size" value={number(item.filledSize, 8)} />
                    <Metric label="Fee" value={money(item.feePaid)} />
                    <Metric
                      label="Realized PnL"
                      value={<span className={pnlTone(item.realizedPnl)}>{money(item.realizedPnl)}</span>}
                    />
                    <Metric label="Position Link" value={item.linkedPositionId != null ? String(item.linkedPositionId) : "-"} />
                  </div>

                  {item.notes ? (
                    <div className="mt-4 rounded-lg border border-white/8 bg-white/5 px-3 py-2 text-sm text-white/65">
                      {item.notes}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Previous
            </button>

            <div className="text-sm text-white/60">
              Showing {Math.min(items.length, page * PAGE_SIZE + 1)}-
              {Math.min(items.length, (page + 1) * PAGE_SIZE)} of {items.length}
            </div>

            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-white/8 bg-white/5 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-white/45">{label}</div>
      <div className="mt-1 text-sm font-medium text-white">{value}</div>
    </div>
  );
}