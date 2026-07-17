import { AlertTriangle, Activity, BadgeDollarSign, Gauge, Route, ShieldCheck, Target, TrendingUp } from "lucide-react";
import GlassCard from "../ui/GlassCard";
import MetricCard from "../ui/MetricCard";
import SectionTitle from "../ui/SectionTitle";
import type { DashboardV2Overview } from "../../types/dashboardV2";

function formatMoney(value: number | null | undefined) {
  const safe = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `$${safe.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPct(value: number | null | undefined, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${value.toFixed(digits)}%`;
}

function formatRatioAsPct(value: number | null | undefined, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toFixed(digits);
}

function toneClass(value: number | null | undefined) {
  if ((value ?? 0) > 0) return "text-emerald-300";
  if ((value ?? 0) < 0) return "text-rose-300";
  return "text-white";
}

function MiniStat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-white/35">{label}</div>
      <div className="mt-2 text-xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-white/40">{hint}</div> : null}
    </div>
  );
}

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const style =
    tone === "good"
      ? "border-emerald-400/15 bg-emerald-500/10 text-emerald-200"
      : tone === "warn"
      ? "border-amber-400/15 bg-amber-500/10 text-amber-200"
      : tone === "bad"
      ? "border-rose-400/15 bg-rose-500/10 text-rose-200"
      : "border-white/10 bg-white/7 text-white/65";

  return <span className={`inline-flex rounded-full border px-3 py-1 text-xs ${style}`}>{children}</span>;
}

export default function OverviewV2Panels({ data }: { data: DashboardV2Overview | null }) {
  if (!data) {
    return (
      <GlassCard>
        <SectionTitle title="Overview V2" subtitle="Waiting for dashboard-api aggregation layer" />
        <div className="rounded-2xl border border-white/8 bg-white/5 p-5 text-sm text-white/50">
          V2 overview data has not loaded yet. The classic overview remains active above.
        </div>
      </GlassCard>
    );
  }

  const perf = data.performance_summary;
  const strategy = data.strategy_summary;
  const tp = data.tp_summary;
  const stop = data.stop_summary;
  const costs = data.cost_breakdown;
  const drawdown = data.drawdown_summary;

  return (
    <div className="space-y-7">
      {data.partial ? (
        <GlassCard className="border-amber-300/20 bg-amber-500/8">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl bg-amber-400/10 p-2 text-amber-200">
              <AlertTriangle size={18} />
            </div>
            <div>
              <div className="font-semibold text-amber-100">Dashboard V2 loaded with partial data</div>
              <div className="mt-1 text-sm text-amber-100/65">
                Some evaluator panels failed, but the overview is still rendering available sections.
              </div>
              {data.errors?.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {data.errors.slice(0, 4).map((error, index) => (
                    <Pill key={index} tone="warn">
                      {String(error.source ?? "unknown")}
                    </Pill>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </GlassCard>
      ) : null}

      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Net Realized PnL V2" value={formatMoney(perf?.net_realized_pnl)} hint="Closed positions, net of actual fees" />
        <MetricCard label="Win Rate V2" value={formatPct(perf?.position_win_rate)} hint={`${perf?.wins ?? 0} wins / ${perf?.losses ?? 0} losses`} />
        <MetricCard label="Profit Factor" value={formatNumber(perf?.profit_factor)} hint="Net wins divided by net losses" />
        <MetricCard label="Max Drawdown" value={formatPct(drawdown?.max_drawdown_pct)} hint={formatMoney(drawdown?.max_drawdown_value)} />
        <MetricCard label="Fill Rate" value={formatPct(strategy?.fill_rate)} hint="Paper submitted to filled" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <GlassCard>
          <SectionTitle title="Performance V2" subtitle="Position-aware realized performance with fees separated" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <MiniStat label="Positions Closed" value={String(perf?.positions_closed ?? 0)} />
            <MiniStat label="Expectancy" value={formatMoney(perf?.expectancy_net_pnl)} hint="Net per closed position" />
            <MiniStat label="Average R" value={formatNumber(perf?.average_realized_r)} />
            <MiniStat label="Fees Paid" value={formatMoney(costs?.fees_paid)} />
            <MiniStat label="Fee Pressure" value={formatRatioAsPct(costs?.fee_to_gross_realized_ratio)} />
            <MiniStat label="Avg Slippage" value={formatNumber(costs?.average_slippage_bps)} hint="bps, if provided" />
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/55">
            <div className="flex items-center gap-2 text-white/75">
              <BadgeDollarSign size={16} />
              PnL convention
            </div>
            <div className="mt-2">
              Realized PnL is net after actual fees. Unrealized PnL remains live gross PnL with no estimated exit fees.
              Fees, slippage, spread, and funding stay visible separately.
            </div>
          </div>
        </GlassCard>

        <GlassCard>
          <SectionTitle title="Strategy Funnel V2" subtitle="Decision pipeline from candidate to fill" />
          <div className="space-y-3">
            {[
              ["Candidates", strategy?.rows],
              ["Trade Candidates", strategy?.trade_candidates],
              ["Risk Approved", strategy?.risk_approved],
              ["Guardian Allowed", strategy?.guardian_allowed],
              ["Submitted", strategy?.paper_submitted],
              ["Filled", strategy?.filled],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex items-center justify-between rounded-2xl border border-white/8 bg-white/5 px-4 py-3">
                <div className="text-sm text-white/50">{label}</div>
                <div className="text-lg font-semibold text-white">{Number(value ?? 0).toLocaleString()}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <MiniStat label="Trade Rate" value={formatPct(strategy?.trade_candidate_rate)} />
            <MiniStat label="Risk Pass" value={formatPct(strategy?.risk_approval_rate)} />
            <MiniStat label="Guardian Pass" value={formatPct(strategy?.guardian_allow_rate)} />
            <MiniStat label="Avg Score" value={formatNumber(strategy?.average_best_strategy_score)} />
          </div>
        </GlassCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <GlassCard>
          <SectionTitle title="TP Leg Progression" subtitle="Partial close quality and continuation" />
          <div className="grid gap-3 sm:grid-cols-3">
            <MiniStat label="TP1 Hit Rate" value={formatPct(tp?.tp1_hit_rate)} hint={`${tp?.tp1_hits ?? 0} hits`} />
            <MiniStat label="TP2 Hit Rate" value={formatPct(tp?.tp2_hit_rate)} hint={`${tp?.tp2_hits ?? 0} hits`} />
            <MiniStat label="TP3 Hit Rate" value={formatPct(tp?.tp3_hit_rate)} hint={`${tp?.tp3_hits ?? 0} hits`} />
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
              <div className="flex items-center gap-2 text-sm text-white/55">
                <Target size={16} />
                TP1 → TP2
              </div>
              <div className="mt-2 text-3xl font-semibold text-white">{formatPct(tp?.tp1_to_tp2_continuation_rate)}</div>
            </div>
            <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
              <div className="flex items-center gap-2 text-sm text-white/55">
                <TrendingUp size={16} />
                TP2 → TP3
              </div>
              <div className="mt-2 text-3xl font-semibold text-white">{formatPct(tp?.tp2_to_tp3_continuation_rate)}</div>
            </div>
          </div>
        </GlassCard>

        <GlassCard>
          <SectionTitle title="Stop Management" subtitle="Adaptive protection, near-TP protection, and regime stop behavior" />
          <div className="grid gap-3 sm:grid-cols-2">
            <MiniStat label="Stop Events" value={String(stop?.events ?? 0)} />
            <MiniStat label="Reprices" value={String(stop?.reprices ?? 0)} hint={formatPct(stop?.reprice_rate)} />
            <MiniStat label="No-ops" value={String(stop?.noops ?? 0)} hint={formatPct(stop?.noop_rate)} />
            <MiniStat label="Errors" value={String(stop?.errors ?? 0)} />
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-white/5 p-4">
            <div className="flex items-center gap-2 text-sm text-white/55">
              <ShieldCheck size={16} />
              Average stop improvement
            </div>
            <div className={`mt-2 text-3xl font-semibold ${toneClass(stop?.average_stop_improvement)}`}>
              {formatNumber(stop?.average_stop_improvement, 6)}
            </div>
            <div className="mt-1 text-xs text-white/35">Absolute stop distance change when old/new stops are available</div>
          </div>
        </GlassCard>
      </div>

      <GlassCard>
        <SectionTitle title="Live V2 Snapshot" subtitle="Dashboard-api aggregation of evaluator live state" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MiniStat label="Open Positions" value={String(data.live?.open_positions_count ?? 0)} />
          <MiniStat label="Open Orders" value={String(data.live?.open_orders_count ?? 0)} />
          <MiniStat label="Equity" value={formatMoney(data.latest_equity?.equity)} />
          <MiniStat label="Unrealized PnL" value={formatMoney(data.latest_equity?.unrealized_pnl)} hint="Live gross PnL" />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Pill tone={data.ok ? "good" : data.partial ? "warn" : "bad"}>
            <span className="inline-flex items-center gap-2">
              <Activity size={13} />
              {data.ok ? "All V2 sources healthy" : data.partial ? "Partial V2 data" : "V2 unavailable"}
            </span>
          </Pill>
          <Pill>
            <span className="inline-flex items-center gap-2">
              <Gauge size={13} />
              {data.dashboard_aggregation_v2_version}
            </span>
          </Pill>
          <Pill>
            <span className="inline-flex items-center gap-2">
              <Route size={13} />
              /dashboard/v2/overview
            </span>
          </Pill>
        </div>
      </GlassCard>
    </div>
  );
}
