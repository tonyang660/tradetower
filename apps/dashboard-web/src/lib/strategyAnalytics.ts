import type {
  ExitOutcomeSummary,
  ExitOutcomesSection,
  ExitTypeRow,
  FeePressureRow,
  FeePressureSection,
  FeePressureSummary,
  HoldingBucketRow,
  HoldingTimeSummary,
  HoldingTimesSection,
  ScoreBucketRow,
  StrategyAnalyticsBootstrapResponse,
  StrategyAnalyticsSummary,
  SymbolAnalyticsRow,
  BootstrapError,
} from "../types/strategyAnalytics";

export type StrategyAnalyticsViewModel = {
  summary: StrategyAnalyticsSummary | null;
  scoreBuckets: ScoreBucketRow[];
  symbols: SymbolAnalyticsRow[];
  holdingTimes: HoldingTimesSection;
  exitOutcomes: ExitOutcomesSection;
  feePressure: FeePressureSection;
  generatedAt: string | null;
  hasErrors: boolean;
  errors: BootstrapError[];
};

export function buildStrategyAnalyticsViewModel(
  payload: StrategyAnalyticsBootstrapResponse
): StrategyAnalyticsViewModel {
  return {
    summary: normalizeSummary(payload.summary),
    scoreBuckets: normalizeScoreBuckets(payload.score_buckets ?? []),
    symbols: normalizeSymbols(payload.symbols ?? []),
    holdingTimes: normalizeHoldingTimes(payload.holding_times),
    exitOutcomes: normalizeExitOutcomes(payload.exit_outcomes),
    feePressure: normalizeFeePressure(payload.fee_pressure),
    generatedAt: payload.generated_at ?? null,
    hasErrors: (payload.errors?.length ?? 0) > 0,
    errors: payload.errors ?? [],
  };
}

function normalizeSummary(
  summary: StrategyAnalyticsSummary | null | undefined
): StrategyAnalyticsSummary | null {
  if (!summary) return null;

  return {
    total_closed_trades: numberOrZero(summary.total_closed_trades),
    gross_pnl: numberOrZero(summary.gross_pnl),
    net_pnl: numberOrZero(summary.net_pnl),
    total_fees: numberOrZero(summary.total_fees),
    avg_trade_score: nullableNumber(summary.avg_trade_score) as number,
    avg_hold_minutes: numberOrZero(summary.avg_hold_minutes),
    best_symbol: summary.best_symbol ?? null,
    worst_symbol: summary.worst_symbol ?? null,
    fee_to_gross_ratio: nullableNumber(summary.fee_to_gross_ratio),
  };
}
function normalizeScoreBuckets(rows: ScoreBucketRow[]): ScoreBucketRow[] {
  const order = new Map<string, number>([
    ["<60", 0],
    ["60-69", 1],
    ["70-74", 2],
    ["75-79", 3],
    ["80-84", 4],
    ["85+", 5],
  ]);

  return rows
    .map((row) => ({
      bucket_label: row.bucket_label,
      trades: numberOrZero(row.trades),
      gross_pnl: numberOrZero(row.gross_pnl),
      net_pnl: numberOrZero(row.net_pnl),
      total_fees: numberOrZero(row.total_fees),
      win_rate: numberOrZero(row.win_rate),
      expectancy: numberOrZero(row.expectancy),
      avg_hold_minutes: numberOrZero(row.avg_hold_minutes),
    }))
    .sort(
      (a, b) =>
        (order.get(a.bucket_label) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.bucket_label) ?? Number.MAX_SAFE_INTEGER)
    );
}

function normalizeSymbols(rows: SymbolAnalyticsRow[]): SymbolAnalyticsRow[] {
  return rows
    .map((row) => ({
      symbol: row.symbol,
      trades: numberOrZero(row.trades),
      gross_pnl: numberOrZero(row.gross_pnl),
      net_pnl: numberOrZero(row.net_pnl),
      total_fees: numberOrZero(row.total_fees),
      win_rate: numberOrZero(row.win_rate),
      expectancy: numberOrZero(row.expectancy),
      avg_hold_minutes: numberOrZero(row.avg_hold_minutes),
      stop_out_rate: numberOrZero(row.stop_out_rate),
      tp1_rate: numberOrZero(row.tp1_rate),
      tp2_rate: numberOrZero(row.tp2_rate),
      tp3_rate: numberOrZero(row.tp3_rate),
      fee_to_gross_ratio: nullableNumber(row.fee_to_gross_ratio),
    }))
    .sort((a, b) => b.net_pnl - a.net_pnl);
}

function normalizeHoldingTimes(
  section: HoldingTimesSection | null | undefined
): HoldingTimesSection {
  return {
    summary: normalizeHoldingTimeSummary(section?.summary),
    items: normalizeHoldingBuckets(section?.items ?? []),
  };
}

function normalizeHoldingTimeSummary(
  summary: HoldingTimeSummary | null | undefined
): HoldingTimeSummary | null {
  if (!summary) return null;

  return {
    avg_hold_minutes: numberOrZero(summary.avg_hold_minutes),
    median_hold_minutes: numberOrZero(summary.median_hold_minutes),
    avg_winner_hold_minutes: numberOrZero(summary.avg_winner_hold_minutes),
    avg_loser_hold_minutes: numberOrZero(summary.avg_loser_hold_minutes),
    immediate_stopouts_count: numberOrZero(summary.immediate_stopouts_count),
    fast_winners_count: numberOrZero(summary.fast_winners_count),
  };
}

function normalizeHoldingBuckets(rows: HoldingBucketRow[]): HoldingBucketRow[] {
  const order = new Map<string, number>([
    ["<5m", 0],
    ["5-15m", 1],
    ["15-30m", 2],
    ["30-60m", 3],
    ["1-4h", 4],
    ["4h+", 5],
  ]);

  return rows
    .map((row) => ({
      bucket_label: row.bucket_label,
      trades: numberOrZero(row.trades),
      winners: numberOrZero(row.winners),
      losers: numberOrZero(row.losers),
      gross_pnl: numberOrZero(row.gross_pnl),
      net_pnl: numberOrZero(row.net_pnl),
    }))
    .sort(
      (a, b) =>
        (order.get(a.bucket_label) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.bucket_label) ?? Number.MAX_SAFE_INTEGER)
    );
}

function normalizeExitOutcomes(
  section: ExitOutcomesSection | null | undefined
): ExitOutcomesSection {
  return {
    summary: normalizeExitOutcomeSummary(section?.summary),
    items: normalizeExitTypeRows(section?.items ?? []),
  };
}

function normalizeExitOutcomeSummary(
  summary: ExitOutcomeSummary | null | undefined
): ExitOutcomeSummary | null {
  if (!summary) return null;

  return {
    stop_loss_rate: numberOrZero(summary.stop_loss_rate),
    tp1_rate: numberOrZero(summary.tp1_rate),
    tp2_rate: numberOrZero(summary.tp2_rate),
    tp3_rate: numberOrZero(summary.tp3_rate),
  };
}

function normalizeExitTypeRows(rows: ExitTypeRow[]): ExitTypeRow[] {
  const order = new Map<string, number>([
    ["STOP_LOSS", 0],
    ["TP1", 1],
    ["TP2", 2],
    ["TP3", 3],
  ]);

  return rows
    .map((row) => ({
      exit_type: row.exit_type,
      executions: numberOrZero(row.executions),
      avg_realized_pnl: nullableNumber(row.avg_realized_pnl),
      total_realized_pnl: numberOrZero(row.total_realized_pnl),
      total_fees: numberOrZero(row.total_fees),
    }))
    .sort(
      (a, b) =>
        (order.get(a.exit_type) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.exit_type) ?? Number.MAX_SAFE_INTEGER)
    );
}

function normalizeFeePressure(
  section: FeePressureSection | null | undefined
): FeePressureSection {
  return {
    summary: normalizeFeePressureSummary(section?.summary),
    items: normalizeFeePressureRows(section?.items ?? []),
  };
}

function normalizeFeePressureSummary(
  summary: FeePressureSummary | null | undefined
): FeePressureSummary | null {
  if (!summary) return null;

  return {
    total_fees: numberOrZero(summary.total_fees),
    fee_to_gross_ratio: nullableNumber(summary.fee_to_gross_ratio),
    avg_fees_per_trade: numberOrZero(summary.avg_fees_per_trade),
    worst_fee_symbol: summary.worst_fee_symbol ?? null,
    best_fee_efficiency_symbol: summary.best_fee_efficiency_symbol ?? null,
  };
}

function normalizeFeePressureRows(rows: FeePressureRow[]): FeePressureRow[] {
  return rows
    .map((row) => ({
      symbol: row.symbol,
      gross_pnl: numberOrZero(row.gross_pnl),
      total_fees: numberOrZero(row.total_fees),
      net_pnl: numberOrZero(row.net_pnl),
      avg_fees_per_trade: numberOrZero(row.avg_fees_per_trade),
      fee_to_gross_ratio: nullableNumber(row.fee_to_gross_ratio),
    }))
    .sort((a, b) => {
      const aRatio = a.fee_to_gross_ratio ?? -1;
      const bRatio = b.fee_to_gross_ratio ?? -1;
      return bRatio - aRatio;
    });
}

function numberOrZero(value: number | null | undefined): number {
  if (value == null || Number.isNaN(value)) return 0;
  return Number(value);
}

function nullableNumber(value: number | null | undefined): number | null {
  if (value == null || Number.isNaN(value)) return null;
  return Number(value);
}

export function money(value: number | null | undefined): string {
  const safe = value == null || Number.isNaN(value) ? 0 : Number(value);
  return `$${safe.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function metricNumber(
  value: number | null | undefined,
  digits = 2
): string {
  if (value == null || Number.isNaN(value)) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function ratioPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `${metricNumber(value, 2)}%`;
}

export function minutesLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";

  const minutes = Number(value);

  if (minutes < 60) {
    return `${metricNumber(minutes, 1)}m`;
  }

  const hours = minutes / 60;
  if (hours < 24) {
    return `${metricNumber(hours, 1)}h`;
  }

  const days = hours / 24;
  return `${metricNumber(days, 1)}d`;
}

export function pnlTone(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-white";
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-white";
}

export function ratioTone(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-white/70";
  if (value < 0.15) return "text-emerald-300";
  if (value < 0.35) return "text-amber-300";
  return "text-rose-300";
}