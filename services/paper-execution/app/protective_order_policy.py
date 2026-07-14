"""
Phase 6 Step 5 — Protective order lifecycle parity.

This module formalizes the expected protective-order set for every open paper
position:

- one stop_loss order
- one tp1 order
- one tp2 order
- one tp3 order
- v1 close split defaults: 50 / 30 / 20
- exit side is opposite of position side
- protective orders are reduce-only where supported
- maintenance trigger priority remains conservative: SL before TP1 before TP2 before TP3

It does not implement adaptive stop/breakeven behavior. That starts later in
Phase 6.
"""

from __future__ import annotations

from typing import Any

PROTECTIVE_ORDER_POLICY_VERSION = "phase6_step5_protective_order_lifecycle"

PROTECTIVE_ROLES = ("stop_loss", "tp1", "tp2", "tp3")
TP_CLOSE_DEFAULTS = {
    "tp1": 50.0,
    "tp2": 30.0,
    "tp3": 20.0,
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_role(value: Any) -> str:
    return str(value or "").lower()


def normalize_side(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    return "unknown"


def opposite_order_side(position_side: str) -> str:
    return "sell" if normalize_side(position_side) == "long" else "buy"


def normalize_order_status(value: Any) -> str:
    return str(value or "").lower()


def is_working_order(order: dict[str, Any]) -> bool:
    return normalize_order_status(order.get("status")) in {
        "created",
        "submitted",
        "acknowledged",
        "open",
        "partially_filled",
        "cancel_pending",
        "pending_entry",
        "resting",
        "partially_filled",
    }


def order_price_for_role(order: dict[str, Any], role: str) -> float | None:
    role = normalize_role(role)
    keys = {
        "stop_loss": ("stop_loss", "requested_price", "entry_price"),
        "tp1": ("tp1", "requested_price", "entry_price"),
        "tp2": ("tp2", "requested_price", "entry_price"),
        "tp3": ("tp3", "requested_price", "entry_price"),
    }.get(role, ("requested_price", "entry_price"))

    for key in keys:
        value = order.get(key)
        if value is not None:
            return safe_float(value)
    return None


def group_protective_orders(orders: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for order in orders or []:
        role = normalize_role(order.get("role"))
        if role in PROTECTIVE_ROLES and role not in result:
            result[role] = order
    return result


def expected_tp_sizes(original_size: float) -> dict[str, float]:
    original_size = safe_float(original_size)
    tp1_size = round(original_size * (TP_CLOSE_DEFAULTS["tp1"] / 100.0), 8)
    tp2_size = round(original_size * (TP_CLOSE_DEFAULTS["tp2"] / 100.0), 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)
    return {
        "tp1": tp1_size,
        "tp2": tp2_size,
        "tp3": tp3_size,
    }


def validate_protective_order_set(
    *,
    position: dict[str, Any],
    protective_orders: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    roles = group_protective_orders(protective_orders)
    missing_roles = [role for role in PROTECTIVE_ROLES if role not in roles]
    duplicate_roles = []

    role_counts = {}
    for order in protective_orders or []:
        role = normalize_role(order.get("role"))
        if role in PROTECTIVE_ROLES:
            role_counts[role] = role_counts.get(role, 0) + 1
    duplicate_roles = [role for role, count in role_counts.items() if count > 1]

    position_side = normalize_side(position.get("side") or position.get("position_side"))
    expected_side = opposite_order_side(position_side)
    side_mismatches = []

    for role, order in roles.items():
        order_side = str(order.get("side") or "").lower()
        # Paper API sometimes reports order side as normalized long/short in
        # fetch_all_open_orders. Only flag explicit buy/sell mismatches here.
        if order_side in ("buy", "sell") and order_side != expected_side:
            side_mismatches.append(role)

    missing_prices = [
        role
        for role, order in roles.items()
        if order_price_for_role(order, role) is None
    ]

    non_working_roles = [
        role
        for role, order in roles.items()
        if not is_working_order(order)
    ]

    original_size = safe_float(
        position.get("original_size", position.get("size", position.get("remaining_size", 0.0)))
    )

    expected_sizes = expected_tp_sizes(original_size)
    actual_sizes = {
        role: safe_float(roles.get(role, {}).get("requested_size"))
        for role in ("tp1", "tp2", "tp3")
        if role in roles
    }

    reason_codes: list[str] = []
    if missing_roles:
        reason_codes.append("PROTECTIVE_ORDERS_MISSING_ROLES")
    if duplicate_roles:
        reason_codes.append("PROTECTIVE_ORDERS_DUPLICATE_ROLES")
    if side_mismatches:
        reason_codes.append("PROTECTIVE_ORDERS_SIDE_MISMATCH")
    if missing_prices:
        reason_codes.append("PROTECTIVE_ORDERS_MISSING_PRICES")
    if non_working_roles:
        reason_codes.append("PROTECTIVE_ORDERS_NOT_WORKING")

    return {
        "ok": not reason_codes,
        "protective_order_policy_version": PROTECTIVE_ORDER_POLICY_VERSION,
        "required_roles": list(PROTECTIVE_ROLES),
        "missing_roles": missing_roles,
        "duplicate_roles": duplicate_roles,
        "side_mismatches": side_mismatches,
        "missing_prices": missing_prices,
        "non_working_roles": non_working_roles,
        "expected_exit_side": expected_side,
        "expected_tp_close_percents": TP_CLOSE_DEFAULTS,
        "expected_tp_sizes": expected_sizes,
        "actual_tp_sizes": actual_sizes,
        "reason_codes": reason_codes,
        "orders_by_role": roles,
    }


def should_trigger_for_order(
    *,
    role: str,
    side: str,
    low: float,
    high: float,
    price: float | None,
) -> bool:
    if price is None:
        return False

    side = normalize_side(side)

    if role == "stop_loss":
        if side == "long":
            return low <= price
        if side == "short":
            return high >= price

    if role in ("tp1", "tp2", "tp3"):
        if side == "long":
            return high >= price
        if side == "short":
            return low <= price

    return False


def select_protective_trigger_from_candle(
    *,
    position: dict[str, Any],
    orders_by_role: dict[str, dict[str, Any]],
    candle: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Conservative same-candle priority:
        SL -> TP1 -> TP2 -> TP3

    This matches the existing paper execution ambiguity rule and keeps this
    step behavior-preserving.
    """
    side = normalize_side(position.get("side") or position.get("position_side"))
    low = safe_float(candle.get("low"))
    high = safe_float(candle.get("high"))

    for role, execution_type in (
        ("stop_loss", "STOP_LOSS"),
        ("tp1", "TP1"),
        ("tp2", "TP2"),
        ("tp3", "TP3"),
    ):
        order = orders_by_role.get(role)
        if order is None:
            continue

        price = order_price_for_role(order, role)
        if should_trigger_for_order(
            role=role,
            side=side,
            low=low,
            high=high,
            price=price,
        ):
            return {
                "execution_type": execution_type,
                "trigger_price": price,
                "trigger_order": order,
                "trigger_role": role,
                "trigger_source": "candle",
                "candle": {
                    "low": low,
                    "high": high,
                    "timestamp": candle.get("timestamp") or candle.get("open_time") or candle.get("ts"),
                },
            }

    return None


def build_protective_order_policy_contract() -> dict[str, Any]:
    return {
        "protective_order_policy_version": PROTECTIVE_ORDER_POLICY_VERSION,
        "required_roles": list(PROTECTIVE_ROLES),
        "tp_close_defaults": TP_CLOSE_DEFAULTS,
        "same_candle_priority": ["stop_loss", "tp1", "tp2", "tp3"],
        "owner_of_protective_orders": "trade_guardian",
        "paper_execution_role": "simulate fills against Trade Guardian protective orders",
        "not_in_scope": [
            "adaptive stop loss",
            "breakeven stop movement",
            "near-TP reversal protection",
            "regime-change stop movement",
            "partial fills",
        ],
    }
