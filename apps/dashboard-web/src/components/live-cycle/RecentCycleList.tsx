import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { RecentCycleCard } from "../../types/liveCycle";

export default function RecentCycleList({
  cycles,
}: {
  cycles: RecentCycleCard[];
}) {
  return (
    <GlassCard>
      <SectionTitle title="Recent Cycle History" subtitle="Compact history of recent pipeline runs" />

      <div className="mt-2 space-y-3">
        {cycles.length === 0 ? (
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/50">
            No cycle history available.
          </div>
        ) : (
          cycles.map((cycle) => (
            <div
              key={cycle.cycle_id}
              className="grid gap-3 rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/60 transition hover:bg-white/7 xl:grid-cols-[1.2fr_repeat(6,0.7fr)]"
            >
              <div>
                <div className="font-medium text-white">{cycle.cycle_id}</div>
                <div className="mt-1 text-xs text-white/40">
                  {new Date(cycle.started_at).toLocaleString()}
                </div>
              </div>

              <div>
                <div className="text-white/40">Duration</div>
                <div className="mt-1 text-white">{cycle.duration_seconds ?? "-"}s</div>
              </div>

              <div>
                <div className="text-white/40">Refreshed</div>
                <div className="mt-1 text-white">{cycle.refreshed_symbols_count}</div>
              </div>

              <div>
                <div className="text-white/40">Candidates</div>
                <div className="mt-1 text-white">{cycle.candidates_found}</div>
              </div>

              <div>
                <div className="text-white/40">Analyzed</div>
                <div className="mt-1 text-white">{cycle.strategy_analyzed}</div>
              </div>

              <div>
                <div className="text-white/40">Accepted</div>
                <div className="mt-1 text-white">{cycle.strategy_accepted}</div>
              </div>

              <div>
                <div className="text-white/40">Errors</div>
                <div className="mt-1 text-white">{cycle.error_count}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}