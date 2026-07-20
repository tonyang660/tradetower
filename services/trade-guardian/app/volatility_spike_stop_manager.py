"""
Phase 7.6b — Volatility-spike stop manager.
"""

from __future__ import annotations

from typing import Any

from orders import activate_adaptive_sl2_split_for_position
from positions import get_open_position
from volatility_spike_stop_policy import (
    VOLATILITY_SPIKE_STOP_POLICY_VERSION,
    build_volatility_spike_stop_policy_contract,
    evaluate_volatility_spike_stop_adjustment,
)


def evaluate_volatility_spike_stop_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    entry_atr: float,
    current_atr: float,
    min_profit_r: float = 0.4,
    spike_multiplier: float = 1.6,
    breakeven_buffer_pct: float = 0.0015,
    already_triggered: bool = False,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {"ok": False, "error": "open_position_not_found", "account_id": int(account_id), "symbol": str(symbol).upper()}

    decision = evaluate_volatility_spike_stop_adjustment(
        position=position,
        current_price=float(current_price),
        entry_atr=float(entry_atr),
        current_atr=float(current_atr),
        min_profit_r=min_profit_r,
        spike_multiplier=spike_multiplier,
        breakeven_buffer_pct=breakeven_buffer_pct,
        already_triggered=already_triggered,
    )
    return {"ok": bool(decision.get("ok", False)), "account_id": int(account_id), "symbol": str(symbol).upper(), "position_id": int(position["position_id"]), "decision": decision}


def apply_volatility_spike_stop_for_position(
    *,
    account_id: int,
    symbol: str,
    current_price: float,
    entry_atr: float,
    current_atr: float,
    min_profit_r: float = 0.4,
    spike_multiplier: float = 1.6,
    breakeven_buffer_pct: float = 0.0015,
    already_triggered: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    position = get_open_position(int(account_id), str(symbol).upper())
    if position is None:
        return {"ok": False, "error": "open_position_not_found", "account_id": int(account_id), "symbol": str(symbol).upper()}

    decision = evaluate_volatility_spike_stop_adjustment(
        position=position,
        current_price=float(current_price),
        entry_atr=float(entry_atr),
        current_atr=float(current_atr),
        min_profit_r=min_profit_r,
        spike_multiplier=spike_multiplier,
        breakeven_buffer_pct=breakeven_buffer_pct,
        already_triggered=already_triggered,
    )

    if decision.get("action") != "ACTIVATE_DEFENSIVE_SL2":
        return {
            "ok": True,
            "action": decision.get("action", "NO_ACTION"),
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "decision": decision,
            "reason_codes": [decision.get("reason_code")],
        }

    if dry_run:
        return {
            "ok": True,
            "action": "DRY_RUN_VOLATILITY_SPIKE_SL2_SPLIT",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": int(position["position_id"]),
            "sl2_price": decision["proposed_stop"],
            "decision": decision,
        }

    split_update = activate_adaptive_sl2_split_for_position(
        account_id=int(account_id),
        position_id=int(position["position_id"]),
        symbol=str(symbol).upper(),
        position_side=str(position["side"]).lower(),
        remaining_size=float(position["remaining_size"]),
        sl2_price=float(decision["proposed_stop"]),
        current_sl1_price=decision["current_stop"],
        reason_code=decision["reason_code"],
    )

    if not split_update.get("ok"):
        return {
            "ok": False,
            "error": "volatility_spike_adaptive_sl2_split_failed",
            "account_id": int(account_id),
            "symbol": str(symbol).upper(),
            "position_id": position["position_id"],
            "decision": decision,
            "split_update": split_update,
        }

    return {
        "ok": True,
        "action": "VOLATILITY_SPIKE_SL2_SPLIT_ACTIVATED",
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "position_id": position["position_id"],
        "sl2_price": decision["proposed_stop"],
        "reason_code": decision["reason_code"],
        "decision": decision,
        "split_update": split_update,
    }


def build_volatility_spike_stop_manager_contract() -> dict[str, Any]:
    return {
        "volatility_spike_stop_policy_version": VOLATILITY_SPIKE_STOP_POLICY_VERSION,
        "policy": build_volatility_spike_stop_policy_contract(),
        "manager_role": "evaluate ATR spike and optionally create defensive SL2 at breakeven buffer",
        "routes": [
            "POST /position/evaluate-volatility-spike-stop",
            "POST /position/manage-volatility-spike-stop",
        ],
    }
