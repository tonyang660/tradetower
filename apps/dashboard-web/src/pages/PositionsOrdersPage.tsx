import { useEffect, useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { fetchOpenPositions, fetchRecentClosedPositions } from "../lib/api";
import { buildPositionsOrdersViewModel } from "../lib/positionsOrders";
import type {
  OpenPositionsResponse,
  RecentClosedPositionsResponse,
  PositionsOrdersViewModel,
} from "../types/positionsOrders";
import GlassCard from "../components/ui/GlassCard";
import SectionTitle from "../components/ui/SectionTitle";
import PositionAnalyticsStrip from "../components/positions-orders/PositionAnalyticsStrip";
import ExposureRibbon from "../components/positions-orders/ExposureRibbon";
import OpenPositionsPanel from "../components/positions-orders/OpenPositionsPanel";
import WorkingOrdersPanel from "../components/positions-orders/WorkingOrdersPanel";
import RecentClosedPositionsPanel from "../components/positions-orders/RecentClosedPositionsPanel";

export default function PositionsOrdersPage() {
  const [openPayload, setOpenPayload] = useState<OpenPositionsResponse | null>(null);
  const [recentPayload, setRecentPayload] = useState<RecentClosedPositionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const [openRes, recentRes] = await Promise.all([
        fetchOpenPositions(1, true),
        fetchRecentClosedPositions(1, 20),
      ]);

      setOpenPayload(openRes);
      setRecentPayload(recentRes);
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

  const model: PositionsOrdersViewModel | null = useMemo(() => {
    if (!openPayload || !recentPayload) return null;
    return buildPositionsOrdersViewModel(openPayload.items, recentPayload.items);
  }, [openPayload, recentPayload]);

  if (loading) {
    return <div className="text-white/70">Loading positions & orders...</div>;
  }

  if (error || !model) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load positions & orders. {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch xl:justify-between">
        <GlassCard className="flex-1">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-[0.28em] text-white/40">Execution Surface</div>
              <div className="mt-2 text-3xl font-semibold tracking-tight text-white">
                Positions & Orders
              </div>
              <div className="mt-2 text-sm text-white/45">
                Portfolio pressure, live exposure, execution state, and recent trade outcomes.
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

      <PositionAnalyticsStrip analytics={model.analytics} />

      <ExposureRibbon analytics={model.analytics} segments={model.exposureSegments} />

      <OpenPositionsPanel positions={model.openPositions as any} />

      <WorkingOrdersPanel />

      <RecentClosedPositionsPanel positions={model.recentClosed} />
    </div>
  );
}