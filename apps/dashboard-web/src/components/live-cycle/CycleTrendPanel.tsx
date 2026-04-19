import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import MiniBarChart from "../charts/MiniBarChart";

export default function CycleTrendPanel({
  trends,
}: {
  trends: {
    candidates_per_cycle: { label: string; value: number }[];
    accepted_per_cycle: { label: string; value: number }[];
    fills_per_cycle: { label: string; value: number }[];
    errors_per_cycle: { label: string; value: number }[];
  };
}) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <GlassCard>
        <SectionTitle title="Candidates per Cycle" subtitle="Recent opportunity flow" />
        <MiniBarChart data={trends.candidates_per_cycle} />
      </GlassCard>

      <GlassCard>
        <SectionTitle title="Accepted per Cycle" subtitle="Strategy engine approvals" />
        <MiniBarChart data={trends.accepted_per_cycle} />
      </GlassCard>

      <GlassCard>
        <SectionTitle title="Fills per Cycle" subtitle="Execution outcomes" />
        <MiniBarChart data={trends.fills_per_cycle} />
      </GlassCard>

      <GlassCard>
        <SectionTitle title="Errors per Cycle" subtitle="Operational fault visibility" />
        <MiniBarChart data={trends.errors_per_cycle} />
      </GlassCard>
    </div>
  );
}