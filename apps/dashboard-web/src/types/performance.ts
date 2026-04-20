export type PerformanceSummary = {
  gross_pnl: number;
  net_pnl: number;
  total_fees_paid: number;
  equity_change_pct: number;
  max_drawdown_pct: number;
  max_drawdown_value: number;
  total_trades: number;
  win_rate: number;
  expectancy: number;
  profit_factor: number | null;
  average_win: number;
  average_loss: number;
  average_rr: number | null;
  sharpe_ratio: number | null;
  best_trade: number;
  worst_trade: number;
  wins: number;
  losses: number;
};

export type EquityPoint = {
  recorded_at: string;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
};

export type DrawdownPoint = {
  recorded_at: string;
  equity: number;
  peak_equity: number;
  drawdown_value: number;
  drawdown_pct: number;
};

export type DirectionalBreakdownSide = {
  trades: number;
  pnl: number;
  win_rate: number;
  expectancy: number;
};

export type DirectionalBreakdown = {
  long: DirectionalBreakdownSide;
  short: DirectionalBreakdownSide;
};

export type HourlyPerformanceItem = {
  hour: number;
  pnl: number;
  trades: number;
  win_rate: number;
};

export type WeekdayPerformanceItem = {
  weekday: string;
  pnl: number;
  trades: number;
  win_rate: number;
};

export type SessionPerformanceItem = {
  session: string;
  pnl: number;
  trades: number;
  win_rate: number;
};

export type CalendarDayItem = {
  date: string;
  pnl: number;
  trades: number;
  win_rate: number;
};

export type MonthlySummary = {
  month: string;
  pnl: number;
  pnl_pct: number;
  winning_days: number;
  losing_days: number;
  flat_days: number;
  best_day: number | null;
  worst_day: number | null;
} | null;

export type PerformanceBootstrapResponse = {
  ok: boolean;
  account_id: number;
  generated_at: string;
  summary: PerformanceSummary | null;
  equity_curve: EquityPoint[];
  drawdown_curve: DrawdownPoint[];
  directional_breakdown: DirectionalBreakdown | null;
  hourly_performance: HourlyPerformanceItem[];
  weekday_performance: WeekdayPerformanceItem[];
  session_performance: SessionPerformanceItem[];
  calendar_days: CalendarDayItem[];
  monthly_summary: MonthlySummary;
  errors: Array<Record<string, unknown>>;
};