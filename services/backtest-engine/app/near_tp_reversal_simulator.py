from __future__ import annotations

from typing import Any

from production_runtime import load_production_module


BACKTEST_NEAR_TP_ADAPTER_VERSION = "backtest_production_near_tp_reversal_adapter_v1"


def evaluate_near_tp_reversal(
    *,
    position: dict[str, Any],
    current_price: float,
    candle_high: float,
    candle_low: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    policy = load_production_module("trade_guardian", "near_tp_reversal_policy")
    side = str(position.get("side") or "").lower()
    previous_best = position.get("near_tp_best_price")
    favorable_price = float(candle_high if side == "long" else candle_low)
    best = policy.favorable_best_price(
        side=side,
        entry_price=float(position["entry"]),
        current_price=favorable_price,
        previous_best_price=previous_best,
    )
    position["near_tp_best_price"] = best

    next_level = policy.next_unhit_tp({
        "tp1_hit": "tp1" in (position.get("partial_tp_filled") or []),
        "tp2_hit": "tp2" in (position.get("partial_tp_filled") or []),
        "tp3_hit": "tp3" in (position.get("partial_tp_filled") or []),
    })
    target = float(position.get(next_level, 0.0)) if next_level else 0.0
    target_touched = bool(
        target > 0 and (
            (side == "long" and float(candle_high) >= target)
            or (side == "short" and float(candle_low) <= target)
        )
    )
    if target_touched:
        return {
            "ok": True,
            "action": "NO_ACTION",
            "reason_code": "NEXT_TP_TOUCHED_THIS_CANDLE",
            "best_price": best,
            "next_tp_level": next_level,
            "next_tp_price": target,
            "target_touched": True,
            "backtest_adapter_version": BACKTEST_NEAR_TP_ADAPTER_VERSION,
        }

    production_position = {
        "side": side,
        "entry_price": float(position["entry"]),
        "stop_loss": float(position["stop"]),
        "tp1_price": float(position["tp1"]),
        "tp2_price": float(position["tp2"]),
        "tp3_price": float(position["tp3"]),
        "tp1_hit": "tp1" in (position.get("partial_tp_filled") or []),
        "tp2_hit": "tp2" in (position.get("partial_tp_filled") or []),
        "tp3_hit": "tp3" in (position.get("partial_tp_filled") or []),
    }
    decision = policy.evaluate_near_tp_reversal(
        position=production_position,
        current_price=float(current_price),
        previous_best_price=best,
        near_tp_progress_threshold=float(config.get("near_tp_progress_threshold", 0.92)),
        pullback_threshold_pct=float(config.get("near_tp_pullback_threshold_pct", 0.005)),
        breakeven_buffer_pct=float(config.get("near_tp_breakeven_buffer_pct", 0.0)),
    )
    decision["backtest_adapter_version"] = BACKTEST_NEAR_TP_ADAPTER_VERSION
    return decision
