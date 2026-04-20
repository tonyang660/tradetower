import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { SystemHealthService } from "../../types/systemHealth";
import { formatLatency, statusTone, titleCaseStatus } from "../../lib/systemHealth";

export default function ServiceHealthGrid({
  services,
}: {
  services: SystemHealthService[];
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Service Health"
        subtitle="Reachability, latency, status code, and heartbeat checks"
      />

      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {services.map((service) => {
          const tone = statusTone(service.status);

          return (
            <div
              key={service.service_key}
              className={`rounded-[24px] border border-white/8 bg-white/5 p-4 ${tone.glow}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-base font-semibold text-white">
                    {service.service_name}
                  </div>
                  <div className="mt-1 text-sm text-white/40">
                    {service.service_key}
                  </div>
                </div>

                <div className={`rounded-full border px-2.5 py-1 text-xs ${tone.pill}`}>
                  {titleCaseStatus(service.status)}
                </div>
              </div>

              <div className="mt-4 grid gap-2 text-sm text-white/60">
                <div className="flex justify-between">
                  <span>Latency</span>
                  <span className="text-white">{formatLatency(service.latency_ms)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Status code</span>
                  <span className="text-white">{service.status_code ?? "-"}</span>
                </div>
                <div className="flex justify-between">
                  <span>Last checked</span>
                  <span className="text-white">
                    {service.last_checked_at ? new Date(service.last_checked_at).toLocaleTimeString() : "-"}
                  </span>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-white/8 bg-black/10 p-3 text-sm text-white/45">
                {service.message ?? "No active health warnings."}
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}