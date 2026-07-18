"""
Phase 5 Step 10 — Risk Approval payload v2.

This module is a response-shape layer only. It does not calculate risk,
leverage, portfolio exposure, correlation, drawdown, or BTC macro context.

It standardizes approved and rejected Risk Engine outputs so downstream services
can consume one stable contract.
"""

from __future__ import annotations

from typing import Any

RISK_APPROVAL_PAYLOAD_VERSION = "phase5_step10_risk_approval_payload_v2"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def make_json_safe(value: Any, *, max_depth: int = 8, _depth: int = 0, _seen: set[int] | None = None) -> Any:
    """
    Defensive serializer guard for Risk Engine responses.

    Prevents recursive / oversized context objects from crashing /plan with:
        maximum recursion depth exceeded

    Also removes raw strategy payload copies that are useful for local debugging
    but unsafe for API response contracts.
    """
    if _seen is None:
        _seen = set()

    if _depth > max_depth:
        return "[max_depth_exceeded]"

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        object_id = id(value)
        if object_id in _seen:
            return "[circular_reference]"

        _seen.add(object_id)
        result = {}

        for key, item in value.items():
            key = str(key)

            if key in {
                "raw_signal",
                "raw_payload",
                "raw_context",
                "raw_response",
                "traceback",
            }:
                continue

            result[key] = make_json_safe(
                item,
                max_depth=max_depth,
                _depth=_depth + 1,
                _seen=_seen,
            )

        _seen.remove(object_id)
        return result

    if isinstance(value, (list, tuple, set)):
        object_id = id(value)
        if object_id in _seen:
            return "[circular_reference]"

        _seen.add(object_id)
        result = [
            make_json_safe(
                item,
                max_depth=max_depth,
                _depth=_depth + 1,
                _seen=_seen,
            )
            for item in list(value)[:100]
        ]
        _seen.remove(object_id)
        return result

    return str(value)


def compact_context(context: dict[str, Any] | None) -> dict[str, Any]:
    safe = make_json_safe(context or {}, max_depth=8)
    return safe if isinstance(safe, dict) else {}

def build_risk_approval_payload_v2(
    *,
    account_id: int,
    symbol: str,
    position_side: str,
    entry_order_type: str,
    entry_price: float,
    stop_loss: float,
    tp_ladder: dict[str, Any],
    sizing: dict[str, Any],
    leverage_result: dict[str, Any],
    portfolio_result: dict[str, Any],
    correlation_result: dict[str, Any],
    weekly_drawdown_result: dict[str, Any],
    btc_macro_result: dict[str, Any],
    normalized_signal: dict[str, Any],
    risk_engine_version: str,
    risk_policy_version: str,
    runtime_version: str,
    leverage_policy_version: str,
    portfolio_policy_version: str,
    correlation_policy_version: str,
    weekly_drawdown_policy_version: str,
    btc_macro_policy_version: str,
    minimum_notional_required: float,
) -> dict[str, Any]:
    take_profits = tp_ladder["take_profits"]
    safe_normalized_signal = compact_context(normalized_signal)

    risk_context = {
        "dynamic_risk": sizing.get("dynamic_risk", {}),
        "risk_adjustment": sizing.get("risk_adjustment_context", {}),
        "weekly_drawdown": compact_context(weekly_drawdown_result),
        "btc_macro": compact_context(btc_macro_result),
        "leverage": {
            "candidates": leverage_result.get("candidates", []),
            "candidate_notes": leverage_result.get("candidate_notes", []),
            "leverage_rejections": leverage_result.get("leverage_rejections", []),
        },
        "portfolio": compact_context(portfolio_result),
        "correlation": compact_context(correlation_result),
        "strategy_signal": {
            "schema_version": safe_normalized_signal.get("schema_version"),
            "v2_decision": safe_normalized_signal.get("v2_decision"),
            "legacy_decision": safe_normalized_signal.get("legacy_decision"),
            "selected_strategy": safe_normalized_signal.get("selected_strategy"),
            "regime": safe_normalized_signal.get("regime"),
            "score": safe_normalized_signal.get("score"),
            "reason_tags": safe_normalized_signal.get("reason_tags", []),
        },
    }

    payload = {
        "ok": True,
        "approved": True,
        "risk_decision": "approved",
        "risk_approval_payload_version": RISK_APPROVAL_PAYLOAD_VERSION,
        "risk_engine_version": risk_engine_version,
        "risk_policy_version": risk_policy_version,
        "runtime_version": runtime_version,
        "policy_versions": {
            "risk_policy": risk_policy_version,
            "leverage_policy": leverage_policy_version,
            "portfolio_policy": portfolio_policy_version,
            "correlation_policy": correlation_policy_version,
            "weekly_drawdown_policy": weekly_drawdown_policy_version,
            "btc_macro_policy": btc_macro_policy_version,
        },
        "account_id": int(account_id),
        "symbol": str(symbol or "").upper(),
        "position_side": position_side,
        "entry_order_type": entry_order_type,
        "entry_price": round(safe_float(entry_price), 8),
        "stop_loss": round(safe_float(stop_loss), 8),
        "take_profits": take_profits,
        "tp1_price": round(safe_float(tp_ladder["tp1_price"]), 8),
        "tp2_price": round(safe_float(tp_ladder["tp2_price"]), 8),
        "tp3_price": round(safe_float(tp_ladder["tp3_price"]), 8),
        "tp1_close_percent": round(safe_float(tp_ladder["tp1_close_percent"]), 8),
        "tp2_close_percent": round(safe_float(tp_ladder["tp2_close_percent"]), 8),
        "tp3_close_percent": round(safe_float(tp_ladder["tp3_close_percent"]), 8),
        "tp1_ratio": round(safe_float(tp_ladder["tp1_ratio"]), 8),
        "tp2_ratio": round(safe_float(tp_ladder["tp2_ratio"]), 8),
        "tp3_ratio": round(safe_float(tp_ladder["tp3_ratio"]), 8),
        "tp_ladder_source": tp_ladder.get("source"),
        "risk_pct": sizing.get("risk_pct"),
        "base_risk_amount": sizing.get("base_risk_amount", sizing.get("risk_amount")),
        "risk_amount_multiplier": sizing.get("risk_amount_multiplier", 1.0),
        "risk_amount": sizing.get("risk_amount"),
        "stop_distance": sizing.get("stop_distance"),
        "size": sizing.get("size"),
        "notional": sizing.get("notional"),
        "leverage": round(safe_float(leverage_result["chosen_leverage"]), 8),
        "margin_required": round(safe_float(leverage_result["margin_required"]), 8),
        "minimum_notional_required": round(safe_float(minimum_notional_required), 8),
        "liquidation_price_estimate": round(safe_float(leverage_result["liquidation_price_estimate"]), 8),
        "liquidation_buffer_pct": round(safe_float(leverage_result["liquidation_buffer_pct"]), 6),
        "reason_codes": [],
        "risk_context": risk_context,

        # Backward-compatible top-level context fields for current dashboard /
        # scheduler diagnostics.
        "dynamic_risk": compact_context(sizing.get("dynamic_risk", {})),
        "weekly_drawdown_context": compact_context(weekly_drawdown_result),
        "btc_macro_context": compact_context(btc_macro_result),
        "leverage_context": compact_context({
            "candidates": leverage_result.get("candidates", []),
            "candidate_notes": leverage_result.get("candidate_notes", []),
            "leverage_rejections": leverage_result.get("leverage_rejections", []),
        }),
        "portfolio_context": compact_context(portfolio_result),
        "correlation_context": compact_context(correlation_result),
        "strategy_signal_context": compact_context(risk_context["strategy_signal"]),
    }

    return payload


def build_risk_rejection_payload_v2(
    *,
    symbol: str,
    reason_codes: list[str],
    context: dict[str, Any] | None,
    risk_engine_version: str,
    risk_policy_version: str,
    runtime_version: str,
    policy_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "approved": False,
        "risk_decision": "rejected",
        "risk_approval_payload_version": RISK_APPROVAL_PAYLOAD_VERSION,
        "risk_engine_version": risk_engine_version,
        "risk_policy_version": risk_policy_version,
        "runtime_version": runtime_version,
        "policy_versions": policy_versions or {},
        "symbol": str(symbol or "").upper(),
        "reason_codes": reason_codes,
        "risk_context": compact_context(context),
    }


def build_risk_approval_payload_contract() -> dict[str, Any]:
    return {
        "risk_approval_payload_version": RISK_APPROVAL_PAYLOAD_VERSION,
        "approved_payload_required_fields": [
            "ok",
            "approved",
            "risk_decision",
            "risk_approval_payload_version",
            "risk_engine_version",
            "risk_policy_version",
            "runtime_version",
            "policy_versions",
            "account_id",
            "symbol",
            "position_side",
            "entry_order_type",
            "entry_price",
            "stop_loss",
            "take_profits",
            "risk_pct",
            "base_risk_amount",
            "risk_amount_multiplier",
            "risk_amount",
            "stop_distance",
            "size",
            "notional",
            "leverage",
            "margin_required",
            "liquidation_price_estimate",
            "liquidation_buffer_pct",
            "reason_codes",
            "risk_context",
        ],
        "rejection_payload_required_fields": [
            "ok",
            "approved",
            "risk_decision",
            "risk_approval_payload_version",
            "risk_engine_version",
            "risk_policy_version",
            "runtime_version",
            "policy_versions",
            "symbol",
            "reason_codes",
            "risk_context",
        ],
        "backward_compatibility_fields": [
            "tp1_price",
            "tp2_price",
            "tp3_price",
            "tp1_close_percent",
            "tp2_close_percent",
            "tp3_close_percent",
            "dynamic_risk",
            "weekly_drawdown_context",
            "btc_macro_context",
            "leverage_context",
            "portfolio_context",
            "correlation_context",
            "strategy_signal_context",
        ],
    }
