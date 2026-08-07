import { useEffect, useMemo, useState } from "react";
import { Activity, BarChart3, RefreshCcw, TrendingDown } from "lucide-react";
import { fetchBacktestCharts } from "../../lib/backtestApi";
import type { BacktestChartDataResponse } from "../../types/backtests";

type Point = { [key: string]: any };

function money(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function signedMoney(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${money(value)}`;
}

function pct(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function extent(values: number[]) {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return [0, 1];
  const min = Math.min(...valid);
  const max = Math.max(...valid);
  if (min === max) return [min - 1, max + 1];
  return [min, max];
}

function Sparkline({ rows, valueKey, height = 180 }: { rows: Point[]; valueKey: string; height?: number }) {
  const width = 680;
  const padding = 18;
  const values = rows.map((row) => Number(row[valueKey])).filter((value) => Number.isFinite(value));
  const [min, max] = extent(values);
  const points = rows.map((row, index) => {
    const x = padding + (rows.length <= 1 ? 0 : (index / (rows.length - 1)) * (width - padding * 2));
    const value = Number(row[valueKey]);
    const y = padding + ((max - value) / (max - min)) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-48 w-full overflow-visible">
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="currentColor" className="text-white/10" />
      <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="currentColor" className="text-white/10" />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.5" className="text-cyan-200" />
      {rows.length ? (
        <>
          <circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="4" className="fill-cyan-200" />
          <text x={padding} y={padding - 4} className="fill-white/45 text-xs">{max.toFixed(2)}</text>
          <text x={padding} y={height - 4} className="fill-white/45 text-xs">{min.toFixed(2)}</text>
        </>
      ) : null}
    </svg>
  );
}

function BarChart({ rows, valueKey, labelKey = "key", valueFormatter = money }: { rows: Point[]; valueKey: string; labelKey?: string; valueFormatter?: (value: unknown) => string }) {
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(Number(row[valueKey]) || 0)));
  return (
    <div className="space-y-2">
      {rows.length ? rows.slice(0, 10).map((row) => {
        const value = Number(row[valueKey]) || 0;
        const width = Math.max(3, Math.abs(value) / maxAbs * 100);
        return (
          <div key={String(row[labelKey])} className="grid grid-cols-[120px_1fr_90px] items-center gap-3 text-sm">
            <div className="truncate text-white/60">{String(row[labelKey])}</div>
            <div className="h-3 rounded-full bg-white/10">
              <div className={`h-3 rounded-full ${value >= 0 ? "bg-emerald-300/70" : "bg-rose-300/70"}`} style={{ width: `${width}%` }} />
            </div>
            <div className={value >= 0 ? "text-emerald-200" : "text-rose-200"}>{valueFormatter(value)}</div>
          </div>
        );
      }) : <div className="rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/35">No data available.</div>}
    </div>
  );
}

function ChartCard({ title, subtitle, icon, children }: { title: string; subtitle?: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">{icon}{title}</div>
          {subtitle ? <div className="mt-1 text-xs text-white/40">{subtitle}</div> : null}
        </div>
      </div>
      {children}
    </div>
  );
}

export default function BacktestChartsPanel({ runId }: { runId: number | null | undefined }) {
  const [data, setData] = useState<BacktestChartDataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!runId) return;
    try {
      setLoading(true);
      setError(null);
      const payload = await fetchBacktestCharts(runId);
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load chart data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const charts = data?.charts;
  const equityMetadata = data?.equity_metadata;

  const equityRows = charts?.equity_curve ?? [];
  const drawdownRows = charts?.drawdown_curve ?? [];

  const monthlyRows = useMemo(() => {
    return (charts?.monthly_returns ?? []).map((row) => ({ ...row, key: row.month, value: row.return_pct }));
  }, [charts]);

  if (!runId) {
    return (
      <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
        <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
          <BarChart3 size={18} className="text-cyan-200" />
          Charts
        </div>
        <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/40">
          Run a backtest to load charts.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <BarChart3 size={18} className="text-cyan-200" />
            Charts
          </div>
          <div className="mt-1 text-sm text-white/45">Equity, drawdown, returns, symbol/regime performance, and exit-leg distribution.</div>
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

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard
          title="Equity curve"
          subtitle={`${equityRows.length} stored points${equityMetadata?.summary_matches_curve === false ? " · accounting mismatch" : ""}`}
          icon={<Activity size={15} className="text-cyan-200" />}
        >
          <Sparkline rows={equityRows} valueKey="equity" />
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["Starting", money(equityMetadata?.starting_equity)],
              ["Stored curve last", money(equityMetadata?.raw_last_equity_curve_value)],
              ["Stored run summary", money(equityMetadata?.final_equity)],
              ["Difference", signedMoney(equityMetadata?.final_equity_delta)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-white/10 bg-black/18 p-3">
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/35">{label}</div>
                <div className="mt-1 text-sm font-semibold text-white">{value}</div>
              </div>
            ))}
          </div>
          {equityMetadata?.summary_matches_curve === false ? (
            <div className="mt-3 rounded-xl border border-rose-300/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-100/75">
              The stored run summary differs from the persisted equity curve by {signedMoney(equityMetadata.final_equity_delta)}. The chart remains on stored equity and does not add a synthetic final jump. Rerun this backtest after the accounting fix.
            </div>
          ) : null}
        </ChartCard>

        <ChartCard title="Drawdown curve" subtitle="Percent from running peak" icon={<TrendingDown size={15} className="text-rose-200" />}>
          <Sparkline rows={drawdownRows} valueKey="drawdown_pct" />
        </ChartCard>

        <ChartCard title="Monthly returns" subtitle="Return percentage by month" icon={<BarChart3 size={15} className="text-violet-200" />}>
          <BarChart rows={monthlyRows} valueKey="value" valueFormatter={pct} />
        </ChartCard>

        <ChartCard title="PnL by symbol" subtitle="Net PnL by traded symbol" icon={<BarChart3 size={15} className="text-emerald-200" />}>
          <BarChart rows={charts?.pnl_by_symbol ?? []} valueKey="net_pnl" />
        </ChartCard>

        <ChartCard title="PnL by regime" subtitle="Net PnL by market regime" icon={<BarChart3 size={15} className="text-amber-200" />}>
          <BarChart rows={charts?.pnl_by_regime ?? []} valueKey="net_pnl" />
        </ChartCard>

        <ChartCard title="Score bucket performance" subtitle="Exit-leg net PnL by persisted strategy score" icon={<BarChart3 size={15} className="text-cyan-200" />}>
          <BarChart rows={charts?.score_bucket_performance ?? []} valueKey="net_pnl" />
        </ChartCard>

        <ChartCard title="Holding time performance" subtitle="Exit-leg net PnL by duration bucket" icon={<BarChart3 size={15} className="text-violet-200" />}>
          <BarChart rows={charts?.holding_time_performance ?? []} valueKey="net_pnl" />
        </ChartCard>

        <ChartCard title="Fee pressure" subtitle="Net PnL by fees/gross bucket" icon={<BarChart3 size={15} className="text-rose-200" />}>
          <BarChart rows={charts?.fee_pressure ?? []} valueKey="net_pnl" />
        </ChartCard>

        <ChartCard title="Exit-leg distribution" subtitle="Counts and PnL by exit-leg outcome bucket" icon={<BarChart3 size={15} className="text-white/70" />}>
          <BarChart rows={charts?.trade_distribution ?? []} valueKey="trades" valueFormatter={(value) => `${value} legs`} />
        </ChartCard>
      </div>
    </section>
  );
}
