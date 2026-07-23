export type BacktestRunConfig = {
  strategy_name: string;
  strategy_version?: string;
  symbols: string[];
  timeframes: string[];
  cycle_timeframe: string;
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
