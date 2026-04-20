import { useMemo } from "react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

type ValidationMap = Record<
  string,
  {
    state: "valid" | "invalid" | "pending";
    message?: string;
  }
>;

function pillTone(state?: "valid" | "invalid" | "pending") {
  if (state === "valid") return "border-emerald-400/15 bg-emerald-500/10 text-emerald-200";
  if (state === "invalid") return "border-rose-400/15 bg-rose-500/10 text-rose-200";
  if (state === "pending") return "border-amber-400/15 bg-amber-500/10 text-amber-200";
  return "border-white/10 bg-white/8 text-white/75";
}

export default function SymbolUniverseManager({
  symbols,
  symbolInput,
  validationMap,
  onInputChange,
  onAddSymbol,
  onRemoveSymbol,
}: {
  symbols: string[];
  symbolInput: string;
  validationMap: ValidationMap;
  onInputChange: (value: string) => void;
  onAddSymbol: () => void;
  onRemoveSymbol: (symbol: string) => void;
}) {
  const sortedSymbols = useMemo(() => [...symbols].sort(), [symbols]);

  return (
    <GlassCard>
      <SectionTitle
        title="Symbol Universe"
        subtitle="Define the active tradable universe and validate symbols against Bitget"
      />

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="flex-1">
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              value={symbolInput}
              onChange={(e) => onInputChange(e.target.value)}
              placeholder="Add symbol, e.g. DOGEUSDT"
              className="flex-1 rounded-2xl border border-white/10 bg-white/6 px-4 py-3 text-white outline-none placeholder:text-white/30"
            />
            <button
              onClick={onAddSymbol}
              className="rounded-2xl border border-violet-400/15 bg-violet-500/10 px-4 py-3 text-sm font-medium text-violet-200 transition hover:bg-violet-500/15"
            >
              Validate & Add
            </button>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            {sortedSymbols.length === 0 ? (
              <div className="rounded-2xl border border-white/8 bg-white/5 px-4 py-3 text-sm text-white/45">
                No active symbols configured.
              </div>
            ) : (
              sortedSymbols.map((symbol) => {
                const validation = validationMap[symbol];

                return (
                  <div
                    key={symbol}
                    className="rounded-[22px] border border-white/8 bg-white/5 px-4 py-3"
                  >
                    <div className="flex items-center gap-3">
                      <div className="text-sm font-semibold text-white">{symbol}</div>
                      <div className={`rounded-full border px-2 py-1 text-[11px] ${pillTone(validation?.state ?? "valid")}`}>
                        {validation?.state === "pending"
                          ? "Pending"
                          : validation?.state === "invalid"
                          ? "Invalid"
                          : "Valid"}
                      </div>
                      <button
                        onClick={() => onRemoveSymbol(symbol)}
                        className="rounded-full border border-white/10 bg-white/8 px-2 py-1 text-[11px] text-white/70 transition hover:bg-white/12 hover:text-white"
                      >
                        Remove
                      </button>
                    </div>

                    {validation?.message ? (
                      <div className="mt-2 text-xs text-white/40">{validation.message}</div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </GlassCard>
  );
}