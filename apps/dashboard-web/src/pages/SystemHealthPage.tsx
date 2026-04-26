import { useEffect, useState } from "react";
import type { SystemHealthBootstrapResponse } from "../types/systemHealth";
import { fetchSystemHealthBootstrap } from "../lib/api";
import PlatformStatusHero from "../components/system-health/PlatformStatusHero";
import SystemHealthControls from "../components/system-health/SystemHealthControls";
import SystemHealthSummaryStrip from "../components/system-health/SystemHealthSummaryStrip";
import OperationalFlowPanel from "../components/system-health/OperationalFlowPanel";
import ServiceHealthGrid from "../components/system-health/ServiceHealthGrid";
import AvailabilityTimelinePanel from "../components/system-health/AvailabilityTimelinePanel";
import FreshnessPanel from "../components/system-health/FreshnessPanel";
import IssuesPanel from "../components/system-health/IssuesPanel";
import OrderCycleStatusCard from "../components/positions-orders/OrderCycleStatusCard";

export default function SystemHealthPage() {
  const [data, setData] = useState<SystemHealthBootstrapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchSystemHealthBootstrap(1);
      setData(payload);
      setError(null);
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
    return <div className="text-white/70">Loading system health...</div>;
  }

  if (error || !data) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load system health. {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[1.45fr_0.75fr]">
        <PlatformStatusHero overall={data.overall} generatedAt={data.generated_at} />
        <SystemHealthControls
          refreshing={refreshing}
          autoRefresh={autoRefresh}
          onRefresh={() => load(false, true)}
          onToggleAutoRefresh={() => setAutoRefresh((v) => !v)}
        />
      </div>

      <SystemHealthSummaryStrip summary={data.summary_strip} />

      {data.order_cycle ? (
        <OrderCycleStatusCard
          autoLoopEnabled={data.freshness.scheduler_auto_loop_enabled ?? false}
          loopIntervalSeconds={data.freshness.scheduler_loop_interval_seconds ?? 300}
          pendingEntryLoopIntervalSeconds={
            data.order_cycle?.pending_entry_loop_interval_seconds ?? 60
          }
          pendingEntryMaxAttempts={
            data.order_cycle?.pending_entry_max_attempts ?? 15
          }
          pendingEntriesCount={data.order_cycle?.pending_entries_count ?? 0}
          pendingEntries={data.order_cycle?.pending_entries ?? []}
          lastPendingEntryLoopAt={data.order_cycle?.last_pending_entry_loop_at ?? null}
          lastPendingEntryLoopProcessed={
            data.order_cycle?.last_pending_entry_loop_processed ?? 0
          }
          lastPendingEntryLoopFills={
            data.order_cycle?.last_pending_entry_loop_fills ?? 0
          }
          lastPendingEntryLoopPending={
            data.order_cycle?.last_pending_entry_loop_pending ?? 0
          }
          lastPendingEntryLoopCancelled={
            data.order_cycle?.last_pending_entry_loop_cancelled ?? 0
          }
          lastPendingEntryLoopBlocked={
            data.order_cycle?.last_pending_entry_loop_blocked ?? 0
          }
          lastPendingEntryLoopErrors={
            data.order_cycle?.last_pending_entry_loop_errors ?? 0
          }
        />
      ) : null}      

      <OperationalFlowPanel nodes={data.dependency_flow} />

      <ServiceHealthGrid services={data.services} />

      <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
        <AvailabilityTimelinePanel rows={data.availability_timeline} />
        <FreshnessPanel freshness={data.freshness} />
      </div>

      <IssuesPanel issues={data.issues} />
    </div>
  );
}