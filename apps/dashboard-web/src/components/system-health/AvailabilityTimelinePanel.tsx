import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { AvailabilityTimelineRow } from "../../types/systemHealth";
import { statusTone } from "../../lib/systemHealth";

export default function AvailabilityTimelinePanel({
  rows,
}: {
  rows: AvailabilityTimelineRow[];
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Availability Timeline"
        subtitle="Recent service status continuity"
      />

      <div className="mt-5 space-y-4">
        {rows.map((row) => (
          <div key={row.service_key} className="grid gap-2 xl:grid-cols-[180px_1fr] xl:items-center">
            <div className="text-sm font-medium text-white/70">{row.service_name}</div>

            <div className="grid grid-cols-12 gap-1 sm:grid-cols-24">
              {row.points.map((point, idx) => {
                const tone = statusTone(point.status);

                return (
                  <div
                    key={`${row.service_key}-${idx}`}
                    className={`h-5 rounded-md ${tone.dot} opacity-90`}
                    title={`${row.service_name} · ${point.label} · ${point.status}`}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}