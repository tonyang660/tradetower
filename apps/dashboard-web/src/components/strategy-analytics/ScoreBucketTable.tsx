import { useMemo, useState } from "react";
import type { ScoreBucketRow } from "../../types/strategyAnalytics";
import { money, metricNumber, minutesLabel, pnlTone } from "../../lib/strategyAnalytics";

type SortKey =
  | "bucket_label"
  | "trades"
  | "gross_pnl"
  | "net_pnl"
  | "total_fees"
  | "win_rate"
  | "expectancy"
  | "avg_hold_minutes";

export default function ScoreBucketTable({
  items,
}: {
  items: ScoreBucketRow[];
}) {
  const [sortKey, setSortKey] = useState<SortKey>("bucket_label");
  const [descending, setDescending] = useState(false);

  const sorted = useMemo(() => {
    const rows = [...items];

    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];

      if (typeof av === "string" && typeof bv === "string") {
        return av.localeCompare(bv);
      }

      return Number(av) - Number(bv);
    });

    return descending ? rows.reverse() : rows;
  }, [items, sortKey, descending]);

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setDescending((prev) => !prev);
      return;
    }
    setSortKey(nextKey);
    setDescending(nextKey !== "bucket_label");
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Score Bucket Analysis</h2>
        <p className="mt-1 text-sm text-white/50">
          Measures whether higher candidate scores actually correspond to better outcomes.
        </p>
      </div>

      {sorted.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 bg-black/10 px-4 py-6 text-sm text-white/45">
          No closed trades available for score-bucket analysis yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-white/45">
              <tr className="border-b border-white/10">
                <HeaderCell label="Bucket" onClick={() => toggleSort("bucket_label")} />
                <HeaderCell label="Trades" onClick={() => toggleSort("trades")} />
                <HeaderCell label="Win Rate" onClick={() => toggleSort("win_rate")} />
                <HeaderCell label="Gross PnL" onClick={() => toggleSort("gross_pnl")} />
                <HeaderCell label="Net PnL" onClick={() => toggleSort("net_pnl")} />
                <HeaderCell label="Fees" onClick={() => toggleSort("total_fees")} />
                <HeaderCell label="Expectancy" onClick={() => toggleSort("expectancy")} />
                <HeaderCell label="Avg Hold" onClick={() => toggleSort("avg_hold_minutes")} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.bucket_label} className="border-b border-white/5 last:border-b-0">
                  <BodyCell>{row.bucket_label}</BodyCell>
                  <BodyCell>{row.trades}</BodyCell>
                  <BodyCell>{metricNumber(row.win_rate, 2)}%</BodyCell>
                  <BodyCell className={pnlTone(row.gross_pnl)}>{money(row.gross_pnl)}</BodyCell>
                  <BodyCell className={pnlTone(row.net_pnl)}>{money(row.net_pnl)}</BodyCell>
                  <BodyCell>{money(row.total_fees)}</BodyCell>
                  <BodyCell className={pnlTone(row.expectancy)}>{money(row.expectancy)}</BodyCell>
                  <BodyCell>{minutesLabel(row.avg_hold_minutes)}</BodyCell>
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