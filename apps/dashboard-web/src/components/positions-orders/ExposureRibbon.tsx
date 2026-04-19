import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { ExposureRibbonSegment, PositionsAnalytics } from "../../types/positionsOrders";

function money(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function ExposureRibbon({
  analytics,
  segments,
}: {
  analytics: PositionsAnalytics;
  segments: ExposureRibbonSegment[];
}) {
  const total = segments.reduce((acc, s) => acc + s.value, 0);
  const topSegments = [...segments].slice(0, 3);

  return (
    <GlassCard>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <SectionTitle
          title="Exposure Ribbon"
          subtitle="Portfolio pressure, directional bias, and symbol concentration"
        />

        <div className="text-sm text-white/50">
          Net bias:{" "}
          <span className="font-medium text-white">
            {analytics.short_exposure_notional > analytics.long_exposure_notional
              ? "Short"
              : analytics.long_exposure_notional > analytics.short_exposure_notional
              ? "Long"
              : "Balanced"}
          </span>
        </div>
      </div>

      {segments.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          No open exposure. Ribbon will appear once positions are filled.
        </div>
      ) : (
        <>
          <div className="mt-4 overflow-hidden rounded-[24px] border border-white/8 bg-white/5 p-3">
            <div className="flex h-9 overflow-hidden rounded-full bg-white/6">
              {segments.map((segment) => {
                const widthPct = total > 0 ? (segment.value / total) * 100 : 0;
                const className =
                  segment.side === "long"
                    ? "bg-gradient-to-r from-emerald-500/70 to-emerald-300/70"
                    : "bg-gradient-to-r from-rose-500/70 to-rose-300/70";

                return (
                  <div
                    key={`${segment.side}-${segment.symbol}`}
                    className={`relative h-full ${className}`}
                    style={{ width: `${Math.max(widthPct, 4)}%` }}
                    title={`${segment.symbol} · ${segment.side} · ${money(segment.value)}`}
                  />
                );
              })}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {topSegments.map((segment) => (
              <div
                key={`${segment.side}-${segment.symbol}-legend`}
                className="rounded-full border border-white/8 bg-white/5 px-3 py-1.5 text-xs text-white/65"
              >
                {segment.symbol} · {segment.side} · {money(segment.value)}
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 text-sm text-white/60 sm:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
              Long exposure: <span className="text-white">{money(analytics.long_exposure_notional)}</span>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
              Short exposure: <span className="text-white">{money(analytics.short_exposure_notional)}</span>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
              Used margin: <span className="text-white">{money(analytics.total_margin_used)}</span>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
              Open PnL: <span className="text-white">{money(analytics.total_open_pnl)}</span>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
              Largest concentration:{" "}
              <span className="text-white">{topSegments[0]?.symbol ?? "-"}</span>
            </div>
          </div>
        </>
      )}
    </GlassCard>
  );
}