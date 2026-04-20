import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import GlassCard from "../components/ui/GlassCard";
import SectionTitle from "../components/ui/SectionTitle";
import PerformanceSummaryStrip from "../components/performance/PerformanceSummaryStrip";
import EquityCurvePanel from "../components/performance/EquityCurvePanel";
import DrawdownPanel from "../components/performance/DrawdownPanel";
import TradeQualityPanel from "../components/performance/TradeQualityPanel";
import DirectionalBreakdownPanel from "../components/performance/DirectionalBreakdownPanel";
import MetricBarChartPanel from "../components/performance/MetricBarChartPanel";
import TradingCalendarPanel from "../components/performance/TradingCalendarPanel";
import { fetchPerformanceBootstrap } from "../lib/api";
import type { PerformanceBootstrapResponse } from "../types/performance";

export default function PerformancePage() {
  const [data, setData] = useState<PerformanceBootstrapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchPerformanceBootstrap(1);
      setData(payload);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (showLoading) setLoading(false);
      if (showRefreshing) setRefreshing(false);
    }
  }

  useEffect(() => {
    load(true, false);
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => load(false, false), 30000);
    return () => window.clearInterval(id);
  }, [autoRefresh]);

  if (loading) {
    return <div className="text-white/70">Loading performance...</div>;
  }

  if (error || !data) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load performance. {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch xl:justify-between">
        <GlassCard className="flex-1">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-[0.28em] text-white/40">Performance Lab</div>
              <div className="mt-2 text-3xl font-semibold tracking-tight text-white">
                Performance
              </div>
              <div className="mt-2 text-sm text-white/45">
                Account returns, edge quality, directional bias, and time-based diagnostics.
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3 text-sm text-white/60">
              Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : "Not yet"}
            </div>
          </div>
        </GlassCard>

        <GlassCard className="xl:w-[320px]">
          <SectionTitle title="Controls" subtitle="Refresh and page behavior" />
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => load(false, true)}
              disabled={refreshing}
              className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-2">
                <RefreshCcw size={16} />
                {refreshing ? "Refreshing..." : "Refresh Now"}
              </span>
            </button>

            <button
              onClick={() => setAutoRefresh((v) => !v)}
              className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white"
            >
              Auto-refresh: {autoRefresh ? "On" : "Off"}
            </button>
          </div>
        </GlassCard>
      </div>

      <PerformanceSummaryStrip summary={data.summary} />

      <div className="grid gap-6 xl:grid-cols-2">
        <EquityCurvePanel items={data.equity_curve} />
        <DrawdownPanel items={data.drawdown_curve} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <TradeQualityPanel summary={data.summary} />
        <DirectionalBreakdownPanel breakdown={data.directional_breakdown} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <MetricBarChartPanel
          title="Hourly Performance"
          subtitle="Realized pnl by UTC hour"
          data={data.hourly_performance}
          xKey="hour"
          rightLabel="UTC hours"
        />
        <MetricBarChartPanel
          title="Weekday Performance"
          subtitle="Realized pnl by weekday"
          data={data.weekday_performance}
          xKey="weekday"
        />
        <MetricBarChartPanel
          title="Session Performance"
          subtitle="Performance by trading session"
          data={data.session_performance}
          xKey="session"
        />
      </div>

      <TradingCalendarPanel
        days={data.calendar_days}
        monthlySummary={data.monthly_summary}
      />
    </div>
  );
}