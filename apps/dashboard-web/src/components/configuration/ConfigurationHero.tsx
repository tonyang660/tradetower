import GlassCard from "../ui/GlassCard";

export default function ConfigurationHero({
  environment,
  generatedAt,
  hasUnsavedChanges,
}: {
  environment: string;
  generatedAt: string;
  hasUnsavedChanges: boolean;
}) {
  return (
    <GlassCard className="relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(168,85,247,0.11),transparent_34%),radial-gradient(circle_at_78%_24%,rgba(56,189,248,0.08),transparent_28%)]" />
      <div className="relative flex h-full flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] text-white/38">
            Global Configuration
          </div>
          <div className="mt-3 text-3xl font-semibold tracking-tight text-white">
            Configuration
          </div>
          <div className="mt-3 max-w-2xl text-base text-white/55">
            Global runtime controls for scheduler cadence, symbol universe, and platform-wide thresholds.
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-white/75">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">Environment</div>
            <div className="mt-1 text-lg font-semibold text-white">{environment}</div>
          </div>

          <div
            className={`rounded-[22px] border px-4 py-3 ${
              hasUnsavedChanges
                ? "border-amber-400/15 bg-amber-500/10 text-amber-200"
                : "border-emerald-400/15 bg-emerald-500/10 text-emerald-200"
            }`}
          >
            <div className="text-xs uppercase tracking-[0.18em] opacity-80">Save State</div>
            <div className="mt-1 text-lg font-semibold">
              {hasUnsavedChanges ? "Unsaved Changes" : "Saved"}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/6 px-4 py-3 text-white/75 sm:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">Loaded</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {new Date(generatedAt).toLocaleString()}
            </div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}