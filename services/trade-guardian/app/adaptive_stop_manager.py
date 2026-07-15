"""
Phase 6 Step 7 — Trade Guardian adaptive stop manager.

This starts the v1 adaptive stop-loss behavior in the correct service:
Trade Guardian.

v1 parity implemented here:
- after TP1: move stop to 50% of original risk
- after TP2: move stop to breakeven / entry price

Not in this step:
- near-TP reversal early exits
- regime-change stop movement
- partial-protection split stop behavior
- ATR trailing beyond TP3
"""

from __future__ import annotations

from typing import Any

from orders import fetch_all_open_orders, reprice_protective_order
from positions import get_open_position
from position_stop_updates import update_position_stop_loss

ADAPTIVE_STOP_MANAGER_VERSION = "phase6_step7_adaptive_stop_manager"

STOP_MOVE_AFTER_TP1 = "tp1_half_risk"
STOP_MOVE_AFTER_TP2 = "tp2_breakeven"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_side(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    return "unknown"


def calculate_original_stop_from_risk(position: dict[str, Any]) -> float | None:
    """
    Reconstruct the original stop from entry/risk if available.

    Risk Engine sizes approximately as:
        risk_amount = abs(entry - stop) * size

    So:
        risk_per_unit = risk_amount / original_size
    """
    entry = safe_float(position.get("entry_price"))
    side = normalize_side(position.get("side"))
    original_size = safe_float(position.get("original_size", position.get("size", 0.0)))
    risk_amount = safe_float(position.get("risk_amount"))

    if entry <= 0 or original_size <= 0 or risk_amount <= 0:
        current_stop = position.get("stop_loss")
        return safe_float(current_stop) if current_stop is not None else None

    risk_per_unit = risk_amount / original_size

    if side == "long":
        return round(entry - risk_per_unit, 8)
    if side == "short":
        return round(entry + risk_per_unit, 8)

    return None


def calculate_tp1_half_risk_stop(position: dict[str, Any]) -> float | None:
    entry = safe_float(position.get("entry_price"))
    original_stop = calculate_original_stop_from_risk(position)
    side = normalize_side(position.get("side"))

    if original_stop is None or entry <= 0:
        return None

    if side == "long":
        return round(original_stop + ((entry - original_stop) * 0.5), 8)
    if side == "short":
        return round(original_stop - ((original_stop - entry) * 0.5), 8)

    return None


def calculate_tp2_breakeven_stop(position: dict[str, Any]) -> float | None:
    entry = safe_float(position.get("entry_price"))
    if entry <= 0:
        return None
    return round(entry, 8)


def is_stop_improvement(*, side: str, current_stop: float | None, proposed_stop: float | None) -> bool:
    if proposed_stop is None:
        return False

    if current_stop is None:
        return True

    side = normalize_side(side)
    current = safe_float(current_stop)
    proposed = safe_float(proposed_stop)

    if side == "long":
        return proposed > current
    if side == "short":
        return proposed < current

    return False


def choose_adaptive_stop_target(position: dict[str, Any]) -> dict[str, Any]:
    side = normalize_side(position.get("side"))
    current_stop = position.get("stop_loss")

    # TP2 has higher priority than TP1. Once TP2 is hit, breakeven should be
    # the minimum protection target.
    if bool(position.get("tp2_hit")):
        proposed_stop = calculate_tp2_breakeven_stop(position)
        action = STOP_MOVE_AFTER_TP2
        reason_code = "TP2_MOVE_STOP_TO_BREAKEVEN"
    elif bool(position.get("tp1_hit")):
        proposed_stop = calculate_tp1_half_risk_stop(position)
        action = STOP_MOVE_AFTER_TP1
        reason_code = "TP1_MOVE_STOP_TO_HALF_RISK"
    else:
        proposed_stop = None
        action = "none"
        reason_code = "NO_TP_HIT_FOR_ADAPTIVE_STOP"

    improvement = is_stop_improvement(
        side=side,
        current_stop=current_stop,
        proposed_stop=proposed_stop,
    )

    return {
        "adaptive_stop_manager_version": ADAPTIVE_STOP_MANAGER_VERSION,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "current_stop": safe_float(current_stop) if current_stop is not None else None,
        "proposed_stop": proposed_stop,
        "is_improvement": improvement,
        "tp1_hit": bool(position.get("tp1_hit")),
        "tp2_hit": bool(position.get("tp2_hit")),
        "tp3_hit": bool(position.get("tp3_hit")),
        "entry_price": safe_float(position.get("entry_price")),
        "original_stop_estimate": calculate_original_stop_from_risk(position),
    }


def find_stop_loss_order(
    *,
    account_id: int,
    position_id: int,
    symbol: str,
) -> dict[str, Any] | None:
    orders_payload = fetch_all_open_orders(int(account_id))
    items = orders_payload.get("items", []) if isinstance(orders_payload, dict) else []

    for order in items:
        if str(order.get("symbol", "")).upper() != str(symbol).upper():
            continue
        if str(order.get("role", "")).lower() != "stop_loss":
            continue
        if order.get("linked_position_id") is not None and int(order["linked_position_id"]) != int(position_id):
            continue
        return order

    return None


def evaluate_adaptive_stop_for_position(
    *,
    account_id: int,
    symbol: str,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {
            "ok": False,
            "error": "open_position_not_found",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
        }

    decision = choose_adaptive_stop_target(position)

    return {
        "ok": True,
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position": {
            "position_id": position["position_id"],
            "side": position["side"],
            "entry_price": position["entry_price"],
            "stop_loss": position.get("stop_loss"),
            "tp1_hit": position.get("tp1_hit"),
            "tp2_hit": position.get("tp2_hit"),
            "tp3_hit": position.get("tp3_hit"),
        },
        "decision": decision,
    }


def apply_adaptive_stop_for_position(
    *,
    account_id: int,
    symbol: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {
            "ok": False,
            "error": "open_position_not_found",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
        }

    decision = choose_adaptive_stop_target(position)

    if not decision["is_improvement"]:
        return {
            "ok": True,
            "action": "NO_STOP_REPRICE",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "decision": decision,
            "reason_codes": [decision["reason_code"]],
        }

    stop_order = find_stop_loss_order(
        account_id=int(account_id),
        position_id=int(position["position_id"]),
        symbol=str(symbol).upper(),
    )
    if stop_order is None:
        return {
            "ok": False,
            "error": "stop_loss_order_not_found",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "decision": decision,
        }

    if dry_run:
        return {
            "ok": True,
            "action": "DRY_RUN_STOP_REPRICE",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "stop_order_id": int(stop_order["order_id"]),
            "decision": decision,
        }

    order_update = reprice_protective_order(
        account_id=int(account_id),
        order_id=int(stop_order["order_id"]),
        new_price=float(decision["proposed_stop"]),
    )

    if order_update is None:
        return {
            "ok": False,
            "error": "stop_loss_order_reprice_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "stop_order_id": int(stop_order["order_id"]),
            "decision": decision,
        }

    position_update = update_position_stop_loss(
        account_id=int(account_id),
        position_id=int(position["position_id"]),
        new_stop_loss=float(decision["proposed_stop"]),
    )

    if position_update is None:
        return {
            "ok": False,
            "error": "position_stop_update_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "stop_order_id": int(stop_order["order_id"]),
            "order_update": order_update,
            "decision": decision,
        }

    return {
        "ok": True,
        "action": "STOP_REPRICED",
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position_id": position["position_id"],
        "stop_order_id": int(stop_order["order_id"]),
        "old_stop": decision["current_stop"],
        "new_stop": decision["proposed_stop"],
        "reason_code": decision["reason_code"],
        "decision": decision,
        "order_update": order_update,
        "position_update": position_update,
    }


def build_adaptive_stop_manager_contract() -> dict[str, Any]:
    return {
        "adaptive_stop_manager_version": ADAPTIVE_STOP_MANAGER_VERSION,
        "owner": "trade_guardian",
        "implemented_rules": {
            STOP_MOVE_AFTER_TP1: "after TP1, move SL to 50% of original risk",
            STOP_MOVE_AFTER_TP2: "after TP2, move SL to breakeven / entry price",
        },
        "safety_rules": [
            "never move a long stop downward",
            "never move a short stop upward",
            "do nothing when no TP has been hit",
            "do nothing when proposed stop is not more protective",
        ],
        "not_in_scope": [
            "near-TP reversal early exit",
            "regime-change stop movement",
            "partial-protection split stop behavior",
            "ATR trailing after TP3",
        ],
    }
