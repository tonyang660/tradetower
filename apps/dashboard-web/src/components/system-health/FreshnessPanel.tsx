import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { SystemHealthFreshness } from "../../types/systemHealth";
import { formatRelativeAge, titleCaseStatus } from "../../lib/systemHealth";

export default function FreshnessPanel({
  freshness,
}: {
  freshness: SystemHealthFreshness;
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Freshness"
        subtitle="Cycle age, dataset staleness, and scheduler state"
      />

      <div className="mt-5 space-y-3 text-sm text-white/65">
        <div className="flex justify-between">
          <span>Last scheduler cycle</span>
          <span className="text-white">
            {freshness.last_scheduler_cycle_at
              ? new Date(freshness.last_scheduler_cycle_at).toLocaleString()
              : "-"}
          </span>
        </div>

        <div className="flex justify-between">
          <span>Cycle age</span>
          <span className="text-white">{formatRelativeAge(freshness.last_cycle_age_seconds)}</span>
        </div>

        <div className="flex justify-between">
          <span>Overview freshness</span>
          <span className="text-white">
            {freshness.overview_generated_at
              ? new Date(freshness.overview_generated_at).toLocaleTimeString()
              : "-"}
          </span>
        </div>

        <div className="flex justify-between">
          <span>Performance freshness</span>
          <span className="text-white">
            {freshness.performance_generated_at
              ? new Date(freshness.performance_generated_at).toLocaleTimeString()
              : "-"}
          </span>
        </div>

        <div className="mt-4 rounded-2xl border border-white/8 bg-white/5 p-4">
          <div className="text-[11px] uppercase tracking-[0.18em] text-white/35">
            Scheduler
          </div>
          <div className="mt-2 text-base font-medium text-white">
            {titleCaseStatus(freshness.scheduler_auto_loop_enabled ? "enabled" : "disabled")}
          </div>
          <div className="mt-1 text-sm text-white/45">
            Interval: {freshness.scheduler_loop_interval_seconds ?? "-"}s
          </div>
        </div>
      </div>
    </GlassCard>
  );
}