import { useMemo, useState } from "react";
import type { SymbolAnalyticsRow } from "../../types/strategyAnalytics";
import {
  money,
  minutesLabel,
  pnlTone,
  ratioPercent,
  ratioTone,
} from "../../lib/strategyAnalytics";

type SortKey =
  | "symbol"
  | "trades"
  | "gross_pnl"
  | "net_pnl"
  | "total_fees"
  | "win_rate"
  | "expectancy"
  | "avg_hold_minutes"
  | "stop_out_rate"
  | "tp1_rate"
  | "tp2_rate"
  | "tp3_rate"
  | "fee_to_gross_ratio";

export default function SymbolEdgeTable({
  items,
}: {
  items: SymbolAnalyticsRow[];
}) {
  const [sortKey, setSortKey] = useState<SortKey>("net_pnl");
  const [descending, setDescending] = useState(true);

  const sorted = useMemo(() => {
    const rows = [...items];

    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];

      if (typeof av === "string" && typeof bv === "string") {
        return av.localeCompare(bv);
      }

      return Number(av ?? -Infinity) - Number(bv ?? -Infinity);
    });

    return descending ? rows.reverse() : rows;
  }, [items, sortKey, descending]);

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setDescending((prev) => !prev);
      return;
    }
    setSortKey(nextKey);
    setDescending(nextKey !== "symbol");
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Symbol Edge Table</h2>
        <p className="mt-1 text-sm text-white/50">
          Identifies which symbols create real net edge and which ones mainly generate churn.
        </p>
      </div>

      {sorted.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 bg-black/10 px-4 py-6 text-sm text-white/45">
          No symbol analytics available yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-white/45">
              <tr className="border-b border-white/10">
                <HeaderCell label="Symbol" onClick={() => toggleSort("symbol")} />
                <HeaderCell label="Trades" onClick={() => toggleSort("trades")} />
                <HeaderCell label="Win Rate" onClick={() => toggleSort("win_rate")} />
                <HeaderCell label="Gross" onClick={() => toggleSort("gross_pnl")} />
                <HeaderCell label="Net" onClick={() => toggleSort("net_pnl")} />
                <HeaderCell label="Fees" onClick={() => toggleSort("total_fees")} />
                <HeaderCell label="Expectancy" onClick={() => toggleSort("expectancy")} />
                <HeaderCell label="Avg Hold" onClick={() => toggleSort("avg_hold_minutes")} />
                <HeaderCell label="Stop %" onClick={() => toggleSort("stop_out_rate")} />
                <HeaderCell label="TP1 %" onClick={() => toggleSort("tp1_rate")} />
                <HeaderCell label="TP2 %" onClick={() => toggleSort("tp2_rate")} />
                <HeaderCell label="TP3 %" onClick={() => toggleSort("tp3_rate")} />
                <HeaderCell label="Fee / Gross" onClick={() => toggleSort("fee_to_gross_ratio")} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.symbol} className="border-b border-white/5 last:border-b-0">
                  <BodyCell className="font-medium">{row.symbol}</BodyCell>
                  <BodyCell>{row.trades}</BodyCell>
                  <BodyCell>{ratioPercent(row.win_rate)}</BodyCell>
                  <BodyCell className={pnlTone(row.gross_pnl)}>{money(row.gross_pnl)}</BodyCell>
                  <BodyCell className={pnlTone(row.net_pnl)}>{money(row.net_pnl)}</BodyCell>
                  <BodyCell>{money(row.total_fees)}</BodyCell>
                  <BodyCell className={pnlTone(row.expectancy)}>{money(row.expectancy)}</BodyCell>
                  <BodyCell>{minutesLabel(row.avg_hold_minutes)}</BodyCell>
                  <BodyCell>{ratioPercent(row.stop_out_rate)}</BodyCell>
                  <BodyCell>{ratioPercent(row.tp1_rate)}</BodyCell>
                  <BodyCell>{ratioPercent(row.tp2_rate)}</BodyCell>
                  <BodyCell>{ratioPercent(row.tp3_rate)}</BodyCell>
                  <BodyCell className={ratioTone(row.fee_to_gross_ratio)}>
                    {row.fee_to_gross_ratio != null
                      ? ratioPercent(row.fee_to_gross_ratio * 100)
                      : "-"}
                  </BodyCell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function HeaderCell({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <th className="px-3 py-3 font-medium">
      <button type="button" onClick={onClick} className="transition hover:text-white">
        {label}
      </button>
    </th>
  );
}

function BodyCell({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-3 text-white ${className}`}>{children}</td>;
}