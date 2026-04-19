import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import StrategyDecisionList from "./StrategyDecisionList";

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

  return (
    <div className="space-y-6">
      <GlassCard>
        <SectionTitle
          title="Latest Cycle Details"
          subtitle="Expanded inspection of the most recent cycle"
        />

        <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <div className="space-y-4">
            <div className="rounded-[24px] border border-white/8 bg-white/5 p-5">
              <div className="text-xs uppercase tracking-[0.18em] text-white/35">Cycle Context</div>
              <div className="mt-3 text-lg font-semibold text-white">{cycle.cycle_id}</div>

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
              <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-white/35">Refresh</div>
                <div className="mt-2 text-2xl font-semibold text-white">{refreshResults.length}</div>
                <div className="mt-1 text-sm text-white/55">
                  refresh entries across all symbols and timeframes
                </div>
              </div>

              <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-white/35">Maintenance</div>
                <div className="mt-2 text-2xl font-semibold text-white">
                  {maintenance.actions_triggered ?? 0}
                </div>
                <div className="mt-1 text-sm text-white/55">
                  actions · {maintenance.checked ?? 0} checked
                </div>
              </div>

              <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-white/35">Candidate Filter</div>
                <div className="mt-2 text-2xl font-semibold text-white">
                  {(candidateFilter.candidates ?? []).length}
                </div>
                <div className="mt-1 text-sm text-white/55">
                  candidates · {(candidateFilter.rejected ?? []).length} rejected
                </div>
              </div>

              <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-white/35">Errors</div>
                <div className="mt-2 text-2xl font-semibold text-white">{errors.length}</div>
                <div className="mt-1 text-sm text-white/55">
                  {errors.length === 0 ? "No cycle errors." : "Errors present in cycle."}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
            <div className="mb-4">
              <div className="text-xs uppercase tracking-[0.16em] text-white/35">Strategy Engine</div>
              <div className="mt-2 text-sm text-white/55">
                Analyzed: {strategyEngine.analyzed ?? 0} · Accepted: {strategyEngine.accepted ?? 0}
              </div>
            </div>

            <StrategyDecisionList results={strategyResults} />
          </div>
        </div>
      </GlassCard>
    </div>
  );
}