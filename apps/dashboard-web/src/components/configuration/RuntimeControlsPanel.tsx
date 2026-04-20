import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import { prettySeconds } from "../../lib/configuration";

export default function RuntimeControlsPanel({
  autoLoopEnabled,
  loopIntervalSeconds,
  mtmEnabled,
  mtmIntervalSeconds,
  onToggleAutoLoop,
}: {
  autoLoopEnabled: boolean;
  loopIntervalSeconds: number;
  mtmEnabled: boolean;
  mtmIntervalSeconds: number;
  onToggleAutoLoop: (enabled: boolean) => void;
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Runtime Controls"
        subtitle="Platform cadence, scheduler state, and mark-to-market refresh behavior"
      />

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
          <div className="text-sm text-white/40">Auto Loop</div>
          <div className="mt-3 flex items-center justify-between gap-4">
            <div>
              <div className="text-lg font-semibold text-white">
                {autoLoopEnabled ? "Enabled" : "Disabled"}
              </div>
              <div className="mt-1 text-sm text-white/45">
                Live-editable
              </div>
            </div>

            <button
              onClick={() => onToggleAutoLoop(!autoLoopEnabled)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                autoLoopEnabled
                  ? "border border-emerald-400/15 bg-emerald-500/10 text-emerald-200"
                  : "border border-white/10 bg-white/8 text-white/75"
              }`}
            >
              {autoLoopEnabled ? "Turn Off" : "Turn On"}
            </button>
          </div>
        </div>

        <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
          <div className="text-sm text-white/40">Cycle Interval</div>
          <div className="mt-3 text-lg font-semibold text-white">{loopIntervalSeconds}s</div>
          <div className="mt-1 text-sm text-white/45">
            {prettySeconds(loopIntervalSeconds)} · Read-only for v1
          </div>
        </div>

        <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
          <div className="text-sm text-white/40">MTM Auto Refresh</div>
          <div className="mt-3 text-lg font-semibold text-white">
            {mtmEnabled ? "Enabled" : "Disabled"}
          </div>
          <div className="mt-1 text-sm text-white/45">Read-only for v1</div>
        </div>

        <div className="rounded-[24px] border border-white/8 bg-white/5 p-4">
          <div className="text-sm text-white/40">MTM Refresh Interval</div>
          <div className="mt-3 text-lg font-semibold text-white">{mtmIntervalSeconds}s</div>
          <div className="mt-1 text-sm text-white/45">
            {prettySeconds(mtmIntervalSeconds)} · Read-only for v1
          </div>
        </div>
      </div>
    </GlassCard>
  );
}