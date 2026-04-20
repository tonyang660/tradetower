import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function ChartCard({
  title,
  subtitle,
  right,
  children,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <GlassCard>
      <div className="flex items-start justify-between gap-4">
        <SectionTitle title={title} subtitle={subtitle} />
        {right ? <div className="text-sm text-white/45">{right}</div> : null}
      </div>
      <div className="mt-4">{children}</div>
    </GlassCard>
  );
}