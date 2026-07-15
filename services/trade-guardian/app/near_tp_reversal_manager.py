"""
Phase 6 Step 8 — Near-TP reversal manager.

This wraps near_tp_reversal_policy with Trade Guardian data access and stop
repricing helpers.

It is intentionally separate from main.py so it can be wired into routes/loops
without replacing the entire Trade Guardian server file.
"""

from __future__ import annotations

from typing import Any

from adaptive_stop_manager import find_stop_loss_order
from near_tp_reversal_policy import (
    NEAR_TP_REVERSAL_POLICY_VERSION,
    build_near_tp_reversal_policy_contract,
    evaluate_near_tp_reversal,
)
from orders import reprice_protective_order
from position_stop_updates import update_position_stop_loss
from positions import get_open_position


def evaluate_near_tp_reversal_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    previous_best_price: float | None = None,
    near_tp_progress_threshold: float = 0.92,
    pullback_threshold_pct: float = 0.005,
    breakeven_buffer_pct: float = 0.0,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {
            "ok": False,
            "error": "open_position_not_found",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
        }

    decision = evaluate_near_tp_reversal(
        position=position,
        current_price=float(current_price),
        previous_best_price=previous_best_price,
        near_tp_progress_threshold=near_tp_progress_threshold,
        pullback_threshold_pct=pullback_threshold_pct,
        breakeven_buffer_pct=breakeven_buffer_pct,
    )

    return {
        "ok": bool(decision.get("ok", False)),
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position_id": int(position["position_id"]),
        "decision": decision,
    }


def apply_near_tp_reversal_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    previous_best_price: float | None = None,
    near_tp_progress_threshold: float = 0.92,
    pullback_threshold_pct: float = 0.005,
    breakeven_buffer_pct: float = 0.0,
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

    decision = evaluate_near_tp_reversal(
        position=position,
        current_price=float(current_price),
        previous_best_price=previous_best_price,
        near_tp_progress_threshold=near_tp_progress_threshold,
        pullback_threshold_pct=pullback_threshold_pct,
        breakeven_buffer_pct=breakeven_buffer_pct,
    )

    if not decision.get("ok", False):
        return {
            "ok": False,
            "error": decision.get("error", "near_tp_reversal_evaluation_failed"),
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "decision": decision,
        }

    if decision.get("action") != "MOVE_STOP_TO_BREAKEVEN":
        return {
            "ok": True,
            "action": decision.get("action", "NO_ACTION"),
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "decision": decision,
            "reason_codes": [decision.get("reason_code")],
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
            "position_id": int(position["position_id"]),
            "decision": decision,
        }

    if dry_run:
        return {
            "ok": True,
            "action": "DRY_RUN_NEAR_TP_STOP_REPRICE",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
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
            "error": "near_tp_stop_order_reprice_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
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
            "error": "near_tp_position_stop_update_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "stop_order_id": int(stop_order["order_id"]),
            "order_update": order_update,
            "decision": decision,
        }

    return {
        "ok": True,
        "action": "NEAR_TP_STOP_REPRICED_TO_BREAKEVEN",
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position_id": int(position["position_id"]),
        "stop_order_id": int(stop_order["order_id"]),
        "old_stop": decision["current_stop"],
        "new_stop": decision["proposed_stop"],
        "reason_code": decision["reason_code"],
        "decision": decision,
        "order_update": order_update,
        "position_update": position_update,
    }


def build_near_tp_reversal_manager_contract() -> dict[str, Any]:
    return {
        "near_tp_reversal_policy_version": NEAR_TP_REVERSAL_POLICY_VERSION,
        "policy": build_near_tp_reversal_policy_contract(),
        "manager_role": "evaluate and optionally reprice stop to breakeven",
        "routes_to_wire_later": [
            "POST /position/evaluate-near-tp-reversal",
            "POST /position/manage-near-tp-reversal",
        ],
    }
