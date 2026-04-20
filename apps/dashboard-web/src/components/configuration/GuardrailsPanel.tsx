import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

export default function GuardrailsPanel({
  maxRiskPct,
  maxLeverage,
  minNotionalPct,
  limitFeePct,
  marketFeePct,
  marketSlippagePct,
}: {
  maxRiskPct: number;
  maxLeverage: number;
  minNotionalPct: number;
  limitFeePct: number;
  marketFeePct: number;
  marketSlippagePct: number;
}) {
  const items = [
    { label: "Max Risk %", value: `${maxRiskPct.toFixed(2)}%`, source: "Risk Engine Env" },
    { label: "Max Leverage", value: `${maxLeverage.toFixed(2)}x`, source: "Risk Engine Env" },
    { label: "Min Notional %", value: `${minNotionalPct.toFixed(2)}%`, source: "Risk Engine Env" },
    { label: "Limit Fee %", value: `${limitFeePct.toFixed(2)}%`, source: "Paper Execution Env" },
    { label: "Market Fee %", value: `${marketFeePct.toFixed(2)}%`, source: "Paper Execution Env" },
    { label: "Market Slippage %", value: `${marketSlippagePct.toFixed(2)}%`, source: "Paper Execution Env" },
  ];

  return (
    <GlassCard>
      <SectionTitle
        title="Risk & Execution Guardrails"
        subtitle="Global execution assumptions and risk constraints currently loaded by the platform"
      />

      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-[24px] border border-white/8 bg-white/5 p-4">
            <div className="text-sm text-white/40">{item.label}</div>
            <div className="mt-2 text-lg font-semibold text-white">{item.value}</div>
            <div className="mt-2 text-sm text-white/45">Read-only for v1 · {item.source}</div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}