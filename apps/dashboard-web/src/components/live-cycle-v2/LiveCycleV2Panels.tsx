import { AlertTriangle, Activity, Boxes, ListChecks, RadioTower } from "lucide-react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { DashboardV2LiveResponse } from "../../types/dashboardLiveV2";

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}

function getCycleShell(latest: Record<string, any> | null | undefined) {
  return latest?.cycle ?? latest ?? {};
}

function getCycleSummary(latest: Record<string, any> | null | undefined) {
  return getCycleShell(latest)?.summary ?? {};
}

function miniCount(value: unknown) {
  if (typeof value === "number") return value;
  if (Array.isArray(value)) return value.length;
  return 0;
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

function ServicePill({ label, ok }: { label: string; ok?: boolean }) {
  return (
    <span
      className={`inline-flex rounded-full border px-3 py-1 text-xs ${
        ok
          ? "border-emerald-400/15 bg-emerald-500/10 text-emerald-200"
          : "border-rose-400/15 bg-rose-500/10 text-rose-200"
      }`}
    >
      {label}: {ok ? "OK" : "Issue"}
    </span>
  );
}

export default function LiveCycleV2Panels({ data }: { data: DashboardV2LiveResponse | null }) {
  if (!data) {
    return (
      <GlassCard>
        <SectionTitle title="Live Monitor V2" subtitle="Waiting for dashboard-api live aggregation" />
        <div className="rounded-2xl border border-white/8 bg-white/5 p-5 text-sm text-white/50">
          V2 live data has not loaded yet. The classic live cycle monitor remains active below.
        </div>
      </GlassCard>
    );
  }

  const cycle = getCycleShell(data.latest_cycle);
  const summary = getCycleSummary(data.latest_cycle);

  const refreshed = miniCount(summary.refreshed_symbols_count ?? summary.refreshed_symbols);
  const candidates = miniCount(summary.candidate_filter?.candidates ?? summary.candidate_filter?.candidate_count ?? summary.candidates);
  const analyzed = miniCount(summary.strategy_engine?.analyzed ?? summary.strategy_engine?.results ?? summary.analyzed);
  const accepted = miniCount(summary.strategy_engine?.accepted ?? summary.strategy_engine?.accepted_count ?? summary.accepted);

  return (
    <div className="space-y-5">
      {data.partial ? (
        <GlassCard className="border-amber-300/20 bg-amber-500/8">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl bg-amber-400/10 p-2 text-amber-200">
              <AlertTriangle size={18} />
            </div>
            <div>
              <div className="font-semibold text-amber-100">Live Monitor V2 loaded with partial data</div>
              <div className="mt-1 text-sm text-amber-100/65">
                One or more evaluator live sources failed, but available cycle context will still render.
              </div>
            </div>
          </div>
        </GlassCard>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
        <GlassCard>
          <SectionTitle title="Live Cycle V2" subtitle="Aggregated from dashboard-api /dashboard/v2/live" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MiniStat label="Cycle" value={String(cycle.cycle_id ?? "-").slice(0, 14)} hint={formatDate(cycle.completed_at ?? cycle.started_at)} />
            <MiniStat label="Refreshed" value={String(refreshed ?? 0)} />
            <MiniStat label="Candidates" value={String(candidates ?? 0)} />
            <MiniStat label="Accepted" value={String(accepted ?? 0)} hint={`${analyzed ?? 0} analyzed`} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <ServicePill label="Latest Cycle" ok={data.services?.latest_cycle?.ok} />
            <ServicePill label="Cycle History" ok={data.services?.cycle_history?.ok} />
            <ServicePill label="Open Positions Source" ok={data.services?.open_positions?.ok} />
            <ServicePill label="Open Orders Source" ok={data.services?.open_orders?.ok} />
          </div>
        </GlassCard>

        <GlassCard>
          <SectionTitle title="Live State Counts" subtitle="Context only; details stay on Positions & Orders" />
          <div className="grid gap-3">
            <MiniStat label="Open Positions" value={String(data.open_positions?.length ?? 0)} />
            <MiniStat label="Open Orders" value={String(data.open_orders?.length ?? 0)} />
            <MiniStat label="Recent Cycles" value={String(data.cycles?.length ?? 0)} />
          </div>
        </GlassCard>
      </div>

      <GlassCard>
        <SectionTitle title="V2 Monitor Notes" subtitle="How this panel is wired" />
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/55">
            <RadioTower className="mb-2 text-violet-200" size={18} />
            Uses <span className="text-white/75">/dashboard/v2/live</span> as the dashboard-web source.
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/55">
            <ListChecks className="mb-2 text-violet-200" size={18} />
            Keeps the classic cycle rail and details below as the main monitor UI.
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/55">
            <Boxes className="mb-2 text-violet-200" size={18} />
            Position/order counts are context only; detailed rows belong on Positions & Orders.
          </div>
        </div>

        <div className="mt-4 inline-flex rounded-full border border-white/10 bg-white/7 px-3 py-1 text-xs text-white/55">
          <Activity size={13} className="mr-2" />
          {data.dashboard_aggregation_v2_version}
        </div>
      </GlassCard>
    </div>
  );
}
