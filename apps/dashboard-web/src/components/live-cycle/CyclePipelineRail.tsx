import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { PipelineStage } from "../../types/liveCycle";

function stageClasses(status: PipelineStage["status"]) {
  if (status === "ok") {
    return {
      badge: "bg-emerald-500/12 text-emerald-200 border-emerald-400/20",
      dot: "bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,0.7)]",
      ring: "border-emerald-400/12",
    };
  }
  if (status === "blocked") {
    return {
      badge: "bg-amber-500/12 text-amber-200 border-amber-400/20",
      dot: "bg-amber-300 shadow-[0_0_14px_rgba(252,211,77,0.65)]",
      ring: "border-amber-400/12",
    };
  }
  if (status === "error") {
    return {
      badge: "bg-rose-500/12 text-rose-200 border-rose-400/20",
      dot: "bg-rose-400 shadow-[0_0_14px_rgba(251,113,133,0.65)]",
      ring: "border-rose-400/12",
    };
  }
  return {
    badge: "bg-white/8 text-white/60 border-white/10",
    dot: "bg-white/30",
    ring: "border-white/8",
  };
}

export default function CyclePipelineRail({
  stages,
}: {
  stages: PipelineStage[];
}) {
  const width = 1200;
  const height = 120;
  const points = stages.map((_, i) => {
    const x = 70 + i * ((width - 140) / Math.max(stages.length - 1, 1));
    const y = i % 2 === 0 ? 58 : 68;
    return { x, y };
  });

  const path = points
    .map((p, i) => {
      if (i === 0) return `M ${p.x} ${p.y}`;
      const prev = points[i - 1];
      const cx1 = prev.x + (p.x - prev.x) * 0.35;
      const cy1 = prev.y;
      const cx2 = prev.x + (p.x - prev.x) * 0.65;
      const cy2 = p.y;
      return `C ${cx1} ${cy1}, ${cx2} ${cy2}, ${p.x} ${p.y}`;
    })
    .join(" ");

  return (
    <GlassCard>
      <SectionTitle title="Pipeline Rail" subtitle="Latest cycle stage-by-stage flow" />

      <div className="relative mt-4">
        <div className="pointer-events-none absolute inset-x-0 top-[78px] hidden h-[120px] xl:block">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-full w-full overflow-visible"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id="pipelineGlow" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="rgba(99,102,241,0.0)" />
                <stop offset="20%" stopColor="rgba(99,102,241,0.28)" />
                <stop offset="50%" stopColor="rgba(168,85,247,0.32)" />
                <stop offset="80%" stopColor="rgba(45,212,191,0.22)" />
                <stop offset="100%" stopColor="rgba(45,212,191,0.0)" />
              </linearGradient>
              <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <path
              d={path}
              fill="none"
              stroke="rgba(255,255,255,0.08)"
              strokeWidth="2"
            />
            <path
              d={path}
              fill="none"
              stroke="url(#pipelineGlow)"
              strokeWidth="4"
              filter="url(#softGlow)"
              strokeLinecap="round"
            />

            {points.map((p, i) => (
              <circle
                key={i}
                cx={p.x}
                cy={p.y}
                r="4.5"
                fill="rgba(255,255,255,0.65)"
                opacity="0.75"
              />
            ))}
          </svg>
        </div>

        <div className="grid gap-4 xl:grid-cols-8">
          {stages.map((stage) => {
            const styles = stageClasses(stage.status);

            return (
              <div
                key={stage.key}
                className={`relative rounded-[24px] border bg-white/5 p-4 ${styles.ring}`}
              >
                <div className="mb-3 flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${styles.dot}`} />
                  <span className="text-[11px] uppercase tracking-[0.22em] text-white/40">
                    {stage.label}
                  </span>
                </div>

                <div className="text-[2rem] font-semibold tracking-tight text-white">
                  {stage.primary_value}
                </div>
                <div className="mt-1 text-sm leading-snug text-white/45">
                  {stage.secondary_text}
                </div>

                <div className={`mt-4 inline-flex rounded-full border px-2.5 py-1 text-xs ${styles.badge}`}>
                  {stage.status.toUpperCase()}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </GlassCard>
  );
}