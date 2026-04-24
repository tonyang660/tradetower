export type BootstrapOverview = {
  ok: boolean;
  account_id: number;
  generated_at: string;
  market_banner: {
    current_utc_time: string;
    active_sessions?: string[];
    overlap_count?: number;
    is_weekend?: boolean;
    session_rows?: Array<{
      name: string;
      open_hour_utc: number;
      close_hour_utc: number;
      is_active: boolean;
    }>;
    next_session: {
      name: string;
      opens_at_utc: string;
      seconds_until_open: number;
    } | null;
  };
  trading_banner: {
    trading_disabled: boolean;
    reason_codes: string[];
    message: string;
    maintenance_remains_active: boolean;
  };
  scheduler_health?: {
    auto_loop_enabled?: boolean;
    loop_interval_seconds?: number;
  };
  overview: {
    account_status: {
      account_name: string;
      equity: number;
      cash_balance: number;
      realized_pnl: number;
      unrealized_pnl: number;
      fees_paid_total?: number;
      trading_enabled: boolean;
      open_positions_count: number;
      manual_halt: boolean;
      daily_kill_switch: boolean;
      weekly_kill_switch: boolean;
      daily_basis_equity?: number;
      weekly_basis_equity?: number;
      daily_loss_limit_pct?: number;
      weekly_loss_limit_pct?: number;
    };
    equity_series: { recorded_at: string; equity: number }[];
    open_positions: Array<Record<string, unknown>>;
    recent_positions: Array<Record<string, unknown>>;
    micro_metrics: {
      daily_pnl: number;
      daily_completed_trades: number;
      daily_wins: number;
      daily_losses: number;
      daily_win_rate: number;
      open_positions_count: number;
    };
    latest_cycle: {
      cycle_id: string;
      started_at: string;
      completed_at: string | null;
      summary: Record<string, any>;
    } | null;
  };
  performance_summary: {
    performance: {
      completed_trades: number;
      net_realized_pnl: number;
      average_trade_pnl: number;
      wins: number;
      losses: number;
      win_rate: number;
      best_trade: number;
      worst_trade: number;
      fees_paid_total: number;
    };
  };
  latest_cycle: {
    cycle: {
      cycle_id: string;
      started_at: string;
      completed_at: string | null;
      summary: Record<string, any>;
    } | null;
  };
  decision_funnel: {
    funnel: {
      decision_rows: number;
      candidate_filter_seen: number;
      no_trade: number;
      risk_approved: number;
      guardian_allowed: number;
      paper_submitted: number;
      filled: number;
    };
  };
  errors: Array<Record<string, unknown>>;
};