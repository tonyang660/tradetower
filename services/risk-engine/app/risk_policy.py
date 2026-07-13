"""
Phase 5 Steps 1-2 — Risk Engine v2 contract and v1 dynamic risk tiers.

This module is intentionally side-effect free. It defines the Risk Engine v2
contract shape and the v1 account-size dynamic risk model without changing the
runtime /plan endpoint yet.

Later Phase 5 steps should import this module from risk-engine/app/main.py.
"""

from __future__ import annotations

from typing import Any

RISK_ENGINE_VERSION = "risk_engine_v2"
RISK_POLICY_VERSION = "phase5_step1_2_v1_dynamic_risk_tiers"

# v1 account-size dynamic risk tiers.
# Each entry is: min_equity inclusive, max_equity exclusive, risk percent.
V1_DYNAMIC_RISK_TIERS = [
    {"min_equity": 0.0, "max_equity": 3000.0, "risk_pct": 1.0, "tier": "sub_3k"},
    {"min_equity": 3000.0, "max_equity": 5000.0, "risk_pct": 0.8, "tier": "3k_to_5k"},
    {"min_equity": 5000.0, "max_equity": 7000.0, "risk_pct": 0.7, "tier": "5k_to_7k"},
    {"min_equity": 7000.0, "max_equity": 10000.0, "risk_pct": 0.6, "tier": "7k_to_10k"},
    {"min_equity": 10000.0, "max_equity": 20000.0, "risk_pct": 0.5, "tier": "10k_to_20k"},
    {"min_equity": 20000.0, "max_equity": None, "risk_pct": 0.4, "tier": "20k_plus"},
]

V1_MAX_LEVERAGE = 15.0
V1_MAX_CORRELATED_SIGNALS = 2

RISK_DECISION_APPROVED = "approved"
RISK_DECISION_REJECTED = "rejected"

RISK_REASON_CODES = {
    "APPROVED": "Risk proposal approved.",
    "INVALID_STRATEGY_SIGNAL_SCHEMA": "Strategy Signal v2 schema is missing or invalid.",
    "NOT_A_TRADE_CANDIDATE": "Strategy signal is not a trade candidate.",
    "MISSING_POSITION_SIDE": "Missing long/short position side.",
    "INVALID_POSITION_SIDE": "Position side is not long or short.",
    "MISSING_ENTRY_PRICE": "Missing entry price.",
    "MISSING_STOP_LOSS": "Missing stop loss.",
    "MISSING_TAKE_PROFITS": "Missing take-profit ladder.",
    "INVALID_STOP_DISTANCE": "Stop distance is zero, negative, or invalid.",
    "SIZE_NON_POSITIVE": "Calculated position size is not positive.",
    "NOTIONAL_BELOW_MINIMUM": "Trade notional is below the useful minimum.",
    "MARGIN_EXCEEDS_AVAILABLE_CAPITAL": "Required margin exceeds available cash.",
    "LIQUIDATION_TOO_CLOSE_TO_STOP": "Estimated liquidation is too close to stop loss.",
    "NO_VALID_LEVERAGE_FOUND": "No leverage candidate satisfies margin and liquidation constraints.",
    "CORRELATION_GROUP_LIMIT_REACHED": "Correlation group exposure limit reached.",
    "DAILY_LOSS_LIMIT_REACHED": "Daily loss limit reached.",
    "WEEKLY_LOSS_LIMIT_REACHED": "Weekly loss limit reached.",
    "COOLDOWN_ACTIVE": "Risk cooldown is active.",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def select_dynamic_risk_tier(equity: float) -> dict[str, Any]:
    equity = safe_float(equity, 0.0)

    for tier in V1_DYNAMIC_RISK_TIERS:
        min_equity = safe_float(tier["min_equity"])
        max_equity = tier["max_equity"]
        if equity < min_equity:
            continue
        if max_equity is None or equity < safe_float(max_equity):
            return {
                "tier": tier["tier"],
                "equity": equity,
                "risk_pct": safe_float(tier["risk_pct"]),
                "min_equity": min_equity,
                "max_equity": max_equity,
                "risk_policy_version": RISK_POLICY_VERSION,
            }

    # Defensive fallback. The list above should always catch all non-negative
    # equity values.
    last = V1_DYNAMIC_RISK_TIERS[-1]
    return {
        "tier": last["tier"],
        "equity": equity,
        "risk_pct": safe_float(last["risk_pct"]),
        "min_equity": safe_float(last["min_equity"]),
        "max_equity": last["max_equity"],
        "risk_policy_version": RISK_POLICY_VERSION,
    }


def calculate_base_risk_amount(
    equity: float,
    max_risk_pct_ceiling: float | None = None,
) -> dict[str, Any]:
    tier = select_dynamic_risk_tier(equity)
    dynamic_risk_pct = safe_float(tier["risk_pct"])

    if max_risk_pct_ceiling is not None:
        risk_pct = min(dynamic_risk_pct, safe_float(max_risk_pct_ceiling, dynamic_risk_pct))
        ceiling_applied = risk_pct < dynamic_risk_pct
    else:
        risk_pct = dynamic_risk_pct
        ceiling_applied = False

    equity_value = safe_float(equity)
    risk_amount = equity_value * (risk_pct / 100.0)

    return {
        "risk_policy_version": RISK_POLICY_VERSION,
        "equity": equity_value,
        "dynamic_risk_tier": tier,
        "dynamic_risk_pct": dynamic_risk_pct,
        "max_risk_pct_ceiling": max_risk_pct_ceiling,
        "ceiling_applied": ceiling_applied,
        "risk_pct": risk_pct,
        "risk_amount": round(risk_amount, 8),
    }


def normalize_position_side(payload: dict[str, Any]) -> str | None:
    for key in ("position_side", "decision_side", "side"):
        value = payload.get(key)
        if value is None:
            continue
        value = str(value).lower()
        if value in ("long", "short"):
            return value
    return None


def extract_strategy_trade_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize Strategy Signal v2 or compatibility payload into a future Risk
    Engine v2 intake block. This does not approve or reject by itself.
    """
    proposed_trade = payload.get("proposed_trade") or {}
    take_profits = payload.get("take_profits") or proposed_trade.get("take_profits")

    return {
        "schema_version": payload.get("schema_version"),
        "symbol": str(payload.get("symbol") or "").upper(),
        "v2_decision": payload.get("v2_decision") or payload.get("decision"),
        "legacy_decision": payload.get("legacy_decision"),
        "position_side": normalize_position_side(payload),
        "selected_strategy": payload.get("selected_strategy"),
        "regime": payload.get("regime"),
        "score": payload.get("score") or payload.get("confidence"),
        "entry_order_type": payload.get("entry_order_type") or proposed_trade.get("entry_order_type"),
        "entry_price": payload.get("entry_price") or proposed_trade.get("entry_price"),
        "stop_loss": payload.get("stop_loss") or proposed_trade.get("stop_loss"),
        "take_profits": take_profits,
        "risk_per_unit": payload.get("risk_per_unit") or proposed_trade.get("risk_per_unit"),
        "reason_tags": payload.get("reason_tags", []),
        "raw_signal": payload,
    }


def build_rejection(
    symbol: str,
    reason_codes: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "approved": False,
        "risk_engine_version": RISK_ENGINE_VERSION,
        "risk_policy_version": RISK_POLICY_VERSION,
        "risk_decision": RISK_DECISION_REJECTED,
        "symbol": str(symbol or "").upper(),
        "reason_codes": reason_codes,
        "reason_details": {
            code: RISK_REASON_CODES.get(code, code)
            for code in reason_codes
        },
        "risk_context": context or {},
    }


def build_approval_skeleton(
    *,
    symbol: str,
    position_side: str,
    entry_order_type: str,
    entry_price: float,
    stop_loss: float,
    take_profits: dict[str, Any],
    risk_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Approval skeleton for later Phase 5 steps. Position sizing, leverage, margin,
    and liquidation details should be filled by runtime sizing/leverage steps.
    """
    return {
        "ok": True,
        "approved": True,
        "risk_engine_version": RISK_ENGINE_VERSION,
        "risk_policy_version": RISK_POLICY_VERSION,
        "risk_decision": RISK_DECISION_APPROVED,
        "symbol": str(symbol or "").upper(),
        "position_side": position_side,
        "entry_order_type": entry_order_type,
        "entry_price": safe_float(entry_price),
        "stop_loss": safe_float(stop_loss),
        "take_profits": take_profits,
        "reason_codes": [],
        "risk_context": risk_context or {},
    }


def build_risk_engine_v2_contract() -> dict[str, Any]:
    return {
        "risk_engine_version": RISK_ENGINE_VERSION,
        "risk_policy_version": RISK_POLICY_VERSION,
        "decision_values": [RISK_DECISION_APPROVED, RISK_DECISION_REJECTED],
        "approved_boolean_field": "approved",
        "v1_dynamic_risk_tiers": V1_DYNAMIC_RISK_TIERS,
        "v1_max_leverage": V1_MAX_LEVERAGE,
        "v1_max_correlated_signals": V1_MAX_CORRELATED_SIGNALS,
        "required_strategy_signal_fields": [
            "schema_version",
            "symbol",
            "v2_decision",
            "position_side",
            "entry_order_type",
            "entry_price",
            "stop_loss",
            "take_profits",
        ],
        "approved_payload_fields": [
            "ok",
            "approved",
            "risk_engine_version",
            "risk_policy_version",
            "symbol",
            "position_side",
            "entry_order_type",
            "entry_price",
            "stop_loss",
            "take_profits",
            "risk_pct",
            "risk_amount",
            "stop_distance",
            "size",
            "notional",
            "leverage",
            "margin_required",
            "liquidation_price_estimate",
            "liquidation_buffer_pct",
            "portfolio_context",
            "correlation_context",
            "drawdown_context",
            "reason_codes",
        ],
        "rejection_payload_fields": [
            "ok",
            "approved",
            "risk_engine_version",
            "risk_policy_version",
            "symbol",
            "reason_codes",
            "reason_details",
            "risk_context",
        ],
        "reason_codes": sorted(RISK_REASON_CODES.keys()),
        "runtime_status": "contract_and_dynamic_risk_module_only_not_wired_into_plan_endpoint_yet",
    }
