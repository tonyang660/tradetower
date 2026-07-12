"""
Phase 4 Step 1 — Strategy Signal v2 contract.

This module is contract-only. It locks Strategy Engine's v2 output before
porting v1 logic into the runtime implementation.

Strategy Engine must not execute trades directly. It emits signal proposals for
Risk Engine and Trade Guardian to evaluate.
"""

STRATEGY_SIGNAL_SCHEMA_VERSION = "strategy_signal_v2"
STRATEGY_ENGINE_VERSION = "v2"
STRATEGY_ENGINE_CONTRACT_VERSION = "phase4_step1"
V1_PARITY_MODE = "v1_full_port_first"
V1_BENCHMARK_REPO = "tonyang660/crypto-signal-bot"

DECISIONS = {
    "no_trade": {
        "meaning": "Do not send to Risk Engine.",
        "legacy_decision": "no_trade",
    },
    "observe": {
        "meaning": "Worth logging/observing, but do not send to Risk Engine.",
        "legacy_decision": "observe",
    },
    "trade_candidate": {
        "meaning": "Strategy-approved candidate; send to Risk Engine, not execution.",
        "legacy_decision": "trade",
    },
}

DECISION_SIDES = ["long", "short", "neutral"]

STRATEGY_TYPES = {
    "trend_following": {
        "v1_regime_strategy": "Trend-Following",
        "route_when": ["Uptrend", "Downtrend"],
    },
    "mean_reversion": {
        "v1_regime_strategy": "Mean-Reversion",
        "route_when": ["Sideways"],
    },
    "none": {
        "v1_regime_strategy": "unknown",
        "route_when": [],
    },
}

V1_TREND_WEIGHTS = {
    "htf_alignment": 25,
    "momentum": 20,
    "entry_location": 20,
    "break_of_structure": 15,
    "rsi_quality": 12,
    "volatility": 8,
}

V1_MEAN_REVERSION_WEIGHTS = {
    "range_confirmation": 20,
    "breakout_safety": 15,
    "reversal_pattern": 20,
    "entry_extremity": 20,
    "rsi_divergence": 15,
    "low_volatility": 10,
}

V1_THRESHOLD_POLICY = {
    "normal_trade_threshold": 70,
    "drawdown_trade_threshold": 85,
    "hot_streak_trade_threshold": 65,
    "btc_trade_threshold": 80,
    "observe_threshold_default": 50,
    "notes": [
        "Drawdown and hot-streak state require account/evaluator context and may remain inactive until supplied.",
        "BTC macro score adjustments must affect only new candidate threshold/risk policy downstream.",
    ],
}

REQUIRED_MARKET_SNAPSHOT_FIELDS = {
    "schema_version": "market_snapshot_v2",
    "timeframes": ["5m", "15m", "4h"],
    "optional_context_timeframes": ["1h"],
    "required_blocks": [
        "indicators",
        "structure",
        "volatility",
        "regime_inputs",
        "price_action",
    ],
    "top_level_blocks": [
        "data_quality",
        "multi_timeframe_context",
    ],
}

PROPOSED_TRADE_FIELDS = [
    "entry_order_type",
    "entry_price",
    "stop_loss",
    "take_profits",
    "risk_per_unit",
    "invalidation_reference",
]

RUNTIME_POLICY = {
    "strategy_engine_does_not_execute": True,
    "strategy_engine_does_not_size_position": True,
    "strategy_engine_does_not_override_guardian": True,
    "risk_engine_owns_position_size": True,
    "trade_guardian_owns_final_safety_gate": True,
    "candidate_filter_is_prescreener_only": True,
}


def build_strategy_signal_contract() -> dict:
    return {
        "schema_version": STRATEGY_SIGNAL_SCHEMA_VERSION,
        "strategy_engine_version": STRATEGY_ENGINE_VERSION,
        "contract_version": STRATEGY_ENGINE_CONTRACT_VERSION,
        "v1_parity_mode": V1_PARITY_MODE,
        "v1_benchmark_repo": V1_BENCHMARK_REPO,
        "decisions": DECISIONS,
        "decision_sides": DECISION_SIDES,
        "strategy_types": STRATEGY_TYPES,
        "v1_trend_weights": V1_TREND_WEIGHTS,
        "v1_mean_reversion_weights": V1_MEAN_REVERSION_WEIGHTS,
        "v1_threshold_policy": V1_THRESHOLD_POLICY,
        "required_market_snapshot_fields": REQUIRED_MARKET_SNAPSHOT_FIELDS,
        "proposed_trade_fields": PROPOSED_TRADE_FIELDS,
        "runtime_policy": RUNTIME_POLICY,
    }


def build_no_trade_signal(
    symbol: str,
    reason: str,
    reason_tags: list[str] | None = None,
    snapshot_refs: dict | None = None,
) -> dict:
    return {
        "ok": True,
        "schema_version": STRATEGY_SIGNAL_SCHEMA_VERSION,
        "strategy_engine_version": STRATEGY_ENGINE_VERSION,
        "contract_version": STRATEGY_ENGINE_CONTRACT_VERSION,
        "v1_parity_mode": V1_PARITY_MODE,
        "symbol": str(symbol).upper(),
        "decision": "no_trade",
        "legacy_decision": "no_trade",
        "decision_side": "neutral",
        "selected_strategy": "none",
        "regime": "unknown",
        "regime_strategy": "unknown",
        "score": 0.0,
        "score_thresholds": {
            "trade_minimum_required": V1_THRESHOLD_POLICY["normal_trade_threshold"],
            "observe_minimum_required": V1_THRESHOLD_POLICY["observe_threshold_default"],
        },
        "entry_validation": {
            "valid": False,
            "direction": "neutral",
            "strategy_type": "none",
            "reason": reason,
            "failed_conditions": reason_tags or [reason],
        },
        "score_breakdown": {},
        "reason_tags": reason_tags or [reason],
        "proposed_trade": None,
        "snapshot_refs": snapshot_refs or {},
        "candidate_filter_context": None,
    }
