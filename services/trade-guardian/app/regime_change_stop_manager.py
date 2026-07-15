"""
Phase 6 Step 9 — Regime-change stop manager.

Wraps regime_change_stop_policy with Trade Guardian data access and existing
stop repricing helpers.
"""

from __future__ import annotations

from typing import Any

from adaptive_stop_manager import find_stop_loss_order
from orders import reprice_protective_order
from position_stop_updates import update_position_stop_loss
from positions import get_open_position
from regime_change_stop_policy import (
    REGIME_CHANGE_STOP_POLICY_VERSION,
    build_regime_change_stop_policy_contract,
    evaluate_regime_change_stop_adjustment,
)


def evaluate_regime_change_stop_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    entry_regime: str,
    current_regime: str,
    min_profit_r: float = 0.4,
    breakeven_buffer_pct: float = 0.0015,
    already_triggered: bool = False,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {
            "ok": False,
            "error": "open_position_not_found",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
        }

    decision = evaluate_regime_change_stop_adjustment(
        position=position,
        current_price=float(current_price),
        entry_regime=entry_regime,
        current_regime=current_regime,
        min_profit_r=min_profit_r,
        breakeven_buffer_pct=breakeven_buffer_pct,
        already_triggered=already_triggered,
    )

    return {
        "ok": bool(decision.get("ok", False)),
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position_id": int(position["position_id"]),
        "decision": decision,
    }


def apply_regime_change_stop_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    entry_regime: str,
    current_regime: str,
    min_profit_r: float = 0.4,
    breakeven_buffer_pct: float = 0.0015,
    already_triggered: bool = False,
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

    decision = evaluate_regime_change_stop_adjustment(
        position=position,
        current_price=float(current_price),
        entry_regime=entry_regime,
        current_regime=current_regime,
        min_profit_r=min_profit_r,
        breakeven_buffer_pct=breakeven_buffer_pct,
        already_triggered=already_triggered,
    )

    if decision.get("action") != "MOVE_STOP_TO_BREAKEVEN_BUFFER":
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
            "action": "DRY_RUN_REGIME_CHANGE_STOP_REPRICE",
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
            "error": "regime_change_stop_order_reprice_failed",
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
            "error": "regime_change_position_stop_update_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "stop_order_id": int(stop_order["order_id"]),
            "order_update": order_update,
            "decision": decision,
        }

    return {
        "ok": True,
        "action": "REGIME_CHANGE_STOP_REPRICED",
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


def build_regime_change_stop_manager_contract() -> dict[str, Any]:
    return {
        "regime_change_stop_policy_version": REGIME_CHANGE_STOP_POLICY_VERSION,
        "policy": build_regime_change_stop_policy_contract(),
        "manager_role": "evaluate and optionally reprice stop to breakeven plus buffer",
        "routes_to_wire_later": [
            "POST /position/evaluate-regime-change-stop",
            "POST /position/manage-regime-change-stop",
        ],
    }
