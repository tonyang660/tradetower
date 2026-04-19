import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function WorkingOrdersPanel() {
  return (
    <GlassCard>
      <SectionTitle title="Working Orders" subtitle="Pending entries and active order state" />

      <div className="mt-3 rounded-[24px] border border-white/8 bg-white/5 p-6">
        <div className="text-sm font-medium text-white/75">Orders endpoint coming next</div>
        <div className="mt-2 text-sm text-white/50">
          This section is reserved for resting entries, TP/SL-linked orders, rejected or cancelled orders,
          and pending execution state.
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-sm text-white/50">
            Pending entry orders will appear here.
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-sm text-white/50">
            TP / SL order lifecycle will appear here.
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-sm text-white/50">
            Cancelled / rejected orders will appear here.
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/4 p-3 text-sm text-white/50">
            Linked order status and timestamps will appear here.
          </div>
        </div>
      </div>
    </GlassCard>
  );
}