import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import StrategyDecisionList from "./StrategyDecisionList";

function MetricCard({
  label,
  value,
  subtitle,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  subtitle: string;
  tone?: "neutral" | "green" | "violet" | "rose";
}) {
  const toneClass =
    tone === "green"
      ? "border-emerald-400/10 bg-emerald-500/6"
      : tone === "violet"
      ? "border-violet-400/10 bg-violet-500/6"
      : tone === "rose"
      ? "border-rose-400/10 bg-rose-500/6"
      : "border-white/8 bg-white/5";

  return (
    <div className={`rounded-[24px] border ${toneClass} p-4`}>
      <div className="text-[11px] uppercase tracking-[0.16em] text-white/35">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-sm text-white/55">{subtitle}</div>
    </div>
  );
}

export default function LatestCycleDetails({
  cycle,
}: {
  cycle: {
    cycle_id: string;
    started_at: string;
    completed_at: string | null;
    summary: Record<string, any>;
  } | null;
}) {
  if (!cycle) {
    return (
      <GlassCard>
        <SectionTitle title="Latest Cycle Details" subtitle="No cycle data available" />
      </GlassCard>
    );
  }

  const summary = cycle.summary ?? {};
  const candidateFilter = summary.candidate_filter ?? {};
  const strategyEngine = summary.strategy_engine ?? {};
  const maintenance = summary.maintenance ?? {};
  const refreshResults = summary.refresh_results ?? [];
  const errors = summary.errors ?? [];
  const strategyResults = strategyEngine.results ?? [];
  const riskEngine = summary.risk_engine ?? {};
  const finalEntryGate = summary.final_entry_gate ?? {};
  const paperExecution = summary.paper_execution ?? {};
  const pendingBefore = summary.pending_entries_before_cycle ?? 0;
  const pendingAfter = summary.pending_entries_after_cycle ?? 0;

  return (
    <div className="space-y-6">
      <GlassCard>
        <SectionTitle
          title="Latest Cycle Details"
          subtitle="Expanded inspection of the most recent cycle"
        />

        <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-[24px] border border-white/8 bg-white/5 p-5">
            <div className="text-xs uppercase tracking-[0.18em] text-white/35">Cycle Context</div>
            <div className="mt-3 break-all text-lg font-semibold text-white">{cycle.cycle_id}</div>

            <div className="mt-4 grid gap-3 text-sm text-white/60 sm:grid-cols-2">
              <div className="rounded-2xl border border-white/8 bg-white/4 p-3">
                <div className="text-white/35">Started</div>
                <div className="mt-1 text-white">
                  {new Date(cycle.started_at).toLocaleString()}
                </div>
              </div>

              <div className="rounded-2xl border border-white/8 bg-white/4 p-3">
                <div className="text-white/35">Completed</div>
                <div className="mt-1 text-white">
                  {cycle.completed_at
                    ? new Date(cycle.completed_at).toLocaleString()
                    : "In progress"}
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <MetricCard
              label="Refresh"
              value={refreshResults.length}
              subtitle="refresh entries across all symbols and timeframes"
            />

            <MetricCard
              label="Maintenance"
              value={maintenance.actions_triggered ?? 0}
              subtitle={`actions · ${maintenance.checked ?? 0} checked`}
            />

            <MetricCard
              label="Candidate Filter"
              value={(candidateFilter.candidates ?? []).length}
              subtitle={`candidates · ${(candidateFilter.rejected ?? []).length} rejected`}
            />

            <MetricCard
              label="Errors"
              value={errors.length}
              subtitle={errors.length === 0 ? "No cycle errors." : "Errors present in cycle."}
              tone={errors.length > 0 ? "rose" : "neutral"}
            />
          </div>
        </div>
      </GlassCard>

      <GlassCard>
        <SectionTitle
          title="Strategy Engine"
          subtitle="Scored symbols with downstream risk, gate, and execution status"
        />

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Analyzed"
            value={strategyEngine.analyzed ?? 0}
            subtitle="symbols evaluated"
          />

          <MetricCard
            label="Trade Candidates"
            value={strategyEngine.trade_candidates ?? strategyEngine.accepted ?? 0}
            subtitle={`risk checked · ${riskEngine.checked ?? 0}`}
            tone="green"
          />

          <MetricCard
            label="Observe"
            value={strategyEngine.observe_candidates ?? 0}
            subtitle="watchlist candidates"
            tone="violet"
          />

          <MetricCard
            label="No Trade"
            value={strategyEngine.no_trade ?? 0}
            subtitle="filtered by strategy"
          />

          <MetricCard
            label="Submitted"
            value={paperExecution.submitted ?? 0}
            subtitle={`fills · ${paperExecution.fills ?? 0}`}
            tone={(paperExecution.submitted ?? 0) > 0 ? "green" : "neutral"}
          />

          <MetricCard
            label="Pending Retries"
            value={paperExecution.pending_retries ?? 0}
            subtitle="deferred entry attempts"
          />

          <MetricCard
            label="Pending Before"
            value={pendingBefore}
            subtitle="open before cycle"
          />

          <MetricCard
            label="Pending After"
            value={pendingAfter}
            subtitle="open after cycle"
          />
        </div>

        <div className="mt-5">
          <StrategyDecisionList
            results={strategyResults}
            riskResults={riskEngine.results ?? []}
            gateResults={finalEntryGate.results ?? []}
            paperResults={paperExecution.results ?? []}
          />
        </div>
      </GlassCard>
    </div>
  );
}
