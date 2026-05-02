export type StrategyAnalyticsSummary = {
  total_closed_trades: number;
  gross_pnl: number;
  net_pnl: number;
  total_fees: number;
  avg_trade_score: number;
  avg_hold_minutes: number;
  best_symbol: string | null;
  worst_symbol: string | null;
  fee_to_gross_ratio: number | null;
};

export type ScoreBucketRow = {
  bucket_label: string;
  trades: number;
  gross_pnl: number;
  net_pnl: number;
  total_fees: number;
  win_rate: number;
  expectancy: number;
  avg_hold_minutes: number;
};

export type SymbolAnalyticsRow = {
  symbol: string;
  trades: number;
  gross_pnl: number;
  net_pnl: number;
  total_fees: number;
  win_rate: number;
  expectancy: number;
  avg_hold_minutes: number;
  stop_out_rate: number;
  tp1_rate: number;
  tp2_rate: number;
  tp3_rate: number;
  fee_to_gross_ratio: number | null;
};

export type HoldingTimeSummary = {
  avg_hold_minutes: number;
  median_hold_minutes: number;
  avg_winner_hold_minutes: number;
  avg_loser_hold_minutes: number;
  immediate_stopouts_count: number;
  fast_winners_count: number;
};

export type HoldingBucketRow = {
  bucket_label: string;
  trades: number;
  winners: number;
  losers: number;
  gross_pnl: number;
  net_pnl: number;
};

export type ExitOutcomeSummary = {
  stop_loss_rate: number;
  tp1_rate: number;
  tp2_rate: number;
  tp3_rate: number;
};

export type ExitTypeRow = {
  exit_type: "STOP_LOSS" | "TP1" | "TP2" | "TP3" | string;
  executions: number;
  avg_realized_pnl: number | null;
  total_realized_pnl: number;
  total_fees: number;
};

export type FeePressureSummary = {
  total_fees: number;
  fee_to_gross_ratio: number | null;
  avg_fees_per_trade: number;
  worst_fee_symbol: string | null;
  best_fee_efficiency_symbol: string | null;
};

export type FeePressureRow = {
  symbol: string;
  gross_pnl: number;
  total_fees: number;
  net_pnl: number;
  avg_fees_per_trade: number;
  fee_to_gross_ratio: number | null;
};

export type HoldingTimesSection = {
  summary: HoldingTimeSummary | null;
  items: HoldingBucketRow[];
};

export type ExitOutcomesSection = {
  summary: ExitOutcomeSummary | null;
  items: ExitTypeRow[];
};

export type FeePressureSection = {
  summary: FeePressureSummary | null;
  items: FeePressureRow[];
};

export type BootstrapError = {
  source: string;
  error: unknown;
};

export type StrategyAnalyticsBootstrapResponse = {
  ok: boolean;
  account_id: number;
  generated_at: string;
  summary: StrategyAnalyticsSummary | null;
  score_buckets: ScoreBucketRow[];
  symbols: SymbolAnalyticsRow[];
  holding_times: HoldingTimesSection;
  exit_outcomes: ExitOutcomesSection;
  fee_pressure: FeePressureSection;
  errors: BootstrapError[];
};