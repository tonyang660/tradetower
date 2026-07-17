export type DashboardV2Error = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type DashboardV2Overview = {
  ok: boolean;
  partial: boolean;
  dashboard_aggregation_v2_version: string;
  account_id: number;
  generated_at: string;
  performance_summary?: Record<string, any> | null;
  latest_equity?: Record<string, any> | null;
  drawdown_summary?: Record<string, any> | null;
  cost_breakdown?: Record<string, any> | null;
  strategy_summary?: Record<string, any> | null;
  tp_summary?: Record<string, any> | null;
  stop_summary?: Record<string, any> | null;
  live?: Record<string, any>;
  errors: DashboardV2Error[];
};
