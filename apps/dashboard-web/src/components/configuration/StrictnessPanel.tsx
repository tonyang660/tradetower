import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import { strictnessLabel } from "../../lib/configuration";

export default function StrictnessPanel({
  strictScoreThreshold,
}: {
  strictScoreThreshold: number;
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Platform Strictness"
        subtitle="Global participation threshold before candidate ideas become strategy candidates"
      />

      <div className="mt-5 rounded-[24px] border border-white/8 bg-white/5 p-5">
        <div className="text-sm text-white/40">Strict Score Threshold</div>
        <div className="mt-3 flex items-end justify-between gap-4">
          <div>
            <div className="text-3xl font-semibold tracking-tight text-white">
              {strictScoreThreshold.toFixed(0)}
            </div>
            <div className="mt-1 text-sm text-white/45">
              {strictnessLabel(strictScoreThreshold)} · Read-only for v1
            </div>
          </div>

          <div className="rounded-full border border-violet-400/15 bg-violet-500/10 px-3 py-1.5 text-sm text-violet-200">
            Strategy Engine Env
          </div>
        </div>
      </div>
    </GlassCard>
  );
}