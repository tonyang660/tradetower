"""
Phase 3 Step 1 — MarketSnapshot v2 contract constants.

This module is intentionally contract-only. It does not change Feature Factory
runtime behavior by itself. Later Phase 3 steps should import these constants as
the implementation is moved toward v1 parity.
"""

MARKET_SNAPSHOT_SCHEMA_VERSION = "market_snapshot_v2"
MARKET_SNAPSHOT_CONTRACT_VERSION = "phase3_step1"
V1_BENCHMARK_REPO = "tonyang660/crypto-signal-bot"
V1_PARITY_MODE = "v1_parity_first"

TIMEFRAME_ROLES = {
    "entry": "5m",
    "primary": "15m",
    "higher_timeframe": "4h",
}

REQUIRED_INDICATORS = [
    "ema_fast_21",
    "ema_medium_50",
    "ema_slow_200",
    "macd_12_26_9",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "atr_sma_20",
    "rsi_14",
    "adx_14",
    "volume_sma_100",
]

TREND_SCORING_COMPONENTS = {
    "htf_alignment": 25,
    "momentum": 20,
    "entry_location": 20,
    "break_of_structure": 15,
    "rsi_quality": 12,
    "volatility": 8,
}

MEAN_REVERSION_SCORING_COMPONENTS = {
    "range_confirmation": 20,
    "breakout_safety": 15,
    "reversal_pattern": 20,
    "entry_extremity": 20,
    "rsi_divergence": 15,
    "low_volatility": 10,
}

REQUIRED_STRATEGY_INPUTS = [
    "trend_direction",
    "regime",
    "regime_strategy",
    "btc_macro_regime",
    "break_of_structure",
    "bos_quality",
    "mean_reversion_range",
    "range_position",
    "atr_ratio",
    "ema_slope_pct",
    "ema_spread_pct",
    "price_velocity_short",
    "price_velocity_medium",
    "strong_primary_trend",
    "rsi_context",
    "entry_distance_from_ema_atr",
]


def build_v1_parity_contract() -> dict:
    return {
        "benchmark_repo": V1_BENCHMARK_REPO,
        "mode": V1_PARITY_MODE,
        "behavior_policy": (
            "Prefer v1 behavior parity. Deviations require an explicit rationale "
            "and should improve robustness without silently changing the core edge."
        ),
        "required_timeframe_roles": TIMEFRAME_ROLES,
        "required_indicator_set": REQUIRED_INDICATORS,
        "required_strategy_inputs": REQUIRED_STRATEGY_INPUTS,
        "required_scoring_components": {
            "trend_following": TREND_SCORING_COMPONENTS,
            "mean_reversion": MEAN_REVERSION_SCORING_COMPONENTS,
        },
        "allowed_deviation_policy": (
            "Allowed deviations: provider-neutral symbol handling, data-quality "
            "guards, NaN-safety, explicit schemas, and clearer diagnostics. "
            "Not allowed without review: changing scoring weights, thresholds, "
            "entry conditions, risk sizing, TP/SL behavior, or cooldown behavior."
        ),
    }
