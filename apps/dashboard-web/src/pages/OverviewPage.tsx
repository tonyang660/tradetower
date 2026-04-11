import { useEffect, useMemo, useState } from "react";
import { RefreshCcw, PauseCircle, PlayCircle, Zap, Clock3 } from "lucide-react";
import { fetchBootstrapOverview, resumeTrading, suspendTrading, enableSchedulerAutoLoop, disableSchedulerAutoLoop } from "../lib/api";
import type { BootstrapOverview } from "../types/dashboard";
import GlassCard from "../components/ui/GlassCard";
import MetricCard from "../components/ui/MetricCard";
import SectionTitle from "../components/ui/SectionTitle";
import EquityChart from "../components/charts/EquityChart";
import TradingStatusCard from "../components/overview/TradingStatusCard";
import MarketSessionsCard from "../components/overview/MarketSessionsCard";

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCountdown(seconds: number) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return `${hrs}h ${mins}m ${secs}s`;
}

function ActionButton({
  onClick,
  children,
  variant = "default",
  disabled = false,
}: {
  onClick: () => void;
  children: React.ReactNode;
  variant?: "default" | "danger" | "success";
  disabled?: boolean;
}) {
  const style =
    variant === "danger"
      ? "border-rose-400/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/15"
      : variant === "success"
      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/15"
      : "border-white/10 bg-white/8 text-white/80 hover:bg-white/12 hover:text-white";

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-2xl border px-4 py-2 text-sm font-medium transition ${style} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {children}
    </button>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<BootstrapOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [actionBusy, setActionBusy] = useState<"suspend" | "resume" | null>(null);
  const [schedulerBusy, setSchedulerBusy] = useState<"enable" | "disable" | null>(null);
  const [liveNow, setLiveNow] = useState<Date>(new Date());
  const [serverClockAnchor, setServerClockAnchor] = useState<Date | null>(null);
  const [clientClockAnchor, setClientClockAnchor] = useState<number | null>(null);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchBootstrapOverview(1);
      setData(payload);
      setError(null);
      setLastUpdated(new Date());

      const serverNow = new Date(payload.market_banner.current_utc_time);
      setServerClockAnchor(serverNow);
      setClientClockAnchor(Date.now());
      setLiveNow(serverNow);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (showLoading) setLoading(false);
      if (showRefreshing) setRefreshing(false);
    }
  }

  useEffect(() => {
    load(true, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (!serverClockAnchor || clientClockAnchor === null) return;

      const elapsedMs = Date.now() - clientClockAnchor;
      setLiveNow(new Date(serverClockAnchor.getTime() + elapsedMs));
    }, 1000);

    return () => window.clearInterval(id);
  }, [serverClockAnchor, clientClockAnchor]);

  useEffect(() => {
    if (!autoRefresh) return;

    const id = window.setInterval(() => {
      load(false, false);
    }, 30000);

    return () => window.clearInterval(id);
  }, [autoRefresh]);

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
      cycleId: latestCycle.cycle_id ?? data.overview.latest_cycle?.cycle_id ?? "-",
    };
  }, [data]);

  const countdownSeconds = useMemo(() => {
    if (!data?.market_banner?.next_session?.opens_at_utc) return null;
    const target = new Date(data.market_banner.next_session.opens_at_utc).getTime();
    return Math.max(0, Math.floor((target - liveNow.getTime()) / 1000));
  }, [data, liveNow]);

  async function handleSuspend() {
    try {
      setActionBusy("suspend");
      await suspendTrading(1);
      await load(false, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to suspend trading");
    } finally {
      setActionBusy(null);
    }
  }

  async function handleResume() {
    try {
      setActionBusy("resume");
      await resumeTrading(1);
      await load(false, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume trading");
    } finally {
      setActionBusy(null);
    }
  }

  async function handleEnableSchedulerLoop() {
    try {
      setSchedulerBusy("enable");
      await enableSchedulerAutoLoop();
      await load(false, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enable scheduler loop");
    } finally {
      setSchedulerBusy(null);
    }
  }

  async function handleDisableSchedulerLoop() {
    try {
      setSchedulerBusy("disable");
      await disableSchedulerAutoLoop();
      await load(false, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable scheduler loop");
    } finally {
      setSchedulerBusy(null);
    }
  }

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
    <div className="space-y-7">
      <div className="grid gap-5 xl:grid-cols-[1.35fr_0.85fr_1fr]">
        <MarketSessionsCard
          now={liveNow.toISOString()}
          activeSessions={data.market_banner.active_sessions ?? []}
          isWeekend={data.market_banner.is_weekend ?? false}
          nextSessionName={data.market_banner.next_session?.name ?? null}
          nextSessionCountdown={countdownSeconds !== null ? formatCountdown(countdownSeconds) : "-"}
          sessionRows={data.market_banner.session_rows ?? []}
        />

        <TradingStatusCard
          enabled={!data.trading_banner.trading_disabled}
          reasonCodes={data.trading_banner.reason_codes}
        />

        <GlassCard className="h-full">
          <SectionTitle title="Controls" subtitle="Operator controls for the active account" />

          <div className="flex flex-wrap gap-3">
            <ActionButton onClick={() => load(false, true)} disabled={refreshing}>
              <span className="inline-flex items-center gap-2">
                <RefreshCcw size={16} />
                {refreshing ? "Refreshing..." : "Refresh Now"}
              </span>
            </ActionButton>

            <ActionButton onClick={() => setAutoRefresh((v) => !v)}>
              <span className="inline-flex items-center gap-2">
                <Zap size={16} />
                Auto-refresh: {autoRefresh ? "On" : "Off"}
              </span>
            </ActionButton>

            <ActionButton onClick={handleSuspend} variant="danger" disabled={actionBusy !== null}>
              <span className="inline-flex items-center gap-2">
                <PauseCircle size={16} />
                {actionBusy === "suspend" ? "Suspending..." : "Suspend Trading"}
              </span>
            </ActionButton>

            <ActionButton onClick={handleResume} variant="success" disabled={actionBusy !== null}>
              <span className="inline-flex items-center gap-2">
                <PlayCircle size={16} />
                {actionBusy === "resume" ? "Resuming..." : "Resume Trading"}
              </span>
            </ActionButton>

            <ActionButton
              onClick={handleEnableSchedulerLoop}
              disabled={schedulerBusy !== null || data.scheduler_health?.auto_loop_enabled === true}
            >
              Enable Cycle Loop
            </ActionButton>

            <ActionButton
              onClick={handleDisableSchedulerLoop}
              disabled={schedulerBusy !== null || data.scheduler_health?.auto_loop_enabled === false}
            >
              Disable Cycle Loop
            </ActionButton>
          </div>

          <div className="mt-4 space-y-2 text-sm text-white/55">
            <div className="inline-flex items-center gap-2">
              <Clock3 size={15} />
              <span>Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : "Not yet"}</span>
            </div>

            <div>
              Scheduler loop:{" "}
              <span className="font-medium text-white/75">
                {data.scheduler_health?.auto_loop_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            <div>
              Loop interval:{" "}
              <span className="font-medium text-white/75">
                {data.scheduler_health?.loop_interval_seconds ?? "-"}s
              </span>
            </div>
          </div>
        </GlassCard>
      </div>

      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
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
              {[
                ["Decision Rows", data.decision_funnel.funnel.decision_rows],
                ["Candidates Seen", data.decision_funnel.funnel.candidate_filter_seen],
                ["No Trade", data.decision_funnel.funnel.no_trade],
                ["Risk Approved", data.decision_funnel.funnel.risk_approved],
                ["Submitted", data.decision_funnel.funnel.paper_submitted],
                ["Filled", data.decision_funnel.funnel.filled],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl border border-white/8 bg-white/5 p-3">
                  <div className="text-white/45">{label}</div>
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
            <div className="rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
              <div className="font-medium text-white/70">No open positions</div>
              <div className="mt-2 text-white/45">
                Active positions will appear here once entries are filled and marked to market.
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {data.overview.open_positions.map((pos: any, idx: number) => (
                <div key={idx} className="rounded-2xl border border-white/8 bg-white/5 p-4 transition hover:bg-white/7">
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
            <div className="rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
              <div className="font-medium text-white/70">No recent positions yet</div>
              <div className="mt-2 text-white/45">
                Closed trades will appear here with PnL, leverage, and direction once trading activity begins.
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {data.overview.recent_positions.map((trade: any) => (
                <div key={trade.trade_id} className="rounded-2xl border border-white/8 bg-white/5 p-4 transition hover:bg-white/7">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-white">{trade.symbol}</div>
                    <div
                      className={`rounded-full px-2 py-1 text-xs font-medium ${
                        trade.win_loss === "WIN"
                          ? "bg-emerald-400/10 text-emerald-300"
                          : trade.win_loss === "LOSS"
                          ? "bg-rose-400/10 text-rose-300"
                          : "bg-white/10 text-white/60"
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
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard label="Cycle ID" value={summary.cycleId.slice(11, 19)} />
          <MetricCard label="Candidates" value={String(summary.cycleCandidates)} />
          <MetricCard label="Analyzed" value={String(summary.cycleAnalyzed)} />
          <MetricCard label="Accepted" value={String(summary.cycleAccepted)} />
          <MetricCard label="Refreshed Symbols" value={String(summary.cycleRefreshedSymbols)} />
        </div>
      </GlassCard>
    </div>
  );
}