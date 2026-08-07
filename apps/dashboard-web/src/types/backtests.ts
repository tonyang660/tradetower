export type BacktestRunConfig = {
  strategy_name: string;
  strategy_version?: string;
  symbols: string[];
  timeframes: string[];
  cycle_timeframe: string;
  decision_timeframe?: string;
  execution_timeframe?: string;
  execution_data_timeframe?: string;
  start_time: string;
  end_time: string;
  starting_capital: number;
  max_cycles: number;
  risk_per_trade_pct: number;
  maker_fee_bps: number;
  taker_fee_bps: number;
  limit_order_fill_ratio: number;
  slippage_bps: number;
  spread_bps?: number;
  execution_mode?: string;
  macro_bias_mode?: string;
  regime_model_version?: string;
  guardian_max_position_leverage: number;
  guardian_account_max_notional_multiplier: number;
  guardian_max_account_exposure_pct: number;
  data_mode: string;
  dataset_id: number;
  warmup_required_bars: number;
  preflight_strict: boolean;
  strategy_validation_strict_timeframes: boolean;
};

export type StrategyListResponse = {
  ok: boolean;
  strategies?: string[];
  items?: StrategyOption[];
  error?: string;
};

export type StrategyOption = {
  name: string;
  version?: string;
  family?: string;
  description?: string;
  tags?: string[];
};

export type StrategyDetailResponse = {
  ok: boolean;
  strategy?: any;
  error?: string;
};

export type BacktestRunResponse = {
  ok: boolean;
  run_id?: number;
  summary?: BacktestSummary;
  diagnostics?: any;
  preflight?: any;
  config?: BacktestRunConfig;
  error?: string;
};

export type BacktestSummary = {
  run_id: number;
  final_equity?: number;
  return_pct?: number;
  gross_pnl?: number;
  net_pnl?: number;
  max_drawdown_pct?: number;
  total_trades?: number;
  win_rate?: number | null;
  profit_factor?: number | null;
};

export type BacktestRunListResponse = {
  ok: boolean;
  runs?: any[];
  error?: string;
};

export type BacktestRunDetailResponse = {
  ok: boolean;
  run?: any;
  error?: string;
};


export type BacktestValidationResponse = {
  ok?: boolean;
  valid?: boolean;
  validation?: {
    valid?: boolean;
    errors?: string[];
    warnings?: string[];
    requested_timeframes?: string[];
    required_timeframes?: string[];
    active_phase_timeframes?: string[];
    strict_timeframes?: boolean;
    strategy?: any;
  };
  config?: BacktestRunConfig;
  error?: string;
  errors?: string[];
  warnings?: string[];
};


export type BacktestJobProgress = {
  ok: boolean;
  job_id?: string;
  job?: {
    job_id: string;
    status: string;
    run_id?: number | null;
    elapsed_seconds?: number;
    estimated_remaining_seconds?: number | null;
    progress_pct?: number;
    candles_processed?: number;
    cycles_processed?: number;
    trades_generated?: number;
    current_simulated_date?: string | null;
    current_status?: string;
    logs?: Array<{ timestamp?: string; level?: string; event_type?: string; message?: string; details?: any }>;
    result?: BacktestRunResponse | null;
    error?: string | null;
    cancel_requested?: boolean;
  };
  error?: string;
};


export type BacktestAnalyticsMetric = {
  name: string;
  value: any;
  available: boolean;
  unit?: string | null;
  description?: string | null;
};

export type BacktestAnalyticsBreakdownRow = {
  key: string;
  trades: number;
  gross_pnl: number;
  net_pnl: number;
  fees: number;
  win_rate: number;
};

export type BacktestExecutionMetrics = {
  version: string;
  liquidity: {
    maker_fill_count: number;
    maker_fee_total: number;
    taker_fill_count: number;
    taker_fee_total: number;
    unknown_fill_count: number;
    unknown_fee_total: number;
  };
  entry_orders: {
    submitted: number;
    filled: number;
    expired: number;
    market_fallbacks: number;
    average_wait_attempts: number | null;
    wait_attempt_samples: number;
  };
  stop_loss: {
    limit_reprice_attempts: number;
    limit_maker_fills: number;
    market_fallbacks: number;
  };
  sl2: {
    created: number;
    filled: number;
    by_trigger: Array<{ trigger: string; created: number; filled: number }>;
  };
  outcomes: {
    exit_leg_count: number;
    exit_leg_wins: number;
    exit_leg_win_rate: number | null;
    position_count: number;
    position_wins: number;
    position_win_rate: number | null;
  };
  availability: Record<string, boolean>;
};

export type BacktestRiskAdjustedReturns = {
  daily_return_samples: number;
  annualization_days: number;
  minimum_recommended_samples: number;
  reliable: boolean;
  note: string;
};


export type BacktestAnalyticsResponse = {
  ok: boolean;
  run_id: number;
  run?: any;
  metrics?: BacktestAnalyticsMetric[];
  summary?: any;
  execution?: BacktestExecutionMetrics;
  risk_adjusted_returns?: BacktestRiskAdjustedReturns;
  breakdowns?: {
    symbols?: BacktestAnalyticsBreakdownRow[];
    regimes?: BacktestAnalyticsBreakdownRow[];
    exit_reasons?: BacktestAnalyticsBreakdownRow[];
    score_buckets?: BacktestAnalyticsBreakdownRow[];
  };
  availability?: Record<string, boolean>;
  error?: string;
};


export type BacktestChartDataResponse = {
  ok: boolean;
  run_id: number;
  downsampling?: {
    enabled: boolean;
    method: string;
    raw_points: number;
    returned_points: number;
    max_points: number;
  };
  equity_metadata?: {
    starting_equity: number | null;
    latest_equity_curve_value: number | null;
    raw_last_equity_curve_value: number | null;
    final_equity: number | null;
    final_equity_delta: number | null;
    raw_curve_min: number | null;
    raw_curve_max: number | null;
    equity_curve_min: number | null;
    equity_curve_max: number | null;
    raw_points: number;
    display_points: number;
    final_point_appended: boolean;
    reconciliation_status: string;
  };
  charts?: {
    equity_curve?: any[];
    drawdown_curve?: any[];
    monthly_returns?: any[];
    pnl_by_symbol?: any[];
    pnl_by_regime?: any[];
    score_bucket_performance?: any[];
    holding_time_performance?: any[];
    fee_pressure?: any[];
    trade_distribution?: any[];
  };
  availability?: Record<string, boolean>;
  error?: string;
};


export type BacktestPagedRowsResponse = {
  ok: boolean;
  run_id?: number;
  exit_legs?: any[];
  trades?: any[];
  positions?: any[];
  position_events?: any[];
  logs?: any[];
  rows?: any[];
  total?: number;
  count?: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
  error?: string;
};

export type BacktestResultBundleResponse = {
  ok: boolean;
  run_id?: number;
  run?: any;
  metrics?: any;
  positions?: any;
  exit_legs?: any;
  position_events?: any;
  trades?: any;
  equity_curve?: any;
  logs?: any;
  error?: string;
};
