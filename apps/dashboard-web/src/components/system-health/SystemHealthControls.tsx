import { RefreshCcw } from "lucide-react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function SystemHealthControls({
  refreshing,
  autoRefresh,
  onRefresh,
  onToggleAutoRefresh,
}: {
  refreshing: boolean;
  autoRefresh: boolean;
  onRefresh: () => void;
  onToggleAutoRefresh: () => void;
}) {
  return (
    <GlassCard>
      <SectionTitle title="Controls" subtitle="Refresh and monitoring behavior" />
      <div className="flex flex-wrap gap-3">
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <RefreshCcw size={16} />
            {refreshing ? "Refreshing..." : "Refresh Now"}
          </span>
        </button>

        <button
          onClick={onToggleAutoRefresh}
          className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white"
        >
          Auto-refresh: {autoRefresh ? "On" : "Off"}
        </button>
      </div>
    </GlassCard>
  );
}