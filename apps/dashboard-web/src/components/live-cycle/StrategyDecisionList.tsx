import { useState } from "react";
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

type DirectionEvaluation = {
  selected_direction?: string;
  evaluated_directions?: Array<{
    score?: number;
    direction?: string;
    entry_valid?: boolean;
    entry_reason?: string;
    proposed_trade_valid?: boolean;
  }>;
};

type StrategyResult = {
  symbol: string;
  decision: string;
  regime?: string;
  macro_bias?: string;
  macroBias?: string;
  selected_strategy?: string;
  best_strategy_score?: number;
  score?: number;
  confidence?: number;
  setup_confidence?: number;
  decision_confidence?: number;
  strategy_scores?: Record<string, number>;
  score_thresholds?: ScoreThresholds;
  entry_validation?: EntryValidation;
  reason_tags?: string[];
  strategy_reason_tags?: string[];
  score_breakdown?: Record<string, any>;
  position_side?: string;
  decision_side?: string;
  side?: string;
  direction?: string;
  proposed_trade?: Record<string, any>;
  direction_evaluation?: DirectionEvaluation;
  btc_macro_context?: Record<string, any>;
  btc_macro_policy?: Record<string, any>;
  market_context?: Record<string, any>;
  mtf_context?: Record<string, any>;
  snapshot_refs?: Record<string, any>;
  regime_route?: Record<string, any>;
};

type RiskResult = {
  symbol?: string;
  ok?: boolean;
  approved?: boolean;
  risk_decision?: string;
  reason_codes?: string[];
  error?: string;
  details?: string;
  risk_context?: Record<string, any>;
  scheduler_risk_summary?: {
    reason_codes?: string[];
    risk_decision?: string;
    approved?: boolean;
  };
};

type GateResult = {
  symbol?: string;
  trade_allowed?: boolean;
  allowed?: boolean;
  reason_codes?: string[];
  error?: string;
  details?: string;
};

type PaperResult = {
  symbol?: string;
  action?: string;
  status?: string;
  ok?: boolean;
  error?: string;
  details?: string;
  execution_event?: {
    symbol?: string;
    action?: string;
    status?: string;
  };
};

type DownstreamStatus = {
  blocker: string;
  riskLabel: string;
  gateLabel: string;
  executionLabel: string;
  riskTone: "green" | "red" | "yellow" | "neutral";
  gateTone: "green" | "red" | "yellow" | "neutral";
  executionTone: "green" | "red" | "yellow" | "neutral";
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

function normalizeSymbol(value: unknown): string {
  return String(value ?? "").toUpperCase();
}

function symbolOf(value: { symbol?: string; execution_event?: { symbol?: string } }) {
  return normalizeSymbol(value.symbol ?? value.execution_event?.symbol);
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return null;
}

function scoreFor(item: StrategyResult): number | null {
  const directScore = asNumber(item.best_strategy_score);
  if (directScore != null) return directScore;

  const v2Score = asNumber(item.score ?? item.confidence);
  if (v2Score != null) return v2Score;

  const selected = item.selected_strategy ?? "";
  const selectedScore = item.strategy_scores?.[selected];
  const numericSelectedScore = asNumber(selectedScore);
  if (numericSelectedScore != null) return numericSelectedScore;

  return null;
}

function strategyFor(item: StrategyResult): string {
  const selected = firstString(item.selected_strategy);
  if (selected) return selected;

  const regime = String(item.regime ?? "").toLowerCase();
  if (regime.includes("sideways") || regime.includes("range")) return "mean_reversion";
  if (regime.includes("uptrend") || regime.includes("downtrend") || regime.includes("trend")) {
    return "trend_following";
  }

  return "unknown";
}

function selectedBreakdownFor(item: StrategyResult): Record<string, unknown> {
  const breakdown = item.score_breakdown ?? {};
  if (!breakdown || typeof breakdown !== "object") return {};

  const selected = strategyFor(item);

  if (selected === "trend_following") {
    return breakdown.trend_following ?? breakdown.trend ?? breakdown;
  }

  if (selected === "mean_reversion") {
    return breakdown.mean_reversion ?? breakdown.mean ?? breakdown;
  }

  return breakdown[selected] ?? breakdown;
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

function bestDirection(item: StrategyResult): "long" | "short" | null {
  const direct = firstString(
    item.position_side,
    item.decision_side,
    item.side,
    item.direction,
    item.entry_validation?.direction,
    item.proposed_trade?.position_side,
    item.proposed_trade?.direction,
    item.direction_evaluation?.selected_direction
  )?.toLowerCase();

  if (direct === "long" || direct === "short") return direct;

  const candidates = item.direction_evaluation?.evaluated_directions ?? [];
  let best: { direction: "long" | "short"; score: number } | null = null;

  for (const candidate of candidates) {
    const direction = String(candidate.direction ?? "").toLowerCase();
    const score = asNumber(candidate.score);
    if ((direction === "long" || direction === "short") && score != null) {
      if (!best || score > best.score) best = { direction, score };
    }
  }

  return best?.direction ?? null;
}

function directionTone(direction: "long" | "short" | null) {
  if (direction === "long") {
    return {
      card: "border-emerald-400/15 bg-emerald-500/10",
      tag: "border-emerald-400/25 bg-emerald-500/12 text-emerald-100",
      label: "LONG",
    };
  }

  if (direction === "short") {
    return {
      card: "border-rose-400/15 bg-rose-500/10",
      tag: "border-rose-400/25 bg-rose-500/12 text-rose-100",
      label: "SHORT",
    };
  }

  return {
    card: "border-white/8 bg-white/5",
    tag: "border-white/10 bg-white/6 text-white/55",
    label: "SIDE -",
  };
}

function findNestedString(source: unknown, keys: string[], depth = 0): string | null {
  if (!source || typeof source !== "object" || depth > 5) return null;

  const object = source as Record<string, unknown>;
  for (const key of keys) {
    const value = object[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }

  for (const value of Object.values(object)) {
    if (value && typeof value === "object") {
      const found = findNestedString(value, keys, depth + 1);
      if (found) return found;
    }
  }

  return null;
}

function macroBiasFor(item: StrategyResult): string {
  const value = firstString(
    item.macro_bias,
    item.macroBias,
    item.btc_macro_context?.bias,
    item.btc_macro_context?.regime,
    item.btc_macro_policy?.bias,
    item.market_context?.macro_bias,
    item.market_context?.btc_macro_bias,
    item.mtf_context?.macro_bias,
    item.snapshot_refs?.macro_bias,
    item.regime_route?.macro_bias,
    findNestedString(item, ["macro_bias", "macroBias", "btc_macro_bias"])
  );

  return value ?? "-";
}

function shortReasons(codes?: string[]) {
  if (!codes || codes.length === 0) return "";
  return codes.slice(0, 2).join(", ");
}

function downstreamStatus(
  item: StrategyResult,
  risk?: RiskResult,
  gate?: GateResult,
  paper?: PaperResult
): DownstreamStatus {
  const tags = item.reason_tags ?? item.strategy_reason_tags ?? [];
  const paperAction = String(paper?.action ?? paper?.execution_event?.action ?? "").toUpperCase();
  const paperStatus = String(paper?.status ?? paper?.execution_event?.status ?? "").toUpperCase();
  const riskCodes = risk?.reason_codes ?? risk?.scheduler_risk_summary?.reason_codes ?? [];
  const gateCodes = gate?.reason_codes ?? [];

  let blocker = "Strategy pending downstream";
  let riskLabel = "Not checked";
  let gateLabel = "Not checked";
  let executionLabel = "Not reached";
  let riskTone: DownstreamStatus["riskTone"] = "neutral";
  let gateTone: DownstreamStatus["gateTone"] = "neutral";
  let executionTone: DownstreamStatus["executionTone"] = "neutral";

  if (tags.includes("ENTRY_VALIDATION_FAILED") || item.entry_validation?.valid === false) {
    blocker = "Entry validation";
  } else if (tags.includes("ROUTE_INVALID")) {
    blocker = "Regime route";
  } else if (tags.includes("BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME")) {
    blocker = "BTC regime rule";
  } else if (tags.includes("SCORE_BELOW_OBSERVE_THRESHOLD")) {
    blocker = "Score below observe threshold";
  } else if (tags.includes("SCORE_BELOW_TRADE_THRESHOLD")) {
    blocker = "Score below trade threshold";
  } else if (item.decision === "observe") {
    blocker = "Observed only";
  } else if (item.decision === "trade_candidate") {
    blocker = "Eligible trade candidate";
  }

  if (risk) {
    const riskDecision = String(risk.risk_decision ?? risk.scheduler_risk_summary?.risk_decision ?? "").toLowerCase();

    if (risk.approved === true || riskDecision === "approved") {
      riskLabel = "Approved";
      riskTone = "green";
      blocker = "Risk approved";
    } else if (riskDecision === "error" || risk.ok === false || risk.error) {
      riskLabel = `Error${shortReasons(riskCodes) ? ` · ${shortReasons(riskCodes)}` : ""}`;
      riskTone = "red";
      blocker = "Risk engine error";
    } else if (risk.approved === false || riskDecision === "rejected") {
      riskLabel = `Rejected${shortReasons(riskCodes) ? ` · ${shortReasons(riskCodes)}` : ""}`;
      riskTone = "red";
      blocker = shortReasons(riskCodes) || "Risk rejected";
    }
  }

  if (gate) {
    const allowed = gate.trade_allowed ?? gate.allowed;
    if (allowed === true) {
      gateLabel = "Allowed";
      gateTone = "green";
      blocker = "Final gate allowed";
    } else if (allowed === false) {
      gateLabel = `Blocked${shortReasons(gateCodes) ? ` · ${shortReasons(gateCodes)}` : ""}`;
      gateTone = "red";
      blocker = shortReasons(gateCodes) || "Final gate blocked";
    } else if (gate.error) {
      gateLabel = "Error";
      gateTone = "red";
      blocker = "Final gate error";
    }
  }

  if (paper) {
    if (paperAction === "ENTRY_FILLED" || paperStatus === "FILLED") {
      executionLabel = "Filled";
      executionTone = "green";
      blocker = "Filled";
    } else if (paperAction === "ENTRY_PENDING" || paperStatus === "PENDING") {
      executionLabel = "Pending";
      executionTone = "yellow";
      blocker = "Pending entry";
    } else if (paper.ok === false || paper.error) {
      executionLabel = "Error";
      executionTone = "red";
      blocker = "Execution error";
    } else {
      executionLabel = paperAction || paperStatus || "Submitted";
      executionTone = "green";
      blocker = "Submitted";
    }
  }

  if (item.decision === "no_trade" && blocker === "Strategy pending downstream") {
    blocker = "No trade";
  }

  return {
    blocker,
    riskLabel,
    gateLabel,
    executionLabel,
    riskTone,
    gateTone,
    executionTone,
  };
}

function pillTone(tone: "green" | "red" | "yellow" | "neutral") {
  if (tone === "green") return "border-emerald-400/20 bg-emerald-500/10 text-emerald-100";
  if (tone === "red") return "border-rose-400/20 bg-rose-500/10 text-rose-100";
  if (tone === "yellow") return "border-amber-400/20 bg-amber-500/10 text-amber-100";
  return "border-white/10 bg-white/6 text-white/60";
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

function StatusPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "red" | "yellow" | "neutral";
}) {
  return (
    <div className={`rounded-2xl border px-3 py-2 text-xs ${pillTone(tone)}`}>
      <div className="text-white/45">{label}</div>
      <div className="mt-1 font-medium text-current">{value}</div>
    </div>
  );
}

function ThresholdDiagnostics({
  item,
  status,
}: {
  item: StrategyResult;
  status: DownstreamStatus;
}) {
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
          <div className="mt-1 text-sm font-medium text-white">{status.blocker}</div>
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

      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        <StatusPill label="Risk" value={status.riskLabel} tone={status.riskTone} />
        <StatusPill label="Final Gate" value={status.gateLabel} tone={status.gateTone} />
        <StatusPill label="Execution" value={status.executionLabel} tone={status.executionTone} />
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

function ReasonTagsPanel({ item }: { item: StrategyResult }) {
  const tags = item.reason_tags ?? item.strategy_reason_tags ?? [];

  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
      <div className="text-sm text-white/45">Reason Tags</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {tags.length > 0 ? (
          tags.map((tag) => (
            <div
              key={tag}
              className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs text-white/70"
            >
              {tag}
            </div>
          ))
        ) : (
          <div className="text-sm text-white/40">No reason tags included.</div>
        )}
      </div>
    </div>
  );
}

export default function StrategyDecisionList({
  results,
  riskResults = [],
  gateResults = [],
  paperResults = [],
}: {
  results: StrategyResult[];
  riskResults?: RiskResult[];
  gateResults?: GateResult[];
  paperResults?: PaperResult[];
}) {
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);

  if (results.length === 0) {
    return (
      <div className="rounded-[24px] border border-white/8 bg-white/4 p-5">
        <SectionTitle title="Strategy Decisions" subtitle="No analyzed symbols in this cycle" />
      </div>
    );
  }

  return (
    <div className="rounded-[24px] border border-white/8 bg-white/4 p-5">
      <SectionTitle title="Strategy Decisions" subtitle="Analyzed symbols and score breakdown" />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {results.map((item) => {
          const symbol = normalizeSymbol(item.symbol);
          const risk = riskResults.find((result) => normalizeSymbol(result.symbol) === symbol);
          const gate = gateResults.find((result) => normalizeSymbol(result.symbol) === symbol);
          const paper = paperResults.find((result) => symbolOf(result) === symbol);
          const status = downstreamStatus(item, risk, gate, paper);
          const isOpen = openSymbol === item.symbol;
          const selectedStrategy = strategyFor(item);
          const selectedBreakdown = selectedBreakdownFor(item);
          const maxScoreMap = maxScoresFor(selectedStrategy);
          const score = scoreFor(item);
          const direction = bestDirection(item);
          const directionStyle = directionTone(direction);

          return (
            <div
              key={item.symbol}
              className={`rounded-2xl border p-4 ${directionStyle.card}`}
            >
              <button
                onClick={() => setOpenSymbol(isOpen ? null : item.symbol)}
                className="flex w-full items-center justify-between gap-4 text-left"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-lg font-semibold text-white">{item.symbol}</div>

                    <div className={`rounded-full border px-2 py-1 text-xs ${directionStyle.tag}`}>
                      {directionStyle.label}
                    </div>

                    <div
                      className={`rounded-full px-2 py-1 text-xs ${
                        item.decision === "no_trade"
                          ? "bg-white/10 text-white/65"
                          : item.decision === "observe"
                          ? "bg-violet-500/12 text-violet-200"
                          : "bg-emerald-500/12 text-emerald-200"
                      }`}
                    >
                      {item.decision}
                    </div>

                    <div className={`rounded-full border px-2 py-1 text-xs ${pillTone(status.executionTone)}`}>
                      {status.blocker}
                    </div>
                  </div>

                  <div className="mt-2 grid grid-cols-2 gap-3 text-sm text-white/55 xl:grid-cols-5">
                    <div>Regime: {item.regime ?? "-"}</div>
                    <div>Macro: {macroBiasFor(item)}</div>
                    <div>Score: {score != null ? formatNumber(score) : "-"}</div>
                    <div>Selected: {selectedStrategy}</div>
                    <div>
                      Entry:{" "}
                      {item.entry_validation?.valid === true
                        ? "passed"
                        : item.entry_validation?.valid === false
                        ? "failed"
                        : "-"}
                    </div>
                  </div>
                </div>

                <div className="shrink-0 text-white/50">
                  {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </div>
              </button>

              {isOpen ? (
                <div className="mt-4 grid gap-4">
                  <div className="grid gap-4 2xl:grid-cols-2">
                    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
                      <div className="text-sm text-white/45">
                        Score Breakdown · {prettyLabel(selectedStrategy)}
                      </div>
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

                    <ThresholdDiagnostics item={item} status={status} />
                  </div>

                  <div className="grid gap-4 2xl:grid-cols-2">
                    <EntryValidationPanel item={item} />
                    <ReasonTagsPanel item={item} />
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
