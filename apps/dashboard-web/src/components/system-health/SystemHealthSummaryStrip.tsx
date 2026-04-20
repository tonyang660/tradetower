import MetricCard from "../ui/MetricCard";
import type { SystemHealthSummaryStrip } from "../../types/systemHealth";
import { formatLatency, formatRelativeAge, titleCaseStatus } from "../../lib/systemHealth";

export default function SystemHealthSummaryStrip({
  summary,
}: {
  summary: SystemHealthSummaryStrip;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
      <MetricCard
        label="Overall Status"
        value={titleCaseStatus(summary.overall_status)}
        hint="Global platform state"
      />
      <MetricCard
        label="Healthy Services"
        value={String(summary.healthy_services)}
        hint="Core services currently healthy"
      />
      <MetricCard
        label="Average Latency"
        value={formatLatency(summary.average_latency_ms)}
        hint="Mean health-check response time"
      />
      <MetricCard
        label="Scheduler"
        value={titleCaseStatus(summary.scheduler_state)}
        hint="Auto loop runtime state"
      />
      <MetricCard
        label="Last Cycle Age"
        value={formatRelativeAge(summary.last_cycle_age_seconds)}
        hint="Freshness of last completed cycle"
      />
      <MetricCard
        label="Issues Open"
        value={String(summary.issues_open)}
        hint="Warnings and critical incidents"
      />
    </div>
  );
}