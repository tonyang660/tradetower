export type OpenPosition = {
  position_id?: number;
  symbol: string;
  side: "long" | "short" | string;
  entry_price?: number | null;
  current_price?: number | null;
  remaining_size?: number | null;
  original_size?: number | null;
  leverage?: number | null;
  notional?: number | null;
  margin_used?: number | null;
  unrealized_pnl?: number | null;
  fees_paid?: number | null;
  opened_at?: string | null;
  status?: string | null;

  stop_loss?: number | null;
  tp1?: number | null;
  tp2?: number | null;
  tp3?: number | null;
};

export type OpenPositionsResponse = {
  ok: boolean;
  account_id: number;
  count: number;
  items: OpenPosition[];
  account_status?: {
    equity?: number;
    cash_balance?: number;
    realized_pnl?: number;
    unrealized_pnl?: number;
    open_positions_count?: number;
  };
  pricing_errors?: string[];
};

export type RecentClosedPosition = {
  trade_id: number;
  symbol: string;
  direction: "long" | "short" | string;
  entry_price?: number | null;
  exit_price?: number | null;
  size?: number | null;
  leverage?: number | null;
  notional: number;
  realized_pnl: number;
  fees_paid: number;
  pnl_pct: number;
  win_loss: "WIN" | "LOSS" | "BREAKEVEN";
  opened_at?: string | null;
  closed_at?: string | null;
};

export type RecentClosedPositionsResponse = {
  ok: boolean;
  account_id: number;
  count: number;
  items: RecentClosedPosition[];
};

export type ExposureRibbonSegment = {
  symbol: string;
  side: "long" | "short";
  value: number;
  pnl: number;
};

export type PositionsAnalytics = {
  open_positions: number;
  total_notional: number;
  total_margin_used: number;
  total_open_pnl: number;
  total_open_pnl_pct_on_margin: number;
  long_exposure_notional: number;
  short_exposure_notional: number;
  long_exposure_pct: number;
  short_exposure_pct: number;
  biggest_winner_symbol: string | null;
  biggest_winner_pnl: number | null;
  biggest_loser_symbol: string | null;
  biggest_loser_pnl: number | null;
};

export type PositionsOrdersViewModel = {
  openPositions: OpenPosition[];
  recentClosed: RecentClosedPosition[];
  analytics: PositionsAnalytics;
  exposureSegments: ExposureRibbonSegment[];
};

export type WorkingOrder = {
  order_id: string;
  account_id?: number;
  symbol: string;
  side: "long" | "short" | string;
  order_type: string;
  role?: string;
  entry_price?: number | null;
  requested_size?: number | null;
  stop_loss?: number | null;
  tp1?: number | null;
  tp2?: number | null;
  tp3?: number | null;
  status: string;
  linked_position_id?: number | null;
  submitted_at?: string | null;
  updated_at?: string | null;
};

export type OpenOrdersResponse = {
  ok: boolean;
  account_id: number;
  count: number;
  items: WorkingOrder[];
};