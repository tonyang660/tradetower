import type { ConfigurationSettings } from "../types/configuration";

export function prettySeconds(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function strictnessLabel(value: number) {
  if (value >= 85) return "Very Strict";
  if (value >= 75) return "Strict";
  if (value >= 65) return "Balanced";
  return "Permissive";
}

export function normalizeSymbol(value: string) {
  return value.trim().toUpperCase();
}

export function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  return a.every((value, index) => value === b[index]);
}

export function settingsEqual(
  original: ConfigurationSettings | null,
  current: ConfigurationSettings | null
) {
  if (!original || !current) return false;

  return (
    original.auto_loop_enabled === current.auto_loop_enabled &&
    original.loop_interval_seconds === current.loop_interval_seconds &&
    original.mtm_auto_refresh_enabled === current.mtm_auto_refresh_enabled &&
    original.mtm_auto_refresh_interval_seconds === current.mtm_auto_refresh_interval_seconds &&
    arraysEqual(original.enabled_symbols, current.enabled_symbols) &&
    original.strict_score_threshold === current.strict_score_threshold &&
    original.max_risk_pct === current.max_risk_pct &&
    original.max_leverage === current.max_leverage &&
    original.min_notional_pct_of_max_deployable === current.min_notional_pct_of_max_deployable &&
    original.limit_fee_pct === current.limit_fee_pct &&
    original.market_fee_pct === current.market_fee_pct &&
    original.market_slippage_pct === current.market_slippage_pct
  );
}