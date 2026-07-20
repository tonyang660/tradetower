import { useEffect, useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { buildPositionsOrdersViewModel } from "../lib/positionsOrders";
import { fetchPositionsOrdersV2 } from "../lib/dashboardV2";
import { fetchConfigurationBootstrap } from "../lib/api";
import type { ConfigurationBootstrapResponse } from "../types/configuration";
import type { PositionsOrdersV2Response } from "../types/positionsOrdersV2";

import {
  type OpenPositionsResponse,
  type RecentClosedPositionsResponse,
  type OpenOrdersResponse,
  type PositionsOrdersViewModel,
  type ExecutedOrdersResponse,
} from "../types/positionsOrders";
import {
  mockOpenPositionsResponse,
  mockRecentClosedPositionsResponse,
  mockWorkingOrders,
} from "../mocks/positionsOrdersMock";

import GlassCard from "../components/ui/GlassCard";
import SectionTitle from "../components/ui/SectionTitle";
import PositionAnalyticsStrip from "../components/positions-orders/PositionAnalyticsStrip";
import ExposureRibbon from "../components/positions-orders/ExposureRibbon";
import OpenPositionsPanel from "../components/positions-orders/OpenPositionsPanel";
import WorkingOrdersPanel from "../components/positions-orders/WorkingOrdersPanel";
import RecentClosedPositionsPanel from "../components/positions-orders/RecentClosedPositionsPanel";
import OrderCycleStatusCard from "../components/positions-orders/OrderCycleStatusCard";
import ExecutedOrdersPanel from "../components/positions-orders/ExecutedOrdersPanel";
import PositionEventsPanel from "../components/positions-orders/PositionEventsPanel";

export default function PositionsOrdersPage() {
  const [openPayload, setOpenPayload] = useState<OpenPositionsResponse | null>(null);
  const [recentPayload, setRecentPayload] = useState<RecentClosedPositionsResponse | null>(null);
  const [executedPayload, setExecutedPayload] = useState<ExecutedOrdersResponse | null>(null);
  const [ordersPayload, setOrdersPayload] = useState<OpenOrdersResponse | null>(null);
  const [positionsOrdersV2, setPositionsOrdersV2] = useState<PositionsOrdersV2Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configurationBootstrap, setConfigurationBootstrap] = useState<ConfigurationBootstrapResponse | null>(null);
  const USE_MOCK_POSITIONS = false;

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      if (USE_MOCK_POSITIONS) {
        setOpenPayload(mockOpenPositionsResponse);
        setRecentPayload(mockRecentClosedPositionsResponse);
        setOrdersPayload({
          ok: true,
          account_id: 1,
          count: mockWorkingOrders.length,
          items: mockWorkingOrders,
        });
        setError(null);
        setLastUpdated(new Date());
        if (showLoading) setLoading(false);
        if (showRefreshing) setRefreshing(false);
        return;
      }

      const [positionsOrdersRes, configurationRes] = await Promise.all([
        fetchPositionsOrdersV2(1, 20, 50, 10),
        fetchConfigurationBootstrap(),
      ]);

      setPositionsOrdersV2(positionsOrdersRes);
      setOpenPayload({
        ok: positionsOrdersRes.services?.open_positions?.ok ?? positionsOrdersRes.partial === false,
        account_id: positionsOrdersRes.account_id,
        count: positionsOrdersRes.counts.open_positions,
        items: positionsOrdersRes.open_positions,
        positions: positionsOrdersRes.open_positions,
        account_status: positionsOrdersRes.raw?.open_positions?.account_status,
        pricing_errors: positionsOrdersRes.raw?.open_positions?.pricing_errors,
      });
      setRecentPayload({
        ok: positionsOrdersRes.services?.recent_positions?.ok ?? positionsOrdersRes.partial === false,
        account_id: positionsOrdersRes.account_id,
        count: positionsOrdersRes.counts.recent_closed_positions,
        items: positionsOrdersRes.recent_closed_positions,
      });
      setOrdersPayload({
        ok: positionsOrdersRes.services?.open_orders?.ok ?? positionsOrdersRes.partial === false,
        account_id: positionsOrdersRes.account_id,
        count: positionsOrdersRes.counts.open_orders,
        items: positionsOrdersRes.open_orders,
      });
      setExecutedPayload({
        ok: positionsOrdersRes.services?.executed_orders?.ok ?? positionsOrdersRes.partial === false,
        account_id: positionsOrdersRes.account_id,
        count: positionsOrdersRes.counts.executed_orders,
        items: positionsOrdersRes.executed_orders,
      });
      setConfigurationBootstrap(configurationRes);

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
    if (!openPayload || !recentPayload || !ordersPayload || !executedPayload) return null;

    const openPositions = openPayload.positions ?? openPayload.items ?? [];
    const recentClosed = recentPayload.items ?? [];
    const workingOrders = ordersPayload.items ?? [];
    const executedOrders = executedPayload.items ?? [];

    return buildPositionsOrdersViewModel(openPositions, recentClosed, executedOrders, workingOrders);
  }, [openPayload, recentPayload, executedPayload, ordersPayload]);

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

      {positionsOrdersV2?.partial ? (
        <div className="rounded-3xl border border-amber-400/20 bg-amber-500/10 p-4 text-sm text-amber-100/80">
          Positions & Orders V2 loaded with partial data. Available panels are still shown; failed sources are logged in the V2 payload.
        </div>
      ) : null}

      <PositionAnalyticsStrip analytics={model.analytics} />

      <ExposureRibbon analytics={model.analytics} segments={model.exposureSegments} />

      {configurationBootstrap ? (
        <OrderCycleStatusCard
          autoLoopEnabled={configurationBootstrap.settings.auto_loop_enabled}
          loopIntervalSeconds={configurationBootstrap.settings.loop_interval_seconds}
          pendingEntryLoopIntervalSeconds={
            configurationBootstrap.settings.pending_entry_loop_interval_seconds
          }
          pendingEntryMaxAttempts={
            configurationBootstrap.settings.pending_entry_max_attempts
          }
          pendingEntriesCount={configurationBootstrap.settings.pending_entries_count}
          pendingEntries={configurationBootstrap.settings.pending_entries}
          lastPendingEntryLoopAt={
            configurationBootstrap.settings.last_pending_entry_loop_at ?? null
          }
          lastPendingEntryLoopProcessed={
            configurationBootstrap.settings.last_pending_entry_loop_processed ?? 0
          }
          lastPendingEntryLoopFills={
            configurationBootstrap.settings.last_pending_entry_loop_fills ?? 0
          }
          lastPendingEntryLoopPending={
            configurationBootstrap.settings.last_pending_entry_loop_pending ?? 0
          }
          lastPendingEntryLoopCancelled={
            configurationBootstrap.settings.last_pending_entry_loop_cancelled ?? 0
          }
          lastPendingEntryLoopBlocked={
            configurationBootstrap.settings.last_pending_entry_loop_blocked ?? 0
          }
          lastPendingEntryLoopErrors={
            configurationBootstrap.settings.last_pending_entry_loop_errors ?? 0
          }
        />
      ) : null}

      <OpenPositionsPanel positions={model.openPositions} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <PositionEventsPanel lifecycles={positionsOrdersV2?.recent_position_lifecycles ?? []} />
        <WorkingOrdersPanel orders={model.workingOrders} />
      </div>

      <ExecutedOrdersPanel items={model.executedOrders} />

      <RecentClosedPositionsPanel positions={model.recentClosed} />
    </div>
  );
}