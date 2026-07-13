from config import (
    APP_ENV,
    MTM_AUTO_REFRESH_ENABLED,
    MTM_AUTO_REFRESH_INTERVAL_SECONDS,
    STRICT_SCORE_THRESHOLD,
    MAX_RISK_PCT,
    MAX_LEVERAGE,
    MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE,
    LIMIT_FEE_PCT,
    MARKET_FEE_PCT,
    MARKET_SLIPPAGE_PCT,
    SCHEDULER_BASE_URL,
)
from http_client import get_json
from symbol_config import load_symbol_universe_config
from time_utils import iso_now


def get_bootstrap_configuration():
    errors = []

    scheduler_health, scheduler_status, scheduler_error = get_json(
        f"{SCHEDULER_BASE_URL}/health",
        timeout=10,
    )
    if scheduler_error or scheduler_status != 200:
        errors.append({
            "source": "scheduler_health",
            "error": scheduler_error or scheduler_health,
        })
        scheduler_health = None

    symbol_config = load_symbol_universe_config()
    if not symbol_config.get("ok", False):
        errors.append({
            "source": "symbol_universe",
            "error": symbol_config,
        })

    enabled_symbols = symbol_config.get("enabled_symbols", []) if symbol_config.get("ok") else []
    symbol_universe = symbol_config.get("symbols", []) if symbol_config.get("ok") else []

    return {
        "ok": len(errors) == 0,
        "generated_at": iso_now(),
        "environment": APP_ENV,
        "settings": {
            "auto_loop_enabled": scheduler_health.get("auto_loop_enabled", False) if scheduler_health else False,
            "loop_interval_seconds": scheduler_health.get("loop_interval_seconds", 300) if scheduler_health else 300,
            "pending_entry_loop_interval_seconds": scheduler_health.get("pending_entry_loop_interval_seconds", 60) if scheduler_health else 60,
            "pending_entry_max_attempts": scheduler_health.get("pending_entry_max_attempts", 15) if scheduler_health else 15,
            "pending_entries_count": scheduler_health.get("pending_entries_count", 0) if scheduler_health else 0,
            "pending_entries": scheduler_health.get("pending_entries", []) if scheduler_health else [],
            "last_pending_entry_loop_at": scheduler_health.get("last_pending_entry_loop_at") if scheduler_health else None,
            "last_pending_entry_loop_processed": scheduler_health.get("last_pending_entry_loop_processed", 0) if scheduler_health else 0,
            "last_pending_entry_loop_fills": scheduler_health.get("last_pending_entry_loop_fills", 0) if scheduler_health else 0,
            "last_pending_entry_loop_pending": scheduler_health.get("last_pending_entry_loop_pending", 0) if scheduler_health else 0,
            "last_pending_entry_loop_cancelled": scheduler_health.get("last_pending_entry_loop_cancelled", 0) if scheduler_health else 0,
            "last_pending_entry_loop_blocked": scheduler_health.get("last_pending_entry_loop_blocked", 0) if scheduler_health else 0,
            "last_pending_entry_loop_errors": scheduler_health.get("last_pending_entry_loop_errors", 0) if scheduler_health else 0,
            "mtm_auto_refresh_enabled": MTM_AUTO_REFRESH_ENABLED,
            "mtm_auto_refresh_interval_seconds": MTM_AUTO_REFRESH_INTERVAL_SECONDS,
            "enabled_symbols": enabled_symbols,
            "symbol_universe": symbol_universe,
            "strict_score_threshold": STRICT_SCORE_THRESHOLD,
            "max_risk_pct": MAX_RISK_PCT,
            "max_leverage": MAX_LEVERAGE,
            "min_notional_pct_of_max_deployable": MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE,
            "limit_fee_pct": LIMIT_FEE_PCT,
            "market_fee_pct": MARKET_FEE_PCT,
            "market_slippage_pct": MARKET_SLIPPAGE_PCT,
        },
        "editability": {
            "auto_loop_enabled": "live",
            "enabled_symbols": "live",
            "symbol_universe": "live",
            "loop_interval_seconds": "read_only",
            "pending_entry_loop_interval_seconds": "read_only",
            "pending_entry_max_attempts": "read_only",
            "pending_entries_count": "live",
            "pending_entries": "live",
            "mtm_auto_refresh_enabled": "read_only",
            "mtm_auto_refresh_interval_seconds": "read_only",
            "strict_score_threshold": "read_only",
            "max_risk_pct": "read_only",
            "max_leverage": "read_only",
            "min_notional_pct_of_max_deployable": "read_only",
            "limit_fee_pct": "read_only",
            "market_fee_pct": "read_only",
            "market_slippage_pct": "read_only",
        },
        "sources": {
            "auto_loop_enabled": "scheduler_runtime",
            "loop_interval_seconds": "scheduler_runtime",
            "pending_entry_loop_interval_seconds": "scheduler_runtime",
            "pending_entry_max_attempts": "scheduler_runtime",
            "pending_entries_count": "scheduler_runtime",
            "pending_entries": "scheduler_runtime",
            "mtm_auto_refresh_enabled": "trade_guardian_env",
            "mtm_auto_refresh_interval_seconds": "trade_guardian_env",
            "enabled_symbols": "symbol_universe_json",
            "symbol_universe": "symbol_universe_json",
            "strict_score_threshold": "strategy_engine_env",
            "max_risk_pct": "risk_engine_env",
            "max_leverage": "risk_engine_env",
            "min_notional_pct_of_max_deployable": "risk_engine_env",
            "limit_fee_pct": "paper_execution_env",
            "market_fee_pct": "paper_execution_env",
            "market_slippage_pct": "paper_execution_env",
        },
        "errors": errors,
    }
