import { useState } from "react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import { ChevronDown, ChevronUp } from "lucide-react";

type StrategyResult = {
  symbol: string;
  decision: string;
  regime: string;
  macro_bias: string;
  selected_strategy: string;
  best_strategy_score: number;
  setup_confidence?: number;
  decision_confidence?: number;
  strategy_scores?: Record<string, number>;
  reason_tags?: string[];
  score_breakdown?: Record<string, any>;
};

const TREND_MAX_SCORES: Record<string, number> = {
  macro_alignment: 15,
  htf_structure_quality: 20,
  ema_strength: 15,
  bos_quality_freshness: 15,
  pullback_quality: 15,
  momentum_quality: 10,
  volatility_suitability: 10,
};

const MEAN_MAX_SCORES: Record<string, number> = {
  range_quality: 25,
  boundary_proximity: 20,
  rsi_stretch: 15,
  trend_weakness: 15,
  anti_breakout_filter: 10,
  volatility_suitability: 5,
  invalidation_clarity: 10,
};

function prettyLabel(key: string) {
  return key
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function StrategyDecisionList({
  results,
}: {
  results: StrategyResult[];
}) {
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);

  if (results.length === 0) {
    return (
      <GlassCard>
        <SectionTitle title="Strategy Decisions" subtitle="No analyzed symbols in this cycle" />
      </GlassCard>
    );
  }

  return (
    <GlassCard>
      <SectionTitle title="Strategy Decisions" subtitle="Analyzed symbols and score breakdown" />

      <div className="space-y-3">
        {results.map((item) => {
          const isOpen = openSymbol === item.symbol;

          const selectedBreakdown =
            item.selected_strategy === "trend_following"
              ? item.score_breakdown?.trend_following ?? item.score_breakdown ?? {}
              : item.selected_strategy === "mean_reversion"
              ? item.score_breakdown?.mean_reversion ?? item.score_breakdown ?? {}
              : item.score_breakdown?.[item.selected_strategy] ?? {};

          const maxScoreMap =
            item.selected_strategy === "trend_following"
              ? TREND_MAX_SCORES
              : item.selected_strategy === "mean_reversion"
              ? MEAN_MAX_SCORES
              : {};

          return (
            <div
              key={item.symbol}
              className="rounded-2xl border border-white/8 bg-white/5 p-4"
            >
              <button
                onClick={() => setOpenSymbol(isOpen ? null : item.symbol)}
                className="flex w-full items-center justify-between text-left"
              >
                <div>
                  <div className="flex items-center gap-3">
                    <div className="text-lg font-semibold text-white">{item.symbol}</div>
                    <div
                      className={`rounded-full px-2 py-1 text-xs ${
                        item.decision === "no_trade"
                          ? "bg-white/10 text-white/65"
                          : item.decision === "observe"
                          ? "bg-violet-500/12 text-violet-200"
                          : item.decision === "long"
                          ? "bg-emerald-500/12 text-emerald-200"
                          : "bg-rose-500/12 text-rose-200"
                      }`}
                    >
                      {item.decision}
                    </div>
                  </div>

                  <div className="mt-2 grid grid-cols-2 gap-3 text-sm text-white/55 xl:grid-cols-4">
                    <div>Regime: {item.regime}</div>
                    <div>Macro: {item.macro_bias}</div>
                    <div>Best score: {item.best_strategy_score ?? "-"}</div>
                    <div>Selected: {item.selected_strategy ?? "none"}</div>
                  </div>
                </div>

                <div className="text-white/50">
                  {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </div>
              </button>

              {isOpen ? (
                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
                    <div className="text-sm text-white/45">Score Breakdown</div>
                    <div className="mt-3 space-y-2 text-sm text-white/65">
                      {Object.entries(selectedBreakdown ?? {}).map(([k, v]) => {
                        if (["raw_score", "final_score", "score_cap", "macro_penalty"].includes(k)) {
                          return (
                            <div key={k} className="flex items-center justify-between">
                              <span>{prettyLabel(k)}</span>
                              <span className="font-medium text-white">{String(v)}</span>
                            </div>
                          );
                        }

                        const maxValue = maxScoreMap[k];
                        const numericValue = typeof v === "number" ? v : Number(v);

                        return (
                          <div key={k} className="flex items-center justify-between">
                            <span>{prettyLabel(k)}</span>
                            <span className="font-medium text-white">
                              {Number.isFinite(numericValue)
                                ? maxValue != null
                                  ? `${numericValue.toFixed(2)} / ${maxValue}`
                                  : numericValue.toFixed(2)
                                : String(v)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
                    <div className="text-sm text-white/45">Confidence</div>
                    <div className="mt-3 space-y-2 text-sm text-white/65">
                      <div className="flex items-center justify-between">
                        <span>Setup confidence</span>
                        <span className="font-medium text-white">{item.setup_confidence ?? "-"}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span>Decision confidence</span>
                        <span className="font-medium text-white">{item.decision_confidence ?? "-"}</span>
                      </div>
                    </div>

                    <div className="mt-4 text-sm text-white/45">Reason Tags</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(item.reason_tags ?? []).map((tag) => (
                        <div
                          key={tag}
                          className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/70"
                        >
                          {tag}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}