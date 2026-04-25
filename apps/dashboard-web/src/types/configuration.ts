export type ConfigurationEditability = "live" | "read_only";

export type ConfigurationSettings = {
  auto_loop_enabled: boolean;
  loop_interval_seconds: number;
  mtm_auto_refresh_enabled: boolean;
  mtm_auto_refresh_interval_seconds: number;
  enabled_symbols: string[];
  strict_score_threshold: number;
  max_risk_pct: number;
  max_leverage: number;
  min_notional_pct_of_max_deployable: number;
  limit_fee_pct: number;
  market_fee_pct: number;
  market_slippage_pct: number;
  pending_entry_loop_interval_seconds: number;
  pending_entry_max_attempts: number;
  pending_entries_count: number;
  pending_entries: Array<{
    symbol: string;
    attempt_number: number;
    updated_at?: string;
    order_type?: string;
    position_side?: string;
    entry_price?: number;
  }>;
};

export type ConfigurationBootstrapResponse = {
  ok: boolean;
  generated_at: string;
  environment: string;
  settings: ConfigurationSettings;
  editability: Record<keyof ConfigurationSettings, ConfigurationEditability>;
  sources: Record<keyof ConfigurationSettings, string>;
  errors: Array<Record<string, unknown>>;
};

export type ValidateSymbolResponse = {
  ok: boolean;
  valid: boolean;
  symbol: string;
  provider?: string;
  message?: string;
  error?: string;
};

export type SaveSymbolUniverseResponse = {
  ok: boolean;
  saved?: boolean;
  enabled_symbols?: string[];
  count?: number;
  path?: string;
  error?: string;
  validation_errors?: Array<{
    symbol: string;
    error: string;
  }>;
};

export type SetAutoLoopResponse = {
  ok: boolean;
  auto_loop_enabled?: boolean;
  scheduler_response?: Record<string, unknown>;
  error?: string;
};