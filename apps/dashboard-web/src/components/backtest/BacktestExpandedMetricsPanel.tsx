import { useEffect, useState } from "react";
import { Gauge, Layers3, RefreshCcw } from "lucide-react";
import { fetchBacktestAnalytics } from "../../lib/backtestApi";
import type { BacktestAnalyticsResponse } from "../../types/backtests";

function money(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not calculated";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not calculated";
  return `${(value * 100).toFixed(2)}%`;
}

function num(value: unknown, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not calculated";
  return value.toFixed(digits);
}

function seconds(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not calculated";
  const mins = value / 60;
  if (mins < 120) return `${mins.toFixed(1)}m`;
  const hrs = mins / 60;
  if (hrs < 72) return `${hrs.toFixed(1)}h`;
  return `${(hrs / 24).toFixed(1)}d`;
}

function formatMetric(metric: any) {
  if (!metric?.available) return "Not calculated";
  if (metric.unit === "currency") return money(metric.value);
  if (metric.unit === "percent") return typeof metric.value === "number" ? `${metric.value.toFixed(2)}%` : "Not calculated";
  if (metric.unit === "ratio") return pct(metric.value);
  if (metric.unit === "seconds") return seconds(metric.value);
  if (metric.unit === "currency_per_trade") return money(metric.value);
  if (typeof metric.value === "number") return num(metric.value);
  return String(metric.value ?? "Not calculated");
}

function tone(value: unknown) {
  if (typeof value !== "number") return "text-white";
  if (value > 0) return "text-emerald-200";
  if (value < 0) return "text-rose-200";
  return "text-white";
}

function MetricCard({ metric }: { metric: any }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-white/35">{metric.name}</div>
      <div className={`mt-2 truncate text-xl font-semibold ${tone(metric.value)}`}>{formatMetric(metric)}</div>
      {!metric.available ? <div className="mt-1 text-xs text-white/30">Needs more stored data or Phase 18 lifecycle fields.</div> : null}
    </div>
  );
}

function BreakdownTable({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10">
      <div className="border-b border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white">{title}</div>
      <table className="min-w-full divide-y divide-white/10 text-sm">
        <thead className="bg-black/20 text-left text-xs uppercase tracking-[0.16em] text-white/35">
          <tr>
            <th className="px-4 py-3">Group</th>
            <th className="px-4 py-3">Trades</th>
            <th className="px-4 py-3">Net PnL</th>
            <th className="px-4 py-3">Gross PnL</th>
            <th className="px-4 py-3">Fees</th>
            <th className="px-4 py-3">Win rate</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/8 text-white/65">
          {rows.length ? rows.slice(0, 8).map((row) => (
            <tr key={row.key}>
              <td className="px-4 py-3 text-white">{row.key}</td>
              <td className="px-4 py-3">{row.trades}</td>
              <td className={`px-4 py-3 ${tone(row.net_pnl)}`}>{money(row.net_pnl)}</td>
              <td className={`px-4 py-3 ${tone(row.gross_pnl)}`}>{money(row.gross_pnl)}</td>
              <td className="px-4 py-3">{money(row.fees)}</td>
              <td className="px-4 py-3">{pct(row.win_rate)}</td>
            </tr>
          )) : (
            <tr><td className="px-4 py-6 text-center text-white/35" colSpan={6}>No breakdown data available.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function BacktestExpandedMetricsPanel({ runId }: { runId: number | null | undefined }) {
  const [data, setData] = useState<BacktestAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!runId) return;
    try {
      setLoading(true);
      setError(null);
      const payload = await fetchBacktestAnalytics(runId);
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  if (!runId) {
    return (
      <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
        <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
          <Gauge size={18} className="text-emerald-200" />
          Expanded Metrics
        </div>
        <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/40">
          Run a backtest to load expanded metrics.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <Gauge size={18} className="text-emerald-200" />
            Expanded Metrics
          </div>
          <div className="mt-1 text-sm text-white/45">Phase 17F aggregates run-level, trade-level, symbol, regime, and fee-pressure analytics.</div>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/8 px-3 py-2 text-sm text-white/70 transition hover:bg-white/12 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error ? <div className="mb-4 rounded-2xl border border-rose-300/20 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</div> : null}

      <div className="space-y-5">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          {(data?.metrics ?? []).map((metric) => <MetricCard key={metric.name} metric={metric} />)}
          {!data?.metrics?.length ? (
            <div className="col-span-full rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/40">
              {loading ? "Loading expanded metrics..." : "No expanded metrics loaded."}
            </div>
          ) : null}
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <BreakdownTable title="PnL by symbol" rows={data?.breakdowns?.symbols ?? []} />
          <BreakdownTable title="PnL by regime" rows={data?.breakdowns?.regimes ?? []} />
          <BreakdownTable title="PnL by exit reason" rows={data?.breakdowns?.exit_reasons ?? []} />
          <BreakdownTable title="Score bucket performance" rows={data?.breakdowns?.score_buckets ?? []} />
        </div>

        <div className="rounded-2xl border border-amber-300/15 bg-amber-500/8 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-100">
            <Layers3 size={15} />
            Availability notes
          </div>
          <div className="grid gap-2 text-sm text-amber-100/70 md:grid-cols-2">
            <div>Average R: {data?.availability?.average_r ? "available" : "not stored yet"}</div>
            <div>Hold time: {data?.availability?.hold_time ? "available" : "approximate or missing until Phase 18"}</div>
            <div>Sharpe / Sortino: {data?.availability?.sharpe_sortino ? "available" : "needs enough equity history"}</div>
            <div>Regime / score buckets: depends on trade debug fields being persisted.</div>
          </div>
        </div>
      </div>
    </section>
  );
}
