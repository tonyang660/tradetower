"""
Phase 5 Step 9 — BTC macro / market context risk adjustment.

Minimal scope:
- Risk Engine does not calculate BTC macro regime.
- Risk Engine only consumes upstream context, especially position_size_mult.
- The multiplier applies only to new-entry risk amount before sizing.
- Existing positions are never resized or closed by this policy.
"""

from __future__ import annotations

from typing import Any

BTC_MACRO_POLICY_VERSION = "phase5_step9_btc_macro_risk_adjustment"

DEFAULT_POSITION_SIZE_MULT = 1.0
MIN_POSITION_SIZE_MULT = 0.0
MAX_POSITION_SIZE_MULT = 2.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def extract_btc_macro_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}

    candidates = [
        payload.get("btc_macro_policy"),
        payload.get("btc_macro_context"),
        payload.get("market_context", {}).get("btc_macro_policy")
        if isinstance(payload.get("market_context"), dict)
        else None,
        payload.get("mtf_context", {}).get("btc_macro_policy")
        if isinstance(payload.get("mtf_context"), dict)
        else None,
        payload.get("strategy_signal", {}).get("btc_macro_policy")
        if isinstance(payload.get("strategy_signal"), dict)
        else None,
    ]

    proposed_trade = payload.get("proposed_trade")
    if isinstance(proposed_trade, dict):
        candidates.extend([
            proposed_trade.get("btc_macro_policy"),
            proposed_trade.get("btc_macro_context"),
        ])

    for candidate in candidates:
        if isinstance(candidate, dict):
            return dict(candidate)

    # Also support flat fields from older backtest/live glue.
    flat_keys = {
        "position_size_mult",
        "btc_position_mult",
        "score_threshold_adj",
        "btc_threshold_adj",
        "max_signals_adj",
        "btc_max_signals_adj",
        "regime",
        "bias",
        "reason",
    }
    if any(key in payload for key in flat_keys):
        return {
            "position_size_mult": payload.get("position_size_mult", payload.get("btc_position_mult")),
            "score_threshold_adj": payload.get("score_threshold_adj", payload.get("btc_threshold_adj")),
            "max_signals_adj": payload.get("max_signals_adj", payload.get("btc_max_signals_adj")),
            "regime": payload.get("regime"),
            "bias": payload.get("bias"),
            "reason": payload.get("reason"),
            "source": "flat_payload_fields",
        }

    return {}


def normalize_position_size_multiplier(context: dict[str, Any] | None) -> float:
    context = context or {}

    raw_value = (
        context.get("position_size_mult")
        if context.get("position_size_mult") is not None
        else context.get("btc_position_mult")
    )

    if raw_value is None:
        return DEFAULT_POSITION_SIZE_MULT

    # Conservative by design: BTC macro can reduce risk or leave it unchanged,
    # and can increase new-entry risk up to the configured maximum for favorable BTC regimes.
    return clamp(
        safe_float(raw_value, DEFAULT_POSITION_SIZE_MULT),
        MIN_POSITION_SIZE_MULT,
        MAX_POSITION_SIZE_MULT,
    )


def evaluate_btc_macro_risk_adjustment(
    *,
    payload: dict[str, Any] | None,
    base_risk_amount: float,
) -> dict[str, Any]:
    context = extract_btc_macro_context(payload)
    multiplier = normalize_position_size_multiplier(context)

    base_risk_amount = safe_float(base_risk_amount)
    adjusted_risk_amount = base_risk_amount * multiplier

    reason_codes: list[str] = []
    if multiplier < 1.0:
        reason_codes.append("BTC_MACRO_POSITION_SIZE_REDUCED")
    elif multiplier == 0.0:
        reason_codes.append("BTC_MACRO_NEW_ENTRIES_DISABLED")

    return {
        "ok": True,
        "btc_macro_policy_version": BTC_MACRO_POLICY_VERSION,
        "source_context": context,
        "position_size_mult": multiplier,
        "base_risk_amount": round(base_risk_amount, 8),
        "adjusted_risk_amount": round(adjusted_risk_amount, 8),
        "score_threshold_adj": context.get("score_threshold_adj", context.get("btc_threshold_adj")),
        "max_signals_adj": context.get("max_signals_adj", context.get("btc_max_signals_adj")),
        "reason_codes": reason_codes,
        "applies_to": "new_entries_only",
        "does_not": [
            "resize_existing_positions",
            "close_existing_positions",
            "override_guardian_kill_switches",
            "increase_risk_above_configured_maximum",
        ],
    }


def build_btc_macro_policy_contract() -> dict[str, Any]:
    return {
        "btc_macro_policy_version": BTC_MACRO_POLICY_VERSION,
        "owner_of_macro_detection": "feature_factory_or_strategy_engine",
        "risk_engine_behavior": (
            "Risk Engine consumes upstream BTC macro context and applies "
            "position_size_mult to new-entry risk amount only."
        ),
        "recognized_fields": [
            "btc_macro_policy.position_size_mult",
            "btc_macro_context.position_size_mult",
            "market_context.btc_macro_policy.position_size_mult",
            "mtf_context.btc_macro_policy.position_size_mult",
            "position_size_mult",
            "btc_position_mult",
            "score_threshold_adj",
            "max_signals_adj",
        ],
        "multiplier_bounds": {
            "min": MIN_POSITION_SIZE_MULT,
            "max": MAX_POSITION_SIZE_MULT,
        },
        "not_in_scope": [
            "BTC macro calculation",
            "existing position resize",
            "existing position close",
            "kill switch behavior",
            "score threshold enforcement",
        ],
    }
