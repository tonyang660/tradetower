import { useEffect, useMemo, useState } from "react";
import { fetchBootstrapOverview } from "../lib/api";
import type { BootstrapOverview } from "../types/dashboard";
import GlassCard from "../components/ui/GlassCard";
import MetricCard from "../components/ui/MetricCard";
import SectionTitle from "../components/ui/SectionTitle";
import EquityChart from "../components/charts/EquityChart";

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCountdown(seconds: number) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hrs}h ${mins}m`;
}

export default function OverviewPage() {
  const [data, setData] = useState<BootstrapOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [liveNow, setLiveNow] = useState<Date>(new Date());

  useEffect(() => {
    const id = window.setInterval(() => {
      setLiveNow(new Date());
    }, 1000);

    return () => window.clearInterval(id);
  }, []);

  const countdownSeconds = useMemo(() => {
    if (!data?.market_banner?.next_session?.opens_at_utc) return null;
    const target = new Date(data.market_banner.next_session.opens_at_utc).getTime();
    const diff = Math.max(0, Math.floor((target - liveNow.getTime()) / 1000));
    return diff;
  }, [data, liveNow]);

  useEffect(() => {
  let mounted = true;

  async function load(showLoading = false) {
    try {
      if (showLoading) setLoading(true);

      const payload = await fetchBootstrapOverview(1);

      if (mounted) {
        setData(payload);
        setError(null);
      }
    } catch (err) {
      if (mounted) {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    } finally {
      if (mounted && showLoading) setLoading(false);
    }
  }

  load(true); // first load only shows loading state

  const id = window.setInterval(() => {
    load(false); // background refresh, no full page loading state
  }, 30000);

  return () => {
    mounted = false;
    window.clearInterval(id);
  };
}, []);

  const summary = useMemo(() => {
    if (!data) return null;

    const account = data.overview.account_status;
    const micro = data.overview.micro_metrics;
    const perf = data.performance_summary.performance;
    const latestCycle = data.latest_cycle.cycle?.summary ?? data.overview.latest_cycle?.summary ?? {};

    return {
      equity: account.equity,
      cash: account.cash_balance,
      realized: account.realized_pnl,
      unrealized: account.unrealized_pnl,
      openPositions: micro.open_positions_count,
      dailyPnl: micro.daily_pnl,
      dailyWinRate: micro.daily_win_rate,
      completedTrades: perf.completed_trades,
      cycleAnalyzed: latestCycle.strategy_engine?.analyzed ?? 0,
      cycleAccepted: latestCycle.strategy_engine?.accepted ?? 0,
      cycleCandidates: latestCycle.candidate_filter?.candidates?.length ?? 0,
      cycleRefreshedSymbols: latestCycle.refreshed_symbols_count ?? 0,
    };
  }, [data]);

  if (loading) {
    return <div className="text-white/70">Loading dashboard overview...</div>;
  }

  if (error || !data || !summary) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load overview. {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <GlassCard className="overflow-hidden">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm text-white/50">Current market time</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight">
                {liveNow.toLocaleString()}
              </div>
              <div className="mt-2 text-sm text-white/45">
                Active session: {data.market_banner.active_session ?? "None"}
              </div>
            </div>

            {data.market_banner.next_session ? (
              <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3 text-sm">
                <div className="text-white/55">Next session</div>
                <div className="mt-1 font-medium text-white">
                  {data.market_banner.next_session.name} opens in{" "}
                  {countdownSeconds !== null ? formatCountdown(countdownSeconds) : "-"}
                </div>
              </div>
            ) : null}
          </div>
        </GlassCard>

        <GlassCard
          className={
            data.trading_banner.trading_disabled
              ? "border-amber-300/20 bg-amber-500/10"
              : "border-emerald-300/20 bg-emerald-500/10"
          }
        >
          <div className="text-sm text-white/55">Trading status</div>
          <div className="mt-1 text-xl font-semibold">{data.trading_banner.message}</div>
          <div className="mt-2 text-sm text-white/55">
            {data.trading_banner.trading_disabled
              ? `Reason: ${data.trading_banner.reason_codes.join(", ")}`
              : "All entry paths available. Maintenance remains active."}
          </div>
        </GlassCard>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Live Equity" value={formatMoney(summary.equity)} hint="Current account equity" />
        <MetricCard label="Cash Balance" value={formatMoney(summary.cash)} hint="Available cash balance" />
        <MetricCard label="Realized PnL" value={formatMoney(summary.realized)} hint="Closed profit and loss" />
        <MetricCard label="Open Positions" value={String(summary.openPositions)} hint="Currently active positions" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <GlassCard>
          <SectionTitle title="Equity Curve" subtitle="Live account equity history" />
          <EquityChart data={data.overview.equity_series} />
        </GlassCard>

        <div className="space-y-6">
          <GlassCard>
            <SectionTitle title="Micro Metrics" subtitle="Today’s operating metrics" />
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="Daily PnL" value={formatMoney(summary.dailyPnl)} />
              <MetricCard label="Daily Win Rate" value={`${summary.dailyWinRate.toFixed(2)}%`} />
              <MetricCard label="Daily Completed Trades" value={String(data.overview.micro_metrics.daily_completed_trades)} />
              <MetricCard label="Total Trades" value={String(summary.completedTrades)} />
            </div>
          </GlassCard>

          <GlassCard>
            <SectionTitle title="Decision Funnel" subtitle="Current evaluator decision flow totals" />
            <div className="grid grid-cols-2 gap-3 text-sm">
              {Object.entries(data.decision_funnel.funnel).map(([key, value]) => (
                <div key={key} className="rounded-2xl border border-white/8 bg-white/5 p-3">
                  <div className="text-white/45">{key}</div>
                  <div className="mt-1 text-xl font-semibold text-white">{String(value)}</div>
                </div>
              ))}
            </div>
          </GlassCard>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <GlassCard>
          <SectionTitle title="Live Open Positions" subtitle="Marked-to-market active positions" />
          {data.overview.open_positions.length === 0 ? (
            <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/50">
              No open positions.
            </div>
          ) : (
            <div className="space-y-3">
              {data.overview.open_positions.map((pos: any, idx: number) => (
                <div key={idx} className="rounded-2xl border border-white/8 bg-white/5 p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-white">{pos.symbol}</div>
                    <div className="text-sm uppercase text-white/55">{pos.side}</div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-white/60">
                    <div>Entry: {pos.entry_price}</div>
                    <div>Leverage: {pos.leverage ?? "-"}</div>
                    <div>Remaining Size: {pos.remaining_size ?? "-"}</div>
                    <div>Current Price: {pos.current_price ?? "-"}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard>
          <SectionTitle title="Recent Positions" subtitle="Most recently closed trades" />
          {data.overview.recent_positions.length === 0 ? (
            <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/50">
              No recent positions yet.
            </div>
          ) : (
            <div className="space-y-3">
              {data.overview.recent_positions.map((trade: any) => (
                <div key={trade.trade_id} className="rounded-2xl border border-white/8 bg-white/5 p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-white">{trade.symbol}</div>
                    <div
                      className={`text-sm font-medium ${
                        trade.win_loss === "WIN"
                          ? "text-emerald-300"
                          : trade.win_loss === "LOSS"
                          ? "text-rose-300"
                          : "text-white/60"
                      }`}
                    >
                      {trade.win_loss}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-white/60">
                    <div>Direction: {trade.direction}</div>
                    <div>Leverage: {trade.leverage ?? "-"}</div>
                    <div>Notional: {trade.notional ?? "-"}</div>
                    <div>PnL: {trade.realized_pnl ?? "-"}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      <GlassCard>
        <SectionTitle title="Latest Cycle Snapshot" subtitle="Most recent deterministic cycle activity" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Candidates" value={String(summary.cycleCandidates)} />
          <MetricCard label="Analyzed" value={String(summary.cycleAnalyzed)} />
          <MetricCard label="Accepted" value={String(summary.cycleAccepted)} />
          <MetricCard label="Refreshed Symbols" value={String(summary.cycleRefreshedSymbols)} />
        </div>
      </GlassCard>
    </div>
  );
}
