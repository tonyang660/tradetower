import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import { RefreshCcw, Save, RotateCcw } from "lucide-react";

export default function ConfigurationControls({
  refreshing,
  saving,
  hasUnsavedChanges,
  onRefresh,
  onSave,
  onReset,
}: {
  refreshing: boolean;
  saving: boolean;
  hasUnsavedChanges: boolean;
  onRefresh: () => void;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <GlassCard>
      <SectionTitle title="Actions" subtitle="Review, refresh, save, or revert changes" />
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          onClick={onRefresh}
          disabled={refreshing || saving}
          className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <RefreshCcw size={16} />
            {refreshing ? "Refreshing..." : "Refresh"}
          </span>
        </button>

        <button
          onClick={onReset}
          disabled={!hasUnsavedChanges || saving}
          className="rounded-2xl border border-white/10 bg-white/8 px-4 py-2 text-sm text-white/80 transition hover:bg-white/12 hover:text-white disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <RotateCcw size={16} />
            Reset
          </span>
        </button>

        <button
          onClick={onSave}
          disabled={!hasUnsavedChanges || saving}
          className="rounded-2xl border border-emerald-400/15 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-200 transition hover:bg-emerald-500/15 disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <Save size={16} />
            {saving ? "Saving..." : "Save Changes"}
          </span>
        </button>
      </div>
    </GlassCard>
  );
}