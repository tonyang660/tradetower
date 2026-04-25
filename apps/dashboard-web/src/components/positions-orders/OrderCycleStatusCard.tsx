import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

type PendingEntryItem = {
  symbol: string;
  attempt_number: number;
  updated_at?: string;
  order_type?: string;
  position_side?: string;
  entry_price?: number;
};

export default function OrderCycleStatusCard({
  autoLoopEnabled,
  loopIntervalSeconds,
  pendingEntryLoopIntervalSeconds,
  pendingEntryMaxAttempts,
  pendingEntriesCount,
  pendingEntries,
}: {
  autoLoopEnabled: boolean;
  loopIntervalSeconds: number;
  pendingEntryLoopIntervalSeconds: number;
  pendingEntryMaxAttempts: number;
  pendingEntriesCount: number;
  pendingEntries: PendingEntryItem[];
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Order Cycle Status"
        subtitle="Dedicated pending-entry retry loop"
      />

      <div className="mt-3 grid gap-4 md:grid-cols-4">
        <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
          <div className="text-xs text-white/40">Main Cycle</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {loopIntervalSeconds}s
          </div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
          <div className="text-xs text-white/40">Order Cycle</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {pendingEntryLoopIntervalSeconds}s
          </div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
          <div className="text-xs text-white/40">Max Attempts</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {pendingEntryMaxAttempts}
          </div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
          <div className="text-xs text-white/40">Pending Entries</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {pendingEntriesCount}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-2xl border border-white/8 bg-white/5 p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm text-white/70">Scheduler state</div>
          <div
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              autoLoopEnabled
                ? "bg-emerald-500/15 text-emerald-200"
                : "bg-amber-500/15 text-amber-200"
            }`}
          >
            {autoLoopEnabled ? "Enabled" : "Disabled"}
          </div>
        </div>

        {pendingEntries.length === 0 ? (
          <div className="mt-4 text-sm text-white/45">
            No pending entry orders currently being retried.
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {pendingEntries.map((item) => (
              <div
                key={item.symbol}
                className="rounded-xl border border-white/8 bg-black/10 px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-white">{item.symbol}</div>
                  <div className="text-white/60">
                    Attempt {item.attempt_number} / {pendingEntryMaxAttempts}
                  </div>
                </div>
                <div className="mt-1 text-xs text-white/45">
                  {item.position_side} · {item.order_type} ·{" "}
                  {item.updated_at
                    ? new Date(item.updated_at).toLocaleString()
                    : "No timestamp"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </GlassCard>
  );
}