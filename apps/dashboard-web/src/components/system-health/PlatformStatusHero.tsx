import GlassCard from "../ui/GlassCard";
import type { SystemHealthOverall } from "../../types/systemHealth";
import { formatLatency, overallTone, titleCaseStatus } from "../../lib/systemHealth";

export default function PlatformStatusHero({
  overall,
  generatedAt,
}: {
  overall: SystemHealthOverall;
  generatedAt: string;
}) {
  const tone = overallTone(overall.status);

  return (
    <GlassCard className="relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(168,85,247,0.11),transparent_34%),radial-gradient(circle_at_78%_24%,rgba(56,189,248,0.08),transparent_28%)]" />
      <div className="relative flex h-full flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] text-white/38">
            Platform Status
          </div>
          <div className="mt-3 flex items-center gap-4">
            <div className={`h-4 w-4 rounded-full ${tone.beacon} animate-pulse`} />
            <div className={`text-3xl font-semibold tracking-tight ${tone.text}`}>
              {titleCaseStatus(overall.status)}
            </div>
          </div>
          <div className="mt-3 max-w-2xl text-base text-white/55">
            {overall.message}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className={`rounded-[22px] border px-4 py-3 ${tone.pill}`}>
            <div className="text-xs uppercase tracking-[0.18em] opacity-80">Healthy</div>
            <div className="mt-1 text-lg font-semibold">
              {overall.healthy_services} / {overall.total_services}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-white/75">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">Avg Latency</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {formatLatency(overall.average_latency_ms)}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-white/75">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">Incidents</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {overall.incidents_open}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-white/75">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">Updated</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {new Date(generatedAt).toLocaleTimeString()}
            </div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}