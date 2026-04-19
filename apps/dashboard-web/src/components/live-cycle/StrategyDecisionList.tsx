import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
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
  if (score == null) return "text-white/65";
  if (score >= 75) return "text-emerald-300";
  if (score >= 50) return "text-amber-200";
  if (score > 0) return "text-white";
  return "text-white/50";
}

function formatLabel(label: string) {
  return label.replaceAll("_", " ");
}

function renderBreakdownGroup(
  title: string,
  values: Record<string, number>,
  isPrimary: boolean
) {
  return (
    <div>
      <div
        className={`mb-2 text-[11px] uppercase tracking-[0.18em] ${
          isPrimary ? "text-violet-200" : "text-white/30"
        }`}
      >
        {formatLabel(title)}
      </div>

      <div className="space-y-1.5">
        {Object.entries(values).map(([k, v]) => (
          <div
            key={k}
            className="flex items-center justify-between border-b border-white/5 pb-1 text-sm last:border-b-0"
          >
            <span className="capitalize text-white/55">{formatLabel(k)}</span>
            <span className={`font-medium ${scoreTone(Number(v))}`}>{String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function StrategyDecisionList({
  results,
}: {
  results: StrategyResult[];
}) {
  const [openSymbol, setOpenSymbol] = useState<string | null>(results[0]?.symbol ?? null);

  if (results.length === 0) {
    return (
      <div className="rounded-[24px] border border-white/8 bg-white/4 p-4">
        <SectionTitle title="Strategy Decisions" subtitle="No analyzed symbols in this cycle" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SectionTitle title="Strategy Decisions" subtitle="Analyzed symbols and score breakdown" />

      <div className="space-y-3">
        {results.map((item) => {
          const isOpen = openSymbol === item.symbol;
          const activeStrategy =
            item.selected_strategy && item.selected_strategy !== "none"
              ? item.selected_strategy
              : (item.score_thresholds?.trend_following_score ?? 0) >=
                (item.score_thresholds?.mean_reversion_score ?? 0)
              ? "trend_following"
              : "mean_reversion";

          const groupedBreakdown =
            item.score_breakdown &&
            (Object.prototype.hasOwnProperty.call(item.score_breakdown, "trend_following") ||
              Object.prototype.hasOwnProperty.call(item.score_breakdown, "mean_reversion"));

          return (
            <div
              key={item.symbol}
              className={`rounded-[24px] border bg-white/5 p-4 transition ${
                isOpen ? "border-violet-300/12" : "border-white/8"
              }`}
            >
              <button
                onClick={() => setOpenSymbol(isOpen ? null : item.symbol)}
                className="flex w-full items-center justify-between text-left"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-[1.05rem] font-semibold text-white">{item.symbol}</div>
                    <div
                      className={`rounded-full px-2.5 py-1 text-xs ${
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

                <div className="ml-3 text-white/45">
                  {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </div>
              </button>

              {isOpen ? (
                <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_0.85fr_0.95fr]">
                  <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                    <div className="text-sm text-white/45">Scoring Anatomy</div>

                    {groupedBreakdown ? (
                      <div className="mt-3 space-y-4">
                        {Object.entries(item.score_breakdown ?? {}).map(([group, bucketObj]) =>
                          renderBreakdownGroup(
                            group,
                            (bucketObj as Record<string, number>) ?? {},
                            group === activeStrategy
                          )
                        )}
                      </div>
                    ) : item.score_breakdown && Object.keys(item.score_breakdown).length > 0 ? (
                      <div className="mt-3">
                        {renderBreakdownGroup("score_breakdown", item.score_breakdown as Record<string, number>, true)}
                      </div>
                    ) : (
                      <div className="mt-3">
                        {renderBreakdownGroup("strategy_scores", item.strategy_scores ?? {}, true)}
                      </div>
                    )}
                  </div>

                  <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                    <div className="text-sm text-white/45">Thresholds & Confidence</div>

                    <div className="mt-3 space-y-2 text-sm text-white/65">
                      <div className="flex items-center justify-between">
                        <span>Minimum required</span>
                        <span className="font-medium text-white">
                          {item.score_thresholds?.minimum_required ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Trend-following</span>
                        <span className={`font-medium ${scoreTone(item.score_thresholds?.trend_following_score)}`}>
                          {item.score_thresholds?.trend_following_score ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span>Mean-reversion</span>
                        <span className={`font-medium ${scoreTone(item.score_thresholds?.mean_reversion_score)}`}>
                          {item.score_thresholds?.mean_reversion_score ?? "-"}
                        </span>
                      </div>

                      <div className="flex items-center justify-between border-t border-white/8 pt-2">
                        <span>Best strategy score</span>
                        <span
                          className={`font-semibold ${scoreTone(
                            item.score_thresholds?.best_strategy_score ?? item.best_strategy_score
                          )}`}
                        >
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

                  <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                    <div className="text-sm text-white/45">Reason Tags</div>
                    <div className="mt-3 flex max-h-[260px] flex-wrap gap-2 overflow-auto pr-1">
                      {(item.reason_tags ?? []).map((tag) => (
                        <div
                          key={tag}
                          className="rounded-full border border-white/10 bg-white/6 px-2.5 py-1 text-[11px] text-white/70"
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