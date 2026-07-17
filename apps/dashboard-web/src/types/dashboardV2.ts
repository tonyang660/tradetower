export type DashboardV2Error = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type DashboardV2LatestEquity = {
  recorded_at?: string | null;
  cash_balance?: number | null;
  equity?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  fees_paid_total?: number | null;
  trading_enabled?: boolean;
  manual_halt?: boolean;
  daily_kill_switch?: boolean;
  weekly_kill_switch?: boolean;
};

export type DashboardV2PerformanceSummary = {
  positions_total?: number;
  positions_open?: number;
  positions_closed?: number;
  wins?: number;
  losses?: number;
  breakeven?: number;
  position_win_rate?: number;
  gross_realized_pnl?: number;
  fees_paid?: number;
  net_realized_pnl?: number;
  fee_to_gross_realized_ratio?: number | null;
  expectancy_net_pnl?: number;
  profit_factor?: number | null;
  average_realized_r?: number | null;
  average_win_r?: number | null;
  average_loss_r?: number | null;
  by_exit_reason?: Record<string, number>;
};

export type DashboardV2DrawdownSummary = {
  start_equity?: number | null;
  end_equity?: number | null;
  equity_change_pct?: number;
  max_drawdown_value?: number;
  max_drawdown_pct?: number;
};

export type DashboardV2CostBreakdown = {
  fees_paid?: number;
  fee_to_gross_realized_ratio?: number | null;
  average_slippage_bps?: number | null;
  spread_cost?: number | null;
  spread_note?: string;
  funding_cost?: number | null;
  funding_note?: string;
};

export type DashboardV2StrategySummary = {
  rows?: number;
  trade_candidates?: number;
  risk_approved?: number;
  guardian_allowed?: number;
  paper_submitted?: number;
  filled?: number;
  trade_candidate_rate?: number;
  risk_approval_rate?: number;
  guardian_allow_rate?: number;
  paper_submit_rate?: number;
  fill_rate?: number;
  average_best_strategy_score?: number | null;
  average_candidate_score?: number | null;
};

export type DashboardV2TpSummary = {
  total_positions?: number;
  tp1_hits?: number;
  tp2_hits?: number;
  tp3_hits?: number;
  tp1_hit_rate?: number;
  tp2_hit_rate?: number;
  tp3_hit_rate?: number;
  tp1_to_tp2_continuation_rate?: number;
  tp2_to_tp3_continuation_rate?: number;
};

export type DashboardV2StopSummary = {
  events?: number;
  reprices?: number;
  noops?: number;
  errors?: number;
  reprice_rate?: number;
  noop_rate?: number;
  average_stop_improvement?: number | null;
  total_stop_improvement?: number;
  by_module?: Record<string, unknown>;
  by_reason?: Record<string, number>;
  by_symbol?: Record<string, unknown>;
};

export type DashboardV2LiveBlock = {
  latest_cycle?: Record<string, any> | null;
  open_positions?: Array<Record<string, any>>;
  open_positions_count?: number;
  open_orders?: Array<Record<string, any>>;
  open_orders_count?: number;
};

export type DashboardV2Overview = {
  ok: boolean;
  partial: boolean;
  dashboard_aggregation_v2_version: string;
  account_id: number;
  generated_at: string;
  performance_summary: DashboardV2PerformanceSummary | null;
  latest_equity: DashboardV2LatestEquity | null;
  drawdown_summary: DashboardV2DrawdownSummary | null;
  cost_breakdown: DashboardV2CostBreakdown | null;
  strategy_summary: DashboardV2StrategySummary | null;
  tp_summary: DashboardV2TpSummary | null;
  stop_summary: DashboardV2StopSummary | null;
  live: DashboardV2LiveBlock;
  errors: DashboardV2Error[];
};
