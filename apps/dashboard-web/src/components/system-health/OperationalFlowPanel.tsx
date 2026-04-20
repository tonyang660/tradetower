import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { DependencyFlowNode } from "../../types/systemHealth";
import { statusTone } from "../../lib/systemHealth";

export default function OperationalFlowPanel({
  nodes,
}: {
  nodes: DependencyFlowNode[];
}) {
  return (
    <GlassCard className="overflow-hidden">
      <SectionTitle
        title="Operational Flow"
        subtitle="Core platform dependency line and service continuity"
      />

      <div className="relative mt-5">
        <div className="pointer-events-none absolute left-10 right-10 top-1/2 hidden h-[2px] -translate-y-1/2 bg-gradient-to-r from-cyan-400/20 via-violet-400/25 to-emerald-400/20 lg:block" />

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6 2xl:grid-cols-11">
          {nodes.map((node) => {
            const tone = statusTone(node.status);

            return (
              <div
                key={node.service_key}
                className={`relative rounded-[24px] border border-white/8 bg-white/5 p-4 ${tone.glow}`}
              >
                <div className="mb-3 flex items-center gap-2">
                  <div className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} />
                  <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">
                    {node.status}
                  </div>
                </div>

                <div className="text-sm font-medium leading-snug text-white">
                  {node.service_name}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </GlassCard>
  );
}