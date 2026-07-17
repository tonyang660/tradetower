import { useState } from "react";
import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import { ChevronDown, ChevronUp } from "lucide-react";

type ScoreThresholds = {
  trade_minimum_required?: number;
  observe_minimum_required?: number;
  normal_trade_threshold?: number;
  btc_trade_threshold?: number;
  drawdown_trade_threshold?: number;
  hot_streak_trade_threshold?: number;
};

type EntryValidation = {
  valid?: boolean;
  direction?: string;
  failed_conditions?: string[];
  passed_conditions?: string[];
  reason_tags?: string[];
  details?: Record<string, unknown>;
};

type ScoreComponent = {
  points?: number;
  score?: number;
  value?: number;
  max?: number;
  details?: string;
  reason?: string;
};

type StrategyResult = {
  symbol: string;
  decision: string;
  regime: string;
  macro_bias?: string;
  selected_strategy: string;
  best_strategy_score?: number;
  score?: number;
  setup_confidence?: number;
  decision_confidence?: number;
  strategy_scores?: Record<string, number>;
  score_thresholds?: ScoreThresholds;
  entry_validation?: EntryValidation;
  reason_tags?: string[];
  score_breakdown?: Record<string, any>;
};

const TREND_MAX_SCORES: Record<string, number> = {
  htf_alignment: 25,
  momentum: 20,
  entry_location: 20,
  break_of_structure: 15,
  rsi_quality: 12,
  volatility: 8,
  macro_alignment: 15,
  htf_structure_quality: 20,
  ema_strength: 15,
  bos_quality_freshness: 15,
  pullback_quality: 15,
  momentum_quality: 10,
  volatility_suitability: 10,
};

const MEAN_MAX_SCORES: Record<string, number> = {
  range_confirmation: 20,
  breakout_safety: 15,
  reversal_pattern: 20,
  entry_extremity: 20,
  rsi_divergence: 15,
  low_volatility: 10,
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

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function formatNumber(value: unknown, digits = 2): string {
  const numeric = asNumber(value);
  if (numeric == null) return "-";
  return numeric.toFixed(digits).replace(/\.?0+$/, "");
}

function scoreFor(item: StrategyResult): number | null {
  const directScore = asNumber(item.best_strategy_score);
  if (directScore != null) return directScore;

  const v2Score = asNumber(item.score);
  if (v2Score != null) return v2Score;

  const selectedScore = item.strategy_scores?.[item.selected_strategy];
  const numericSelectedScore = asNumber(selectedScore);
  if (numericSelectedScore != null) return numericSelectedScore;

  return null;
}

function selectedBreakdownFor(item: StrategyResult): Record<string, unknown> {
  const breakdown = item.score_breakdown ?? {};
  if (!breakdown || typeof breakdown !== "object") return {};

  if (item.selected_strategy === "trend_following") {
    return breakdown.trend_following ?? breakdown;
  }

  if (item.selected_strategy === "mean_reversion") {
    return breakdown.mean_reversion ?? breakdown;
  }

  return breakdown[item.selected_strategy] ?? breakdown;
}

function maxScoresFor(strategy: string): Record<string, number> {
  if (strategy === "trend_following") return TREND_MAX_SCORES;
  if (strategy === "mean_reversion") return MEAN_MAX_SCORES;
  return {};
}

function componentScore(value: unknown): ScoreComponent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as ScoreComponent;
}

function renderedBlocker(item: StrategyResult): string {
  const tags = item.reason_tags ?? [];
  if (tags.includes("ENTRY_VALIDATION_FAILED") || item.entry_validation?.valid === false) {
    return "Entry validation";
  }

  if (tags.includes("ROUTE_INVALID")) {
    return "Regime route";
  }

  if (tags.includes("BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME")) {
    return "BTC regime rule";
  }

  if (tags.includes("SCORE_BELOW_OBSERVE_THRESHOLD")) {
    return "Score below observe threshold";
  }

  if (tags.includes("SCORE_BELOW_TRADE_THRESHOLD")) {
    return "Score below trade threshold";
  }

  if (item.decision === "observe") {
    return "Observed only";
  }

  if (item.decision === "trade_candidate") {
    return "Eligible trade candidate";
  }

  return "Not specified";
}

function validationTone(valid?: boolean) {
  if (valid === true) return "border-emerald-400/20 bg-emerald-500/10 text-emerald-200";
  if (valid === false) return "border-rose-400/20 bg-rose-500/10 text-rose-200";
  return "border-white/10 bg-white/6 text-white/60";
}

function ScoreBreakdownRow({
  labelKey,
  value,
  maxScoreMap,
}: {
  labelKey: string;
  value: unknown;
  maxScoreMap: Record<string, number>;
}) {
  const objectValue = componentScore(value);
  const directNumeric = asNumber(value);

  if (objectValue) {
    const points = asNumber(objectValue.points ?? objectValue.score ?? objectValue.value);
    const max = asNumber(objectValue.max) ?? maxScoreMap[labelKey] ?? null;
    const details = objectValue.details ?? objectValue.reason ?? null;

    return (
      <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
        <div className="flex items-start justify-between gap-3">
          <span className="text-white/65">{prettyLabel(labelKey)}</span>
          <span className="shrink-0 font-medium text-white">
            {points != null
              ? max != null
                ? `${formatNumber(points)} / ${formatNumber(max)}`
                : formatNumber(points)
              : "-"}
          </span>
        </div>

        {details ? (
          <div className="mt-1 text-xs leading-5 text-white/40">{String(details)}</div>
        ) : null}
      </div>
    );
  }

  const max = maxScoreMap[labelKey];
  return (
    <div className="flex items-center justify-between rounded-2xl border border-white/8 bg-white/5 p-3">
      <span className="text-white/65">{prettyLabel(labelKey)}</span>
      <span className="font-medium text-white">
        {directNumeric != null
          ? max != null
            ? `${formatNumber(directNumeric)} / ${formatNumber(max)}`
            : formatNumber(directNumeric)
          : String(value ?? "-")}
      </span>
    </div>
  );
}

function ThresholdDiagnostics({ item }: { item: StrategyResult }) {
  const score = scoreFor(item);
  const thresholds = item.score_thresholds ?? {};
  const tradeThreshold = thresholds.trade_minimum_required;
  const observeThreshold = thresholds.observe_minimum_required;

  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
      <div className="text-sm text-white/45">Decision Diagnostics</div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-white/40">Score</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {score != null ? formatNumber(score) : "-"}
          </div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-white/40">Blocked by</div>
          <div className="mt-1 text-sm font-medium text-white">{renderedBlocker(item)}</div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-white/40">Observe Threshold</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {observeThreshold != null ? formatNumber(observeThreshold) : "-"}
          </div>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/5 p-3">
          <div className="text-white/40">Trade Threshold</div>
          <div className="mt-1 text-lg font-semibold text-white">
            {tradeThreshold != null ? formatNumber(tradeThreshold) : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

function EntryValidationPanel({ item }: { item: StrategyResult }) {
  const validation = item.entry_validation;
  const failed = validation?.failed_conditions ?? [];
  const passed = validation?.passed_conditions ?? [];
  const valid = validation?.valid;

  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-white/45">Entry Validation</div>
        <div className={`rounded-full border px-3 py-1 text-xs ${validationTone(valid)}`}>
          {valid === true ? "Passed" : valid === false ? "Failed" : "Unknown"}
        </div>
      </div>

      {failed.length > 0 ? (
        <>
          <div className="mt-4 text-sm text-rose-200/80">Failed Conditions</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {failed.map((condition) => (
              <div
                key={condition}
                className="rounded-full border border-rose-400/15 bg-rose-500/10 px-3 py-1 text-xs text-rose-100/80"
              >
                {condition}
              </div>
            ))}
          </div>
        </>
      ) : null}

      {passed.length > 0 ? (
        <>
          <div className="mt-4 text-sm text-emerald-200/80">Passed Conditions</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {passed.slice(0, 12).map((condition) => (
              <div
                key={condition}
                className="rounded-full border border-emerald-400/15 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-100/75"
              >
                {condition}
              </div>
            ))}
            {passed.length > 12 ? (
              <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/45">
                +{passed.length - 12} more
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {!failed.length && !passed.length ? (
        <div className="mt-3 text-sm text-white/40">No entry-validation details were included.</div>
      ) : null}
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
    <GlassCard>
      <SectionTitle title="Strategy Decisions" subtitle="Analyzed symbols and score breakdown" />

      <div className="space-y-3">
        {results.map((item) => {
          const isOpen = openSymbol === item.symbol;
          const selectedBreakdown = selectedBreakdownFor(item);
          const maxScoreMap = maxScoresFor(item.selected_strategy);
          const score = scoreFor(item);

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
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-lg font-semibold text-white">{item.symbol}</div>
                    <div
                      className={`rounded-full px-2 py-1 text-xs ${
                        item.decision === "no_trade"
                          ? "bg-white/10 text-white/65"
                          : item.decision === "observe"
                          ? "bg-violet-500/12 text-violet-200"
                          : item.decision === "long" || item.decision === "trade_candidate"
                          ? "bg-emerald-500/12 text-emerald-200"
                          : "bg-rose-500/12 text-rose-200"
                      }`}
                    >
                      {item.decision}
                    </div>

                    <div className="rounded-full border border-white/10 bg-white/6 px-2 py-1 text-xs text-white/45">
                      Blocked by: {renderedBlocker(item)}
                    </div>
                  </div>

                  <div className="mt-2 grid grid-cols-2 gap-3 text-sm text-white/55 xl:grid-cols-5">
                    <div>Regime: {item.regime}</div>
                    <div>Macro: {item.macro_bias ?? "-"}</div>
                    <div>Score: {score != null ? formatNumber(score) : "-"}</div>
                    <div>Selected: {item.selected_strategy ?? "none"}</div>
                    <div>Entry: {item.entry_validation?.valid === true ? "passed" : item.entry_validation?.valid === false ? "failed" : "-"}</div>
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
                      {Object.entries(selectedBreakdown ?? {}).length > 0 ? (
                        Object.entries(selectedBreakdown ?? {}).map(([k, v]) => (
                          <ScoreBreakdownRow
                            key={k}
                            labelKey={k}
                            value={v}
                            maxScoreMap={maxScoreMap}
                          />
                        ))
                      ) : (
                        <div className="rounded-2xl border border-white/8 bg-white/5 p-3 text-white/45">
                          No score breakdown included.
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="space-y-4">
                    <ThresholdDiagnostics item={item} />
                    <EntryValidationPanel item={item} />

                    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
                      <div className="text-sm text-white/45">Confidence</div>
                      <div className="mt-3 space-y-2 text-sm text-white/65">
                        <div className="flex items-center justify-between">
                          <span>Setup confidence</span>
                          <span className="font-medium text-white">
                            {item.setup_confidence ?? "-"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span>Decision confidence</span>
                          <span className="font-medium text-white">
                            {item.decision_confidence ?? "-"}
                          </span>
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
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
