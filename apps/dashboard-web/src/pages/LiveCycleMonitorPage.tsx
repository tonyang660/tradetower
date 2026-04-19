import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { fetchLiveCycleMonitor } from "../lib/api";
import type { LiveCycleMonitorBootstrap } from "../types/liveCycle";
import GlassCard from "../components/ui/GlassCard";
import SectionTitle from "../components/ui/SectionTitle";
import CycleSummaryStrip from "../components/live-cycle/CycleSummaryStrip";
import CyclePipelineRail from "../components/live-cycle/CyclePipelineRail";
import LatestCycleDetails from "../components/live-cycle/LatestCycleDetails";
import RecentCycleList from "../components/live-cycle/RecentCycleList";
import CycleTrendPanel from "../components/live-cycle/CycleTrendPanel";

export default function LiveCycleMonitorPage() {
  const [data, setData] = useState<LiveCycleMonitorBootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchLiveCycleMonitor(1, 15);
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
    return <div className="text-white/70">Loading live cycle monitor...</div>;
  }

  if (error || !data) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load live cycle monitor. {error}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch xl:justify-between">
        <GlassCard className="flex-1">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-[0.28em] text-white/40">Pipeline Observability</div>
              <div className="mt-2 text-3xl font-semibold tracking-tight text-white">Live Cycle Monitor</div>
              <div className="mt-2 text-sm text-white/45">
                Follow the deterministic cycle flow from refresh through paper execution.
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3 text-sm text-white/60">
              Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : "Not yet"}
            </div>
          </div>
        </GlassCard>

        <GlassCard className="xl:w-[320px]">
          <SectionTitle title="Controls" subtitle="Page refresh behavior" />
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

      {data.summary_strip ? <CycleSummaryStrip summary={data.summary_strip} /> : null}

      <CyclePipelineRail stages={data.pipeline_stages} />

      <LatestCycleDetails cycle={data.latest_cycle} />

      <RecentCycleList cycles={data.recent_cycles} />

      <CycleTrendPanel trends={data.trends} />
    </div>
  );
}