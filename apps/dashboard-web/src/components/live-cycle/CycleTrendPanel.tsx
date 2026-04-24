import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import MiniBarChart from "../charts/MiniBarChart";

type TrendPoint = { label: string; value: number };

export default function CycleTrendPanel({
  trends,
}: {
  trends: {
    candidates_per_cycle: TrendPoint[];
    accepted_per_cycle?: TrendPoint[];
    trade_candidates_per_cycle?: TrendPoint[];
    observe_per_cycle?: TrendPoint[];
    fills_per_cycle: TrendPoint[];
    errors_per_cycle: TrendPoint[];
  };
}) {
  const acceptedLikeSeries =
    trends.accepted_per_cycle ?? trends.trade_candidates_per_cycle ?? [];

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <GlassCard>
        <SectionTitle title="Candidates per Cycle" subtitle="Recent opportunity flow" />
        <MiniBarChart data={trends.candidates_per_cycle} />
      </GlassCard>

      <GlassCard>
        <SectionTitle title="Accepted per Cycle" subtitle="Strategy engine approvals" />
        <MiniBarChart data={acceptedLikeSeries} />
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