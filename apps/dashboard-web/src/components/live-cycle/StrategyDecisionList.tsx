import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

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
  score_breakdown?: Record<string, any>;
  score_thresholds?: {
    minimum_required?: number;
    trend_following_score?: number | null;
    mean_reversion_score?: number | null;
    best_strategy_score?: number | null;
  };
  reason_tags?: string[];
};

function scoreTone(score?: number | null) {
  if (score == null) return "text-white/70";
  if (score >= 75) return "text-emerald-300";
  if (score >= 50) return "text-amber-200";
  return "text-white/70";
}

function renderBreakdownBlock(scoreBreakdown?: Record<string, any>, strategyScores?: Record<string, number>) {
  if (
    scoreBreakdown &&
    (Object.prototype.hasOwnProperty.call(scoreBreakdown, "trend_following") ||
      Object.prototype.hasOwnProperty.call(scoreBreakdown, "mean_reversion"))
  ) {
    return (
      <div className="mt-3 space-y-4">
        {Object.entries(scoreBreakdown).map(([group, bucketObj]) => (
          <div key={group}>
            <div className="mb-2 text-xs uppercase tracking-[0.16em] text-white/35">
              {group.replaceAll("_", " ")}
            </div>
            <div className="space-y-2 text-sm text-white/65">
              {Object.entries((bucketObj as Record<string, number>) ?? {}).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="capitalize">{k.replaceAll("_", " ")}</span>
                  <span className={`font-medium ${scoreTone(Number(v))}`}>{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (scoreBreakdown && Object.keys(scoreBreakdown).length > 0) {
    return (
      <div className="mt-3 space-y-2 text-sm text-white/65">
        {Object.entries(scoreBreakdown).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between">
            <span className="capitalize">{k.replaceAll("_", " ")}</span>
            <span className={`font-medium ${scoreTone(Number(v))}`}>{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2 text-sm text-white/65">
      {Object.entries(strategyScores ?? {}).map(([k, v]) => (
        <div key={k} className="flex items-center justify-between">
          <span>{k}</span>
          <span className={`font-medium ${scoreTone(Number(v))}`}>{String(v)}</span>
        </div>
      ))}
    </div>
  );
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
    <div className="space-y-4">
      <SectionTitle title="Strategy Decisions" subtitle="Analyzed symbols and score breakdown" />

      <div className="space-y-3">
        {results.map((item) => {
          const isOpen = openSymbol === item.symbol;

          return (
            <div
              key={item.symbol}
              className="rounded-2xl border border-white/8 bg-white/5 p-4"
            >
              <button
                onClick={() => setOpenSymbol(isOpen ? null : item.symbol)}
                className="flex w-full items-center justify-between text-left"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-lg font-semibold text-white">{item.symbol}</div>
                    <div
                      className={`rounded-full px-2 py-1 text-xs ${
                        item.decision === "no_trade"
                          ? "bg-white/10 text-white/65"
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
                    <div className={scoreTone(item.best_strategy_score)}>
                      Best score: {item.best_strategy_score ?? "-"}
                    </div>
                    <div>Selected: {item.selected_strategy ?? "none"}</div>
                  </div>
                </div>

                <div className="ml-3 text-white/50">
                  {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </div>
              </button>

              {isOpen ? (
                <div className="mt-4 grid gap-4 xl:grid-cols-3">
                  <div className="rounded-2xl border border-white/8 bg-white/4 p-4 xl:col-span-1">
                    <div className="text-sm text-white/45">Scoring Anatomy</div>
                    {renderBreakdownBlock(item.score_breakdown, item.strategy_scores)}
                  </div>

                  <div className="rounded-2xl border border-white/8 bg-white/4 p-4 xl:col-span-1">
                    <div className="text-sm text-white/45">Thresholds & Confidence</div>

                    <div className="mt-3 space-y-2 text-sm text-white/65">
                      <div className="flex items-center justify-between">
                        <span>Minimum required</span>
                        <span className="font-medium text-white">
                          {item.score_thresholds?.minimum_required ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Trend-following score</span>
                        <span className={`font-medium ${scoreTone(item.score_thresholds?.trend_following_score)}`}>
                          {item.score_thresholds?.trend_following_score ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Mean-reversion score</span>
                        <span className={`font-medium ${scoreTone(item.score_thresholds?.mean_reversion_score)}`}>
                          {item.score_thresholds?.mean_reversion_score ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Best strategy score</span>
                        <span className={`font-medium ${scoreTone(item.score_thresholds?.best_strategy_score ?? item.best_strategy_score)}`}>
                          {item.score_thresholds?.best_strategy_score ?? item.best_strategy_score ?? "-"}
                        </span>
                      </div>

                      <div className="mt-3 flex items-center justify-between">
                        <span>Setup confidence</span>
                        <span className="font-medium text-white">{item.setup_confidence ?? "-"}</span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Decision confidence</span>
                        <span className="font-medium text-white">{item.decision_confidence ?? "-"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-white/8 bg-white/4 p-4 xl:col-span-1">
                    <div className="text-sm text-white/45">Reason Tags</div>
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
    </div>
  );
}